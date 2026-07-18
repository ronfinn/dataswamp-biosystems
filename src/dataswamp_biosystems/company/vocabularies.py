"""Controlled-vocabulary term models.

Every controlled value used by the business entities (access classifications,
retention classes, scientific domains, modalities, lifecycle stages, intended
uses, model-training approval statuses, plus the supporting role and
stewardship-type vocabularies) is defined once here and referenced by ``id``
elsewhere. Terms are validated on load; entity fields that name a term are
checked against the loaded vocabulary by the loader.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dataswamp_biosystems.company.identifiers import TermId

# Shared model configuration for every canonical model: immutable (supports
# deterministic reuse) and strict about unknown keys (never silently drop
# invalid fields).
STRICT_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid")


class VocabularyTerm(BaseModel):
    """Base controlled-vocabulary term: a stable id plus human-facing labels."""

    model_config = STRICT_MODEL_CONFIG

    id: TermId
    label: str = Field(min_length=1)
    description: str = ""


class AccessClassificationTerm(VocabularyTerm):
    """An access/sensitivity classification with an ordinal for comparison."""

    sensitivity_level: int = Field(ge=0)


class RetentionClassTerm(VocabularyTerm):
    """A retention class. ``duration`` is an ISO-8601 period, or null for permanent."""

    duration: str | None = None


class ScientificDomainTerm(VocabularyTerm):
    """A scientific/analytical domain (genomics, imaging, clinical, …)."""


class ModalityTerm(VocabularyTerm):
    """A data modality, tied to the scientific domain it belongs to.

    ``scientific_domain`` is an intra-vocabulary reference validated by the
    loader against the scientific-domains vocabulary.
    """

    scientific_domain: TermId


class LifecycleStageTerm(VocabularyTerm):
    """A data-lifecycle stage with an explicit ordering position."""

    order: int = Field(ge=0)


class IntendedUseTerm(VocabularyTerm):
    """An intended-use classification for data assets."""


class TrainingApprovalStatusTerm(VocabularyTerm):
    """A model-training approval status."""


class RoleTerm(VocabularyTerm):
    """An organisational role a person may hold."""


class StewardshipTypeTerm(VocabularyTerm):
    """A kind of stewardship relationship (data, quality, access …)."""


__all__ = [
    "STRICT_MODEL_CONFIG",
    "VocabularyTerm",
    "AccessClassificationTerm",
    "RetentionClassTerm",
    "ScientificDomainTerm",
    "ModalityTerm",
    "LifecycleStageTerm",
    "IntendedUseTerm",
    "TrainingApprovalStatusTerm",
    "RoleTerm",
    "StewardshipTypeTerm",
]
