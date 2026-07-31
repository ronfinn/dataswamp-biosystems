"""The assembled truth graph and its metadata.

:class:`TruthGraph` is the in-memory container of every generated entity list,
in a fixed field order. :class:`TruthGraphMeta` records the provenance needed to
reproduce and verify a run (generator/schema versions, seed, epoch anchor).
Neither performs generation; they are plain containers the generator fills and
the writer/validator read.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG
from dataswamp_biosystems.truth.entities import (
    Assay,
    Biospecimen,
    DataContract,
    DataProduct,
    Dataset,
    GovernanceRecord,
    InstrumentRun,
    IntendedUseRecord,
    LineageEdge,
    ModelTrainingApproval,
    PhysicalFileRecord,
    PipelineRun,
    QualityCheck,
    Subject,
)

# Bumped when the on-disk truth-graph schema changes incompatibly.
TRUTH_SCHEMA_VERSION = 1


class TruthGraphMeta(BaseModel):
    """Provenance for a generated truth graph."""

    model_config = STRICT_MODEL_CONFIG

    generator_version: str
    schema_version: int
    seed: int
    epoch_anchor: str


class TruthGraph(BaseModel):
    """Every generated entity, grouped by kind in fixed order."""

    model_config = STRICT_MODEL_CONFIG

    meta: TruthGraphMeta
    subjects: list[Subject] = Field(default_factory=list)
    biospecimens: list[Biospecimen] = Field(default_factory=list)
    assays: list[Assay] = Field(default_factory=list)
    instrument_runs: list[InstrumentRun] = Field(default_factory=list)
    pipeline_runs: list[PipelineRun] = Field(default_factory=list)
    files: list[PhysicalFileRecord] = Field(default_factory=list)
    datasets: list[Dataset] = Field(default_factory=list)
    data_products: list[DataProduct] = Field(default_factory=list)
    contracts: list[DataContract] = Field(default_factory=list)
    quality_checks: list[QualityCheck] = Field(default_factory=list)
    governance_records: list[GovernanceRecord] = Field(default_factory=list)
    intended_use_records: list[IntendedUseRecord] = Field(default_factory=list)
    training_approvals: list[ModelTrainingApproval] = Field(default_factory=list)
    lineage: list[LineageEdge] = Field(default_factory=list)

    def entity_counts(self) -> dict[str, int]:
        """Return entity counts in a deterministic, presentation-ready order."""
        return {
            "subjects": len(self.subjects),
            "biospecimens": len(self.biospecimens),
            "assays": len(self.assays),
            "instrument_runs": len(self.instrument_runs),
            "pipeline_runs": len(self.pipeline_runs),
            "files": len(self.files),
            "datasets": len(self.datasets),
            "data_products": len(self.data_products),
            "contracts": len(self.contracts),
            "quality_checks": len(self.quality_checks),
            "governance_records": len(self.governance_records),
            "intended_use_records": len(self.intended_use_records),
            "training_approvals": len(self.training_approvals),
            "lineage_edges": len(self.lineage),
        }


__all__ = ["TRUTH_SCHEMA_VERSION", "TruthGraphMeta", "TruthGraph"]
