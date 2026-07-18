"""Record models and taxonomy enums for the imperfection engine.

The engine derives a deliberately-imperfect *observed* view of the truth graph.
Four ledgers make every injected defect explicit and scorable: the defect
instances, the field-level mutations (with before/after values), the expected
findings, and the expected remediations. Every model is frozen, rejects unknown
keys, and carries ``synthetic: True``.

The observed graph itself is *not* modelled here: it is deliberately a relaxed
collection of JSON objects (the truth entities' ``model_dump`` with mutations
applied) so that defects can express states the strict truth models forbid — an
empty owner, an invalid vocabulary term, an inverted size, a dangling reference.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.identifiers import Slug
from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG


class Category(StrEnum):
    """The twelve defect categories in the initial taxonomy."""

    METADATA_COMPLETENESS = "metadata-completeness"
    SEMANTIC_QUALITY = "semantic-quality"
    OWNERSHIP = "ownership-stewardship"
    NAMING_VERSIONING = "naming-versioning"
    GOVERNANCE_CLASSIFICATION = "governance-classification"
    LICENSING_INTENDED_USE = "licensing-intended-use"
    LINEAGE_PROVENANCE = "lineage-provenance"
    SCHEMA_STRUCTURAL = "schema-structural"
    MODALITY_SCIENTIFIC = "modality-scientific"
    AI_TRAINING_READINESS = "ai-training-readiness"
    LIFECYCLE_STALENESS = "lifecycle-staleness"
    FILE_INTEGRITY = "file-integrity"


class Severity(StrEnum):
    """Default severity of a defect type."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Sort rank so findings can be ordered most-severe first, deterministically.
SEVERITY_RANK: dict[str, int] = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


class Multiplicity(StrEnum):
    """How many times a rule may apply to one primary entity."""

    PER_ENTITY = "per_entity"  # at most once per entity
    PER_FIELD = "per_field"  # at most once per (entity, field)
    GLOBAL = "global"  # bounded only by the global cap


class ChangeOp(StrEnum):
    """How a single mutation is applied to the observed working graph."""

    SET = "set"  # set a scalar/object field at ``path`` to ``after``
    SET_LIST = "set_list"  # replace a list-valued field
    DELETE_RECORD = "delete_record"  # remove a whole record from its shard
    ADD_RECORD = "add_record"  # append a fabricated record to a shard


class ObservedMeta(BaseModel):
    """Provenance for a generated observed estate."""

    model_config = STRICT_MODEL_CONFIG

    generator_version: str
    schema_version: int
    defect_seed: int
    profile: str
    truth_generator_version: str
    truth_seed: int
    epoch_anchor: str


class DefectInstance(BaseModel):
    """One applied defect: the anchor every mutation/finding/remediation links to."""

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    rule_id: str = Field(min_length=1)
    category: Category
    severity: Severity
    entity_kind: str = Field(min_length=1)
    entity_id: Slug
    modality: str = ""
    target_fields: list[str] = Field(default_factory=list)
    profile: str = Field(min_length=1)
    defect_seed: int = Field(ge=0)
    truth_seed: int = Field(ge=0)
    mutation_ids: list[Slug] = Field(min_length=1)
    finding_id: Slug
    remediation_ids: list[Slug] = Field(min_length=1)
    synthetic: Literal[True] = True


class MutationRecord(BaseModel):
    """One field-level change, carrying the truth ``before`` and observed ``after``.

    A mutation is self-describing for a future evaluator: it names the defect
    instance and rule, the affected entity and its type, the JSON-pointer field
    path or relationship target, the previous canonical value (preserved even for
    deletions and missing-value defects) and the new value, plus the severity,
    seed, profile, selection rationale, fix eligibility, approval requirement, and
    whether the defect is metadata-only or physically manifested. No wall-clock
    timestamp is recorded (determinism); provenance is the seed and profile.
    """

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    instance_id: Slug
    rule_id: str = Field(min_length=1)
    shard: str = Field(min_length=1)
    entity_kind: str = Field(min_length=1)
    entity_id: Slug
    operation: ChangeOp
    path: str
    field: str = ""
    before: Any = None
    after: Any = None
    severity: Severity
    seed: int = Field(ge=0)
    profile: str = Field(min_length=1)
    selection_rationale: str = Field(min_length=1)
    auto_fixable: bool
    requires_human_approval: bool
    reversible: bool
    manifestation: Literal["metadata", "physical"] = "metadata"
    synthetic: Literal[True] = True


class ExpectedFinding(BaseModel):
    """The finding a governance agent is expected to raise for one defect.

    Structured so a future evaluator can grant credit on *semantics*, not exact
    prose: ``match_fields`` holds the machine-matchable keys (rule, entity,
    category, severity, target fields), ``observable_evidence`` states what is
    visible in the observed graph, ``expected_message_semantics`` states what the
    finding must communicate, and ``remediation_id`` links the expected fix.
    """

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    instance_id: Slug
    rule_id: str = Field(min_length=1)
    category: Category
    severity: Severity
    entity_kind: str = Field(min_length=1)
    entity_id: Slug
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    observable_evidence: str = Field(min_length=1)
    expected_message_semantics: str = Field(min_length=1)
    detection_locator: str = Field(min_length=1)
    remediation_id: Slug
    match_fields: dict[str, Any] = Field(default_factory=dict)
    expected_status: Literal["present"] = "present"
    synthetic: Literal[True] = True


class ExpectedRemediation(BaseModel):
    """The remediation expected to resolve one finding (metadata only; never applied)."""

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    finding_id: Slug
    instance_id: Slug
    rule_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    target: str = Field(min_length=1)
    recommended_value: Any = None
    truth_reference: Any = None
    auto_fixable: bool
    requires_human_approval: bool
    reversible: bool
    synthetic: Literal[True] = True


__all__ = [
    "Category",
    "Severity",
    "SEVERITY_RANK",
    "Multiplicity",
    "ChangeOp",
    "ObservedMeta",
    "DefectInstance",
    "MutationRecord",
    "ExpectedFinding",
    "ExpectedRemediation",
]
