"""Typed, validated identifier types for the canonical company model.

Identifiers are lowercase kebab-case ASCII slugs. Each entity family uses a
distinct prefix (``prog-``, ``study-``, ``team-`` …) so that cross-file
references are self-describing and duplicate detection can be
namespace-aware. The types here are thin ``Annotated[str, ...]`` aliases that
apply a shared pattern constraint; they exist to make model signatures
readable, not to encode the prefix rule at the type level (prefix rules are
enforced structurally by the loader where they matter).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

# A slug is lowercase alphanumerics separated by single hyphens, e.g.
# ``prog-nsclc`` or ``study-nsclc-01``. No leading/trailing/double hyphens.
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

Slug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN)]

# Distinct aliases per entity family. They share one constraint today but are
# kept separate so signatures document intent and future milestones can
# tighten individual families without touching call sites.
CompanyId = Slug
ProgrammeId = Slug
StudyId = Slug
TeamId = Slug
PersonId = Slug
RoleId = Slug
TermId = Slug
AssignmentId = Slug

__all__ = [
    "SLUG_PATTERN",
    "Slug",
    "CompanyId",
    "ProgrammeId",
    "StudyId",
    "TeamId",
    "PersonId",
    "RoleId",
    "TermId",
    "AssignmentId",
]
