"""Write a generated estate to disk atomically, safely, and within budget.

Output is staged in a temporary sibling directory and swapped into place with
directory renames, so a failed or over-budget run never leaves a
seemingly-complete estate and any previous estate is restored on failure
(mirroring :mod:`dataswamp_biosystems.truth.writer`).

Three safety invariants are enforced *while writing*, not merely checked after:
every file path is confirmed to resolve inside the output directory, the running
physical-byte total is kept under the profile's hard budget, and every file's
checksum is computed from the bytes actually written.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataswamp_biosystems.estate.entities import FileManifestRecord, PlaceholderSidecar
from dataswamp_biosystems.estate.errors import EstateIssue, EstateIssueKind, EstateValidationError
from dataswamp_biosystems.estate.generator import build_meta, iter_records
from dataswamp_biosystems.estate.profiles import Profile, profile_spec
from dataswamp_biosystems.truth import serialize
from dataswamp_biosystems.truth.graph import TruthGraph

MANIFEST_NAME = "file-manifest.jsonl"
SUMMARY_JSON_NAME = "generation-summary.json"
SUMMARY_MD_NAME = "summary.md"
FILES_DIRNAME = "files"


def _safe_join(root: Path, relative: str) -> Path:
    """Join ``relative`` under ``root``, refusing any path that escapes ``root``."""
    root = root.resolve()
    candidate = (root / relative).resolve()
    if root != candidate and root not in candidate.parents:
        raise EstateValidationError(
            [
                EstateIssue(
                    kind=EstateIssueKind.PATH_ESCAPE,
                    message=f"path {relative!r} resolves outside the output directory",
                )
            ]
        )
    return candidate


@dataclass
class _Accumulator:
    records: list[FileManifestRecord]
    total_physical: int
    total_logical: int


def _generate_into(tmp_root: Path, graph: TruthGraph, profile: Profile, seed: int) -> _Accumulator:
    """Materialize every planned file into ``tmp_root``, enforcing safety+budget."""
    budget = profile_spec(profile).budget_bytes
    acc = _Accumulator(records=[], total_physical=0, total_logical=0)

    for _plan, content, record, sidecar in iter_records(graph, profile, seed):
        acc.total_physical += len(content)
        if acc.total_physical > budget:
            raise EstateValidationError(
                [
                    EstateIssue(
                        kind=EstateIssueKind.BUDGET,
                        message=(
                            f"profile {profile.value!r} would write {acc.total_physical} bytes, "
                            f"exceeding the {budget}-byte budget"
                        ),
                    )
                ]
            )
        target = _safe_join(tmp_root, record.relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if sidecar is not None:
            _write_sidecar(target, sidecar)

        acc.records.append(record)
        acc.total_logical += record.logical_bytes

    return acc


def _write_sidecar(stub_path: Path, sidecar: PlaceholderSidecar) -> None:
    path = stub_path.with_name(stub_path.name + ".json")
    payload = sidecar.model_dump(mode="json")
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))


def build_summary(
    graph: TruthGraph, profile: Profile, seed: int, acc: _Accumulator
) -> dict[str, Any]:
    """Build the machine-readable ``generation-summary.json`` payload."""
    meta = build_meta(graph, profile, seed)
    by_format: dict[str, int] = {}
    by_role: dict[str, int] = {}
    by_group: dict[str, int] = {}
    assets: set[str] = set()
    placeholders = 0
    for record in acc.records:
        by_format[record.file_format] = by_format.get(record.file_format, 0) + 1
        by_role[record.file_role] = by_role.get(record.file_role, 0) + 1
        by_group[record.modality_group] = by_group.get(record.modality_group, 0) + 1
        assets.add(record.asset_id)
        if record.is_placeholder:
            placeholders += 1
    manifest_sha = serialize.digest(serialize.jsonl_bytes(acc.records))
    return {
        "meta": meta.model_dump(mode="json"),
        "counts": {
            "files": len(acc.records),
            "genuine": len(acc.records) - placeholders,
            "placeholders": placeholders,
            "assets": len(assets),
        },
        "formats_generated": sorted(by_format),
        "by_format": dict(sorted(by_format.items())),
        "by_role": dict(sorted(by_role.items())),
        "by_modality_group": dict(sorted(by_group.items())),
        "sizes": {
            "total_physical_bytes": acc.total_physical,
            "total_logical_bytes": acc.total_logical,
            "budget_bytes": meta.budget_bytes,
        },
        "manifest_sha256": manifest_sha,
    }


def _render_summary_md(summary: dict[str, Any]) -> str:
    meta = summary["meta"]
    counts = summary["counts"]
    sizes = summary["sizes"]
    lines = [
        "# Estate generation summary",
        "",
        f"- Generator version: {meta['generator_version']}",
        f"- Profile: {meta['profile']}",
        f"- Seed: {meta['seed']}",
        f"- Truth generator version: {meta['truth_generator_version']} (seed {meta['truth_seed']})",
        f"- Epoch anchor: {meta['epoch_anchor']}",
        "",
        "## Counts",
        "",
        f"- Files: {counts['files']}",
        f"- Genuine: {counts['genuine']}",
        f"- Placeholders: {counts['placeholders']}",
        f"- Assets covered: {counts['assets']}",
        "",
        "## Sizes",
        "",
        f"- Total physical bytes: {sizes['total_physical_bytes']}",
        f"- Total represented logical bytes: {sizes['total_logical_bytes']}",
        f"- Budget bytes: {sizes['budget_bytes']}",
        "",
        "## Files by format",
        "",
    ]
    for fmt, count in summary["by_format"].items():
        lines.append(f"- {fmt}: {count}")
    lines.extend(["", "## Files by modality group", ""])
    for group, count in summary["by_modality_group"].items():
        lines.append(f"- {group}: {count}")
    lines.append("")
    return "\n".join(lines)


def write_estate(
    graph: TruthGraph, profile: Profile, seed: int, output_dir: Path | str
) -> dict[str, Any]:
    """Generate and atomically write the estate for ``profile`` into ``output_dir``.

    Returns the ``generation-summary.json`` payload. Raises
    :class:`EstateValidationError` on a path escape or budget breach, having
    written nothing final.
    """
    output_dir = Path(output_dir)
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{output_dir.name}.tmp-{os.getpid()}"
    backup = parent / f".{output_dir.name}.bak-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)

    try:
        tmp.mkdir(parents=True)
        acc = _generate_into(tmp, graph, profile, seed)
        summary = build_summary(graph, profile, seed, acc)

        (tmp / MANIFEST_NAME).write_bytes(serialize.jsonl_bytes(acc.records))
        (tmp / SUMMARY_JSON_NAME).write_bytes(serialize.manifest_bytes(summary))
        serialize.write_text(tmp / SUMMARY_MD_NAME, _render_summary_md(summary))

        had_existing = output_dir.exists()
        if had_existing:
            os.replace(output_dir, backup)
        try:
            os.replace(tmp, output_dir)
        except OSError:
            if had_existing:  # pragma: no cover - best-effort restore
                os.replace(backup, output_dir)
            raise
        if had_existing:
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return summary


__all__ = [
    "MANIFEST_NAME",
    "SUMMARY_JSON_NAME",
    "SUMMARY_MD_NAME",
    "FILES_DIRNAME",
    "write_estate",
    "build_summary",
]
