"""Tests for truth-graph invariant validation, including negative cases."""

from __future__ import annotations

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.truth import GenerationPlan, validate_truth_graph
from dataswamp_biosystems.truth.entities import EdgeType, LineageEdge
from dataswamp_biosystems.truth.errors import TruthIssueKind, TruthValidationError
from dataswamp_biosystems.truth.graph import TruthGraph


def _kinds(exc: TruthValidationError) -> set[TruthIssueKind]:
    return {issue.kind for issue in exc.issues}


def test_generated_graph_is_valid(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    validate_truth_graph(graph, config, plan)


def test_missing_governance_record_is_rejected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    broken = graph.model_copy(update={"governance_records": graph.governance_records[1:]})
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.COMPLETENESS in _kinds(excinfo.value)


def test_lineage_cycle_is_detected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    a, b = graph.datasets[0].id, graph.datasets[1].id
    cycle = [
        LineageEdge(
            id="edge-cycle-a", upstream_id=a, downstream_id=b, edge_type=EdgeType.DERIVED_FROM
        ),
        LineageEdge(
            id="edge-cycle-b", upstream_id=b, downstream_id=a, edge_type=EdgeType.DERIVED_FROM
        ),
    ]
    broken = graph.model_copy(update={"lineage": [*graph.lineage, *cycle]})
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.LINEAGE in _kinds(excinfo.value)


def test_count_mismatch_is_rejected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    broken = graph.model_copy(update={"data_products": graph.data_products[:-1]})
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.COUNT_MISMATCH in _kinds(excinfo.value)


def test_dangling_reference_is_rejected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    dangling = graph.contracts[0].model_copy(update={"asset_id": "ds-does-not-exist"})
    broken = graph.model_copy(update={"contracts": [dangling, *graph.contracts[1:]]})
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.UNRESOLVED_REFERENCE in _kinds(excinfo.value)


def test_every_asset_has_upstream_lineage(graph: TruthGraph) -> None:
    downstream = {edge.downstream_id for edge in graph.lineage}
    for dataset in graph.datasets:
        assert dataset.id in downstream
    for product in graph.data_products:
        assert product.id in downstream


def test_no_self_lineage_in_generated_graph(graph: TruthGraph) -> None:
    for edge in graph.lineage:
        assert edge.upstream_id != edge.downstream_id


def test_injected_self_lineage_is_rejected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    node = graph.datasets[0].id
    loop = LineageEdge(
        id="edge-self-loop", upstream_id=node, downstream_id=node, edge_type=EdgeType.DERIVED_FROM
    )
    broken = graph.model_copy(update={"lineage": [*graph.lineage, loop]})
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.LINEAGE in _kinds(excinfo.value)


def test_invalid_vocabulary_is_rejected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    bad = graph.datasets[0].model_copy(update={"modality": "not-a-real-modality"})
    broken = graph.model_copy(update={"datasets": [bad, *graph.datasets[1:]]})
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.INVALID_VOCABULARY in _kinds(excinfo.value)


def test_programme_study_mismatch_is_rejected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    dataset = graph.datasets[0]
    other_programme = next(p.id for p in config.programmes if p.id != dataset.programme_id)
    bad = dataset.model_copy(update={"programme_id": other_programme})
    broken = graph.model_copy(update={"datasets": [bad, *graph.datasets[1:]]})
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.RELATIONSHIP in _kinds(excinfo.value)


def test_governance_inconsistency_is_rejected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    dataset = graph.datasets[0]
    other_owner = next(t.id for t in config.teams if t.id != dataset.owner_ref)
    bad = dataset.model_copy(update={"owner_ref": other_owner})
    broken = graph.model_copy(update={"datasets": [bad, *graph.datasets[1:]]})
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.CONSISTENCY in _kinds(excinfo.value)


def test_unsupported_modality_metadata_is_rejected(
    graph: TruthGraph, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    modality_dataset = next(d for d in graph.datasets if not d.is_reference)
    bad = modality_dataset.model_copy(update={"modality_metadata": {"bogus_key": 1}})
    broken = graph.model_copy(
        update={"datasets": [bad, *(d for d in graph.datasets if d.id != bad.id)]}
    )
    with pytest.raises(TruthValidationError) as excinfo:
        validate_truth_graph(broken, config, plan)
    assert TruthIssueKind.METADATA in _kinds(excinfo.value)
