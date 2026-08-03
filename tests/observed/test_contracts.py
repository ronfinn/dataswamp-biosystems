"""The rule and remediation contract: declarations are enforced, not decorative.

Every defect rule declares what it may change, whether a correct fix can be
derived mechanically, and whether a human must authorise it. These tests prove
those declarations are a *contract*: generated evidence is checked against them,
a rule whose evidence drifts from its declaration is reported with the rule, the
entity and the violated field named, and the catalogue keeps every benchmark
state populated.

Remediation availability and approval policy are deliberately independent axes.
Tests here assert that independence directly, because collapsing them back into a
single "fixability" scale is the specific regression this milestone exists to
prevent.
"""

from __future__ import annotations

import dataclasses

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.defects import (
    DEFECTS,
    REQUIRED_CONTRACT_STATES,
    RULE_CONTRACTS,
    contract_coverage,
    validate_registry,
)
from dataswamp_biosystems.observed.engine import ObservedResult, generate_observed
from dataswamp_biosystems.observed.entities import (
    NO_REMEDIATION_ACTION,
    ApprovalEvidence,
    ApprovalPolicy,
    ApproverRole,
    ChangeOp,
    NonRemediableReason,
    RemediationAvailability,
)
from dataswamp_biosystems.observed.errors import (
    ObservedIssueCollector,
    ObservedIssueKind,
)
from dataswamp_biosystems.observed.index import GraphIndex
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.validate import _check_rule_contracts
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.observed.conftest import TEST_SEED

ALL_PROFILES = list(ObservedProfile)


@pytest.fixture(scope="module")
def result(graph: TruthGraph, config: CanonicalConfig) -> ObservedResult:
    return generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED)


@pytest.fixture(scope="module")
def index(graph: TruthGraph, config: CanonicalConfig) -> GraphIndex:
    return GraphIndex(graph, config)


def _contract_issues(result: ObservedResult, index: GraphIndex) -> list[str]:
    """Run only the contract checks and return rendered issues.

    Every issue these checks raise must use the ``rule-contract`` kind, so a
    consumer can filter contract breaches from other observed-state problems.
    """
    issues = ObservedIssueCollector()
    _check_rule_contracts(result, index, issues)
    assert all(i.kind is ObservedIssueKind.RULE_CONTRACT for i in issues.issues)
    return [i.render() for i in issues.issues]


def _patch_contract(monkeypatch: pytest.MonkeyPatch, rule_id: str, **changes: object) -> None:
    """Replace one rule's declaration so it disagrees with already-emitted evidence."""
    patched = dict(DEFECTS)
    patched[rule_id] = dataclasses.replace(DEFECTS[rule_id], **changes)  # type: ignore[arg-type]
    monkeypatch.setattr("dataswamp_biosystems.observed.validate.DEFECTS", patched)


# -- the declarations themselves ---------------------------------------------


def test_every_rule_declares_a_full_contract() -> None:
    """No rule may reach the catalogue without an explicit contract."""
    assert set(RULE_CONTRACTS) == set(DEFECTS)
    for rule_id, definition in DEFECTS.items():
        assert isinstance(definition.remediation_availability, RemediationAvailability), rule_id
        assert isinstance(definition.approval_policy, ApprovalPolicy), rule_id
        assert isinstance(definition.approver_role, ApproverRole), rule_id
        assert isinstance(definition.approval_evidence, ApprovalEvidence), rule_id
        assert isinstance(definition.non_remediable_reason, NonRemediableReason), rule_id
        assert definition.mutation_ops, rule_id
        assert all(isinstance(op, ChangeOp) for op in definition.mutation_ops), rule_id
        assert definition.applies_to_kinds, rule_id
        assert definition.applies_to_modalities, rule_id


def test_registry_is_valid() -> None:
    assert validate_registry(DEFECTS) == []


def test_an_unregistered_rule_cannot_be_defined() -> None:
    """A rule with no contract entry is a hard error, not a silent default."""
    from dataswamp_biosystems.observed.defects import _def

    with pytest.raises(KeyError, match="RULE-THAT-DOES-NOT-EXIST"):
        _def(rule_id="RULE-THAT-DOES-NOT-EXIST")


def test_a_non_remediable_rule_may_not_declare_a_recommendation() -> None:
    """A contradicted declaration must fail loudly, not be quietly discarded."""
    from dataswamp_biosystems.observed.defects import _def

    with pytest.raises(TypeError, match="non-remediable"):
        _def(rule_id="FILE-MISSING", remediation_recommended="restore-from-truth")


def test_legacy_fixability_flags_cannot_be_declared_directly() -> None:
    """``auto_fixable`` is derived; setting it by hand would re-couple the axes."""
    from dataswamp_biosystems.observed.defects import _def

    with pytest.raises(TypeError, match="auto_fixable"):
        _def(rule_id="META-TITLE-MISSING", auto_fixable=True)


# -- independence of the two axes --------------------------------------------


def test_fixability_and_approval_are_independent() -> None:
    """Neither axis may be predicted from the other across the catalogue.

    If every automatic rule were also approval-free, an agent could infer one
    from the other and the benchmark would test a single scale, not two.
    """
    pairs = {
        (d.remediation_availability, d.approval_policy)
        for d in DEFECTS.values()
        if d.remediation_availability is not RemediationAvailability.NONE
    }
    assert (RemediationAvailability.AUTOMATIC, ApprovalPolicy.NOT_REQUIRED) in pairs
    assert (RemediationAvailability.AUTOMATIC, ApprovalPolicy.REQUIRED) in pairs
    assert (RemediationAvailability.MANUAL, ApprovalPolicy.NOT_REQUIRED) in pairs
    assert (RemediationAvailability.MANUAL, ApprovalPolicy.REQUIRED) in pairs
    assert len(pairs) == 4


def test_derived_booleans_track_their_own_axis_only() -> None:
    for definition in DEFECTS.values():
        assert definition.auto_fixable is (
            definition.remediation_availability is RemediationAvailability.AUTOMATIC
        )
        assert definition.requires_human_approval is (
            definition.approval_policy is ApprovalPolicy.REQUIRED
        )


@pytest.mark.parametrize("state", REQUIRED_CONTRACT_STATES)
def test_every_required_contract_state_is_populated(state: str) -> None:
    assert contract_coverage()[state], f"no rule covers contract state {state!r}"


def test_coverage_reports_exactly_the_required_states() -> None:
    assert set(contract_coverage()) == set(REQUIRED_CONTRACT_STATES)


def test_approval_metadata_is_present_exactly_when_approval_is_required() -> None:
    """An approval requirement with nobody able to grant it is not enforceable."""
    for definition in DEFECTS.values():
        if definition.approval_policy is ApprovalPolicy.REQUIRED:
            assert definition.approver_role is not ApproverRole.NONE, definition.rule_id
            assert definition.approval_evidence is not ApprovalEvidence.NONE, definition.rule_id
        else:
            assert definition.approver_role is ApproverRole.NONE, definition.rule_id
            assert definition.approval_evidence is ApprovalEvidence.NONE, definition.rule_id


def test_non_remediable_rules_state_a_reason_and_recommend_nothing() -> None:
    for definition in DEFECTS.values():
        if definition.is_remediable:
            assert definition.non_remediable_reason is NonRemediableReason.NONE
        else:
            assert definition.non_remediable_reason is not NonRemediableReason.NONE
            assert definition.remediation_recommended is None
            assert definition.action_class == NO_REMEDIATION_ACTION


# -- generated evidence matches the declarations ------------------------------


def test_generated_evidence_satisfies_every_declaration(
    result: ObservedResult, index: GraphIndex
) -> None:
    assert _contract_issues(result, index) == []


def test_every_emitted_record_carries_its_rules_contract(result: ObservedResult) -> None:
    for instance in result.instances:
        definition = DEFECTS[instance.rule_id]
        assert instance.remediation_availability is definition.remediation_availability
        assert instance.approval_policy is definition.approval_policy
        assert instance.approver_role is definition.approver_role
    for remediation in result.remediations:
        definition = DEFECTS[remediation.rule_id]
        assert remediation.availability is definition.remediation_availability
        assert remediation.approval_policy is definition.approval_policy
        assert remediation.approval_evidence is definition.approval_evidence
        assert remediation.auto_fixable is definition.auto_fixable
        assert remediation.requires_human_approval is definition.requires_human_approval


def test_every_finding_resolves_to_exactly_one_remediation(result: ObservedResult) -> None:
    """Including non-remediable ones: the decision is recorded, never omitted."""
    counts: dict[str, int] = {}
    for remediation in result.remediations:
        counts[remediation.finding_id] = counts.get(remediation.finding_id, 0) + 1
    assert {f.id: counts.get(f.id, 0) for f in result.findings} == {
        f.id: 1 for f in result.findings
    }


def test_non_remediable_findings_record_an_explicit_no_action_decision(
    result: ObservedResult,
) -> None:
    seen = 0
    for remediation in result.remediations:
        if DEFECTS[remediation.rule_id].is_remediable:
            assert remediation.action != NO_REMEDIATION_ACTION
            continue
        seen += 1
        assert remediation.action == NO_REMEDIATION_ACTION
        assert remediation.recommended_value is None
        assert remediation.non_remediable_reason is not NonRemediableReason.NONE
        # The truth reference survives: it is scoring ground truth, not a repair.
        assert remediation.truth_reference
    assert seen, "no non-remediable defect was injected to assert on"


def test_non_remediable_findings_declare_their_unavailability(result: ObservedResult) -> None:
    for finding in result.findings:
        definition = DEFECTS[finding.rule_id]
        assert finding.remediation_available is definition.remediation_availability
        if not definition.is_remediable:
            assert finding.non_remediable_reason is not NonRemediableReason.NONE


def test_every_mutation_uses_a_declared_operation(result: ObservedResult) -> None:
    for mutation in result.mutations:
        definition = DEFECTS[mutation.rule_id]
        assert mutation.operation in definition.mutation_ops, mutation.rule_id


def test_every_instance_is_within_its_rules_applicability(
    result: ObservedResult, index: GraphIndex
) -> None:
    from dataswamp_biosystems.observed.engine import modality_group_of

    for instance in result.instances:
        definition = DEFECTS[instance.rule_id]
        assert instance.entity_kind in definition.applies_to_kinds
        declared = set(definition.applies_to_modalities)
        if "*" not in declared:
            assert modality_group_of(index, instance.entity_id) in declared


# -- violations are caught, located and named ---------------------------------


def test_a_mutation_outside_the_declared_operations_is_caught(
    result: ObservedResult, index: GraphIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_contract(monkeypatch, "META-TITLE-MISSING", mutation_ops=(ChangeOp.ADD_RECORD,))
    issues = _contract_issues(result, index)
    offending = [i for i in issues if "mutation_ops" in i]
    assert offending, issues
    assert "META-TITLE-MISSING" in offending[0]
    assert "[rule-contract]" in offending[0]


def test_an_entity_outside_the_declared_applicability_is_caught(
    result: ObservedResult, index: GraphIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_contract(monkeypatch, "META-TITLE-MISSING", applies_to_kinds=["nothing_at_all"])
    offending = [i for i in _contract_issues(result, index) if "field=entity_kind" in i]
    assert offending
    assert "META-TITLE-MISSING" in offending[0]


def test_a_modality_outside_the_declared_applicability_is_caught(
    result: ObservedResult, index: GraphIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A modality-scoped rule reaching another modality is a mis-scoped benchmark."""
    _patch_contract(monkeypatch, "META-TITLE-MISSING", applies_to_modalities=["wgs-wes"])
    offending = [i for i in _contract_issues(result, index) if "applies_to_modalities" in i]
    assert offending
    assert "META-TITLE-MISSING" in offending[0]


def test_a_remediable_rule_emitting_no_remediation_is_caught(
    result: ObservedResult, index: GraphIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FILE-MISSING emitted a no-action decision; declaring it remediable must fail."""
    _patch_contract(
        monkeypatch,
        "FILE-MISSING",
        remediation_availability=RemediationAvailability.AUTOMATIC,
        non_remediable_reason=NonRemediableReason.NONE,
    )
    issues = _contract_issues(result, index)
    assert any("is remediable but the record declares no remediation" in i for i in issues), issues
    assert all("FILE-MISSING" in i for i in issues if "remediable" in i)


def test_a_non_remediable_rule_emitting_a_remediation_is_caught(
    result: ObservedResult, index: GraphIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The converse: META-TITLE-MISSING emitted a real fix; declaring it unfixable must fail."""
    _patch_contract(
        monkeypatch,
        "META-TITLE-MISSING",
        remediation_availability=RemediationAvailability.NONE,
        non_remediable_reason=NonRemediableReason.SOURCE_SYSTEM_RECOVERY,
    )
    issues = _contract_issues(result, index)
    assert any("is non-remediable but the record recommends" in i for i in issues), issues
    assert any("field=action" in i for i in issues), issues


def test_an_approval_policy_mismatch_is_caught_independently_of_fixability(
    result: ObservedResult, index: GraphIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flipping only approval must be caught without touching availability."""
    _patch_contract(
        monkeypatch,
        "META-TITLE-MISSING",
        approval_policy=ApprovalPolicy.REQUIRED,
        approver_role=ApproverRole.DATA_OWNER,
        approval_evidence=ApprovalEvidence.OWNER_SIGN_OFF,
    )
    issues = _contract_issues(result, index)
    assert any("field=approval_policy" in i for i in issues), issues
    assert any("field=requires_human_approval" in i for i in issues), issues
    # Availability was untouched, so no availability issue may be reported.
    assert not any("field=remediation_availability" in i for i in issues), issues


def test_a_fixability_mismatch_is_caught_independently_of_approval(
    result: ObservedResult, index: GraphIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_contract(
        monkeypatch,
        "META-TITLE-MISSING",
        remediation_availability=RemediationAvailability.AUTOMATIC,
    )
    issues = _contract_issues(result, index)
    assert any("field=remediation_availability" in i for i in issues), issues
    assert any("field=auto_fixable" in i for i in issues), issues
    assert not any("field=approval_policy" in i for i in issues), issues


def test_contract_violations_name_rule_entity_and_field(
    result: ObservedResult, index: GraphIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure must be actionable: which rule, which record, which declaration."""
    _patch_contract(
        monkeypatch,
        "META-TITLE-MISSING",
        remediation_availability=RemediationAvailability.AUTOMATIC,
    )
    issues = _contract_issues(result, index)
    assert issues
    for issue in issues:
        assert issue.startswith("[rule-contract] ")
        assert "id=" in issue
        assert "field=" in issue


# -- coverage is structured, reachable and deterministic ----------------------


@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_profile_summary_reports_contract_coverage(
    graph: TruthGraph, config: CanonicalConfig, profile: ObservedProfile
) -> None:
    summary = generate_observed(graph, config, profile, TEST_SEED).summary
    assert summary["contract_state_coverage"] == {
        state: len(rules) for state, rules in contract_coverage().items()
    }
    for key in ("by_contract_state", "by_action_class", "by_mutation_op"):
        assert key in summary
        assert summary[key] == dict(sorted(summary[key].items())), f"{key} is unsorted"


def test_every_contract_state_is_reachable_in_some_profile(
    graph: TruthGraph, config: CanonicalConfig
) -> None:
    """A declared state nobody can reach is a benchmark gap, not a nuance."""
    reached: set[str] = set()
    for profile in ALL_PROFILES:
        summary = generate_observed(graph, config, profile, TEST_SEED).summary
        reached |= {state for state, n in summary["by_contract_state"].items() if n}
    assert reached >= set(REQUIRED_CONTRACT_STATES), sorted(set(REQUIRED_CONTRACT_STATES) - reached)


def test_every_declared_mutation_op_is_reachable_in_some_profile(
    graph: TruthGraph, config: CanonicalConfig
) -> None:
    declared = {op.value for d in DEFECTS.values() for op in d.mutation_ops}
    reached: set[str] = set()
    for profile in ALL_PROFILES:
        summary = generate_observed(graph, config, profile, TEST_SEED).summary
        reached |= {op for op, n in summary["by_mutation_op"].items() if n}
    assert declared <= reached, sorted(declared - reached)


def test_every_action_class_is_reachable_in_some_profile(
    graph: TruthGraph, config: CanonicalConfig
) -> None:
    declared = {d.action_class for d in DEFECTS.values()}
    reached: set[str] = set()
    for profile in ALL_PROFILES:
        summary = generate_observed(graph, config, profile, TEST_SEED).summary
        reached |= {a for a, n in summary["by_action_class"].items() if n}
    assert declared <= reached, sorted(declared - reached)


@pytest.mark.parametrize("seed", [TEST_SEED, TEST_SEED + 1, 7])
def test_coverage_reporting_is_deterministic_across_seeds(
    graph: TruthGraph, config: CanonicalConfig, seed: int
) -> None:
    """Declared coverage never depends on the seed; fired counts are reproducible."""
    first = generate_observed(graph, config, ObservedProfile.DEMO, seed).summary
    second = generate_observed(graph, config, ObservedProfile.DEMO, seed).summary
    assert first["by_contract_state"] == second["by_contract_state"]
    assert first["by_mutation_op"] == second["by_mutation_op"]
    assert first["contract_state_coverage"] == {
        state: len(rules) for state, rules in contract_coverage().items()
    }


def test_contract_coverage_is_stable_and_sorted() -> None:
    coverage = contract_coverage()
    assert list(coverage) == sorted(coverage)
    for rules in coverage.values():
        assert rules == sorted(rules)
    assert contract_coverage() == coverage


def test_coverage_reports_a_gap_rather_than_hiding_it() -> None:
    """Emptying a state must be a registry error, not a silent pass."""
    reduced = {
        rule_id: d
        for rule_id, d in DEFECTS.items()
        if d.remediation_availability is not RemediationAvailability.NONE
    }
    problems = validate_registry(reduced)
    assert any("non-remediable" in p for p in problems), problems
