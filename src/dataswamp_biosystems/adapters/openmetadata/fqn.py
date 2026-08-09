"""Deterministic OpenMetadata identities derived from stable DataSwamp ids.

OpenMetadata identifies entities two ways at once. Every entity has a
server-assigned ``id`` (a UUID) *and* a ``fullyQualifiedName`` built by joining
name segments with ``.``. Only the second is knowable offline, so the FQN is this
adapter's identity and the UUID is never used as one — an export that depended on
a UUID could not be written before the server had already seen it, which defeats
the point of an offline plan.

Every FQN here is therefore a pure function of **stable DataSwamp ids**. Never a
display title, a description, an owner, a checksum, a quality status or anything
else a defect could plausibly mutate: if an identity moved when a title changed,
re-loading the same benchmark would produce a second estate beside the first
instead of updating it.

Three properties are enforced rather than hoped for.

*Namespacing.* OpenMetadata's Domain, DataProduct, Team, Glossary and
Classification namespaces are **global** — there is no service to scope them
under, the way a Container is scoped under its StorageService. A bare
``genomics`` domain would collide with any other producer's. So every root-level
identity carries the ``dataswamp`` / ``dataswamp-biosystems`` prefix.

*Injectivity.* :func:`encode_id` is reversible, and :func:`decode_id` inverts it
exactly. This matters more than it looks: an *observed* graph is deliberately
allowed to hold values the strict truth models forbid, so a defect must never be
able to smuggle a ``.`` into a name and silently re-parent an entity, nor a ``"``
into an FQN segment and change how it tokenises.

*Hierarchy.* Container FQNs nest, so the parent of
``dataswamp-biosystems.study-a.ds-b`` is ``dataswamp-biosystems.study-a`` as a
string operation. :func:`parent_fqn` is that operation, and the plan validator
uses it to prove containment closure without a lookup table.

The codec below intentionally duplicates the DataHub adapter's escaping scheme.
That is a considered choice, not an oversight: the two adapters must be free to
diverge when their catalogues' rules diverge, and sharing a helper today would
buy a little brevity in exchange for a coupling that has to be undone later.
Nothing here imports from :mod:`dataswamp_biosystems.adapters.datahub`.
"""

from __future__ import annotations

import re

# The StorageService every DataSwamp container hangs under, and the root of every
# container FQN.
SERVICE_NAME = "dataswamp-biosystems"

# The prefix on every *root-level* identity in one of OpenMetadata's global
# namespaces (domains, data products, teams, glossaries, classifications).
NAMESPACE = "dataswamp"

# OpenMetadata's storage-service discriminator. ``CustomStorage`` is a real
# member of the upstream enum and is the honest choice here: the estate is not in
# S3, ADLS or GCS, and no storage connection is fabricated to pretend otherwise.
SERVICE_TYPE = "CustomStorage"

# The single Classification every DataSwamp facet tag lives under.
CLASSIFICATION_NAME = NAMESPACE

# The FQN segment separator, and the characters that must never survive into a
# segment because OpenMetadata gives them structural meaning.
SEPARATOR = "."

# OpenMetadata's ``entityName`` bound. Segments are checked against it here so an
# over-long observed value fails at identity construction rather than at load.
MAX_NAME_LENGTH = 256

_SAFE = re.compile(r"[a-z0-9-]")

# What an encoded segment may contain, by construction. The plan validator
# re-checks emitted names against this, so an identity that skipped the codec
# cannot reach an export.
SAFE_SEGMENT = re.compile(r"^[a-z0-9~-]+$")


def encode_id(value: str) -> str:
    """Return ``value`` in the FQN-safe alphabet, reversibly.

    Characters outside ``[a-z0-9-]`` become ``~`` followed by two lowercase hex
    digits per UTF-8 byte; ``~`` itself is escaped the same way, so the encoding
    is injective and :func:`decode_id` inverts it exactly. In particular the FQN
    separator ``.``, the quoting character ``"``, whitespace and the ``::``
    sequence OpenMetadata's ``entityName`` pattern forbids can never survive into
    a segment.

    An empty input is rejected rather than silently producing an empty segment,
    which would collapse two FQNs into one.
    """
    if not value:
        raise ValueError("cannot build an OpenMetadata name from an empty identifier")
    out: list[str] = []
    for char in value:
        if _SAFE.fullmatch(char):
            out.append(char)
        else:
            out.extend(f"~{byte:02x}" for byte in char.encode("utf-8"))
    encoded = "".join(out)
    if len(encoded) > MAX_NAME_LENGTH:
        raise ValueError(
            f"encoded name for {value!r} is {len(encoded)} characters, "
            f"over OpenMetadata's {MAX_NAME_LENGTH}-character entityName limit"
        )
    return encoded


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


def _join(*segments: str) -> str:
    return SEPARATOR.join(segments)


# -- containers: service -> study -> dataset -> file --------------------------


def service_fqn() -> str:
    """Return the StorageService FQN, which is also the container-hierarchy root."""
    return SERVICE_NAME


def study_fqn(study_id: str) -> str:
    """Return the container FQN for a DataSwamp study id."""
    return _join(SERVICE_NAME, encode_id(study_id))


def dataset_fqn(study_id: str, dataset_id: str) -> str:
    """Return the container FQN for a dataset inside its study."""
    return _join(SERVICE_NAME, encode_id(study_id), encode_id(dataset_id))


def file_fqn(study_id: str, dataset_id: str, file_id: str) -> str:
    """Return the container FQN for a physical file inside its dataset."""
    return _join(SERVICE_NAME, encode_id(study_id), encode_id(dataset_id), encode_id(file_id))


# -- globally-namespaced entities ---------------------------------------------


def domain_fqn(programme_id: str) -> str:
    """Return the Domain FQN for a DataSwamp programme id."""
    return f"{NAMESPACE}-{encode_id(programme_id)}"


def data_product_fqn(programme_id: str, product_id: str) -> str:
    """Return the DataProduct FQN for a product within its programme's domain.

    OpenMetadata's DataProduct name is globally unique in its own right, so the
    programme prefix is part of the *name*, not a parent path — but it is written
    with the same dotted shape so the domain a product belongs to is legible from
    its identity alone.
    """
    return f"{NAMESPACE}-{encode_id(programme_id)}{SEPARATOR}{encode_id(product_id)}"


def team_fqn(team_id: str) -> str:
    """Return the Team FQN for a DataSwamp owning/stewarding team id."""
    return f"{NAMESPACE}-{encode_id(team_id)}"


def glossary_fqn(vocabulary_id: str) -> str:
    """Return the Glossary FQN standing for one controlled vocabulary."""
    return f"{NAMESPACE}-{encode_id(vocabulary_id)}"


def glossary_term_fqn(vocabulary_id: str, term_id: str) -> str:
    """Return the GlossaryTerm FQN for one controlled-vocabulary term."""
    return f"{NAMESPACE}-{encode_id(vocabulary_id)}{SEPARATOR}{encode_id(term_id)}"


def classification_fqn() -> str:
    """Return the FQN of the single Classification DataSwamp facet tags live under."""
    return CLASSIFICATION_NAME


def tag_fqn(facet_id: str) -> str:
    """Return the Tag FQN for one DataSwamp facet."""
    return f"{CLASSIFICATION_NAME}{SEPARATOR}{encode_id(facet_id)}"


# -- names, parents and links -------------------------------------------------


def name_of(fqn: str) -> str:
    """Return the last segment of ``fqn`` — the entity's own ``name`` field."""
    return fqn.rsplit(SEPARATOR, 1)[-1]


def parent_fqn(fqn: str) -> str | None:
    """Return the containing FQN, or ``None`` for a root-level identity."""
    if SEPARATOR not in fqn:
        return None
    return fqn.rsplit(SEPARATOR, 1)[0]


def entity_link(entity_type: str, fqn: str) -> str:
    """Return an OpenMetadata ``entityLink`` for a whole entity.

    The shape is ``<#E::{entityType}::{fqn}>``, which is what OpenMetadata's
    ``entityLink`` pattern accepts for an entity-level (rather than field-level)
    reference.
    """
    return f"<#E::{entity_type}::{fqn}>"


def id_from_fqn(fqn: str) -> str:
    """Recover the DataSwamp id from any FQN built by this module.

    Traceability, not identity: the emitted entities also carry a ``dataswampId``
    custom property, and nothing in the adapter re-derives an identity by parsing
    an FQN or a property back out.
    """
    return decode_id(name_of(fqn))


__all__ = [
    "SERVICE_NAME",
    "NAMESPACE",
    "SERVICE_TYPE",
    "CLASSIFICATION_NAME",
    "SEPARATOR",
    "MAX_NAME_LENGTH",
    "SAFE_SEGMENT",
    "encode_id",
    "decode_id",
    "service_fqn",
    "study_fqn",
    "dataset_fqn",
    "file_fqn",
    "domain_fqn",
    "data_product_fqn",
    "team_fqn",
    "glossary_fqn",
    "glossary_term_fqn",
    "classification_fqn",
    "tag_fqn",
    "name_of",
    "parent_fqn",
    "entity_link",
    "id_from_fqn",
]
