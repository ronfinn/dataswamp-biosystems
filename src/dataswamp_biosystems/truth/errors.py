"""Errors and issue collection for truth-graph generation and validation.

Mirrors :mod:`dataswamp_biosystems.company.errors`: problems are accumulated as
:class:`TruthIssue` values and raised together as a single
:class:`TruthValidationError` with a deterministically ordered list, so that a
generation or validation run reports every problem in one pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TruthIssueKind(StrEnum):
    """Categories of truth-graph problem, used for stable reporting/testing."""

    PLAN = "plan"
    DUPLICATE_ID = "duplicate-id"
    INVALID_ID = "invalid-id"
    UNRESOLVED_REFERENCE = "unresolved-reference"
    INVALID_VOCABULARY = "invalid-vocabulary"
    RELATIONSHIP = "relationship"
    COUNT_MISMATCH = "count-mismatch"
    LINEAGE = "lineage"
    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    METADATA = "metadata"
    TEMPORAL = "temporal"
    SIZE = "size"
    SYNTHETIC_FLAG = "synthetic-flag"
    DOMAIN_LOCK = "domain-lock"


@dataclass(frozen=True, order=True)
class TruthIssue:
    """A single, actionable truth-graph problem.

    Ordering is defined so a list of issues sorts deterministically
    (by kind, then entity kind, then entity id, then field) for stable output
    and stable test assertions.
    """

    kind: TruthIssueKind
    entity_kind: str = ""
    entity_id: str = ""
    field: str = ""
    message: str = ""

    def render(self) -> str:
        location = self.entity_kind or "<graph>"
        parts = [f"[{self.kind.value}] {location}"]
        if self.entity_id:
            parts.append(f"id={self.entity_id}")
        if self.field:
            parts.append(f"field={self.field}")
        return f"{' '.join(parts)}: {self.message}"


class TruthError(Exception):
    """Base class for all truth-graph errors."""


class TruthConfigError(TruthError):
    """A generation-plan file could not be read or parsed (maps to CLI exit 2)."""


class TruthValidationError(TruthError):
    """One or more problems were found while generating or validating the graph."""

    def __init__(self, issues: list[TruthIssue]) -> None:
        self.issues: list[TruthIssue] = sorted(issues)
        super().__init__(self._summarize())

    def _summarize(self) -> str:
        lines = [f"{len(self.issues)} truth-graph issue(s) found:"]
        lines.extend(f"  - {issue.render()}" for issue in self.issues)
        return "\n".join(lines)


@dataclass(frozen=True)
class TruthIssueCollector:
    """Accumulates issues during a generation or validation pass."""

    issues: list[TruthIssue] = field(default_factory=list)

    def add(
        self,
        kind: TruthIssueKind,
        message: str,
        *,
        entity_kind: str = "",
        entity_id: str = "",
        field: str = "",
    ) -> None:
        self.issues.append(
            TruthIssue(
                kind=kind,
                entity_kind=entity_kind,
                entity_id=entity_id,
                field=field,
                message=message,
            )
        )

    def raise_if_any(self) -> None:
        if self.issues:
            raise TruthValidationError(self.issues)


__all__ = [
    "TruthIssueKind",
    "TruthIssue",
    "TruthError",
    "TruthConfigError",
    "TruthValidationError",
    "TruthIssueCollector",
]
