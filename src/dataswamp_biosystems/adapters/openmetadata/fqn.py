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
identity carries the ``dataswamp`` / ``dataswamp-biosystems`` prefix — and is a
*single segment*, because the server derives a root entity's FQN from its ``name``
alone (``quoteName(name)``) and there is no parent to restore a prefix a dotted
identity would imply.

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
            escape = value[index + 1 : index + 3]
            if len(escape) != 2 or any(digit not in "0123456789abcdef" for digit in escape):
                # Not something :func:`encode_id` can have produced. Refusing
                # beats returning a plausible-looking id built from a guess.
                raise ValueError(f"{value!r} is not an encoded DataSwamp id")
            out.append(int(escape, 16))
            index += 3
        else:
            out.extend(char.encode("utf-8"))
            index += 1
    return out.decode("utf-8")


def _root_name(*parts: str) -> str:
    """Return a root-level ``name``, checked against the whole-name length bound.

    :func:`encode_id` bounds the *encoded segment*, which leaves the constant
    prefix every root-level identity carries unaccounted for: a
    ``dataswamp``-prefixed name can exceed OpenMetadata's ``entityName`` limit
    while each of its encoded parts is individually inside it. Root-level names
    are built through here so the bound is applied to the string the server will
    actually receive.

    The failure is loud on purpose. Truncating would break injectivity, and
    hashing would break reversibility — either would trade a load-time error for
    two estates silently sharing one identity.
    """
    name = "".join(parts)
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(
            f"root-level name {name[:40]!r}… is {len(name)} characters, "
            f"over OpenMetadata's {MAX_NAME_LENGTH}-character entityName limit"
        )
    return name


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
    return _root_name(f"{NAMESPACE}-", encode_id(programme_id))


# The separator between a data product's two *already-encoded* ids.
#
# ``~~`` cannot occur inside an encoded id: :func:`encode_id` emits ``~`` only as
# the start of a ``~hh`` triple, so a ``~`` is always followed by two hex digits
# and never by another ``~``. That makes it the one sequence that can split the
# pair unambiguously, while staying inside the safe alphabet the plan validator
# holds every name segment to.
#
# Encoding the two ids *separately* is load-bearing. Joining first and encoding
# afterwards looks equivalent and is not: the codec would escape the separator
# and any separator inside an id identically, so programme ``a.b`` + product
# ``c`` and programme ``a`` + product ``b.c`` would produce the same name.
DATA_PRODUCT_KEY_SEPARATOR = "~~"


def data_product_fqn(programme_id: str, product_id: str) -> str:
    """Return the DataProduct FQN for a product within its programme's domain.

    OpenMetadata's DataProduct is a **root-level** entity: its repository does not
    override ``setFullyQualifiedName``, so the server assigns
    ``fullyQualifiedName = quoteName(name)`` and the owning Domain is a field, not
    a path component. The identity therefore has to be a single segment that is
    already its own FQN, and it has to carry the programme itself — nothing on the
    server side can restore a prefix the way a Container's parent does.

    Each id is encoded separately and the results joined with
    ``DATA_PRODUCT_KEY_SEPARATOR``, which keeps the identity injective over
    ``(programme_id, product_id)``. A literal ``-`` join would not: ``-`` is inside
    the codec's safe alphabet, so programme ``a-b`` + product ``c`` and programme
    ``a`` + product ``b-c`` would be the same name. The result is free of ``.`` and
    ``"``, the two characters OpenMetadata's ``needsQuoting`` treats as quoting
    triggers, so the server stores the name unchanged.
    """
    return _root_name(
        f"{NAMESPACE}-",
        encode_id(programme_id),
        DATA_PRODUCT_KEY_SEPARATOR,
        encode_id(product_id),
    )


def data_product_ids_from_fqn(fqn: str) -> tuple[str, str]:
    """Recover ``(programme_id, product_id)`` from a DataProduct FQN.

    The DataProduct-specific inverse of :func:`data_product_fqn`. It exists as its
    own function rather than as behaviour inside :func:`id_from_fqn` because a
    data product's identity is a *pair*: overloading the generic helper would make
    what it returns depend on which family the caller happened to pass, which is
    exactly the ambiguity this module exists to remove.
    """
    prefix = f"{NAMESPACE}-"
    if not fqn.startswith(prefix):
        raise ValueError(f"{fqn!r} is not a DataSwamp root-level identity")
    programme, separator, product = fqn[len(prefix) :].partition(DATA_PRODUCT_KEY_SEPARATOR)
    if not separator:
        raise ValueError(f"{fqn!r} is not a DataSwamp DataProduct identity")
    return decode_id(programme), decode_id(product)


def team_fqn(team_id: str) -> str:
    """Return the Team FQN for a DataSwamp owning/stewarding team id."""
    return _root_name(f"{NAMESPACE}-", encode_id(team_id))


def glossary_fqn(vocabulary_id: str) -> str:
    """Return the Glossary FQN standing for one controlled vocabulary."""
    return _root_name(f"{NAMESPACE}-", encode_id(vocabulary_id))


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

    What it returns is family-dependent, and deliberately not smoothed over. For a
    Container or a GlossaryTerm — whose FQNs nest — it recovers the entity's own
    id. For a root-level identity it recovers the whole namespaced name, because
    that *is* the entity's name; for a DataProduct specifically that means the
    encoded ``programme.product`` pair rather than the bare product id. Use
    :func:`data_product_ids_from_fqn` when the pair is what is wanted.
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
    "DATA_PRODUCT_KEY_SEPARATOR",
    "data_product_fqn",
    "data_product_ids_from_fqn",
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
