"""Record models and taxonomy enums for the imperfection engine.

The engine derives a deliberately-imperfect *observed* view of the truth graph.
Six ledgers make every injected defect explicit and scorable: the defect
instances, the field-level mutations (with before/after values), the expected
findings, the expected remediations, the control partition (every entity that
carries no defect — the benchmark's negative class), and the per-rule selection
scope. Every model is frozen, rejects unknown keys, and carries
``synthetic: True``.

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


class RemediationAvailability(StrEnum):
    """Whether — and how — a defect can be remediated.

    This is the *capability* dimension and is deliberately independent of
    :class:`ApprovalPolicy`, which is the *authority* dimension. A change can be
    mechanically derivable yet still require sign-off (correcting an access
    classification), and it can need no sign-off yet be impossible to automate
    (writing a missing description).
    """

    AUTOMATIC = "automatic"  # the correct value is mechanically derivable
    MANUAL = "manual"  # a human must supply or decide the correct value
    NONE = "none"  # nothing can be remediated from available information


class ApprovalPolicy(StrEnum):
    """Whether remediating a defect requires human authorisation."""

    NOT_REQUIRED = "not-required"
    REQUIRED = "required"


class ApproverRole(StrEnum):
    """Who may authorise a remediation.

    The stewardship values mirror ``config/vocabularies/stewardship-types.yaml``;
    ``data-owner`` is the owning team recorded on the asset itself.
    """

    NONE = "none"
    DATA_STEWARD = "data-steward"
    QUALITY_STEWARD = "quality-steward"
    ACCESS_STEWARD = "access-steward"
    DATA_OWNER = "data-owner"


class ApprovalEvidence(StrEnum):
    """The artefact an approval must produce to be auditable."""

    NONE = "none"
    STEWARD_SIGN_OFF = "steward-sign-off"
    OWNER_SIGN_OFF = "owner-sign-off"
    ACCESS_REVIEW_RECORD = "access-review-record"
    QUALITY_REVIEW_RECORD = "quality-review-record"
    TRAINING_APPROVAL_RECORD = "training-approval-record"


class NonRemediableReason(StrEnum):
    """Why a defect cannot be remediated from the information available.

    Only meaningful when availability is :attr:`RemediationAvailability.NONE`.
    """

    NONE = "none"
    SOURCE_SYSTEM_RECOVERY = "source-system-recovery-required"
    UPSTREAM_REPROCESSING = "upstream-reprocessing-required"


# The action recorded when a finding is deliberately non-remediable. It is an
# explicit *no-action decision*, not a hollow fix: an agent that proposes a
# repair here is wrong, and an agent that abstains is right.
NO_REMEDIATION_ACTION = "no-remediation"


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
    remediation_availability: RemediationAvailability
    approval_policy: ApprovalPolicy
    approver_role: ApproverRole = ApproverRole.NONE
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
    remediation_available: RemediationAvailability
    non_remediable_reason: NonRemediableReason = NonRemediableReason.NONE
    remediation_id: Slug
    match_fields: dict[str, Any] = Field(default_factory=dict)
    expected_status: Literal["present"] = "present"
    synthetic: Literal[True] = True


class ControlReason(StrEnum):
    """Why an entity belongs to the clean (control) partition.

    The first two reasons describe the *reserved* partition — assets the profile
    holds out before selection, so no rule may ever draw them. The last two
    describe entities that were exposed to selection (or to no rule at all) and
    nevertheless carry no defect.
    """

    RESERVED_ASSET = "reserved-control-asset"
    MEMBER_OF_RESERVED_ASSET = "member-of-reserved-control-asset"
    ELIGIBLE_UNSELECTED = "eligible-unselected"
    NEVER_ELIGIBLE = "never-eligible"


class ControlRecord(BaseModel):
    """One catalogue asset or file that carries no injected defect.

    Together the control records are the benchmark's *negative* class: every
    entity an assessment agent should leave unflagged. ``reserved`` marks the
    strict held-out partition (excluded from every rule's eligible population
    before selection); the other controls were eligible or out of scope and
    simply not drawn. ``eligible_rule_count`` says how many rules had this entity
    in their eligible population, so a specificity denominator can be scoped per
    rule via ``rule-scope.jsonl``.
    """

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    entity_kind: str = Field(min_length=1)
    shard: str = Field(min_length=1)
    reason: ControlReason
    reserved: bool
    parent_asset_id: str = ""
    modality: str = ""
    modality_group: str = ""
    eligible_rule_count: int = Field(ge=0)
    profile: str = Field(min_length=1)
    defect_seed: int = Field(ge=0)
    truth_seed: int = Field(ge=0)
    control_fraction: float = Field(ge=0.0, le=1.0)
    expected_status: Literal["clean"] = "clean"
    synthetic: Literal[True] = True


class RuleScopeRecord(BaseModel):
    """The selection scope of one defect rule, as machine-readable counts and ids.

    Emitted for every rule in the registry — including rules that fired zero
    times — so an evaluator can scope precision and recall per rule without
    parsing any human-readable ``selection_rationale`` prose.
    The record ``id`` *is* the rule id, so a scope row joins directly to a
    defect instance's ``rule_id``. The population splits exactly into
    ``eligible_ids`` and
    ``control_excluded_ids``; ``selected_ids`` are the entities actually mutated
    and always match the rule's defect instances.
    """

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)
    category: Category
    severity: Severity
    profile: str = Field(min_length=1)
    defect_seed: int = Field(ge=0)
    injection_rate: float = Field(ge=0.0, le=1.0)
    population_count: int = Field(ge=0)
    control_excluded_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    eligible_ids: list[str] = Field(default_factory=list)
    control_excluded_ids: list[str] = Field(default_factory=list)
    selected_ids: list[str] = Field(default_factory=list)
    synthetic: Literal[True] = True


class ExpectedRemediation(BaseModel):
    """The remediation expected to resolve one finding (metadata only; never applied)."""

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    finding_id: Slug
    instance_id: Slug
    rule_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    action_class: str = Field(min_length=1)
    target: str = Field(min_length=1)
    recommended_value: Any = None
    truth_reference: Any = None
    availability: RemediationAvailability
    approval_policy: ApprovalPolicy
    approver_role: ApproverRole = ApproverRole.NONE
    approval_evidence: ApprovalEvidence = ApprovalEvidence.NONE
    non_remediable_reason: NonRemediableReason = NonRemediableReason.NONE
    # Retained so existing readers keep working; both are derived from the two
    # independent dimensions above and are validated against them.
    auto_fixable: bool
    requires_human_approval: bool
    reversible: bool
    synthetic: Literal[True] = True


__all__ = [
    "Category",
    "Severity",
    "SEVERITY_RANK",
    "Multiplicity",
    "RemediationAvailability",
    "ApprovalPolicy",
    "ApproverRole",
    "ApprovalEvidence",
    "NonRemediableReason",
    "NO_REMEDIATION_ACTION",
    "ChangeOp",
    "ObservedMeta",
    "DefectInstance",
    "MutationRecord",
    "ControlReason",
    "ControlRecord",
    "RuleScopeRecord",
    "ExpectedFinding",
    "ExpectedRemediation",
]
