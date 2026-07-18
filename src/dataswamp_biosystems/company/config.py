"""The assembled, validated canonical configuration.

:class:`CanonicalConfig` is the whole company model in one immutable object,
suitable for JSON/YAML round-tripping and for future generators to consume.
The loader builds it and runs cross-file validation; construction here does
per-model field validation only.
"""

from __future__ import annotations

from pydantic import BaseModel

from dataswamp_biosystems.company.entities import (
    Company,
    Person,
    Programme,
    Study,
    Team,
)
from dataswamp_biosystems.company.generation import GenerationConfig
from dataswamp_biosystems.company.relationships import (
    OwnershipAssignment,
    StewardshipAssignment,
)
from dataswamp_biosystems.company.vocabularies import (
    STRICT_MODEL_CONFIG,
    AccessClassificationTerm,
    IntendedUseTerm,
    LifecycleStageTerm,
    ModalityTerm,
    RetentionClassTerm,
    RoleTerm,
    ScientificDomainTerm,
    StewardshipTypeTerm,
    TrainingApprovalStatusTerm,
)

# Bumped when the on-disk configuration schema changes incompatibly. Every
# config file also carries its own ``schema_version``; the loader checks both.
SCHEMA_VERSION = 1


class Vocabularies(BaseModel):
    """All controlled vocabularies, grouped for convenient reference resolution."""

    model_config = STRICT_MODEL_CONFIG

    access_classifications: list[AccessClassificationTerm]
    retention_classes: list[RetentionClassTerm]
    scientific_domains: list[ScientificDomainTerm]
    modalities: list[ModalityTerm]
    lifecycle_stages: list[LifecycleStageTerm]
    intended_uses: list[IntendedUseTerm]
    training_approval_statuses: list[TrainingApprovalStatusTerm]
    stewardship_types: list[StewardshipTypeTerm]

    def term_count(self) -> int:
        """Total number of controlled-vocabulary terms across all vocabularies."""
        return (
            len(self.access_classifications)
            + len(self.retention_classes)
            + len(self.scientific_domains)
            + len(self.modalities)
            + len(self.lifecycle_stages)
            + len(self.intended_uses)
            + len(self.training_approval_statuses)
            + len(self.stewardship_types)
        )


class CanonicalConfig(BaseModel):
    """The complete, validated canonical company model."""

    model_config = STRICT_MODEL_CONFIG

    schema_version: int
    company: Company
    programmes: list[Programme]
    studies: list[Study]
    teams: list[Team]
    people: list[Person]
    roles: list[RoleTerm]
    ownership: list[OwnershipAssignment]
    stewardship: list[StewardshipAssignment]
    vocabularies: Vocabularies
    generation: GenerationConfig

    def entity_counts(self) -> dict[str, int]:
        """Return entity counts in a deterministic, presentation-ready order."""
        return {
            "programmes": len(self.programmes),
            "studies": len(self.studies),
            "teams": len(self.teams),
            "people": len(self.people),
            "roles": len(self.roles),
            "ownership_assignments": len(self.ownership),
            "stewardship_assignments": len(self.stewardship),
            "vocabulary_terms": self.vocabularies.term_count(),
        }


__all__ = ["SCHEMA_VERSION", "Vocabularies", "CanonicalConfig"]
