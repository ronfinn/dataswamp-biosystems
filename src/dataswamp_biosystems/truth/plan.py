"""The deterministic generation plan: config models, loader, and allocation.

The plan (``config/truth/generation-plan.yaml``) declares exact target counts.
This module loads and type-validates it, cross-checks it against the canonical
company model, and provides the deterministic count-allocation math the
generator uses to turn totals into per-study dataset counts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from dataswamp_biosystems.company.config import CanonicalConfig
from dataswamp_biosystems.company.identifiers import Slug, TermId
from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG
from dataswamp_biosystems.truth.entities import SubjectKind
from dataswamp_biosystems.truth.errors import (
    TruthConfigError,
    TruthIssueCollector,
    TruthIssueKind,
)

# Location of the plan relative to a config directory.
PLAN_RELATIVE_PATH = Path("truth") / "generation-plan.yaml"
PLAN_SCHEMA_VERSION = 1


class ModalityGroup(BaseModel):
    """A modality family with a target dataset count spread across studies."""

    model_config = STRICT_MODEL_CONFIG

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    modalities: list[TermId] = Field(min_length=1)
    dataset_count: int = Field(ge=0)
    subject_kind: SubjectKind
    studies: list[Slug] = Field(min_length=1)


class GenerationPlan(BaseModel):
    """The full, type-validated generation plan."""

    model_config = STRICT_MODEL_CONFIG

    generator_version: str = Field(min_length=1)
    epoch_anchor: date
    subjects_per_study: int = Field(ge=1)
    reference_dataset_count: int = Field(ge=0)
    data_product_count: int = Field(ge=0)
    modality_groups: list[ModalityGroup] = Field(min_length=1)

    def total_modality_datasets(self) -> int:
        return sum(group.dataset_count for group in self.modality_groups)

    def total_datasets(self) -> int:
        return self.total_modality_datasets() + self.reference_dataset_count

    def total_catalogue_assets(self) -> int:
        return self.total_datasets() + self.data_product_count


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise TruthConfigError(f"missing generation plan: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - message content only
        raise TruthConfigError(f"could not parse {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise TruthConfigError(f"expected a top-level mapping in {path}")
    return dict(raw)


def load_generation_plan(config_dir: Path | str) -> GenerationPlan:
    """Load and type-validate the generation plan from ``config_dir``.

    Raises:
        TruthConfigError: the file is missing, malformed, wrong schema version,
            or fails field validation.
    """
    path = Path(config_dir) / PLAN_RELATIVE_PATH
    doc = _read_mapping(path)
    if doc.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise TruthConfigError(
            f"generation plan schema_version must be {PLAN_SCHEMA_VERSION}, "
            f"got {doc.get('schema_version')!r}"
        )
    body = doc.get("generation_plan")
    if not isinstance(body, Mapping):
        raise TruthConfigError(f"missing 'generation_plan' mapping in {path}")
    try:
        return GenerationPlan.model_validate(body)
    except ValidationError as exc:
        raise TruthConfigError(f"invalid generation plan in {path}: {exc}") from exc


def validate_plan_against_config(
    plan: GenerationPlan,
    config: CanonicalConfig,
    issues: TruthIssueCollector,
) -> None:
    """Check that every plan reference resolves against the canonical model.

    Each modality group's studies must exist, and each such study must declare
    at least one of the group's modalities in its own ``modalities`` list, so
    the truth graph stays backed by the hand-authored company model.
    """
    study_modalities: dict[str, set[str]] = {
        study.id: set(study.modalities) for study in config.studies
    }
    known_modalities = {term.id for term in config.vocabularies.modalities}

    for group in plan.modality_groups:
        for modality in group.modalities:
            if modality not in known_modalities:
                issues.add(
                    TruthIssueKind.PLAN,
                    f"modality group {group.id!r} references unknown modality {modality!r}",
                    entity_kind="modality_group",
                    entity_id=group.id,
                    field="modalities",
                )
        for study_id in group.studies:
            declared = study_modalities.get(study_id)
            if declared is None:
                issues.add(
                    TruthIssueKind.PLAN,
                    f"modality group {group.id!r} references unknown study {study_id!r}",
                    entity_kind="modality_group",
                    entity_id=group.id,
                    field="studies",
                )
                continue
            if declared.isdisjoint(group.modalities):
                issues.add(
                    TruthIssueKind.PLAN,
                    f"study {study_id!r} does not declare any modality of group {group.id!r}",
                    entity_kind="modality_group",
                    entity_id=group.id,
                    field="studies",
                )


def even_split(total: int, keys: Sequence[str]) -> dict[str, int]:
    """Distribute ``total`` across ``keys`` as evenly as possible, deterministically.

    Keys are sorted; each gets ``total // n`` and the remainder is assigned one
    each to the lowest-sorted keys first (largest-remainder with equal weights).
    """
    if not keys:
        raise ValueError("cannot split across zero keys")
    ordered = sorted(keys)
    base, remainder = divmod(total, len(ordered))
    return {key: base + (1 if index < remainder else 0) for index, key in enumerate(ordered)}


__all__ = [
    "PLAN_RELATIVE_PATH",
    "PLAN_SCHEMA_VERSION",
    "ModalityGroup",
    "GenerationPlan",
    "load_generation_plan",
    "validate_plan_against_config",
    "even_split",
]
