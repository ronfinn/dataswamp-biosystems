"""Metric arithmetic in isolation: denominators, undefined values and aggregation."""

from __future__ import annotations

import pytest

from dataswamp_biosystems.evaluation import Counts, macro_block, metric_block, metrics_from_counts


def test_counts_expose_every_denominator() -> None:
    counts = Counts(tp=3, fp=2, fn=1, tn=4)
    assert counts.positives == 4
    assert counts.negatives == 6
    assert counts.predicted_positive == 5
    assert counts.total == 10


def test_a_perfect_group_scores_one_everywhere() -> None:
    metrics = metrics_from_counts(Counts(tp=5, tn=5))
    assert metrics["precision"]["value"] == 1.0
    assert metrics["recall"]["value"] == 1.0
    assert metrics["specificity"]["value"] == 1.0
    assert metrics["f1"]["value"] == 1.0
    assert metrics["false_positive_rate"]["value"] == 0.0
    assert metrics["false_negative_rate"]["value"] == 0.0


def test_precision_is_undefined_with_no_predicted_positives() -> None:
    """Silence is not imprecision — a zero here would be a fabricated measurement."""
    precision = metrics_from_counts(Counts(fn=4, tn=6))["precision"]
    assert precision["value"] is None
    assert precision["denominator"] == 0


def test_recall_is_undefined_with_no_positives() -> None:
    recall = metrics_from_counts(Counts(fp=1, tn=6))["recall"]
    assert recall["value"] is None
    assert recall["numerator"] == 0


def test_specificity_is_undefined_with_no_negatives() -> None:
    metrics = metrics_from_counts(Counts(tp=2, fn=1))
    assert metrics["specificity"]["value"] is None
    assert metrics["false_positive_rate"]["value"] is None


def test_an_entirely_empty_group_defines_nothing() -> None:
    metrics = metrics_from_counts(Counts())
    assert all(metric["value"] is None for metric in metrics.values())


def test_f1_is_derived_from_counts_not_from_precision_and_recall() -> None:
    """F1 stays defined when precision alone is not, because it never divides by it."""
    metrics = metrics_from_counts(Counts(tp=0, fp=0, fn=3, tn=1))
    assert metrics["precision"]["value"] is None
    assert metrics["f1"]["value"] == 0.0


def test_micro_and_macro_differ_and_say_which_they_are() -> None:
    """A large group and a tiny one: micro follows the mass, macro follows the count."""
    groups = {
        "big": Counts(tp=90, fp=10, fn=0, tn=100),
        "small": Counts(tp=0, fp=1, fn=1, tn=1),
    }
    micro = metric_block(groups["big"] + groups["small"])["metrics"]
    macro = macro_block(groups)
    assert micro["precision"]["value"] == pytest.approx(90 / 101)
    assert macro["precision"]["value"] == pytest.approx((90 / 100 + 0 / 1) / 2)
    assert macro["precision"]["group_count"] == 2
    assert macro["precision"]["total_groups"] == 2


def test_macro_skips_undefined_groups_and_reports_how_many_contributed() -> None:
    groups = {
        "measured": Counts(tp=1, fp=1, fn=0, tn=1),
        "unmeasurable": Counts(fn=2, tn=2),  # no predicted positives at all
    }
    macro = macro_block(groups)
    assert macro["precision"]["value"] == 0.5
    assert macro["precision"]["group_count"] == 1
    assert macro["precision"]["total_groups"] == 2


def test_macro_over_no_groups_is_undefined_rather_than_zero() -> None:
    macro = macro_block({})
    assert macro["f1"]["value"] is None
    assert macro["f1"]["total_groups"] == 0


def test_counts_add_cellwise() -> None:
    assert Counts(tp=1, fp=2) + Counts(fn=3, tn=4) == Counts(tp=1, fp=2, fn=3, tn=4)
