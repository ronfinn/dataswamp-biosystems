"""Read a catalogue's state back, so it can be compared against what was sent.

Strictly read-only, and strictly unprivileged: this module opens no bundle, no
defect ledger, no rule scope, no scenario file, no expected finding or
remediation and no control partition. Its only inputs are a verified emitted
export and a client.

Two retrieval paths exist because DataHub has two, and conflating them would
quietly drop an aspect from the round-trip:

*Versioned* aspects are read in one call per entity, requesting everything the
catalogue holds rather than only what was sent — which is what makes an *extra*
aspect visible instead of invisible.

*Timeseries* aspects (see
:data:`~dataswamp_biosystems.adapters.datahub.client.TIMESERIES_ASPECTS`) are
read individually through their own endpoint, and only their latest value is
compared. The adapter emits exactly one run event per quality check, so a series
is not something it can produce; that is a stated limitation rather than a
pretence of series-level verification.

Extra-entity enumeration runs only for families whose URN prefix unambiguously
identifies DataSwamp — see
:data:`~dataswamp_biosystems.adapters.datahub.roundtrip.ENTITY_FAMILIES`. The
families that are scanned are recorded on the result, so the report can state
that coverage for the rest is *unavailable* rather than implying it was clean.
"""

from __future__ import annotations

from dataswamp_biosystems.adapters.datahub.client import TIMESERIES_ASPECTS, DataHubClient
from dataswamp_biosystems.adapters.datahub.ingest import LoadedExport
from dataswamp_biosystems.adapters.datahub.roundtrip import (
    SCANNABLE_FAMILIES,
    Readback,
    RetrievedAspect,
)


def read_back(
    export: LoadedExport, client: DataHubClient, *, scan_namespace: bool = True
) -> Readback:
    """Retrieve everything needed to judge the four round-trip claims."""
    entity_types: dict[str, str] = {}
    timeseries_wanted: set[tuple[str, str]] = set()
    for proposal in export.proposals:
        urn = str(proposal["entityUrn"])
        entity_types[urn] = str(proposal["entityType"])
        aspect_name = str(proposal["aspectName"])
        if aspect_name in TIMESERIES_ASPECTS:
            timeseries_wanted.add((urn, aspect_name))

    aspects: list[RetrievedAspect] = []
    for urn in sorted(entity_types):
        entity_type = entity_types[urn]
        for aspect_name, payload in sorted(client.fetch_aspects(entity_type, urn).items()):
            aspects.append(RetrievedAspect(entity_type, urn, aspect_name, payload))

    for urn, aspect_name in sorted(timeseries_wanted):
        entity_type = entity_types[urn]
        if any(a.entity_urn == urn and a.aspect_name == aspect_name for a in aspects):
            continue  # Already returned alongside the versioned aspects.
        payload = client.fetch_timeseries_aspect(entity_type, urn, aspect_name)
        if payload is not None:
            aspects.append(RetrievedAspect(entity_type, urn, aspect_name, payload))

    scanned: set[str] = set()
    namespace_urns: set[str] = set()
    if scan_namespace:
        for family in SCANNABLE_FAMILIES:
            for urn in client.scroll_urns(family.entity_type):
                if family.owns(urn):
                    namespace_urns.add(urn)
            scanned.add(family.entity_type)

    return Readback(
        aspects=tuple(sorted(aspects, key=lambda a: (a.entity_urn, a.aspect_name))),
        scanned_families=frozenset(scanned),
        namespace_urns=frozenset(namespace_urns),
    )


__all__ = ["read_back"]
