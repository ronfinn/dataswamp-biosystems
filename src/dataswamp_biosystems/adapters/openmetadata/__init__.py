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

**There is no live path and no verified compatibility point.**
:data:`~dataswamp_biosystems.adapters.openmetadata.mapping.VERIFIED_OPENMETADATA_VERSION`
is ``None`` and stays ``None`` until a real-server run earns one. The schemas
were read, which is not the same as having been tested against — see
``docs/adr/0006-compatibility-points-not-ranges.md``.

See ``docs/openmetadata.md``.
"""

from __future__ import annotations

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
    # Errors.
    "OpenMetadataAdapterError",
    "OpenMetadataConfigError",
]
