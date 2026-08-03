"""The name-to-agent registry behind ``dataswamp run-baseline``.

A plain dictionary, built once and ordered from weakest to strongest so that
listing it reads as a ladder. Adding a baseline means writing the agent and
adding one entry here; there is no discovery mechanism, entry point or plugin
protocol, because three reference agents do not need one.
"""

from __future__ import annotations

from dataswamp_biosystems.baselines.base import BaselineAgent, BaselineInfo
from dataswamp_biosystems.baselines.errors import UnknownBaselineError
from dataswamp_biosystems.baselines.naive_agent import NaiveMetadataBaseline
from dataswamp_biosystems.baselines.null_agent import NullBaseline
from dataswamp_biosystems.baselines.rule_agent import RuleBasedBaseline

_AGENTS: tuple[BaselineAgent, ...] = (
    NullBaseline(),
    NaiveMetadataBaseline(),
    RuleBasedBaseline(),
)

BASELINES: dict[str, BaselineAgent] = {agent.info.name: agent for agent in _AGENTS}

#: Every registered baseline name, in registration order.
BASELINE_NAMES: tuple[str, ...] = tuple(BASELINES)


def get_baseline(name: str) -> BaselineAgent:
    """Return the agent registered under ``name``, or raise :class:`UnknownBaselineError`."""
    try:
        return BASELINES[name]
    except KeyError:
        raise UnknownBaselineError(name, BASELINE_NAMES) from None


def baseline_infos() -> tuple[BaselineInfo, ...]:
    """Return every baseline's identity block, in registration order."""
    return tuple(agent.info for agent in _AGENTS)


__all__ = ["BASELINES", "BASELINE_NAMES", "baseline_infos", "get_baseline"]
