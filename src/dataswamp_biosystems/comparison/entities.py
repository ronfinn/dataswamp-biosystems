"""Record models for the comparison reports.

Like the evaluation records, every model is frozen, rejects unknown keys and
carries an ``id`` — the shared serializer sorts JSONL by ``id``, so file order
is a property of the data rather than of comparison order.

Because file order is by ``id``, *ranking* cannot be expressed as file order.
Every ranked record therefore carries an explicit integer ``rank``, and the
ranked reading order lives in the Markdown report and in the summary's ranked
lists. A rank that has to be recovered by re-sorting is still deterministic;
one that depends on line order would not survive the serializer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG


class PairTransition(StrEnum):
    """How one ``(entity, rule)`` pair's outcome changed between the two runs.

    Named from the candidate's point of view, and named for what *happened to
    the benchmark result* rather than for the raw cell change, so a reader does
    not have to translate ``fn -> tp`` into "good" every time.
    """

    NEWLY_SOLVED = "newly-solved"  # a missed defect is now detected (fn -> tp)
    NEWLY_BROKEN = "newly-broken"  # a detected defect is now missed (tp -> fn)
    NEW_FALSE_POSITIVE = "new-false-positive"  # a clean pair is now flagged (tn -> fp)
    RESOLVED_FALSE_POSITIVE = "resolved-false-positive"  # a flag on a clean pair is gone
    # Movements into or out of the matrix: an out-of-scope prediction is not a
    # matrix cell, so a pair crossing that boundary is neither solved nor broken.
    ENTERED_OUT_OF_SCOPE = "entered-out-of-scope"
    LEFT_OUT_OF_SCOPE = "left-out-of-scope"
    OTHER = "other"


class RuleStatus(StrEnum):
    """The overall direction of one rule's change."""

    REGRESSED = "regressed"
    IMPROVED = "improved"
    MIXED = "mixed"
    UNCHANGED = "unchanged"


class RemediationTransition(StrEnum):
    """How one remediation decision changed between the two runs."""

    NEWLY_CORRECT = "newly-correct"
    NEWLY_INCORRECT = "newly-incorrect"
    NEWLY_UNSAFE = "newly-unsafe"
    RESOLVED_UNSAFE = "resolved-unsafe"
    NEWLY_CORRECT_NO_REMEDIATION = "newly-correct-no-remediation"
    NEWLY_INCORRECT_NO_REMEDIATION = "newly-incorrect-no-remediation"
    NEWLY_SUBMITTED = "newly-submitted"
    NEWLY_MISSING = "newly-missing"


class PairTransitionRecord(BaseModel):
    """One evaluated pair whose confusion-matrix outcome changed."""

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    category: str = ""
    severity: str = ""
    entity_kind: str = ""
    entity_class: str = ""
    reserved_control: bool = False
    baseline_outcome: str = ""
    candidate_outcome: str = ""
    baseline_predicted_status: str = ""
    candidate_predicted_status: str = ""
    transition: PairTransition
    regression: bool
    synthetic: Literal[True] = True


class RuleRegressionRecord(BaseModel):
    """One rule whose counts or metrics moved between the two runs.

    Emitted for improvements as well as regressions: "which rules changed" is
    the question, and a comparison that showed only the bad news would be a
    worse instrument than one that shows both.
    """

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)  # the rule id, preserved exactly
    rule_id: str = Field(min_length=1)
    status: RuleStatus
    rank: int = Field(ge=1)
    regression_impact: int = Field(ge=0)
    improvement_impact: int = Field(ge=0)
    newly_solved: int = Field(ge=0)
    newly_broken: int = Field(ge=0)
    new_false_positives: int = Field(ge=0)
    resolved_false_positives: int = Field(ge=0)
    new_reserved_control_false_positives: int = Field(ge=0)
    counts: dict[str, Any]
    metrics: dict[str, Any]
    synthetic: Literal[True] = True


class ControlRegressionRecord(BaseModel):
    """One control pair whose false-positive status changed.

    A first-class output rather than a filtered view: a candidate that buys
    recall by flagging clean entities must be impossible to miss, and burying
    that in a general transition list is exactly how it gets missed.
    """

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    category: str = ""
    severity: str = ""
    entity_class: str = ""
    reserved_control: bool
    transition: Literal["new-false-positive", "resolved-false-positive"]
    regression: bool
    unsafe_remediation: bool = False
    synthetic: Literal[True] = True


class RemediationRegressionRecord(BaseModel):
    """One remediation decision that changed between the two runs."""

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    baseline_state: str = ""
    candidate_state: str = ""
    baseline_fully_correct: bool | None = None
    candidate_fully_correct: bool | None = None
    baseline_unsafe: bool | None = None
    candidate_unsafe: bool | None = None
    baseline_no_remediation_correct: bool | None = None
    candidate_no_remediation_correct: bool | None = None
    transitions: list[RemediationTransition]
    regression: bool
    synthetic: Literal[True] = True


__all__ = [
    "PairTransition",
    "RuleStatus",
    "RemediationTransition",
    "PairTransitionRecord",
    "RuleRegressionRecord",
    "ControlRegressionRecord",
    "RemediationRegressionRecord",
]
