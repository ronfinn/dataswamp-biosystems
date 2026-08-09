"""The OpenMetadata normalization contract for round-trip fidelity comparison.

This is the highest-risk module in the OpenMetadata live path, and the risk is
not a bug — it is *erosion*. When a round-trip fails, the cheapest possible fix
is to add the offending field to the ignore list and watch the check go green.
Do that a few times and fidelity validation becomes a function that always
returns "identical", which is strictly worse than having no check at all,
because it looks like evidence.

**This contract is entirely independent of the DataHub one.** The two catalogues
have different models, different server-owned state and different evidence behind
them; :data:`OM_NORMALIZATION_VERSION` starts at 1 and has no relationship to
DataHub's ``NORMALIZATION_VERSION``. Nothing here imports from that adapter.

Four rules hold the line.

**Version 1 forgives only what OpenMetadata's own schemas prove it generates.**
The bar is not "a server might add this". It is: *the ``Create<Entity>`` request
schema sets* ``additionalProperties: false`` *and does not declare the field,
while the entity schema does* — so DataSwamp cannot send it, cannot have sent it,
and any value found at that path in a readback is definitionally the platform's.
That test is mechanical and is asserted against the vendored 1.13.3 schemas in
``tests/adapters/openmetadata/test_normalize.py``, so the justification is
checked rather than asserted. A field that merely *looks* server-owned, or that a
fake server happens to return, does not qualify — the fake is a contract
simulator, not evidence about a real OpenMetadata. Anything in that second
category waits for a real-server canary.

**Forgiveness is conditional on being additive.** A platform-generated field is
ignored only where the emitted plan carried no value at that path. If DataSwamp
ever sends one and the server answers with something different, that is a
mutation and is reported as one. This is strictly stronger than stripping the
field from both sides.

**Reference projection is a change of representation, not of value.**
OpenMetadata accepts a reference as an FQN string (``service``, ``domains``,
``glossary``) or as an ``EntityReference`` keyed by a server-assigned UUID
(``parent``, ``owners``, ``assets``), and it *always* answers with the expanded
``EntityReference`` form. Comparing those literally would report every reference
in the estate as mutated, and comparing them by UUID would make the benchmark's
identity depend on which server it was loaded into. So both sides are projected
to the target's ``fullyQualifiedName`` — which is exactly the value the emitted
plan declared — and compared as that. Nothing is forgiven: a reference pointing
somewhere else still fails.

**Unknown additions are differences.** A field the server adds that is not on one
of the lists below is reported, not silently dropped. The default is suspicion;
forgiveness is opt-in, justified and paired with a test proving an adjacent field
is still caught.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Bumped whenever the rules below change in any way. Recorded in every
# round-trip report so a stored report stays interpretable.
#
# 1: the initial contract. Deliberately close to the minimum: it ships with no
#    evidence from a running OpenMetadata, and inventing forgiveness rules for
#    behaviour nobody has observed is exactly the erosion described above.
OM_NORMALIZATION_VERSION = 1


@dataclass(frozen=True)
class PlatformGeneratedField:
    """One field OpenMetadata generates, which fidelity comparison therefore ignores.

    ``path`` is a top-level key of an *entity document*. ``entity_types`` limits
    the rule to specific entity types, or is empty when it applies to all of them.
    ``justification`` is not decoration: it is what a reviewer checks an addition
    against, it is rendered into the report, and for every entry below it is
    mechanically verifiable against the vendored schemas.
    """

    path: str
    justification: str
    entity_types: frozenset[str] = frozenset()

    def applies_to(self, entity_type: str) -> bool:
        return not self.entity_types or entity_type in self.entity_types


# --------------------------------------------------------------------------
# Platform-generated entity fields.
# --------------------------------------------------------------------------
# Every entry satisfies the create-schema exclusion test described above, has a
# focused forgiveness test, and has a paired test proving an adjacent field that
# is NOT on this list still surfaces as a mutation. See
# ``tests/adapters/openmetadata/test_normalize.py``.
#
# Note what is deliberately absent. ``retentionPeriod``, ``sampleData``,
# ``certification`` and ``entityStatus`` are also missing from the create
# schemas, but OpenMetadata does not *generate* them — a user or another tool
# sets them through PATCH. A value appearing there is somebody else writing to
# DataSwamp's entities, which is precisely what containment exists to notice, so
# they stay off this list and remain discrepancies by default.
PLATFORM_GENERATED_FIELDS: tuple[PlatformGeneratedField, ...] = (
    PlatformGeneratedField(
        path="id",
        justification=(
            "The server-assigned UUID. Absent from every Create<Entity> schema, all of "
            "which set additionalProperties: false, so DataSwamp cannot send one — and "
            "must not: an identity that could only be written after the server had "
            "already seen the entity cannot be part of an offline export. DataSwamp "
            "identity is the fullyQualifiedName throughout."
        ),
    ),
    PlatformGeneratedField(
        path="href",
        justification=(
            "The URI of the entity on the server that answered. Built by the resource "
            "layer from the request's UriInfo (OpenMetadata's Entity.withHref), so it "
            "varies with the host the catalogue is reached at and is not a property of "
            "the metadata at all."
        ),
    ),
    PlatformGeneratedField(
        path="version",
        justification=(
            "OpenMetadata's own metadata version counter, incremented by the server on "
            "each accepted change. It is 0.1 after a first ingestion and higher after a "
            "second, so comparing it would make the idempotence claim untestable."
        ),
    ),
    PlatformGeneratedField(
        path="updatedAt",
        justification=(
            "The server's wall clock at the moment it accepted the write, in Unix epoch "
            "milliseconds. DataSwamp emits no wall-clock value anywhere by design."
        ),
    ),
    PlatformGeneratedField(
        path="updatedBy",
        justification=(
            "The authenticated principal the server attributed the write to. A property "
            "of the credential used, not of the metadata sent."
        ),
    ),
    PlatformGeneratedField(
        path="impersonatedBy",
        justification=(
            "The bot the server attributed the write to on a user's behalf. Like "
            "updatedBy, a property of how the request was authenticated."
        ),
    ),
    PlatformGeneratedField(
        path="changeDescription",
        justification=(
            "The server-computed diff between this version of the entity and the "
            "previous one. Derived entirely from what the server already stored."
        ),
    ),
    PlatformGeneratedField(
        path="incrementalChangeDescription",
        justification=(
            "The incremental form of changeDescription, computed the same way and for "
            "the same reason."
        ),
    ),
    PlatformGeneratedField(
        path="deleted",
        justification=(
            "The soft-delete flag, defaulted and maintained by the server's delete "
            "lifecycle. DataSwamp never deletes, so it is always the server's false."
        ),
    ),
    PlatformGeneratedField(
        path="children",
        justification=(
            "The inverse of the parent reference, materialised by the server. A pure "
            "function of the containers DataSwamp already sent, and the export "
            "deliberately declares containment one way only — the child names its "
            "parent — so a children list is derived, never sent."
        ),
        entity_types=frozenset({"container"}),
    ),
    PlatformGeneratedField(
        path="serviceType",
        justification=(
            "Copied onto a Container by the server from the StorageService it hangs "
            "under. Absent from createContainer precisely because it is not the "
            "container's fact to state; DataSwamp sends serviceType once, on the "
            "StorageService, where it is compared normally."
        ),
        entity_types=frozenset({"container"}),
    ),
)

# --------------------------------------------------------------------------
# Denormalized tag-label fields.
# --------------------------------------------------------------------------
# A TagLabel as sent carries the four fields the schema requires — tagFQN,
# source, labelType, state. A TagLabel as returned additionally carries the
# referenced Tag's own display metadata, copied in by the server so a UI need not
# fetch each tag. Those copies are derived from Tag entities DataSwamp itself
# created, so they are additive server annotation rather than a changed value.
#
# Forgiveness here is additive-only, like everything else: if a future mapping
# ever sends one of these and the server answers differently, it is a mutation.
TAG_LABEL_DERIVED_FIELDS: frozenset[str] = frozenset(
    {"name", "displayName", "description", "style", "href", "appliedAt", "appliedBy", "metadata"}
)

# --------------------------------------------------------------------------
# Reference-valued fields.
# --------------------------------------------------------------------------
# Fields OpenMetadata answers as an EntityReference (or a list of them) whatever
# form they were sent in. Both sides are projected to the target FQN before
# comparison. This is a representation projection, not forgiveness: a reference
# that points somewhere else still fails fidelity, which the paired tests prove.
REFERENCE_FIELDS: frozenset[str] = frozenset(
    {
        "service",
        "parent",
        "owners",
        "domains",
        "dataProducts",
        "experts",
        "reviewers",
        "glossary",
        "classification",
        "assets",
        "children",
    }
)

# Fields whose list order OpenMetadata does not preserve because it stores them
# as a set of relationships rather than an array. Compared as multisets. Every
# other list stays positional — ``fileFormats`` included, where order is the
# order the mapping emitted and a reordering would be a real change.
UNORDERED_FIELDS: frozenset[str] = frozenset(
    {"tags", "owners", "domains", "dataProducts", "experts", "reviewers", "assets", "children"}
)


def is_platform_generated(entity_type: str, path: str) -> bool:
    """Return whether ``path`` on ``entity_type`` is a platform-generated field."""
    return any(
        field.path == path and field.applies_to(entity_type) for field in PLATFORM_GENERATED_FIELDS
    )


def project_reference(value: Any) -> Any:
    """Project a reference value to the fully-qualified name(s) it names.

    Accepts every form OpenMetadata uses for the same fact: a bare FQN string, an
    ``EntityReference`` object, or a list of either. A reference object without a
    ``fullyQualifiedName`` is returned unchanged rather than reduced to its UUID —
    an unresolvable reference must stay visible as a difference, not be quietly
    projected onto something that happens to compare equal.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        fqn = value.get("fullyQualifiedName")
        return fqn if isinstance(fqn, str) else value
    if isinstance(value, list):
        return [project_reference(item) for item in value]
    return value


def normalize_field(field: str, value: Any) -> Any:
    """Return ``value`` in the form fidelity comparison uses for ``field``."""
    if field in REFERENCE_FIELDS:
        return project_reference(value)
    return value


def forgive_additions(sent: Any, retrieved: Any, derived: frozenset[str]) -> Any:
    """Return ``retrieved`` with ``derived`` keys removed *only where nothing was sent*.

    The additive condition is the whole point. Stripping a key from both sides
    unconditionally would hide a genuine mutation of a value DataSwamp did send;
    this drops a key only when the sent object has no opinion about it.
    """
    if not isinstance(retrieved, dict):
        return retrieved
    sent_keys = set(sent) if isinstance(sent, dict) else set()
    return {
        key: value
        for key, value in retrieved.items()
        if not (key in derived and key not in sent_keys)
    }


def normalization_contract() -> dict[str, Any]:
    """Return the full contract, for embedding verbatim in a round-trip report.

    A stored report must be readable years later without this source file, so it
    carries the rules and their justifications rather than a version number
    alone.
    """
    return {
        "normalization_version": OM_NORMALIZATION_VERSION,
        "catalogue": "openmetadata",
        "independent_of": (
            "the DataHub normalization contract; the two share no rules, no version and no evidence"
        ),
        "evidence_standard": (
            "A field is forgiven only where OpenMetadata's own Create<Entity> schema "
            "sets additionalProperties: false and omits it while the entity schema "
            "declares it, proving DataSwamp cannot have sent it. A fake server "
            "returning a field is not evidence that a real OpenMetadata generates it."
        ),
        "additive_only": (
            "Every forgiveness rule applies only where the emitted plan carried no "
            "value at that path. A value DataSwamp sent is always compared."
        ),
        "platform_generated_fields": [
            {
                "path": field.path,
                "entity_types": sorted(field.entity_types) or ["*"],
                "justification": field.justification,
            }
            for field in PLATFORM_GENERATED_FIELDS
        ],
        "tag_label_derived_fields": {
            "fields": sorted(TAG_LABEL_DERIVED_FIELDS),
            "justification": (
                "A returned TagLabel carries the referenced Tag's display metadata, "
                "copied in by the server from Tag entities DataSwamp created. Forgiven "
                "additively; the four fields the mapping sends are always compared."
            ),
        },
        "reference_projection": {
            "fields": sorted(REFERENCE_FIELDS),
            "justification": (
                "OpenMetadata accepts a reference as an FQN or an EntityReference and "
                "always answers with the expanded EntityReference. Both sides are "
                "projected to the target's fullyQualifiedName — the value the emitted "
                "plan declared. This changes representation, not value: a reference "
                "pointing elsewhere still fails fidelity. A server-assigned UUID is "
                "never used as DataSwamp identity."
            ),
        },
        "unordered_fields": {
            "fields": sorted(UNORDERED_FIELDS),
            "justification": (
                "OpenMetadata stores these as relationship sets, so list order is not "
                "meaningful. Every other list is compared positionally."
            ),
        },
        "unknown_additions": (
            "reported as discrepancies; forgiveness is opt-in, justified and paired "
            "with a test proving an adjacent field is still caught"
        ),
    }


__all__ = [
    "OM_NORMALIZATION_VERSION",
    "PlatformGeneratedField",
    "PLATFORM_GENERATED_FIELDS",
    "TAG_LABEL_DERIVED_FIELDS",
    "REFERENCE_FIELDS",
    "UNORDERED_FIELDS",
    "is_platform_generated",
    "project_reference",
    "normalize_field",
    "forgive_additions",
    "normalization_contract",
]
