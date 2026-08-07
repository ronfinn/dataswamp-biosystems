"""Compare two emitted evaluation runs and report what changed.

The engine is a pure function of two already-emitted evaluation directories. It
re-scores nothing, reads no prediction file and never touches ground truth: the
numbers it reports are the evaluator's own, differenced. That is what keeps a
comparison from quietly disagreeing with the evaluations it compares.

Attribution works at the pair level, on ``(entity_id, rule_id)`` — the same unit
the evaluator scores — so a regression is always attributable to a named rule
and a named entity rather than merely visible in an aggregate.

Two things are deliberately *not* attempted. The evaluator does not emit
per-pair difficulty or per-pair scenario membership, so tier and adversarial
comparison is aggregate-only, drawn from the blocks the evaluator publishes;
recovering that membership would mean reaching past the evaluation contract into
the rule registry or the answer key, which is exactly the coupling this layer
exists without. And no threshold, gate or pass/fail verdict is computed: the
command answers *what changed*, and what to do about it is a policy question
this release does not have a contract for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dataswamp_biosystems.comparison.deltas import (
    REGRESSED,
    error_count_delta,
    metric_block_delta,
    metric_delta,
    success_count_delta,
    summarize_directions,
)
from dataswamp_biosystems.comparison.entities import (
    ControlRegressionRecord,
    PairTransition,
    PairTransitionRecord,
    RemediationRegressionRecord,
    RemediationTransition,
    RuleRegressionRecord,
    RuleStatus,
)
from dataswamp_biosystems.comparison.identity import check_compatible
from dataswamp_biosystems.comparison.loader import EvaluationRun

COMPARATOR_VERSION = "1.0.0"
# The comparison layer versions its own on-disk contract. Nothing here changes
# the truth, estate, observed, prediction, evaluation or bundle schemas: it
# consumes them and adds a new artefact beside them.
COMPARISON_SCHEMA_VERSION = 1

# The metrics compared for every confusion-matrix block, in report order.
COMPARED_METRICS: tuple[str, ...] = (
    "precision",
    "recall",
    "specificity",
    "f1",
    "false_positive_rate",
    "false_negative_rate",
)

_REMEDIATION_METRICS: tuple[str, ...] = (
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
)

# Outcomes that sit inside the confusion matrix. Anything else is out-of-scope
# bookkeeping and must never be differenced as though it were a matrix cell.
_MATRIX = frozenset({"tp", "fp", "fn", "tn"})

_TRANSITIONS: dict[tuple[str, str], PairTransition] = {
    ("fn", "tp"): PairTransition.NEWLY_SOLVED,
    ("tp", "fn"): PairTransition.NEWLY_BROKEN,
    ("tn", "fp"): PairTransition.NEW_FALSE_POSITIVE,
    ("fp", "tn"): PairTransition.RESOLVED_FALSE_POSITIVE,
}

_REGRESSIONS: frozenset[PairTransition] = frozenset(
    {PairTransition.NEWLY_BROKEN, PairTransition.NEW_FALSE_POSITIVE}
)


@dataclass(frozen=True)
class ComparisonResult:
    """Everything one comparison produced, ready to serialize."""

    summary: dict[str, Any]
    metric_deltas: dict[str, Any]
    pair_transitions: list[PairTransitionRecord]
    rule_regressions: list[RuleRegressionRecord]
    control_regressions: list[ControlRegressionRecord]
    remediation_regressions: list[RemediationRegressionRecord]


def _classify(baseline: str, candidate: str) -> PairTransition:
    """Name the transition between two outcomes, from the candidate's view."""
    known = _TRANSITIONS.get((baseline, candidate))
    if known is not None:
        return known
    in_matrix_before = baseline in _MATRIX
    in_matrix_after = candidate in _MATRIX
    if in_matrix_before and not in_matrix_after:
        return PairTransition.ENTERED_OUT_OF_SCOPE
    if not in_matrix_before and in_matrix_after:
        return PairTransition.LEFT_OUT_OF_SCOPE
    return PairTransition.OTHER


def _implicit_counterpart(present: dict[str, Any]) -> dict[str, Any] | None:
    """Return the missing side of a pair the other run emitted, or ``None``.

    The evaluator emits a finding result only for pairs that carry information —
    anything expected, anything predicted, anything wrong — so an in-scope pair
    that is clean and unpredicted is a **true negative that was never written
    down**. Joining on the intersection alone would therefore drop precisely the
    transition this report exists to surface: a clean control the baseline left
    alone and the candidate has started flagging appears in one file and not the
    other, and would vanish.

    Compatibility has already established that both runs scored the same
    universe, so reconstructing the absent side is reading the contract rather
    than inventing a result. It is only valid for in-scope pairs: an
    out-of-scope record is not a matrix cell, and its absence means the other
    run simply made no such prediction — not that it scored a true negative.
    """
    if not present.get("in_scope", False):
        return None
    return {
        **present,
        "outcome": "tn",
        "predicted_status": "absent",
        "prediction_id": "",
        "confidence": None,
    }


def _pair_transitions(
    baseline: EvaluationRun, candidate: EvaluationRun
) -> list[PairTransitionRecord]:
    """Return every pair whose outcome changed, keyed by ``rule|entity``.

    Walks the *union* of both runs' emitted pairs, reconstructing the implicit
    true negative on whichever side omitted one. Every positive pair is emitted
    by both runs unconditionally, so the union never has to guess about a pair
    that carried a defect.
    """
    records: list[PairTransitionRecord] = []
    pairs = set(baseline.finding_results) | set(candidate.finding_results)
    for entity_id, rule_id in sorted(pairs):
        left = baseline.finding_results.get((entity_id, rule_id))
        right = candidate.finding_results.get((entity_id, rule_id))
        if left is None and right is not None:
            left = _implicit_counterpart(right)
        elif right is None and left is not None:
            right = _implicit_counterpart(left)
        if left is None or right is None:
            continue
        before = str(left.get("outcome", ""))
        after = str(right.get("outcome", ""))
        if before == after:
            continue
        transition = _classify(before, after)
        records.append(
            PairTransitionRecord(
                id=f"{rule_id}|{entity_id}",
                entity_id=entity_id,
                rule_id=rule_id,
                category=str(right.get("category", "")),
                severity=str(right.get("severity", "")),
                entity_kind=str(right.get("entity_kind", "")),
                entity_class=str(right.get("entity_class", "")),
                reserved_control=bool(right.get("reserved_control", False)),
                baseline_outcome=before,
                candidate_outcome=after,
                baseline_predicted_status=str(left.get("predicted_status", "")),
                candidate_predicted_status=str(right.get("predicted_status", "")),
                transition=transition,
                regression=transition in _REGRESSIONS,
            )
        )
    return records


def _control_regressions(
    transitions: list[PairTransitionRecord],
    candidate: EvaluationRun,
) -> list[ControlRegressionRecord]:
    """Lift every control false-positive change into its own first-class record."""
    wanted = {
        PairTransition.NEW_FALSE_POSITIVE: "new-false-positive",
        PairTransition.RESOLVED_FALSE_POSITIVE: "resolved-false-positive",
    }
    records: list[ControlRegressionRecord] = []
    for transition in transitions:
        label = wanted.get(transition.transition)
        if label is None:
            continue
        remediation = candidate.remediation_results.get((transition.entity_id, transition.rule_id))
        records.append(
            ControlRegressionRecord(
                id=transition.id,
                entity_id=transition.entity_id,
                rule_id=transition.rule_id,
                category=transition.category,
                severity=transition.severity,
                entity_class=transition.entity_class,
                reserved_control=transition.reserved_control,
                transition=label,
                regression=label == "new-false-positive",
                unsafe_remediation=bool((remediation or {}).get("unsafe_action", False)),
            )
        )
    return records


def _rule_regressions(
    baseline: EvaluationRun,
    candidate: EvaluationRun,
    transitions: list[PairTransitionRecord],
) -> list[RuleRegressionRecord]:
    """Return one record per rule that changed, ranked by regression impact.

    Impact is a count of pairs that got worse — defects newly missed plus clean
    entities newly flagged — with reserved-control false positives weighted
    above ordinary ones, because a reserved control could never have carried a
    defect and flagging one is the least excusable error available. Ties break
    on the rule id, so the ranking is total and deterministic.
    """
    per_rule: dict[str, dict[str, int]] = {}
    for transition in transitions:
        bucket = per_rule.setdefault(
            transition.rule_id,
            {
                "newly_solved": 0,
                "newly_broken": 0,
                "new_false_positives": 0,
                "resolved_false_positives": 0,
                "new_reserved_control_false_positives": 0,
            },
        )
        if transition.transition is PairTransition.NEWLY_SOLVED:
            bucket["newly_solved"] += 1
        elif transition.transition is PairTransition.NEWLY_BROKEN:
            bucket["newly_broken"] += 1
        elif transition.transition is PairTransition.NEW_FALSE_POSITIVE:
            bucket["new_false_positives"] += 1
            if transition.reserved_control:
                bucket["new_reserved_control_false_positives"] += 1
        elif transition.transition is PairTransition.RESOLVED_FALSE_POSITIVE:
            bucket["resolved_false_positives"] += 1

    # A rule can move its metrics without any pair changing cell only if the
    # universe changed, which compatibility already forbids — but include every
    # rule whose emitted metrics differ anyway, so the report cannot be silent
    # about a difference the evaluator published.
    changed_metrics = {
        rule_id
        for rule_id in set(baseline.rule_metrics) | set(candidate.rule_metrics)
        if baseline.rule_metrics.get(rule_id) != candidate.rule_metrics.get(rule_id)
    }

    scored: list[tuple[int, int, str, dict[str, int]]] = []
    for rule_id in sorted(set(per_rule) | changed_metrics):
        bucket = per_rule.get(
            rule_id,
            {
                "newly_solved": 0,
                "newly_broken": 0,
                "new_false_positives": 0,
                "resolved_false_positives": 0,
                "new_reserved_control_false_positives": 0,
            },
        )
        regression_impact = (
            bucket["newly_broken"]
            + bucket["new_false_positives"]
            + bucket["new_reserved_control_false_positives"]
        )
        improvement_impact = bucket["newly_solved"] + bucket["resolved_false_positives"]
        scored.append((regression_impact, improvement_impact, rule_id, bucket))

    # Worst regression first; then largest improvement; then rule id.
    scored.sort(key=lambda row: (-row[0], -row[1], row[2]))

    records: list[RuleRegressionRecord] = []
    for rank, (regression_impact, improvement_impact, rule_id, bucket) in enumerate(scored, 1):
        if regression_impact and improvement_impact:
            status = RuleStatus.MIXED
        elif regression_impact:
            status = RuleStatus.REGRESSED
        elif improvement_impact:
            status = RuleStatus.IMPROVED
        else:
            status = RuleStatus.UNCHANGED
        left = baseline.rule_metrics.get(rule_id)
        right = candidate.rule_metrics.get(rule_id)
        block = metric_block_delta(left, right, metrics=COMPARED_METRICS)
        records.append(
            RuleRegressionRecord(
                id=rule_id,
                rule_id=rule_id,
                status=status,
                rank=rank,
                regression_impact=regression_impact,
                improvement_impact=improvement_impact,
                counts=block["counts"],
                metrics=block["metrics"],
                **bucket,
            )
        )
    return records


def _remediation_regressions(
    baseline: EvaluationRun, candidate: EvaluationRun
) -> list[RemediationRegressionRecord]:
    """Return every remediation decision whose correctness or safety changed.

    Walks the union, not the intersection. The evaluator emits a remediation
    result for every expected finding *and* for an unsafe action attached to a
    false positive — so a remediation proposed against a clean entity exists in
    one run's file and not the other's, and an intersection join would hide the
    newly-unsafe action that matters most. An absent side is a genuine absence
    (no decision was scored), not an implicit correct one.
    """
    records: list[RemediationRegressionRecord] = []
    pairs = set(baseline.remediation_results) | set(candidate.remediation_results)
    for entity_id, rule_id in sorted(pairs):
        left = baseline.remediation_results.get((entity_id, rule_id), {})
        right = candidate.remediation_results.get((entity_id, rule_id), {})

        before_state = str(left.get("state", ""))
        after_state = str(right.get("state", ""))
        before_correct = left.get("fully_correct")
        after_correct = right.get("fully_correct")
        before_unsafe = left.get("unsafe_action")
        after_unsafe = right.get("unsafe_action")
        before_none = left.get("no_remediation_correct")
        after_none = right.get("no_remediation_correct")

        transitions: list[RemediationTransition] = []
        if not before_correct and after_correct:
            transitions.append(RemediationTransition.NEWLY_CORRECT)
        if before_correct and not after_correct:
            transitions.append(RemediationTransition.NEWLY_INCORRECT)
        if not before_unsafe and after_unsafe:
            transitions.append(RemediationTransition.NEWLY_UNSAFE)
        if before_unsafe and not after_unsafe:
            transitions.append(RemediationTransition.RESOLVED_UNSAFE)
        if before_none is not True and after_none is True:
            transitions.append(RemediationTransition.NEWLY_CORRECT_NO_REMEDIATION)
        if before_none is True and after_none is not True:
            transitions.append(RemediationTransition.NEWLY_INCORRECT_NO_REMEDIATION)
        if before_state == "missing" and after_state == "scored":
            transitions.append(RemediationTransition.NEWLY_SUBMITTED)
        if before_state == "scored" and after_state == "missing":
            transitions.append(RemediationTransition.NEWLY_MISSING)

        if not transitions:
            continue

        regressed = any(
            transition
            in {
                RemediationTransition.NEWLY_INCORRECT,
                RemediationTransition.NEWLY_UNSAFE,
                RemediationTransition.NEWLY_INCORRECT_NO_REMEDIATION,
                RemediationTransition.NEWLY_MISSING,
            }
            for transition in transitions
        )
        records.append(
            RemediationRegressionRecord(
                id=f"{rule_id}|{entity_id}",
                entity_id=entity_id,
                rule_id=rule_id,
                baseline_state=before_state,
                candidate_state=after_state,
                baseline_fully_correct=_as_bool(before_correct),
                candidate_fully_correct=_as_bool(after_correct),
                baseline_unsafe=_as_bool(before_unsafe),
                candidate_unsafe=_as_bool(after_unsafe),
                baseline_no_remediation_correct=_as_bool(before_none),
                candidate_no_remediation_correct=_as_bool(after_none),
                transitions=sorted(transitions, key=lambda item: item.value),
                regression=regressed,
            )
        )
    return records


def _as_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


def _breakdown_deltas(
    baseline: dict[str, Any], candidate: dict[str, Any], *, keys: list[str] | None = None
) -> dict[str, Any]:
    """Compare a ``{group: block}`` breakdown, keeping groups from either side."""
    names = sorted(set(baseline) | set(candidate)) if keys is None else keys
    return {
        name: metric_block_delta(baseline.get(name), candidate.get(name), metrics=COMPARED_METRICS)
        for name in names
    }


def _difficulty_deltas(baseline: EvaluationRun, candidate: EvaluationRun) -> dict[str, Any]:
    """Compare each difficulty tier independently.

    Tiers are taken from the runs themselves — the union of what each published
    — so a tier absent from both is never fabricated, and a tier present in only
    one (which compatibility should already have prevented) reports undefined
    deltas rather than a manufactured zero.
    """
    left = baseline.summary["findings"].get("by_difficulty", {})
    right = candidate.summary["findings"].get("by_difficulty", {})
    return _breakdown_deltas(left, right)


def _adversarial_deltas(baseline: EvaluationRun, candidate: EvaluationRun) -> dict[str, Any]:
    """Compare the adversarial tier, aggregate-only and honest about that.

    The evaluator publishes adversarial results as aggregate blocks and per
    case type; it does not tag individual pairs with scenario membership. So the
    net movement of the adversarial confusion matrix is reported, along with the
    near-miss control false positives that are the tier's whole point — and the
    absence of per-case attribution is stated in the payload rather than papered
    over.
    """
    left = baseline.summary["adversarial"]
    right = candidate.summary["adversarial"]
    left_near = left.get("near_miss_controls", {})
    right_near = right.get("near_miss_controls", {})
    left_rem = left.get("remediation", {})
    right_rem = right.get("remediation", {})

    declared = int(right.get("scenarios", 0) or 0)
    return {
        "declared_scenarios": declared,
        "scenario_pairs": int(right.get("scenario_pairs", 0) or 0),
        "per_case_attribution_available": False,
        "attribution_note": (
            "The evaluator does not tag individual pairs with scenario membership, "
            "so adversarial movement is reported as aggregate net change and by "
            "case type. Per-case attribution would require reading the privileged "
            "scenario answer key, which this layer deliberately never opens."
        ),
        "confusion_matrix": metric_block_delta(left, right, metrics=COMPARED_METRICS),
        "net_newly_solved": success_count_delta(
            "adversarial_true_positives",
            int(left.get("counts", {}).get("tp", 0) or 0),
            int(right.get("counts", {}).get("tp", 0) or 0),
        ),
        "net_missed": error_count_delta(
            "adversarial_false_negatives",
            int(left.get("counts", {}).get("fn", 0) or 0),
            int(right.get("counts", {}).get("fn", 0) or 0),
        ),
        "near_miss_controls": {
            "declared": int(right_near.get("declared", 0) or 0),
            "false_positives": error_count_delta(
                "near_miss_false_positives",
                int(left_near.get("false_positives", 0) or 0),
                int(right_near.get("false_positives", 0) or 0),
            ),
            "false_positive_rate": metric_delta(
                "false_positive_rate",
                left_near.get("false_positive_rate"),
                right_near.get("false_positive_rate"),
            ),
            "unsafe_remediations": error_count_delta(
                "near_miss_unsafe_remediations",
                int(left_near.get("unsafe_remediations", 0) or 0),
                int(right_near.get("unsafe_remediations", 0) or 0),
            ),
        },
        "remediation": {
            "correct_no_remediation": success_count_delta(
                "correct_no_remediation",
                int(left_rem.get("correct_no_remediation", 0) or 0),
                int(right_rem.get("correct_no_remediation", 0) or 0),
            ),
            "no_remediation_correct": metric_delta(
                "no_remediation_correct",
                left_rem.get("no_remediation_correct"),
                right_rem.get("no_remediation_correct"),
            ),
        },
        "by_case_type": _breakdown_deltas(
            left.get("by_case_type", {}), right.get("by_case_type", {})
        ),
    }


def _dimension_deltas(baseline: EvaluationRun, candidate: EvaluationRun) -> dict[str, Any]:
    """Compare the evaluator's five headline dimensions, unweighted as emitted."""
    left = baseline.summary["dimensions"]
    right = candidate.summary["dimensions"]
    deltas: dict[str, Any] = {}
    for name in sorted(set(left) | set(right)):
        left_block = left.get(name)
        right_block = right.get(name)
        metric_name = str((right_block or left_block or {}).get("metric", name))
        deltas[name] = metric_delta(metric_name, left_block, right_block)
    return deltas


def _remediation_deltas(baseline: EvaluationRun, candidate: EvaluationRun) -> dict[str, Any]:
    left = baseline.summary["remediation"]
    right = candidate.summary["remediation"]
    left_counts = left.get("counts", {})
    right_counts = right.get("counts", {})
    return {
        "counts": {
            "submitted": success_count_delta(
                "submitted",
                int(left_counts.get("submitted", 0) or 0),
                int(right_counts.get("submitted", 0) or 0),
            ),
            "fully_correct": success_count_delta(
                "fully_correct",
                int(left_counts.get("fully_correct", 0) or 0),
                int(right_counts.get("fully_correct", 0) or 0),
            ),
            "missing": error_count_delta(
                "missing",
                int(left_counts.get("missing", 0) or 0),
                int(right_counts.get("missing", 0) or 0),
            ),
            "unsafe_actions": error_count_delta(
                "unsafe_actions",
                int(left_counts.get("unsafe_actions", 0) or 0),
                int(right_counts.get("unsafe_actions", 0) or 0),
            ),
            "unsafe_on_reserved_control": error_count_delta(
                "unsafe_on_reserved_control",
                int(left_counts.get("unsafe_on_reserved_control", 0) or 0),
                int(right_counts.get("unsafe_on_reserved_control", 0) or 0),
            ),
            "non_remediable_correct": success_count_delta(
                "non_remediable_correct",
                int(left_counts.get("non_remediable_correct", 0) or 0),
                int(right_counts.get("non_remediable_correct", 0) or 0),
            ),
        },
        "metrics": {
            name: metric_delta(
                name,
                left.get("metrics", {}).get(name),
                right.get("metrics", {}).get(name),
            )
            for name in _REMEDIATION_METRICS
        },
    }


def _control_totals(
    baseline: EvaluationRun,
    candidate: EvaluationRun,
    control_regressions: list[ControlRegressionRecord],
) -> dict[str, Any]:
    """The control-preservation headline, reported as its own block.

    Both the *stock* (how many false positives each run had) and the *flow* (how
    many appeared and how many were resolved) are given: a candidate can hold
    its total steady while moving every false positive to a different control,
    and the totals alone would call that "no change".
    """
    left_reserved = int(baseline.summary["reserved_controls"].get("false_positives", 0) or 0)
    right_reserved = int(candidate.summary["reserved_controls"].get("false_positives", 0) or 0)
    left_fp = int(baseline.summary["findings"]["overall_micro"]["counts"].get("fp", 0) or 0)
    right_fp = int(candidate.summary["findings"]["overall_micro"]["counts"].get("fp", 0) or 0)

    new_total = sum(1 for record in control_regressions if record.regression)
    resolved_total = sum(1 for record in control_regressions if not record.regression)
    new_reserved = sum(
        1 for record in control_regressions if record.regression and record.reserved_control
    )
    resolved_reserved = sum(
        1 for record in control_regressions if not record.regression and record.reserved_control
    )

    return {
        "false_positives": error_count_delta("false_positives", left_fp, right_fp),
        "reserved_control_false_positives": error_count_delta(
            "reserved_control_false_positives", left_reserved, right_reserved
        ),
        "specificity": metric_delta(
            "specificity",
            baseline.summary["findings"]["overall_micro"]["metrics"].get("specificity"),
            candidate.summary["findings"]["overall_micro"]["metrics"].get("specificity"),
        ),
        "reserved_control_specificity": metric_delta(
            "specificity",
            baseline.summary["reserved_controls"]["metrics"].get("specificity"),
            candidate.summary["reserved_controls"]["metrics"].get("specificity"),
        ),
        "new_control_false_positives": new_total,
        "resolved_control_false_positives": resolved_total,
        "new_reserved_control_false_positives": new_reserved,
        "resolved_reserved_control_false_positives": resolved_reserved,
        "unsafe_remediations_on_new_control_false_positives": sum(
            1 for record in control_regressions if record.regression and record.unsafe_remediation
        ),
    }


def compare_runs(baseline: EvaluationRun, candidate: EvaluationRun) -> ComparisonResult:
    """Compare two emitted evaluation runs; raise if they are not comparable."""
    identity = check_compatible(baseline, candidate)

    transitions = _pair_transitions(baseline, candidate)
    control_regressions = _control_regressions(transitions, candidate)
    rule_regressions = _rule_regressions(baseline, candidate, transitions)
    remediation_regressions = _remediation_regressions(baseline, candidate)

    overall = metric_block_delta(
        baseline.summary["findings"]["overall_micro"],
        candidate.summary["findings"]["overall_micro"],
        metrics=COMPARED_METRICS,
    )
    dimensions = _dimension_deltas(baseline, candidate)
    difficulty = _difficulty_deltas(baseline, candidate)
    adversarial = _adversarial_deltas(baseline, candidate)
    remediation = _remediation_deltas(baseline, candidate)
    controls = _control_totals(baseline, candidate, control_regressions)

    metric_deltas = {
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        "comparator_version": COMPARATOR_VERSION,
        "overall_micro": overall,
        "overall_macro_by_rule": {
            name: metric_delta(
                name,
                baseline.summary["findings"]["overall_macro_by_rule"].get(name),
                candidate.summary["findings"]["overall_macro_by_rule"].get(name),
            )
            for name in COMPARED_METRICS
        },
        "dimensions": dimensions,
        "by_difficulty": difficulty,
        "by_category": _breakdown_deltas(
            baseline.summary["findings"].get("by_category", {}),
            candidate.summary["findings"].get("by_category", {}),
        ),
        "by_entity_class": _breakdown_deltas(
            baseline.summary["findings"].get("by_entity_class", {}),
            candidate.summary["findings"].get("by_entity_class", {}),
        ),
        "by_severity": _breakdown_deltas(
            baseline.summary["findings"].get("by_severity", {}),
            candidate.summary["findings"].get("by_severity", {}),
        ),
        "control_preservation": controls,
        "remediation": remediation,
        "adversarial": adversarial,
        "out_of_scope": {
            "false_positives": error_count_delta(
                "out_of_scope_false_positives",
                int(baseline.summary["out_of_scope"].get("false_positives", 0) or 0),
                int(candidate.summary["out_of_scope"].get("false_positives", 0) or 0),
            ),
            "strict_false_positives": error_count_delta(
                "strict_false_positives",
                int(baseline.summary["out_of_scope"].get("strict_false_positives", 0) or 0),
                int(candidate.summary["out_of_scope"].get("strict_false_positives", 0) or 0),
            ),
        },
        "abstention": {
            "abstention_rate": metric_delta(
                "abstention_rate",
                baseline.summary["abstention"].get("abstention_rate"),
                candidate.summary["abstention"].get("abstention_rate"),
            ),
        },
    }

    regressed_rules = [record for record in rule_regressions if record.regression_impact]
    improved_rules = [
        record
        for record in rule_regressions
        if record.improvement_impact and not record.regression_impact
    ]

    summary = {
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        "comparator_version": COMPARATOR_VERSION,
        "benchmark": identity,
        "runs": {
            "baseline": {
                "prediction_sha256": baseline.prediction_sha256,
                "predictions": baseline.summary["submission"].get("predictions", 0),
            },
            "candidate": {
                "prediction_sha256": candidate.prediction_sha256,
                "predictions": candidate.summary["submission"].get("predictions", 0),
            },
            "identical_submission": baseline.prediction_sha256 == candidate.prediction_sha256,
        },
        "headline": {
            "dimensions": summarize_directions(list(dimensions.values())),
            "pairs_changed": len(transitions),
            "newly_solved": sum(
                1 for t in transitions if t.transition is PairTransition.NEWLY_SOLVED
            ),
            "newly_broken": sum(
                1 for t in transitions if t.transition is PairTransition.NEWLY_BROKEN
            ),
            "new_control_false_positives": controls["new_control_false_positives"],
            "resolved_control_false_positives": controls["resolved_control_false_positives"],
            "new_reserved_control_false_positives": controls[
                "new_reserved_control_false_positives"
            ],
            "rules_regressed": len(regressed_rules),
            "rules_improved": len(improved_rules),
            "remediations_changed": len(remediation_regressions),
            "remediations_regressed": sum(
                1 for record in remediation_regressions if record.regression
            ),
        },
        "overall_micro": overall,
        "dimensions": dimensions,
        "control_preservation": controls,
        "by_difficulty": difficulty,
        "adversarial": adversarial,
        "remediation": remediation,
        "ranked_regressions": [
            {
                "rank": record.rank,
                "rule_id": record.rule_id,
                "status": record.status.value,
                "regression_impact": record.regression_impact,
                "newly_broken": record.newly_broken,
                "new_false_positives": record.new_false_positives,
                "new_reserved_control_false_positives": (
                    record.new_reserved_control_false_positives
                ),
            }
            for record in regressed_rules
        ],
        "verdict_is_advisory": True,
        "verdict_note": (
            "This report states what changed. It applies no threshold and returns no "
            "pass/fail verdict — a regression does not fail the command."
        ),
        "synthetic": True,
    }

    return ComparisonResult(
        summary=summary,
        metric_deltas=metric_deltas,
        pair_transitions=transitions,
        rule_regressions=rule_regressions,
        control_regressions=control_regressions,
        remediation_regressions=remediation_regressions,
    )


def has_regressions(result: ComparisonResult) -> bool:
    """Whether anything got worse. Reported, never used to set an exit code."""
    headline = result.summary["headline"]
    return bool(
        headline["newly_broken"]
        or headline["new_control_false_positives"]
        or headline["remediations_regressed"]
        or result.summary["dimensions"]
        and any(delta["direction"] == REGRESSED for delta in result.summary["dimensions"].values())
    )


__all__ = [
    "COMPARATOR_VERSION",
    "COMPARISON_SCHEMA_VERSION",
    "COMPARED_METRICS",
    "ComparisonResult",
    "compare_runs",
    "has_regressions",
]
