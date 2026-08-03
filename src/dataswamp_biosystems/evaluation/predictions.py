"""The versioned prediction contract an assessment agent submits.

A submission is one JSONL file: one JSON object per line, each a
:class:`Prediction`. The contract is deliberately *small* — an agent must supply
only what it could reasonably know by looking at the observed graph. Everything
the ground truth records but an agent could not infer (defect instance ids,
mutation ids, truth ``before`` values) is never asked for.

Three claims are expressible, via the ``status`` field:

``finding``
    "this entity violates this rule". The scorable positive claim.
``clean``
    "I looked and this entity does not violate this rule". Scored as a negative
    prediction, and the only way to earn an *explicit* true negative.
``abstain``
    "I decline to decide". Distinguishable from silence: an abstention is
    recorded, counted and reported, never silently folded into a
    confusion-matrix cell it did not earn.

Matching is structural. ``entity_id`` plus ``rule_id`` identify the pair being
claimed; prose in ``evidence`` is carried for a human reader and never matched
on. An agent that spots a real problem without naming a rule may omit
``rule_id``; such a prediction is never guessed into a pair, and is instead
scored in the coarser entity- and category-level universes described in
:mod:`dataswamp_biosystems.evaluation.engine`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG
from dataswamp_biosystems.evaluation.errors import (
    EvaluationConfigError,
    PredictionIssueCollector,
    PredictionIssueKind,
)
from dataswamp_biosystems.observed.entities import (
    NO_REMEDIATION_ACTION,
    ApprovalPolicy,
    ApproverRole,
    Category,
    RemediationAvailability,
    Severity,
)

# The prediction schema this evaluator understands. A submission declaring any
# other version is rejected rather than best-effort parsed: an agent built
# against a different contract must be told so, not silently mis-scored.
PREDICTION_SCHEMA_VERSION = 1
SUPPORTED_PREDICTION_SCHEMA_VERSIONS: frozenset[int] = frozenset({PREDICTION_SCHEMA_VERSION})

# The status strings, as an explicit contract rather than a bare enum reference.
STATUS_FINDING = "finding"
STATUS_CLEAN = "clean"
STATUS_ABSTAIN = "abstain"


class PredictedRemediation(BaseModel):
    """A proposed fix, scored only against the expected remediation for a true positive.

    ``action_class`` is the programmatic action family (``restore_field``,
    ``assign_owner``, …) mirroring
    :attr:`dataswamp_biosystems.observed.defects.DefectDef.action_class`. The
    explicit no-action decision is the sentinel
    :data:`~dataswamp_biosystems.observed.entities.NO_REMEDIATION_ACTION`, which
    is a *decision*, not an omission — an agent that stays silent on a
    non-remediable finding has not made it.
    """

    model_config = STRICT_MODEL_CONFIG

    action_class: str = Field(min_length=1)
    availability: RemediationAvailability
    approval_policy: ApprovalPolicy
    approver_role: ApproverRole = ApproverRole.NONE
    action: str = ""
    recommended_value: Any = None

    @property
    def is_no_remediation(self) -> bool:
        return self.action_class == NO_REMEDIATION_ACTION


class Prediction(BaseModel):
    """One agent claim about one ``(entity_id, rule_id)`` pair."""

    model_config = STRICT_MODEL_CONFIG

    schema_version: int
    prediction_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    rule_id: str = ""
    status: str = STATUS_FINDING
    category: Category | None = None
    severity: Severity | None = None
    confidence: float | None = None
    evidence: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    remediation: PredictedRemediation | None = None
    agent: dict[str, str] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in (STATUS_FINDING, STATUS_CLEAN, STATUS_ABSTAIN):
            raise ValueError(
                f"unsupported status {value!r}; expected one of "
                f"{STATUS_FINDING!r}, {STATUS_CLEAN!r}, {STATUS_ABSTAIN!r}"
            )
        return value

    @field_validator("confidence")
    @classmethod
    def _finite_confidence(cls, value: float | None) -> float | None:
        """Reject NaN/±inf and out-of-range values.

        Pydantic accepts ``float("nan")`` for a ``float`` field, and JSON's
        ``NaN``/``Infinity`` extensions parse happily, so the check has to be
        explicit — a NaN confidence would otherwise poison every summary
        statistic computed from it.
        """
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError(f"confidence must be a finite number, got {value!r}")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must lie in [0.0, 1.0], got {value!r}")
        return value

    @property
    def claims_finding(self) -> bool:
        return self.status == STATUS_FINDING

    @property
    def abstains(self) -> bool:
        return self.status == STATUS_ABSTAIN

    @property
    def pair_key(self) -> tuple[str, str]:
        return (self.entity_id, self.rule_id)


def _contradictions(prediction: Prediction) -> list[tuple[str, str, str]]:
    """Return ``(field, value, expected)`` for every internal contradiction.

    These are cross-field rules a single-field validator cannot express, and
    each one describes a submission that is not merely wrong but *incoherent* —
    scoring it would mean guessing which half the agent meant.
    """
    problems: list[tuple[str, str, str]] = []
    remediation = prediction.remediation
    if remediation is None:
        return problems

    if not prediction.claims_finding:
        problems.append(
            (
                "remediation",
                remediation.action_class,
                f"no remediation on a {prediction.status!r} prediction; "
                f"a remediation only makes sense alongside status {STATUS_FINDING!r}",
            )
        )
        return problems

    non_remediable = remediation.availability is RemediationAvailability.NONE
    if non_remediable and not remediation.is_no_remediation:
        problems.append(
            (
                "remediation.action_class",
                remediation.action_class,
                f"{NO_REMEDIATION_ACTION!r} when availability is "
                f"{RemediationAvailability.NONE.value!r}",
            )
        )
    if remediation.is_no_remediation and not non_remediable:
        problems.append(
            (
                "remediation.availability",
                remediation.availability.value,
                f"{RemediationAvailability.NONE.value!r} when action_class is "
                f"{NO_REMEDIATION_ACTION!r}",
            )
        )
    if (
        remediation.approval_policy is ApprovalPolicy.REQUIRED
        and remediation.approver_role is ApproverRole.NONE
    ):
        problems.append(
            (
                "remediation.approver_role",
                remediation.approver_role.value,
                f"a concrete approver role when approval_policy is "
                f"{ApprovalPolicy.REQUIRED.value!r}",
            )
        )
    return problems


def _field_path(location: tuple[Any, ...]) -> str:
    return ".".join(str(part) for part in location) or "<record>"


def parse_predictions(
    text: str,
    *,
    known_entities: frozenset[str],
    known_rules: frozenset[str],
) -> list[Prediction]:
    """Parse and validate a JSONL submission, or raise with *every* problem found.

    Nothing is silently discarded: a malformed line, an unknown id, a duplicate
    or a contradiction is an issue naming the line, field, value and contract.
    Validation is total — the whole file is inspected before anything is raised —
    so an agent author sees the full picture in one run.
    """
    issues = PredictionIssueCollector()
    predictions: list[Prediction] = []
    seen_ids: dict[str, int] = {}
    seen_pairs: dict[tuple[str, str], int] = {}

    for offset, raw in enumerate(text.splitlines()):
        line = offset + 1
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            issues.add(
                line,
                PredictionIssueKind.MALFORMED_JSON,
                value=exc.msg,
                expected="one JSON object per line",
            )
            continue
        if not isinstance(payload, dict):
            issues.add(
                line,
                PredictionIssueKind.MALFORMED_JSON,
                value=type(payload).__name__,
                expected="a JSON object",
            )
            continue

        # The schema version gates parsing: a record written against a different
        # contract must not be coerced into this one.
        declared = payload.get("schema_version")
        if declared not in SUPPORTED_PREDICTION_SCHEMA_VERSIONS:
            issues.add(
                line,
                PredictionIssueKind.SCHEMA_VERSION,
                field="schema_version",
                value=json.dumps(declared),
                prediction_id=str(payload.get("prediction_id", "")),
                expected=f"one of {sorted(SUPPORTED_PREDICTION_SCHEMA_VERSIONS)}",
            )
            continue

        claimed_id = str(payload.get("prediction_id", ""))
        try:
            prediction = Prediction.model_validate(payload)
        except ValidationError as exc:
            for error in exc.errors():
                issues.add(
                    line,
                    PredictionIssueKind.INVALID_FIELD,
                    field=_field_path(error["loc"]),
                    value=repr(error.get("input")),
                    prediction_id=claimed_id,
                    expected=error["msg"],
                )
            continue

        if prediction.prediction_id in seen_ids:
            issues.add(
                line,
                PredictionIssueKind.DUPLICATE_ID,
                field="prediction_id",
                value=prediction.prediction_id,
                prediction_id=prediction.prediction_id,
                expected=f"a unique id (first seen on line {seen_ids[prediction.prediction_id]})",
            )
        else:
            seen_ids[prediction.prediction_id] = line

        if prediction.pair_key in seen_pairs:
            first = seen_pairs[prediction.pair_key]
            issues.add(
                line,
                PredictionIssueKind.DUPLICATE_PAIR,
                field="entity_id,rule_id",
                value=f"{prediction.entity_id},{prediction.rule_id}",
                prediction_id=prediction.prediction_id,
                expected=f"at most one prediction per pair (first seen on line {first})",
            )
        else:
            seen_pairs[prediction.pair_key] = line

        if prediction.entity_id not in known_entities:
            issues.add(
                line,
                PredictionIssueKind.UNKNOWN_ENTITY,
                field="entity_id",
                value=prediction.entity_id,
                prediction_id=prediction.prediction_id,
                expected="an entity present in the benchmark ground truth",
            )
        if prediction.rule_id and prediction.rule_id not in known_rules:
            issues.add(
                line,
                PredictionIssueKind.UNKNOWN_RULE,
                field="rule_id",
                value=prediction.rule_id,
                prediction_id=prediction.prediction_id,
                expected="a rule id present in rule-scope.jsonl",
            )

        for field_name, value, expected in _contradictions(prediction):
            issues.add(
                line,
                PredictionIssueKind.CONTRADICTION,
                field=field_name,
                value=value,
                prediction_id=prediction.prediction_id,
                expected=expected,
            )

        predictions.append(prediction)

    issues.raise_if_any()
    # Sorted so evaluation order never depends on file order.
    return sorted(predictions, key=lambda p: (p.entity_id, p.rule_id, p.prediction_id))


def load_predictions(
    path: Path | str,
    *,
    known_entities: frozenset[str],
    known_rules: frozenset[str],
) -> tuple[list[Prediction], bytes]:
    """Read and validate a submission; return the predictions and the raw bytes.

    The raw bytes are returned so the caller can fingerprint exactly what was
    submitted, before any normalisation.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise EvaluationConfigError(f"could not read predictions at {path}: {exc}") from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationConfigError(f"predictions at {path} are not valid UTF-8: {exc}") from exc
    predictions = parse_predictions(text, known_entities=known_entities, known_rules=known_rules)
    return predictions, data


__all__ = [
    "PREDICTION_SCHEMA_VERSION",
    "SUPPORTED_PREDICTION_SCHEMA_VERSIONS",
    "STATUS_FINDING",
    "STATUS_CLEAN",
    "STATUS_ABSTAIN",
    "Prediction",
    "PredictedRemediation",
    "parse_predictions",
    "load_predictions",
]
