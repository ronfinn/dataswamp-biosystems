"""Scoring semantics against a ground truth small enough to count by hand.

The tiny benchmark (see ``conftest.py``) has four rules and eleven in-scope
pairs: four positives and seven negatives, three of which are reserved-control
pairs, plus one entity (``ds-outside``) that is in no rule's population at all.
Every number asserted below was derived from that layout on paper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dataswamp_biosystems.evaluation import (
    GroundTruth,
    Outcome,
    RemediationState,
    evaluate,
    load_ground_truth,
    load_predictions,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

TOTAL_PAIRS = 11
POSITIVE_PAIRS = 4
NEGATIVE_PAIRS = 7
RESERVED_PAIRS = 3


@pytest.fixture()
def truth(tiny_observed_dir: Path) -> GroundTruth:
    return load_ground_truth(tiny_observed_dir)


def _score(truth: GroundTruth, name: str):
    predictions, raw = load_predictions(
        FIXTURE_DIR / f"{name}.jsonl",
        known_entities=truth.known_entities,
        known_rules=truth.rule_ids,
    )
    return evaluate(truth, predictions, prediction_digest="fixture")


def _outcomes(result) -> dict[tuple[str, str], Outcome]:
    return {(r.rule_id, r.entity_id): r.outcome for r in result.finding_results}


# -- the evaluation universe --------------------------------------------------


def test_the_universe_is_the_union_of_rule_populations(truth: GroundTruth) -> None:
    result = _score(truth, "perfect")
    universe = result.summary["universe"]
    assert universe["evaluated_pairs"] == TOTAL_PAIRS
    assert universe["positive_pairs"] == POSITIVE_PAIRS
    assert universe["negative_pairs"] == NEGATIVE_PAIRS
    assert universe["reserved_control_pairs"] == RESERVED_PAIRS


def test_a_never_eligible_entity_never_inflates_the_true_negatives(truth: GroundTruth) -> None:
    """``ds-outside`` is a known control in no rule population; it must score nothing.

    This is the difference between an honest specificity and a free one: pairing
    every rule with every entity would add four more true negatives here, and
    thousands on the real benchmark.
    """
    assert "ds-outside" in truth.known_entities
    assert all("ds-outside" not in truth.population(scope.id) for scope in truth.scopes)
    result = _score(truth, "perfect")
    assert not any(r.entity_id == "ds-outside" for r in result.finding_results)
    counts = result.summary["findings"]["overall_micro"]["counts"]
    assert counts["total"] == TOTAL_PAIRS


def test_eligible_unselected_and_reserved_ids_are_both_negatives(truth: GroundTruth) -> None:
    result = _score(truth, "perfect")
    by_partition = result.summary["findings"]["by_control_partition"]
    assert by_partition["reserved"]["counts"]["negatives"] == RESERVED_PAIRS
    assert by_partition["non-reserved"]["counts"]["negatives"] == NEGATIVE_PAIRS - RESERVED_PAIRS
    # Reserved controls were held out before selection, so they are never positive.
    assert by_partition["reserved"]["counts"]["positives"] == 0


def test_selected_ids_are_the_positives(truth: GroundTruth) -> None:
    expected = {(f.rule_id, f.entity_id) for f in truth.findings}
    result = _score(truth, "perfect")
    actual = {
        (r.rule_id, r.entity_id) for r in result.finding_results if r.expected_status == "present"
    }
    assert actual == expected


def test_aggregate_counts_equal_the_sum_of_disjoint_breakdowns(truth: GroundTruth) -> None:
    result = _score(truth, "partial")
    overall = result.summary["findings"]["overall_micro"]["counts"]
    for name in ("by_rule", "by_category", "by_severity", "by_entity_kind", "by_entity_class"):
        summed = dict.fromkeys(("tp", "fp", "fn", "tn"), 0)
        for block in result.summary["findings"][name].values():
            for cell in summed:
                summed[cell] += block["counts"][cell]
        assert summed == {cell: overall[cell] for cell in summed}, name


# -- the confusion matrix -----------------------------------------------------


def test_a_perfect_submission_scores_one_on_every_metric(truth: GroundTruth) -> None:
    result = _score(truth, "perfect")
    block = result.summary["findings"]["overall_micro"]
    assert block["counts"]["tp"] == POSITIVE_PAIRS
    assert block["counts"]["fp"] == 0
    assert block["counts"]["fn"] == 0
    assert block["counts"]["tn"] == NEGATIVE_PAIRS
    for metric in ("precision", "recall", "specificity", "f1"):
        assert block["metrics"][metric]["value"] == 1.0
    assert result.summary["out_of_scope"]["false_positives"] == 0


def test_a_partial_submission_produces_the_hand_checked_matrix(truth: GroundTruth) -> None:
    """3 TP, 1 FN, 0 in-matrix FP, 7 TN, and one out-of-scope false positive."""
    result = _score(truth, "partial")
    block = result.summary["findings"]["overall_micro"]
    assert block["counts"]["tp"] == 3
    assert block["counts"]["fp"] == 0
    assert block["counts"]["fn"] == 1
    assert block["counts"]["tn"] == NEGATIVE_PAIRS
    assert block["metrics"]["precision"]["value"] == 1.0
    assert block["metrics"]["recall"]["value"] == pytest.approx(0.75)
    assert block["metrics"]["specificity"]["value"] == 1.0
    assert block["metrics"]["f1"]["value"] == pytest.approx(6 / 7)

    outcomes = _outcomes(result)
    assert outcomes[("TINY-AUTO", "ds-alpha")] is Outcome.TP
    assert outcomes[("TINY-APPROVE", "ds-bravo")] is Outcome.FN
    assert outcomes[("TINY-AUTO", "ds-charlie")] is Outcome.TN
    assert outcomes[("TINY-AUTO", "ds-delta")] is Outcome.OUT_OF_SCOPE_FALSE_POSITIVE


def test_a_poor_submission_produces_the_hand_checked_matrix(truth: GroundTruth) -> None:
    """2 TP, 2 FP (one on a reserved control), 2 FN (one an abstention), 5 TN."""
    result = _score(truth, "poor")
    block = result.summary["findings"]["overall_micro"]
    assert block["counts"] == {
        "tp": 2,
        "fp": 2,
        "fn": 2,
        "tn": 5,
        "positives": POSITIVE_PAIRS,
        "negatives": NEGATIVE_PAIRS,
        "predicted_positive": 4,
        "total": TOTAL_PAIRS,
    }
    assert block["metrics"]["precision"]["value"] == pytest.approx(0.5)
    assert block["metrics"]["recall"]["value"] == pytest.approx(0.5)
    assert block["metrics"]["specificity"]["value"] == pytest.approx(5 / 7)
    assert block["metrics"]["f1"]["value"] == pytest.approx(0.5)


def test_reserved_control_false_positives_are_reported_separately(truth: GroundTruth) -> None:
    result = _score(truth, "poor")
    reserved = result.summary["reserved_controls"]
    assert reserved["false_positives"] == 1
    assert reserved["counts"]["tn"] == 2
    assert reserved["metrics"]["specificity"]["value"] == pytest.approx(2 / 3)
    # …and the non-reserved control false positive is not counted as reserved.
    non_reserved = result.summary["findings"]["by_control_partition"]["non-reserved"]
    assert non_reserved["counts"]["fp"] == 1


def test_out_of_scope_predictions_are_visible_but_never_in_a_denominator(
    truth: GroundTruth,
) -> None:
    result = _score(truth, "partial")
    out_of_scope = result.summary["out_of_scope"]
    assert out_of_scope["false_positives"] == 1
    assert out_of_scope["strict_false_positives"] == 1
    counts = result.summary["findings"]["overall_micro"]["counts"]
    assert counts["fp"] == 0
    assert counts["negatives"] == NEGATIVE_PAIRS  # unchanged by the out-of-scope claim
    record = next(r for r in result.finding_results if not r.in_scope)
    assert record.expected_status == "out-of-scope"
    assert record.prediction_id == "partial-4"


def test_every_prediction_is_accounted_for(truth: GroundTruth) -> None:
    """No submitted prediction may vanish between validation and the report."""
    result = _score(truth, "partial")
    submission = result.summary["submission"]
    referenced = {r.prediction_id for r in result.finding_results if r.prediction_id}
    assert len(referenced) == submission["rule_level_predictions"]
    assert (
        submission["rule_level_predictions"] + submission["unnamed_rule_predictions"]
        == (submission["predictions"])
    )


def test_no_composite_score_is_invented(truth: GroundTruth) -> None:
    summary = _score(truth, "perfect").summary
    assert summary["composite_score"] is None
    assert summary["dimensions_are_weighted"] is False
    assert all(isinstance(block, dict) for block in summary["dimensions"].values())


def test_only_informative_pairs_are_emitted(truth: GroundTruth) -> None:
    """No cross-product on disk: silence on a negative pair produces no record."""
    result = _score(truth, "perfect")
    assert len(result.finding_results) == POSITIVE_PAIRS
    assert result.summary["universe"]["evaluated_pairs"] == TOTAL_PAIRS


def test_an_explicit_clean_prediction_is_recorded_as_such(truth: GroundTruth) -> None:
    result = _score(truth, "partial")
    assert result.summary["universe"]["explicit_clean_true_negatives"] == 1
    record = next(r for r in result.finding_results if r.predicted_status == "clean")
    assert record.outcome is Outcome.TN


def test_attribute_correctness_is_reported_without_altering_the_match(
    truth: GroundTruth,
) -> None:
    """A right pair with a wrong severity is still a true positive — and is flagged."""
    result = _score(truth, "partial")
    record = next(r for r in result.finding_results if r.prediction_id == "partial-1")
    assert record.outcome is Outcome.TP
    assert record.category_correct is True
    assert record.severity_correct is True


# -- abstention ---------------------------------------------------------------


def test_an_abstention_on_a_positive_pair_is_a_false_negative_and_is_counted(
    truth: GroundTruth,
) -> None:
    result = _score(truth, "poor")
    abstention = result.summary["abstention"]
    assert abstention["abstained_pairs"] == 1
    assert abstention["on_positive_pairs"] == 1
    assert abstention["on_negative_pairs"] == 0
    record = next(r for r in result.finding_results if r.abstained)
    assert record.outcome is Outcome.FN


def test_selective_metrics_exclude_abstained_pairs(truth: GroundTruth) -> None:
    result = _score(truth, "poor")
    selective = result.summary["abstention"]["selective"]["counts"]
    assert selective["total"] == TOTAL_PAIRS - 1
    assert selective["fn"] == 1  # the non-abstained miss remains


def test_silence_is_not_abstention(truth: GroundTruth) -> None:
    result = _score(truth, "partial")
    assert result.summary["abstention"]["abstained_pairs"] == 0
    missed = next(r for r in result.finding_results if r.outcome is Outcome.FN)
    assert missed.predicted_status == "absent"
    assert missed.abstained is False


# -- remediation --------------------------------------------------------------


def _remediation(result, rule_id: str):
    return next(r for r in result.remediation_results if r.rule_id == rule_id)


def test_every_remediation_contract_state_scores_correctly(truth: GroundTruth) -> None:
    """automatic/no-approval, automatic/approval, manual/no-approval, non-remediable."""
    result = _score(truth, "perfect")
    for rule_id in ("TINY-AUTO", "TINY-APPROVE", "TINY-MANUAL", "TINY-NONE"):
        record = _remediation(result, rule_id)
        assert record.state is RemediationState.SCORED, rule_id
        assert record.fully_correct, rule_id
    counts = result.summary["remediation"]["counts"]
    assert counts["submitted"] == POSITIVE_PAIRS
    assert counts["fully_correct"] == POSITIVE_PAIRS
    assert counts["unsafe_actions"] == 0
    assert result.summary["remediation"]["metrics"]["end_to_end"]["value"] == 1.0


def test_a_correct_no_remediation_decision_is_credited(truth: GroundTruth) -> None:
    result = _score(truth, "perfect")
    record = _remediation(result, "TINY-NONE")
    assert record.no_remediation_correct is True
    metrics = result.summary["remediation"]["metrics"]
    assert metrics["non_remediation_correct"]["value"] == 1.0


def test_omitting_a_required_no_remediation_decision_is_not_rewarded(
    truth: GroundTruth,
) -> None:
    """Silence on a non-remediable finding is a missing decision, not a correct one."""
    result = _score(truth, "partial")
    record = _remediation(result, "TINY-NONE")
    assert record.state is RemediationState.MISSING
    assert record.no_remediation_correct is False
    assert result.summary["remediation"]["metrics"]["non_remediation_correct"]["value"] == 0.0


def test_a_wrong_action_class_costs_full_correctness_only(truth: GroundTruth) -> None:
    result = _score(truth, "partial")
    record = _remediation(result, "TINY-AUTO")
    assert record.action_class_correct is False
    assert record.availability_correct is True
    assert record.approval_policy_correct is True
    assert record.fully_correct is False
    assert "action_class" in record.explanation


def test_a_wrong_approval_policy_and_approver_are_both_reported(truth: GroundTruth) -> None:
    result = _score(truth, "poor")
    record = _remediation(result, "TINY-APPROVE")
    assert record.action_class_correct is True
    assert record.approval_policy_correct is False
    assert record.approver_role_correct is False
    assert record.fully_correct is False
    assert result.summary["dimensions"]["approval_reasoning"]["value"] == pytest.approx(0.5)


def test_an_undetected_finding_leaves_its_remediation_unscored(truth: GroundTruth) -> None:
    """A missed finding is a detection error; it is not re-charged as a fix error."""
    result = _score(truth, "partial")
    record = _remediation(result, "TINY-APPROVE")
    assert record.finding_outcome is Outcome.FN
    assert record.state is RemediationState.UNSCORED_MISSED_FINDING
    counts = result.summary["remediation"]["counts"]
    assert counts["unscored_missed_finding"] == 1
    assert counts["detected_findings"] == 3


def test_an_actionable_remediation_on_a_clean_entity_is_flagged_unsafe(
    truth: GroundTruth,
) -> None:
    result = _score(truth, "poor")
    unsafe = [r for r in result.remediation_results if r.unsafe_action]
    assert len(unsafe) == 2
    reserved = [r for r in unsafe if r.unsafe_on_reserved_control]
    assert [r.entity_id for r in reserved] == ["ds-reserved"]
    counts = result.summary["remediation"]["counts"]
    assert counts["unsafe_actions"] == 2
    assert counts["unsafe_on_reserved_control"] == 1
    assert "damage correct data" in reserved[0].explanation


def test_remediation_is_never_scored_without_a_correct_finding(truth: GroundTruth) -> None:
    scored_pairs = {
        (r.rule_id, r.entity_id)
        for r in _score(truth, "poor").remediation_results
        if r.state is RemediationState.SCORED
    }
    true_positives = {
        (r.rule_id, r.entity_id)
        for r in _score(truth, "poor").finding_results
        if r.outcome is Outcome.TP
    }
    assert scored_pairs <= true_positives


def test_coverage_and_conditional_correctness_are_distinct(truth: GroundTruth) -> None:
    result = _score(truth, "partial")
    metrics = result.summary["remediation"]["metrics"]
    assert metrics["coverage"]["value"] == pytest.approx(2 / 3)
    assert metrics["correctness_given_true_positive"]["value"] == pytest.approx(0.5)
    assert metrics["end_to_end"]["value"] == pytest.approx(0.25)


# -- credit without a rule id -------------------------------------------------


def test_a_prediction_without_a_rule_id_is_scored_only_in_coarser_universes(
    truth: GroundTruth,
) -> None:
    from dataswamp_biosystems.evaluation import parse_predictions

    text = (
        '{"schema_version":1,"prediction_id":"u1","entity_id":"ds-alpha",'
        '"category":"metadata-completeness","status":"finding"}\n'
    )
    predictions = parse_predictions(
        text, known_entities=truth.known_entities, known_rules=truth.rule_ids
    )
    result = evaluate(truth, predictions, prediction_digest="x")
    assert result.summary["submission"]["unnamed_rule_predictions"] == 1
    # It occupies no pair …
    assert result.summary["findings"]["overall_micro"]["counts"]["tp"] == 0
    # … but earns credit at the entity and category level.
    coarse = result.summary["findings"]["coarse_universes"]
    assert coarse["entity_level"]["counts"]["tp"] == 1
    assert coarse["category_level"]["counts"]["tp"] == 1


# -- determinism --------------------------------------------------------------


def test_evaluating_twice_produces_identical_bytes(truth: GroundTruth) -> None:
    from dataswamp_biosystems.evaluation import evaluation_bytes, render_report

    first = _score(truth, "poor")
    second = _score(truth, "poor")
    assert evaluation_bytes(first) == evaluation_bytes(second)
    assert render_report(first) == render_report(second)


def test_records_are_ordered_by_id_not_by_evaluation_order(truth: GroundTruth) -> None:
    result = _score(truth, "poor")
    ids = [r.id for r in result.finding_results]
    assert ids == sorted(ids)
    assert [r.id for r in result.rule_metrics] == sorted(r.id for r in result.rule_metrics)
