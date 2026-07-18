"""Pydantic models for the generated file estate: manifest and sidecars.

Every generated file (genuine or placeholder) is described by exactly one
:class:`FileManifestRecord`. Placeholders additionally carry a
:class:`PlaceholderSidecar` written next to the stub so the estate never
presents a stand-in as a valid scientific binary. :class:`EstateMeta` captures
the provenance needed to reproduce and verify a run. All models are frozen,
reject unknown keys, and carry ``synthetic: True``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.identifiers import Slug, TermId
from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG

# The single checksum algorithm used across the estate.
CHECKSUM_ALGORITHM = "sha256"


class FileManifestRecord(BaseModel):
    """One row of ``file-manifest.jsonl`` describing a single generated file."""

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    asset_id: Slug
    relative_path: str = Field(min_length=1)
    modality: TermId
    modality_group: str = Field(min_length=1)
    file_format: str = Field(min_length=1)
    file_role: str = Field(min_length=1)
    mime_type: str | None = None
    physical_bytes: int = Field(ge=0)
    logical_bytes: int = Field(ge=0)
    checksum_algorithm: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    is_placeholder: bool
    generator_version: str = Field(min_length=1)
    generation_seed: int = Field(ge=0)
    synthetic: Literal[True] = True


class PlaceholderSidecar(BaseModel):
    """Sidecar JSON accompanying every placeholder stub file.

    A placeholder is a tiny, unambiguous stand-in for a format too heavy or
    unjustified to generate genuinely (BAM, CRAM, DICOM, SVS, large Zarr). The
    sidecar records exactly what the stub represents so nothing downstream
    mistakes it for a real scientific binary.
    """

    model_config = STRICT_MODEL_CONFIG

    placeholder: Literal[True] = True
    file_id: Slug
    intended_format: str = Field(min_length=1)
    intended_mime_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    represented_logical_bytes: int = Field(ge=0)
    limitations: str = Field(min_length=1)
    source_truth_asset_id: Slug
    modality: TermId
    generation_seed: int = Field(ge=0)
    generator_version: str = Field(min_length=1)
    synthetic: Literal[True] = True


class EstateMeta(BaseModel):
    """Provenance for a generated estate, embedded in ``generation-summary.json``."""

    model_config = STRICT_MODEL_CONFIG

    generator_version: str
    schema_version: int
    seed: int
    profile: str
    epoch_anchor: str
    # Traceability back to the truth graph the estate was derived from.
    truth_generator_version: str
    truth_seed: int
    budget_bytes: int


__all__ = [
    "CHECKSUM_ALGORITHM",
    "FileManifestRecord",
    "PlaceholderSidecar",
    "EstateMeta",
]
