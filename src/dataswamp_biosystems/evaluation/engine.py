"""The deterministic evaluation engine: predictions in, evidence out.

The evaluation universe
-----------------------

Scoring is **pair-level** on ``(entity_id, rule_id)``, and the pairs come from
``rule-scope.jsonl`` — never from a cross-product. For each rule:

* its **population** is ``eligible_ids ∪ control_excluded_ids``;
* its **positives** are ``selected_ids`` (equivalently, its expected findings);
* its **negatives** are the rest of the population — entities that were exposed
  to the rule and not drawn (``eligible-unselected``) plus the reserved controls
  the profile held out before selection (``control_excluded_ids``).

An entity that was never in a rule's population is not a negative for that rule.
Pairing every rule with every entity would manufacture tens of thousands of free
true negatives and inflate specificity towards 1.0 for any agent, which is why
the population is read per rule rather than assumed.

A prediction naming a *known* entity that is outside the named rule's population
is neither a false positive within the matrix nor a quietly discarded record: it
is reported as ``out_of_scope_false_positive`` (see
:class:`~dataswamp_biosystems.evaluation.entities.Outcome`), counted in a strict
false-positive total, and excluded from every denominator.

Matching
--------

Exact and structural: a prediction scores against the pair named by its
``entity_id`` and ``rule_id``. Category and severity correctness are reported as
attributes of a matched pair and never used to rescue an unmatched one. No prose
is compared, and no fuzzy or semantic matching exists in this milestone.

Predictions that name no rule cannot occupy a pair — binding them to one would
be a guess. They are instead scored in two coarser universes that are
well-defined without a rule id: an ``(entity_id, category)`` universe and an
``entity_id`` universe, each with its own population and positives derived the
same way from ``rule-scope.jsonl``. That is where an agent which finds a real
problem without naming the rule earns credit, and the report says exactly which
universe the credit came from.

Abstention
----------

``abstain`` is a decision and is recorded as one: on a positive pair it is a
false negative (the defect went unreported), on a negative pair a true negative
(nothing was wrongly flagged), and in both cases the pair is flagged
``abstained`` and counted separately. A *selective* metric block, computed with
abstained pairs removed entirely, shows what the agent achieves on the pairs it
was willing to decide. Silence — no prediction at all — is not abstention and is
counted as neither.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from dataswamp_biosystems.evaluation.entities import (
    FindingResult,
    GroupMetricRecord,
    Outcome,
    RemediationResult,
    RemediationState,
)
from dataswamp_biosystems.evaluation.ground_truth import GroundTruth
from dataswamp_biosystems.evaluation.metrics import (
    Counts,
    breakdown,
    macro_block,
    metric_block,
    ratio,
    total_counts,
)
from dataswamp_biosystems.evaluation.predictions import (
    PREDICTION_SCHEMA_VERSION,
    STATUS_ABSTAIN,
    STATUS_CLEAN,
    STATUS_FINDING,
    Prediction,
)
from dataswamp_biosystems.observed.difficulty import (
    DIFFICULTY_ORDER,
    Difficulty,
    UnknownRuleDifficultyError,
    difficulty_for,
)
from dataswamp_biosystems.observed.entities import (
    NO_REMEDIATION_ACTION,
    ApprovalPolicy,
    ExpectedRemediation,
    RemediationAvailability,
)
from dataswamp_biosystems.truth import serialize

EVALUATOR_VERSION = "0.1.0"
# 2 — added the ``by_difficulty`` aggregation and ``difficulty-metrics.jsonl``.
# Nothing that existed at schema 1 changed shape or meaning.
EVALUATION_SCHEMA_VERSION = 2

STATUS_ABSENT = "absent"

#: The tier bucket for a scored rule the difficulty model does not classify.
#: Should never appear — ``validate_registry`` rejects an unclassified rule long
#: before generation — so it is a defensive state, reported rather than hidden,
#: and asserted empty by ``tests/evaluation/test_difficulty.py``.
UNKNOWN_DIFFICULTY = "unknown"

#: The tier buckets always present in a report, in tier order. Emitting a tier
#: with no pairs (as ``null`` metrics over zero denominators) keeps the report
#: shape stable across mixed, tier-restricted and adversarial runs; a reader can
#: then compare two reports without first checking which keys exist.
#: ``adversarial`` is included for exactly that reason: "this benchmark had no
#: adversarial cases" and "the agent handled them all" must not look alike.
REPORTED_DIFFICULTIES: tuple[str, ...] = tuple(tier.value for tier in DIFFICULTY_ORDER)


def _difficulty_of(rule_id: str) -> str:
    """Return ``rule_id``'s tier, or :data:`UNKNOWN_DIFFICULTY` if unclassified."""
    try:
        return difficulty_for(rule_id).value
    except UnknownRuleDifficultyError:
        return UNKNOWN_DIFFICULTY


def _pair_id(entity_id: str, rule_id: str) -> str:
    return f"{rule_id}|{entity_id}"


def _aggregate_status(statuses: list[str]) -> str:
    """Collapse several predictions about one coarser key into a single claim.

    A single ``finding`` claim dominates — an agent that flags an entity for any
    reason has flagged it. Otherwise an explicit ``clean`` beats an ``abstain``,
    and silence remains silence.
    """
    if STATUS_FINDING in statuses:
        return STATUS_FINDING
    if STATUS_CLEAN in statuses:
        return STATUS_CLEAN
    if STATUS_ABSTAIN in statuses:
        return STATUS_ABSTAIN
    return STATUS_ABSENT


def _outcome(expected_present: bool, predicted_status: str) -> Outcome:
    """Map (expected, predicted) to a confusion-matrix cell.

    ``abstain`` and ``absent`` are both non-claims and so land on the same side
    of the matrix; they are distinguished on the record, not in the cell.
    """
    predicted_finding = predicted_status == STATUS_FINDING
    if expected_present:
        return Outcome.TP if predicted_finding else Outcome.FN
    return Outcome.FP if predicted_finding else Outcome.TN


_CELL = {Outcome.TP: "tp", Outcome.FP: "fp", Outcome.FN: "fn", Outcome.TN: "tn"}


def _add(counts: dict[str, Counts], key: str, outcome: Outcome) -> None:
    cell = _CELL.get(outcome)
    if cell is None:
        return
    current = counts.get(key, Counts())
    counts[key] = current + Counts(**{cell: 1})


@dataclass
class EvaluationResult:
    """Everything one evaluation produced: records, tables and the summary."""

    summary: dict[str, Any]
    finding_results: list[FindingResult] = field(default_factory=list)
    remediation_results: list[RemediationResult] = field(default_factory=list)
    rule_metrics: list[GroupMetricRecord] = field(default_factory=list)
    category_metrics: list[GroupMetricRecord] = field(default_factory=list)
    difficulty_metrics: list[GroupMetricRecord] = field(default_factory=list)
    #: One row per adversarial scenario case type. Empty for a benchmark that
    #: declares no scenarios, so an ordinary evaluation emits no extra file.
    scenario_metrics: list[GroupMetricRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Coarser universes for predictions that name no rule.
# ---------------------------------------------------------------------------


def _coarse_block(
    populations: dict[str, set[str]],
    positives: dict[str, set[str]],
    predicted: dict[str, str],
) -> dict[str, Any]:
    """Score a universe whose keys are coarser than a pair.

    ``populations`` maps a key to the entities in scope for it, ``positives`` the
    entities that actually carry a defect there, and ``predicted`` the collapsed
    claim per ``key::entity``. Same rules as the pair universe: only members of a
    population are scored, so nothing outside it can inflate a denominator.
    """
    counts = Counts()
    for key, members in populations.items():
        positive_members = positives.get(key, set())
        for entity_id in members:
            status = predicted.get(f"{key}::{entity_id}", STATUS_ABSENT)
            outcome = _outcome(entity_id in positive_members, status)
            cell = _CELL[outcome]
            counts = counts + Counts(**{cell: 1})
    return metric_block(counts)


def _coarse_universes(
    truth: GroundTruth, predictions: list[Prediction]
) -> dict[str, dict[str, Any]]:
    """Return the ``(entity, category)`` and ``entity`` universes' metric blocks."""
    category_population: dict[str, set[str]] = defaultdict(set)
    category_positive: dict[str, set[str]] = defaultdict(set)
    entity_population: set[str] = set()
    entity_positive: set[str] = set()

    for scope in truth.scopes:
        population = truth.population(scope.id)
        category_population[scope.category.value] |= population
        category_positive[scope.category.value] |= set(scope.selected_ids)
        entity_population |= population
        entity_positive |= set(scope.selected_ids)

    # A prediction contributes its rule's category when it names one, its own
    # declared category otherwise; a prediction with neither reaches only the
    # entity universe.
    scope_by_rule = truth.scope_by_rule
    category_claims: dict[str, list[str]] = defaultdict(list)
    entity_claims: dict[str, list[str]] = defaultdict(list)
    for prediction in predictions:
        entity_claims[f"::{prediction.entity_id}"].append(prediction.status)
        category = ""
        if prediction.rule_id and prediction.rule_id in scope_by_rule:
            category = scope_by_rule[prediction.rule_id].category.value
        elif prediction.category is not None:
            category = prediction.category.value
        if category:
            category_claims[f"{category}::{prediction.entity_id}"].append(prediction.status)

    category_predicted = {k: _aggregate_status(v) for k, v in category_claims.items()}
    entity_predicted = {k: _aggregate_status(v) for k, v in entity_claims.items()}

    return {
        "category_level": _coarse_block(
            dict(category_population), dict(category_positive), category_predicted
        ),
        "entity_level": _coarse_block(
            {"": entity_population}, {"": entity_positive}, entity_predicted
        ),
    }


# ---------------------------------------------------------------------------
# Remediation scoring.
# ---------------------------------------------------------------------------


def _score_remediation(
    entity_id: str,
    rule_id: str,
    expected: ExpectedRemediation,
    prediction: Prediction | None,
) -> RemediationResult:
    """Score a submitted remediation against the expected one for a true positive."""
    base = {
        "id": _pair_id(entity_id, rule_id),
        "entity_id": entity_id,
        "rule_id": rule_id,
        "finding_outcome": Outcome.TP,
        "expected_availability": expected.availability.value,
        "expected_approval_policy": expected.approval_policy.value,
        "expected_approver_role": expected.approver_role.value,
        "expected_action_class": expected.action_class,
        "expected_recommended_value": expected.recommended_value,
    }
    non_remediable = expected.availability is RemediationAvailability.NONE

    if prediction is None or prediction.remediation is None:
        # Silence is never a correct answer, not even where nothing can be fixed:
        # the expected result there is an explicit no-remediation *decision*.
        explanation = (
            "no remediation submitted; a non-remediable finding still requires an "
            f"explicit {NO_REMEDIATION_ACTION!r} decision"
            if non_remediable
            else "no remediation submitted for a correctly detected finding"
        )
        return RemediationResult(
            **base,
            state=RemediationState.MISSING,
            no_remediation_correct=False if non_remediable else None,
            explanation=explanation,
        )

    proposed = prediction.remediation
    availability_correct = proposed.availability is expected.availability
    approval_correct = proposed.approval_policy is expected.approval_policy
    action_correct = proposed.action_class == expected.action_class
    # The approver only has to be named where approval is actually required;
    # elsewhere the expected role is "none" and demanding it adds noise.
    approver_applicable = expected.approval_policy is ApprovalPolicy.REQUIRED
    approver_correct = (
        proposed.approver_role is expected.approver_role if approver_applicable else None
    )
    value_applicable = expected.recommended_value is not None
    value_correct = (
        proposed.recommended_value == expected.recommended_value if value_applicable else None
    )
    no_remediation_correct = (
        proposed.is_no_remediation and proposed.availability is RemediationAvailability.NONE
        if non_remediable
        else None
    )

    checks = [availability_correct, approval_correct, action_correct]
    if approver_correct is not None:
        checks.append(approver_correct)
    if value_correct is not None:
        checks.append(value_correct)
    if no_remediation_correct is not None:
        checks.append(no_remediation_correct)
    fully_correct = all(checks)

    wrong = sorted(
        name
        for name, ok in (
            ("availability", availability_correct),
            ("approval_policy", approval_correct),
            ("action_class", action_correct),
            ("approver_role", approver_correct),
            ("recommended_value", value_correct),
        )
        if ok is False
    )
    explanation = (
        "remediation matches the expected decision"
        if fully_correct
        else (f"incorrect: {', '.join(wrong)}")
    )

    return RemediationResult(
        **base,
        state=RemediationState.SCORED,
        predicted_availability=proposed.availability.value,
        predicted_approval_policy=proposed.approval_policy.value,
        predicted_approver_role=proposed.approver_role.value,
        predicted_action_class=proposed.action_class,
        predicted_recommended_value=proposed.recommended_value,
        availability_correct=availability_correct,
        approval_policy_correct=approval_correct,
        approver_role_correct=approver_correct,
        action_class_correct=action_correct,
        recommended_value_correct=value_correct,
        no_remediation_correct=no_remediation_correct,
        fully_correct=fully_correct,
        explanation=explanation,
    )


def _remediation_totals(results: list[RemediationResult]) -> dict[str, Any]:
    """Summarise remediation scoring, keeping each question's denominator visible."""
    scored = [r for r in results if r.state is RemediationState.SCORED]
    missing = [r for r in results if r.state is RemediationState.MISSING]
    unscored = [r for r in results if r.state is RemediationState.UNSCORED_MISSED_FINDING]
    unsafe = [r for r in results if r.state is RemediationState.UNSAFE]
    detected = len(scored) + len(missing)

    def field_ratio(attribute: str) -> dict[str, Any]:
        applicable = [r for r in scored if getattr(r, attribute) is not None]
        return ratio(sum(1 for r in applicable if getattr(r, attribute)), len(applicable))

    # Non-remediable findings are counted twice, deliberately: once over every
    # such finding in the benchmark and once over only those the agent actually
    # detected. Omitting a required no-remediation *decision* must cost the
    # agent something, but failing to detect the finding at all is a detection
    # error and is not re-charged here as a remediation error — the report shows
    # both denominators so the distinction cannot be lost.
    non_remediable = [r for r in results if r.expected_availability == RemediationAvailability.NONE]
    non_remediable_detected = [
        r for r in non_remediable if r.state in (RemediationState.SCORED, RemediationState.MISSING)
    ]
    non_remediable_correct = sum(1 for r in non_remediable_detected if r.no_remediation_correct)

    return {
        "counts": {
            "expected_remediations": len(results) - len(unsafe),
            "detected_findings": detected,
            "submitted": len(scored),
            "missing": len(missing),
            "unscored_missed_finding": len(unscored),
            "fully_correct": sum(1 for r in scored if r.fully_correct),
            "unsafe_actions": len(unsafe),
            "unsafe_on_reserved_control": sum(1 for r in unsafe if r.unsafe_on_reserved_control),
            "non_remediable_expected": len(non_remediable),
            "non_remediable_detected": len(non_remediable_detected),
            "non_remediable_correct": non_remediable_correct,
        },
        "metrics": {
            # Coverage: of the findings the agent actually detected, how many did
            # it also propose a decision for?
            "coverage": ratio(len(scored), detected),
            # Correctness *conditional on* a true positive — the only remediation
            # accuracy figure that is not confounded by detection.
            "correctness_given_true_positive": ratio(
                sum(1 for r in scored if r.fully_correct), len(scored)
            ),
            # End to end: correct finding *and* correct remediation, over every
            # expected finding, so missed findings are not quietly excused.
            "end_to_end": ratio(
                sum(1 for r in scored if r.fully_correct), len(results) - len(unsafe)
            ),
            "availability_correct": field_ratio("availability_correct"),
            "approval_policy_correct": field_ratio("approval_policy_correct"),
            "approver_role_correct": field_ratio("approver_role_correct"),
            "action_class_correct": field_ratio("action_class_correct"),
            "recommended_value_correct": field_ratio("recommended_value_correct"),
            # Conditional on detection …
            "non_remediation_correct": ratio(non_remediable_correct, len(non_remediable_detected)),
            # … and over every non-remediable finding in the benchmark.
            "non_remediation_end_to_end": ratio(non_remediable_correct, len(non_remediable)),
        },
    }


def _rules_per_difficulty(truth: GroundTruth) -> dict[str, int]:
    """Return ``{tier: rule count}`` for the rules this ground truth actually scopes."""
    counts = dict.fromkeys(REPORTED_DIFFICULTIES, 0)
    for scope in truth.scopes:
        tier = _difficulty_of(scope.id)
        counts[tier] = counts.get(tier, 0) + 1
    return dict(sorted(counts.items()))


def _difficulty_blocks(
    by_difficulty: dict[str, Counts],
    by_difficulty_reserved: dict[str, Counts],
    remediation_results: list[RemediationResult],
) -> dict[str, dict[str, Any]]:
    """Return the per-tier report: one block per benchmark difficulty tier.

    Each block is the same shape as the overall report — confusion matrix,
    metrics, reserved-control behaviour, remediation — restricted to the pairs
    whose rule sits at that tier. The restriction is a *partition*: no pair is
    counted twice and none is dropped, so the tier counts sum to the overall
    matrix. Counts are summed before dividing, exactly as everywhere else; a
    tier with no pairs reports ``null`` metrics over zero denominators rather
    than a zero that would look like a measured failure.
    """
    tiers = list(REPORTED_DIFFICULTIES)
    # The defensive bucket is reported only when something actually landed in it,
    # so its presence in a report is itself the signal.
    tiers.extend(sorted(set(by_difficulty) - set(tiers)))

    remediation_by_tier: dict[str, list[RemediationResult]] = {tier: [] for tier in tiers}
    for result in remediation_results:
        remediation_by_tier.setdefault(_difficulty_of(result.rule_id), []).append(result)

    blocks: dict[str, dict[str, Any]] = {}
    for tier in tiers:
        counts = by_difficulty.get(tier, Counts())
        reserved = by_difficulty_reserved.get(tier, Counts())
        remediation = _remediation_totals(remediation_by_tier.get(tier, []))
        blocks[tier] = {
            **metric_block(counts),
            "reserved_controls": {
                **metric_block(reserved),
                "false_positives": reserved.fp,
                "false_positive_rate": ratio(reserved.fp, reserved.negatives),
            },
            "remediation": {
                "coverage": remediation["metrics"]["coverage"],
                "correctness_given_true_positive": remediation["metrics"][
                    "correctness_given_true_positive"
                ],
                "end_to_end": remediation["metrics"]["end_to_end"],
                "unsafe_actions": remediation["counts"]["unsafe_actions"],
                "unsafe_on_reserved_control": remediation["counts"]["unsafe_on_reserved_control"],
            },
        }
    return blocks


def _scenario_block(
    truth: GroundTruth,
    by_case_type: dict[str, Counts],
    near_miss: Counts,
    remediation_results: list[RemediationResult],
    *,
    wrong_entity: int,
    wrong_rule: int,
    correct_abstentions: int,
) -> dict[str, Any]:
    """Report the adversarial tier by scenario case type, and by how it was failed.

    This is *reporting*, not a second scoring engine: every count here is a
    regrouping of pairs the one engine already scored, so the case-type counts
    sum to the adversarial tier's matrix and nothing is rescored under different
    rules.

    Only pairs that belong to a declared scenario are counted. That is the whole
    denominator discipline of this block: the adversarial universe is the
    constructed neighbourhood, and admitting the rest of the estate would bury a
    dozen hard decisions under thousands of free true negatives.
    """
    scenario_pairs = set(truth.case_type_by_pair)
    near_miss_ids = truth.near_miss_entity_ids
    no_remediation_pairs = truth.no_remediation_pairs

    in_scenario = [
        result
        for result in remediation_results
        if (result.entity_id, result.rule_id) in scenario_pairs
    ]
    unsafe_on_near_miss = sum(
        1
        for result in in_scenario
        if result.state is RemediationState.UNSAFE and result.entity_id in near_miss_ids
    )
    no_remediation_scored = [
        result
        for result in in_scenario
        if (result.entity_id, result.rule_id) in no_remediation_pairs
        and result.state in (RemediationState.SCORED, RemediationState.MISSING)
    ]
    no_remediation_correct = sum(1 for r in no_remediation_scored if r.no_remediation_correct)

    overall = total_counts(by_case_type.values())
    positives = sum(1 for pair in truth.scenario_positive_pairs if pair in truth.case_type_by_pair)

    # A near miss is only an in-matrix negative if its entity is in the mimicked
    # rule's *truth-derived* population. Some are not — a control dressed to look
    # restricted was not restricted in truth, so the rule could never have drawn
    # it. Flagging one is still counted, as an out-of-scope false positive, but it
    # cannot enter a specificity denominator without inventing a population.
    # Reported rather than quietly dropped: an unscored near miss is a limit on
    # what this benchmark measured, and hiding it would overstate the coverage.
    declared_near_misses = len(near_miss_ids)
    scored_near_misses = len(
        {
            entity_id
            for entity_id, rule_id in scenario_pairs
            if entity_id in near_miss_ids and entity_id in truth.population(rule_id)
        }
    )
    case_blocks = {
        case_type: {
            **metric_block(counts),
            "counts": counts.as_dict(),
        }
        for case_type, counts in sorted(by_case_type.items())
    }
    remediation = _remediation_totals(in_scenario)
    return {
        "scenarios": len(truth.scenarios),
        "scenario_pairs": overall.total,
        "positive_support": positives,
        "near_miss_negative_support": near_miss.negatives,
        "confusion_matrix": overall.as_dict(),
        **metric_block(overall),
        "by_case_type": case_blocks,
        "near_miss_controls": {
            **metric_block(near_miss),
            "declared": declared_near_misses,
            "scored_in_matrix": scored_near_misses,
            "unscored_outside_rule_population": declared_near_misses - scored_near_misses,
            "false_positives": near_miss.fp,
            # The headline adversarial number: how often the agent was fooled by
            # a lookalike it was supposed to leave alone.
            "false_positive_rate": ratio(near_miss.fp, near_miss.negatives),
            "unsafe_remediations": unsafe_on_near_miss,
        },
        "attribution": {
            # A single false positive can be both — right rule on the wrong
            # entity *and* right entity under the wrong rule — so these are two
            # lenses on the same pairs, never a partition to be summed.
            "wrong_entity_predictions": wrong_entity,
            "wrong_rule_predictions": wrong_rule,
        },
        "abstention": {"correct_abstentions": correct_abstentions},
        "remediation": {
            "coverage": remediation["metrics"]["coverage"],
            "correctness_given_true_positive": remediation["metrics"][
                "correctness_given_true_positive"
            ],
            "end_to_end": remediation["metrics"]["end_to_end"],
            "unsafe_actions": remediation["counts"]["unsafe_actions"],
            "correct_no_remediation": no_remediation_correct,
            "no_remediation_expected": len(no_remediation_pairs),
            "no_remediation_correct": ratio(no_remediation_correct, len(no_remediation_scored)),
        },
    }


# ---------------------------------------------------------------------------
# The evaluation itself.
# ---------------------------------------------------------------------------


def evaluate(
    truth: GroundTruth,
    predictions: list[Prediction],
    *,
    prediction_digest: str,
) -> EvaluationResult:
    """Score ``predictions`` against ``truth`` and return every report artefact."""
    scope_by_rule = truth.scope_by_rule
    finding_by_pair = truth.finding_by_pair
    remediation_by_finding = truth.remediation_by_finding

    by_pair: dict[tuple[str, str], Prediction] = {p.pair_key: p for p in predictions if p.rule_id}
    unnamed_rule = [p for p in predictions if not p.rule_id]

    finding_results: list[FindingResult] = []
    remediation_results: list[RemediationResult] = []

    by_rule: dict[str, Counts] = {}
    by_category: dict[str, Counts] = {}
    by_severity: dict[str, Counts] = {}
    by_entity_kind: dict[str, Counts] = {}
    by_entity_class: dict[str, Counts] = {}
    by_control_partition: dict[str, Counts] = {}
    by_difficulty: dict[str, Counts] = {}
    by_difficulty_reserved: dict[str, Counts] = {}
    by_case_type: dict[str, Counts] = {}
    selective = Counts()

    # Adversarial indexes, read once. An ordinary benchmark leaves them empty and
    # every branch below collapses to the pre-existing behaviour.
    case_type_by_pair = truth.case_type_by_pair
    near_miss_ids = truth.near_miss_entity_ids
    scenario_positives = truth.scenario_positive_pairs
    scenario_positive_rules = {rule_id for _, rule_id in scenario_positives}
    scenario_positive_entities = {entity_id for entity_id, _ in scenario_positives}
    near_miss_counts = Counts()
    wrong_entity = 0
    wrong_rule = 0
    correct_abstentions = 0

    abstained_positive = 0
    abstained_negative = 0
    explicit_clean_true_negatives = 0
    scored_pairs = 0

    for scope in truth.scopes:
        rule_id = scope.id
        selected = set(scope.selected_ids)
        category = scope.category.value
        severity = scope.severity.value
        # Derived from the rule registry, never read from ground truth: the
        # emitted observed state carries no difficulty field, and duplicating one
        # there would let a stale ledger disagree with the live classification.
        rule_tier = _difficulty_of(rule_id)
        for entity_id in sorted(truth.population(rule_id)):
            expected_present = entity_id in selected
            prediction = by_pair.get((entity_id, rule_id))
            status = prediction.status if prediction is not None else STATUS_ABSENT
            outcome = _outcome(expected_present, status)
            reserved = truth.is_reserved(entity_id)
            entity_kind = truth.entity_kind(entity_id)
            entity_class = truth.entity_class(entity_id)
            abstained = status == STATUS_ABSTAIN
            scored_pairs += 1

            # A pair that belongs to a constructed case is adversarial *because
            # of the construction*, whatever tier its rule sits at on its own.
            # That is the whole claim of the tier, and it is applied here rather
            # than by relabelling the rule, so the rule keeps its honest tier
            # everywhere else.
            case_type = case_type_by_pair.get((entity_id, rule_id))
            tier = Difficulty.ADVERSARIAL.value if case_type is not None else rule_tier

            _add(by_rule, rule_id, outcome)
            _add(by_category, category, outcome)
            _add(by_severity, severity, outcome)
            _add(by_entity_kind, entity_kind, outcome)
            _add(by_entity_class, entity_class, outcome)
            _add(by_control_partition, "reserved" if reserved else "non-reserved", outcome)
            # Every scored pair lands in exactly one tier, so the tier counts
            # partition the matrix rather than resampling it.
            _add(by_difficulty, tier, outcome)
            if reserved:
                _add(by_difficulty_reserved, tier, outcome)
            if case_type is not None:
                _add(by_case_type, case_type, outcome)
                if entity_id in near_miss_ids:
                    cell = _CELL.get(outcome)
                    if cell is not None:
                        near_miss_counts = near_miss_counts + Counts(**{cell: 1})
                if abstained and not expected_present:
                    correct_abstentions += 1
            # Attribution is deliberately *not* gated on the pair being a declared
            # scenario pair. Flagging the right entity under a rule no case
            # declares is exactly a wrong-rule attribution, and it would go
            # uncounted if only declared pairs were inspected. These counters sit
            # outside the confusion matrix, so widening what they look at cannot
            # move a denominator.
            if outcome is Outcome.FP and scenario_positives:
                # Right rule, wrong subject: the agent located the problem class
                # but attributed it to a lookalike.
                if rule_id in scenario_positive_rules:
                    wrong_entity += 1
                # Right subject, wrong problem: the entity really is defective,
                # but under a different rule.
                if entity_id in scenario_positive_entities:
                    wrong_rule += 1
            if abstained:
                if expected_present:
                    abstained_positive += 1
                else:
                    abstained_negative += 1
            else:
                selective = selective + Counts(**{_CELL[outcome]: 1})
            if outcome is Outcome.TN and status == STATUS_CLEAN:
                explicit_clean_true_negatives += 1

            expected_finding = finding_by_pair.get((entity_id, rule_id))
            category_correct: bool | None = None
            severity_correct: bool | None = None
            if outcome is Outcome.TP and prediction is not None and expected_finding is not None:
                category_correct = (
                    prediction.category is not None
                    and prediction.category.value == expected_finding.category.value
                )
                severity_correct = (
                    prediction.severity is not None
                    and prediction.severity.value == expected_finding.severity.value
                )

            # Emitting a record for every in-scope pair would mean thousands of
            # rows describing silence. Only pairs that carry information are
            # emitted: anything expected, anything predicted, anything wrong.
            if expected_present or prediction is not None:
                finding_results.append(
                    FindingResult(
                        id=_pair_id(entity_id, rule_id),
                        entity_id=entity_id,
                        rule_id=rule_id,
                        category=category,
                        severity=severity,
                        entity_kind=entity_kind,
                        entity_class=entity_class,
                        expected_status="present" if expected_present else "clean",
                        predicted_status=status,
                        outcome=outcome,
                        in_scope=True,
                        reserved_control=reserved,
                        abstained=abstained,
                        prediction_id=prediction.prediction_id if prediction else "",
                        confidence=prediction.confidence if prediction else None,
                        category_correct=category_correct,
                        severity_correct=severity_correct,
                    )
                )

            if expected_finding is not None:
                expected_remediation = remediation_by_finding.get(expected_finding.id)
                if expected_remediation is None:  # pragma: no cover - ledger invariant
                    continue
                if outcome is Outcome.TP:
                    remediation_results.append(
                        _score_remediation(entity_id, rule_id, expected_remediation, prediction)
                    )
                else:
                    remediation_results.append(
                        RemediationResult(
                            id=_pair_id(entity_id, rule_id),
                            entity_id=entity_id,
                            rule_id=rule_id,
                            finding_outcome=outcome,
                            state=RemediationState.UNSCORED_MISSED_FINDING,
                            expected_availability=expected_remediation.availability.value,
                            expected_approval_policy=expected_remediation.approval_policy.value,
                            expected_approver_role=expected_remediation.approver_role.value,
                            expected_action_class=expected_remediation.action_class,
                            expected_recommended_value=expected_remediation.recommended_value,
                            explanation=(
                                "finding was not detected, so its remediation is reported "
                                "as unscored rather than counted as a remediation error"
                            ),
                        )
                    )
            elif outcome is Outcome.FP and prediction is not None:
                unsafe = _unsafe_result(prediction, entity_id, rule_id, outcome, reserved)
                if unsafe is not None:
                    remediation_results.append(unsafe)

    # -- predictions naming a pair outside the rule's population ---------------

    out_of_scope_false_positives = 0
    out_of_scope_clean = 0
    for prediction in sorted(predictions, key=lambda p: (p.rule_id, p.entity_id)):
        if not prediction.rule_id:
            continue
        out_of_scope_rule = scope_by_rule.get(prediction.rule_id)
        if out_of_scope_rule is None:  # pragma: no cover - rejected during validation
            continue
        if prediction.entity_id in truth.population(prediction.rule_id):
            continue
        claims = prediction.claims_finding
        outcome = Outcome.OUT_OF_SCOPE_FALSE_POSITIVE if claims else Outcome.OUT_OF_SCOPE_CLEAN
        if claims:
            out_of_scope_false_positives += 1
        else:
            out_of_scope_clean += 1
        reserved = truth.is_reserved(prediction.entity_id)
        finding_results.append(
            FindingResult(
                id=_pair_id(prediction.entity_id, prediction.rule_id),
                entity_id=prediction.entity_id,
                rule_id=prediction.rule_id,
                category=out_of_scope_rule.category.value,
                severity=out_of_scope_rule.severity.value,
                entity_kind=truth.entity_kind(prediction.entity_id),
                entity_class=truth.entity_class(prediction.entity_id),
                expected_status="out-of-scope",
                predicted_status=prediction.status,
                outcome=outcome,
                in_scope=False,
                reserved_control=reserved,
                abstained=prediction.abstains,
                prediction_id=prediction.prediction_id,
                confidence=prediction.confidence,
            )
        )
        if claims:
            unsafe = _unsafe_result(
                prediction, prediction.entity_id, prediction.rule_id, outcome, reserved
            )
            if unsafe is not None:
                remediation_results.append(unsafe)

    # -- aggregation -----------------------------------------------------------

    overall = total_counts(by_rule.values())
    micro = metric_block(overall)
    macro_rule = macro_block(by_rule)
    reserved_counts = by_control_partition.get("reserved", Counts())

    difficulty_blocks = _difficulty_blocks(
        by_difficulty, by_difficulty_reserved, remediation_results
    )
    scenario_block = _scenario_block(
        truth,
        by_case_type,
        near_miss_counts,
        remediation_results,
        wrong_entity=wrong_entity,
        wrong_rule=wrong_rule,
        correct_abstentions=correct_abstentions,
    )

    abstention_total = abstained_positive + abstained_negative
    decided = sum(1 for p in predictions if not p.abstains)

    summary: dict[str, Any] = {
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "benchmark": {
            "profile": truth.meta.get("profile", ""),
            "defect_seed": truth.meta.get("defect_seed"),
            "truth_seed": truth.meta.get("truth_seed"),
            "observed_generator_version": truth.meta.get("generator_version", ""),
            "observed_schema_version": truth.meta.get("schema_version"),
            "ground_truth_fingerprint": truth.fingerprint,
        },
        "submission": {
            "prediction_sha256": prediction_digest,
            "predictions": len(predictions),
            "rule_level_predictions": len(by_pair),
            "unnamed_rule_predictions": len(unnamed_rule),
            "decided": decided,
            "abstentions": len(predictions) - decided,
        },
        "universe": {
            "rules": len(truth.scopes),
            "evaluated_pairs": scored_pairs,
            "positive_pairs": overall.positives,
            "negative_pairs": overall.negatives,
            "reserved_control_pairs": reserved_counts.total,
            "emitted_finding_results": len(finding_results),
            "explicit_clean_true_negatives": explicit_clean_true_negatives,
            # How many *rules* each tier contributed to this scenario. A
            # tier-restricted benchmark shows zeroes for the tiers it excluded,
            # which is how a reader tells "not attempted" from "attempted badly".
            "rules_by_difficulty": _rules_per_difficulty(truth),
        },
        "findings": {
            "overall_micro": micro,
            "overall_macro_by_rule": macro_rule,
            "confusion_matrix": overall.as_dict(),
            "by_rule": breakdown(by_rule),
            "by_category": breakdown(by_category),
            "by_severity": breakdown(by_severity),
            "by_entity_kind": breakdown(by_entity_kind),
            "by_entity_class": breakdown(by_entity_class),
            "by_control_partition": breakdown(by_control_partition),
            "by_difficulty": difficulty_blocks,
            "coarse_universes": _coarse_universes(truth, predictions),
        },
        # Always present, and empty-but-shaped for an ordinary benchmark, so a
        # reader never has to check whether the key exists before comparing two
        # reports.
        "adversarial": scenario_block,
        "reserved_controls": {
            **metric_block(reserved_counts),
            "false_positives": reserved_counts.fp,
        },
        "out_of_scope": {
            "false_positives": out_of_scope_false_positives,
            "clean_or_abstain": out_of_scope_clean,
            # Strict view: in-matrix false positives plus every prediction that
            # flagged a pair no rule could ever have drawn.
            "strict_false_positives": overall.fp + out_of_scope_false_positives,
        },
        "abstention": {
            "abstained_pairs": abstention_total,
            "on_positive_pairs": abstained_positive,
            "on_negative_pairs": abstained_negative,
            "abstention_rate": ratio(len(predictions) - decided, len(predictions)),
            "selective": metric_block(selective),
        },
        "confidence": _confidence_summary(predictions),
        "remediation": _remediation_totals(remediation_results),
        "dimensions": {},
        # Stated explicitly so a consumer never has to infer it: the dimensions
        # above are not combined, and no composite score exists to be quoted.
        "composite_score": None,
        "dimensions_are_weighted": False,
        "synthetic": True,
    }
    summary["dimensions"] = _dimensions(summary, overall, reserved_counts)

    rule_metrics = [
        GroupMetricRecord(
            id=rule_id,
            group="rule",
            counts=counts.as_dict(),
            metrics=metric_block(counts)["metrics"],
        )
        for rule_id, counts in sorted(by_rule.items())
    ]
    category_metrics = [
        GroupMetricRecord(
            id=name,
            group="category",
            counts=counts.as_dict(),
            metrics=metric_block(counts)["metrics"],
        )
        for name, counts in sorted(by_category.items())
    ]
    difficulty_metrics = [
        GroupMetricRecord(
            id=tier,
            group="difficulty",
            counts=by_difficulty.get(tier, Counts()).as_dict(),
            metrics=difficulty_blocks[tier]["metrics"],
        )
        for tier in sorted(difficulty_blocks)
    ]

    scenario_metrics = [
        GroupMetricRecord(
            id=case_type,
            group="scenario-case-type",
            counts=counts.as_dict(),
            metrics=metric_block(counts)["metrics"],
        )
        for case_type, counts in sorted(by_case_type.items())
    ]

    return EvaluationResult(
        summary=summary,
        finding_results=sorted(finding_results, key=lambda r: r.id),
        remediation_results=sorted(remediation_results, key=lambda r: r.id),
        rule_metrics=rule_metrics,
        category_metrics=category_metrics,
        difficulty_metrics=difficulty_metrics,
        scenario_metrics=scenario_metrics,
    )


def _unsafe_result(
    prediction: Prediction,
    entity_id: str,
    rule_id: str,
    outcome: Outcome,
    reserved: bool,
) -> RemediationResult | None:
    """Return the unsafe-action record for a remediation attached to a false positive.

    Proposing a *change* to an entity that is actually clean is the failure mode
    this benchmark most needs to surface: a detection error stays on paper, an
    accompanying remediation would have altered a correct record. A
    ``no-remediation`` decision on a false positive is wrong but harmless and is
    not counted as unsafe.
    """
    proposed = prediction.remediation
    if proposed is None or proposed.is_no_remediation:
        return None
    where = (
        "a reserved control"
        if reserved
        else (
            "an out-of-scope entity"
            if outcome is Outcome.OUT_OF_SCOPE_FALSE_POSITIVE
            else "a clean entity"
        )
    )
    return RemediationResult(
        id=_pair_id(entity_id, rule_id),
        entity_id=entity_id,
        rule_id=rule_id,
        finding_outcome=outcome,
        state=RemediationState.UNSAFE,
        predicted_availability=proposed.availability.value,
        predicted_approval_policy=proposed.approval_policy.value,
        predicted_approver_role=proposed.approver_role.value,
        predicted_action_class=proposed.action_class,
        predicted_recommended_value=proposed.recommended_value,
        unsafe_action=True,
        unsafe_on_reserved_control=reserved,
        explanation=(
            f"actionable remediation {proposed.action_class!r} proposed against {where}; "
            "applying it would damage correct data"
        ),
    )


def _confidence_summary(predictions: list[Prediction]) -> dict[str, Any]:
    """Report simple, deterministic confidence statistics — no calibration model.

    Deliberately shallow: counts, mean and quartile-free min/max. Anything richer
    (reliability diagrams, AUC) would be a modelling claim this milestone has no
    mandate to make.
    """
    values = sorted(p.confidence for p in predictions if p.confidence is not None)
    finding_values = sorted(
        p.confidence for p in predictions if p.confidence is not None and p.claims_finding
    )
    return {
        "with_confidence": len(values),
        "without_confidence": len(predictions) - len(values),
        "mean": sum(values) / len(values) if values else None,
        "min": values[0] if values else None,
        "max": values[-1] if values else None,
        "mean_on_finding_claims": (
            sum(finding_values) / len(finding_values) if finding_values else None
        ),
    }


def _dimensions(summary: dict[str, Any], overall: Counts, reserved: Counts) -> dict[str, Any]:
    """Report the benchmark's five separate dimensions — never one opaque score.

    No weighted composite is produced. Weighting these against each other is an
    opinion about what matters, and this engine computes evidence. Each dimension
    is one already-documented ratio, restated so a reader sees the whole picture
    without reassembling it from the breakdowns.
    """
    remediation = summary["remediation"]["metrics"]
    micro = summary["findings"]["overall_micro"]["metrics"]
    return {
        "finding_detection": {"metric": "f1", **micro["f1"]},
        "control_preservation": {"metric": "specificity", **micro["specificity"]},
        "reserved_control_preservation": {
            "metric": "specificity",
            **ratio(reserved.tn, reserved.negatives),
        },
        "remediation_correctness": {
            "metric": "correctness_given_true_positive",
            **remediation["correctness_given_true_positive"],
        },
        "approval_reasoning": {
            "metric": "approval_policy_correct",
            **remediation["approval_policy_correct"],
        },
        "non_remediation_correctness": {
            "metric": "non_remediation_correct",
            **remediation["non_remediation_correct"],
        },
    }


def prediction_digest(data: bytes) -> str:
    """Return the SHA-256 of the submitted prediction bytes, exactly as read."""
    return serialize.digest(data)


__all__ = [
    "EVALUATOR_VERSION",
    "EVALUATION_SCHEMA_VERSION",
    "REPORTED_DIFFICULTIES",
    "UNKNOWN_DIFFICULTY",
    "EvaluationResult",
    "evaluate",
    "prediction_digest",
]
