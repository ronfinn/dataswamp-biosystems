"""Errors and issue collection for the imperfection engine (observed state).

Mirrors :mod:`dataswamp_biosystems.truth.errors`: problems are accumulated as
:class:`ObservedIssue` values and raised together as a single
:class:`ObservedValidationError` with a deterministically ordered list, so a
generation or validation run reports every problem in one pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ObservedIssueKind(StrEnum):
    """Categories of observed-state problem, used for stable reporting/testing."""

    PROFILE = "profile"
    DUPLICATE_ID = "duplicate-id"
    INVALID_ID = "invalid-id"
    UNRESOLVED_REFERENCE = "unresolved-reference"
    UNKNOWN_RULE = "unknown-rule"
    LEDGER = "ledger"
    FIDELITY = "fidelity"
    CONTAMINATION = "contamination"
    INCOMPATIBILITY = "incompatibility"
    CONSISTENCY = "consistency"
    PROFILE_BOUNDS = "profile-bounds"
    SYNTHETIC_FLAG = "synthetic-flag"


@dataclass(frozen=True, order=True)
class ObservedIssue:
    """A single, actionable observed-state problem.

    Ordering is defined so a list of issues sorts deterministically (by kind,
    then entity kind, then entity id, then field) for stable output and stable
    test assertions.
    """

    kind: ObservedIssueKind
    entity_kind: str = ""
    entity_id: str = ""
    field: str = ""
    message: str = ""

    def render(self) -> str:
        location = self.entity_kind or "<observed>"
        parts = [f"[{self.kind.value}] {location}"]
        if self.entity_id:
            parts.append(f"id={self.entity_id}")
        if self.field:
            parts.append(f"field={self.field}")
        return f"{' '.join(parts)}: {self.message}"


class ObservedError(Exception):
    """Base class for all observed-state errors."""


class ObservedConfigError(ObservedError):
    """An observed estate could not be read or its inputs parsed (CLI exit 2)."""


class ObservedValidationError(ObservedError):
    """One or more problems were found while generating or validating the observed state."""

    def __init__(self, issues: list[ObservedIssue]) -> None:
        self.issues: list[ObservedIssue] = sorted(issues)
        super().__init__(self._summarize())

    def _summarize(self) -> str:
        lines = [f"{len(self.issues)} observed-state issue(s) found:"]
        lines.extend(f"  - {issue.render()}" for issue in self.issues)
        return "\n".join(lines)


@dataclass(frozen=True)
class ObservedIssueCollector:
    """Accumulates issues during a generation or validation pass."""

    issues: list[ObservedIssue] = field(default_factory=list)

    def add(
        self,
        kind: ObservedIssueKind,
        message: str,
        *,
        entity_kind: str = "",
        entity_id: str = "",
        field: str = "",
    ) -> None:
        self.issues.append(
            ObservedIssue(
                kind=kind,
                entity_kind=entity_kind,
                entity_id=entity_id,
                field=field,
                message=message,
            )
        )

    def raise_if_any(self) -> None:
        if self.issues:
            raise ObservedValidationError(self.issues)


__all__ = [
    "ObservedIssueKind",
    "ObservedIssue",
    "ObservedError",
    "ObservedConfigError",
    "ObservedValidationError",
    "ObservedIssueCollector",
]
