"""Map DataSwamp benchmark entities onto DataHub entities and aspects.

The mapping is a pure function of one *source graph* — a shard-keyed collection
of records read from a bundle — and produces an ordered list of Metadata Change
Proposals. It performs no I/O, holds no state and consults no clock, so the same
source graph always yields byte-identical output.

Two modes exist and they differ in **what they are allowed to read**, not merely
in what they choose to emit:

``observed``
    Built from ``observed/observed-graph.json`` alone. The expected findings,
    expected remediations, control partition, rule scope, defect instances and
    mutation log are never opened. An agent under test can be handed this export
    without leaking which entities carry defects.
``truth``
    Built from the ``truth/`` shards, optionally annotated with the ground-truth
    labels. Every entity is tagged privileged and the export manifest says so.

What DataHub cannot represent is documented rather than distorted — see
``docs/datahub.md``. Notably: subjects, biospecimens, assays and runs have no
catalogue analogue and are not emitted; the truth graph carries no field-level
schema, so no ``schemaMetadata`` is invented for it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from dataswamp_biosystems.adapters.datahub import urns

# Bumped when the emitted payload changes for unchanged input.
ADAPTER_VERSION = "1.0.0"

# The DataHub metadata model this adapter targets. Aspect names and payload
# shapes below are the file-source ("MetadataChangeProposal") representation of
# these aspects, which has been stable across DataHub releases in this range.
DATAHUB_MODEL_VERSION = ">=0.13,<2"

CHANGE_TYPE = "UPSERT"

# A synthetic, non-personal actor for the audit stamps DataHub's model requires.
# Time is fixed at the epoch: an audit stamp is mandatory in the schema but
# carries no benchmark meaning, and a wall clock here would destroy determinism.
AUDIT_ACTOR = f"urn:li:corpuser:{urns.PLATFORM_ID}"
AUDIT_STAMP: dict[str, Any] = {"time": 0, "actor": AUDIT_ACTOR}

TAG_PRIVILEGED = "dataswamp-privileged-truth-export"
TAG_SYNTHETIC = "dataswamp-synthetic"

# Custom-property keys that only ever appear in a privileged truth export.
# The observed validator asserts their absence, so a future mapping change that
# leaked one would fail the suite rather than the benchmark.
TRUTH_ONLY_PROPERTY_PREFIX = "dataswamp_truth_"

# Asset fields that reference a controlled vocabulary, and the vocabulary each
# belongs to. Drives glossary-term emission.
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


class ExportMode(StrEnum):
    """What a DataHub export is allowed to contain."""

    OBSERVED = "observed"
    TRUTH = "truth"


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


def _mcp(entity_type: str, urn: str, aspect_name: str, aspect: dict[str, Any]) -> dict[str, Any]:
    """Build one Metadata Change Proposal in DataHub's file-source shape."""
    return {
        "entityType": entity_type,
        "entityUrn": urn,
        "changeType": CHANGE_TYPE,
        "aspectName": aspect_name,
        "aspect": {"json": aspect},
    }


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


def _epoch_millis(value: Any) -> int:
    """Return a UTC timestamp in milliseconds, or 0 when unparseable.

    Derived from the record's own recorded time — never from a clock — so it
    stays deterministic. A defect that corrupts a timestamp yields 0 rather than
    an exception; the catalogue seeing a nonsense time is the point.
    """
    if not isinstance(value, str) or not value:
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return int(parsed.timestamp() * 1000)


def _terms_for(record: Mapping[str, Any]) -> list[str]:
    """Return the glossary-term URNs one asset record references, sorted."""
    terms: set[str] = set()
    for field_name, vocabulary in VOCABULARY_FIELDS.items():
        value = record.get(field_name)
        if isinstance(value, str) and value:
            terms.add(urns.glossary_term_urn(vocabulary, value))
    for field_name, vocabulary in VOCABULARY_LIST_FIELDS.items():
        values = record.get(field_name)
        if isinstance(values, list):
            terms.update(
                urns.glossary_term_urn(vocabulary, item)
                for item in values
                if isinstance(item, str) and item
            )
    return sorted(terms)


def _tags_for(record: Mapping[str, Any]) -> list[str]:
    """Return the tag values one asset carries, sorted.

    Tags are the *coarse* facets a catalogue user browses by; the precise
    controlled-vocabulary values are glossary terms, not tags, so the two do not
    duplicate each other.
    """
    tags = {TAG_SYNTHETIC}
    for field_name in ("modality_group", "quality_status"):
        value = record.get(field_name)
        if isinstance(value, str) and value:
            tags.add(f"{field_name.replace('_', '-')}-{value}")
    if record.get("is_reference") is True:
        tags.add("reference-dataset")
    return sorted(tags)


def _ownership(record: Mapping[str, Any]) -> dict[str, Any]:
    """Map owner and steward references onto DataHub ownership.

    Owner and stewards are distinct ownership *types*, not one flattened list:
    collapsing them would lose exactly the distinction the governance benchmark
    is testing for.
    """
    owners: list[dict[str, Any]] = []
    owner_ref = record.get("owner_ref")
    if isinstance(owner_ref, str) and owner_ref:
        owners.append({"owner": urns.corp_group_urn(owner_ref), "type": "DATAOWNER"})
    stewards = record.get("steward_refs")
    if isinstance(stewards, list):
        owners.extend(
            {"owner": urns.corp_group_urn(steward), "type": "DATA_STEWARD"}
            for steward in sorted({s for s in stewards if isinstance(s, str) and s})
        )
    return {"owners": owners, "lastModified": dict(AUDIT_STAMP)}


def _asset_custom_properties(
    record: Mapping[str, Any], contract: Mapping[str, Any] | None
) -> dict[str, str]:
    """Return the custom properties every catalogue asset carries.

    ``dataswamp_id`` is the traceability anchor required by the URN contract: it
    survives round-tripping through DataHub even where the URN itself is a GUID.
    """
    properties: dict[str, str] = {
        "dataswamp_id": _text(record.get("id")),
        "dataswamp_entity_type": _text(record.get("asset_type")),
        "dataswamp_programme_id": _text(record.get("programme_id")),
        "dataswamp_study_id": _text(record.get("study_id")),
        "dataswamp_modality": _text(record.get("modality")),
        "dataswamp_modality_group": _text(record.get("modality_group")),
        "dataswamp_version": _text(record.get("version")),
        "dataswamp_lifecycle_stage": _text(record.get("lifecycle_stage")),
        "dataswamp_access_classification": _text(record.get("access_classification")),
        "dataswamp_retention_class": _text(record.get("retention_class")),
        "dataswamp_model_training_status": _text(record.get("model_training_status")),
        "dataswamp_intended_uses": _text(record.get("intended_uses")),
        "dataswamp_quality_status": _text(record.get("quality_status")),
        "dataswamp_synthetic": "true",
    }
    for key in ("physical_bytes", "logical_bytes", "record_count"):
        if key in record:
            properties[f"dataswamp_{key}"] = _text(record.get(key))
    if contract is not None:
        properties.update(
            {
                "dataswamp_contract_id": _text(contract.get("id")),
                "dataswamp_contract_version": _text(contract.get("contract_version")),
                "dataswamp_schema_ref": _text(contract.get("schema_ref")),
                "dataswamp_sla": _text(contract.get("sla")),
            }
        )
    return dict(sorted(properties.items()))


def _upstreams(dataset_urns: Iterable[str], upstream_type: str) -> list[dict[str, Any]]:
    return [
        {"auditStamp": dict(AUDIT_STAMP), "dataset": urn, "type": upstream_type}
        for urn in sorted(dataset_urns)
    ]


def build_mcps(source: SourceGraph) -> list[dict[str, Any]]:
    """Return every Metadata Change Proposal for ``source``, in deterministic order.

    Emission order is: referenced vocabulary and organisational entities first
    (glossary, domains, containers, groups, tags), then files, datasets, data
    products and assertions. That ordering is not required by DataHub — file
    ingestion resolves references regardless — but it makes the output readable
    and keeps every referenced URN defined before it is used.
    """
    privileged = source.mode is ExportMode.TRUTH
    mcps: list[dict[str, Any]] = []

    datasets = source.records("datasets")
    products = source.records("data_products")
    assets = [*datasets, *products]
    files = source.records("files")
    contracts = {
        str(row.get("asset_id", "")): row
        for row in source.records("contracts")
        if isinstance(row.get("asset_id"), str)
    }
    quality_checks = source.records("quality_checks")
    lineage = source.records("lineage")

    # -- vocabulary, organisation and structural entities ---------------------
    vocab_terms: set[tuple[str, str]] = set()
    for record in assets:
        for field_name, vocabulary in VOCABULARY_FIELDS.items():
            value = record.get(field_name)
            if isinstance(value, str) and value:
                vocab_terms.add((vocabulary, value))
        for field_name, vocabulary in VOCABULARY_LIST_FIELDS.items():
            values = record.get(field_name)
            if isinstance(values, list):
                vocab_terms.update(
                    (vocabulary, item) for item in values if isinstance(item, str) and item
                )

    for vocabulary in sorted({name for name, _ in vocab_terms}):
        mcps.append(
            _mcp(
                "glossaryNode",
                urns.glossary_node_urn(vocabulary),
                "glossaryNodeInfo",
                {
                    "name": vocabulary,
                    "definition": f"DataSwamp controlled vocabulary: {vocabulary}.",
                },
            )
        )
    for vocabulary, term in sorted(vocab_terms):
        mcps.append(
            _mcp(
                "glossaryTerm",
                urns.glossary_term_urn(vocabulary, term),
                "glossaryTermInfo",
                {
                    "name": term,
                    "definition": f"DataSwamp {vocabulary} term {term!r}.",
                    "termSource": "INTERNAL",
                    "parentNode": urns.glossary_node_urn(vocabulary),
                    "customProperties": {"dataswamp_id": term, "dataswamp_vocabulary": vocabulary},
                },
            )
        )

    programmes = sorted(
        {
            str(record["programme_id"])
            for record in assets
            if isinstance(record.get("programme_id"), str) and record["programme_id"]
        }
    )
    for programme in programmes:
        mcps.append(
            _mcp(
                "domain",
                urns.domain_urn(programme),
                "domainProperties",
                {
                    "name": programme,
                    "description": f"DataSwamp research programme {programme!r}.",
                    "customProperties": {"dataswamp_id": programme},
                },
            )
        )

    studies = sorted(
        {str(r["study_id"]) for r in assets if isinstance(r.get("study_id"), str) and r["study_id"]}
    )
    study_programme = {
        str(r.get("study_id")): str(r.get("programme_id", ""))
        for r in sorted(assets, key=lambda row: str(row.get("id", "")))
        if isinstance(r.get("study_id"), str)
    }
    for study in studies:
        container = urns.container_urn(study)
        mcps.append(
            _mcp(
                "container",
                container,
                "containerProperties",
                {
                    "name": study,
                    "description": f"DataSwamp study {study!r}.",
                    # The GUID URN is not reversible, so the id travels here.
                    "customProperties": {"dataswamp_id": study, "dataswamp_entity_type": "study"},
                },
            )
        )
        mcps.append(_mcp("container", container, "subTypes", {"typeNames": ["Study"]}))
        programme = study_programme.get(study, "")
        if programme:
            mcps.append(
                _mcp(
                    "container",
                    container,
                    "domains",
                    {"domains": [urns.domain_urn(programme)]},
                )
            )

    teams: set[str] = set()
    for record in assets:
        owner = record.get("owner_ref")
        if isinstance(owner, str) and owner:
            teams.add(owner)
        stewards = record.get("steward_refs")
        if isinstance(stewards, list):
            teams.update(s for s in stewards if isinstance(s, str) and s)
    for team in sorted(teams):
        mcps.append(
            _mcp(
                "corpGroup",
                urns.corp_group_urn(team),
                "corpGroupInfo",
                {
                    "displayName": team,
                    "description": f"DataSwamp owning/stewarding team {team!r}.",
                    "admins": [],
                    "members": [],
                    "groups": [],
                },
            )
        )

    tags: set[str] = {TAG_SYNTHETIC}
    for record in assets:
        tags.update(_tags_for(record))
    if privileged:
        tags.add(TAG_PRIVILEGED)
    for tag in sorted(tags):
        mcps.append(
            _mcp(
                "tag",
                urns.tag_urn(tag),
                "tagProperties",
                {"name": tag, "description": f"DataSwamp facet {tag!r}."},
            )
        )

    # -- physical files as file-subtype datasets ------------------------------
    dataset_ids = {str(record.get("id")) for record in datasets}
    files_by_dataset: dict[str, list[str]] = {}
    dataset_study = {str(record.get("id")): str(record.get("study_id", "")) for record in datasets}
    for record in files:
        file_id = str(record.get("id", ""))
        if not file_id:
            continue
        parent = _text(record.get("dataset_id"))
        urn = urns.dataset_urn(file_id)
        files_by_dataset.setdefault(parent, []).append(urn)
        properties = {
            "dataswamp_id": file_id,
            "dataswamp_entity_type": "file",
            "dataswamp_dataset_id": parent,
            "dataswamp_relative_path": _text(record.get("relative_path")),
            "dataswamp_file_format": _text(record.get("file_format")),
            "dataswamp_physical_bytes": _text(record.get("physical_bytes")),
            "dataswamp_checksum": _text(record.get("checksum")),
            "dataswamp_producing_run_id": _text(record.get("producing_run_id")),
            "dataswamp_synthetic": "true",
        }
        mcps.append(
            _mcp(
                "dataset",
                urn,
                "datasetProperties",
                {
                    "name": file_id,
                    "qualifiedName": urns.dataset_name(file_id),
                    "description": (
                        f"Physical file {_text(record.get('relative_path'))} "
                        f"belonging to dataset {parent}."
                    ),
                    "customProperties": dict(sorted(properties.items())),
                },
            )
        )
        mcps.append(_mcp("dataset", urn, "subTypes", {"typeNames": ["File"]}))
        mcps.append(_mcp("dataset", urn, "status", {"removed": False}))
        study = dataset_study.get(parent, "")
        if study:
            mcps.append(_mcp("dataset", urn, "container", {"container": urns.container_urn(study)}))

    # -- lineage between catalogue entities -----------------------------------
    product_components: dict[str, list[str]] = {}
    for record in products:
        components = record.get("component_dataset_ids")
        if isinstance(components, list):
            product_components[str(record.get("id"))] = [
                str(item) for item in components if isinstance(item, str)
            ]

    derived: dict[str, set[str]] = {}
    for edge in lineage:
        upstream = _text(edge.get("upstream_id"))
        downstream = _text(edge.get("downstream_id"))
        if upstream in dataset_ids and downstream in dataset_ids and upstream != downstream:
            derived.setdefault(downstream, set()).add(urns.dataset_urn(upstream))

    # -- datasets --------------------------------------------------------------
    for record in datasets:
        asset_id = str(record.get("id", ""))
        if not asset_id:
            continue
        urn = urns.dataset_urn(asset_id)
        contract = contracts.get(asset_id)
        properties = _asset_custom_properties(record, contract)
        if privileged:
            rules = source.expected_finding_rules.get(asset_id, ())
            properties[f"{TRUTH_ONLY_PROPERTY_PREFIX}expected_finding_rules"] = ",".join(
                sorted(rules)
            )
            properties[f"{TRUTH_ONLY_PROPERTY_PREFIX}export"] = "true"
        mcps.append(
            _mcp(
                "dataset",
                urn,
                "datasetProperties",
                {
                    "name": asset_id,
                    "qualifiedName": urns.dataset_name(asset_id),
                    "description": _text(record.get("description")),
                    "customProperties": dict(sorted(properties.items())),
                },
            )
        )
        mcps.append(_mcp("dataset", urn, "subTypes", {"typeNames": ["Dataset"]}))
        mcps.append(_mcp("dataset", urn, "status", {"removed": False}))
        mcps.append(_mcp("dataset", urn, "ownership", _ownership(record)))
        asset_tags = [*_tags_for(record), *([TAG_PRIVILEGED] if privileged else [])]
        mcps.append(
            _mcp(
                "dataset",
                urn,
                "globalTags",
                {"tags": [{"tag": urns.tag_urn(tag)} for tag in sorted(set(asset_tags))]},
            )
        )
        mcps.append(
            _mcp(
                "dataset",
                urn,
                "glossaryTerms",
                {
                    "terms": [{"urn": term} for term in _terms_for(record)],
                    "auditStamp": dict(AUDIT_STAMP),
                },
            )
        )
        programme = _text(record.get("programme_id"))
        if programme:
            mcps.append(_mcp("dataset", urn, "domains", {"domains": [urns.domain_urn(programme)]}))
        study = _text(record.get("study_id"))
        if study:
            mcps.append(_mcp("dataset", urn, "container", {"container": urns.container_urn(study)}))
        upstreams = [
            *_upstreams(files_by_dataset.get(asset_id, ()), "COPY"),
            *_upstreams(derived.get(asset_id, ()), "TRANSFORMED"),
        ]
        if upstreams:
            mcps.append(_mcp("dataset", urn, "upstreamLineage", {"upstreams": upstreams}))

    # -- data products ---------------------------------------------------------
    for record in products:
        asset_id = str(record.get("id", ""))
        if not asset_id:
            continue
        urn = urns.data_product_urn(asset_id)
        properties = _asset_custom_properties(record, contracts.get(asset_id))
        if privileged:
            rules = source.expected_finding_rules.get(asset_id, ())
            properties[f"{TRUTH_ONLY_PROPERTY_PREFIX}expected_finding_rules"] = ",".join(
                sorted(rules)
            )
            properties[f"{TRUTH_ONLY_PROPERTY_PREFIX}export"] = "true"
        components = [
            component
            for component in product_components.get(asset_id, [])
            if component in dataset_ids
        ]
        mcps.append(
            _mcp(
                "dataProduct",
                urn,
                "dataProductProperties",
                {
                    "name": asset_id,
                    "description": _text(record.get("description")),
                    "customProperties": dict(sorted(properties.items())),
                    "assets": [
                        {"destinationUrn": urns.dataset_urn(component)}
                        for component in sorted(components)
                    ],
                },
            )
        )
        mcps.append(_mcp("dataProduct", urn, "ownership", _ownership(record)))
        product_tags = [*_tags_for(record), *([TAG_PRIVILEGED] if privileged else [])]
        mcps.append(
            _mcp(
                "dataProduct",
                urn,
                "globalTags",
                {"tags": [{"tag": urns.tag_urn(tag)} for tag in sorted(set(product_tags))]},
            )
        )
        mcps.append(
            _mcp(
                "dataProduct",
                urn,
                "glossaryTerms",
                {
                    "terms": [{"urn": term} for term in _terms_for(record)],
                    "auditStamp": dict(AUDIT_STAMP),
                },
            )
        )
        programme = _text(record.get("programme_id"))
        if programme:
            mcps.append(
                _mcp("dataProduct", urn, "domains", {"domains": [urns.domain_urn(programme)]})
            )

    # -- quality checks as dataset assertions ---------------------------------
    for record in quality_checks:
        check_id = str(record.get("id", ""))
        asset_id = _text(record.get("asset_id"))
        if not check_id or asset_id not in dataset_ids:
            continue
        assertion = urns.assertion_urn(check_id)
        dataset = urns.dataset_urn(asset_id)
        mcps.append(
            _mcp(
                "assertion",
                assertion,
                "assertionInfo",
                {
                    "type": "DATASET",
                    "datasetAssertion": {
                        "dataset": dataset,
                        "scope": "DATASET_COLUMN",
                        "operator": "_NATIVE_",
                        "aggregation": "_NATIVE_",
                        "nativeType": _text(record.get("check_type")),
                    },
                    "description": _text(record.get("evidence")),
                    "customProperties": {
                        "dataswamp_id": check_id,
                        "dataswamp_asset_id": asset_id,
                        "dataswamp_check_type": _text(record.get("check_type")),
                        "dataswamp_status": _text(record.get("status")),
                    },
                },
            )
        )
        mcps.append(
            _mcp(
                "assertion",
                assertion,
                "assertionRunEvent",
                {
                    "timestampMillis": _epoch_millis(record.get("evaluated_at")),
                    "runId": check_id,
                    "assertionUrn": assertion,
                    "asserteeUrn": dataset,
                    "status": "COMPLETE",
                    "result": {
                        "type": "SUCCESS" if record.get("status") == "pass" else "FAILURE",
                        "nativeResults": {"evidence": _text(record.get("evidence"))},
                    },
                },
            )
        )

    return mcps


__all__ = [
    "ADAPTER_VERSION",
    "DATAHUB_MODEL_VERSION",
    "CHANGE_TYPE",
    "AUDIT_ACTOR",
    "AUDIT_STAMP",
    "TAG_PRIVILEGED",
    "TAG_SYNTHETIC",
    "TRUTH_ONLY_PROPERTY_PREFIX",
    "VOCABULARY_FIELDS",
    "VOCABULARY_LIST_FIELDS",
    "ExportMode",
    "SourceGraph",
    "build_mcps",
]
