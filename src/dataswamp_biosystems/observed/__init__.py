"""Deterministic imperfection engine: the observed state derived from truth.

The observed state is a deliberately-imperfect view of the truth graph, produced
by a *separate* transformation that reads the truth graph and applies a curated
taxonomy of defects, writing to ``generated/observed/``. It never mutates the
truth graph and never depends on any catalogue tool — it consumes the truth
graph in memory, exactly as the estate does. Every injected defect is recorded
explicitly, with before/after values and machine-readable expected findings and
remediations, so a future governance agent can be scored against known truth.

Generation is seeded and deterministic: the same config, truth seed, defect
seed, and profile produce byte-identical output. See ``docs/observed-state.md``
and ADR 0003.
"""

from __future__ import annotations

from dataswamp_biosystems.observed.defects import (
    DEFECTS,
    DefectDef,
    defects_in_order,
    registry_rows,
    validate_registry,
)
from dataswamp_biosystems.observed.engine import (
    OBSERVED_GENERATOR_VERSION,
    OBSERVED_SCHEMA_VERSION,
    ObservedResult,
    generate_observed,
)
from dataswamp_biosystems.observed.entities import (
    Category,
    DefectInstance,
    ExpectedFinding,
    ExpectedRemediation,
    MutationRecord,
    ObservedMeta,
    Severity,
)
from dataswamp_biosystems.observed.errors import (
    ObservedConfigError,
    ObservedError,
    ObservedIssue,
    ObservedIssueKind,
    ObservedValidationError,
)
from dataswamp_biosystems.observed.inject import (
    InjectionReport,
    TruthImmutabilityError,
    compute_truth_checksums,
    ensure_output_outside_truth,
    inject_defects,
    load_truth_from_disk,
    resolve_truth_dir,
)
from dataswamp_biosystems.observed.profiles import (
    ObservedProfile,
    profile_spec,
    profile_specs,
)
from dataswamp_biosystems.observed.validate import read_observed_meta, validate_observed
from dataswamp_biosystems.observed.writer import write_observed

__all__ = [
    "DEFECTS",
    "DefectDef",
    "defects_in_order",
    "registry_rows",
    "validate_registry",
    "inject_defects",
    "InjectionReport",
    "TruthImmutabilityError",
    "compute_truth_checksums",
    "ensure_output_outside_truth",
    "load_truth_from_disk",
    "resolve_truth_dir",
    "Category",
    "Severity",
    "DefectInstance",
    "MutationRecord",
    "ExpectedFinding",
    "ExpectedRemediation",
    "ObservedMeta",
    "ObservedProfile",
    "profile_spec",
    "profile_specs",
    "OBSERVED_GENERATOR_VERSION",
    "OBSERVED_SCHEMA_VERSION",
    "ObservedResult",
    "generate_observed",
    "read_observed_meta",
    "validate_observed",
    "write_observed",
    "ObservedError",
    "ObservedConfigError",
    "ObservedValidationError",
    "ObservedIssue",
    "ObservedIssueKind",
]
