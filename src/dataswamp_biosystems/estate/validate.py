"""Validate a generated estate against the truth graph, its own bytes, and disk.

``validate-files`` regenerates the estate's manifest from the recorded seed and
profile and confirms it is byte-identical to what is on disk (a determinism and
integrity tripwire), then checks every on-disk file: its checksum matches, its
path stays inside the estate, its asset exists in the truth graph, its
represented logical size is at least its physical size, and every placeholder
carries a complete, consistent sidecar. All problems are collected and raised
together.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from dataswamp_biosystems.estate.entities import FileManifestRecord, PlaceholderSidecar
from dataswamp_biosystems.estate.errors import (
    EstateConfigError,
    EstateIssueCollector,
    EstateIssueKind,
)
from dataswamp_biosystems.estate.generator import iter_records
from dataswamp_biosystems.estate.profiles import Profile
from dataswamp_biosystems.estate.writer import MANIFEST_NAME, SUMMARY_JSON_NAME
from dataswamp_biosystems.truth import serialize
from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.ids import is_slug


def read_estate_meta(estate_dir: Path) -> dict[str, object]:
    """Read the ``meta`` block from ``generation-summary.json``."""
    path = estate_dir / SUMMARY_JSON_NAME
    if not path.exists():
        raise EstateConfigError(f"no generation summary at {path}")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
        meta = summary["meta"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise EstateConfigError(f"could not read estate summary {path}: {exc}") from exc
    if not isinstance(meta, dict):
        raise EstateConfigError(f"malformed meta block in {path}")
    return meta


def load_manifest_records(estate_dir: Path) -> list[FileManifestRecord]:
    """Load and type-validate every row of ``file-manifest.jsonl``."""
    path = estate_dir / MANIFEST_NAME
    if not path.exists():
        raise EstateConfigError(f"no manifest at {path}")
    records: list[FileManifestRecord] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(FileManifestRecord.model_validate_json(line))
        except ValidationError as exc:
            raise EstateConfigError(f"invalid manifest row {line_no} in {path}: {exc}") from exc
    return records


def validate_estate(estate_dir: Path, graph: TruthGraph) -> None:
    """Validate the estate under ``estate_dir`` against ``graph`` and disk.

    ``graph`` must be the truth graph the estate was derived from (same seed).
    Raises :class:`EstateValidationError` on any problem.
    """
    estate_dir = Path(estate_dir)
    issues = EstateIssueCollector()

    meta = read_estate_meta(estate_dir)
    seed = int(str(meta["seed"]))
    profile = Profile(str(meta["profile"]))
    truth_seed = int(str(meta["truth_seed"]))
    if graph.meta.seed != truth_seed:
        issues.add(
            EstateIssueKind.CONSISTENCY,
            f"truth graph seed {graph.meta.seed} does not match estate truth_seed {truth_seed}",
        )

    on_disk = load_manifest_records(estate_dir)

    # Determinism/integrity tripwire: regenerated manifest bytes must match disk.
    regen = [record for _p, _c, record, _s in iter_records(graph, profile, seed)]
    if serialize.jsonl_bytes(regen) != serialize.jsonl_bytes(on_disk):
        issues.add(
            EstateIssueKind.CONSISTENCY,
            "on-disk manifest differs from a freshly regenerated manifest (drift)",
        )

    asset_ids = {a.id for a in graph.datasets} | {p.id for p in graph.data_products}
    seen: set[str] = set()
    for record in on_disk:
        _validate_record(estate_dir, record, asset_ids, seen, issues)

    issues.raise_if_any()


def _validate_record(
    estate_dir: Path,
    record: FileManifestRecord,
    asset_ids: set[str],
    seen: set[str],
    issues: EstateIssueCollector,
) -> None:
    if not is_slug(record.id):
        issues.add(
            EstateIssueKind.INVALID_ID, f"id {record.id!r} is not a slug", entity_id=record.id
        )
    if record.id in seen:
        issues.add(EstateIssueKind.DUPLICATE_ID, f"duplicate id {record.id!r}", entity_id=record.id)
    seen.add(record.id)

    if record.asset_id not in asset_ids:
        issues.add(
            EstateIssueKind.UNRESOLVED_ASSET,
            f"asset {record.asset_id!r} is not in the truth graph",
            entity_id=record.id,
            field="asset_id",
        )

    if record.logical_bytes < record.physical_bytes:
        issues.add(
            EstateIssueKind.SIZE,
            f"logical_bytes {record.logical_bytes} < physical_bytes {record.physical_bytes}",
            entity_id=record.id,
        )

    # Path safety and on-disk integrity.
    root = estate_dir.resolve()
    target = (root / record.relative_path).resolve()
    if root != target and root not in target.parents:
        issues.add(
            EstateIssueKind.PATH_ESCAPE,
            f"path {record.relative_path!r} escapes the estate directory",
            entity_id=record.id,
        )
        return
    if not target.exists():
        issues.add(
            EstateIssueKind.CONSISTENCY,
            f"manifest file {record.relative_path!r} is missing on disk",
            entity_id=record.id,
        )
        return
    actual = serialize.digest(target.read_bytes())
    if actual != record.checksum:
        issues.add(
            EstateIssueKind.CHECKSUM,
            f"checksum mismatch for {record.relative_path!r}",
            entity_id=record.id,
        )

    if record.is_placeholder:
        _validate_placeholder(target, record, issues)


def _validate_placeholder(
    stub_path: Path, record: FileManifestRecord, issues: EstateIssueCollector
) -> None:
    sidecar_path = stub_path.with_name(stub_path.name + ".json")
    if not sidecar_path.exists():
        issues.add(
            EstateIssueKind.PLACEHOLDER,
            f"placeholder {record.relative_path!r} has no sidecar",
            entity_id=record.id,
        )
        return
    try:
        sidecar = PlaceholderSidecar.model_validate_json(sidecar_path.read_bytes())
    except ValidationError as exc:
        issues.add(
            EstateIssueKind.PLACEHOLDER,
            f"placeholder sidecar for {record.id!r} is invalid: {exc}",
            entity_id=record.id,
        )
        return
    if sidecar.source_truth_asset_id != record.asset_id:
        issues.add(
            EstateIssueKind.PLACEHOLDER,
            f"sidecar asset {sidecar.source_truth_asset_id!r} != record asset {record.asset_id!r}",
            entity_id=record.id,
        )
    if sidecar.intended_format != record.file_format:
        issues.add(
            EstateIssueKind.PLACEHOLDER,
            f"sidecar intended_format {sidecar.intended_format!r} != {record.file_format!r}",
            entity_id=record.id,
        )


__all__ = [
    "read_estate_meta",
    "load_manifest_records",
    "validate_estate",
]
