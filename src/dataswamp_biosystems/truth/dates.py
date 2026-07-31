"""Deterministic date and timestamp derivation.

No wall-clock is ever read. Every date is the fixed ``epoch_anchor`` plus a
deterministic integer offset (days/seconds), so runs are reproducible and
lineage timestamps can be made monotonic by construction. All values are
timezone-aware UTC and serialized with a trailing ``Z``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def at_days(anchor: date, days: int) -> date:
    """Return ``anchor`` shifted by ``days`` (may be negative)."""
    return anchor + timedelta(days=days)


def at_offset(anchor: date, *, days: int = 0, seconds: int = 0) -> datetime:
    """Return a UTC ``datetime`` at ``anchor`` midnight plus the given offset."""
    base = datetime(anchor.year, anchor.month, anchor.day, tzinfo=UTC)
    return base + timedelta(days=days, seconds=seconds)


def iso_date(value: date) -> str:
    """Serialize a ``date`` as ``YYYY-MM-DD``."""
    return value.isoformat()


def iso_datetime(value: datetime) -> str:
    """Serialize a UTC ``datetime`` as ISO-8601 with a trailing ``Z``.

    Requires an aware UTC value; a naive or non-UTC datetime is a bug in the
    generator and raises rather than silently producing an ambiguous string.
    """
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"expected an aware UTC datetime, got {value!r}")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["at_days", "at_offset", "iso_date", "iso_datetime"]
