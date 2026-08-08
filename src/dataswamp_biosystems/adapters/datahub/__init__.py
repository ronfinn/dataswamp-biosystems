"""A deterministic DataHub metadata adapter for benchmark bundles.

The adapter maps DataSwamp catalogue entities onto DataHub entities and aspects
and emits Metadata Change Proposals — the payload DataHub's own ``file`` source
ingests. It is deliberately **schema-emitting rather than SDK-backed**: DataHub's
Python SDK (``acryl-datahub``) is a large dependency tree whose only role here
would be to serialise a few dozen well-documented aspect payloads. Emitting them
directly keeps the core package free of any catalogue dependency, keeps the whole
adapter testable with no server and no network, and leaves a user free to install
whichever DataHub client their instance requires.

A **live path** sits strictly downstream of that emitted export::

    bundle -> export-datahub -> emitted export -> ingest-datahub -> verify-ingestion

``ingest.py`` transmits an emitted export verbatim, ``readback.py`` reads the
catalogue's state back, and ``roundtrip.py`` compares the two as a pure function
— reporting completeness, fidelity, containment and observed-mode non-leakage
separately. Every socket and every endpoint path is confined to ``client.py``,
which uses the standard library alone. The live commands are unprivileged: they
consume an emitted export and never the bundle or the benchmark answer key.

The targeted metadata model is recorded as
:data:`~dataswamp_biosystems.adapters.datahub.mapping.DATAHUB_MODEL_VERSION`, and
the emitted payloads are pinned by committed fixtures so a mapping change cannot
pass unnoticed.

See ``docs/datahub.md``.
"""

from __future__ import annotations

from dataswamp_biosystems.adapters.datahub.client import (
    DEFAULT_BATCH_SIZE,
    GMS_TOKEN_ENV,
    GMS_URL_ENV,
    LIVE_SUPPORT,
    DataHubClient,
    build_batches,
    redact_url,
)
from dataswamp_biosystems.adapters.datahub.errors import (
    DataHubAdapterError,
    DataHubConfigError,
    DataHubTransportError,
)
from dataswamp_biosystems.adapters.datahub.export import (
    EXPORT_MANIFEST_NAME,
    MCPS_JSON_NAME,
    MCPS_JSONL_NAME,
    RECIPE_NAME,
    build_source,
    export_datahub,
)
from dataswamp_biosystems.adapters.datahub.ingest import (
    IngestPlan,
    LoadedExport,
    execute_ingestion,
    load_export,
    plan_ingestion,
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
from dataswamp_biosystems.adapters.datahub.normalize import (
    NORMALIZATION_VERSION,
    SERVER_OWNED_FIELDS,
    UNORDERED_FIELDS,
    normalization_contract,
    normalize_aspect,
)
from dataswamp_biosystems.adapters.datahub.readback import read_back
from dataswamp_biosystems.adapters.datahub.report import (
    DISCREPANCIES_NAME,
    LEAK_FINDINGS_NAME,
    ROUNDTRIP_REPORT_NAME,
    build_report,
    write_roundtrip,
)
from dataswamp_biosystems.adapters.datahub.roundtrip import (
    ENTITY_FAMILIES,
    LEAK_PROBES,
    ROUNDTRIP_SCHEMA_VERSION,
    Claim,
    Discrepancy,
    DiscrepancyKind,
    Readback,
    RetrievedAspect,
    RoundTripResult,
    compare,
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
    # The live path: ingest an emitted export, then read it back and compare.
    "GMS_URL_ENV",
    "GMS_TOKEN_ENV",
    "LIVE_SUPPORT",
    "DEFAULT_BATCH_SIZE",
    "DataHubClient",
    "build_batches",
    "redact_url",
    "DataHubAdapterError",
    "DataHubConfigError",
    "DataHubTransportError",
    "LoadedExport",
    "IngestPlan",
    "load_export",
    "plan_ingestion",
    "execute_ingestion",
    "read_back",
    "NORMALIZATION_VERSION",
    "SERVER_OWNED_FIELDS",
    "UNORDERED_FIELDS",
    "normalize_aspect",
    "normalization_contract",
    "ROUNDTRIP_SCHEMA_VERSION",
    "Claim",
    "Discrepancy",
    "DiscrepancyKind",
    "ENTITY_FAMILIES",
    "LEAK_PROBES",
    "Readback",
    "RetrievedAspect",
    "RoundTripResult",
    "compare",
    "ROUNDTRIP_REPORT_NAME",
    "DISCREPANCIES_NAME",
    "LEAK_FINDINGS_NAME",
    "build_report",
    "write_roundtrip",
]
