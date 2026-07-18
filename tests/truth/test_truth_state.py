"""Tests that every catalogue asset carries the full required truth-state.

The milestone requires each dataset and data product to carry a stable id, a
synthetic marker, title, description, programme, study, scientific domain,
modality, lifecycle stage, version, owner, steward, access classification,
retention class, intended use, training-approval status, contract reference,
quality status, provenance, lineage, generator version, and seed.
"""

from __future__ import annotations

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.truth import GenerationPlan, generate_truth_graph
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.truth.conftest import TEST_SEED


def _assets(graph: TruthGraph) -> list:
    return [*graph.datasets, *graph.data_products]


def test_every_asset_has_required_catalogue_fields(graph: TruthGraph, plan: GenerationPlan) -> None:
    for asset in _assets(graph):
        assert asset.id
        assert asset.synthetic is True
        assert asset.title.strip()
        assert asset.description.strip()
        assert asset.programme_id
        assert asset.study_id
        assert asset.scientific_domain
        assert asset.modality
        assert asset.lifecycle_stage
        assert asset.version
        assert asset.owner_ref
        assert asset.steward_refs
        assert asset.access_classification
        assert asset.retention_class
        assert asset.intended_uses
        assert asset.model_training_status
        assert asset.contract_ref
        assert asset.quality_status.value == "pass"
        assert asset.generator_version == plan.generator_version
        assert asset.generation_seed == TEST_SEED


def test_ownership_and_stewardship_resolve_to_org(
    graph: TruthGraph, config: CanonicalConfig
) -> None:
    org_ids = {t.id for t in config.teams} | {p.id for p in config.people}
    for asset in _assets(graph):
        assert asset.owner_ref in org_ids
        assert asset.steward_refs
        for steward in asset.steward_refs:
            assert steward in org_ids


def test_every_asset_has_governance_contract_and_quality(graph: TruthGraph) -> None:
    governed = {g.asset_id for g in graph.governance_records}
    contracted = {c.asset_id for c in graph.contracts}
    trained = {m.asset_id for m in graph.training_approvals}
    quality_counts: dict[str, int] = {}
    for q in graph.quality_checks:
        assert q.status.value == "pass"
        quality_counts[q.asset_id] = quality_counts.get(q.asset_id, 0) + 1
    for asset in _assets(graph):
        assert asset.id in governed
        assert asset.id in contracted
        assert asset.id in trained
        assert quality_counts.get(asset.id, 0) >= 1


def test_datasets_carry_provenance_run(graph: TruthGraph) -> None:
    run_ids = {r.id for r in graph.instrument_runs} | {r.id for r in graph.pipeline_runs}
    for dataset in graph.datasets:
        assert dataset.provenance_run_id in run_ids


def test_meta_records_seed_and_generator_version(graph: TruthGraph, plan: GenerationPlan) -> None:
    assert graph.meta.seed == TEST_SEED
    assert graph.meta.generator_version == plan.generator_version
    assert graph.meta.schema_version >= 1


def test_ids_are_stable_across_runs(config: CanonicalConfig, plan: GenerationPlan) -> None:
    first = generate_truth_graph(config, plan, TEST_SEED)
    second = generate_truth_graph(config, plan, TEST_SEED)
    for name, value in first:
        if name == "meta":
            continue
        other = dict(second)[name]
        assert [e.id for e in value] == [e.id for e in other]
    # A representative id is present and well-formed.
    assert any(d.id.startswith("ds-") for d in first.datasets)
