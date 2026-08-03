"""Errors raised while resolving or running a baseline agent."""

from __future__ import annotations


class BaselineError(Exception):
    """Base class for every baseline failure."""


class UnknownBaselineError(BaselineError):
    """A baseline was requested by a name no agent is registered under."""

    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        self.name = name
        self.known = known
        super().__init__(f"unknown baseline {name!r}; expected one of: {', '.join(known)}")


class ObservedInputError(BaselineError):
    """The observed input a baseline reads is missing, unreadable or malformed."""


__all__ = ["BaselineError", "UnknownBaselineError", "ObservedInputError"]
