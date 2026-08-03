"""Record models for the evaluation reports.

Every emitted record is frozen, rejects unknown keys and carries an ``id`` — the
shared serializer sorts JSONL by ``id``, so record order is a property of the
data rather than of evaluation order.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG


class Outcome(StrEnum):
    """What one evaluated pair contributed to the score.

    The four confusion-matrix cells are the only outcomes that enter a metric
    denominator. The last two are deliberately *outside* the matrix: an
    out-of-scope prediction names a pair that was never part of any rule's
    population, and folding it into the matrix would either invent a true
    negative or silently enlarge a denominator nobody measured.
    """

    TP = "tp"
    FP = "fp"
    FN = "fn"
    TN = "tn"
    OUT_OF_SCOPE_FALSE_POSITIVE = "out_of_scope_false_positive"
    OUT_OF_SCOPE_CLEAN = "out_of_scope_clean"


class RemediationState(StrEnum):
    """How one expected or submitted remediation decision was treated."""

    SCORED = "scored"  # a true positive with a submitted remediation
    MISSING = "missing"  # a true positive with no remediation submitted
    UNSCORED_MISSED_FINDING = "unscored-missed-finding"  # the finding itself was not detected
    UNSAFE = "unsafe"  # a remediation attached to a false positive


class FindingResult(BaseModel):
    """One evaluated ``(entity_id, rule_id)`` pair."""

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    category: str
    severity: str
    entity_kind: str
    entity_class: str
    expected_status: Literal["present", "clean", "out-of-scope"]
    predicted_status: Literal["finding", "clean", "abstain", "absent"]
    outcome: Outcome
    in_scope: bool
    reserved_control: bool
    abstained: bool
    prediction_id: str = ""
    confidence: float | None = None
    # Attribute correctness is reported *alongside* the outcome and never used to
    # rescue or invalidate the pair match itself.
    category_correct: bool | None = None
    severity_correct: bool | None = None
    synthetic: Literal[True] = True


class RemediationResult(BaseModel):
    """One remediation decision, scored only where the finding permits it."""

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    finding_outcome: Outcome
    state: RemediationState
    expected_availability: str = ""
    expected_approval_policy: str = ""
    expected_approver_role: str = ""
    expected_action_class: str = ""
    expected_recommended_value: Any = None
    predicted_availability: str = ""
    predicted_approval_policy: str = ""
    predicted_approver_role: str = ""
    predicted_action_class: str = ""
    predicted_recommended_value: Any = None
    availability_correct: bool | None = None
    approval_policy_correct: bool | None = None
    approver_role_correct: bool | None = None
    action_class_correct: bool | None = None
    recommended_value_correct: bool | None = None
    no_remediation_correct: bool | None = None
    fully_correct: bool = False
    unsafe_action: bool = False
    unsafe_on_reserved_control: bool = False
    explanation: str = ""
    synthetic: Literal[True] = True


class GroupMetricRecord(BaseModel):
    """One row of a per-rule or per-category metric table."""

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)
    group: str = Field(min_length=1)
    counts: dict[str, int]
    metrics: dict[str, Any]
    synthetic: Literal[True] = True


__all__ = [
    "Outcome",
    "RemediationState",
    "FindingResult",
    "RemediationResult",
    "GroupMetricRecord",
]
