"""Truth-graph scientific and governance entity models.

Every entity is a frozen, ``extra="forbid"`` Pydantic model carrying a
slug ``id`` and ``synthetic: Literal[True]`` (the whole estate is fictional).
Sizes are integer bytes; dates/timestamps use the canonical-serializing aliases
from :mod:`.fields`. Foreign keys are typed slugs resolved by the truth
validator, not here.

These models are the *shape* of the truth graph. Generation logic lives in
:mod:`.generator`; ordering, allocation, and referential wiring are the
generator's job, keeping these classes free of behaviour.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from dataswamp_biosystems.company.identifiers import Slug, TermId
from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG
from dataswamp_biosystems.truth.fields import IsoDate, UtcDateTime


class SubjectKind(StrEnum):
    """Whether a study subject is a human participant or an experimental model."""

    HUMAN_SUBJECT = "human_subject"
    EXPERIMENTAL_MODEL = "experimental_model"


class RunKind(StrEnum):
    """Discriminator for the two kinds of processing run in ``runs.jsonl``."""

    INSTRUMENT = "instrument"
    PIPELINE = "pipeline"


class RunStatus(StrEnum):
    """Run outcome. The truth graph is fully successful before defects."""

    SUCCEEDED = "succeeded"


class QualityStatus(StrEnum):
    """Quality-check outcome. All truth-graph checks pass."""

    PASS = "pass"


class AssetType(StrEnum):
    """Discriminator for catalogue nodes in ``assets.jsonl``."""

    DATASET = "dataset"
    DATA_PRODUCT = "data_product"


class GovernanceRecordType(StrEnum):
    """Discriminator for the governance evidence records in ``governance.jsonl``."""

    GOVERNANCE = "governance"
    INTENDED_USE = "intended_use"
    MODEL_TRAINING_APPROVAL = "model_training_approval"


class EdgeType(StrEnum):
    """The kind of relationship a lineage edge represents (upstream → downstream)."""

    COLLECTED_FROM = "collected_from"
    ASSAYED_FROM = "assayed_from"
    PROFILED_BY = "profiled_by"
    PROCESSED_BY = "processed_by"
    PRODUCED = "produced"
    DERIVED_FROM = "derived_from"
    AGGREGATED_INTO = "aggregated_into"


class SyntheticEntity(BaseModel):
    """Base for every truth-graph entity: a slug id and the synthetic flag."""

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    synthetic: Literal[True] = True


class Subject(SyntheticEntity):
    """A study subject: a fictional human participant or an experimental model."""

    kind: SubjectKind
    study_id: Slug
    programme_id: Slug
    subject_code: str = Field(min_length=1)
    origin_date: IsoDate
    # Experimental-model-only descriptors; null for human subjects.
    model_system: str | None = None
    cell_line: str | None = None
    perturbation_library: str | None = None

    @model_validator(mode="after")
    def _kind_coherence(self) -> Subject:
        is_model = self.kind is SubjectKind.EXPERIMENTAL_MODEL
        if is_model and (self.model_system is None or self.cell_line is None):
            raise ValueError("experimental_model subjects require model_system and cell_line")
        if not is_model and any(
            value is not None
            for value in (self.model_system, self.cell_line, self.perturbation_library)
        ):
            raise ValueError("human_subject subjects must not set model-only fields")
        return self


class Biospecimen(SyntheticEntity):
    """A specimen collected from a subject."""

    subject_id: Slug
    study_id: Slug
    specimen_type: str = Field(min_length=1)
    collected_on: IsoDate
    preservation: str = Field(min_length=1)


class Assay(SyntheticEntity):
    """A measurement performed on a biospecimen for one modality."""

    biospecimen_id: Slug
    study_id: Slug
    modality: TermId
    platform: str = Field(min_length=1)
    assayed_on: IsoDate


class InstrumentRun(SyntheticEntity):
    """A raw acquisition run on an instrument, producing primary output."""

    run_kind: Literal[RunKind.INSTRUMENT] = RunKind.INSTRUMENT
    assay_id: Slug
    instrument_model: str = Field(min_length=1)
    run_status: RunStatus = RunStatus.SUCCEEDED
    started_at: UtcDateTime
    completed_at: UtcDateTime


class PipelineRun(SyntheticEntity):
    """A processing run transforming upstream runs/files into derived output."""

    run_kind: Literal[RunKind.PIPELINE] = RunKind.PIPELINE
    pipeline_name: str = Field(min_length=1)
    pipeline_version: str = Field(min_length=1)
    input_ids: list[Slug] = Field(min_length=1)
    run_status: RunStatus = RunStatus.SUCCEEDED
    started_at: UtcDateTime
    completed_at: UtcDateTime


class PhysicalFileRecord(SyntheticEntity):
    """A record of one physical file belonging to a dataset.

    ``checksum`` is a deterministic digest of the file's *metadata*, not of any
    file contents — no scientific bytes exist at this milestone.
    """

    producing_run_id: Slug
    dataset_id: Slug
    relative_path: str = Field(min_length=1)
    file_format: str = Field(min_length=1)
    physical_bytes: int = Field(ge=0)
    checksum: str = Field(min_length=1)


class CatalogueAsset(SyntheticEntity):
    """Fields common to every catalogue-level asset (dataset or data product).

    A catalogue entry is self-describing: it carries its own title, description,
    programme/study placement, scientific classification, lifecycle, version, and
    denormalised governance summary (owner, stewards, classification, retention,
    intended uses, training-approval status, contract reference, and expected
    quality status). The authoritative governance *evidence* also exists as
    separate records (GovernanceRecord, DataContract, QualityCheck, …); the
    validator checks the two agree. ``generator_version`` and ``generation_seed``
    are stamped on every asset for provenance.
    """

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    programme_id: Slug
    study_id: Slug
    scientific_domain: TermId
    modality: TermId
    modality_group: str = Field(min_length=1)
    lifecycle_stage: TermId
    version: str = Field(min_length=1)
    owner_ref: Slug
    steward_refs: list[Slug] = Field(min_length=1)
    access_classification: TermId
    retention_class: TermId
    intended_uses: list[TermId] = Field(min_length=1)
    model_training_status: TermId
    contract_ref: Slug
    quality_status: QualityStatus = QualityStatus.PASS
    generator_version: str = Field(min_length=1)
    generation_seed: int = Field(ge=0)


class Dataset(CatalogueAsset):
    """A catalogue-level dataset: a versioned, governed collection of files."""

    asset_type: Literal[AssetType.DATASET] = AssetType.DATASET
    physical_bytes: int = Field(ge=0)
    logical_bytes: int = Field(ge=0)
    record_count: int = Field(ge=0)
    file_ids: list[Slug] = Field(min_length=1)
    provenance_run_id: Slug
    modality_metadata: dict[str, str | int] = Field(default_factory=dict)
    # Reference/manifest/supporting datasets are cross-modal by nature; they take
    # a representative modality and a primary study for catalogue completeness,
    # and are flagged here so modality-count targets can exclude them.
    is_reference: bool = False


class DataProduct(CatalogueAsset):
    """A curated multimodal product composed of several datasets."""

    asset_type: Literal[AssetType.DATA_PRODUCT] = AssetType.DATA_PRODUCT
    component_dataset_ids: list[Slug] = Field(min_length=1)


class DataContract(SyntheticEntity):
    """A contract describing the schema, SLA, and quality expectations of an asset."""

    asset_id: Slug
    contract_version: str = Field(min_length=1)
    schema_ref: str = Field(min_length=1)
    sla: str = Field(min_length=1)
    quality_expectations: list[str] = Field(min_length=1)


class QualityCheck(SyntheticEntity):
    """A quality-check result for a catalogue asset. All truth checks pass."""

    asset_id: Slug
    check_type: str = Field(min_length=1)
    status: QualityStatus = QualityStatus.PASS
    evidence: str = Field(min_length=1)
    evaluated_at: UtcDateTime


class GovernanceRecord(SyntheticEntity):
    """Ownership, stewardship, and classification evidence for an asset."""

    record_type: Literal[GovernanceRecordType.GOVERNANCE] = GovernanceRecordType.GOVERNANCE
    asset_id: Slug
    owner_ref: Slug
    steward_refs: list[Slug] = Field(min_length=1)
    access_classification: TermId
    retention_class: TermId
    reviewed_at: UtcDateTime


class IntendedUseRecord(SyntheticEntity):
    """An intended-use decision for an asset."""

    record_type: Literal[GovernanceRecordType.INTENDED_USE] = GovernanceRecordType.INTENDED_USE
    asset_id: Slug
    intended_use: TermId
    approved: bool
    decided_at: UtcDateTime


class ModelTrainingApproval(SyntheticEntity):
    """A model-training approval decision for an asset."""

    record_type: Literal[GovernanceRecordType.MODEL_TRAINING_APPROVAL] = (
        GovernanceRecordType.MODEL_TRAINING_APPROVAL
    )
    asset_id: Slug
    status: TermId
    approver_ref: Slug
    decided_at: UtcDateTime
    conditions: str = ""


class LineageEdge(SyntheticEntity):
    """A directed lineage edge from an upstream entity to a downstream one."""

    upstream_id: Slug
    downstream_id: Slug
    edge_type: EdgeType


__all__ = [
    "SubjectKind",
    "RunKind",
    "RunStatus",
    "QualityStatus",
    "AssetType",
    "GovernanceRecordType",
    "EdgeType",
    "SyntheticEntity",
    "Subject",
    "Biospecimen",
    "Assay",
    "InstrumentRun",
    "PipelineRun",
    "PhysicalFileRecord",
    "CatalogueAsset",
    "Dataset",
    "DataProduct",
    "DataContract",
    "QualityCheck",
    "GovernanceRecord",
    "IntendedUseRecord",
    "ModelTrainingApproval",
    "LineageEdge",
]
