"""Errors and issue collection for scientific-file (estate) generation.

Mirrors :mod:`dataswamp_biosystems.truth.errors`: problems are accumulated as
:class:`EstateIssue` values and raised together as a single
:class:`EstateValidationError` with a deterministically ordered list, so a
generation or validation run reports every problem in one pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EstateIssueKind(StrEnum):
    """Categories of estate problem, used for stable reporting/testing."""

    PROFILE = "profile"
    DUPLICATE_ID = "duplicate-id"
    INVALID_ID = "invalid-id"
    UNRESOLVED_ASSET = "unresolved-asset"
    PATH_ESCAPE = "path-escape"
    CHECKSUM = "checksum"
    SIZE = "size"
    BUDGET = "budget"
    PLACEHOLDER = "placeholder"
    CONSISTENCY = "consistency"
    FORMAT = "format"
    SYNTHETIC_FLAG = "synthetic-flag"


@dataclass(frozen=True, order=True)
class EstateIssue:
    """A single, actionable estate problem.

    Ordering is defined so a list of issues sorts deterministically (by kind,
    then entity kind, then entity id, then field) for stable output and stable
    test assertions.
    """

    kind: EstateIssueKind
    entity_kind: str = ""
    entity_id: str = ""
    field: str = ""
    message: str = ""

    def render(self) -> str:
        location = self.entity_kind or "<estate>"
        parts = [f"[{self.kind.value}] {location}"]
        if self.entity_id:
            parts.append(f"id={self.entity_id}")
        if self.field:
            parts.append(f"field={self.field}")
        return f"{' '.join(parts)}: {self.message}"


class EstateError(Exception):
    """Base class for all estate errors."""


class EstateConfigError(EstateError):
    """An estate could not be read or its inputs parsed (maps to CLI exit 2)."""


class EstateValidationError(EstateError):
    """One or more problems were found while generating or validating the estate."""

    def __init__(self, issues: list[EstateIssue]) -> None:
        self.issues: list[EstateIssue] = sorted(issues)
        super().__init__(self._summarize())

    def _summarize(self) -> str:
        lines = [f"{len(self.issues)} estate issue(s) found:"]
        lines.extend(f"  - {issue.render()}" for issue in self.issues)
        return "\n".join(lines)


@dataclass(frozen=True)
class EstateIssueCollector:
    """Accumulates issues during a generation or validation pass."""

    issues: list[EstateIssue] = field(default_factory=list)

    def add(
        self,
        kind: EstateIssueKind,
        message: str,
        *,
        entity_kind: str = "",
        entity_id: str = "",
        field: str = "",
    ) -> None:
        self.issues.append(
            EstateIssue(
                kind=kind,
                entity_kind=entity_kind,
                entity_id=entity_id,
                field=field,
                message=message,
            )
        )

    def raise_if_any(self) -> None:
        if self.issues:
            raise EstateValidationError(self.issues)


__all__ = [
    "EstateIssueKind",
    "EstateIssue",
    "EstateError",
    "EstateConfigError",
    "EstateValidationError",
    "EstateIssueCollector",
]
