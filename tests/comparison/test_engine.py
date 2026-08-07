"""Comparison semantics against a ground truth small enough to count by hand.

The tiny benchmark has four rules and eleven in-scope pairs: four positives and
seven negatives, three of them reserved-control pairs. Every transition asserted
below was derived from that layout on paper.
"""

from __future__ import annotations

from pathlib import Path

from dataswamp_biosystems.comparison import (
    PairTransition,
    RemediationTransition,
    RuleStatus,
    compare_runs,
    higher_is_better,
    load_run,
    metric_delta,
)
from tests.comparison.conftest import (
    DEFECTS,
    ORDINARY_CONTROL,
    RESERVED_CONTROL,
    finding,
    wrong_remediation,
)
from tests.evaluation.conftest import RULE_AUTO, RULE_MANUAL, RULE_NONE


def _compare(baseline: Path, candidate: Path):  # noqa: ANN202
    return compare_runs(load_run(baseline), load_run(candidate))


def _transitions(result) -> dict[tuple[str, str], PairTransition]:  # noqa: ANN001
    return {(r.rule_id, r.entity_id): r.transition for r in result.pair_transitions}


# -- a run against itself -----------------------------------------------------


def test_comparing_a_run_with_itself_reports_no_change(perfect_run: Path) -> None:
    result = _compare(perfect_run, perfect_run)
    headline = result.summary["headline"]
    assert headline["pairs_changed"] == 0
    assert headline["newly_solved"] == 0
    assert headline["newly_broken"] == 0
    assert headline["new_control_false_positives"] == 0
    assert headline["rules_regressed"] == 0
    assert result.pair_transitions == []
    assert result.control_regressions == []
    assert result.remediation_regressions == []


def test_a_run_against_itself_leaves_every_defined_delta_at_zero(perfect_run: Path) -> None:
    result = _compare(perfect_run, perfect_run)
    for name, delta in result.summary["dimensions"].items():
        assert delta["delta"] in (0.0, None), name
        assert delta["direction"] in {"unchanged", "undefined"}, name


# -- improvement and regression ----------------------------------------------


def test_a_clearly_improved_candidate_reports_newly_solved_pairs(
    silent_run: Path, perfect_run: Path
) -> None:
    result = _compare(silent_run, perfect_run)
    headline = result.summary["headline"]
    assert headline["newly_solved"] == len(DEFECTS)
    assert headline["newly_broken"] == 0
    assert headline["new_control_false_positives"] == 0
    assert result.summary["dimensions"]["finding_detection"]["direction"] == "improved"
    assert set(_transitions(result).values()) == {PairTransition.NEWLY_SOLVED}


def test_a_clearly_regressed_candidate_reports_newly_broken_pairs(
    perfect_run: Path, silent_run: Path
) -> None:
    result = _compare(perfect_run, silent_run)
    headline = result.summary["headline"]
    assert headline["newly_broken"] == len(DEFECTS)
    assert headline["newly_solved"] == 0
    assert result.summary["dimensions"]["finding_detection"]["direction"] == "regressed"
    assert set(_transitions(result).values()) == {PairTransition.NEWLY_BROKEN}


def test_regression_is_attributed_to_the_exact_rule_and_entity(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    """One rule dropped; only that rule may be reported as regressed."""
    kept = [finding(e, r) for e, r in DEFECTS if r != RULE_MANUAL]
    candidate = make_run("dropped-one", kept)
    result = _compare(perfect_run, candidate)

    assert _transitions(result) == {(RULE_MANUAL, "ds-charlie"): PairTransition.NEWLY_BROKEN}
    regressed = [r for r in result.rule_regressions if r.status is RuleStatus.REGRESSED]
    assert [r.rule_id for r in regressed] == [RULE_MANUAL]
    assert regressed[0].newly_broken == 1
    assert regressed[0].new_false_positives == 0
    # Rule ids survive verbatim — never normalised, lower-cased or truncated.
    assert regressed[0].id == RULE_MANUAL


def test_rules_are_ranked_deterministically_by_regression_impact(
    perfect_run: Path, make_run
) -> None:  # noqa: ANN001
    """Two rules broken, one of them also flagging a reserved control."""
    candidate = make_run(
        "mixed-damage",
        [finding(e, r) for e, r in DEFECTS if r not in {RULE_MANUAL, RULE_AUTO}]
        + [finding(RESERVED_CONTROL, RULE_AUTO)],
    )
    result = _compare(perfect_run, candidate)
    ranked = result.summary["ranked_regressions"]
    assert [row["rank"] for row in ranked] == sorted(row["rank"] for row in ranked)
    # RULE_AUTO lost its defect *and* gained a reserved-control false positive,
    # so it must outrank the rule that only lost a defect.
    assert ranked[0]["rule_id"] == RULE_AUTO
    assert ranked[0]["new_reserved_control_false_positives"] == 1
    # Rank is an explicit field, because JSONL order is by id, not by rank.
    by_rule = {r.rule_id: r.rank for r in result.rule_regressions}
    assert by_rule[RULE_AUTO] < by_rule[RULE_MANUAL]


# -- control preservation -----------------------------------------------------


def test_a_new_ordinary_control_false_positive_is_reported(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    candidate = make_run(
        "flags-control",
        [finding(e, r) for e, r in DEFECTS] + [finding(ORDINARY_CONTROL, RULE_MANUAL)],
    )
    result = _compare(perfect_run, candidate)

    assert result.summary["headline"]["new_control_false_positives"] == 1
    assert result.summary["headline"]["new_reserved_control_false_positives"] == 0
    records = result.control_regressions
    assert [(r.entity_id, r.rule_id, r.transition) for r in records] == [
        (ORDINARY_CONTROL, RULE_MANUAL, "new-false-positive")
    ]
    assert records[0].reserved_control is False
    assert records[0].regression is True
    assert result.summary["control_preservation"]["specificity"]["direction"] == "regressed"


def test_a_new_reserved_control_false_positive_is_reported_separately(
    perfect_run: Path, make_run
) -> None:  # noqa: ANN001
    """The least excusable error available: a control no rule could ever draw."""
    candidate = make_run(
        "flags-reserved",
        [finding(e, r) for e, r in DEFECTS] + [finding(RESERVED_CONTROL, RULE_AUTO)],
    )
    result = _compare(perfect_run, candidate)

    controls = result.summary["control_preservation"]
    assert controls["new_control_false_positives"] == 1
    assert controls["new_reserved_control_false_positives"] == 1
    assert controls["reserved_control_false_positives"]["direction"] == "regressed"
    assert controls["reserved_control_specificity"]["direction"] == "regressed"
    record = result.control_regressions[0]
    assert record.reserved_control is True
    assert record.entity_id == RESERVED_CONTROL


def test_a_control_false_positive_that_goes_away_is_reported_as_resolved(
    perfect_run: Path, make_run
) -> None:  # noqa: ANN001
    noisy = make_run(
        "noisy",
        [finding(e, r) for e, r in DEFECTS] + [finding(RESERVED_CONTROL, RULE_AUTO)],
    )
    result = _compare(noisy, perfect_run)
    controls = result.summary["control_preservation"]
    assert controls["new_control_false_positives"] == 0
    assert controls["resolved_control_false_positives"] == 1
    assert controls["resolved_reserved_control_false_positives"] == 1
    assert result.control_regressions[0].transition == "resolved-false-positive"
    assert result.control_regressions[0].regression is False


def test_recall_bought_with_control_damage_is_impossible_to_miss(
    silent_run: Path, make_run
) -> None:  # noqa: ANN001
    """The tradeoff the benchmark exists to expose: better F1, worse controls."""
    candidate = make_run(
        "trigger-happy",
        [finding(e, r) for e, r in DEFECTS]
        + [finding(RESERVED_CONTROL, RULE_AUTO), finding(ORDINARY_CONTROL, RULE_MANUAL)],
    )
    result = _compare(silent_run, candidate)

    assert result.summary["dimensions"]["finding_detection"]["direction"] == "improved"
    assert result.summary["dimensions"]["control_preservation"]["direction"] == "regressed"
    assert result.summary["headline"]["new_control_false_positives"] == 2
    assert result.summary["headline"]["new_reserved_control_false_positives"] == 1


# -- undefined metrics --------------------------------------------------------


def test_an_undefined_metric_on_either_side_yields_an_undefined_delta() -> None:
    defined = {"value": 1.0, "numerator": 2, "denominator": 2}
    undefined = {"value": None, "numerator": 0, "denominator": 0}

    assert metric_delta("precision", undefined, defined)["delta"] is None
    assert metric_delta("precision", defined, undefined)["delta"] is None
    assert metric_delta("precision", undefined, undefined)["direction"] == "undefined"
    # Never zero. A zero here would read as "measured, and unchanged".
    assert metric_delta("precision", undefined, defined)["direction"] == "undefined"


def test_an_undefined_delta_keeps_both_numerators_and_denominators() -> None:
    delta = metric_delta(
        "precision",
        {"value": None, "numerator": 0, "denominator": 0},
        {"value": 0.5, "numerator": 1, "denominator": 2},
    )
    assert delta["baseline"] == {"value": None, "numerator": 0, "denominator": 0}
    assert delta["candidate"] == {"value": 0.5, "numerator": 1, "denominator": 2}


def test_a_silent_run_leaves_precision_undefined_and_the_delta_undefined(
    silent_run: Path, perfect_run: Path
) -> None:
    """A real end-to-end case: nothing predicted means precision was never asked."""
    result = _compare(silent_run, perfect_run)
    precision = result.summary["overall_micro"]["metrics"]["precision"]
    assert precision["baseline"]["value"] is None
    assert precision["baseline"]["denominator"] == 0
    assert precision["delta"] is None
    assert precision["direction"] == "undefined"


# -- direction semantics ------------------------------------------------------


def test_error_rates_are_marked_as_lower_is_better() -> None:
    assert higher_is_better("recall") is True
    assert higher_is_better("f1") is True
    assert higher_is_better("false_positive_rate") is False
    assert higher_is_better("false_negative_rate") is False


def test_a_rising_error_rate_is_reported_as_a_regression_not_a_positive_number(
    perfect_run: Path, make_run
) -> None:  # noqa: ANN001
    candidate = make_run(
        "flags-reserved",
        [finding(e, r) for e, r in DEFECTS] + [finding(RESERVED_CONTROL, RULE_AUTO)],
    )
    result = _compare(perfect_run, candidate)
    rate = result.summary["overall_micro"]["metrics"]["false_positive_rate"]
    # The raw delta is honestly positive; the direction says what that means.
    assert rate["delta"] is not None and rate["delta"] > 0
    assert rate["direction"] == "regressed"
    assert rate["higher_is_better"] is False


def test_error_counts_carry_an_explicit_direction(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    candidate = make_run(
        "flags-reserved",
        [finding(e, r) for e, r in DEFECTS] + [finding(RESERVED_CONTROL, RULE_AUTO)],
    )
    result = _compare(perfect_run, candidate)
    false_positives = result.summary["control_preservation"]["false_positives"]
    assert false_positives["delta"] == 1
    assert false_positives["direction"] == "regressed"
    assert false_positives["higher_is_better"] is False


# -- difficulty ---------------------------------------------------------------


def test_difficulty_tiers_are_compared_independently(silent_run: Path, perfect_run: Path) -> None:
    result = _compare(silent_run, perfect_run)
    by_difficulty = result.summary["by_difficulty"]
    assert by_difficulty, "the evaluator publishes a difficulty breakdown"
    for tier, block in by_difficulty.items():
        assert set(block["metrics"]) >= {"precision", "recall", "specificity", "f1"}, tier
        assert "counts" in block, tier


def test_a_tier_neither_run_measured_is_not_fabricated(silent_run: Path, perfect_run: Path) -> None:
    """Tiers come from the runs. A tier absent from both must not appear."""
    result = _compare(silent_run, perfect_run)
    published = set(load_run(perfect_run).summary["findings"]["by_difficulty"])
    assert set(result.summary["by_difficulty"]) == published


def test_an_empty_tier_reports_undefined_rather_than_zero(
    silent_run: Path, perfect_run: Path
) -> None:
    """The tiny benchmark declares no adversarial pairs, so its tier is undefined."""
    result = _compare(silent_run, perfect_run)
    adversarial = result.summary["by_difficulty"].get("adversarial")
    if adversarial is not None:
        assert adversarial["metrics"]["recall"]["delta"] is None
        assert adversarial["metrics"]["recall"]["direction"] == "undefined"


# -- adversarial --------------------------------------------------------------


def test_adversarial_is_reported_as_aggregate_and_says_so(
    silent_run: Path, perfect_run: Path
) -> None:
    """Per-case attribution would need the privileged answer key; it is not claimed."""
    result = _compare(silent_run, perfect_run)
    adversarial = result.summary["adversarial"]
    assert adversarial["per_case_attribution_available"] is False
    assert "scenario membership" in adversarial["attribution_note"]
    assert adversarial["declared_scenarios"] == 0


def test_near_miss_control_regressions_are_counted_as_errors(
    silent_run: Path, perfect_run: Path
) -> None:
    result = _compare(silent_run, perfect_run)
    near_miss = result.summary["adversarial"]["near_miss_controls"]
    assert near_miss["false_positives"]["higher_is_better"] is False
    assert near_miss["unsafe_remediations"]["higher_is_better"] is False


# -- remediation --------------------------------------------------------------


def test_a_newly_correct_remediation_is_reported(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    baseline = make_run(
        "bad-remediation",
        [wrong_remediation(e, r) if r == RULE_AUTO else finding(e, r) for e, r in DEFECTS],
    )
    result = _compare(baseline, perfect_run)
    changed = {r.rule_id: r for r in result.remediation_regressions}
    assert RULE_AUTO in changed
    assert RemediationTransition.NEWLY_CORRECT in changed[RULE_AUTO].transitions
    assert changed[RULE_AUTO].regression is False
    assert result.summary["headline"]["remediations_regressed"] == 0


def test_a_newly_incorrect_remediation_is_reported_as_a_regression(
    perfect_run: Path, make_run
) -> None:  # noqa: ANN001
    candidate = make_run(
        "bad-remediation",
        [wrong_remediation(e, r) if r == RULE_AUTO else finding(e, r) for e, r in DEFECTS],
    )
    result = _compare(perfect_run, candidate)
    changed = {r.rule_id: r for r in result.remediation_regressions}
    assert RemediationTransition.NEWLY_INCORRECT in changed[RULE_AUTO].transitions
    assert changed[RULE_AUTO].regression is True
    assert result.summary["headline"]["remediations_regressed"] >= 1
    assert result.summary["remediation"]["counts"]["fully_correct"]["direction"] == "regressed"


def test_a_newly_missing_remediation_is_reported(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    candidate = make_run(
        "no-remediation-submitted",
        [finding(e, r, remediation=(r != RULE_AUTO)) for e, r in DEFECTS],
    )
    result = _compare(perfect_run, candidate)
    changed = {r.rule_id: r for r in result.remediation_regressions}
    assert RemediationTransition.NEWLY_MISSING in changed[RULE_AUTO].transitions
    assert changed[RULE_AUTO].regression is True


def test_a_newly_unsafe_remediation_against_a_control_is_reported(
    perfect_run: Path, make_run
) -> None:  # noqa: ANN001
    """An unsafe action exists only in the candidate's file; the join must find it."""
    candidate = make_run(
        "unsafe",
        [finding(e, r) for e, r in DEFECTS] + [finding(RESERVED_CONTROL, RULE_AUTO)],
    )
    result = _compare(perfect_run, candidate)
    unsafe = [
        record
        for record in result.remediation_regressions
        if RemediationTransition.NEWLY_UNSAFE in record.transitions
    ]
    assert unsafe, "a remediation proposed against a clean control is unsafe"
    assert unsafe[0].entity_id == RESERVED_CONTROL
    assert unsafe[0].regression is True
    assert result.summary["remediation"]["counts"]["unsafe_actions"]["direction"] == "regressed"
    assert result.control_regressions[0].unsafe_remediation is True


def test_a_no_remediation_decision_regression_is_reported(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    """``TINY-NONE`` is non-remediable: proposing an action for it is wrong."""
    candidate = make_run(
        "proposes-action-for-non-remediable",
        [wrong_remediation(e, r) if r == RULE_NONE else finding(e, r) for e, r in DEFECTS],
    )
    result = _compare(perfect_run, candidate)
    changed = {r.rule_id: r for r in result.remediation_regressions}
    assert RULE_NONE in changed
    assert RemediationTransition.NEWLY_INCORRECT_NO_REMEDIATION in changed[RULE_NONE].transitions
    assert changed[RULE_NONE].regression is True


# -- no policy gate -----------------------------------------------------------


def test_a_regression_produces_a_report_not_a_verdict(perfect_run: Path, silent_run: Path) -> None:
    result = _compare(perfect_run, silent_run)
    assert result.summary["verdict_is_advisory"] is True
    assert "no threshold" in result.summary["verdict_note"]
