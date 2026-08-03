"""Errors and issue collection for the evaluation layer.

Mirrors :mod:`dataswamp_biosystems.observed.errors`: problems are accumulated as
:class:`PredictionIssue` values and raised together, so one submission reports
every problem in a single pass rather than failing on the first bad line.

Every prediction issue names the input record (line number and prediction id
where known), the field, the offending value, and the contract that value
violated — enough for an agent author to fix the submission without reading the
evaluator's source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PredictionIssueKind(StrEnum):
    """Categories of prediction problem, used for stable reporting and testing."""

    MALFORMED_JSON = "malformed-json"
    SCHEMA_VERSION = "schema-version"
    INVALID_FIELD = "invalid-field"
    DUPLICATE_ID = "duplicate-id"
    DUPLICATE_PAIR = "duplicate-pair"
    UNKNOWN_ENTITY = "unknown-entity"
    UNKNOWN_RULE = "unknown-rule"
    CONTRADICTION = "contradiction"


@dataclass(frozen=True, order=True)
class PredictionIssue:
    """A single, actionable problem with one submitted prediction.

    Ordering is defined so a list of issues sorts deterministically (line first,
    so a reader walks the file top to bottom).
    """

    line: int
    kind: PredictionIssueKind
    field: str = ""
    value: str = ""
    prediction_id: str = ""
    expected: str = ""

    def render(self) -> str:
        parts = [f"line {self.line}", f"[{self.kind.value}]"]
        if self.prediction_id:
            parts.append(f"prediction_id={self.prediction_id}")
        if self.field:
            parts.append(f"field={self.field}")
        if self.value:
            parts.append(f"value={self.value}")
        rendered = " ".join(parts)
        return f"{rendered}: expected {self.expected}" if self.expected else rendered


class EvaluationError(Exception):
    """Base class for all evaluation-layer errors."""


class EvaluationConfigError(EvaluationError):
    """Ground truth or a prediction file could not be read (CLI exit 2)."""


class PredictionValidationError(EvaluationError):
    """One or more submitted predictions violate the prediction contract."""

    def __init__(self, issues: list[PredictionIssue]) -> None:
        self.issues: list[PredictionIssue] = sorted(issues)
        super().__init__(self._summarize())

    def _summarize(self) -> str:
        lines = [f"{len(self.issues)} prediction issue(s) found:"]
        lines.extend(f"  - {issue.render()}" for issue in self.issues)
        return "\n".join(lines)


@dataclass(frozen=True)
class PredictionIssueCollector:
    """Accumulates prediction issues during a validation pass."""

    issues: list[PredictionIssue] = field(default_factory=list)

    def add(
        self,
        line: int,
        kind: PredictionIssueKind,
        *,
        field: str = "",
        value: str = "",
        prediction_id: str = "",
        expected: str = "",
    ) -> None:
        self.issues.append(
            PredictionIssue(
                line=line,
                kind=kind,
                field=field,
                value=value,
                prediction_id=prediction_id,
                expected=expected,
            )
        )

    def raise_if_any(self) -> None:
        if self.issues:
            raise PredictionValidationError(self.issues)


__all__ = [
    "PredictionIssueKind",
    "PredictionIssue",
    "EvaluationError",
    "EvaluationConfigError",
    "PredictionValidationError",
    "PredictionIssueCollector",
]
