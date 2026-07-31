"""Writes a :class:`TruthGraph` to the canonical ``generated/truth/`` layout.

The set of shards, their fixed write order, and the manifest are defined here.
Heterogeneous shards (runs, assets, governance) combine related entity kinds
behind a discriminator field. Every shard's bytes are hashed into the manifest
so ``truth-graph.json`` doubles as a determinism tripwire.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from dataswamp_biosystems.truth import serialize
from dataswamp_biosystems.truth.graph import TruthGraph

# Fixed shard order. Each maps to the concatenation of its entity lists.
_SHARD_ORDER = [
    "subjects.jsonl",
    "biospecimens.jsonl",
    "assays.jsonl",
    "runs.jsonl",
    "files.jsonl",
    "assets.jsonl",
    "contracts.jsonl",
    "quality.jsonl",
    "governance.jsonl",
    "lineage.jsonl",
]

MANIFEST_NAME = "truth-graph.json"
SUMMARY_NAME = "summary.md"


def _shard_models(graph: TruthGraph, shard: str) -> list[BaseModel]:
    if shard == "subjects.jsonl":
        return list(graph.subjects)
    if shard == "biospecimens.jsonl":
        return list(graph.biospecimens)
    if shard == "assays.jsonl":
        return list(graph.assays)
    if shard == "runs.jsonl":
        return [*graph.instrument_runs, *graph.pipeline_runs]
    if shard == "files.jsonl":
        return list(graph.files)
    if shard == "assets.jsonl":
        return [*graph.datasets, *graph.data_products]
    if shard == "contracts.jsonl":
        return list(graph.contracts)
    if shard == "quality.jsonl":
        return list(graph.quality_checks)
    if shard == "governance.jsonl":
        return [
            *graph.governance_records,
            *graph.intended_use_records,
            *graph.training_approvals,
        ]
    if shard == "lineage.jsonl":
        return list(graph.lineage)
    raise ValueError(f"unknown shard {shard!r}")  # pragma: no cover


def shard_bytes(graph: TruthGraph) -> dict[str, bytes]:
    """Return the canonical bytes of every JSONL shard, keyed by filename.

    Computed without touching the filesystem, so callers can compare against
    on-disk files or verify determinism in memory.
    """
    result: dict[str, bytes] = {}
    for shard in _SHARD_ORDER:
        result[shard] = serialize.jsonl_bytes(_shard_models(graph, shard))
    return result


def build_manifest(graph: TruthGraph, shards: dict[str, bytes]) -> dict[str, Any]:
    """Build the manifest dict (meta, counts, per-shard record counts + digests)."""
    file_index: dict[str, dict[str, object]] = {}
    for shard in _SHARD_ORDER:
        data = shards[shard]
        records = data.count(b"\n") if data else 0
        file_index[shard] = {"records": records, "sha256": serialize.digest(data)}
    return {
        "meta": graph.meta.model_dump(mode="json"),
        "counts": graph.entity_counts(),
        "files": file_index,
    }


def write_truth_graph(graph: TruthGraph, output_dir: Path | str) -> dict[str, Any]:
    """Write all shards, the manifest, and the summary, replacing any prior output.

    Output is staged in a temporary sibling directory and swapped into place with
    directory renames, so a previously generated output is only replaced once the
    new output is fully written — an interrupted or failing run never leaves a
    partial final directory, and the previous output is restored on failure.
    """
    output_dir = Path(output_dir)
    shards = shard_bytes(graph)
    manifest = build_manifest(graph, shards)

    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{output_dir.name}.tmp-{os.getpid()}"
    backup = parent / f".{output_dir.name}.bak-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)

    try:
        for shard in _SHARD_ORDER:
            serialize.write_bytes(tmp / shard, shards[shard])
        serialize.write_bytes(tmp / MANIFEST_NAME, serialize.manifest_bytes(manifest))
        serialize.write_text(tmp / SUMMARY_NAME, _render_summary(graph))

        had_existing = output_dir.exists()
        if had_existing:
            os.replace(output_dir, backup)
        try:
            os.replace(tmp, output_dir)
        except OSError:
            if had_existing:  # pragma: no cover - restore path is best-effort
                os.replace(backup, output_dir)
            raise
        if had_existing:
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return manifest


def _render_summary(graph: TruthGraph) -> str:
    lines = [
        "# Truth graph summary",
        "",
        f"- Generator version: {graph.meta.generator_version}",
        f"- Schema version: {graph.meta.schema_version}",
        f"- Seed: {graph.meta.seed}",
        f"- Epoch anchor: {graph.meta.epoch_anchor}",
        "",
        "## Entity counts",
        "",
    ]
    for name, count in graph.entity_counts().items():
        lines.append(f"- {name.replace('_', ' ')}: {count}")

    lines.extend(["", "## Datasets by modality group", ""])
    by_group: dict[str, int] = {}
    for dataset in graph.datasets:
        by_group[dataset.modality_group] = by_group.get(dataset.modality_group, 0) + 1
    for group in sorted(by_group):
        lines.append(f"- {group}: {by_group[group]}")

    lines.append("")
    return "\n".join(lines)


__all__ = [
    "write_truth_graph",
    "shard_bytes",
    "build_manifest",
    "MANIFEST_NAME",
    "SUMMARY_NAME",
]
