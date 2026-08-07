"""The compatibility gate: what must match before a delta means anything.

Every rejection below is a case where the arithmetic would still work. That is
the point — subtracting two numbers from different universes always produces a
number, and the number is worthless. Each test proves the comparison refuses
*and* names the field, because "incompatible" without a cause is not actionable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.comparison import (
    IncompatibleRunsError,
    benchmark_identity,
    compare_runs,
    load_run,
)
from dataswamp_biosystems.evaluation.writer import EVALUATION_SUMMARY_NAME
from tests.comparison.conftest import DEFECTS, finding


def _rewrite_summary(run_dir: Path, mutate) -> Path:  # noqa: ANN001
    """Apply ``mutate`` to a copy of the run's summary, in place."""
    path = run_dir / EVALUATION_SUMMARY_NAME
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return run_dir


def _mismatch_fields(baseline: Path, candidate: Path) -> list[str]:
    with pytest.raises(IncompatibleRunsError) as caught:
        compare_runs(load_run(baseline), load_run(candidate))
    return [mismatch.field for mismatch in caught.value.mismatches]


def test_a_run_is_compatible_with_itself(perfect_run: Path) -> None:
    result = compare_runs(load_run(perfect_run), load_run(perfect_run))
    assert result.summary["runs"]["identical_submission"] is True


def test_identity_is_read_from_the_evaluators_own_output(perfect_run: Path) -> None:
    identity = benchmark_identity(load_run(perfect_run))
    assert identity["ground_truth_fingerprint"]
    assert identity["profile"] == "tiny-eval"
    assert identity["evaluator_version"]
    # The submission digest is deliberately *not* identity: comparing a run with
    # itself is the determinism check, and must stay legal.
    assert "prediction_sha256" not in identity


def test_a_different_ground_truth_fingerprint_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(
        other, lambda p: p["benchmark"].__setitem__("ground_truth_fingerprint", "0" * 64)
    )
    assert "ground_truth_fingerprint" in _mismatch_fields(perfect_run, other)


def test_a_different_profile_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(other, lambda p: p["benchmark"].__setitem__("profile", "some-other-profile"))
    assert "profile" in _mismatch_fields(perfect_run, other)


def test_a_different_truth_seed_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(other, lambda p: p["benchmark"].__setitem__("truth_seed", 999))
    assert "truth_seed" in _mismatch_fields(perfect_run, other)


def test_a_different_defect_seed_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(other, lambda p: p["benchmark"].__setitem__("defect_seed", 4242))
    assert "defect_seed" in _mismatch_fields(perfect_run, other)


def test_a_different_observed_generator_version_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(
        other, lambda p: p["benchmark"].__setitem__("observed_generator_version", "99.0.0")
    )
    assert "observed_generator_version" in _mismatch_fields(perfect_run, other)


def test_a_different_evaluator_version_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    """Two evaluator versions are two definitions of the metric, not two agents."""
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(other, lambda p: p.__setitem__("evaluator_version", "99.0.0"))
    assert "evaluator_version" in _mismatch_fields(perfect_run, other)


def test_a_different_evaluation_schema_version_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(other, lambda p: p.__setitem__("evaluation_schema_version", 99))
    assert "evaluation_schema_version" in _mismatch_fields(perfect_run, other)


def test_a_different_universe_shape_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    """The tripwire for a summary whose fingerprint was left intact by hand."""
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(other, lambda p: p["universe"].__setitem__("evaluated_pairs", 10_000))
    assert "universe.evaluated_pairs" in _mismatch_fields(perfect_run, other)


def test_a_different_difficulty_composition_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(
        other,
        lambda p: p["universe"].__setitem__("rules_by_difficulty", {"bronze": 99}),
    )
    assert "universe.rules_by_difficulty" in _mismatch_fields(perfect_run, other)


def test_a_different_scenario_count_is_rejected(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(other, lambda p: p["adversarial"].__setitem__("scenarios", 6))
    assert "adversarial.scenarios" in _mismatch_fields(perfect_run, other)


def test_every_differing_field_is_reported_not_only_the_first(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    """An author who changed seed *and* profile should learn both at once."""
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])

    def mutate(payload: dict[str, Any]) -> None:
        payload["benchmark"]["profile"] = "elsewhere"
        payload["benchmark"]["truth_seed"] = 1
        payload["benchmark"]["defect_seed"] = 2

    _rewrite_summary(other, mutate)
    fields = _mismatch_fields(perfect_run, other)
    assert {"profile", "truth_seed", "defect_seed"} <= set(fields)


def test_the_error_message_names_both_values(perfect_run: Path, make_run) -> None:  # noqa: ANN001
    other = make_run("other", [finding(entity, rule) for entity, rule in DEFECTS])
    _rewrite_summary(other, lambda p: p["benchmark"].__setitem__("profile", "elsewhere"))
    with pytest.raises(IncompatibleRunsError) as caught:
        compare_runs(load_run(perfect_run), load_run(other))
    message = str(caught.value)
    assert "profile" in message
    assert "tiny-eval" in message
    assert "elsewhere" in message
