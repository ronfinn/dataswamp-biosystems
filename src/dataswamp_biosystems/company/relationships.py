"""Ownership and stewardship assignment models.

Relationships are kept in their own files/models (rather than embedded on
entities) so that relationship churn produces clean diffs and reference
validation has a single place to resolve subjects, owners, and stewards.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.identifiers import (
    AssignmentId,
    PersonId,
    Slug,
    TermId,
)
from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG


class SubjectType(StrEnum):
    """The kind of asset or organisational unit an assignment points at."""

    PROGRAMME = "programme"
    STUDY = "study"
    TEAM = "team"


class OwnerType(StrEnum):
    """Whether an owner is a team or an individual person."""

    TEAM = "team"
    PERSON = "person"


class OwnershipAssignment(BaseModel):
    """Assigns accountable ownership of a subject to a team or person."""

    model_config = STRICT_MODEL_CONFIG

    id: AssignmentId
    subject_type: SubjectType
    subject_id: Slug
    owner_type: OwnerType
    owner_id: Slug
    description: str = ""


class StewardshipAssignment(BaseModel):
    """Assigns a typed stewardship responsibility over a subject to a person."""

    model_config = STRICT_MODEL_CONFIG

    id: AssignmentId
    subject_type: SubjectType
    subject_id: Slug
    steward_id: PersonId
    stewardship_type: TermId = Field(min_length=1)
    description: str = ""


__all__ = [
    "SubjectType",
    "OwnerType",
    "OwnershipAssignment",
    "StewardshipAssignment",
]
