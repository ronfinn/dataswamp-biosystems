"""Control-partition tests: emission, joins, determinism, and metrics readiness.

The control partition is the benchmark's *negative* class — every catalogue
asset and file that carries no injected defect. These tests pin the externally
meaningful contract: what is emitted, that it joins to the estate and the
observed graph, that it never overlaps the mutated population, and that the
emitted ground truth alone is sufficient to compute a confusion matrix.
"""

from __future__ import annotations

import json

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.engine import generate_observed
from dataswamp_biosystems.observed.entities import ControlReason
from dataswamp_biosystems.observed.index import GraphIndex
from dataswamp_biosystems.observed.profiles import ObservedProfile, profile_spec
from dataswamp_biosystems.observed.writer import (
    CONTROLS_NAME,
    RULE_SCOPE_NAME,
    observed_bytes,
)
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.observed.conftest import TEST_SEED


@pytest.fixture(scope="module")
def demo(graph: TruthGraph, config: CanonicalConfig):  # type: ignore[no-untyped-def]
    return generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED)


# -- emission -----------------------------------------------------------------


def test_control_partition_is_emitted(demo) -> None:  # type: ignore[no-untyped-def]
    files = observed_bytes(demo)
    assert CONTROLS_NAME in files
    assert RULE_SCOPE_NAME in files
    assert demo.controls
    rows = [json.loads(line) for line in files[CONTROLS_NAME].decode().splitlines()]
    assert len(rows) == len(demo.controls)
    assert all(row["synthetic"] is True for row in rows)
    assert all(row["expected_status"] == "clean" for row in rows)


def test_control_ids_resolve_to_truth_assets_and_files(
    demo, graph: TruthGraph, config: CanonicalConfig
) -> None:  # type: ignore[no-untyped-def]
    index = GraphIndex(graph, config)
    known = set(index.asset_ids()) | set(index.file_ids())
    for control in demo.controls:
        assert control.id in known
        assert index.truth_record(control.shard, control.id) is not None


def test_control_ids_resolve_in_the_observed_graph(demo) -> None:  # type: ignore[no-untyped-def]
    by_shard = {
        shard: {record["id"] for record in records}
        for shard, records in demo.observed_graph.items()
        if shard != "meta"
    }
    for control in demo.controls:
        assert control.id in by_shard[control.shard]


def test_controls_and_mutated_entities_never_overlap(demo) -> None:  # type: ignore[no-untyped-def]
    control_ids = {control.id for control in demo.controls}
    assert not control_ids & {instance.entity_id for instance in demo.instances}
    assert not control_ids & {mutation.entity_id for mutation in demo.mutations}


def test_control_ids_are_unique(demo) -> None:  # type: ignore[no-untyped-def]
    ids = [control.id for control in demo.controls]
    assert len(ids) == len(set(ids))


def test_reserved_controls_are_never_eligible_for_any_rule(demo) -> None:  # type: ignore[no-untyped-def]
    reserved = {control.id for control in demo.controls if control.reserved}
    assert reserved
    for control in demo.controls:
        if control.reserved:
            assert control.eligible_rule_count == 0
    for scope in demo.rule_scopes:
        assert not set(scope.eligible_ids) & reserved


def test_eligible_unselected_entities_are_represented_as_controls(demo) -> None:  # type: ignore[no-untyped-def]
    unselected = [c for c in demo.controls if c.reason is ControlReason.ELIGIBLE_UNSELECTED]
    assert unselected, "the demo profile must leave eligible-but-undrawn entities clean"
    for control in unselected:
        assert control.reserved is False
        assert control.eligible_rule_count > 0


def test_every_clean_asset_or_file_is_emitted_as_a_control(
    demo, graph: TruthGraph, config: CanonicalConfig
) -> None:  # type: ignore[no-untyped-def]
    """No eligible artefact may be silently omitted from the evaluation population."""
    index = GraphIndex(graph, config)
    population = set(index.asset_ids()) | set(index.file_ids())
    defective = {i.entity_id for i in demo.instances} | {m.entity_id for m in demo.mutations}
    assert {c.id for c in demo.controls} == population - defective


def test_control_reasons_are_exhaustive_and_consistent(demo) -> None:  # type: ignore[no-untyped-def]
    for control in demo.controls:
        assert control.reason in set(ControlReason)
        if control.reason is ControlReason.MEMBER_OF_RESERVED_ASSET:
            assert control.parent_asset_id
            assert control.entity_kind == "file"
        if control.reason is ControlReason.RESERVED_ASSET:
            assert control.entity_kind in {"dataset", "data_product"}


def test_summary_reports_control_totals(demo) -> None:  # type: ignore[no-untyped-def]
    totals = demo.summary["totals"]
    assert totals["control_records"] == len(demo.controls)
    assert totals["reserved_controls"] == sum(1 for c in demo.controls if c.reserved)
    assert sum(demo.summary["by_control_reason"].values()) == len(demo.controls)


# -- rule scope ---------------------------------------------------------------


def test_rule_scope_covers_every_rule_with_structured_counts(demo) -> None:  # type: ignore[no-untyped-def]
    from dataswamp_biosystems.observed.defects import DEFECTS

    assert {scope.id for scope in demo.rule_scopes} == set(DEFECTS)
    for scope in demo.rule_scopes:
        assert scope.eligible_count == len(scope.eligible_ids)
        assert scope.control_excluded_count == len(scope.control_excluded_ids)
        assert scope.selected_count == len(scope.selected_ids)
        assert scope.eligible_count + scope.control_excluded_count == scope.population_count
        assert not set(scope.eligible_ids) & set(scope.control_excluded_ids)
        assert set(scope.selected_ids) <= set(scope.eligible_ids)


def test_rule_scope_selected_ids_match_the_defect_instances(demo) -> None:  # type: ignore[no-untyped-def]
    by_rule: dict[str, set[str]] = {}
    for instance in demo.instances:
        by_rule.setdefault(instance.rule_id, set()).add(instance.entity_id)
    for scope in demo.rule_scopes:
        assert set(scope.selected_ids) == by_rule.get(scope.id, set())


# -- determinism and ordering -------------------------------------------------


def test_control_emission_is_deterministic(graph: TruthGraph, config: CanonicalConfig) -> None:
    first = observed_bytes(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED))
    second = observed_bytes(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED))
    assert first[CONTROLS_NAME] == second[CONTROLS_NAME]
    assert first[RULE_SCOPE_NAME] == second[RULE_SCOPE_NAME]


def test_control_ordering_is_id_sorted(demo) -> None:  # type: ignore[no-untyped-def]
    rows = [json.loads(line) for line in observed_bytes(demo)[CONTROLS_NAME].decode().splitlines()]
    ids = [row["id"] for row in rows]
    assert ids == sorted(ids)
    for scope in demo.rule_scopes:
        assert scope.eligible_ids == sorted(scope.eligible_ids)
        assert scope.selected_ids == sorted(scope.selected_ids)


def test_a_different_defect_seed_changes_the_partition(
    graph: TruthGraph, config: CanonicalConfig
) -> None:
    first = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED)
    other = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED + 1)
    assert {c.id for c in first.controls} != {c.id for c in other.controls}


# -- profile edge cases -------------------------------------------------------


def test_gold_profile_is_control_only(graph: TruthGraph, config: CanonicalConfig) -> None:
    """The zero-defect profile must yield an all-control, all-reserved partition."""
    result = generate_observed(graph, config, ObservedProfile.GOLD, TEST_SEED)
    index = GraphIndex(graph, config)
    assert result.instances == []
    assert {c.id for c in result.controls} == set(index.asset_ids()) | set(index.file_ids())
    assert all(control.reserved for control in result.controls)
    assert all(scope.selected_count == 0 for scope in result.rule_scopes)
    assert all(scope.eligible_count == 0 for scope in result.rule_scopes)


@pytest.mark.parametrize(
    "profile", [ObservedProfile.DEMO, ObservedProfile.CATASTROPHIC, ObservedProfile.MOSTLY_GOOD]
)
def test_profiles_retain_a_valid_control_partition(
    graph: TruthGraph, config: CanonicalConfig, profile: ObservedProfile
) -> None:
    result = generate_observed(graph, config, profile, TEST_SEED)
    control_ids = {control.id for control in result.controls}
    assert control_ids, f"profile {profile.value} must retain controls"
    assert not control_ids & {i.entity_id for i in result.instances}
    assert not control_ids & {m.entity_id for m in result.mutations}
    expected_fraction = profile_spec(profile).control_fraction
    assert all(c.control_fraction == expected_fraction for c in result.controls)


def test_controls_are_unchanged_from_truth_in_the_observed_graph(
    graph: TruthGraph, config: CanonicalConfig
) -> None:
    """Semantic evidence of cleanliness: a control's observed record equals truth."""
    result = generate_observed(graph, config, ObservedProfile.CATASTROPHIC, TEST_SEED)
    index = GraphIndex(graph, config)
    observed = {
        shard: {record["id"]: record for record in records}
        for shard, records in result.observed_graph.items()
        if shard != "meta"
    }
    for control in result.controls:
        assert observed[control.shard][control.id] == index.truth_record(control.shard, control.id)


def test_control_ids_join_to_the_materialized_estate(demo, graph: TruthGraph) -> None:  # type: ignore[no-untyped-def]
    """Pin the real join contract between controls and the generated file estate.

    The estate mints its own ``gf-…`` ids for generated files, so a truth
    ``file-…`` control joins through ``parent_asset_id``, not by file id. Asset
    controls join directly to the manifest's ``asset_id``.
    """
    from dataswamp_biosystems.estate import Profile, iter_file_plans

    plans = iter_file_plans(graph, Profile.TINY, TEST_SEED)
    estate_asset_ids = {plan.asset_id for plan in plans}
    estate_file_ids = {plan.file_id for plan in plans}
    assert estate_asset_ids

    asset_controls = {c.id for c in demo.controls if c.entity_kind != "file"}
    assert asset_controls & estate_asset_ids, "asset controls must join on asset_id"

    file_controls = [c for c in demo.controls if c.entity_kind == "file"]
    assert file_controls
    assert not {c.id for c in file_controls} & estate_file_ids
    assert all(c.parent_asset_id for c in file_controls)
    assert {c.parent_asset_id for c in file_controls} & estate_asset_ids


# -- metrics readiness --------------------------------------------------------


def test_emitted_ground_truth_supports_a_confusion_matrix(demo) -> None:  # type: ignore[no-untyped-def]
    """The emitted artefacts alone must classify a hypothetical agent's findings.

    Scoring itself is a later milestone; this proves the *data contract* is
    sufficient — positives come from ``expected-findings.jsonl`` and negatives
    from ``controls.jsonl``, joined on stable entity ids.
    """
    expected_positives = {(f.entity_id, f.rule_id) for f in demo.findings}
    control_ids = {control.id for control in demo.controls}

    # A hypothetical agent: it detects all but two real defects, and raises one
    # spurious finding against a control entity.
    missed = sorted(expected_positives)[:2]
    false_alarm = (sorted(control_ids)[0], "MDC-MISSING-DESCRIPTION")
    agent_findings = (expected_positives - set(missed)) | {false_alarm}

    true_positives = agent_findings & expected_positives
    false_positives = agent_findings - expected_positives
    false_negatives = expected_positives - agent_findings
    flagged_entities = {entity_id for entity_id, _ in agent_findings}
    true_negatives = control_ids - flagged_entities

    assert len(true_positives) == len(expected_positives) - 2
    assert false_positives == {false_alarm}
    assert len(false_negatives) == 2
    assert len(true_negatives) == len(control_ids) - 1

    precision = len(true_positives) / (len(true_positives) + len(false_positives))
    recall = len(true_positives) / (len(true_positives) + len(false_negatives))
    specificity = len(true_negatives) / len(control_ids)
    assert 0.0 < precision < 1.0
    assert 0.0 < recall < 1.0
    assert 0.0 < specificity < 1.0


def test_per_rule_specificity_denominator_is_derivable(demo) -> None:  # type: ignore[no-untyped-def]
    """Rule-scope plus controls give a per-rule negative population."""
    control_ids = {control.id for control in demo.controls}
    fired = [scope for scope in demo.rule_scopes if scope.selected_count]
    assert fired
    # An entity eligible for a rule but not selected by it is either a control or
    # carries a defect from a *different* rule — directly, or via a mutation whose
    # instance is anchored elsewhere (e.g. a file mutated under a dataset's rule).
    defective_elsewhere = {i.entity_id for i in demo.instances} | {
        m.entity_id for m in demo.mutations
    }
    for scope in fired:
        negatives = set(scope.eligible_ids) - set(scope.selected_ids)
        assert negatives <= control_ids | defective_elsewhere
        assert scope.eligible_count - scope.selected_count == len(negatives)
        # The clean negatives are exactly the controls still eligible for this rule.
        assert negatives & control_ids == set(scope.eligible_ids) & control_ids
