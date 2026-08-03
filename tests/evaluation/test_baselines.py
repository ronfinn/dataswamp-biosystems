"""Baseline agents scored against the real canonical benchmark ground truth.

The tiny fixture proves the arithmetic; these prove the engine holds up on the
actual emitted benchmark — 41 rules, 177 expected findings, thousands of
negative pairs — and that the degenerate strategies score the way a benchmark
must make them score.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.evaluation import (
    GroundTruth,
    evaluate,
    evaluation_bytes,
    load_ground_truth,
    parse_predictions,
)


@pytest.fixture(scope="module")
def truth(real_observed_dir: Path) -> GroundTruth:
    return load_ground_truth(real_observed_dir)


def _score(truth: GroundTruth, rows: list[dict]):
    text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    predictions = parse_predictions(
        text, known_entities=truth.known_entities, known_rules=truth.rule_ids
    )
    return evaluate(truth, predictions, prediction_digest="baseline")


def _perfect_rows(truth: GroundTruth) -> list[dict]:
    remediation_by_finding = truth.remediation_by_finding
    rows = []
    for index, finding in enumerate(truth.findings):
        expected = remediation_by_finding[finding.id]
        rows.append(
            {
                "schema_version": 1,
                "prediction_id": f"perfect-{index}",
                "entity_id": finding.entity_id,
                "rule_id": finding.rule_id,
                "status": "finding",
                "category": finding.category.value,
                "severity": finding.severity.value,
                "remediation": {
                    "action_class": expected.action_class,
                    "availability": expected.availability.value,
                    "approval_policy": expected.approval_policy.value,
                    "approver_role": expected.approver_role.value,
                    "recommended_value": expected.recommended_value,
                },
            }
        )
    return rows


def _flag_everything_rows(truth: GroundTruth) -> list[dict]:
    rows = []
    for scope in truth.scopes:
        for entity_id in sorted(truth.population(scope.id)):
            rows.append(
                {
                    "schema_version": 1,
                    "prediction_id": f"all-{scope.id}-{entity_id}",
                    "entity_id": entity_id,
                    "rule_id": scope.id,
                    "status": "finding",
                }
            )
    return rows


def test_the_ground_truth_loads_with_the_expected_shape(truth: GroundTruth) -> None:
    assert len(truth.scopes) == 41
    assert len(truth.findings) == 177
    assert len(truth.findings) == len(truth.remediations)
    assert len(truth.fingerprint) == 64


def test_a_perfect_agent_scores_one_on_precision_recall_and_specificity(
    truth: GroundTruth,
) -> None:
    result = _score(truth, _perfect_rows(truth))
    metrics = result.summary["findings"]["overall_micro"]["metrics"]
    assert metrics["precision"]["value"] == 1.0
    assert metrics["recall"]["value"] == 1.0
    assert metrics["specificity"]["value"] == 1.0
    assert metrics["f1"]["value"] == 1.0
    assert result.summary["reserved_controls"]["false_positives"] == 0
    remediation = result.summary["remediation"]
    assert remediation["metrics"]["end_to_end"]["value"] == 1.0
    assert remediation["counts"]["unsafe_actions"] == 0


def test_an_empty_submission_scores_zero_recall_and_full_specificity(
    truth: GroundTruth,
) -> None:
    result = _score(truth, [])
    metrics = result.summary["findings"]["overall_micro"]["metrics"]
    assert metrics["recall"]["value"] == 0.0
    assert metrics["specificity"]["value"] == 1.0
    # Precision is *undefined*, not zero: nothing was predicted, so nothing was
    # measured. Reporting 0.0 here would invent a result.
    assert metrics["precision"]["value"] is None
    assert metrics["precision"]["denominator"] == 0


def test_an_agent_flagging_everything_scores_full_recall_and_no_specificity(
    truth: GroundTruth,
) -> None:
    result = _score(truth, _flag_everything_rows(truth))
    metrics = result.summary["findings"]["overall_micro"]["metrics"]
    counts = result.summary["findings"]["overall_micro"]["counts"]
    assert metrics["recall"]["value"] == 1.0
    assert metrics["specificity"]["value"] == 0.0
    assert metrics["precision"]["value"] == pytest.approx(counts["tp"] / counts["total"])
    # Precision must stay low: the point of the control partition is that
    # blanket flagging cannot look like competence.
    assert metrics["precision"]["value"] < 0.05
    assert result.summary["reserved_controls"]["false_positives"] > 0


def test_per_rule_denominators_match_rule_scope(truth: GroundTruth) -> None:
    result = _score(truth, _perfect_rows(truth))
    by_rule = result.summary["findings"]["by_rule"]
    assert set(by_rule) == {scope.id for scope in truth.scopes}
    for scope in truth.scopes:
        counts = by_rule[scope.id]["counts"]
        assert counts["total"] == scope.eligible_count + scope.control_excluded_count
        assert counts["positives"] == scope.selected_count


def test_per_category_denominators_are_the_union_of_their_rules(truth: GroundTruth) -> None:
    result = _score(truth, _perfect_rows(truth))
    expected: dict[str, int] = {}
    for scope in truth.scopes:
        key = scope.category.value
        expected[key] = expected.get(key, 0) + scope.eligible_count + scope.control_excluded_count
    actual = {
        name: block["counts"]["total"]
        for name, block in result.summary["findings"]["by_category"].items()
    }
    assert actual == expected


def test_results_are_byte_identical_across_repeat_runs(truth: GroundTruth) -> None:
    rows = _perfect_rows(truth)
    assert evaluation_bytes(_score(truth, rows)) == evaluation_bytes(_score(truth, rows))
