"""Map DataSwamp benchmark entities onto OpenMetadata's native model.

The mapping is a pure function of one *source graph* — a shard-keyed collection
of records read from a bundle — and produces an ordered **load plan**. It
performs no I/O, holds no state and consults no clock, so the same source graph
always yields byte-identical output.

This is deliberately **not** the DataHub adapter's architecture. DataHub models
an entity as a stream of independently-addressed aspects, so its adapter emits
one proposal per aspect. OpenMetadata models an entity as a whole document with a
hierarchical ``fullyQualifiedName``, so this adapter emits one
``Create<Entity>`` request per entity, in an order that respects containment.
Copying the aspect architecture here would have produced something that ingests
into neither catalogue especially well.

Two modes exist and they differ in **what they are allowed to read**, not merely
in what they choose to emit:

``observed``
    Built from ``observed/observed-graph.json`` alone. The expected findings,
    expected remediations, control partition, rule scope, defect instances,
    mutation log and scenario ledgers are never opened. An agent under test can
    be handed this export without learning which entities carry defects.
``truth``
    Built from the ``truth/`` shards, optionally annotated with ground-truth
    labels. Every asset is tagged privileged, carries reserved ``dataswampTruth*``
    properties, and the export manifest says so.

Three structural facts shape everything below.

**OpenMetadata's ``EntityReference`` requires a server-assigned UUID.** A parent
container, an owning team and a lineage endpoint are all ``EntityReference``
fields, and an offline export cannot know a UUID the server has not issued yet.
Fabricating one would be worse than useless — it would produce a payload that
looks complete and loads wrong. So those references are emitted as an explicit
:class:`Reference` block beside the create payload, to be resolved by FQN at load
time. Fields OpenMetadata already expresses *as* FQNs (``domains``, ``glossary``,
``classification``, ``parent`` on a glossary term) are emitted inline, because
those need no resolution.

**A small number of references point at OpenMetadata's own built-ins.**
Registering a custom property names a property type (``string``) and an entity
type (``container``) that ship with the server. Those are the only references
allowed to resolve outside this export, they are enumerated in
:data:`BUILTIN_REFERENCES`, and the validator rejects any other outside
reference. This is an allow-list, not an escape hatch.

**What OpenMetadata cannot hold is documented rather than distorted.** No Table,
column, database or schema is invented for a project that has no honest
relational schema; no Pipeline or PipelineService is synthesized for an
instrument run; no DataContract entity is populated from facts that do not
constitute a contract; and no TestDefinition is emitted, because its
``entityType`` enum admits only ``TABLE`` and ``COLUMN``. Every one of those
decisions is counted and justified in :mod:`.coverage`, which ships with the
export.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dataswamp_biosystems.adapters.openmetadata import fqn as om_fqn
from dataswamp_biosystems.adapters.openmetadata.coverage import ConceptCounts, build_coverage

# Bumped when the emitted plan changes for unchanged input.
#
# 1.1.0 corrected the root-level DataProduct identity (#37): OpenMetadata derives
# a DataProduct's FQN from its ``name`` alone, so the previous dotted, programme-
# prefixed identity named an entity no server would have created. A consumer
# holding a DataProduct FQN emitted by 1.0.0 cannot match one emitted now — a
# different emitted contract rather than a corrected annotation, which is why
# this is a minor rather than a patch.
OM_ADAPTER_VERSION = "1.1.0"

# The exact OpenMetadata schema revision this adapter's payloads were written
# against and are validated against offline. A *named artefact*, not a claim
# about any running server: the vendored schema subset under
# ``tests/adapters/openmetadata/schemas/`` is taken from this revision, and
# ``tests/adapters/openmetadata/schemas/PROVENANCE.md`` records how to refresh it.
OPENMETADATA_SCHEMA_TARGET = "1.13.3-release"
OPENMETADATA_SCHEMA_COMMIT = "255f6694913b84797064a42859cda3f2a3425dc6"

# The release range the emitted *payload shape* is written for. This is a
# **declared target**, not tested evidence and not a statement about any REST
# endpoint — exactly the distinction ADR 0006 exists to keep. One revision inside
# it has actually been read: OPENMETADATA_SCHEMA_TARGET.
OPENMETADATA_MODEL_TARGET_RANGE = ">=1.9,<2"

# The one OpenMetadata release the live path has been *run* against. A tested
# point, never a range: 1.13.4 and 1.14.0 are untested until a canary says
# otherwise, and neither this constant nor OPENMETADATA_MODEL_TARGET_RANGE above
# may be read as covering them.
#
# Earned by run 31528890425 against a pinned, throwaway OpenMetadata 1.13.3
# (server image sha256:997d666b01f674fc4d587f034759c826082ea7666cd7bc0e6db8fdbb707df010,
# self-reporting revision 255f6694913b84797064a42859cda3f2a3425dc6): 830/830
# entities retrieved and matched, all four claims green, zero discrepancies, zero
# leak findings, 19 live tests including the negative controls that prove a clean
# result is not a comparison of nothing against nothing.
#
# **Scope: observed mode.** What ran end to end is
# bundle -> export-openmetadata --mode observed -> ingest -> real server ->
# readback -> round-trip verification -> negative controls. Truth mode is a
# privileged diagnostic surface; it rests on the deterministic offline contract
# and the vendored schemas, and has *not* been exercised against a real server.
# This constant must not be read as covering it. See docs/openmetadata.md.
VERIFIED_OPENMETADATA_VERSION: str | None = "1.13.3"

# Tag facets. The privileged marker is one of three independent signals that an
# export carries ground truth; see ``docs/openmetadata.md``.
TAG_SYNTHETIC = "synthetic"
TAG_PRIVILEGED = "privileged-truth-export"

# Custom-property keys that only ever appear in a privileged truth export. The
# observed validator asserts their absence, so a future mapping change that
# leaked one fails the suite rather than the benchmark.
TRUTH_ONLY_PROPERTY_PREFIX = "dataswampTruth"

# OpenMetadata's Domain taxonomy is a closed enum. A research programme produces
# its own datasets rather than consuming another domain's, so Source-aligned is
# the honest member; the source concept is preserved in a custom property.
DOMAIN_TYPE = "Source-aligned"

# The only teamType that asserts no organisational hierarchy. DataSwamp teams
# have no parent/child structure, so claiming Department or Division would be
# inventing one.
TEAM_TYPE = "Group"

# OpenMetadata's ``fileFormat`` enum, verbatim. A DataSwamp format outside it is
# left unset rather than coerced: ``h5ad`` is not ``json``, and saying it is
# would put a false fact in a catalogue to satisfy a schema.
FILE_FORMATS: frozenset[str] = frozenset(
    {"zip", "gz", "zstd", "csv", "tsv", "json", "parquet", "avro", "MF4"}
)

# Asset fields that reference a controlled vocabulary, and the vocabulary each
# belongs to. Drives glossary emission.
VOCABULARY_FIELDS: dict[str, str] = {
    "scientific_domain": "scientific-domain",
    "modality": "modality",
    "lifecycle_stage": "lifecycle-stage",
    "access_classification": "access-classification",
    "retention_class": "retention-class",
    "model_training_status": "model-training-status",
}
# List-valued vocabulary fields.
VOCABULARY_LIST_FIELDS: dict[str, str] = {"intended_uses": "intended-use"}

# API paths, recorded so a later live path has one place to read them from rather
# than rediscovering them. Nothing here opens a socket.
ENDPOINTS: dict[str, str] = {
    "customProperty": "/api/v1/metadata/types",
    "classification": "/api/v1/classifications",
    "tag": "/api/v1/tags",
    "glossary": "/api/v1/glossaries",
    "glossaryTerm": "/api/v1/glossaryTerms",
    "team": "/api/v1/teams",
    "domain": "/api/v1/domains",
    "storageService": "/api/v1/services/storageServices",
    "container": "/api/v1/containers",
    "dataProduct": "/api/v1/dataProducts",
    # Addressed by the data product's fully-qualified name. OpenMetadata's
    # DataProductResource exposes the asset *write* only in this form — there is
    # no ``/name/{fqn}/assets/add`` — and the repository resolves the segment
    # through ``getByName``, so what goes there is an FQN despite the upstream
    # parameter being called ``name``.
    "dataProductAssets": "/api/v1/dataProducts/{fqn}/assets/add",
    "lineage": "/api/v1/lineage",
}

# The load phases, in contract order. The plan validator checks that records
# appear in exactly this sequence and that ``order`` increases monotonically
# across the whole export, so a reference can never point forward.
PHASES: tuple[str, ...] = (
    "custom-property",
    "classification",
    "tag",
    "glossary",
    "glossary-term",
    "team",
    "domain",
    "storage-service",
    "study-container",
    "dataset-container",
    "file-container",
    "data-product",
    "data-product-assets",
    "lineage",
    "test-result",
)

# The complete allow-list of references permitted to resolve outside this export:
# OpenMetadata's own built-in property types and entity types, which every server
# ships with and which DataSwamp must not attempt to create. Anything else that
# fails closure is a bug, not a platform primitive.
BUILTIN_REFERENCES: frozenset[tuple[str, str]] = frozenset(
    {
        ("propertyType", "string"),
        ("entityType", "container"),
        ("entityType", "dataProduct"),
    }
)


class ExportMode(StrEnum):
    """What an OpenMetadata export is allowed to contain."""

    OBSERVED = "observed"
    TRUTH = "truth"


@dataclass(frozen=True)
class Reference:
    """A reference the export declares but cannot resolve offline.

    ``field`` is the create-payload field the resolved value belongs in.
    ``entity_type`` and ``target`` say what to look up. ``builtin`` marks the
    allow-listed platform primitives; every other reference must resolve to an
    FQN emitted earlier in this same plan.
    """

    field: str
    entity_type: str
    target: str
    many: bool = False
    builtin: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "entityType": self.entity_type,
            "target": self.target,
            "many": self.many,
            "builtin": self.builtin,
        }


@dataclass(frozen=True)
class PlanRecord:
    """One ordered step of the load plan."""

    order: int
    phase: str
    concept: str
    entity_type: str
    endpoint: str
    fqn: str
    create: dict[str, Any] | None = None
    references: tuple[Reference, ...] = ()
    dataswamp_id: str | None = None
    # Free-form, phase-specific payload for the steps that are not an entity
    # create: asset attachment, lineage edges and the deferred result plan.
    plan: dict[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "order": self.order,
            "phase": self.phase,
            "concept": self.concept,
            "entityType": self.entity_type,
            "endpoint": self.endpoint,
            "fullyQualifiedName": self.fqn,
        }
        if self.dataswamp_id is not None:
            payload["dataswampId"] = self.dataswamp_id
        if self.create is not None:
            payload["create"] = self.create
        if self.plan is not None:
            payload["plan"] = self.plan
        payload["references"] = [reference.as_json() for reference in self.references]
        return payload


@dataclass(frozen=True)
class ExportPlan:
    """The whole deterministic load plan, split by output file."""

    mode: ExportMode
    custom_properties: tuple[PlanRecord, ...]
    entities: tuple[PlanRecord, ...]
    lineage: tuple[PlanRecord, ...]
    test_results: tuple[PlanRecord, ...]
    coverage: dict[str, Any]

    @property
    def records(self) -> tuple[PlanRecord, ...]:
        """Every record, in global load order."""
        return (*self.custom_properties, *self.entities, *self.lineage, *self.test_results)


@dataclass(frozen=True)
class SourceGraph:
    """The records one export is built from, keyed by truth-graph shard name."""

    mode: ExportMode
    shards: Mapping[str, Sequence[Mapping[str, Any]]]
    # Only populated for a privileged truth export: ``{entity_id: [rule_id]}``.
    expected_finding_rules: Mapping[str, Sequence[str]] = field(default_factory=dict)

    def records(self, shard: str) -> list[dict[str, Any]]:
        """Return one shard's records, sorted by id so output order is fixed."""
        rows = [dict(row) for row in self.shards.get(shard, ())]
        return sorted(rows, key=lambda row: str(row.get("id", "")))


# ---------------------------------------------------------------------------
# Custom properties
# ---------------------------------------------------------------------------
# Every DataSwamp fact OpenMetadata has no native home for lands in a custom
# property. All of them are declared ``string``, deliberately: an *observed*
# record may hold a null, an empty value or a wrong-typed one — that is the
# defect — and a typed property would either reject it or silently coerce it.
# The export's job is to show a catalogue what it would really have seen.

_CONTAINER_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("dataswampId", "The stable DataSwamp identifier this entity was generated from."),
    ("dataswampEntityType", "The DataSwamp concept this container stands for."),
    ("dataswampSynthetic", "Always true: every DataSwamp record is fictional."),
    ("dataswampProgrammeId", "The DataSwamp research programme this asset belongs to."),
    ("dataswampStudyId", "The DataSwamp study this asset belongs to."),
    ("dataswampModality", "The controlled-vocabulary modality term."),
    ("dataswampModalityGroup", "The coarse modality grouping."),
    ("dataswampVersion", "The asset version recorded in the DataSwamp catalogue."),
    ("dataswampLifecycleStage", "The controlled-vocabulary lifecycle stage."),
    ("dataswampAccessClassification", "The controlled-vocabulary access classification."),
    ("dataswampRetentionClass", "The controlled-vocabulary retention class."),
    ("dataswampModelTrainingStatus", "The controlled-vocabulary model-training status."),
    ("dataswampIntendedUses", "Comma-separated controlled-vocabulary intended uses."),
    ("dataswampQualityStatus", "The asset's recorded quality status."),
    ("dataswampOwnerRef", "The DataSwamp owning team id, alongside the native owners field."),
    (
        "dataswampStewardRefs",
        "Comma-separated DataSwamp stewarding team ids. OpenMetadata draws no "
        "owner/steward distinction, so this property is the only place stewardship "
        "survives; see mapping-coverage.json.",
    ),
    (
        "dataswampPhysicalBytes",
        "The exact physical size in bytes. OpenMetadata's native size field is in "
        "KB, so this is the authoritative figure.",
    ),
    ("dataswampLogicalBytes", "The exact logical size in bytes."),
    ("dataswampRecordCount", "The record count recorded in the DataSwamp catalogue."),
    (
        "dataswampFileFormat",
        "The DataSwamp file format, including formats outside OpenMetadata's fileFormat enum.",
    ),
    ("dataswampRelativePath", "The estate-relative path of a physical file."),
    ("dataswampChecksum", "The DataSwamp checksum recorded for a physical file."),
    ("dataswampProducingRunId", "The instrument or pipeline run that produced a file."),
    ("dataswampDatasetId", "The dataset a physical file belongs to."),
    ("dataswampContractId", "The DataSwamp data contract governing this asset."),
    ("dataswampContractVersion", "The contract version."),
    ("dataswampSchemaRef", "The schema reference named by the contract."),
    ("dataswampSla", "The service-level agreement named by the contract."),
    (
        "dataswampQualityChecks",
        "The asset's quality checks, as 'check-id:check-type:status' entries. "
        "OpenMetadata's TestDefinition.entityType admits only TABLE and COLUMN, so "
        "no test entities are created; see mapping-coverage.json.",
    ),
)

_TRUTH_ONLY_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("dataswampTruthExport", "PRIVILEGED: marks an entity emitted from benchmark ground truth."),
    (
        "dataswampTruthExpectedFindingRules",
        "PRIVILEGED: the defect rule ids this entity is expected to trigger. Benchmark "
        "answer key — never present in an observed export.",
    ),
)

# Data products carry the governance and contract facts but none of the
# file-level ones, because a data product has no physical file.
_DATA_PRODUCT_ONLY_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "dataswampFileFormat",
        "dataswampRelativePath",
        "dataswampChecksum",
        "dataswampProducingRunId",
        "dataswampDatasetId",
        "dataswampPhysicalBytes",
        "dataswampLogicalBytes",
        "dataswampRecordCount",
    }
)


def property_specs(entity_type: str, *, privileged: bool) -> tuple[tuple[str, str], ...]:
    """Return the custom properties registered for one OpenMetadata entity type."""
    specs = _CONTAINER_PROPERTIES
    if entity_type == "dataProduct":
        specs = tuple(spec for spec in specs if spec[0] not in _DATA_PRODUCT_ONLY_EXCLUSIONS)
    if privileged:
        specs = (*specs, *_TRUTH_ONLY_PROPERTIES)
    return tuple(sorted(specs))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    """Render a field for a custom property without inventing a value.

    Observed records may hold nulls, empty strings and wrong-typed values by
    design — that *is* the defect. They are rendered faithfully so the export
    shows a catalogue what it would really have seen.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return ",".join(_text(item) for item in value)
    return str(value)


def _description(value: Any, fallback: str) -> str:
    """Return a non-empty description.

    Several OpenMetadata create requests make ``description`` mandatory. An
    observed record is allowed to have lost its description — again, the defect —
    so a generated fallback naming the entity is used rather than dropping the
    entity or emitting an empty string the server would reject. The *original*
    value, empty or not, is never discarded: it is what ``description`` carries
    whenever it has one.
    """
    text = _text(value).strip()
    return text if text else fallback


def _tag_label(tag_fqn: str, source: str = "Classification") -> dict[str, Any]:
    return {
        "tagFQN": tag_fqn,
        "source": source,
        "labelType": "Manual",
        "state": "Confirmed",
    }


def _size_kb(physical_bytes: Any) -> float | None:
    """Return OpenMetadata's KB size, floored, or ``None`` if it cannot be derived.

    Flooring is the conservative direction: a container never claims to hold more
    than it does. The exact byte count is preserved separately in
    ``dataswampPhysicalBytes``, which is the authoritative figure — this field
    exists so the native OpenMetadata UI shows something sane, not so anyone
    computes with it.
    """
    if isinstance(physical_bytes, bool) or not isinstance(physical_bytes, int):
        return None
    if physical_bytes < 0:
        return None
    return float(physical_bytes // 1024)


def _terms_for(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return the ``(vocabulary, term)`` pairs one asset record references, sorted."""
    terms: set[tuple[str, str]] = set()
    for field_name, vocabulary in VOCABULARY_FIELDS.items():
        value = record.get(field_name)
        if isinstance(value, str) and value:
            terms.add((vocabulary, value))
    for field_name, vocabulary in VOCABULARY_LIST_FIELDS.items():
        values = record.get(field_name)
        if isinstance(values, list):
            terms.update((vocabulary, item) for item in values if isinstance(item, str) and item)
    return sorted(terms)


def _facets_for(record: Mapping[str, Any]) -> list[str]:
    """Return the coarse browse facets one asset carries, sorted.

    Facets are what a catalogue user browses by; the precise controlled-vocabulary
    values are glossary terms, so the two do not duplicate each other.
    """
    facets = {TAG_SYNTHETIC}
    for field_name in ("modality_group", "quality_status"):
        value = record.get(field_name)
        if isinstance(value, str) and value:
            facets.add(f"{field_name.replace('_', '-')}-{value}")
    if record.get("is_reference") is True:
        facets.add("reference-dataset")
    return sorted(facets)


def _owner_reference(record: Mapping[str, Any]) -> tuple[Reference, ...]:
    """Return the declared owner reference, if the record names an owning team."""
    owner = record.get("owner_ref")
    if isinstance(owner, str) and owner:
        return (
            Reference(
                field="owners",
                entity_type="team",
                target=om_fqn.team_fqn(owner),
                many=True,
            ),
        )
    return ()


def _steward_ids(record: Mapping[str, Any]) -> list[str]:
    stewards = record.get("steward_refs")
    if not isinstance(stewards, list):
        return []
    return sorted({item for item in stewards if isinstance(item, str) and item})


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


class _Builder:
    """Accumulates plan records and keeps the global order counter honest."""

    def __init__(self) -> None:
        self._order = 0
        self.custom_properties: list[PlanRecord] = []
        self.entities: list[PlanRecord] = []
        self.lineage: list[PlanRecord] = []
        self.test_results: list[PlanRecord] = []

    def add(self, bucket: list[PlanRecord], **kwargs: Any) -> PlanRecord:
        self._order += 1
        record = PlanRecord(order=self._order, **kwargs)
        bucket.append(record)
        return record


def _asset_extension(
    record: Mapping[str, Any],
    *,
    entity_type: str,
    contract: Mapping[str, Any] | None,
    quality: Sequence[Mapping[str, Any]],
    privileged: bool,
    expected_rules: Sequence[str],
) -> dict[str, str]:
    """Return the custom-property values a catalogue asset carries."""
    values: dict[str, str] = {
        "dataswampId": _text(record.get("id")),
        "dataswampEntityType": _text(record.get("asset_type")),
        "dataswampSynthetic": "true",
        "dataswampProgrammeId": _text(record.get("programme_id")),
        "dataswampStudyId": _text(record.get("study_id")),
        "dataswampModality": _text(record.get("modality")),
        "dataswampModalityGroup": _text(record.get("modality_group")),
        "dataswampVersion": _text(record.get("version")),
        "dataswampLifecycleStage": _text(record.get("lifecycle_stage")),
        "dataswampAccessClassification": _text(record.get("access_classification")),
        "dataswampRetentionClass": _text(record.get("retention_class")),
        "dataswampModelTrainingStatus": _text(record.get("model_training_status")),
        "dataswampIntendedUses": _text(record.get("intended_uses")),
        "dataswampQualityStatus": _text(record.get("quality_status")),
        "dataswampOwnerRef": _text(record.get("owner_ref")),
        "dataswampStewardRefs": ",".join(_steward_ids(record)),
    }
    if entity_type != "dataProduct":
        for key in ("physical_bytes", "logical_bytes", "record_count"):
            if key in record:
                camel = "".join(part.capitalize() for part in key.split("_"))
                values[f"dataswamp{camel}"] = _text(record.get(key))
    if contract is not None:
        values.update(
            {
                "dataswampContractId": _text(contract.get("id")),
                "dataswampContractVersion": _text(contract.get("contract_version")),
                "dataswampSchemaRef": _text(contract.get("schema_ref")),
                "dataswampSla": _text(contract.get("sla")),
            }
        )
    if quality:
        values["dataswampQualityChecks"] = ",".join(
            f"{_text(check.get('id'))}:{_text(check.get('check_type'))}:{_text(check.get('status'))}"
            for check in quality
        )
    if privileged:
        values["dataswampTruthExport"] = "true"
        values["dataswampTruthExpectedFindingRules"] = ",".join(sorted(expected_rules))
    return dict(sorted(values.items()))


def build_plan(source: SourceGraph) -> ExportPlan:  # noqa: C901 - one ordered pass, by design
    """Return the complete, deterministic load plan for ``source``.

    The function is long because the load order *is* the contract: splitting it
    into per-entity helpers would hide the one property a reader most needs to
    check, which is that every reference target is emitted before the record that
    points at it.
    """
    privileged = source.mode is ExportMode.TRUTH
    builder = _Builder()

    datasets = source.records("datasets")
    products = source.records("data_products")
    assets = [*datasets, *products]
    files = source.records("files")
    quality_checks = source.records("quality_checks")
    lineage_edges = source.records("lineage")
    contracts = {
        str(row.get("asset_id", "")): row
        for row in source.records("contracts")
        if isinstance(row.get("asset_id"), str)
    }

    dataset_study = {
        str(record.get("id", "")): _text(record.get("study_id")) for record in datasets
    }
    quality_by_asset: dict[str, list[dict[str, Any]]] = {}
    for check in quality_checks:
        quality_by_asset.setdefault(_text(check.get("asset_id")), []).append(check)

    # -- 1. custom-property registrations -------------------------------------
    for entity_type in ("container", "dataProduct"):
        for name, description in property_specs(entity_type, privileged=privileged):
            builder.add(
                builder.custom_properties,
                phase="custom-property",
                concept="custom_property",
                entity_type="customProperty",
                endpoint=ENDPOINTS["customProperty"],
                fqn=f"{entity_type}.{name}",
                create={"name": name, "description": description},
                references=(
                    Reference(
                        field="entityType",
                        entity_type="type",
                        target=entity_type,
                        builtin=True,
                    ),
                    Reference(
                        field="propertyType",
                        entity_type="type",
                        target="string",
                        builtin=True,
                    ),
                ),
            )

    # -- 2. classification ----------------------------------------------------
    builder.add(
        builder.entities,
        phase="classification",
        concept="facet_tag",
        entity_type="classification",
        endpoint=ENDPOINTS["classification"],
        fqn=om_fqn.classification_fqn(),
        create={
            "name": om_fqn.CLASSIFICATION_NAME,
            "description": (
                "Coarse browse facets for the Data Swamp Biosystems synthetic benchmark "
                "estate. Every asset under it is fictional."
            ),
            "mutuallyExclusive": False,
        },
    )

    # -- 3. tags --------------------------------------------------------------
    facets: set[str] = {TAG_SYNTHETIC}
    for record in assets:
        facets.update(_facets_for(record))
    if privileged:
        facets.add(TAG_PRIVILEGED)
    for facet in sorted(facets):
        builder.add(
            builder.entities,
            phase="tag",
            concept="facet_tag",
            entity_type="tag",
            endpoint=ENDPOINTS["tag"],
            fqn=om_fqn.tag_fqn(facet),
            dataswamp_id=facet,
            create={
                "name": om_fqn.encode_id(facet),
                "classification": om_fqn.classification_fqn(),
                "description": f"DataSwamp facet {facet!r}.",
            },
        )

    # -- 4/5. glossaries and terms --------------------------------------------
    vocab_terms: set[tuple[str, str]] = set()
    for record in assets:
        vocab_terms.update(_terms_for(record))
    for vocabulary in sorted({name for name, _ in vocab_terms}):
        builder.add(
            builder.entities,
            phase="glossary",
            concept="controlled_vocabulary",
            entity_type="glossary",
            endpoint=ENDPOINTS["glossary"],
            fqn=om_fqn.glossary_fqn(vocabulary),
            dataswamp_id=vocabulary,
            create={
                "name": om_fqn.name_of(om_fqn.glossary_fqn(vocabulary)),
                "description": f"DataSwamp controlled vocabulary {vocabulary!r}.",
                "mutuallyExclusive": False,
            },
        )
    for vocabulary, term in sorted(vocab_terms):
        builder.add(
            builder.entities,
            phase="glossary-term",
            concept="vocabulary_term",
            entity_type="glossaryTerm",
            endpoint=ENDPOINTS["glossaryTerm"],
            fqn=om_fqn.glossary_term_fqn(vocabulary, term),
            dataswamp_id=term,
            create={
                "name": om_fqn.encode_id(term),
                "glossary": om_fqn.glossary_fqn(vocabulary),
                "description": f"DataSwamp {vocabulary} term {term!r}.",
            },
        )

    # -- 6. teams -------------------------------------------------------------
    teams: set[str] = set()
    for record in assets:
        owner = record.get("owner_ref")
        if isinstance(owner, str) and owner:
            teams.add(owner)
        teams.update(_steward_ids(record))
    for team in sorted(teams):
        builder.add(
            builder.entities,
            phase="team",
            concept="team",
            entity_type="team",
            endpoint=ENDPOINTS["team"],
            fqn=om_fqn.team_fqn(team),
            dataswamp_id=team,
            create={
                "name": om_fqn.name_of(om_fqn.team_fqn(team)),
                "teamType": TEAM_TYPE,
                "description": f"DataSwamp owning/stewarding team {team!r}.",
            },
        )

    # -- 7. domains -----------------------------------------------------------
    programmes = sorted(
        {
            str(record["programme_id"])
            for record in assets
            if isinstance(record.get("programme_id"), str) and record["programme_id"]
        }
    )
    for programme in programmes:
        builder.add(
            builder.entities,
            phase="domain",
            concept="programme",
            entity_type="domain",
            endpoint=ENDPOINTS["domain"],
            fqn=om_fqn.domain_fqn(programme),
            dataswamp_id=programme,
            create={
                "name": om_fqn.name_of(om_fqn.domain_fqn(programme)),
                "domainType": DOMAIN_TYPE,
                "description": f"DataSwamp research programme {programme!r}.",
            },
        )

    # -- 8. storage service ---------------------------------------------------
    builder.add(
        builder.entities,
        phase="storage-service",
        concept="company",
        entity_type="storageService",
        endpoint=ENDPOINTS["storageService"],
        fqn=om_fqn.service_fqn(),
        create={
            "name": om_fqn.SERVICE_NAME,
            "serviceType": om_fqn.SERVICE_TYPE,
            "description": (
                "Data Swamp Biosystems — an entirely fictional synthetic oncology data "
                "estate. No storage connection is configured: the estate is a benchmark "
                "artefact, not a real object store."
            ),
        },
    )

    # -- 9. study containers --------------------------------------------------
    study_programme: dict[str, str] = {}
    for record in assets:
        study = _text(record.get("study_id"))
        if study and study not in study_programme:
            study_programme[study] = _text(record.get("programme_id"))
    for study in sorted(study_programme):
        create: dict[str, Any] = {
            "name": om_fqn.name_of(om_fqn.study_fqn(study)),
            "service": om_fqn.service_fqn(),
            "description": f"DataSwamp study {study!r}.",
            "extension": {"dataswampId": study, "dataswampEntityType": "study"},
        }
        programme = study_programme[study]
        if programme:
            create["domains"] = [om_fqn.domain_fqn(programme)]
        builder.add(
            builder.entities,
            phase="study-container",
            concept="study",
            entity_type="container",
            endpoint=ENDPOINTS["container"],
            fqn=om_fqn.study_fqn(study),
            dataswamp_id=study,
            create=create,
        )

    # -- 10. dataset containers -----------------------------------------------
    files_by_dataset: dict[str, list[dict[str, Any]]] = {}
    for record in files:
        files_by_dataset.setdefault(_text(record.get("dataset_id")), []).append(record)

    emitted_datasets: dict[str, str] = {}
    for record in datasets:
        asset_id = str(record.get("id", ""))
        study = _text(record.get("study_id"))
        if not asset_id or not study:
            continue
        target = om_fqn.dataset_fqn(study, asset_id)
        emitted_datasets[asset_id] = target
        facet_tags = [*_facets_for(record), *([TAG_PRIVILEGED] if privileged else [])]
        create = {
            "name": om_fqn.name_of(target),
            "service": om_fqn.service_fqn(),
            "description": _description(
                record.get("description"), f"DataSwamp dataset {asset_id!r}."
            ),
            "extension": _asset_extension(
                record,
                entity_type="container",
                contract=contracts.get(asset_id),
                quality=quality_by_asset.get(asset_id, ()),
                privileged=privileged,
                expected_rules=source.expected_finding_rules.get(asset_id, ()),
            ),
            "tags": [
                *(_tag_label(om_fqn.tag_fqn(facet)) for facet in sorted(set(facet_tags))),
                *(
                    _tag_label(om_fqn.glossary_term_fqn(vocab, term), source="Glossary")
                    for vocab, term in _terms_for(record)
                ),
            ],
            "numberOfObjects": float(len(files_by_dataset.get(asset_id, ()))),
        }
        size = _size_kb(record.get("physical_bytes"))
        if size is not None:
            create["size"] = size
        programme = _text(record.get("programme_id"))
        if programme:
            create["domains"] = [om_fqn.domain_fqn(programme)]
        builder.add(
            builder.entities,
            phase="dataset-container",
            concept="dataset",
            entity_type="container",
            endpoint=ENDPOINTS["container"],
            fqn=target,
            dataswamp_id=asset_id,
            create=create,
            references=(
                Reference(field="parent", entity_type="container", target=om_fqn.study_fqn(study)),
                *_owner_reference(record),
            ),
        )

    # -- 11. file containers --------------------------------------------------
    emitted_files = 0
    dropped_files = 0
    for record in files:
        file_id = str(record.get("id", ""))
        parent_id = _text(record.get("dataset_id"))
        study = dataset_study.get(parent_id, "")
        if not file_id or parent_id not in emitted_datasets or not study:
            dropped_files += 1
            continue
        target = om_fqn.file_fqn(study, parent_id, file_id)
        file_format = _text(record.get("file_format"))
        create = {
            "name": om_fqn.name_of(target),
            "service": om_fqn.service_fqn(),
            "description": (
                f"Physical file {_text(record.get('relative_path'))} "
                f"belonging to dataset {parent_id}."
            ),
            "extension": dict(
                sorted(
                    {
                        "dataswampId": file_id,
                        "dataswampEntityType": "physical_file",
                        "dataswampSynthetic": "true",
                        "dataswampDatasetId": parent_id,
                        "dataswampStudyId": study,
                        "dataswampRelativePath": _text(record.get("relative_path")),
                        "dataswampFileFormat": file_format,
                        "dataswampPhysicalBytes": _text(record.get("physical_bytes")),
                        "dataswampChecksum": _text(record.get("checksum")),
                        "dataswampProducingRunId": _text(record.get("producing_run_id")),
                    }.items()
                )
            ),
            "tags": [_tag_label(om_fqn.tag_fqn(TAG_SYNTHETIC))],
            "fullPath": _text(record.get("relative_path")),
        }
        if privileged:
            create["extension"]["dataswampTruthExport"] = "true"
            create["extension"]["dataswampTruthExpectedFindingRules"] = ",".join(
                sorted(source.expected_finding_rules.get(file_id, ()))
            )
            create["extension"] = dict(sorted(create["extension"].items()))
            create["tags"] = [
                _tag_label(om_fqn.tag_fqn(TAG_SYNTHETIC)),
                _tag_label(om_fqn.tag_fqn(TAG_PRIVILEGED)),
            ]
        size = _size_kb(record.get("physical_bytes"))
        if size is not None:
            create["size"] = size
        # Only a format OpenMetadata actually knows. Anything else stays in the
        # DataSwamp property rather than being coerced into a wrong enum member.
        if file_format in FILE_FORMATS:
            create["fileFormats"] = [file_format]
        builder.add(
            builder.entities,
            phase="file-container",
            concept="physical_file",
            entity_type="container",
            endpoint=ENDPOINTS["container"],
            fqn=target,
            dataswamp_id=file_id,
            create=create,
            references=(
                Reference(
                    field="parent",
                    entity_type="container",
                    target=emitted_datasets[parent_id],
                ),
            ),
        )
        emitted_files += 1

    # -- 12/13. data products and their asset attachments ---------------------
    emitted_products = 0
    dropped_products = 0
    attachment_records = 0
    attached_components = 0
    dropped_components = 0
    # Attachments are collected here and emitted *after* every data product, so
    # the phase sequence stays the contract's sequence. Emitting each attachment
    # beside its product would interleave two phases the moment a second product
    # exists — which the canonical estate has and the mini fixture does not.
    pending_attachments: list[tuple[str, str, list[str]]] = []
    for record in products:
        asset_id = str(record.get("id", ""))
        programme = _text(record.get("programme_id"))
        if not asset_id or not programme:
            dropped_products += 1
            continue
        target = om_fqn.data_product_fqn(programme, asset_id)
        facet_tags = [*_facets_for(record), *([TAG_PRIVILEGED] if privileged else [])]
        builder.add(
            builder.entities,
            phase="data-product",
            concept="data_product",
            entity_type="dataProduct",
            endpoint=ENDPOINTS["dataProduct"],
            fqn=target,
            dataswamp_id=asset_id,
            create={
                "name": om_fqn.name_of(target),
                "description": _description(
                    record.get("description"), f"DataSwamp data product {asset_id!r}."
                ),
                "domains": [om_fqn.domain_fqn(programme)],
                "extension": _asset_extension(
                    record,
                    entity_type="dataProduct",
                    contract=contracts.get(asset_id),
                    quality=quality_by_asset.get(asset_id, ()),
                    privileged=privileged,
                    expected_rules=source.expected_finding_rules.get(asset_id, ()),
                ),
                "tags": [
                    *(_tag_label(om_fqn.tag_fqn(facet)) for facet in sorted(set(facet_tags))),
                    *(
                        _tag_label(om_fqn.glossary_term_fqn(vocab, term), source="Glossary")
                        for vocab, term in _terms_for(record)
                    ),
                ],
            },
            references=_owner_reference(record),
        )
        emitted_products += 1

        components = record.get("component_dataset_ids")
        declared = (
            [item for item in components if isinstance(item, str)]
            if isinstance(components, list)
            else []
        )
        resolvable = sorted({item for item in declared if item in emitted_datasets})
        dropped_components += len(set(declared)) - len(resolvable)
        if resolvable:
            pending_attachments.append((target, asset_id, resolvable))

    for target, asset_id, resolvable in pending_attachments:
        builder.add(
            builder.entities,
            phase="data-product-assets",
            concept="data_product_components",
            entity_type="dataProduct",
            endpoint=ENDPOINTS["dataProductAssets"],
            fqn=target,
            dataswamp_id=asset_id,
            plan={
                "operation": "add-assets",
                "dataProduct": target,
                "assets": [
                    {"entityType": "container", "fullyQualifiedName": emitted_datasets[item]}
                    for item in resolvable
                ],
            },
            references=tuple(
                Reference(
                    field="assets",
                    entity_type="container",
                    target=emitted_datasets[item],
                    many=True,
                )
                for item in resolvable
            ),
        )
        attachment_records += 1
        attached_components += len(resolvable)

    # -- 14. lineage ----------------------------------------------------------
    emitted_edges = 0
    non_dataset_edges = 0
    dropped_edges = 0
    seen_edges: set[tuple[str, str]] = set()
    for edge in lineage_edges:
        upstream = _text(edge.get("upstream_id"))
        downstream = _text(edge.get("downstream_id"))
        if upstream not in emitted_datasets or downstream not in emitted_datasets:
            non_dataset_edges += 1
            continue
        if upstream == downstream:
            # Self-lineage is not a relationship, it is a corrupted edge. It is
            # dropped rather than emitted, and counted so the drop is visible.
            dropped_edges += 1
            continue
        key = (emitted_datasets[upstream], emitted_datasets[downstream])
        if key in seen_edges:
            dropped_edges += 1
            continue
        seen_edges.add(key)
        edge_type = _text(edge.get("edge_type"))
        builder.add(
            builder.lineage,
            phase="lineage",
            concept="dataset_lineage",
            entity_type="lineageEdge",
            endpoint=ENDPOINTS["lineage"],
            fqn=f"{key[0]}->{key[1]}",
            dataswamp_id=str(edge.get("id", "")),
            plan={
                "operation": "add-lineage",
                "fromEntity": {"entityType": "container", "fullyQualifiedName": key[0]},
                "toEntity": {"entityType": "container", "fullyQualifiedName": key[1]},
                # OpenMetadata's edge model has no typed-relationship field, so the
                # DataSwamp edge type is carried in the description rather than
                # asserted as a native relationship kind it does not have.
                "description": f"DataSwamp lineage edge type: {edge_type or 'unspecified'}.",
                "dataswampEdgeType": edge_type,
            },
            references=(
                Reference(field="fromEntity", entity_type="container", target=key[0]),
                Reference(field="toEntity", entity_type="container", target=key[1]),
            ),
        )
        emitted_edges += 1

    # -- 15. deferred quality-check result plan -------------------------------
    # No TestCase exists to attach a result to, for the reason recorded in
    # mapping-coverage.json. The facts and the blocker travel together rather
    # than the results silently disappearing from the export.
    for check in sorted(quality_checks, key=lambda row: str(row.get("id", ""))):
        asset_id = _text(check.get("asset_id"))
        if asset_id not in emitted_datasets:
            continue
        builder.add(
            builder.test_results,
            phase="test-result",
            concept="quality_check_result",
            entity_type="testCaseResult",
            endpoint="",
            fqn=emitted_datasets[asset_id],
            dataswamp_id=str(check.get("id", "")),
            plan={
                "operation": "record-test-result",
                "status": "blocked",
                "blockedBy": (
                    "No OpenMetadata TestCase exists to attach this result to: "
                    "TestDefinition.entityType admits only TABLE and COLUMN, and this "
                    "adapter deliberately invents no Table. See mapping-coverage.json."
                ),
                "target": {
                    "entityType": "container",
                    "fullyQualifiedName": emitted_datasets[asset_id],
                },
                "checkType": _text(check.get("check_type")),
                "checkStatus": _text(check.get("status")),
                "evidence": _text(check.get("evidence")),
                "evaluatedAt": _text(check.get("evaluated_at")),
            },
        )

    # -- coverage --------------------------------------------------------------
    scoped_checks = sum(
        1 for check in quality_checks if _text(check.get("asset_id")) in emitted_datasets
    )
    counts: dict[str, ConceptCounts] = {
        "company": ConceptCounts(source=1, emitted=1),
        "programme": ConceptCounts(source=len(programmes), emitted=len(programmes)),
        "study": ConceptCounts(source=len(study_programme), emitted=len(study_programme)),
        "dataset": ConceptCounts(
            source=len(datasets),
            emitted=len(emitted_datasets),
            dropped=len(datasets) - len(emitted_datasets),
        ),
        "physical_file": ConceptCounts(
            source=len(files), emitted=emitted_files, dropped=dropped_files
        ),
        "data_product": ConceptCounts(
            source=len(products), emitted=emitted_products, dropped=dropped_products
        ),
        "data_product_components": ConceptCounts(
            source=attached_components + dropped_components,
            emitted=attachment_records,
            dropped=dropped_components,
        ),
        "team": ConceptCounts(source=len(teams), emitted=len(teams)),
        "ownership": ConceptCounts(
            source=sum(1 for record in assets if _text(record.get("owner_ref"))),
            emitted=sum(1 for record in assets if _text(record.get("owner_ref"))),
        ),
        "stewardship": ConceptCounts(
            source=sum(len(_steward_ids(record)) for record in assets),
            emitted=sum(len(_steward_ids(record)) for record in assets),
        ),
        "controlled_vocabulary": ConceptCounts(
            source=len({name for name, _ in vocab_terms}),
            emitted=len({name for name, _ in vocab_terms}),
        ),
        "vocabulary_term": ConceptCounts(source=len(vocab_terms), emitted=len(vocab_terms)),
        "facet_tag": ConceptCounts(source=len(facets), emitted=len(facets)),
        "data_contract": ConceptCounts(source=len(contracts), emitted=len(contracts)),
        "dataset_lineage": ConceptCounts(
            source=emitted_edges + dropped_edges,
            emitted=emitted_edges,
            dropped=dropped_edges,
        ),
        "file_containment": ConceptCounts(source=emitted_files, emitted=emitted_files),
        "quality_check": ConceptCounts(
            source=len(quality_checks), emitted=0, dropped=len(quality_checks)
        ),
        "quality_check_result": ConceptCounts(
            source=len(quality_checks),
            emitted=scoped_checks,
            dropped=len(quality_checks) - scoped_checks,
        ),
        # The scientific-provenance shards are never read by either mode's source
        # graph, so their source counts are honestly zero here rather than
        # guessed at. The rows exist so the omission is visible and classified.
        "subject": ConceptCounts(),
        "biospecimen": ConceptCounts(),
        "assay": ConceptCounts(),
        "instrument_run": ConceptCounts(),
        "pipeline_run": ConceptCounts(),
        "non_dataset_lineage": ConceptCounts(
            source=non_dataset_edges, emitted=0, dropped=non_dataset_edges
        ),
    }

    return ExportPlan(
        mode=source.mode,
        custom_properties=tuple(builder.custom_properties),
        entities=tuple(builder.entities),
        lineage=tuple(builder.lineage),
        test_results=tuple(builder.test_results),
        coverage=build_coverage(counts),
    )


def plan_records(plan: ExportPlan) -> Iterable[dict[str, Any]]:
    """Yield every plan record as canonical JSON-able dicts, in load order."""
    for record in plan.records:
        yield record.as_json()


__all__ = [
    "OM_ADAPTER_VERSION",
    "OPENMETADATA_SCHEMA_TARGET",
    "OPENMETADATA_SCHEMA_COMMIT",
    "OPENMETADATA_MODEL_TARGET_RANGE",
    "VERIFIED_OPENMETADATA_VERSION",
    "TAG_SYNTHETIC",
    "TAG_PRIVILEGED",
    "TRUTH_ONLY_PROPERTY_PREFIX",
    "DOMAIN_TYPE",
    "TEAM_TYPE",
    "FILE_FORMATS",
    "VOCABULARY_FIELDS",
    "VOCABULARY_LIST_FIELDS",
    "ENDPOINTS",
    "PHASES",
    "BUILTIN_REFERENCES",
    "ExportMode",
    "Reference",
    "PlanRecord",
    "ExportPlan",
    "SourceGraph",
    "property_specs",
    "build_plan",
    "plan_records",
]
