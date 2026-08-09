"""A deterministic OpenMetadata metadata adapter for benchmark bundles.

The adapter maps DataSwamp catalogue entities onto OpenMetadata's **native**
model — whole-entity ``Create<Entity>`` requests, hierarchical
``fullyQualifiedName`` identity, load-order-aware reference closure — and emits an
ordered load plan as files.

It is deliberately *not* a copy of the DataHub adapter's entity/aspect
architecture. DataSwamp is the vendor-neutral benchmark; each catalogue is an
adapter, and each catalogue gets the shape it actually has. No
``adapters/common/`` exists yet, on purpose: with two adapters in the repository
it is now possible to see what is genuinely common rather than merely similar,
and that judgement is better made once than guessed at twice.

Like the DataHub adapter it is **schema-emitting rather than SDK-backed**. There
is no ``openmetadata-ingestion`` dependency, no HTTP client, and no network in
the test suite; emitted payloads are validated offline against a small vendored
subset of OpenMetadata's own JSON schemas. See
``docs/adr/0007-no-catalogue-client-dependency.md``.

A **live path** exists and is strictly downstream of the emitted export::

    bundle -> export-openmetadata -> emitted export -> ingest-openmetadata -> verify-om-ingestion

:mod:`.client` is the only module that opens a socket and the only one that names
an endpoint; :mod:`.ingest` replays the emitted plan in its emitted order without
remapping it; :mod:`.readback` retrieves state by fully-qualified name;
:mod:`.roundtrip` compares the two purely; :mod:`.report` writes the verdict.

**There is still no verified compatibility point.**
:data:`~dataswamp_biosystems.adapters.openmetadata.mapping.VERIFIED_OPENMETADATA_VERSION`
is ``None`` and stays ``None`` until a real-server run earns one. The request
shapes were read from OpenMetadata's own resource classes and the whole live path
is proved against a strict offline fake, neither of which is the same as having
run against a server — see ``docs/adr/0006-compatibility-points-not-ranges.md``.

See ``docs/openmetadata.md``.
"""

from __future__ import annotations

from dataswamp_biosystems.adapters.openmetadata.client import (
    COLLECTIONS,
    HOST_PORT_ENV,
    JWT_TOKEN_ENV,
    LIVE_SUPPORT,
    OpenMetadataClient,
    redact_url,
)
from dataswamp_biosystems.adapters.openmetadata.coverage import (
    CONCEPT_NAMES,
    CONCEPTS,
    COVERAGE_SCHEMA_VERSION,
    Concept,
    ConceptCounts,
    Fidelity,
    State,
    build_coverage,
)
from dataswamp_biosystems.adapters.openmetadata.errors import (
    OpenMetadataAdapterError,
    OpenMetadataConfigError,
    OpenMetadataTransportError,
)
from dataswamp_biosystems.adapters.openmetadata.export import (
    CUSTOM_PROPERTIES_NAME,
    ENTITIES_NAME,
    EXPORT_MANIFEST_NAME,
    LINEAGE_NAME,
    MAPPING_COVERAGE_NAME,
    TEST_RESULTS_NAME,
    build_source,
    export_openmetadata,
)
from dataswamp_biosystems.adapters.openmetadata.ingest import (
    IngestPlan,
    LoadedExport,
    Operation,
    execute_ingestion,
    load_export,
    plan_ingestion,
)
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    BUILTIN_REFERENCES,
    ENDPOINTS,
    FILE_FORMATS,
    OM_ADAPTER_VERSION,
    OPENMETADATA_MODEL_TARGET_RANGE,
    OPENMETADATA_SCHEMA_COMMIT,
    OPENMETADATA_SCHEMA_TARGET,
    PHASES,
    TAG_PRIVILEGED,
    TAG_SYNTHETIC,
    TRUTH_ONLY_PROPERTY_PREFIX,
    VERIFIED_OPENMETADATA_VERSION,
    ExportMode,
    ExportPlan,
    PlanRecord,
    Reference,
    SourceGraph,
    build_plan,
    property_specs,
)
from dataswamp_biosystems.adapters.openmetadata.normalize import (
    OM_NORMALIZATION_VERSION,
    normalization_contract,
)
from dataswamp_biosystems.adapters.openmetadata.readback import read_back
from dataswamp_biosystems.adapters.openmetadata.report import (
    DISCREPANCIES_NAME,
    LEAK_FINDINGS_NAME,
    ROUNDTRIP_REPORT_NAME,
    build_report,
    write_roundtrip,
)
from dataswamp_biosystems.adapters.openmetadata.roundtrip import (
    CONTAINMENT_FAMILIES,
    LEAK_PROBES,
    OM_ROUNDTRIP_SCHEMA_VERSION,
    Claim,
    ContainmentFamily,
    Coverage,
    Discrepancy,
    DiscrepancyKind,
    LeakFinding,
    Readback,
    RoundTripResult,
    compare,
)
from dataswamp_biosystems.adapters.openmetadata.validate import (
    CUSTOM_PROPERTY_NAME,
    FQN_PATTERNS,
    validate_plan,
)

__all__ = [
    # Identity, mapping and the plan.
    "OM_ADAPTER_VERSION",
    "OPENMETADATA_SCHEMA_TARGET",
    "OPENMETADATA_SCHEMA_COMMIT",
    "OPENMETADATA_MODEL_TARGET_RANGE",
    "VERIFIED_OPENMETADATA_VERSION",
    "ExportMode",
    "SourceGraph",
    "ExportPlan",
    "PlanRecord",
    "Reference",
    "build_plan",
    "build_source",
    "property_specs",
    "PHASES",
    "ENDPOINTS",
    "FILE_FORMATS",
    "BUILTIN_REFERENCES",
    "TAG_SYNTHETIC",
    "TAG_PRIVILEGED",
    "TRUTH_ONLY_PROPERTY_PREFIX",
    # Emitting an export.
    "export_openmetadata",
    "CUSTOM_PROPERTIES_NAME",
    "ENTITIES_NAME",
    "LINEAGE_NAME",
    "TEST_RESULTS_NAME",
    "MAPPING_COVERAGE_NAME",
    "EXPORT_MANIFEST_NAME",
    # Offline validation.
    "validate_plan",
    "FQN_PATTERNS",
    "CUSTOM_PROPERTY_NAME",
    # The mapping-coverage contract.
    "COVERAGE_SCHEMA_VERSION",
    "Fidelity",
    "State",
    "Concept",
    "ConceptCounts",
    "CONCEPTS",
    "CONCEPT_NAMES",
    "build_coverage",
    # The live path: transport.
    "OpenMetadataClient",
    "HOST_PORT_ENV",
    "JWT_TOKEN_ENV",
    "COLLECTIONS",
    "LIVE_SUPPORT",
    "redact_url",
    # The live path: replay.
    "LoadedExport",
    "IngestPlan",
    "Operation",
    "load_export",
    "plan_ingestion",
    "execute_ingestion",
    "read_back",
    # The live path: comparison and reporting.
    "OM_NORMALIZATION_VERSION",
    "normalization_contract",
    "OM_ROUNDTRIP_SCHEMA_VERSION",
    "Claim",
    "Coverage",
    "ContainmentFamily",
    "CONTAINMENT_FAMILIES",
    "LEAK_PROBES",
    "Discrepancy",
    "DiscrepancyKind",
    "LeakFinding",
    "Readback",
    "RoundTripResult",
    "compare",
    "build_report",
    "write_roundtrip",
    "ROUNDTRIP_REPORT_NAME",
    "DISCREPANCIES_NAME",
    "LEAK_FINDINGS_NAME",
    # Errors.
    "OpenMetadataAdapterError",
    "OpenMetadataConfigError",
    "OpenMetadataTransportError",
]
