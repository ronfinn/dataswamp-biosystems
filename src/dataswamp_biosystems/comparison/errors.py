"""Errors for the comparison layer.

Mirrors :mod:`dataswamp_biosystems.evaluation.errors`: problems are accumulated
as :class:`IdentityMismatch` values and raised together, so two runs drawn from
different universes report *every* differing identity field in one pass rather
than failing on the first one. An author who seeded a run differently and also
changed profile should learn both facts at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, order=True)
class IdentityMismatch:
    """One benchmark-identity field that differs between the two runs.

    Ordering is by field name so a list of mismatches renders deterministically.
    """

    field: str
    baseline: str
    candidate: str

    def render(self) -> str:
        return f"{self.field}: baseline={self.baseline!r} candidate={self.candidate!r}"


class ComparisonError(Exception):
    """Base class for all comparison-layer errors."""


class ComparisonConfigError(ComparisonError):
    """An evaluation directory could not be read or is malformed (CLI exit 2)."""


class IncompatibleRunsError(ComparisonError):
    """The two runs do not describe the same benchmark universe (CLI exit 1).

    Refusing is the whole point: differencing metrics across universes produces
    a number that looks meaningful and is not. The message names every field
    that differs, so the reason is actionable without reading this source.
    """

    def __init__(self, mismatches: list[IdentityMismatch]) -> None:
        self.mismatches: list[IdentityMismatch] = sorted(mismatches)
        super().__init__(self._summarize())

    def _summarize(self) -> str:
        lines = [
            f"Runs are not comparable — {len(self.mismatches)} benchmark identity field(s) differ:"
        ]
        lines.extend(f"  - {mismatch.render()}" for mismatch in self.mismatches)
        return "\n".join(lines)


@dataclass(frozen=True)
class IdentityMismatchCollector:
    """Accumulates identity mismatches during a compatibility pass."""

    mismatches: list[IdentityMismatch] = field(default_factory=list)

    def compare(self, field_name: str, baseline: object, candidate: object) -> None:
        """Record a mismatch when the two values differ."""
        if baseline != candidate:
            self.mismatches.append(
                IdentityMismatch(
                    field=field_name,
                    baseline=str(baseline),
                    candidate=str(candidate),
                )
            )

    def raise_if_any(self) -> None:
        if self.mismatches:
            raise IncompatibleRunsError(self.mismatches)


__all__ = [
    "IdentityMismatch",
    "ComparisonError",
    "ComparisonConfigError",
    "IncompatibleRunsError",
    "IdentityMismatchCollector",
]
