"""A deterministic DataHub metadata adapter for benchmark bundles.

The adapter maps DataSwamp catalogue entities onto DataHub entities and aspects
and emits Metadata Change Proposals — the payload DataHub's own ``file`` source
ingests. It is deliberately **schema-emitting rather than SDK-backed**: DataHub's
Python SDK (``acryl-datahub``) is a large dependency tree whose only role here
would be to serialise a few dozen well-documented aspect payloads. Emitting them
directly keeps the core package free of any catalogue dependency, keeps the whole
adapter testable with no server and no network, and leaves a user free to install
whichever DataHub client their instance requires.

The targeted metadata model is recorded as
:data:`~dataswamp_biosystems.adapters.datahub.mapping.DATAHUB_MODEL_VERSION`, and
the emitted payloads are pinned by committed fixtures so a mapping change cannot
pass unnoticed.

See ``docs/datahub.md``.
"""

from __future__ import annotations

from dataswamp_biosystems.adapters.datahub.export import (
    EXPORT_MANIFEST_NAME,
    MCPS_JSON_NAME,
    MCPS_JSONL_NAME,
    RECIPE_NAME,
    build_source,
    export_datahub,
)
from dataswamp_biosystems.adapters.datahub.mapping import (
    ADAPTER_VERSION,
    DATAHUB_MODEL_VERSION,
    TAG_PRIVILEGED,
    TAG_SYNTHETIC,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
    SourceGraph,
    build_mcps,
)
from dataswamp_biosystems.adapters.datahub.validate import (
    ASSET_REQUIRED_ASPECTS,
    REQUIRED_ASPECTS,
    URN_PATTERNS,
    validate_export,
)

__all__ = [
    "ADAPTER_VERSION",
    "DATAHUB_MODEL_VERSION",
    "ExportMode",
    "SourceGraph",
    "build_mcps",
    "build_source",
    "export_datahub",
    "validate_export",
    "URN_PATTERNS",
    "REQUIRED_ASPECTS",
    "ASSET_REQUIRED_ASPECTS",
    "TAG_PRIVILEGED",
    "TAG_SYNTHETIC",
    "TRUTH_ONLY_PROPERTY_PREFIX",
    "MCPS_JSONL_NAME",
    "MCPS_JSON_NAME",
    "EXPORT_MANIFEST_NAME",
    "RECIPE_NAME",
]
