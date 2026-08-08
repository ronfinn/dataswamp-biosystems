"""Fixtures for the DataHub adapter tests.

Two sources, deliberately.

The **mini** source graph below is hand-written: two datasets, one data product,
two files, one contract and one quality check. It is small enough that the whole
emitted payload can be committed as a fixture, which is what makes mapping drift
visible in a diff rather than in a count.

The **real** bundle is the canonical scenario packaged end to end, and is what
proves the adapter behaves on the actual benchmark.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.datahub import (
    ADAPTER_VERSION,
    DATAHUB_MODEL_VERSION,
    EXPORT_MANIFEST_NAME,
    MCPS_JSONL_NAME,
    ExportMode,
    SourceGraph,
    build_mcps,
    export_datahub,
)
from dataswamp_biosystems.truth import serialize

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
MINI_OBSERVED_FIXTURE = FIXTURE_DIR / "mini-observed-mcps.jsonl"
MINI_TRUTH_FIXTURE = FIXTURE_DIR / "mini-truth-mcps.jsonl"


def _asset(asset_id: str, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": asset_id,
        "asset_type": "dataset",
        "title": f"Title for {asset_id}",
        "description": f"Description for {asset_id}.",
        "programme_id": "prog-nsclc",
        "study_id": "study-nsclc-01",
        "scientific_domain": "genomics",
        "modality": "bulk-rna-seq",
        "modality_group": "sequencing",
        "lifecycle_stage": "production",
        "version": "1.0.0",
        "owner_ref": "team-genomics",
        "steward_refs": ["team-governance", "team-quality"],
        "access_classification": "internal",
        "retention_class": "long-term",
        "intended_uses": ["research", "model-training"],
        "model_training_status": "approved",
        "contract_ref": f"contract-{asset_id}",
        "quality_status": "pass",
        "physical_bytes": 4096,
        "logical_bytes": 8192,
        "record_count": 100,
        "file_ids": [f"file-{asset_id}-1"],
        "provenance_run_id": "run-1",
        "generator_version": "test",
        "generation_seed": 1,
        "synthetic": True,
    }
    record.update(overrides)
    return record


MINI_SHARDS: dict[str, list[dict[str, object]]] = {
    "datasets": [_asset("ds-alpha"), _asset("ds-bravo", modality="scrna-seq")],
    "data_products": [
        _asset(
            "dp-omics",
            asset_type="data_product",
            component_dataset_ids=["ds-alpha", "ds-bravo"],
        )
    ],
    "files": [
        {
            "id": "file-ds-alpha-1",
            "dataset_id": "ds-alpha",
            "producing_run_id": "run-1",
            "relative_path": "files/alpha/counts.parquet",
            "file_format": "parquet",
            "physical_bytes": 2048,
            "checksum": "a" * 64,
            "synthetic": True,
        },
        {
            "id": "file-ds-bravo-1",
            "dataset_id": "ds-bravo",
            "producing_run_id": "run-2",
            "relative_path": "files/bravo/matrix.h5ad",
            "file_format": "h5ad",
            "physical_bytes": 1024,
            "checksum": "b" * 64,
            "synthetic": True,
        },
    ],
    "contracts": [
        {
            "id": "contract-ds-alpha",
            "asset_id": "ds-alpha",
            "contract_version": "2.1.0",
            "schema_ref": "schemas/alpha.json",
            "sla": "monthly",
            "quality_expectations": ["no nulls"],
            "synthetic": True,
        }
    ],
    "quality_checks": [
        {
            "id": "qc-ds-alpha-1",
            "asset_id": "ds-alpha",
            "check_type": "completeness",
            "status": "pass",
            "evidence": "all required columns present",
            "evaluated_at": "2026-03-01T00:00:00Z",
            "synthetic": True,
        }
    ],
    "lineage": [
        {
            "id": "edge-1",
            "upstream_id": "ds-alpha",
            "downstream_id": "ds-bravo",
            "edge_type": "derived_from",
            "synthetic": True,
        }
    ],
}


@pytest.fixture
def mini_observed() -> SourceGraph:
    return SourceGraph(mode=ExportMode.OBSERVED, shards=MINI_SHARDS)


@pytest.fixture
def mini_truth() -> SourceGraph:
    return SourceGraph(
        mode=ExportMode.TRUTH,
        shards=MINI_SHARDS,
        expected_finding_rules={"ds-alpha": ["RULE-ONE", "RULE-TWO"]},
    )


@pytest.fixture(scope="session")
def observed_export_dir(full_bundle_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real emitted observed export — the live path's only input."""
    target = tmp_path_factory.mktemp("live-observed") / "export"
    export_datahub(full_bundle_dir, target, mode=ExportMode.OBSERVED)
    return target


@pytest.fixture(scope="session")
def truth_export_dir(full_bundle_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real emitted *privileged* truth export.

    Used to prove the observed leak probes can actually fire. A detector never
    observed to fire is not evidence of anything.
    """
    target = tmp_path_factory.mktemp("live-truth") / "export"
    export_datahub(full_bundle_dir, target, mode=ExportMode.TRUTH)
    return target


@pytest.fixture
def copied_export(observed_export_dir: Path, tmp_path: Path) -> Path:
    """A writable copy of the observed export, for tamper tests."""
    target = tmp_path / "export"
    shutil.copytree(observed_export_dir, target)
    return target


def write_test_export(target: Path, mcps: list[dict], *, mode: ExportMode) -> Path:
    """Write a minimal but *genuine* export directory for the live-path tests.

    Mirrors the layout ``export_datahub`` writes — the same canonical JSONL and
    the same manifest digest contract — over a small hand-built payload, so the
    round-trip tests are not paying for the whole canonical estate on every
    perturbation. The tests that must exercise the real emitted artefact use
    ``observed_export_dir`` and ``truth_export_dir`` instead.
    """
    target.mkdir(parents=True, exist_ok=True)
    payload = "".join(f"{serialize.canonical_json(mcp)}\n" for mcp in mcps).encode("utf-8")
    serialize.write_bytes(target / MCPS_JSONL_NAME, payload)
    manifest = {
        "adapter_version": ADAPTER_VERSION,
        "datahub_model_version": DATAHUB_MODEL_VERSION,
        "mode": mode.value,
        "privileged": mode is ExportMode.TRUTH,
        "bundle": {"bundle_fingerprint": "test", "benchmark_release": "v-test", "layers": []},
        "files": {MCPS_JSONL_NAME: serialize.digest(payload)},
        "synthetic": True,
    }
    serialize.write_bytes(target / EXPORT_MANIFEST_NAME, serialize.manifest_bytes(manifest))
    return target


@pytest.fixture(scope="session")
def mini_export_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small emitted observed export, for the fast perturbation tests."""
    return write_test_export(
        tmp_path_factory.mktemp("mini-observed-export") / "export",
        build_mcps(SourceGraph(mode=ExportMode.OBSERVED, shards=MINI_SHARDS)),
        mode=ExportMode.OBSERVED,
    )


@pytest.fixture(scope="session")
def mini_truth_export_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small emitted *privileged* truth export, for the leak-probe proof."""
    return write_test_export(
        tmp_path_factory.mktemp("mini-truth-export") / "export",
        build_mcps(
            SourceGraph(
                mode=ExportMode.TRUTH,
                shards=MINI_SHARDS,
                expected_finding_rules={"ds-alpha": ["RULE-ONE"]},
            )
        ),
        mode=ExportMode.TRUTH,
    )
