"""Errors for the OpenMetadata adapter.

Only one failure class exists at this milestone, because only one thing can go
wrong: an *input* that cannot be read or does not support the requested mode.
There is no transport error here — this adapter opens no socket. When live
ingestion arrives it will bring its own error class rather than overloading this
one, exactly as the DataHub adapter does.

A *plan validation problem* is deliberately not an exception. Problems are
returned as a sorted list of strings, matching the DataHub validator's
convention, so the CLI can print all of them instead of stopping at the first.
"""

from __future__ import annotations


class OpenMetadataAdapterError(Exception):
    """Base class for every OpenMetadata adapter error."""


class OpenMetadataConfigError(OpenMetadataAdapterError):
    """An input could not be read, or cannot serve the requested mode (CLI exit 2)."""


__all__ = [
    "OpenMetadataAdapterError",
    "OpenMetadataConfigError",
]
