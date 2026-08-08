"""Errors for the DataHub live-ingestion path.

Two failure classes exist and they map onto different exit codes, so they are
different types rather than one exception with a flag:

:class:`DataHubConfigError`
    Something about the *inputs* is wrong — a missing environment variable, an
    export directory that cannot be read, a tampered digest. The command never
    reached the network. CLI exit code 2.
:class:`DataHubTransportError`
    The server could not be reached, or answered in a way that is not a valid
    response. CLI exit code 2 as well: from the caller's point of view an
    unreachable catalogue is an I/O problem, not a benchmark verdict.

A *discrepancy* is deliberately not an exception. Missing, extra and mutated
metadata are the round-trip layer's findings — they belong in the report, and
the CLI turns a non-empty report into exit code 1. Raising on the first one
would defeat the whole purpose of reporting four claims separately.

Every message here is built from non-secret values only. The GMS token is never
interpolated into an exception, because exception text reaches logs, CI output
and issue reports.
"""

from __future__ import annotations


class DataHubAdapterError(Exception):
    """Base class for every DataHub live-path error."""


class DataHubConfigError(DataHubAdapterError):
    """An input could not be read, or required configuration is absent (CLI exit 2)."""


class DataHubTransportError(DataHubAdapterError):
    """The GMS could not be reached or returned an unusable response (CLI exit 2).

    Carries the HTTP status when there was one, so a caller can distinguish
    "refused the payload" from "was not there at all" without parsing text.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


__all__ = [
    "DataHubAdapterError",
    "DataHubConfigError",
    "DataHubTransportError",
]
