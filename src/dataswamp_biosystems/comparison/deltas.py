"""Metric and count deltas, with direction stated rather than implied.

Two rules govern everything here, and both are inherited from the evaluator.

**An undefined metric stays undefined.** If either side's ``value`` is ``null``,
the delta is ``null`` and the direction is ``undefined``. Treating "not
measurable" as zero would manufacture an improvement or a regression out of a
question nobody asked — precisely the failure the evaluator refuses to make, and
it would be worse here, because a fabricated zero on one side silently becomes a
fabricated *delta* on the other. Both sides' numerators and denominators travel
with every delta so a reader can see what was and was not measured.

**Direction is a field, not a sign.** ``recall`` rising is an improvement;
``false_positive_rate`` rising is a regression; a false-positive *count* rising
is a regression. Encoding that in the sign of a number and expecting every
consumer to remember which way each metric points is how a dashboard ends up
reporting a regression as progress. Every delta therefore carries an explicit
``direction`` — ``improved``, ``regressed``, ``unchanged`` or ``undefined`` —
alongside the ``higher_is_better`` flag that produced it.

The raw ``delta`` is always ``candidate - baseline``, unmodified. It is the
honest arithmetic difference; ``direction`` is what interprets it. Sign is never
flipped to make "positive means better" true by construction, because a flipped
number that disagrees with the two values printed beside it is its own trap.
"""

from __future__ import annotations

from typing import Any

IMPROVED = "improved"
REGRESSED = "regressed"
UNCHANGED = "unchanged"
UNDEFINED = "undefined"

# Metrics where a larger value is a better result. Everything the evaluator
# emits that is not listed here is a rate of getting things wrong.
_HIGHER_IS_BETTER: frozenset[str] = frozenset(
    {
        "precision",
        "recall",
        "specificity",
        "f1",
        "coverage",
        "correctness_given_true_positive",
        "end_to_end",
        "action_class_correct",
        "availability_correct",
        "approval_policy_correct",
        "approver_role_correct",
        "recommended_value_correct",
        "non_remediation_correct",
        "non_remediation_end_to_end",
        "no_remediation_correct",
    }
)

_LOWER_IS_BETTER: frozenset[str] = frozenset(
    {
        "false_positive_rate",
        "false_negative_rate",
        "abstention_rate",
    }
)


def higher_is_better(metric: str) -> bool:
    """Return whether a larger value of ``metric`` is the better outcome.

    Unknown metric names default to *higher is better*, matching every quality
    metric the evaluator emits; the error-rate names are enumerated explicitly
    above so a new one cannot be silently misread as a quality metric.
    """
    return metric not in _LOWER_IS_BETTER


def _direction(delta: float | int | None, *, better_when_higher: bool) -> str:
    if delta is None:
        return UNDEFINED
    if delta == 0:
        return UNCHANGED
    improved = delta > 0 if better_when_higher else delta < 0
    return IMPROVED if improved else REGRESSED


def metric_delta(
    metric: str,
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the delta between two ``{value, numerator, denominator}`` blocks.

    Either side may be ``None`` — a breakdown group present in one run and not
    the other — and is reported as undefined rather than as zero.
    """
    better_when_higher = higher_is_better(metric)
    left = None if baseline is None else baseline.get("value")
    right = None if candidate is None else candidate.get("value")
    delta = None if left is None or right is None else right - left
    return {
        "metric": metric,
        "higher_is_better": better_when_higher,
        "baseline": _side(baseline),
        "candidate": _side(candidate),
        "delta": delta,
        "direction": _direction(delta, better_when_higher=better_when_higher),
    }


def _side(block: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return one side of a metric delta, keeping its numerator and denominator."""
    if block is None:
        return None
    return {
        "value": block.get("value"),
        "numerator": block.get("numerator"),
        "denominator": block.get("denominator"),
    }


def count_delta(
    name: str, baseline: int, candidate: int, *, better_when_higher: bool
) -> dict[str, Any]:
    """Return the delta between two plain counts, with direction stated.

    Used for error counts — false positives, unsafe remediations — where the
    issue is explicit that the semantics must not hide behind a signed number.
    """
    delta = candidate - baseline
    return {
        "count": name,
        "higher_is_better": better_when_higher,
        "baseline": baseline,
        "candidate": candidate,
        "delta": delta,
        "direction": _direction(delta, better_when_higher=better_when_higher),
    }


def error_count_delta(name: str, baseline: int, candidate: int) -> dict[str, Any]:
    """A count where fewer is better (false positives, unsafe actions, misses)."""
    return count_delta(name, baseline, candidate, better_when_higher=False)


def success_count_delta(name: str, baseline: int, candidate: int) -> dict[str, Any]:
    """A count where more is better (true positives, correct remediations)."""
    return count_delta(name, baseline, candidate, better_when_higher=True)


def metric_block_delta(
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    *,
    metrics: tuple[str, ...],
) -> dict[str, Any]:
    """Compare two ``{counts, metrics}`` blocks as the evaluator emits them.

    Counts are differenced with their own directions (TP up is good, FP up is
    not), and each named metric gets a full delta. A block missing on one side
    yields undefined deltas rather than being treated as an all-zero block: an
    absent group was not measured as zero, it was not measured.
    """
    left_counts = (baseline or {}).get("counts", {})
    right_counts = (candidate or {}).get("counts", {})
    left_metrics = (baseline or {}).get("metrics", {})
    right_metrics = (candidate or {}).get("metrics", {})

    return {
        "present": {"baseline": baseline is not None, "candidate": candidate is not None},
        "counts": {
            "tp": success_count_delta("tp", left_counts.get("tp", 0), right_counts.get("tp", 0)),
            "fp": error_count_delta("fp", left_counts.get("fp", 0), right_counts.get("fp", 0)),
            "fn": error_count_delta("fn", left_counts.get("fn", 0), right_counts.get("fn", 0)),
            "tn": success_count_delta("tn", left_counts.get("tn", 0), right_counts.get("tn", 0)),
        },
        "metrics": {
            name: metric_delta(
                name,
                left_metrics.get(name) if baseline is not None else None,
                right_metrics.get(name) if candidate is not None else None,
            )
            for name in metrics
        },
    }


def summarize_directions(deltas: list[dict[str, Any]]) -> dict[str, int]:
    """Count how many deltas improved, regressed, stayed level or were undefined."""
    tally = {IMPROVED: 0, REGRESSED: 0, UNCHANGED: 0, UNDEFINED: 0}
    for delta in deltas:
        tally[str(delta["direction"])] += 1
    return tally


__all__ = [
    "IMPROVED",
    "REGRESSED",
    "UNCHANGED",
    "UNDEFINED",
    "higher_is_better",
    "metric_delta",
    "count_delta",
    "error_count_delta",
    "success_count_delta",
    "metric_block_delta",
    "summarize_directions",
]
