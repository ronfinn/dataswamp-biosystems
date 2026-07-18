"""Annotated field types with canonical JSON serialization.

Dates and timestamps serialize to fixed strings (``YYYY-MM-DD`` and ISO-8601
with a trailing ``Z``) regardless of platform or locale, so JSON output is
byte-stable. Entities use these aliases instead of bare ``date``/``datetime``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import PlainSerializer

from dataswamp_biosystems.truth.dates import iso_date, iso_datetime

# UTC timestamp serialized as ``...Z``; plain date serialized as ``YYYY-MM-DD``.
UtcDateTime = Annotated[datetime, PlainSerializer(iso_datetime, return_type=str, when_used="json")]
IsoDate = Annotated[date, PlainSerializer(iso_date, return_type=str, when_used="json")]

__all__ = ["UtcDateTime", "IsoDate"]
