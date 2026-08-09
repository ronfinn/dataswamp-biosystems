"""Read an OpenMetadata catalogue back, so it can be compared against what was sent.

Strictly read-only, and strictly unprivileged: this module opens no bundle, no
defect ledger, no rule scope, no scenario file, no expected finding or
remediation and no control partition. Its only inputs are a verified emitted
export and a client. There is no write function here, and there must never be
one — a readback that could repair what it is about to judge is not a readback.

**Addressed by FQN, never by UUID.** Every retrieval below asks for an entity by
the fully-qualified name the export declared. OpenMetadata's server-assigned
UUIDs appear in responses and are used for exactly one thing — turning the
UUID-keyed edges of an ``EntityLineage`` document back into the FQN pairs the
plan speaks in — and are never retained as DataSwamp identity. A benchmark whose
identity depended on which server it happened to be loaded into would not be a
benchmark.

**Absence is recorded, not smoothed over.** An entity the catalogue does not hold
comes back as ``None`` and reaches the comparison as a *missing* entity. A
retrieval that failed and a retrieval that found nothing must never be collapsed
into "equal", which is the failure mode that lets an empty-versus-empty
comparison masquerade as a clean round-trip.

**Enumeration is scoped, and its scope is recorded.** Only the families
:mod:`.roundtrip` can establish ownership for are enumerated, using the
server-side filters OpenMetadata actually offers where they exist. Which families
were scanned travels on the result, so the report can say that coverage for the
rest is *unavailable* rather than implying it was clean.
"""

from __future__ import annotations

from typing import Any

from dataswamp_biosystems.adapters.openmetadata.client import OpenMetadataClient
from dataswamp_biosystems.adapters.openmetadata.ingest import LoadedExport
from dataswamp_biosystems.adapters.openmetadata.roundtrip import (
    SCANNABLE_FAMILIES,
    Readback,
    build_sent_view,
)


def _lineage_pairs(document: dict[str, Any]) -> set[tuple[str, str]]:
    """Turn one ``EntityLineage`` document into FQN edge pairs.

    OpenMetadata keys lineage edges by entity UUID and lists the participating
    entities separately as ``nodes`` (plus the subject in ``entity``). The UUIDs
    are resolved through that node list and then discarded: an edge is reported
    as the FQN pair the emitted plan speaks in. An edge naming a UUID that is not
    in the node list is dropped rather than guessed at — an unresolvable endpoint
    would otherwise become a fabricated comparison input.
    """
    by_id: dict[str, str] = {}
    for node in [document.get("entity"), *(document.get("nodes") or [])]:
        if isinstance(node, dict):
            identifier = node.get("id")
            fqn = node.get("fullyQualifiedName")
            if isinstance(identifier, str) and isinstance(fqn, str):
                by_id[identifier] = fqn

    pairs: set[tuple[str, str]] = set()
    for key in ("upstreamEdges", "downstreamEdges"):
        for edge in document.get(key) or []:
            if not isinstance(edge, dict):
                continue
            source = by_id.get(str(edge.get("fromEntity")))
            target = by_id.get(str(edge.get("toEntity")))
            if source and target:
                pairs.add((source, target))
    return pairs


def read_back(
    export: LoadedExport,
    client: OpenMetadataClient,
    *,
    enumerate_namespace: bool = True,
) -> Readback:
    """Retrieve everything needed to judge the four round-trip claims."""
    entities, properties, assets, lineage = build_sent_view(export.records)

    retrieved: dict[tuple[str, str], dict[str, Any] | None] = {}
    for sent in entities:
        retrieved[(sent.entity_type, sent.fqn)] = client.get_by_name(sent.entity_type, sent.fqn)

    # Every custom property the type declares is read, not only the ones the
    # export registered, so a DataSwamp-namespaced property nobody sent is
    # visible as an extra rather than invisible.
    custom_properties: dict[str, dict[str, dict[str, Any]]] = {}
    for entity_type in sorted(properties):
        declared: dict[str, dict[str, Any]] = {}
        for item in client.get_custom_properties(entity_type):
            name = item.get("name")
            if isinstance(name, str):
                declared[name] = item
        custom_properties[entity_type] = declared

    data_product_assets: dict[str, list[str]] = {}
    for product in sorted(assets):
        attached = client.get_data_product_assets(product)
        if attached is None:
            continue
        data_product_assets[product] = sorted(
            str(item.get("fullyQualifiedName"))
            for item in attached
            if isinstance(item, dict) and isinstance(item.get("fullyQualifiedName"), str)
        )

    # Lineage is read from each endpoint the plan names. Both ends of every edge
    # are queried so a half-materialised edge — present from one side only — is
    # visible rather than averaged away.
    lineage_edges: set[tuple[str, str]] = set()
    endpoints = sorted({fqn for edge in lineage for fqn in edge})
    for fqn in endpoints:
        document = client.get_lineage("container", fqn)
        if document is not None:
            lineage_edges |= _lineage_pairs(document)

    enumerated: dict[str, set[str]] = {}
    scanned: set[str] = set()
    if enumerate_namespace:
        for family in SCANNABLE_FAMILIES:
            found: set[str] = set()
            for entry in client.list_entities(family.entity_type, family.params):
                listed = entry.get("fullyQualifiedName")
                if isinstance(listed, str):
                    found.add(listed)
            enumerated[family.entity_type] = found
            scanned.add(family.entity_type)

    return Readback(
        entities=retrieved,
        custom_properties=custom_properties,
        data_product_assets=data_product_assets,
        lineage_edges=lineage_edges,
        enumerated=enumerated,
        scanned_families=frozenset(scanned),
    )


__all__ = ["read_back"]
