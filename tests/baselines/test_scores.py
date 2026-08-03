"""The published canonical baseline scores, and the properties behind them.

``tests/baselines/fixtures/baseline-scores.json`` pins what each baseline scores
against the canonical ``demo`` scenario, and the first test here recomputes it.
That pin is necessarily circular — it is generated from the same code — so the
rest of the module asserts properties that come from the *benchmark's* semantics
rather than from the fixture. A regeneration that laundered a broken agent into a
green suite would still have to get past those.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.baselines import (
    BASELINE_NAMES,
    ObservedInput,
    get_baseline,
    render_predictions,
    run_baseline,
)
from dataswamp_biosystems.evaluation import (
    GroundTruth,
    evaluate,
    parse_predictions,
    prediction_digest,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "baseline-scores.json"


@pytest.fixture(scope="session")
def expected_scores() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return document


@pytest.fixture(scope="session")
def actual_scores(real_observed_dir: Path) -> dict[str, Any]:
    import scripts.update_baseline_scores as generator

    return generator.build_scores(real_observed_dir)


def test_the_committed_scores_match_the_agents(
    expected_scores: dict[str, Any], actual_scores: dict[str, Any]
) -> None:
    """Regenerate the fixture in memory and compare it whole.

    Failing here means a baseline's published result has changed. That is a
    reviewed edit, not a test to relax: rerun
    ``scripts/update_baseline_scores.py --confirm --reason ...`` and update the
    score tables in ``README.md`` and ``docs/baselines.md``.
    """
    assert actual_scores == expected_scores


def test_the_fixture_records_the_scenario_the_scores_belong_to(
    expected_scores: dict[str, Any],
) -> None:
    """A score without its scenario identity is not comparable to anything."""
    benchmark = expected_scores["benchmark"]
    for key in (
        "profile",
        "defect_seed",
        "truth_seed",
        "generator_version",
        "truth_generator_version",
        "ground_truth_fingerprint",
    ):
        assert benchmark[key], f"missing scenario identity: {key}"
    assert benchmark["profile"] == "demo"


def test_the_fixture_covers_every_registered_baseline(expected_scores: dict[str, Any]) -> None:
    assert set(expected_scores["baselines"]) == set(BASELINE_NAMES)


# -- properties that do not come from the fixture ----------------------------


@pytest.fixture(scope="session")
def summaries(real_observed_dir: Path, ground_truth: GroundTruth) -> dict[str, Any]:
    """Score every baseline once, through the ordinary evaluator."""
    observed = ObservedInput.load(real_observed_dir)
    scored: dict[str, Any] = {}
    for name in BASELINE_NAMES:
        run = run_baseline(get_baseline(name), observed)
        text = render_predictions(run.predictions)
        submitted = parse_predictions(
            text, known_entities=ground_truth.known_entities, known_rules=ground_truth.rule_ids
        )
        scored[name] = evaluate(
            ground_truth, submitted, prediction_digest=prediction_digest(text.encode("utf-8"))
        ).summary
    return scored


def test_the_null_baseline_is_the_recall_floor_and_specificity_ceiling(
    summaries: dict[str, Any],
) -> None:
    micro = summaries["null"]["findings"]["overall_micro"]
    assert micro["counts"]["tp"] == 0
    assert micro["counts"]["fp"] == 0
    assert micro["metrics"]["recall"]["value"] == 0.0
    assert micro["metrics"]["specificity"]["value"] == 1.0


def test_the_null_baselines_precision_is_undefined_not_zero(summaries: dict[str, Any]) -> None:
    """The failure mode this benchmark exists to avoid, checked on the floor itself."""
    precision = summaries["null"]["findings"]["overall_micro"]["metrics"]["precision"]
    assert precision["value"] is None
    assert precision["denominator"] == 0


def test_the_naive_baseline_is_less_precise_than_the_rule_based_one(
    summaries: dict[str, Any],
) -> None:
    naive = summaries["naive-metadata"]["findings"]["overall_micro"]["metrics"]["precision"][
        "value"
    ]
    rules = summaries["rule-based"]["findings"]["overall_micro"]["metrics"]["precision"]["value"]
    assert naive is not None and rules is not None
    assert naive < rules, "the shallow agent must not out-precision the structural one"
    assert naive < 1.0, "a shallow heuristic that never misfires is not a naive baseline"


def test_the_rule_based_baseline_recalls_more_than_the_naive_one(
    summaries: dict[str, Any],
) -> None:
    naive = summaries["naive-metadata"]["findings"]["overall_micro"]["metrics"]["recall"]["value"]
    rules = summaries["rule-based"]["findings"]["overall_micro"]["metrics"]["recall"]["value"]
    assert rules > naive > 0.0


def test_no_baseline_approaches_perfect_recall(summaries: dict[str, Any]) -> None:
    """The baselines are a floor to beat, not a solved benchmark.

    A baseline that recalled nearly everything would mean either the rules are
    trivial or the agent is reading the answers. Either is a reason to stop.
    """
    for name in BASELINE_NAMES:
        recall = summaries[name]["findings"]["overall_micro"]["metrics"]["recall"]["value"]
        assert recall is not None
        assert recall < 0.75, f"{name} recalls {recall:.4f}; check for ground-truth leakage"


def test_no_baseline_makes_an_out_of_scope_claim(summaries: dict[str, Any]) -> None:
    for name in BASELINE_NAMES:
        assert summaries[name]["out_of_scope"]["false_positives"] == 0


def test_no_baseline_proposes_an_unsafe_remediation(summaries: dict[str, Any]) -> None:
    """An unsafe action on a clean entity is the outcome the scorecard isolates."""
    for name in BASELINE_NAMES:
        assert summaries[name]["remediation"]["counts"]["unsafe_actions"] == 0


def test_the_naive_baseline_proposes_no_remediations(summaries: dict[str, Any]) -> None:
    """Detection without a fix is a documented position, not an oversight."""
    assert summaries["naive-metadata"]["remediation"]["counts"]["submitted"] == 0


def test_the_reserved_control_partition_is_reported_for_every_baseline(
    expected_scores: dict[str, Any],
) -> None:
    for name in BASELINE_NAMES:
        reserved = expected_scores["baselines"][name]["reserved_controls"]
        assert reserved["pairs"] > 0
        assert reserved["false_positive_rate"] is not None
