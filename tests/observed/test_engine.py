"""Behavioural tests for the imperfection engine.

Covers determinism, truth immutability, profile behaviour (gold/demo/typical),
control population, referential integrity, mutation fidelity, incompatibility,
and the per-entity cap.
"""

from __future__ import annotations

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.defects import DEFECTS
from dataswamp_biosystems.observed.engine import ObservedResult, generate_observed
from dataswamp_biosystems.observed.entities import ChangeOp
from dataswamp_biosystems.observed.index import GraphIndex
from dataswamp_biosystems.observed.profiles import ObservedProfile, profile_spec
from dataswamp_biosystems.observed.writer import observed_bytes
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.observed.conftest import TEST_SEED


@pytest.fixture(scope="module")
def demo(graph: TruthGraph, config: CanonicalConfig) -> ObservedResult:
    return generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED)


def test_in_process_generation_is_deterministic(graph: TruthGraph, config: CanonicalConfig) -> None:
    first = observed_bytes(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED))
    second = observed_bytes(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED))
    assert first == second


def test_different_seed_changes_output(graph: TruthGraph, config: CanonicalConfig) -> None:
    first = observed_bytes(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED))
    other = observed_bytes(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED + 1))
    assert first != other


def test_truth_graph_is_not_mutated(graph: TruthGraph, config: CanonicalConfig) -> None:
    before = graph.model_dump(mode="json")
    for profile in ObservedProfile:
        generate_observed(graph, config, profile, TEST_SEED)
    assert graph.model_dump(mode="json") == before


def test_gold_profile_injects_nothing(graph: TruthGraph, config: CanonicalConfig) -> None:
    result = generate_observed(graph, config, ObservedProfile.GOLD, TEST_SEED)
    assert result.instances == []
    assert result.mutations == []


def test_demo_defect_count_in_band(demo: ObservedResult) -> None:
    assert 100 <= len(demo.instances) <= 200


def test_demo_covers_all_categories(demo: ObservedResult) -> None:
    categories = {instance.category for instance in demo.instances}
    assert len(categories) == 12


def test_demo_leaves_clean_controls(demo: ObservedResult) -> None:
    totals = demo.summary["totals"]
    assert totals["control_assets"] > 0
    assert totals["clean_assets"] > 0


def test_typical_fires_every_rule(graph: TruthGraph, config: CanonicalConfig) -> None:
    result = generate_observed(graph, config, ObservedProfile.TYPICAL, TEST_SEED)
    assert set(result.summary["by_rule"]) == set(DEFECTS)


def test_ledger_is_referentially_complete(demo: ObservedResult) -> None:
    instance_ids = {i.id for i in demo.instances}
    finding_ids = {f.id for f in demo.findings}
    mutation_ids = {m.id for m in demo.mutations}
    assert {m.instance_id for m in demo.mutations} <= instance_ids
    assert {f.instance_id for f in demo.findings} == instance_ids
    assert {r.instance_id for r in demo.remediations} == instance_ids
    for instance in demo.instances:
        assert instance.finding_id in finding_ids
        assert set(instance.mutation_ids) <= mutation_ids
        assert len(instance.mutation_ids) >= 1


def test_mutation_before_matches_truth(
    demo: ObservedResult, graph: TruthGraph, config: CanonicalConfig
) -> None:
    index = GraphIndex(graph, config)
    for mutation in demo.mutations:
        record = index.truth_record(mutation.shard, mutation.entity_id)
        if mutation.operation is ChangeOp.ADD_RECORD:
            continue
        if mutation.operation is ChangeOp.DELETE_RECORD:
            assert mutation.before == record
        else:
            expected = record.get(mutation.field) if record is not None else None
            assert mutation.before == expected


def test_no_incompatible_rules_coexist(demo: ObservedResult) -> None:
    rules_by_entity: dict[str, set[str]] = {}
    for instance in demo.instances:
        rules_by_entity.setdefault(instance.entity_id, set()).add(instance.rule_id)
    for rules in rules_by_entity.values():
        for rule_id in rules:
            assert not (set(DEFECTS[rule_id].incompatibilities) & (rules - {rule_id}))


def test_per_entity_cap_respected(demo: ObservedResult) -> None:
    cap = profile_spec(ObservedProfile.DEMO).max_per_entity
    counts: dict[str, int] = {}
    for instance in demo.instances:
        counts[instance.entity_id] = counts.get(instance.entity_id, 0) + 1
    assert max(counts.values()) <= cap


def test_defects_spread_across_modalities_and_assets(demo: ObservedResult) -> None:
    groups = demo.summary["by_modality_group"]
    assert len(groups) >= 4
    # No single asset absorbs a large share of the defects.
    counts: dict[str, int] = {}
    for instance in demo.instances:
        counts[instance.entity_id] = counts.get(instance.entity_id, 0) + 1
    assert max(counts.values()) <= max(3, len(demo.instances) // 20)


def test_mutation_records_carry_required_fields(demo: ObservedResult) -> None:
    for mutation in demo.mutations:
        assert mutation.seed == TEST_SEED
        assert mutation.profile == "demo"
        assert mutation.selection_rationale
        assert mutation.severity.value in {"low", "medium", "high"}
        assert mutation.manifestation in {"metadata", "physical"}
        # Deletion/missing-value defects still preserve the canonical previous value.
        if mutation.operation.value in {"delete_record", "set", "set_list"}:
            assert mutation.before is not None or mutation.field == "present"


def test_findings_carry_match_fields_and_links(demo: ObservedResult) -> None:
    remediation_ids = {r.id for r in demo.remediations}
    for finding in demo.findings:
        assert finding.match_fields["rule_id"] == finding.rule_id
        assert finding.match_fields["entity_id"] == finding.entity_id
        assert finding.match_fields["category"] == finding.category.value
        assert finding.expected_message_semantics
        assert finding.remediation_id in remediation_ids


def test_remediations_reference_truth(demo: ObservedResult) -> None:
    for remediation in demo.remediations:
        assert remediation.truth_reference is not None
        assert isinstance(remediation.auto_fixable, bool)
        assert isinstance(remediation.requires_human_approval, bool)
