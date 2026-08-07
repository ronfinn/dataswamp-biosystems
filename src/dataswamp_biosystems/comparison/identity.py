"""Benchmark identity, and the compatibility gate that guards every comparison.

A metric delta is only meaningful when both sides measured the *same universe*.
Two runs against different seeds, profiles or generator versions produce numbers
that subtract cleanly and mean nothing — which is worse than refusing, because
the result looks like an answer. So the comparison refuses, and names every
field that differs.

The identity is read from the evaluator's own output. Three groups of fields:

* **Universe** — which ground truth was scored. ``ground_truth_fingerprint`` is
  the decisive one: it is a digest of the emitted observed ledgers, so it
  already covers the config, the truth graph and the defect selection that
  produced them. The seeds, profile and observed generator/schema versions are
  checked alongside it because when they differ the fingerprint differs too, and
  naming the *cause* is far more useful than reporting a changed hash.
* **Contract** — which evaluator produced the numbers. Differencing metrics
  across evaluator versions or schema versions compares two definitions of the
  metric, not two agents.
* **Shape** — the derived size of the evaluation universe. Redundant given a
  matching fingerprint, and checked anyway: it is the cheap tripwire that
  catches a hand-edited or mis-assembled summary whose fingerprint was left
  intact.

There is deliberately no *config fingerprint* field: the evaluator does not emit
one, and the comparison layer refuses to reach past the evaluation contract to
recover it. ``ground_truth_fingerprint`` is the evaluator's expression of the
same fact.

The submission's own ``prediction_sha256`` is **not** identity. Two runs of the
same predictions are a legitimate comparison — it is how the determinism of the
comparison itself is tested — and requiring predictions to differ would forbid
the most useful sanity check there is.
"""

from __future__ import annotations

from typing import Any

from dataswamp_biosystems.comparison.errors import IdentityMismatchCollector
from dataswamp_biosystems.comparison.loader import EvaluationRun

# ``(reported field name, summary path)``. The field name is what an error
# message shows, so it reads as the thing the author changed.
_UNIVERSE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ground_truth_fingerprint", ("benchmark", "ground_truth_fingerprint")),
    ("profile", ("benchmark", "profile")),
    ("truth_seed", ("benchmark", "truth_seed")),
    ("defect_seed", ("benchmark", "defect_seed")),
    ("observed_generator_version", ("benchmark", "observed_generator_version")),
    ("observed_schema_version", ("benchmark", "observed_schema_version")),
)

_CONTRACT_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("evaluator_version", ("evaluator_version",)),
    ("evaluation_schema_version", ("evaluation_schema_version",)),
    ("prediction_schema_version", ("prediction_schema_version",)),
)

_SHAPE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("universe.rules", ("universe", "rules")),
    ("universe.evaluated_pairs", ("universe", "evaluated_pairs")),
    ("universe.positive_pairs", ("universe", "positive_pairs")),
    ("universe.negative_pairs", ("universe", "negative_pairs")),
    ("universe.reserved_control_pairs", ("universe", "reserved_control_pairs")),
    ("universe.rules_by_difficulty", ("universe", "rules_by_difficulty")),
    ("adversarial.scenarios", ("adversarial", "scenarios")),
    ("adversarial.scenario_pairs", ("adversarial", "scenario_pairs")),
    ("adversarial.near_miss_controls.declared", ("adversarial", "near_miss_controls", "declared")),
)

IDENTITY_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    _UNIVERSE_FIELDS + _CONTRACT_FIELDS + _SHAPE_FIELDS
)


def _dig(summary: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Return a nested summary value, or ``None`` when any step is absent."""
    node: Any = summary
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def benchmark_identity(run: EvaluationRun) -> dict[str, Any]:
    """Return the identity fields of one run, in a stable order."""
    return {name: _dig(run.summary, path) for name, path in IDENTITY_FIELDS}


def check_compatible(baseline: EvaluationRun, candidate: EvaluationRun) -> dict[str, Any]:
    """Raise unless both runs describe the same benchmark universe.

    Returns the shared identity on success, so a caller that needs it does not
    have to recompute it. Raises :class:`IncompatibleRunsError` naming every
    differing field — never only the first.
    """
    left = benchmark_identity(baseline)
    right = benchmark_identity(candidate)

    collector = IdentityMismatchCollector()
    for name, _ in IDENTITY_FIELDS:
        collector.compare(name, left[name], right[name])
    collector.raise_if_any()

    return left


__all__ = ["IDENTITY_FIELDS", "benchmark_identity", "check_compatible"]
