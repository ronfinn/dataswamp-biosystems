"""Emit a deterministic DataHub metadata export from a verified benchmark bundle.

The export is a set of files, not a network call. Nothing here opens a socket,
reads a token or needs a running DataHub: the MVP produces the payload DataHub's
own file source ingests, so the whole adapter is testable offline and a user
decides separately when and where to push it.

Output, all byte-identical for identical input:

``mcps.jsonl``
    One Metadata Change Proposal per line, canonical JSON. The machine-readable
    form, and the one checksums and fixtures are taken over.
``mcps.json``
    The same proposals as a JSON array — the shape DataHub's ``file`` source
    reads directly.
``export-manifest.json``
    Mode, privilege, counts, the bundle it came from, and a digest per file.
``mapping-coverage.json``
    How each of the 24 DataSwamp semantic families maps into DataHub, how
    faithfully, where it surfaces and what is deliberately dropped. It is an
    adapter contract artefact, digest-verified with the rest of the export and
    never transmitted to a catalogue.
``datahub-recipe.yml``
    A ready-to-run ingestion recipe pointing at ``mcps.json``. It references
    credentials only through environment variables and contains none.
``provenance.json``
    The same environment provenance every other generated directory carries.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from dataswamp_biosystems.adapters.datahub.mapping import (
    ADAPTER_VERSION,
    DATAHUB_MODEL_VERSION,
    ExportMode,
    SourceGraph,
    build_mapping_coverage,
    build_mcps,
)
from dataswamp_biosystems.adapters.datahub.urns import FABRIC, NAMESPACE, PLATFORM_ID
from dataswamp_biosystems.bundle import BundleReader, Layer
from dataswamp_biosystems.bundle.errors import BundleConfigError
from dataswamp_biosystems.provenance import PROVENANCE_NAME, provenance_bytes
from dataswamp_biosystems.truth import serialize


def _json_array_bytes(payload: list[dict[str, Any]]) -> bytes:
    """Render a list of proposals as pretty, deterministic JSON-array bytes.

    The array form is what DataHub's ``file`` source reads. It uses the same
    canonical rules as every other JSON this project writes (sorted keys, UTF-8,
    ``\\n`` endings, trailing newline), so the two emitted forms stay in step.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


MCPS_JSONL_NAME = "mcps.jsonl"
MCPS_JSON_NAME = "mcps.json"
EXPORT_MANIFEST_NAME = "export-manifest.json"
RECIPE_NAME = "datahub-recipe.yml"
COVERAGE_NAME = "mapping-coverage.json"

# The observed graph's shard names are the truth-graph field names, so one
# mapping serves both modes.
_TRUTH_SHARD_SOURCES: dict[str, str] = {
    "files": "files.jsonl",
    "subjects": "subjects.jsonl",
    "biospecimens": "biospecimens.jsonl",
    "assays": "assays.jsonl",
    "contracts": "contracts.jsonl",
    "quality_checks": "quality.jsonl",
    "lineage": "lineage.jsonl",
}


def _truth_source(reader: BundleReader, *, labelled: bool) -> SourceGraph:
    """Build the privileged source graph from the bundle's truth layer."""
    shards: dict[str, list[dict[str, Any]]] = {"datasets": [], "data_products": []}
    for record in reader.iter_assets():
        key = "data_products" if record.get("asset_type") == "data_product" else "datasets"
        shards[key].append(record)
    for shard, source_file in _TRUTH_SHARD_SOURCES.items():
        shards[shard] = list(reader.iter_truth_records(source_file))
    # Both run kinds live in one shard, split on the record's own discriminator
    # so the observed graph's two run shards have truth-mode counterparts.
    runs = list(reader.iter_truth_records("runs.jsonl"))
    shards["instrument_runs"] = [row for row in runs if row.get("run_kind") == "instrument"]
    shards["pipeline_runs"] = [row for row in runs if row.get("run_kind") == "pipeline"]

    labels: dict[str, list[str]] = {}
    if labelled and reader.has_layer(Layer.OBSERVED):
        for finding in reader.iter_findings():
            labels.setdefault(finding.entity_id, []).append(finding.rule_id)
    return SourceGraph(
        mode=ExportMode.TRUTH,
        shards=shards,
        expected_finding_rules={key: sorted(value) for key, value in sorted(labels.items())},
    )


def _observed_source(reader: BundleReader) -> SourceGraph:
    """Build the unprivileged source graph from the bundle's observed graph alone.

    This function is the containment boundary for truth leakage: it reads
    ``observed-graph.json`` and nothing else. The expected findings, expected
    remediations, control partition, rule scope, mutation log and — for an
    adversarial bundle — the scenario ledgers are never opened, so no future
    change to the mapping can accidentally surface them. An adversarial bundle
    therefore exports exactly what an ordinary one does: the near-miss *values*
    are in the observed graph and travel with it, while the records saying they
    were planted stay behind.
    """
    graph = reader.observed_graph()
    shards: dict[str, list[dict[str, Any]]] = {}
    for shard in (
        "datasets",
        "data_products",
        "files",
        "contracts",
        "quality_checks",
        "lineage",
        # Carried for measurement only. The mapping ignores these five by name;
        # coverage counts them so "deliberately not mapped" cannot be confused
        # with "there was nothing there". They come from the same file.
        "subjects",
        "biospecimens",
        "assays",
        "instrument_runs",
        "pipeline_runs",
    ):
        records = graph.get(shard, [])
        shards[shard] = [row for row in records if isinstance(row, dict)]
    return SourceGraph(mode=ExportMode.OBSERVED, shards=shards)


def build_source(reader: BundleReader, mode: ExportMode, *, labelled: bool = True) -> SourceGraph:
    """Return the source graph for ``mode``, or raise if the bundle cannot serve it."""
    if mode is ExportMode.OBSERVED:
        if not reader.has_layer(Layer.OBSERVED):
            raise BundleConfigError(
                "an observed export needs the observed layer; this bundle has "
                f"{', '.join(reader.manifest.layers)}"
            )
        return _observed_source(reader)
    return _truth_source(reader, labelled=labelled)


def _render_recipe(mode: ExportMode) -> str:
    return "\n".join(
        [
            "# DataHub ingestion recipe for a DataSwamp Biosystems metadata export.",
            "#",
            "# The payload is already generated; this recipe only loads it. Point",
            "# `server` at your instance and supply the token through the environment —",
            "# never commit one into this file.",
            "#",
            f"# Export mode: {mode.value}"
            + ("  (PRIVILEGED — benchmark ground truth)" if mode is ExportMode.TRUTH else ""),
            "",
            "source:",
            "  type: file",
            "  config:",
            f"    path: ./{MCPS_JSON_NAME}",
            "",
            "sink:",
            "  type: datahub-rest",
            "  config:",
            '    server: "${DATAHUB_GMS_URL}"',
            '    token: "${DATAHUB_GMS_TOKEN}"',
            "",
            "# Dry run without a server:",
            f"#   datahub ingest -c {RECIPE_NAME} --dry-run",
            "",
        ]
    )


def _export_manifest(
    reader: BundleReader,
    mode: ExportMode,
    mcps: list[dict[str, Any]],
    digests: dict[str, str],
) -> dict[str, Any]:
    by_entity: dict[str, int] = {}
    by_aspect: dict[str, int] = {}
    urns: set[str] = set()
    for mcp in mcps:
        entity_type = str(mcp["entityType"])
        aspect = str(mcp["aspectName"])
        by_entity[entity_type] = by_entity.get(entity_type, 0) + 1
        by_aspect[aspect] = by_aspect.get(aspect, 0) + 1
        urns.add(str(mcp["entityUrn"]))
    return {
        "adapter_version": ADAPTER_VERSION,
        "datahub_model_version": DATAHUB_MODEL_VERSION,
        "mode": mode.value,
        "privileged": mode is ExportMode.TRUTH,
        "bundle": {
            "bundle_fingerprint": reader.manifest.bundle_fingerprint,
            "benchmark_release": reader.manifest.benchmark_release,
            "layers": list(reader.manifest.layers),
            "ground_truth_fingerprint": reader.manifest.ground_truth_fingerprint,
        },
        "counts": {
            "entities": len(urns),
            "aspects": len(mcps),
            "by_entity_type": dict(sorted(by_entity.items())),
            "by_aspect": dict(sorted(by_aspect.items())),
        },
        "urn_scheme": {
            "platform": PLATFORM_ID,
            "namespace": NAMESPACE,
            "fabric": FABRIC,
            "documentation": "docs/datahub.md",
        },
        "files": dict(sorted(digests.items())),
        "synthetic": True,
    }


def export_datahub(
    bundle_dir: Path | str,
    output_dir: Path | str,
    *,
    mode: ExportMode = ExportMode.OBSERVED,
    verify: bool = True,
) -> dict[str, Any]:
    """Export a bundle's metadata as DataHub proposals into ``output_dir``.

    The bundle is opened read-only and verified by default. ``output_dir`` is
    written atomically and is never inside the bundle: callers are responsible
    for applying the shared output-path policy, and this function never writes
    outside the directory it was given.
    """
    output_dir = Path(output_dir)
    with BundleReader.open(bundle_dir, verify=verify) as reader:
        source = build_source(reader, mode)
        mcps = build_mcps(source)

        jsonl = "".join(f"{serialize.canonical_json(mcp)}\n" for mcp in mcps).encode("utf-8")
        array = _json_array_bytes(mcps)
        recipe = _render_recipe(mode).encode("utf-8")
        coverage = serialize.manifest_bytes(build_mapping_coverage(source))
        digests = {
            MCPS_JSONL_NAME: serialize.digest(jsonl),
            MCPS_JSON_NAME: serialize.digest(array),
            RECIPE_NAME: serialize.digest(recipe),
            COVERAGE_NAME: serialize.digest(coverage),
        }
        manifest = _export_manifest(reader, mode, mcps, digests)

    provenance = provenance_bytes(
        layer="adapter-datahub",
        generator_version=ADAPTER_VERSION,
        schema_version=1,
        scenario={
            "mode": mode.value,
            "bundle_fingerprint": manifest["bundle"]["bundle_fingerprint"],
        },
    )
    files = {
        MCPS_JSONL_NAME: jsonl,
        MCPS_JSON_NAME: array,
        RECIPE_NAME: recipe,
        COVERAGE_NAME: coverage,
        EXPORT_MANIFEST_NAME: serialize.manifest_bytes(manifest),
        PROVENANCE_NAME: provenance,
    }

    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{output_dir.name}.tmp-{os.getpid()}"
    backup = parent / f".{output_dir.name}.bak-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        tmp.mkdir(parents=True)
        for name in sorted(files):
            serialize.write_bytes(tmp / name, files[name])
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

    return manifest


__all__ = [
    "MCPS_JSONL_NAME",
    "MCPS_JSON_NAME",
    "EXPORT_MANIFEST_NAME",
    "RECIPE_NAME",
    "COVERAGE_NAME",
    "build_source",
    "export_datahub",
]
