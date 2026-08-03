"""Errors and issue collection for the bundle layer.

Mirrors :mod:`dataswamp_biosystems.evaluation.errors`: verification problems are
accumulated as :class:`BundleIssue` values and raised together, so one pass over
a bundle reports everything wrong with it rather than stopping at the first bad
checksum. Every issue names the offending *file* and the *invariant* it violated,
which is what a consumer needs in order to decide whether a bundle was corrupted
in transit or deliberately altered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BundleIssueKind(StrEnum):
    """Categories of bundle problem, used for stable reporting and testing."""

    MANIFEST_SCHEMA = "manifest-schema"
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    MISSING_FILE = "missing-file"
    UNDECLARED_FILE = "undeclared-file"
    CHECKSUM_MISMATCH = "checksum-mismatch"
    UNSAFE_PATH = "unsafe-path"
    SYMLINK = "symlink"
    STRUCTURE = "structure"
    REFERENCE = "reference"
    PROVENANCE = "provenance"
    FINGERPRINT = "fingerprint"


@dataclass(frozen=True, order=True)
class BundleIssue:
    """A single, actionable problem with one bundle file or invariant."""

    file: str
    kind: BundleIssueKind
    detail: str = ""
    expected: str = ""
    actual: str = ""

    def render(self) -> str:
        parts = [f"{self.file or '<bundle>'}", f"[{self.kind.value}]"]
        if self.detail:
            parts.append(self.detail)
        rendered = " ".join(parts)
        if self.expected or self.actual:
            expected = self.expected or "<none>"
            rendered = f"{rendered}: expected {expected}, got {self.actual or '<none>'}"
        return rendered


class BundleError(Exception):
    """Base class for all bundle-layer errors."""


class BundleConfigError(BundleError):
    """A bundle or one of its inputs could not be read (CLI exit 2)."""


class BundleValidationError(BundleError):
    """One or more bundle invariants are violated."""

    def __init__(self, issues: list[BundleIssue]) -> None:
        self.issues: list[BundleIssue] = sorted(issues)
        super().__init__(self._summarize())

    def _summarize(self) -> str:
        lines = [f"{len(self.issues)} bundle issue(s) found:"]
        lines.extend(f"  - {issue.render()}" for issue in self.issues)
        return "\n".join(lines)


@dataclass(frozen=True)
class BundleIssueCollector:
    """Accumulates bundle issues during a verification pass."""

    issues: list[BundleIssue] = field(default_factory=list)

    def add(
        self,
        file: str,
        kind: BundleIssueKind,
        *,
        detail: str = "",
        expected: str = "",
        actual: str = "",
    ) -> None:
        self.issues.append(
            BundleIssue(file=file, kind=kind, detail=detail, expected=expected, actual=actual)
        )

    def raise_if_any(self) -> None:
        if self.issues:
            raise BundleValidationError(self.issues)


__all__ = [
    "BundleIssueKind",
    "BundleIssue",
    "BundleError",
    "BundleConfigError",
    "BundleValidationError",
    "BundleIssueCollector",
]
