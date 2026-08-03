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

from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.datahub import ExportMode, SourceGraph

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
