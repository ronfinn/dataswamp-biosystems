"""The null baseline: claims nothing at all.

This is the floor, and it is a more interesting floor than it looks. Silence on
a pair is scored as a negative prediction, so a submission containing no lines
earns every true negative in the universe and misses every defect: recall 0.0,
specificity 1.0, and precision and F1 *undefined* rather than zero, because
their denominators are empty.

That last point is the reason this baseline is worth publishing. A benchmark
that reported the null agent's precision as ``0.0`` would be quietly lying about
a quantity it never measured, and a benchmark that folded specificity into a
composite score would rank doing nothing above trying. Publishing the null
baseline makes both failure modes visible in the first row of the table.
"""

from __future__ import annotations

from collections.abc import Iterator

from dataswamp_biosystems.baselines.base import BaselineInfo
from dataswamp_biosystems.baselines.observed_input import ObservedInput
from dataswamp_biosystems.evaluation.predictions import Prediction

NULL_BASELINE_VERSION = "1.0.0"


class NullBaseline:
    """Emits an empty submission."""

    info = BaselineInfo(
        name="null",
        version=NULL_BASELINE_VERSION,
        summary="Predicts nothing. Establishes the recall floor and the specificity ceiling.",
        reads=(),
    )

    def predict(self, observed: ObservedInput) -> Iterator[Prediction]:
        """Yield nothing. ``observed`` is accepted, and deliberately not read."""
        return iter(())


__all__ = ["NULL_BASELINE_VERSION", "NullBaseline"]
