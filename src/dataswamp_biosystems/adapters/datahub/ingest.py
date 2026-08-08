"""Transmit an emitted DataHub export to a live catalogue.

The live path is strictly downstream of the offline one::

    bundle -> export-datahub -> emitted export -> ingest-datahub -> verify-ingestion

This module's input is an **emitted export directory**, never a bundle. It does
not regenerate metadata, reopen a generator, reinterpret a bundle or consult the
benchmark answer key. The emitted export is treated as the authoritative
statement of what the catalogue should hold, which is what makes the round-trip
claim meaningful: if ingestion could re-derive the payload, "the server matches
what we sent" would be comparing a computation against itself.

Transmission is **pure transport**. Nothing here synthesizes, enriches, rewrites
or remaps a proposal. Four things are checked before a byte leaves the process:

1. the export's files parse and the payload passes the offline validator;
2. every digest in ``export-manifest.json`` recomputes;
3. no ``(URN, aspect)`` pair appears twice;
4. the manifest's privilege flag agrees with the mode being ingested.

Every proposal is an ``UPSERT``, so ingestion is idempotent: running it twice
converges on one estate rather than producing a second copy.

No receipt file is written. It would be redundant — the emitted export *is* the
record of what was transmitted, by the contract above, and ``verify-ingestion``
reads it directly rather than trusting a log this command produced about itself.
A receipt would also be the one artefact in the project tempted to carry a wall
clock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataswamp_biosystems.adapters.datahub.client import (
    DEFAULT_BATCH_SIZE,
    DataHubClient,
    IngestBatch,
    build_batches,
)
from dataswamp_biosystems.adapters.datahub.errors import DataHubConfigError
from dataswamp_biosystems.adapters.datahub.export import (
    EXPORT_MANIFEST_NAME,
    MCPS_JSONL_NAME,
)
from dataswamp_biosystems.adapters.datahub.mapping import ExportMode
from dataswamp_biosystems.adapters.datahub.validate import validate_export
from dataswamp_biosystems.truth import serialize


@dataclass(frozen=True)
class LoadedExport:
    """A verified emitted export, ready to transmit or to compare against."""

    root: Path
    mode: ExportMode
    proposals: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]

    @property
    def privileged(self) -> bool:
        return bool(self.manifest.get("privileged", False))

    @property
    def payload_digest(self) -> str:
        """The digest of ``mcps.jsonl`` — the identity of this proposal set."""
        return str(self.manifest.get("files", {}).get(MCPS_JSONL_NAME, ""))

    def identity(self) -> dict[str, Any]:
        """Non-secret provenance identifying which benchmark this export came from."""
        bundle = self.manifest.get("bundle", {})
        return {
            "mode": self.mode.value,
            "privileged": self.privileged,
            "adapter_version": self.manifest.get("adapter_version", ""),
            "datahub_model_version": self.manifest.get("datahub_model_version", ""),
            "mcps_digest": self.payload_digest,
            "bundle_fingerprint": bundle.get("bundle_fingerprint", ""),
            "benchmark_release": bundle.get("benchmark_release", ""),
            "ground_truth_fingerprint": bundle.get("ground_truth_fingerprint", ""),
        }


@dataclass(frozen=True)
class IngestPlan:
    """What would be transmitted, computed with no network activity whatsoever.

    ``--dry-run`` produces one of these and reports it. Building a plan opens no
    socket and performs no connectivity or health check: a dry run that contacts
    a server is not a dry run, and a health probe is not part of this contract.
    """

    export: LoadedExport
    batches: tuple[IngestBatch, ...]

    @property
    def proposal_count(self) -> int:
        return sum(batch.size for batch in self.batches)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataHubConfigError(f"{path.name} is missing from the export directory") from exc
    except json.JSONDecodeError as exc:
        raise DataHubConfigError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DataHubConfigError(f"{path.name} is not a JSON object")
    return payload


def load_export(export_dir: Path | str) -> LoadedExport:
    """Read, digest-verify and validate an emitted DataHub export.

    Raises :class:`DataHubConfigError` on anything wrong with the export. A
    tampered payload is refused here, before any network activity: transmitting
    metadata that no longer matches the manifest it was published with would put
    unattributable content into somebody's catalogue.
    """
    root = Path(export_dir)
    if not root.is_dir():
        raise DataHubConfigError(f"{root} is not a directory")

    manifest = _read_json(root / EXPORT_MANIFEST_NAME)

    declared = manifest.get("files", {})
    if not isinstance(declared, dict) or not declared:
        raise DataHubConfigError(f"{EXPORT_MANIFEST_NAME} declares no files")
    for name in sorted(declared):
        path = root / name
        if not path.is_file():
            raise DataHubConfigError(f"{name} is declared in the manifest but missing")
        actual = serialize.digest(path.read_bytes())
        if actual != declared[name]:
            raise DataHubConfigError(
                f"{name} does not match its manifest digest — the export has been modified "
                f"since it was written (expected {declared[name]}, got {actual})"
            )

    mode_value = str(manifest.get("mode", ""))
    try:
        mode = ExportMode(mode_value)
    except ValueError as exc:
        raise DataHubConfigError(
            f"{EXPORT_MANIFEST_NAME} declares an unknown mode {mode_value!r}"
        ) from exc
    if bool(manifest.get("privileged", False)) is not (mode is ExportMode.TRUTH):
        raise DataHubConfigError(
            f"{EXPORT_MANIFEST_NAME} declares mode {mode_value!r} with "
            f"privileged={manifest.get('privileged')!r}, which contradict each other"
        )

    proposals: list[dict[str, Any]] = []
    text = (root / MCPS_JSONL_NAME).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DataHubConfigError(f"{MCPS_JSONL_NAME} line {number} is not valid JSON") from exc
        if not isinstance(record, dict):
            raise DataHubConfigError(f"{MCPS_JSONL_NAME} line {number} is not a JSON object")
        proposals.append(record)
    if not proposals:
        raise DataHubConfigError(f"{MCPS_JSONL_NAME} contains no proposals")

    problems = validate_export(proposals, mode)
    if problems:
        joined = "; ".join(problems[:5])
        raise DataHubConfigError(
            f"the export payload is invalid — {len(problems)} problem(s): {joined}"
        )

    seen: set[tuple[str, str]] = set()
    for record in proposals:
        key = (str(record.get("entityUrn")), str(record.get("aspectName")))
        if key in seen:  # pragma: no cover - validate_export already rejects this
            raise DataHubConfigError(f"duplicate proposal for {key[0]} aspect {key[1]}")
        seen.add(key)

    return LoadedExport(root=root, mode=mode, proposals=tuple(proposals), manifest=manifest)


def plan_ingestion(export: LoadedExport, batch_size: int = DEFAULT_BATCH_SIZE) -> IngestPlan:
    """Return the transmission plan for a verified export. Opens no socket."""
    return IngestPlan(export=export, batches=build_batches(list(export.proposals), batch_size))


def execute_ingestion(plan: IngestPlan, client: DataHubClient) -> int:
    """Transmit every batch in ``plan`` and return the number of proposals sent."""
    for batch in plan.batches:
        client.ingest_batch(batch)
    return plan.proposal_count


__all__ = [
    "LoadedExport",
    "IngestPlan",
    "load_export",
    "plan_ingestion",
    "execute_ingestion",
]
