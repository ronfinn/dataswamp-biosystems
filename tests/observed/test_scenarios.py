"""The adversarial scenario model: constructed cases, and the honesty of near misses.

The claim under test is not "nineteen scenarios were produced". It is that the
adversarial tier is *constructed* rather than relabelled — every case names a
situation the observed graph actually contains — and that a near miss is
genuinely clean. A near miss that is really a defect would put a positive in the
negative class, quietly making every correct agent look wrong, so it is attacked
from several directions here rather than asserted once.
"""

from __future__ import annotations

from typing import Any

import pytest

from dataswamp_biosystems.company import load_config
from dataswamp_biosystems.observed.difficulty import Difficulty
from dataswamp_biosystems.observed.engine import ObservedResult, generate_observed
from dataswamp_biosystems.observed.index import GraphIndex
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.scenarios import (
    CASE_TYPE_ORDER,
    NEAR_MISS_DEFS,
    NEAR_MISS_VALIDITY_CHECKS,
    REQUIRED_CASE_TYPES,
    SCENARIO_CLASSES,
    CaseType,
    ExpectedDetection,
    ExpectedRemediationBehaviour,
    ScenarioCase,
    ScenarioPolarity,
    coverage_problems,
    near_miss_scenario_id,
    plan_scenarios,
    positive_scenario_id,
    scenario_coverage,
)
from dataswamp_biosystems.truth import generate_truth_graph, load_generation_plan
from tests.conftest import CONFIG_DIR


@pytest.fixture(scope="module")
def result() -> ObservedResult:
    config = load_config(CONFIG_DIR)
    plan = load_generation_plan(CONFIG_DIR)
    graph = generate_truth_graph(config, plan, 20260717)
    return generate_observed(graph, config, ObservedProfile.DEMO, 20260717, Difficulty.ADVERSARIAL)


# ---------------------------------------------------------------------------
# The case vocabulary
# ---------------------------------------------------------------------------


def test_no_case_type_is_an_ordinary_single_entity_defect() -> None:
    """There is deliberately no ``direct`` case: that is what bronze already is.

    Admitting one would let the adversarial tier be padded with cases that are
    not adversarial, which is exactly the relabelling this milestone forbids.
    """
    assert "direct" not in {case_type.value for case_type in CaseType}


def test_every_case_type_is_required_and_ordered_exactly_once() -> None:
    assert frozenset(CaseType) == REQUIRED_CASE_TYPES
    assert set(CASE_TYPE_ORDER) == set(CaseType)
    assert len(CASE_TYPE_ORDER) == len(set(CASE_TYPE_ORDER))


def test_every_scenario_class_names_only_registered_rules() -> None:
    from dataswamp_biosystems.observed.defects import DEFECTS

    for scenario_class in SCENARIO_CLASSES:
        assert scenario_class.rule_ids
        for rule_id in scenario_class.rule_ids:
            assert rule_id in DEFECTS, f"{scenario_class.key} names unknown rule {rule_id}"


def test_every_near_miss_definition_names_a_registered_rule_and_a_real_check() -> None:
    from dataswamp_biosystems.observed.defects import DEFECTS

    for definition in NEAR_MISS_DEFS:
        assert definition.mimicked_rule_id in DEFECTS
        assert definition.validity_check in NEAR_MISS_VALIDITY_CHECKS


def test_a_case_type_outside_the_enum_is_rejected() -> None:
    with pytest.raises(ValueError):
        CaseType("sideways-ambiguity")


# ---------------------------------------------------------------------------
# Identity and ordering
# ---------------------------------------------------------------------------


def test_scenario_ids_are_derived_from_the_case_never_from_a_counter(
    result: ObservedResult,
) -> None:
    """A counter-derived id would move whenever the number of cases changed."""
    for case in result.scenarios:
        entity_id = case.target_entity_ids[0]
        if case.is_near_miss:
            key = case.id.removeprefix("scn-nearmiss-").removesuffix(f"-{entity_id}")
            assert case.id == near_miss_scenario_id(key, entity_id)
        else:
            key = case.id.removeprefix("scn-").removesuffix(f"-{entity_id}")
            assert case.id == positive_scenario_id(key, entity_id)


def test_scenario_and_transformation_ids_are_unique_and_sorted(
    result: ObservedResult,
) -> None:
    ids = [case.id for case in result.scenarios]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)
    transformation_ids = [record.id for record in result.transformations]
    assert len(transformation_ids) == len(set(transformation_ids))
    assert transformation_ids == sorted(transformation_ids)


def test_generation_is_deterministic_for_a_fixed_seed() -> None:
    config = load_config(CONFIG_DIR)
    plan = load_generation_plan(CONFIG_DIR)
    graph = generate_truth_graph(config, plan, 20260717)
    first = generate_observed(graph, config, ObservedProfile.DEMO, 20260717, Difficulty.ADVERSARIAL)
    second = generate_observed(
        graph, config, ObservedProfile.DEMO, 20260717, Difficulty.ADVERSARIAL
    )
    assert [case.model_dump(mode="json") for case in first.scenarios] == [
        case.model_dump(mode="json") for case in second.scenarios
    ]
    assert [r.model_dump(mode="json") for r in first.transformations] == [
        r.model_dump(mode="json") for r in second.transformations
    ]


def test_planning_consults_no_random_state_for_near_misses() -> None:
    """Near misses are drawn from the sorted reserved partition, not shuffled.

    Asserted by planning at two different seeds and getting the same entities:
    if a draw were involved, the seeds would disagree.
    """
    config = load_config(CONFIG_DIR)
    plan_spec = load_generation_plan(CONFIG_DIR)
    graph = generate_truth_graph(config, plan_spec, 20260717)
    index = GraphIndex(graph, config)
    reserved = {record["id"] for record in graph.model_dump(mode="json")["datasets"][:40]}
    first = plan_scenarios(index, set(reserved), defect_seed=1)
    second = plan_scenarios(index, set(reserved), defect_seed=999)
    assert [p.entity_id for p in first.near_misses] == [p.entity_id for p in second.near_misses]


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_the_canonical_adversarial_benchmark_covers_every_required_case_type(
    result: ObservedResult,
) -> None:
    coverage = result.summary["scenarios"]
    assert coverage["uncovered_required_case_types"] == []
    for case_type in CaseType:
        assert coverage["by_case_type"][case_type.value] > 0, case_type.value
    assert coverage_problems(coverage) == []


def test_coverage_reports_a_missing_case_class_as_a_problem() -> None:
    """An adversarial benchmark missing a case class must fail, not ship quietly."""
    coverage = scenario_coverage([], [])
    problems = coverage_problems(coverage)
    assert len(problems) == len(CaseType) + 1  # every case type, plus "no near misses"
    assert any("near-miss-control" in problem for problem in problems)
    assert any("no near-miss controls were constructed" in problem for problem in problems)


def test_coverage_counts_agree_with_the_emitted_ledgers(result: ObservedResult) -> None:
    totals = result.summary["scenarios"]["totals"]
    assert totals["scenarios"] == len(result.scenarios)
    assert totals["transformations"] == len(result.transformations)
    assert totals["positive_scenarios"] + totals["near_miss_controls"] == len(result.scenarios)
    assert totals["near_miss_controls"] == sum(1 for c in result.scenarios if c.is_near_miss)


def test_coverage_does_not_demand_every_rule_or_category(result: ObservedResult) -> None:
    """The initial set is focused on purpose; requiring full coverage would force padding."""
    from dataswamp_biosystems.observed.defects import DEFECTS

    coverage = result.summary["scenarios"]
    assert 0 < len(coverage["rules_represented"]) < len(DEFECTS)


# ---------------------------------------------------------------------------
# Structural claims about the emitted cases
# ---------------------------------------------------------------------------


def test_every_case_is_labelled_adversarial_whatever_its_rules_tier(
    result: ObservedResult,
) -> None:
    """The tier is a property of the construction, not of the rule.

    The same rules appear at bronze/silver/gold elsewhere, and must keep those
    tiers there — this asserts only that a *case* is adversarial.
    """
    from dataswamp_biosystems.observed.difficulty import difficulty_for

    for case in result.scenarios:
        assert case.difficulty is Difficulty.ADVERSARIAL
        for rule_id in case.rule_ids:
            assert difficulty_for(rule_id) is not Difficulty.ADVERSARIAL


def test_positive_cases_name_a_finding_and_expect_a_flag(result: ObservedResult) -> None:
    finding_ids = {finding.id for finding in result.findings}
    for case in result.scenarios:
        if case.is_near_miss:
            continue
        assert case.polarity is ScenarioPolarity.POSITIVE
        assert case.expected_detection is ExpectedDetection.FLAG
        assert case.finding_ids
        assert set(case.finding_ids) <= finding_ids
        assert not case.control_ids


def test_near_miss_cases_name_no_finding_and_expect_no_flag(result: ObservedResult) -> None:
    for case in result.scenarios:
        if not case.is_near_miss:
            continue
        assert case.expected_detection is ExpectedDetection.NO_FLAG
        assert case.expected_remediation is ExpectedRemediationBehaviour.NOT_APPLICABLE
        assert case.finding_ids == []
        assert case.control_ids == case.target_entity_ids
        assert case.transformation_ids


def test_a_no_remediation_case_expects_an_explicit_no_action_decision(
    result: ObservedResult,
) -> None:
    from dataswamp_biosystems.observed.entities import RemediationAvailability

    by_finding = {remediation.finding_id: remediation for remediation in result.remediations}
    cases = [c for c in result.scenarios if c.case_type is CaseType.NO_REMEDIATION]
    assert cases, "the no-remediation class produced nothing to check"
    for case in cases:
        assert case.expected_remediation is ExpectedRemediationBehaviour.NO_REMEDIATION
        for finding_id in case.finding_ids:
            assert by_finding[finding_id].availability is RemediationAvailability.NONE


def test_an_overlapping_evidence_case_attributes_two_rules_to_one_entity(
    result: ObservedResult,
) -> None:
    cases = [c for c in result.scenarios if c.case_type is CaseType.OVERLAPPING_EVIDENCE]
    assert cases, "the overlapping-evidence class produced nothing to check"
    for case in cases:
        assert len(case.rule_ids) >= 2
        assert len(case.target_entity_ids) == 1
        assert len(case.finding_ids) == len(case.rule_ids)


def test_a_decoy_case_names_a_decoy_that_mimics_its_own_rule(result: ObservedResult) -> None:
    """A decoy dressed under some unrelated rule would not confuse anything."""
    mimicked_by_entity = {
        record.entity_id: record.mimicked_rule_id for record in result.transformations
    }
    cases = [c for c in result.scenarios if c.case_type is CaseType.DECOY_CANDIDATE]
    assert cases, "the decoy class produced nothing to check"
    for case in cases:
        assert case.decoy_entity_ids, f"{case.id} claims a decoy case with no decoy"
        for decoy in case.decoy_entity_ids:
            assert mimicked_by_entity.get(decoy) in case.rule_ids


def test_evidence_entities_resolve_against_the_truth_graph(result: ObservedResult) -> None:
    """Evidence names what *should* be there, so it is resolved against truth.

    An evidence record may legitimately be missing from the observed graph — for
    ``SCH-CONTRACT-MISSING`` that absence is the defect — so resolving against the
    observed graph would force the case to omit the very thing a detector has to
    notice is gone.
    """
    config = load_config(CONFIG_DIR)
    plan = load_generation_plan(CONFIG_DIR)
    index = GraphIndex(generate_truth_graph(config, plan, 20260717), config)
    known = {
        str(row["id"])
        for records in index.truth.values()
        for row in records
        if isinstance(row, dict) and "id" in row
    }
    for case in result.scenarios:
        unresolved = [e for e in case.evidence_entity_ids if e not in known]
        assert not unresolved, f"{case.id} names unresolved evidence {unresolved}"


def test_at_least_one_case_names_evidence_the_defect_removed(result: ObservedResult) -> None:
    """Guard the guard above: the truth/observed distinction must actually bite."""
    observed_ids: set[str] = set()
    for shard, records in result.observed_graph.items():
        if shard == "meta" or not isinstance(records, list):
            continue
        observed_ids.update(
            str(row["id"]) for row in records if isinstance(row, dict) and "id" in row
        )
    assert any(
        evidence not in observed_ids
        for case in result.scenarios
        for evidence in case.evidence_entity_ids
    )


def test_a_case_may_not_declare_a_target_that_is_also_a_decoy(result: ObservedResult) -> None:
    for case in result.scenarios:
        assert not set(case.target_entity_ids) & set(case.decoy_entity_ids)


def test_the_model_rejects_an_undeclared_extra_field() -> None:
    payload: dict[str, Any] = {
        "id": "scn-x-ds-1",
        "difficulty": "adversarial",
        "case_type": "near-miss-control",
        "polarity": "near-miss-control",
        "reasoning_scope": "single-record",
        "rule_ids": ["SCH-SIZE-INVERSION"],
        "target_entity_ids": ["ds-1"],
        "expected_detection": "no-flag",
        "expected_remediation": "not-applicable",
        "rationale": "x",
        "profile": "demo",
        "defect_seed": 1,
        "truth_seed": 1,
        "smuggled_answer": "ds-1",
    }
    with pytest.raises(ValueError):
        ScenarioCase.model_validate(payload)
