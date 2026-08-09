"""Errors for the OpenMetadata adapter.

Two failure kinds exist, and they are kept apart because they mean different
things to a caller and map to different exit codes' *reasons*:

:class:`OpenMetadataConfigError`
    An *input* problem — an export that cannot be read, a manifest whose digests
    do not recompute, a mode a bundle cannot serve, or a missing configuration
    value. Nothing was transmitted.
:class:`OpenMetadataTransportError`
    A *live* problem — the catalogue could not be reached, answered an error
    status, or answered something that is not JSON. Raised only from
    :mod:`.client`, the one module that opens a socket.

Both map to CLI exit code 2, deliberately: from a user's point of view the run
did not produce a verdict, and inventing a third code to distinguish "your export
is wrong" from "your server is down" would encode a distinction no caller acts on
differently. The message says which it was.

A *plan validation problem* is deliberately not an exception. Problems are
returned as a sorted list of strings, matching the DataHub validator's
convention, so the CLI can print all of them instead of stopping at the first.

No error message here may carry a credential. :class:`OpenMetadataTransportError`
is constructed exclusively from a URL that has already passed through
:func:`~dataswamp_biosystems.adapters.openmetadata.client.redact_url`, because an
exception is one of the easiest ways for a token to reach a CI log.
"""

from __future__ import annotations


class OpenMetadataAdapterError(Exception):
    """Base class for every OpenMetadata adapter error."""


class OpenMetadataConfigError(OpenMetadataAdapterError):
    """An input could not be read, or cannot serve the requested mode (CLI exit 2)."""


class OpenMetadataTransportError(OpenMetadataAdapterError):
    """The catalogue could not be reached or refused a request (CLI exit 2).

    ``status`` carries the HTTP status when there was one, so a caller can treat
    a definitive 404 differently from an unreachable host without parsing the
    message. It is never populated with a response *body*, which on some
    deployments echoes request headers back.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


__all__ = [
    "OpenMetadataAdapterError",
    "OpenMetadataConfigError",
    "OpenMetadataTransportError",
]
