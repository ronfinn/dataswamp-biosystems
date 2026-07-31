"""Project-specific configuration errors.

Loading and validating the canonical configuration collects *every* problem
before failing, so that ``dataswamp validate-config`` can report all issues in
one run rather than stopping at the first. Individual problems are represented
as :class:`ConfigIssue` values; the loader raises a single
:class:`ConfigValidationError` carrying the full, deterministically ordered
list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class IssueKind(StrEnum):
    """Categories of configuration problem, used for stable reporting/testing."""

    SCHEMA = "schema"
    DUPLICATE_ID = "duplicate-id"
    DUPLICATE_EMAIL = "duplicate-email"
    INVALID_EMAIL_DOMAIN = "invalid-email-domain"
    UNRESOLVED_REFERENCE = "unresolved-reference"
    INVALID_VOCABULARY = "invalid-vocabulary"
    STRUCTURAL = "structural"


@dataclass(frozen=True, order=True)
class ConfigIssue:
    """A single, actionable configuration problem.

    Ordering is defined so that a list of issues sorts deterministically
    (by source file, then kind, then entity id, then field) for stable output
    and stable test assertions.
    """

    kind: IssueKind
    message: str
    source: str = ""
    entity_id: str = ""
    field: str = ""

    def render(self) -> str:
        location = self.source or "<config>"
        parts = [f"[{self.kind.value}] {location}"]
        if self.entity_id:
            parts.append(f"id={self.entity_id}")
        if self.field:
            parts.append(f"field={self.field}")
        return f"{' '.join(parts)}: {self.message}"


class ConfigError(Exception):
    """Base class for all canonical-configuration errors."""


class ConfigLoadError(ConfigError):
    """A file could not be read or parsed (missing file, malformed YAML).

    Distinct from validation failures: this maps to CLI exit code 2, whereas
    validation failures map to exit code 1.
    """


class ConfigValidationError(ConfigError):
    """One or more validation issues were found in an otherwise loadable config."""

    def __init__(self, issues: list[ConfigIssue]) -> None:
        self.issues: list[ConfigIssue] = sorted(issues)
        super().__init__(self._summarize())

    def _summarize(self) -> str:
        lines = [f"{len(self.issues)} configuration issue(s) found:"]
        lines.extend(f"  - {issue.render()}" for issue in self.issues)
        return "\n".join(lines)


@dataclass(frozen=True)
class IssueCollector:
    """Accumulates issues during a validation pass."""

    issues: list[ConfigIssue] = field(default_factory=list)

    def add(
        self,
        kind: IssueKind,
        message: str,
        *,
        source: str = "",
        entity_id: str = "",
        field: str = "",
    ) -> None:
        self.issues.append(
            ConfigIssue(
                kind=kind,
                message=message,
                source=source,
                entity_id=entity_id,
                field=field,
            )
        )

    def raise_if_any(self) -> None:
        if self.issues:
            raise ConfigValidationError(self.issues)


__all__ = [
    "IssueKind",
    "ConfigIssue",
    "ConfigError",
    "ConfigLoadError",
    "ConfigValidationError",
    "IssueCollector",
]
