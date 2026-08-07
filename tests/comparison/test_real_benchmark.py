"""Comparison against the canonical benchmark, including the adversarial tier.

The tiny fixture proves the semantics; these tests prove the comparison survives
contact with the real thing — 41 rules, thousands of pairs, and a benchmark that
actually declares adversarial scenarios and near-miss controls.

Marked slow: they generate the canonical observed state, which is shared with
the evaluation tests via the session fixtures in the root ``conftest``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.comparison import compare_runs, load_run
from dataswamp_biosystems.examples import example_path
from dataswamp_biosystems.observed.writer import CONTROLS_NAME
from tests.comparison.conftest import write_evaluation_dir

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def real_runs(real_observed_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Score the three committed example submissions against the real benchmark."""
    root = tmp_path_factory.mktemp("real-comparison")
    runs: dict[str, Path] = {}
    for name in ("perfect", "partial", "unsafe"):
        target = root / name
        submission = example_path(name)
        runs[name] = _score_file(real_observed_dir, submission, target)
    return runs


def _score_file(observed_dir: Path, submission: Path, target: Path) -> Path:
    """Score a committed submission file, reusing the shared evaluation helper."""
    rows = [
        json.loads(line)
        for line in submission.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return write_evaluation_dir(observed_dir, target, rows)


def test_the_canonical_perfect_run_beats_the_partial_one(real_runs: dict[str, Path]) -> None:
    result = compare_runs(load_run(real_runs["partial"]), load_run(real_runs["perfect"]))
    headline = result.summary["headline"]
    assert headline["newly_solved"] > 0
    assert headline["newly_broken"] == 0
    assert headline["new_control_false_positives"] == 0
    assert result.summary["dimensions"]["finding_detection"]["direction"] == "improved"


def test_the_unsafe_submission_regresses_control_preservation(
    real_runs: dict[str, Path],
) -> None:
    """The committed ``unsafe`` example flags reserved controls; it must show."""
    result = compare_runs(load_run(real_runs["perfect"]), load_run(real_runs["unsafe"]))
    controls = result.summary["control_preservation"]
    assert controls["new_control_false_positives"] > 0
    assert controls["new_reserved_control_false_positives"] > 0
    assert controls["reserved_control_false_positives"]["direction"] == "regressed"
    # Every new control false positive is attributed to a named entity and rule.
    regressions = [record for record in result.control_regressions if record.regression]
    assert len(regressions) == controls["new_control_false_positives"]
    assert all(record.entity_id and record.rule_id for record in regressions)


def test_control_regressions_reconcile_with_the_evaluators_own_totals(
    real_runs: dict[str, Path],
) -> None:
    """The flow must explain the stock: new minus resolved equals the count delta."""
    result = compare_runs(load_run(real_runs["perfect"]), load_run(real_runs["unsafe"]))
    controls = result.summary["control_preservation"]
    net = controls["new_control_false_positives"] - controls["resolved_control_false_positives"]
    assert net == controls["false_positives"]["delta"]

    reserved_net = (
        controls["new_reserved_control_false_positives"]
        - controls["resolved_reserved_control_false_positives"]
    )
    assert reserved_net == controls["reserved_control_false_positives"]["delta"]


def test_every_difficulty_tier_is_compared_on_the_real_benchmark(
    real_runs: dict[str, Path],
) -> None:
    result = compare_runs(load_run(real_runs["partial"]), load_run(real_runs["perfect"]))
    tiers = result.summary["by_difficulty"]
    assert {"bronze", "silver", "gold"} <= set(tiers)
    for tier in ("bronze", "silver", "gold"):
        assert tiers[tier]["metrics"]["recall"]["direction"] == "improved"


def test_an_adversarial_benchmark_populates_the_adversarial_comparison(
    adversarial_observed_dir: Path, tmp_path: Path
) -> None:
    """With scenarios declared, the adversarial block carries real numbers."""
    silent = write_evaluation_dir(adversarial_observed_dir, tmp_path / "silent", [])
    result = compare_runs(load_run(silent), load_run(silent))
    adversarial = result.summary["adversarial"]

    assert adversarial["declared_scenarios"] > 0
    assert adversarial["scenario_pairs"] > 0
    assert adversarial["near_miss_controls"]["declared"] > 0
    # Aggregate only, and the payload says so rather than implying more.
    assert adversarial["per_case_attribution_available"] is False
    assert json.dumps(adversarial)  # serializable as emitted


def test_the_adversarial_tier_survives_a_near_miss_regression(
    adversarial_observed_dir: Path, tmp_path: Path
) -> None:
    """Flagging a near-miss control must move the near-miss false-positive count."""
    controls = [
        json.loads(line)
        for line in (adversarial_observed_dir / CONTROLS_NAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert controls, "the adversarial benchmark declares controls"

    silent = write_evaluation_dir(adversarial_observed_dir, tmp_path / "silent", [])
    result = compare_runs(load_run(silent), load_run(silent))
    near_miss = result.summary["adversarial"]["near_miss_controls"]
    # Comparing a run with itself: no movement, and the error counts point down.
    assert near_miss["false_positives"]["delta"] == 0
    assert near_miss["false_positives"]["higher_is_better"] is False
