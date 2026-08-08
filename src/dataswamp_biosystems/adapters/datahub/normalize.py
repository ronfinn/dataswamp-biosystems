"""The normalization contract for round-trip fidelity comparison.

This is the highest-risk module in the live path, and the risk is not a bug —
it is *erosion*. When a live round-trip fails, the cheapest possible fix is to
add the offending field to the ignore list and watch the check go green. Do that
a few times and fidelity validation becomes a function that always returns
"identical", which is strictly worse than having no check at all, because it
looks like evidence.

Three rules hold the line:

**The ignore list is narrow, versioned and justified.** Every entry names the
field, says why the *server* rather than DataSwamp owns it, and carries a test
demonstrating the justification. :data:`NORMALIZATION_VERSION` is recorded in
every emitted round-trip report, so a report can be read later knowing exactly
which forgiveness rules were in force when it was produced.

**Unknown additions are differences.** A field the server adds that is not on
the list is reported as a mutation, not silently dropped. The default is
suspicion; forgiveness is opt-in and reviewed.

**Order-insensitivity is per-field, not global.** A list is compared as a
multiset only where DataHub's model genuinely has no ordering semantics for it.
Everything else is compared positionally, including ``subTypes.typeNames``,
where the first element is conventionally the primary subtype and reordering
would be a real change.

Version 1 was deliberately close to empty, because it shipped with no evidence
from a real DataHub server and inventing forgiveness rules for behaviour nobody
had observed would have been exactly the erosion described above. Version 2 is
what that evidence bought: the first live round-trip against a pinned DataHub
release produced 4,398 discrepancies, and **every one of them was the server
adding something, not changing something**. Zero of the 861 field-level
differences altered a value DataSwamp sent.

That distinction is the whole justification, so version 2 encodes it rather than
merely trusting it:

**Derivation is recognised, not waved through.** A server-derived *aspect* is
exempt from containment only when it is that entity's own key aspect — a pure
function of the URN we sent — or one of three explicitly named materialisations.
An aspect nobody sent and nothing derives is still a containment failure.

**Additive forgiveness is conditional on being additive.** A server-added
*field* is forgiven only where DataSwamp sent no value for it. If a field on
that list ever appears in an emitted payload and the server returns something
different, that is a mutation and is reported as one. This is strictly stronger
than stripping the field from both sides, which is what the systemMetadata rule
does and what a careless addition here would have done.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Bumped whenever the forgiveness rules below change in any way — an added or
# removed server-owned field, a change to which fields are unordered, or a
# change to what counts as server-derived. Recorded in every round-trip report
# so a stored report stays interpretable.
#
# 1 -> 2: server-derived aspects and additive server-added fields, earned by the
#         first live round-trip against DataHub v1.7.0.
NORMALIZATION_VERSION = 2


@dataclass(frozen=True)
class ServerOwnedField:
    """One field a GMS owns, which fidelity comparison therefore ignores.

    ``path`` is a dotted path from the root of an *aspect payload*. ``aspects``
    limits the rule to specific aspect names, or is empty when the rule applies
    to every aspect. ``justification`` is not decoration: it is the thing a
    reviewer checks an addition against, and it is rendered into the docs.
    """

    path: str
    justification: str
    aspects: frozenset[str] = frozenset()

    def applies_to(self, aspect_name: str) -> bool:
        return not self.aspects or aspect_name in self.aspects


# --------------------------------------------------------------------------
# The ignore list.
# --------------------------------------------------------------------------
# Each entry must have: a justification below, a focused unit test proving the
# field is normalized away, and a paired test proving an adjacent field that is
# NOT on this list still surfaces as a mutation. See
# ``tests/adapters/test_normalize.py``.
SERVER_OWNED_FIELDS: tuple[ServerOwnedField, ...] = (
    ServerOwnedField(
        path="systemMetadata",
        justification=(
            "Ingestion provenance the server attaches to every aspect it stores: run "
            "identifier, observation time, and the metadata-registry name and version. "
            "DataSwamp never sends it — the emitted payload has no such key, which the "
            "export fixtures pin — so its presence in a readback is definitionally the "
            "server's own annotation. It also changes on every ingestion by design, so "
            "comparing it would make the idempotence claim untestable: a second "
            "identical ingestion would report every aspect as mutated."
        ),
    ),
)

# --------------------------------------------------------------------------
# Server-derived aspects: materialised by the server, never sent by DataSwamp.
# --------------------------------------------------------------------------
# These are exempt from *containment* — they are not evidence that somebody
# else's metadata leaked into the catalogue. They remain fully subject to
# fidelity: none of them is on the sent key set, so none is ever compared as a
# value, and if the server were to derive one for an entity we never sent, the
# extra-*entity* check still fires.
#
# The bar for this list is derivability: the server must be able to compute the
# aspect from what DataSwamp already sent. "The server happened to add it" is
# not sufficient, because that is indistinguishable from a third party writing
# to our URNs — which is the thing containment exists to detect.


@dataclass(frozen=True)
class ServerDerivedAspect:
    """One aspect a GMS materialises for entities it is given."""

    aspect: str
    justification: str


# The key aspect is handled by rule rather than enumeration: for entity type T,
# DataHub materialises the aspect ``TKey``, whose content is a parse of the URN.
# Expressing it as a rule keeps it exact — ``datasetKey`` is derived on a
# dataset, but the same aspect appearing on a tag is not, and stays a finding.
KEY_ASPECT_SUFFIX = "Key"

KEY_ASPECT_JUSTIFICATION = (
    "The entity's key aspect. DataHub materialises it for every entity from the URN "
    "itself — it is a parse of the identifier DataSwamp sent, carrying no information "
    "the export did not already supply. Observed for all nine emitted entity types "
    "against DataHub v1.7.0. Reporting it as an aspect nobody sent would make every "
    "successful ingestion look like a containment breach."
)

SERVER_DERIVED_ASPECTS: tuple[ServerDerivedAspect, ...] = (
    ServerDerivedAspect(
        aspect="browsePathsV2",
        justification=(
            "Navigation path the server computes from the entity's container and "
            "platform, both of which DataSwamp sent. It exists to drive UI browsing "
            "and is regenerated by the server on ingestion; DataSwamp emits no browse "
            "path, which the export fixtures pin."
        ),
    ),
    ServerDerivedAspect(
        aspect="aliases",
        justification=(
            "Alternate identifiers the server maintains for an entity. Derived from the "
            "URN and never emitted by DataSwamp."
        ),
    ),
    ServerDerivedAspect(
        aspect="dataPlatformInstance",
        justification=(
            "The platform association the server extracts from a dataset URN, whose "
            "platform segment DataSwamp sent as part of the identifier."
        ),
    ),
)

_DERIVED_ASPECT_NAMES = frozenset(item.aspect for item in SERVER_DERIVED_ASPECTS)


def is_server_derived_aspect(entity_type: str, aspect_name: str) -> bool:
    """Return whether ``aspect_name`` is one the server derives for ``entity_type``."""
    if aspect_name == f"{entity_type}{KEY_ASPECT_SUFFIX}":
        return True
    return aspect_name in _DERIVED_ASPECT_NAMES


# --------------------------------------------------------------------------
# Server-added fields: present in a readback, absent from what DataSwamp sent.
# --------------------------------------------------------------------------
# Forgiven **only where DataSwamp sent no value**. If the emitted payload ever
# carries one of these paths and the server returns something different, that is
# a mutation and is reported. This is what separates the rule from stripping,
# and it is what stops the list from being able to hide a real change.


@dataclass(frozen=True)
class ServerAddedField:
    """One field a GMS computes and attaches to an aspect it was given."""

    aspect: str
    path: str
    justification: str


SERVER_ADDED_FIELDS: tuple[ServerAddedField, ...] = (
    ServerAddedField(
        aspect="assertionInfo",
        path="entityUrn",
        justification=(
            "A denormalised copy of the asserted entity, which DataSwamp already sent "
            "inside 'datasetAssertion.dataset'. The server hoists it to the top level "
            "so assertions can be looked up by subject. Same URN, second location."
        ),
    ),
    ServerAddedField(
        aspect="domains",
        path="domainAssociations",
        justification=(
            "A richer rendering of the same membership DataSwamp sent in 'domains': one "
            "association object per domain URN, in the same order. The server maintains "
            "it alongside the plain URN list rather than in place of it."
        ),
    ),
    ServerAddedField(
        aspect="ownership",
        path="ownerTypes",
        justification=(
            "An index of the owners DataSwamp sent, grouped by ownership-type URN. "
            "Derived wholly from 'owners', which remains present and is still compared."
        ),
    ),
)


def is_server_added_field(aspect_name: str, path: str) -> bool:
    """Return whether ``path`` in ``aspect_name`` may be *added* by the server.

    Membership alone forgives nothing. The caller must additionally establish
    that DataSwamp sent no value at ``path`` — see
    :func:`~dataswamp_biosystems.adapters.datahub.roundtrip.compare`.
    """
    return any(item.aspect == aspect_name and item.path == path for item in SERVER_ADDED_FIELDS)


# --------------------------------------------------------------------------
# Fields whose list members are genuinely unordered in DataHub's model, and are
# therefore compared as multisets rather than positionally.
# --------------------------------------------------------------------------
# Restraint matters more than coverage here. A field belongs on this list only
# when ordering carries no meaning in DataHub's own model — not merely when
# ordering is inconvenient. Notably absent:
#
# ``subTypes.typeNames``
#     The first element is conventionally the primary subtype, so a reordering
#     is a real semantic change and must be reported.
# ``customProperties``
#     A mapping, not a list; key order is already irrelevant to comparison.
UNORDERED_FIELDS: dict[str, frozenset[str]] = {
    # A set of (owner, type) associations. DataHub renders ownership as a set of
    # relationships; no owner is "first".
    "ownership": frozenset({"owners"}),
    # Tag associations are a set: a catalogue asset carries tags, not a tag list.
    "globalTags": frozenset({"tags"}),
    # Glossary-term associations are likewise a set.
    "glossaryTerms": frozenset({"terms"}),
    # Domain membership is a set of domain URNs.
    "domains": frozenset({"domains"}),
    # Lineage is an edge set. Upstream order has no meaning in the graph.
    "upstreamLineage": frozenset({"upstreams"}),
    # A data product's assets are its membership set.
    "dataProductProperties": frozenset({"assets"}),
}


def is_unordered(aspect_name: str, field_path: str) -> bool:
    """Return whether ``field_path`` in ``aspect_name`` is semantically unordered.

    Only *top-level* fields qualify. A nested list inside an unordered member is
    a different question with a different answer, and answering it implicitly
    would be exactly the over-reach this module exists to prevent.
    """
    return field_path in UNORDERED_FIELDS.get(aspect_name, frozenset())


def _strip(payload: Any, aspect_name: str, prefix: str) -> Any:
    """Recursively remove server-owned fields from one aspect payload."""
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            if any(
                field.path == path and field.applies_to(aspect_name)
                for field in SERVER_OWNED_FIELDS
            ):
                continue
            result[key] = _strip(value, aspect_name, path)
        return result
    if isinstance(payload, list):
        return [_strip(item, aspect_name, prefix) for item in payload]
    return payload


def normalize_aspect(aspect_name: str, payload: Any) -> Any:
    """Return ``payload`` with server-owned fields removed, ready for comparison.

    Nothing else is touched: no key is added, no default materialised, no type
    coerced. A value the server changed is still a changed value after
    normalization, which is the entire point.
    """
    return _strip(payload, aspect_name, "")


def normalization_contract() -> dict[str, Any]:
    """Return the machine-readable contract, for embedding in a report.

    A stored report should be interpretable without the source tree that
    produced it, so the report carries the rules, not merely a version number.
    """
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "server_owned_fields": [
            {
                "path": field.path,
                "aspects": sorted(field.aspects) or ["*"],
                "justification": field.justification,
            }
            for field in sorted(SERVER_OWNED_FIELDS, key=lambda f: (f.path, sorted(f.aspects)))
        ],
        "server_derived_aspects": {
            "key_aspect_rule": {
                "pattern": f"<entityType>{KEY_ASPECT_SUFFIX}",
                "justification": KEY_ASPECT_JUSTIFICATION,
            },
            "named": [
                {"aspect": item.aspect, "justification": item.justification}
                for item in sorted(SERVER_DERIVED_ASPECTS, key=lambda item: item.aspect)
            ],
            "scope": "exempt from containment only; never from fidelity",
        },
        "server_added_fields": [
            {
                "aspect": item.aspect,
                "path": item.path,
                "justification": item.justification,
            }
            for item in sorted(SERVER_ADDED_FIELDS, key=lambda item: (item.aspect, item.path))
        ],
        "server_added_fields_scope": (
            "forgiven only where the emitted payload carries no value at that path; "
            "a differing value DataSwamp did send is still a mutation"
        ),
        "unordered_fields": {
            aspect: sorted(fields) for aspect, fields in sorted(UNORDERED_FIELDS.items())
        },
        "unknown_server_additions": "reported as mutations",
    }


__all__ = [
    "NORMALIZATION_VERSION",
    "ServerOwnedField",
    "SERVER_OWNED_FIELDS",
    "ServerDerivedAspect",
    "SERVER_DERIVED_ASPECTS",
    "KEY_ASPECT_SUFFIX",
    "KEY_ASPECT_JUSTIFICATION",
    "is_server_derived_aspect",
    "ServerAddedField",
    "SERVER_ADDED_FIELDS",
    "is_server_added_field",
    "UNORDERED_FIELDS",
    "is_unordered",
    "normalize_aspect",
    "normalization_contract",
]
