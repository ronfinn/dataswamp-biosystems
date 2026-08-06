"""Reference baseline agents: small, readable benchmark participants.

Three agents, published so that a DataSwamp score has something to be compared
against. They exist for transparency, not performance — each one is short enough
to read in full, and none of them is a production-quality governance agent.

``null``
    Claims nothing. The recall floor and the specificity ceiling.
``naive-metadata``
    Shallow single-field signals. Low precision by construction.
``rule-based``
    A transparent subset of the defect rules, re-implemented against observed
    metadata. The practical ceiling for a non-learning, metadata-only approach.

Every baseline is scored as a genuine participant. Each reads
``observed-graph.json`` and nothing else — never the expected findings, expected
remediations, controls, rule scope, mutation log, injected defects, profile
summary, truth graph, or a truth-mode catalogue export. That boundary lives in
:mod:`dataswamp_biosystems.baselines.observed_input`, which is the only module
here that opens a file for reading.

Adding a baseline is one new module implementing :class:`BaselineAgent` plus one
line in :mod:`dataswamp_biosystems.baselines.registry`. The same interface is
where a model-backed agent would attach; no provider client, credential or
network access appears anywhere in this package or its tests.

See ``docs/baselines.md``.
"""

from __future__ import annotations

from dataswamp_biosystems.baselines.base import (
    BASELINE_SCHEMA_VERSION,
    BaselineAgent,
    BaselineInfo,
)
from dataswamp_biosystems.baselines.catalogue import RULE_FACTS, RuleFact, rule_fact
from dataswamp_biosystems.baselines.errors import (
    BaselineError,
    ObservedInputError,
    UnknownBaselineError,
)
from dataswamp_biosystems.baselines.naive_agent import (
    NAIVE_CHECKS,
    NaiveMetadataBaseline,
)
from dataswamp_biosystems.baselines.null_agent import NullBaseline
from dataswamp_biosystems.baselines.observed_input import (
    ADVERSARIAL_ONLY_INPUT_FILES,
    ALWAYS_PRESENT_FORBIDDEN_FILES,
    FORBIDDEN_INPUT_FILES,
    PERMITTED_INPUT_FILES,
    ObservedEntity,
    ObservedInput,
)
from dataswamp_biosystems.baselines.registry import (
    BASELINE_NAMES,
    BASELINES,
    baseline_infos,
    get_baseline,
)
from dataswamp_biosystems.baselines.rule_agent import RuleBasedBaseline
from dataswamp_biosystems.baselines.runner import (
    BaselineRun,
    render_predictions,
    run_and_write,
    run_baseline,
    write_predictions,
)

__all__ = [
    "BASELINES",
    "BASELINE_NAMES",
    "BASELINE_SCHEMA_VERSION",
    "ADVERSARIAL_ONLY_INPUT_FILES",
    "ALWAYS_PRESENT_FORBIDDEN_FILES",
    "FORBIDDEN_INPUT_FILES",
    "NAIVE_CHECKS",
    "PERMITTED_INPUT_FILES",
    "RULE_FACTS",
    "BaselineAgent",
    "BaselineError",
    "BaselineInfo",
    "BaselineRun",
    "NaiveMetadataBaseline",
    "NullBaseline",
    "ObservedEntity",
    "ObservedInput",
    "ObservedInputError",
    "RuleBasedBaseline",
    "RuleFact",
    "UnknownBaselineError",
    "baseline_infos",
    "get_baseline",
    "render_predictions",
    "rule_fact",
    "run_and_write",
    "run_baseline",
    "write_predictions",
]
