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

The list is deliberately close to empty at version 1. That is not an oversight:
this module ships with no evidence from a real DataHub server, and inventing
forgiveness rules for behaviour nobody has observed would be exactly the erosion
described above. Additions are earned by evidence from the live integration job
and triaged under the drift policy — see ``docs/datahub.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Bumped whenever the forgiveness rules below change in any way — an added or
# removed server-owned field, or a change to which fields are unordered.
# Recorded in every round-trip report so a stored report stays interpretable.
NORMALIZATION_VERSION = 1


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
        "unordered_fields": {
            aspect: sorted(fields) for aspect, fields in sorted(UNORDERED_FIELDS.items())
        },
        "unknown_server_additions": "reported as mutations",
    }


__all__ = [
    "NORMALIZATION_VERSION",
    "ServerOwnedField",
    "SERVER_OWNED_FIELDS",
    "UNORDERED_FIELDS",
    "is_unordered",
    "normalize_aspect",
    "normalization_contract",
]
