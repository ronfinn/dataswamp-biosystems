"""Emit a deterministic OpenMetadata load plan from a verified benchmark bundle.

The export is a set of files, not a network call. Nothing here opens a socket,
reads a token or needs a running OpenMetadata: the emitted JSONL **is** the
interchange contract, so the whole adapter is testable offline and a user decides
separately when and where to load it. There is deliberately no decorative recipe
or YAML wrapper — a file that only restates what the plan already says is one
more thing to keep in step, and one more place for a claim to drift.

Output, all byte-identical for identical input:

``custom-properties.jsonl``
    The custom-property registrations that must exist before any entity carrying
    an ``extension`` is written.
``entities.jsonl``
    One ``Create<Entity>`` request per entity, in load order, plus the
    data-product asset-attachment plan.
``lineage.jsonl``
    Dataset-to-dataset lineage edges, as a plan: OpenMetadata's edge endpoints are
    ``EntityReference`` values needing server-assigned UUIDs.
``test-results.jsonl``
    The deferred, explicitly *blocked* quality-check result plan. See
    ``mapping-coverage.json`` for why no TestCase exists to attach these to.
``mapping-coverage.json``
    What was mapped, how faithfully, what was dropped and why. A first-class part
    of the export.
``export-manifest.json``
    Mode, privilege, counts, the bundle it came from, the schema target, and a
    digest per file.
``provenance.json``
    The same environment provenance every other generated directory carries.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from dataswamp_biosystems.adapters.openmetadata import fqn as om_fqn
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    OM_ADAPTER_VERSION,
    OPENMETADATA_MODEL_TARGET_RANGE,
    OPENMETADATA_SCHEMA_COMMIT,
    OPENMETADATA_SCHEMA_TARGET,
    PHASES,
    VERIFIED_OPENMETADATA_VERSION,
    ExportMode,
    ExportPlan,
    PlanRecord,
    SourceGraph,
    build_plan,
)
from dataswamp_biosystems.bundle import BundleReader, Layer
from dataswamp_biosystems.bundle.errors import BundleConfigError
from dataswamp_biosystems.provenance import PROVENANCE_NAME, provenance_bytes
from dataswamp_biosystems.truth import serialize

CUSTOM_PROPERTIES_NAME = "custom-properties.jsonl"
ENTITIES_NAME = "entities.jsonl"
LINEAGE_NAME = "lineage.jsonl"
TEST_RESULTS_NAME = "test-results.jsonl"
MAPPING_COVERAGE_NAME = "mapping-coverage.json"
EXPORT_MANIFEST_NAME = "export-manifest.json"

# The observed graph's shard names are the truth-graph field names, so one
# mapping serves both modes.
_TRUTH_SHARD_SOURCES: dict[str, str] = {
    "files": "files.jsonl",
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
    for shard in ("datasets", "data_products", "files", "contracts", "quality_checks", "lineage"):
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


def _jsonl_bytes(records: tuple[PlanRecord, ...]) -> bytes:
    return "".join(f"{serialize.canonical_json(record.as_json())}\n" for record in records).encode(
        "utf-8"
    )


def _live_support(mode: ExportMode) -> str:
    """Return the live-evidence statement true of an export in ``mode``.

    The canary ran an *observed* export end to end, so that is the only mode with
    live evidence behind it. A truth export is the privileged diagnostic surface:
    it rests on the deterministic offline contract and the vendored schemas, and
    no canary has loaded one into a running server. Saying so per mode keeps a
    stored truth export from quoting somebody else's green.
    """
    if VERIFIED_OPENMETADATA_VERSION is None:
        return (
            "none: this export has never been loaded into a running OpenMetadata "
            "instance by this project, and no compatibility point is claimed"
        )
    if mode is ExportMode.TRUTH:
        return (
            f"observed mode is verified against OpenMetadata {VERIFIED_OPENMETADATA_VERSION}; "
            "this is a truth export, and the privileged path has not been run against a "
            "real server. A tested point, never a range"
        )
    return (
        f"verified against OpenMetadata {VERIFIED_OPENMETADATA_VERSION} in observed mode: "
        "a pinned throwaway server accepted an export of this shape and returned it with "
        "zero discrepancies and zero leak findings. A tested point, never a range"
    )


def _export_manifest(
    reader: BundleReader,
    plan: ExportPlan,
    digests: dict[str, str],
) -> dict[str, Any]:
    by_entity: dict[str, int] = {}
    by_phase: dict[str, int] = {}
    for record in plan.records:
        by_entity[record.entity_type] = by_entity.get(record.entity_type, 0) + 1
        by_phase[record.phase] = by_phase.get(record.phase, 0) + 1
    return {
        "adapter_version": OM_ADAPTER_VERSION,
        "openmetadata_schema_target": OPENMETADATA_SCHEMA_TARGET,
        "openmetadata_schema_commit": OPENMETADATA_SCHEMA_COMMIT,
        # A declared target for the emitted payload shape, not tested evidence and
        # not a statement about any REST endpoint. See ADR 0006.
        "openmetadata_model_target_range": OPENMETADATA_MODEL_TARGET_RANGE,
        # The one release a green canary has run this path against. A tested
        # point, never a range.
        "verified_openmetadata_version": VERIFIED_OPENMETADATA_VERSION,
        # Said per mode rather than once, because only one mode was run. An
        # export states the evidence *it* carries: the canary loaded an observed
        # export, so a truth export must not inherit its green.
        "live_support": _live_support(plan.mode),
        "mode": plan.mode.value,
        "privileged": plan.mode is ExportMode.TRUTH,
        "bundle": {
            "bundle_fingerprint": reader.manifest.bundle_fingerprint,
            "benchmark_release": reader.manifest.benchmark_release,
            "layers": list(reader.manifest.layers),
            "ground_truth_fingerprint": reader.manifest.ground_truth_fingerprint,
        },
        "counts": {
            "records": len(plan.records),
            "custom_properties": len(plan.custom_properties),
            "entities": len(plan.entities),
            "lineage_edges": len(plan.lineage),
            "deferred_test_results": len(plan.test_results),
            "by_entity_type": dict(sorted(by_entity.items())),
            "by_phase": dict(sorted(by_phase.items())),
        },
        "fqn_scheme": {
            "service": om_fqn.SERVICE_NAME,
            "namespace": om_fqn.NAMESPACE,
            "service_type": om_fqn.SERVICE_TYPE,
            "classification": om_fqn.CLASSIFICATION_NAME,
            "documentation": "docs/openmetadata.md",
        },
        "load_order": list(PHASES),
        "files": dict(sorted(digests.items())),
        "synthetic": True,
    }


def export_openmetadata(
    bundle_dir: Path | str,
    output_dir: Path | str,
    *,
    mode: ExportMode = ExportMode.OBSERVED,
    verify: bool = True,
) -> dict[str, Any]:
    """Export a bundle's metadata as an OpenMetadata load plan into ``output_dir``.

    The bundle is opened read-only and verified by default. ``output_dir`` is
    written atomically and is never inside the bundle: callers are responsible for
    applying the shared output-path policy, and this function never writes outside
    the directory it was given.
    """
    output_dir = Path(output_dir)
    with BundleReader.open(bundle_dir, verify=verify) as reader:
        plan = build_plan(build_source(reader, mode))

        contents: dict[str, bytes] = {
            CUSTOM_PROPERTIES_NAME: _jsonl_bytes(plan.custom_properties),
            ENTITIES_NAME: _jsonl_bytes(plan.entities),
            LINEAGE_NAME: _jsonl_bytes(plan.lineage),
            TEST_RESULTS_NAME: _jsonl_bytes(plan.test_results),
            MAPPING_COVERAGE_NAME: serialize.manifest_bytes(plan.coverage),
        }
        digests = {name: serialize.digest(data) for name, data in contents.items()}
        manifest = _export_manifest(reader, plan, digests)

    provenance = provenance_bytes(
        layer="adapter-openmetadata",
        generator_version=OM_ADAPTER_VERSION,
        schema_version=1,
        scenario={
            "mode": mode.value,
            "bundle_fingerprint": manifest["bundle"]["bundle_fingerprint"],
        },
    )
    files = {
        **contents,
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
    "CUSTOM_PROPERTIES_NAME",
    "ENTITIES_NAME",
    "LINEAGE_NAME",
    "TEST_RESULTS_NAME",
    "MAPPING_COVERAGE_NAME",
    "EXPORT_MANIFEST_NAME",
    "build_source",
    "export_openmetadata",
]
