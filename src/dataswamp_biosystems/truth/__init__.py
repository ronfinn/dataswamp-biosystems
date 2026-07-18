"""Deterministic truth-graph generation for Data Swamp Biosystems.

The truth graph is the complete and correct synthetic scientific/governance
state *before any defects are introduced* — the ground truth a future observed
graph and governance benchmarks are scored against. Generation is seeded and
deterministic: the same config, generator version, and seed produce
byte-identical output.

This package depends only on the catalogue-independent company model; it never
imports a catalogue or governance tool. See ``docs/domain-model.md``.
"""

from __future__ import annotations

from dataswamp_biosystems.truth.errors import (
    TruthConfigError,
    TruthError,
    TruthIssue,
    TruthIssueKind,
    TruthValidationError,
)
from dataswamp_biosystems.truth.generator import generate_truth_graph
from dataswamp_biosystems.truth.graph import (
    TRUTH_SCHEMA_VERSION,
    TruthGraph,
    TruthGraphMeta,
)
from dataswamp_biosystems.truth.plan import (
    GenerationPlan,
    load_generation_plan,
    validate_plan_against_config,
)
from dataswamp_biosystems.truth.validate import validate_truth_graph
from dataswamp_biosystems.truth.writer import write_truth_graph

__all__ = [
    "TRUTH_SCHEMA_VERSION",
    "TruthGraph",
    "TruthGraphMeta",
    "GenerationPlan",
    "load_generation_plan",
    "validate_plan_against_config",
    "generate_truth_graph",
    "validate_truth_graph",
    "write_truth_graph",
    "TruthError",
    "TruthConfigError",
    "TruthValidationError",
    "TruthIssue",
    "TruthIssueKind",
]
