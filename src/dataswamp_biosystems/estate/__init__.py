"""Deterministic scientific-file (estate) generation for Data Swamp Biosystems.

The estate is a downstream *consumer* of the truth graph: it materializes small,
genuinely-structured, representative scientific files for the assets the truth
graph declares, plus explicitly-declared placeholders for heavy binaries. It
never mutates the truth graph and never depends on any catalogue tool.

Generation is seeded and deterministic: the same truth graph, profile, generator
version, and seed produce byte-identical files and manifest. Output lives
(git-ignored) under ``generated/estate/``. See ``docs/file-generation.md``.
"""

from __future__ import annotations

from dataswamp_biosystems.estate.entities import (
    CHECKSUM_ALGORITHM,
    EstateMeta,
    FileManifestRecord,
    PlaceholderSidecar,
)
from dataswamp_biosystems.estate.errors import (
    EstateConfigError,
    EstateError,
    EstateIssue,
    EstateIssueKind,
    EstateValidationError,
)
from dataswamp_biosystems.estate.generator import (
    ESTATE_GENERATOR_VERSION,
    ESTATE_SCHEMA_VERSION,
    iter_file_plans,
    iter_records,
)
from dataswamp_biosystems.estate.profiles import Profile, profile_spec, profile_specs
from dataswamp_biosystems.estate.validate import (
    load_manifest_records,
    read_estate_meta,
    validate_estate,
)
from dataswamp_biosystems.estate.writer import write_estate

__all__ = [
    "CHECKSUM_ALGORITHM",
    "EstateMeta",
    "FileManifestRecord",
    "PlaceholderSidecar",
    "EstateError",
    "EstateConfigError",
    "EstateValidationError",
    "EstateIssue",
    "EstateIssueKind",
    "ESTATE_GENERATOR_VERSION",
    "ESTATE_SCHEMA_VERSION",
    "Profile",
    "profile_spec",
    "profile_specs",
    "iter_file_plans",
    "iter_records",
    "write_estate",
    "validate_estate",
    "read_estate_meta",
    "load_manifest_records",
]
