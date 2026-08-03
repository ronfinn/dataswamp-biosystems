"""Confusion-matrix counts and the metrics derived from them.

Two rules govern everything here.

**Every metric is derived from counts, never from other metrics.** Aggregates
are computed by summing the underlying TP/FP/FN/TN and dividing once (micro),
not by averaging percentages. Macro aggregation is offered separately and
labelled as such, with the number of groups it averaged over reported alongside,
so a macro figure can never be mistaken for a micro one.

**An undefined metric is reported as undefined.** Precision with no predicted
positives is not zero — it is a question that was never asked. Emitting ``0.0``
there would make a silent agent look maximally imprecise and would drag every
average down with a number nobody measured. Each metric therefore carries its
numerator, its denominator, and a ``value`` that is ``null`` exactly when the
denominator is zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# The metrics computed for every breakdown, in report order.
METRIC_NAMES: tuple[str, ...] = (
    "precision",
    "recall",
    "specificity",
    "f1",
    "false_positive_rate",
    "false_negative_rate",
)


@dataclass(frozen=True)
class Counts:
    """The four confusion-matrix cells for one group of evaluated pairs."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def __add__(self, other: Counts) -> Counts:
        return Counts(
            tp=self.tp + other.tp,
            fp=self.fp + other.fp,
            fn=self.fn + other.fn,
            tn=self.tn + other.tn,
        )

    @property
    def positives(self) -> int:
        """Ground-truth positives: the pairs a defect was actually injected into."""
        return self.tp + self.fn

    @property
    def negatives(self) -> int:
        """Ground-truth negatives: in-scope pairs carrying no defect."""
        return self.tn + self.fp

    @property
    def predicted_positive(self) -> int:
        return self.tp + self.fp

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    def as_dict(self) -> dict[str, int]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "positives": self.positives,
            "negatives": self.negatives,
            "predicted_positive": self.predicted_positive,
            "total": self.total,
        }


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    """Return one metric as ``{value, numerator, denominator}``.

    ``value`` is ``None`` — serialized as JSON ``null`` — exactly when the
    denominator is zero, so a consumer can tell "measured as zero" from "not
    measurable" without inspecting the counts.
    """
    value = numerator / denominator if denominator else None
    return {"value": value, "numerator": numerator, "denominator": denominator}


def metrics_from_counts(counts: Counts) -> dict[str, dict[str, Any]]:
    """Return every metric for one group, each with its own numerator/denominator.

    F1 is computed from counts directly (``2TP / (2TP + FP + FN)``) rather than
    from precision and recall, so it stays defined whenever any of those counts
    is non-zero and never has to special-case an undefined input.
    """
    return {
        "precision": ratio(counts.tp, counts.predicted_positive),
        "recall": ratio(counts.tp, counts.positives),
        "specificity": ratio(counts.tn, counts.negatives),
        "f1": ratio(2 * counts.tp, 2 * counts.tp + counts.fp + counts.fn),
        "false_positive_rate": ratio(counts.fp, counts.negatives),
        "false_negative_rate": ratio(counts.fn, counts.positives),
    }


def metric_block(counts: Counts) -> dict[str, Any]:
    """Return the standard ``{counts, metrics}`` block used everywhere in the report."""
    return {"counts": counts.as_dict(), "metrics": metrics_from_counts(counts)}


def total_counts(groups: Iterable[Counts]) -> Counts:
    """Sum confusion-matrix cells across groups (the basis of every micro metric)."""
    total = Counts()
    for counts in groups:
        total = total + counts
    return total


def micro_block(groups: Mapping[str, Counts]) -> dict[str, Any]:
    """Return the micro-averaged block: sum the cells, then divide once."""
    return metric_block(total_counts(groups.values()))


def macro_block(groups: Mapping[str, Counts]) -> dict[str, Any]:
    """Return the macro-averaged block: unweighted mean of each *defined* group value.

    Groups where a metric is undefined are excluded from that metric's mean
    rather than being counted as zero, and the number of groups that did
    contribute is reported as ``group_count`` — a macro recall averaged over 3
    of 41 rules is a different claim from one averaged over all 41, and the
    report must say which it is.
    """
    per_group = {name: metrics_from_counts(counts) for name, counts in sorted(groups.items())}
    macro: dict[str, Any] = {}
    for metric in METRIC_NAMES:
        values = [
            block[metric]["value"]
            for block in per_group.values()
            if block[metric]["value"] is not None
        ]
        macro[metric] = {
            "value": sum(values) / len(values) if values else None,
            "group_count": len(values),
            "total_groups": len(per_group),
        }
    return macro


def breakdown(groups: Mapping[str, Counts]) -> dict[str, dict[str, Any]]:
    """Return a key-sorted ``{group: block}`` mapping for a categorical breakdown."""
    return {name: metric_block(groups[name]) for name in sorted(groups)}


__all__ = [
    "METRIC_NAMES",
    "Counts",
    "ratio",
    "metrics_from_counts",
    "metric_block",
    "total_counts",
    "micro_block",
    "macro_block",
    "breakdown",
]
