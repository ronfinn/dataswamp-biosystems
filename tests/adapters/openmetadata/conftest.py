"""Fixtures for the OpenMetadata adapter tests.

Two sources, deliberately, mirroring the DataHub adapter's arrangement.

The **mini** source graph below is hand-written and small enough that the whole
emitted plan can be committed as a fixture, which is what makes mapping drift
visible in a diff rather than in a count. It is a near-copy of the DataHub
adapter's mini graph — same ids, same shape — so the two adapters' outputs are
directly comparable when reading them side by side. It is *copied* rather than
imported, on purpose: these are two independent adapters, and a shared fixture
would couple their test suites in exactly the way the architecture avoids.

It is chosen to exercise the awkward cases rather than the happy path:

* a file in ``h5ad``, which is **not** a member of OpenMetadata's ``fileFormat``
  enum, beside one in ``parquet``, which is;
* a physical byte count that is not a whole number of KB, so the KB/bytes
  distinction is measurable;
* two stewards and one owner, so the ownership/stewardship split is visible;
* a contract on one dataset and not the other;
* a quality check, which this adapter deliberately does not map to a test entity.

The **real** bundle is the canonical scenario packaged end to end, and is what
proves the adapter behaves on the actual benchmark.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.openmetadata import (
    ExportMode,
    ExportPlan,
    SourceGraph,
    build_plan,
    export_openmetadata,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


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
            # Not a member of OpenMetadata's fileFormat enum. The adapter must
            # leave fileFormats unset rather than coercing it.
            "relative_path": "files/bravo/matrix.h5ad",
            "file_format": "h5ad",
            # Deliberately not a whole number of KB.
            "physical_bytes": 1500,
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
def mini_observed_source() -> SourceGraph:
    return SourceGraph(mode=ExportMode.OBSERVED, shards=MINI_SHARDS)


@pytest.fixture
def mini_truth_source() -> SourceGraph:
    return SourceGraph(
        mode=ExportMode.TRUTH,
        shards=MINI_SHARDS,
        expected_finding_rules={"ds-alpha": ["RULE-ONE", "RULE-TWO"]},
    )


@pytest.fixture
def mini_observed(mini_observed_source: SourceGraph) -> ExportPlan:
    return build_plan(mini_observed_source)


@pytest.fixture
def mini_truth(mini_truth_source: SourceGraph) -> ExportPlan:
    return build_plan(mini_truth_source)


@pytest.fixture(scope="session")
def om_observed_export_dir(full_bundle_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real emitted observed export, from the canonical benchmark bundle."""
    target = tmp_path_factory.mktemp("om-observed") / "export"
    export_openmetadata(full_bundle_dir, target, mode=ExportMode.OBSERVED)
    return target


@pytest.fixture(scope="session")
def om_truth_export_dir(full_bundle_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real emitted *privileged* truth export.

    Used to prove the observed checks can actually fire. A detector never
    observed to fire is not evidence of anything.
    """
    target = tmp_path_factory.mktemp("om-truth") / "export"
    export_openmetadata(full_bundle_dir, target, mode=ExportMode.TRUTH)
    return target


@pytest.fixture
def copied_om_export(om_observed_export_dir: Path, tmp_path: Path) -> Path:
    """A writable copy of the observed export, for tests that tamper with it."""
    target = tmp_path / "export"
    shutil.copytree(om_observed_export_dir, target)
    return target
