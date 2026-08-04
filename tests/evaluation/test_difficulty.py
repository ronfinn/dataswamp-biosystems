"""By-difficulty aggregation: a partition of the matrix, not a second sampling.

The exact-matrix tests use a purpose-built micro ground truth over three *real*
rule ids, one per tier, small enough to count on paper. The property tests use
the canonical scenario, where the claim that matters is arithmetic: the per-tier
cells must sum to the overall cells, every scored pair must belong to exactly one
tier, and nothing outside a rule's population may reach a tier denominator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    REPORTED_DIFFICULTIES,
    UNKNOWN_DIFFICULTY,
    evaluate,
    load_ground_truth,
)
from dataswamp_biosystems.evaluation.ground_truth import GroundTruth
from dataswamp_biosystems.evaluation.predictions import (
    PREDICTION_SCHEMA_VERSION,
    Prediction,
)
from dataswamp_biosystems.observed.difficulty import difficulty_for
from dataswamp_biosystems.observed.entities import (
    ApprovalEvidence,
    ApprovalPolicy,
    ApproverRole,
    ControlReason,
    ControlRecord,
    ExpectedFinding,
    ExpectedRemediation,
    NonRemediableReason,
    RemediationAvailability,
    RuleScopeRecord,
)

# One real rule per tier, so the tiering under test is the shipped tiering rather
# than a fixture that agrees with itself.
BRONZE_RULE = "OWN-OWNER-MISSING"
SILVER_RULE = "SCH-CONTRACT-MISSING"
GOLD_RULE = "SEM-DESC-GENERIC"

MICRO_SCOPES = (
    # rule, eligible, reserved-excluded, selected
    (BRONZE_RULE, ["ds-a", "ds-b", "ds-c"], ["ds-r"], ["ds-a"]),
    (SILVER_RULE, ["ds-a", "ds-b"], [], ["ds-a", "ds-b"]),
    (GOLD_RULE, ["ds-c", "ds-d"], ["ds-r"], ["ds-c"]),
)


def _micro_ground_truth() -> GroundTruth:
    """Eleven in-scope pairs across three tiers, countable by hand."""
    scopes: list[RuleScopeRecord] = []
    findings: list[ExpectedFinding] = []
    remediations: list[ExpectedRemediation] = []
    for rule_id, eligible, excluded, selected in MICRO_SCOPES:
        definition_category = _category_of(rule_id)
        slug = rule_id.lower()
        scopes.append(
            RuleScopeRecord(
                id=rule_id,
                category=definition_category[0],
                severity=definition_category[1],
                profile="micro",
                defect_seed=1,
                injection_rate=0.5,
                population_count=len(eligible) + len(excluded),
                control_excluded_count=len(excluded),
                eligible_count=len(eligible),
                candidate_count=len(eligible),
                selected_count=len(selected),
                eligible_ids=list(eligible),
                control_excluded_ids=list(excluded),
                selected_ids=list(selected),
            )
        )
        for entity_id in selected:
            finding_id = f"find-{slug}-{entity_id}"
            remediation_id = f"rem-{slug}-{entity_id}"
            findings.append(
                ExpectedFinding(
                    id=finding_id,
                    instance_id=f"di-{slug}-{entity_id}",
                    rule_id=rule_id,
                    category=definition_category[0],
                    severity=definition_category[1],
                    entity_kind="dataset",
                    entity_id=entity_id,
                    title=f"{rule_id} on {entity_id}",
                    description="synthetic micro-fixture finding",
                    observable_evidence="synthetic micro-fixture evidence",
                    expected_message_semantics="synthetic micro-fixture semantics",
                    detection_locator=f"dataset:{entity_id}",
                    remediation_available=RemediationAvailability.MANUAL,
                    non_remediable_reason=NonRemediableReason.NONE,
                    remediation_id=remediation_id,
                    match_fields={"rule_id": rule_id, "entity_id": entity_id},
                )
            )
            remediations.append(
                ExpectedRemediation(
                    id=remediation_id,
                    finding_id=finding_id,
                    instance_id=f"di-{slug}-{entity_id}",
                    rule_id=rule_id,
                    action="rewrite_field",
                    action_class="rewrite_field",
                    target=f"dataset/{entity_id}",
                    recommended_value=None,
                    truth_reference={"field": "value"},
                    availability=RemediationAvailability.MANUAL,
                    approval_policy=ApprovalPolicy.NOT_REQUIRED,
                    approver_role=ApproverRole.NONE,
                    approval_evidence=ApprovalEvidence.NONE,
                    non_remediable_reason=NonRemediableReason.NONE,
                    auto_fixable=False,
                    requires_human_approval=False,
                    reversible=True,
                )
            )

    controls = tuple(
        ControlRecord(
            id=entity_id,
            entity_kind="dataset",
            shard="datasets",
            reason=reason,
            reserved=reserved,
            parent_asset_id="",
            modality="",
            modality_group="",
            eligible_rule_count=1,
            profile="micro",
            defect_seed=1,
            truth_seed=1,
            control_fraction=0.25,
        )
        for entity_id, reason, reserved in (
            ("ds-b", ControlReason.ELIGIBLE_UNSELECTED, False),
            ("ds-d", ControlReason.ELIGIBLE_UNSELECTED, False),
            ("ds-r", ControlReason.RESERVED_ASSET, True),
        )
    )
    return GroundTruth(
        scopes=tuple(scopes),
        findings=tuple(findings),
        remediations=tuple(remediations),
        controls=controls,
        meta={"profile": "micro", "defect_seed": 1, "truth_seed": 1},
        fingerprint="micro-fixture",
        source_dir="memory",
    )


def _category_of(rule_id: str) -> tuple[Any, Any]:
    from dataswamp_biosystems.observed.defects import DEFECTS

    definition = DEFECTS[rule_id]
    return definition.category, definition.default_severity


def _finding(entity_id: str, rule_id: str, index: int) -> Prediction:
    return Prediction(
        schema_version=PREDICTION_SCHEMA_VERSION,
        prediction_id=f"p-{index}",
        entity_id=entity_id,
        rule_id=rule_id,
        status="finding",
    )


@pytest.fixture(scope="module")
def micro_truth() -> GroundTruth:
    return _micro_ground_truth()


# ---------------------------------------------------------------------------
# Exact matrices
# ---------------------------------------------------------------------------


def test_the_micro_fixture_spans_the_three_tiers(micro_truth: GroundTruth) -> None:
    assert difficulty_for(BRONZE_RULE).value == "bronze"
    assert difficulty_for(SILVER_RULE).value == "silver"
    assert difficulty_for(GOLD_RULE).value == "gold"


def test_exact_per_tier_confusion_matrices(micro_truth: GroundTruth) -> None:
    """Counted by hand from ``MICRO_SCOPES``.

    bronze: population {a,b,c,r}, positive {a}. Flag a (TP) and r (FP on a
    reserved control) → tp 1, fp 1, fn 0, tn 2.
    silver: population {a,b}, positives {a,b}. Flag only a → tp 1, fn 1.
    gold:   population {c,d,r}, positive {c}. Flag nothing → fn 1, tn 2.
    """
    predictions = [
        _finding("ds-a", BRONZE_RULE, 1),
        _finding("ds-r", BRONZE_RULE, 2),
        _finding("ds-a", SILVER_RULE, 3),
    ]
    blocks = evaluate(micro_truth, predictions, prediction_digest="d")
    by_difficulty = blocks.summary["findings"]["by_difficulty"]

    assert by_difficulty["bronze"]["counts"] == {
        "tp": 1,
        "fp": 1,
        "fn": 0,
        "tn": 2,
        "positives": 1,
        "negatives": 3,
        "predicted_positive": 2,
        "total": 4,
    }
    assert by_difficulty["silver"]["counts"] == {
        "tp": 1,
        "fp": 0,
        "fn": 1,
        "tn": 0,
        "positives": 2,
        "negatives": 0,
        "predicted_positive": 1,
        "total": 2,
    }
    assert by_difficulty["gold"]["counts"] == {
        "tp": 0,
        "fp": 0,
        "fn": 1,
        "tn": 2,
        "positives": 1,
        "negatives": 2,
        "predicted_positive": 0,
        "total": 3,
    }


def test_undefined_tier_metrics_are_null_with_their_denominators(
    micro_truth: GroundTruth,
) -> None:
    """Silver has no negatives, so specificity is unmeasurable — never ``0.0``."""
    blocks = evaluate(micro_truth, [_finding("ds-a", SILVER_RULE, 1)], prediction_digest="d")
    silver = blocks.summary["findings"]["by_difficulty"]["silver"]["metrics"]
    assert silver["specificity"] == {"value": None, "numerator": 0, "denominator": 0}
    # And gold, where nothing was predicted, has undefined precision.
    gold = blocks.summary["findings"]["by_difficulty"]["gold"]["metrics"]
    assert gold["precision"]["value"] is None
    assert gold["recall"]["value"] == 0.0


def test_reserved_control_false_positives_are_attributed_to_their_tier(
    micro_truth: GroundTruth,
) -> None:
    blocks = evaluate(micro_truth, [_finding("ds-r", BRONZE_RULE, 1)], prediction_digest="d")
    by_difficulty = blocks.summary["findings"]["by_difficulty"]
    assert by_difficulty["bronze"]["reserved_controls"]["false_positives"] == 1
    assert by_difficulty["bronze"]["reserved_controls"]["false_positive_rate"]["value"] == 1.0
    assert by_difficulty["gold"]["reserved_controls"]["false_positives"] == 0
    # Sums back to the overall reserved-control figure.
    assert blocks.summary["reserved_controls"]["false_positives"] == 1


def test_an_out_of_scope_prediction_never_enters_a_tier_denominator(
    micro_truth: GroundTruth,
) -> None:
    """``ds-d`` is not in the bronze rule's population, so bronze must not move."""
    baseline = evaluate(micro_truth, [], prediction_digest="d")
    with_out_of_scope = evaluate(
        micro_truth, [_finding("ds-d", BRONZE_RULE, 1)], prediction_digest="d"
    )
    before = baseline.summary["findings"]["by_difficulty"]
    after = with_out_of_scope.summary["findings"]["by_difficulty"]
    assert before["bronze"]["counts"] == after["bronze"]["counts"]
    assert with_out_of_scope.summary["out_of_scope"]["false_positives"] == 1


def test_tier_remediation_metrics_are_scoped_to_that_tier(micro_truth: GroundTruth) -> None:
    """A detected finding with no remediation submitted: coverage 0 where detected."""
    blocks = evaluate(micro_truth, [_finding("ds-a", BRONZE_RULE, 1)], prediction_digest="d")
    by_difficulty = blocks.summary["findings"]["by_difficulty"]
    bronze = by_difficulty["bronze"]["remediation"]
    assert bronze["coverage"] == {"value": 0.0, "numerator": 0, "denominator": 1}
    assert bronze["unsafe_actions"] == 0
    # Gold detected nothing, so its coverage denominator is zero and null.
    assert by_difficulty["gold"]["remediation"]["coverage"]["value"] is None


# ---------------------------------------------------------------------------
# Partition properties on the real benchmark
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_truth(real_observed_dir: Path) -> GroundTruth:
    return load_ground_truth(real_observed_dir)


@pytest.fixture(scope="module")
def perfect_result(real_truth: GroundTruth):
    predictions = [
        _finding(finding.entity_id, finding.rule_id, index)
        for index, finding in enumerate(real_truth.findings, start=1)
    ]
    return evaluate(real_truth, predictions, prediction_digest="d")


def test_per_tier_counts_sum_to_the_overall_matrix(perfect_result) -> None:
    """The strongest statement available: the tiers partition the pairs exactly."""
    overall = perfect_result.summary["findings"]["overall_micro"]["counts"]
    by_difficulty = perfect_result.summary["findings"]["by_difficulty"]
    for cell in ("tp", "fp", "fn", "tn", "positives", "negatives", "total"):
        assert sum(block["counts"][cell] for block in by_difficulty.values()) == overall[cell]
    assert (
        sum(block["counts"]["total"] for block in by_difficulty.values())
        == perfect_result.summary["universe"]["evaluated_pairs"]
    )


def test_every_scored_rule_lands_in_exactly_one_reported_tier(
    real_truth: GroundTruth, perfect_result
) -> None:
    by_difficulty = perfect_result.summary["findings"]["by_difficulty"]
    assert set(by_difficulty) == set(REPORTED_DIFFICULTIES)
    assert UNKNOWN_DIFFICULTY not in by_difficulty, "an unclassified rule reached scoring"

    rules_by_tier = perfect_result.summary["universe"]["rules_by_difficulty"]
    assert sum(rules_by_tier.values()) == len(real_truth.scopes)
    for scope in real_truth.scopes:
        assert difficulty_for(scope.id).value in REPORTED_DIFFICULTIES


def test_the_tier_metric_file_agrees_with_the_summary(perfect_result) -> None:
    by_difficulty = perfect_result.summary["findings"]["by_difficulty"]
    records = {record.id: record for record in perfect_result.difficulty_metrics}
    assert set(records) == set(by_difficulty)
    for tier, record in records.items():
        assert record.group == "difficulty"
        assert record.counts == by_difficulty[tier]["counts"]
        assert record.metrics == by_difficulty[tier]["metrics"]


def test_the_evaluation_schema_version_records_the_new_block(perfect_result) -> None:
    assert EVALUATION_SCHEMA_VERSION == 2
    assert perfect_result.summary["evaluation_schema_version"] == 2
    # The pre-existing blocks are still exactly where a schema-1 reader left them.
    findings = perfect_result.summary["findings"]
    for key in ("overall_micro", "by_rule", "by_category", "by_severity", "coarse_universes"):
        assert key in findings
