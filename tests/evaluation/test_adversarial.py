"""Scoring the adversarial tier: regrouping, never a second scoring engine.

Every number in the adversarial report is a regrouping of pairs the one engine
already scored, so the tests below check two things: that the regrouping is
arithmetically consistent with the matrix it came from, and that the specific
failure modes the tier exists to surface — flagging a near miss, flagging the
decoy instead of the target, proposing a repair where none exists — are actually
counted rather than quietly absorbed.

The denominator discipline gets particular attention. An adversarial benchmark
whose specificity is computed over the whole estate would report ~1.0 for any
agent at all, which would make the hardest tier the one that discriminates least.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.evaluation import evaluate, load_ground_truth, prediction_digest
from dataswamp_biosystems.evaluation.engine import REPORTED_DIFFICULTIES, EvaluationResult
from dataswamp_biosystems.evaluation.ground_truth import GroundTruth
from dataswamp_biosystems.evaluation.predictions import parse_predictions
from dataswamp_biosystems.evaluation.writer import SCENARIO_METRICS_NAME, evaluation_bytes
from dataswamp_biosystems.observed.difficulty import Difficulty
from dataswamp_biosystems.observed.scenarios import CaseType, ScenarioPolarity


@pytest.fixture(scope="module")
def truth(adversarial_observed_dir: Path) -> GroundTruth:
    return load_ground_truth(adversarial_observed_dir)


def _score(truth: GroundTruth, rows: list[dict[str, Any]]) -> EvaluationResult:
    raw = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")
    submitted = parse_predictions(
        raw.decode("utf-8"),
        known_entities=truth.known_entities,
        known_rules=truth.rule_ids,
    )
    return evaluate(truth, submitted, prediction_digest=prediction_digest(raw))


def _finding(entity_id: str, rule_id: str, index: int = 1, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "prediction_id": f"p-{index}",
        "entity_id": entity_id,
        "rule_id": rule_id,
        "status": "finding",
        **extra,
    }


def _positive_pairs(truth: GroundTruth) -> list[tuple[str, str]]:
    return sorted(pair for pair in truth.scenario_positive_pairs if pair in truth.case_type_by_pair)


def _near_miss_pairs(truth: GroundTruth) -> list[tuple[str, str]]:
    return sorted(
        (entity_id, rule_id)
        for case in truth.scenarios
        if case.polarity is ScenarioPolarity.NEAR_MISS_CONTROL
        for entity_id in case.target_entity_ids
        for rule_id in case.rule_ids
        if entity_id in truth.population(rule_id)
    )


# ---------------------------------------------------------------------------
# The ground truth the evaluator reads
# ---------------------------------------------------------------------------


def test_the_evaluator_reads_the_scenario_ledger(truth: GroundTruth) -> None:
    assert truth.is_adversarial
    assert truth.scenarios
    assert truth.near_miss_entity_ids
    assert truth.no_remediation_pairs


def test_an_ordinary_benchmark_declares_no_scenarios(real_observed_dir: Path) -> None:
    ordinary = load_ground_truth(real_observed_dir)
    assert not ordinary.is_adversarial
    assert ordinary.scenarios == ()
    assert ordinary.case_type_by_pair == {}


def test_the_two_benchmarks_do_not_share_a_fingerprint(
    truth: GroundTruth, real_observed_dir: Path
) -> None:
    """They are different benchmarks; a shared fingerprint would let results be confused."""
    assert truth.fingerprint != load_ground_truth(real_observed_dir).fingerprint


# ---------------------------------------------------------------------------
# The confusion matrix
# ---------------------------------------------------------------------------


def test_silence_scores_every_positive_as_a_false_negative(truth: GroundTruth) -> None:
    block = _score(truth, []).summary["adversarial"]
    matrix = block["confusion_matrix"]
    assert matrix["tp"] == 0
    assert matrix["fp"] == 0
    assert matrix["fn"] == len(_positive_pairs(truth))
    assert matrix["tn"] == len(_near_miss_pairs(truth))
    assert block["metrics"]["recall"]["value"] == 0.0
    # Precision is undefined, not zero: nothing was predicted.
    assert block["metrics"]["precision"]["value"] is None


def test_a_perfect_submission_scores_every_positive(truth: GroundTruth) -> None:
    rows = [
        _finding(entity_id, rule_id, index)
        for index, (entity_id, rule_id) in enumerate(_positive_pairs(truth), start=1)
    ]
    block = _score(truth, rows).summary["adversarial"]
    matrix = block["confusion_matrix"]
    assert matrix["fn"] == 0
    assert matrix["fp"] == 0
    assert matrix["tp"] == len(_positive_pairs(truth))
    assert block["metrics"]["f1"]["value"] == 1.0


def test_the_case_type_counts_partition_the_adversarial_matrix(truth: GroundTruth) -> None:
    rows = [
        _finding(entity_id, rule_id, index)
        for index, (entity_id, rule_id) in enumerate(_positive_pairs(truth), start=1)
    ]
    block = _score(truth, rows).summary["adversarial"]
    summed = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for case in block["by_case_type"].values():
        for cell in summed:
            summed[cell] += case["counts"][cell]
    assert summed == {cell: block["confusion_matrix"][cell] for cell in summed}


# ---------------------------------------------------------------------------
# The failure modes the tier exists to surface
# ---------------------------------------------------------------------------


def test_flagging_a_near_miss_is_a_false_positive_and_is_reported_as_one(
    truth: GroundTruth,
) -> None:
    pairs = _near_miss_pairs(truth)
    assert pairs, "the fixture must contain a scoreable near miss"
    rows = [_finding(entity_id, rule_id, i) for i, (entity_id, rule_id) in enumerate(pairs, 1)]
    block = _score(truth, rows).summary["adversarial"]
    near_miss = block["near_miss_controls"]
    assert near_miss["false_positives"] == len(pairs)
    assert near_miss["false_positive_rate"]["value"] == 1.0
    assert block["by_case_type"][CaseType.NEAR_MISS_CONTROL.value]["counts"]["fp"] == len(pairs)


def test_the_report_says_how_many_near_misses_it_could_not_score(truth: GroundTruth) -> None:
    """An unscored near miss is a limit on the measurement, not something to hide."""
    near_miss = _score(truth, []).summary["adversarial"]["near_miss_controls"]
    assert near_miss["declared"] == len(truth.near_miss_entity_ids)
    assert near_miss["scored_in_matrix"] == len({e for e, _ in _near_miss_pairs(truth)})
    assert near_miss["unscored_outside_rule_population"] == (
        near_miss["declared"] - near_miss["scored_in_matrix"]
    )


def test_a_wrong_entity_prediction_is_counted_as_one(truth: GroundTruth) -> None:
    """Right rule, wrong subject — the decoy trap."""
    decoy_case = next(
        case for case in truth.scenarios if case.case_type is CaseType.DECOY_CANDIDATE
    )
    decoy = decoy_case.decoy_entity_ids[0]
    rule_id = decoy_case.rule_ids[0]
    block = _score(truth, [_finding(decoy, rule_id)]).summary["adversarial"]
    assert block["attribution"]["wrong_entity_predictions"] == 1
    assert block["confusion_matrix"]["tp"] == 0


def test_a_wrong_rule_prediction_is_counted_as_one(truth: GroundTruth) -> None:
    """Right subject, wrong problem — the overlapping-evidence trap."""
    overlap = next(
        case for case in truth.scenarios if case.case_type is CaseType.OVERLAPPING_EVIDENCE
    )
    entity_id = overlap.target_entity_ids[0]
    other = next(
        rule_id
        for case in truth.scenarios
        for rule_id in case.rule_ids
        if rule_id not in overlap.rule_ids and entity_id in truth.population(rule_id)
    )
    block = _score(truth, [_finding(entity_id, other)]).summary["adversarial"]
    assert block["attribution"]["wrong_rule_predictions"] == 1


def test_an_abstention_on_a_clean_scenario_pair_is_counted_as_correct(
    truth: GroundTruth,
) -> None:
    entity_id, rule_id = _near_miss_pairs(truth)[0]
    rows = [_finding(entity_id, rule_id) | {"status": "abstain"}]
    block = _score(truth, rows).summary["adversarial"]
    assert block["abstention"]["correct_abstentions"] == 1
    # Abstaining on a negative is still a true negative: nothing was wrongly flagged.
    assert block["confusion_matrix"]["fp"] == 0


def test_an_explicit_no_remediation_decision_is_scored_as_correct(truth: GroundTruth) -> None:
    entity_id, rule_id = sorted(truth.no_remediation_pairs)[0]
    rows = [
        _finding(
            entity_id,
            rule_id,
            remediation={
                "action_class": "no-remediation",
                "availability": "none",
                "approval_policy": "not-required",
            },
        )
    ]
    block = _score(truth, rows).summary["adversarial"]["remediation"]
    assert block["correct_no_remediation"] == 1
    assert block["no_remediation_correct"]["value"] == 1.0


def test_proposing_a_repair_against_a_near_miss_is_reported_as_unsafe(
    truth: GroundTruth,
) -> None:
    """A detection error stays on paper; an accompanying repair alters a correct record."""
    entity_id, rule_id = _near_miss_pairs(truth)[0]
    rows = [
        _finding(
            entity_id,
            rule_id,
            remediation={
                "action_class": "restore_field",
                "availability": "automatic",
                "approval_policy": "not-required",
                "recommended_value": "anything",
            },
        )
    ]
    block = _score(truth, rows).summary["adversarial"]
    assert block["near_miss_controls"]["unsafe_remediations"] == 1
    assert block["remediation"]["unsafe_actions"] == 1


# ---------------------------------------------------------------------------
# Denominators
# ---------------------------------------------------------------------------


def test_the_adversarial_universe_is_the_constructed_neighbourhood(truth: GroundTruth) -> None:
    """Not the estate. The whole point of the tier is a small, hard universe."""
    block = _score(truth, []).summary["adversarial"]
    universe = _score(truth, []).summary["universe"]
    assert block["scenario_pairs"] < universe["evaluated_pairs"]
    assert block["scenario_pairs"] == len(_positive_pairs(truth)) + len(_near_miss_pairs(truth))


def test_no_entity_outside_a_scenario_enters_an_adversarial_denominator(
    truth: GroundTruth,
) -> None:
    scenario_entities = {entity_id for entity_id, _ in truth.case_type_by_pair}
    block = _score(truth, []).summary["adversarial"]
    total = sum(case["counts"]["total"] for case in block["by_case_type"].values())
    assert total <= len(truth.case_type_by_pair)
    assert scenario_entities <= truth.known_entities


def test_the_true_negatives_are_near_misses_rather_than_free_estate_entities(
    truth: GroundTruth,
) -> None:
    block = _score(truth, []).summary["adversarial"]
    assert block["confusion_matrix"]["tn"] == block["near_miss_negative_support"]


# ---------------------------------------------------------------------------
# Difficulty aggregation
# ---------------------------------------------------------------------------


def test_adversarial_is_a_real_populated_tier(truth: GroundTruth) -> None:
    summary = _score(truth, []).summary
    tiers = summary["findings"]["by_difficulty"]
    assert Difficulty.ADVERSARIAL.value in REPORTED_DIFFICULTIES
    adversarial = tiers[Difficulty.ADVERSARIAL.value]
    assert adversarial["counts"]["total"] > 0


def test_a_scenario_pair_is_tiered_adversarial_whatever_its_rules_own_tier(
    truth: GroundTruth,
) -> None:
    """The construction sets the tier; the rule keeps its honest tier elsewhere."""
    from dataswamp_biosystems.observed.difficulty import difficulty_for

    summary = _score(truth, []).summary
    adversarial = summary["findings"]["by_difficulty"][Difficulty.ADVERSARIAL.value]
    assert adversarial["counts"]["total"] == len(truth.case_type_by_pair) - _unscoped(truth)
    # And no rule involved is itself adversarial.
    for _, rule_id in truth.case_type_by_pair:
        assert difficulty_for(rule_id) is not Difficulty.ADVERSARIAL


def _unscoped(truth: GroundTruth) -> int:
    return sum(
        1
        for entity_id, rule_id in truth.case_type_by_pair
        if entity_id not in truth.population(rule_id)
    )


def test_the_tier_blocks_still_partition_the_whole_matrix(truth: GroundTruth) -> None:
    summary = _score(truth, []).summary
    overall = summary["findings"]["confusion_matrix"]
    summed = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for block in summary["findings"]["by_difficulty"].values():
        for cell in summed:
            summed[cell] += block["counts"][cell]
    assert summed == {cell: overall[cell] for cell in summed}


def test_an_ordinary_benchmark_still_reports_every_tier(real_observed_dir: Path) -> None:
    ordinary = load_ground_truth(real_observed_dir)
    summary = _score(ordinary, []).summary
    tiers = summary["findings"]["by_difficulty"]
    for tier in REPORTED_DIFFICULTIES:
        assert tier in tiers
    # Present but empty, with null metrics rather than a zero that would read as
    # a measured failure.
    adversarial = tiers[Difficulty.ADVERSARIAL.value]
    assert adversarial["counts"]["total"] == 0
    assert adversarial["metrics"]["f1"]["value"] is None
    assert summary["adversarial"]["scenarios"] == 0


# ---------------------------------------------------------------------------
# Emitted artefacts
# ---------------------------------------------------------------------------


def test_scenario_metrics_are_emitted_only_for_an_adversarial_benchmark(
    truth: GroundTruth, real_observed_dir: Path
) -> None:
    adversarial = _score(truth, [])
    assert adversarial.scenario_metrics
    assert SCENARIO_METRICS_NAME in evaluation_bytes(adversarial)

    ordinary = _score(load_ground_truth(real_observed_dir), [])
    assert ordinary.scenario_metrics == []
    assert SCENARIO_METRICS_NAME not in evaluation_bytes(ordinary)


def test_scenario_metric_rows_cover_every_case_type_present(truth: GroundTruth) -> None:
    result = _score(truth, [])
    emitted = {record.id for record in result.scenario_metrics}
    assert emitted == set(result.summary["adversarial"]["by_case_type"])
    assert all(record.group == "scenario-case-type" for record in result.scenario_metrics)
