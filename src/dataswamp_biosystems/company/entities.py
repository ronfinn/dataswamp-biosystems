"""Core business entities: Company, Programme, Study, Team, Person.

Field-level validation (id patterns, required fields, email format and the
``dataswamp.example`` domain lock, list non-emptiness) lives here. Cross-file
reference resolution and controlled-value checks are performed by the loader,
because they need the whole configuration in hand.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field

from dataswamp_biosystems.company.identifiers import (
    CompanyId,
    PersonId,
    ProgrammeId,
    RoleId,
    StudyId,
    TeamId,
    TermId,
)
from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG

# The only permitted domain for every fictional identity in this repository.
FICTIONAL_DOMAIN = "dataswamp.example"


class TeamType(StrEnum):
    """The kind of organisational unit a team represents."""

    SCIENTIFIC = "scientific"
    PLATFORM = "platform"
    GOVERNANCE = "governance"


class Company(BaseModel):
    """The single fictional company the estate belongs to."""

    model_config = STRICT_MODEL_CONFIG

    id: CompanyId
    legal_name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    domain: str
    description: str = ""
    headquarters: str = ""


class Programme(BaseModel):
    """A research programme aligned to one oncology indication."""

    model_config = STRICT_MODEL_CONFIG

    id: ProgrammeId
    display_name: str = Field(min_length=1)
    indication: str = Field(min_length=1)
    description: str = ""
    # Optional programme-level defaults; validated against vocabularies by the loader.
    default_access_classification: TermId | None = None
    default_retention_class: TermId | None = None


class Study(BaseModel):
    """A study belonging to exactly one programme.

    All vocabulary-typed fields carry term ids that the loader resolves
    against the controlled vocabularies.
    """

    model_config = STRICT_MODEL_CONFIG

    id: StudyId
    programme_id: ProgrammeId
    display_name: str = Field(min_length=1)
    description: str = ""
    scientific_domains: list[TermId] = Field(min_length=1)
    modalities: list[TermId] = Field(min_length=1)
    access_classification: TermId
    retention_class: TermId
    lifecycle_stage: TermId
    intended_uses: list[TermId] = Field(min_length=1)
    model_training_approval: TermId


class Team(BaseModel):
    """A scientific, platform, or governance team.

    Scientific teams are aligned to a programme (``programme_id`` required);
    platform and governance teams are cross-programme (``programme_id`` must be
    null). This structural rule is enforced by the loader.
    """

    model_config = STRICT_MODEL_CONFIG

    id: TeamId
    display_name: str = Field(min_length=1)
    team_type: TeamType
    programme_id: ProgrammeId | None = None
    description: str = ""


class Person(BaseModel):
    """A fictional member of staff, with a role and a primary team."""

    model_config = STRICT_MODEL_CONFIG

    id: PersonId
    full_name: str = Field(min_length=1)
    email: EmailStr
    role: RoleId
    team_id: TeamId


__all__ = [
    "FICTIONAL_DOMAIN",
    "TeamType",
    "Company",
    "Programme",
    "Study",
    "Team",
    "Person",
]
