"""Validate an emitted DataHub payload without a DataHub server.

Every check here is a property of the payload itself, so the adapter is provable
offline: URN shape and uniqueness, aspect completeness, reference closure, and —
the check that matters most for a benchmark — that an ``observed`` export carries
no privileged ground-truth field.

Problems are returned as a sorted list of human-readable strings, matching the
defect-registry validator's convention, so the CLI can print them directly.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from dataswamp_biosystems.adapters.datahub.mapping import (
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
)
from dataswamp_biosystems.adapters.datahub.urns import FABRIC, NAMESPACE, PLATFORM_URN, tag_urn

# One URN pattern per emitted entity type. A URN that does not match is either
# built from something other than a stable id or has had an unescaped character
# smuggled into it; both are identity bugs, so both fail here.
URN_PATTERNS: dict[str, re.Pattern[str]] = {
    "dataset": re.compile(
        rf"^urn:li:dataset:\({re.escape(PLATFORM_URN)},{re.escape(NAMESPACE)}\."
        rf"[a-z0-9~-]+,{FABRIC}\)$"
    ),
    "dataProduct": re.compile(r"^urn:li:dataProduct:dataswamp\.[a-z0-9~-]+$"),
    "corpGroup": re.compile(r"^urn:li:corpGroup:[a-z0-9~-]+$"),
    "glossaryTerm": re.compile(r"^urn:li:glossaryTerm:dataswamp\.[a-z0-9~-]+\.[a-z0-9~-]+$"),
    "glossaryNode": re.compile(r"^urn:li:glossaryNode:dataswamp\.[a-z0-9~-]+$"),
    "domain": re.compile(r"^urn:li:domain:dataswamp\.[a-z0-9~-]+$"),
    "tag": re.compile(r"^urn:li:tag:[a-z0-9~-]+$"),
    "container": re.compile(r"^urn:li:container:[0-9a-f]{32}$"),
    "assertion": re.compile(r"^urn:li:assertion:[0-9a-f]{32}$"),
}

# The aspects every entity of a given type must carry for the export to be
# usable in a catalogue rather than merely syntactically valid.
REQUIRED_ASPECTS: dict[str, frozenset[str]] = {
    "dataset": frozenset({"datasetProperties", "subTypes", "status"}),
    "dataProduct": frozenset({"dataProductProperties", "ownership"}),
    "corpGroup": frozenset({"corpGroupInfo"}),
    "glossaryTerm": frozenset({"glossaryTermInfo"}),
    "glossaryNode": frozenset({"glossaryNodeInfo"}),
    "domain": frozenset({"domainProperties"}),
    "tag": frozenset({"tagProperties"}),
    "container": frozenset({"containerProperties", "subTypes"}),
    "assertion": frozenset({"assertionInfo"}),
}

# Aspects a *catalogue asset* (not a file) must additionally carry.
ASSET_REQUIRED_ASPECTS: frozenset[str] = frozenset({"ownership", "globalTags", "glossaryTerms"})


def _referenced_urns(mcp: dict[str, Any]) -> list[str]:
    """Return every URN one proposal points at, excluding its own subject."""
    aspect = mcp.get("aspect", {}).get("json", {})
    referenced: list[str] = []
    if not isinstance(aspect, dict):
        return referenced
    for owner in aspect.get("owners", []) or []:
        if isinstance(owner, dict) and isinstance(owner.get("owner"), str):
            referenced.append(owner["owner"])
    for tag in aspect.get("tags", []) or []:
        if isinstance(tag, dict) and isinstance(tag.get("tag"), str):
            referenced.append(tag["tag"])
    for term in aspect.get("terms", []) or []:
        if isinstance(term, dict) and isinstance(term.get("urn"), str):
            referenced.append(term["urn"])
    referenced.extend(urn for urn in aspect.get("domains", []) or [] if isinstance(urn, str))
    if isinstance(aspect.get("container"), str):
        referenced.append(aspect["container"])
    if isinstance(aspect.get("parentNode"), str):
        referenced.append(aspect["parentNode"])
    for upstream in aspect.get("upstreams", []) or []:
        if isinstance(upstream, dict) and isinstance(upstream.get("dataset"), str):
            referenced.append(upstream["dataset"])
    for asset in aspect.get("assets", []) or []:
        if isinstance(asset, dict) and isinstance(asset.get("destinationUrn"), str):
            referenced.append(asset["destinationUrn"])
    dataset_assertion = aspect.get("datasetAssertion")
    if isinstance(dataset_assertion, dict) and isinstance(dataset_assertion.get("dataset"), str):
        referenced.append(dataset_assertion["dataset"])
    if isinstance(aspect.get("asserteeUrn"), str):
        referenced.append(aspect["asserteeUrn"])
    return referenced


def validate_export(mcps: Sequence[dict[str, Any]], mode: ExportMode) -> list[str]:
    """Return every problem with ``mcps``, or an empty list if the payload is sound."""
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    aspects_by_urn: dict[str, set[str]] = {}
    types_by_urn: dict[str, str] = {}
    subtypes_by_urn: dict[str, list[str]] = {}
    referenced: dict[str, str] = {}

    for index, mcp in enumerate(mcps):
        where = f"proposal {index + 1}"
        for key in ("entityType", "entityUrn", "changeType", "aspectName", "aspect"):
            if key not in mcp:
                problems.append(f"{where}: missing {key!r}")
        if any(key not in mcp for key in ("entityType", "entityUrn", "aspectName", "aspect")):
            continue
        entity_type = str(mcp["entityType"])
        urn = str(mcp["entityUrn"])
        aspect_name = str(mcp["aspectName"])
        if not isinstance(mcp["aspect"], dict) or "json" not in mcp["aspect"]:
            problems.append(f"{where}: aspect payload is not wrapped in a 'json' envelope")

        pattern = URN_PATTERNS.get(entity_type)
        if pattern is None:
            problems.append(f"{where}: unexpected entity type {entity_type!r}")
        elif not pattern.fullmatch(urn):
            problems.append(f"{where}: {urn!r} is not a well-formed {entity_type} URN")

        if (urn, aspect_name) in seen:
            problems.append(f"{where}: duplicate aspect {aspect_name!r} for {urn}")
        seen.add((urn, aspect_name))

        existing = types_by_urn.get(urn)
        if existing is not None and existing != entity_type:
            problems.append(f"{urn}: emitted as both {existing!r} and {entity_type!r}")
        types_by_urn[urn] = entity_type
        aspects_by_urn.setdefault(urn, set()).add(aspect_name)
        if aspect_name == "subTypes":
            names = mcp["aspect"].get("json", {}).get("typeNames", [])
            subtypes_by_urn[urn] = [str(name) for name in names]
        for target in _referenced_urns(mcp):
            referenced.setdefault(target, urn)

        payload = mcp["aspect"].get("json", {}) if isinstance(mcp["aspect"], dict) else {}
        properties = payload.get("customProperties", {}) if isinstance(payload, dict) else {}
        if isinstance(properties, dict):
            leaked = sorted(key for key in properties if key.startswith(TRUTH_ONLY_PROPERTY_PREFIX))
            if leaked and mode is ExportMode.OBSERVED:
                problems.append(
                    f"{where}: observed export leaks truth-only propert(ies) {', '.join(leaked)}"
                )

    if mode is ExportMode.OBSERVED:
        privileged_urn = tag_urn(TAG_PRIVILEGED)
        if privileged_urn in types_by_urn or privileged_urn in referenced:
            problems.append("observed export references the privileged truth-export tag")

    for urn, aspect_names in sorted(aspects_by_urn.items()):
        entity_type = types_by_urn[urn]
        missing = sorted(REQUIRED_ASPECTS.get(entity_type, frozenset()) - aspect_names)
        if missing:
            problems.append(f"{urn}: missing required aspect(s) {', '.join(missing)}")
        is_asset = entity_type == "dataset" and subtypes_by_urn.get(urn) != ["File"]
        if is_asset:
            missing_asset = sorted(ASSET_REQUIRED_ASPECTS - aspect_names)
            if missing_asset:
                problems.append(
                    f"{urn}: catalogue asset missing aspect(s) {', '.join(missing_asset)}"
                )
            if mode is ExportMode.TRUTH and privileged_tag_missing(urn, mcps):
                problems.append(f"{urn}: truth export is not tagged privileged")

    for target, source in sorted(referenced.items()):
        if target not in types_by_urn:
            problems.append(f"{source} references {target}, which is never emitted")

    return sorted(problems)


def privileged_tag_missing(urn: str, mcps: Sequence[dict[str, Any]]) -> bool:
    """Return whether ``urn``'s ``globalTags`` lacks the privileged truth-export tag."""
    privileged = tag_urn(TAG_PRIVILEGED)
    for mcp in mcps:
        if mcp.get("entityUrn") != urn or mcp.get("aspectName") != "globalTags":
            continue
        tags = mcp.get("aspect", {}).get("json", {}).get("tags", [])
        return not any(isinstance(tag, dict) and tag.get("tag") == privileged for tag in tags)
    return True


__all__ = [
    "URN_PATTERNS",
    "REQUIRED_ASPECTS",
    "ASSET_REQUIRED_ASPECTS",
    "validate_export",
    "privileged_tag_missing",
]
