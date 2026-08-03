"""Deterministic DataHub URNs derived from stable DataSwamp identifiers.

Identity is the part of a catalogue integration that is expensive to get wrong:
if a URN moves, re-ingesting the same benchmark produces a second copy of the
estate instead of updating the first. So every URN here is a pure function of a
**stable DataSwamp id** — never of a title, description, owner or any other
field a defect could plausibly mutate. Two exports of the same entity produce the
same URN in any process, on any machine, in any order.

Two URN shapes exist, because DataHub itself has two:

*Transparent* URNs embed the id directly (datasets, data products, groups,
glossary terms, domains, tags). Recovering the DataSwamp id is a string
operation, which :func:`decode_id` performs.

*Key-hashed* URNs are required where DataHub models identity as a GUID over a
key aspect (containers, assertions). Those are not reversible by construction,
so every emitted entity of that kind additionally carries its DataSwamp id in a
custom property — traceability without pretending the hash is invertible.

Ids in this project are lowercase kebab-case slugs, which are already safe in
every URN position. :func:`encode_id` nevertheless escapes anything outside that
alphabet, because an *observed* graph is deliberately allowed to contain values
the strict truth models forbid, and a defect must never be able to inject a
comma or a parenthesis into a URN.
"""

from __future__ import annotations

import re
from hashlib import sha256

# The catalogue platform every DataSwamp asset is published under.
PLATFORM_ID = "dataswamp"
PLATFORM_URN = f"urn:li:dataPlatform:{PLATFORM_ID}"

# DataHub's fabric/environment axis. A synthetic benchmark has exactly one.
FABRIC = "PROD"

# Prefix on every dataset name, so DataSwamp assets never collide with anything
# else a user has ingested under a differently-configured platform.
NAMESPACE = "dataswamp_biosystems"

# Length of the hex GUID used for key-hashed URNs. 32 hex characters (128 bits)
# matches DataHub's own container/assertion GUID width.
GUID_LENGTH = 32

_SAFE = re.compile(r"[a-z0-9-]")


def encode_id(value: str) -> str:
    """Return ``value`` in the URN-safe alphabet, reversibly.

    Characters outside ``[a-z0-9-]`` become ``~`` followed by two lowercase hex
    digits per UTF-8 byte; ``~`` itself is escaped the same way, so the encoding
    is injective and :func:`decode_id` inverts it exactly. An empty input is
    rejected rather than silently producing an empty URN component.
    """
    if not value:
        raise ValueError("cannot build a URN component from an empty identifier")
    out: list[str] = []
    for char in value:
        if _SAFE.fullmatch(char):
            out.append(char)
        else:
            out.extend(f"~{byte:02x}" for byte in char.encode("utf-8"))
    return "".join(out)


def decode_id(value: str) -> str:
    """Invert :func:`encode_id`."""
    out = bytearray()
    index = 0
    while index < len(value):
        char = value[index]
        if char == "~":
            out.append(int(value[index + 1 : index + 3], 16))
            index += 3
        else:
            out.extend(char.encode("utf-8"))
            index += 1
    return out.decode("utf-8")


def _guid(kind: str, entity_id: str) -> str:
    """Return the deterministic GUID for a key-hashed URN.

    The digest input is namespaced by ``kind`` so two different entity families
    sharing an id can never collide, and prefixed by the platform so a DataSwamp
    GUID cannot collide with an unrelated producer's.
    """
    key = f"{PLATFORM_ID}:{kind}:{entity_id}"
    return sha256(key.encode("utf-8")).hexdigest()[:GUID_LENGTH]


def dataset_name(asset_id: str) -> str:
    """Return the platform-scoped dataset name for a DataSwamp asset id."""
    return f"{NAMESPACE}.{encode_id(asset_id)}"


def dataset_urn(asset_id: str) -> str:
    """Return the dataset URN for a DataSwamp dataset id."""
    return f"urn:li:dataset:({PLATFORM_URN},{dataset_name(asset_id)},{FABRIC})"


def data_product_urn(asset_id: str) -> str:
    """Return the data-product URN for a DataSwamp data-product id."""
    return f"urn:li:dataProduct:{PLATFORM_ID}.{encode_id(asset_id)}"


def corp_group_urn(team_id: str) -> str:
    """Return the group URN for a DataSwamp owning/stewarding team id."""
    return f"urn:li:corpGroup:{encode_id(team_id)}"


def glossary_term_urn(vocabulary: str, term_id: str) -> str:
    """Return the glossary-term URN for one controlled-vocabulary term."""
    return f"urn:li:glossaryTerm:{PLATFORM_ID}.{encode_id(vocabulary)}.{encode_id(term_id)}"


def glossary_node_urn(vocabulary: str) -> str:
    """Return the glossary-node URN standing for one controlled vocabulary."""
    return f"urn:li:glossaryNode:{PLATFORM_ID}.{encode_id(vocabulary)}"


def domain_urn(programme_id: str) -> str:
    """Return the domain URN for a DataSwamp programme id."""
    return f"urn:li:domain:{PLATFORM_ID}.{encode_id(programme_id)}"


def tag_urn(tag: str) -> str:
    """Return the tag URN for a DataSwamp-derived tag."""
    return f"urn:li:tag:{encode_id(tag)}"


def container_urn(study_id: str) -> str:
    """Return the container URN for a DataSwamp study id (key-hashed)."""
    return f"urn:li:container:{_guid('study', study_id)}"


def assertion_urn(check_id: str) -> str:
    """Return the assertion URN for a DataSwamp quality-check id (key-hashed)."""
    return f"urn:li:assertion:{_guid('quality-check', check_id)}"


def dataset_id_from_urn(urn: str) -> str:
    """Recover the DataSwamp asset id from a dataset URN built by :func:`dataset_urn`."""
    match = re.fullmatch(
        rf"urn:li:dataset:\({re.escape(PLATFORM_URN)},{re.escape(NAMESPACE)}\.(.+),{FABRIC}\)", urn
    )
    if match is None:
        raise ValueError(f"{urn!r} is not a DataSwamp dataset URN")
    return decode_id(match.group(1))


__all__ = [
    "PLATFORM_ID",
    "PLATFORM_URN",
    "FABRIC",
    "NAMESPACE",
    "GUID_LENGTH",
    "encode_id",
    "decode_id",
    "dataset_name",
    "dataset_urn",
    "data_product_urn",
    "corp_group_urn",
    "glossary_term_urn",
    "glossary_node_urn",
    "domain_urn",
    "tag_urn",
    "container_urn",
    "assertion_urn",
    "dataset_id_from_urn",
]
