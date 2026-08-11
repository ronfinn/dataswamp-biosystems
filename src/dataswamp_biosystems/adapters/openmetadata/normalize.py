"""The OpenMetadata normalization contract for round-trip fidelity comparison.

This is the highest-risk module in the OpenMetadata live path, and the risk is
not a bug — it is *erosion*. When a round-trip fails, the cheapest possible fix
is to add the offending field to the ignore list and watch the check go green.
Do that a few times and fidelity validation becomes a function that always
returns "identical", which is strictly worse than having no check at all,
because it looks like evidence.

**This contract is entirely independent of the DataHub one.** The two catalogues
have different models, different server-owned state and different evidence behind
them; :data:`OM_NORMALIZATION_VERSION` has no relationship to DataHub's
``NORMALIZATION_VERSION``, and the two currently reading the same number is a
coincidence of arithmetic, not a coupling. Nothing here imports from that adapter.

Two stages, and the distinction between them is the whole design
--------------------------------------------------------------
This module owns two different jobs, and conflating them is how a fidelity check
turns into a function that always passes. They run in order, and the guardrail
that separates them does not bend:

    **A DataSwamp-sent semantic value is never a normalization-forgiveness
    candidate. Exact proven representation reconciliation is performed
    separately, before semantic comparison.**

**Stage 1 — representation reconciliation.** OpenMetadata sometimes stores or
returns a value DataSwamp sent in a *different encoding of the same value*: a
reference expanded from an FQN into an ``EntityReference``, a relationship list
returned in another order, free text re-encoded with HTML entities. Reconciling
those is not forgiveness and grants no leniency — it is decoding, and it is
admitted only where the adapter can prove an exact, catalogue-specific,
invertible transformation. Every sent value still has to be there afterwards, and
still has to match. Nothing at this stage may absorb a word change, a punctuation
loss, a double-encoding ambiguity, or one sent value collapsing onto another.

**Stage 2 — normalization.** Only server-owned, server-generated or
server-defaulted state that DataSwamp did *not* semantically send is eligible for
forgiveness here, under the A/B classification policy in ``docs/openmetadata.md``.
Stage 2 never looks at a path stage 1 reconciled; it applies exclusively where the
emitted plan had no opinion at all.

Six rules hold the line — three in each stage.

**Stage 2 forgives only what OpenMetadata's own schemas prove it generates.**
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

**A materialized default is not a fact.** Version 2 adds the one thing the first
real-server canary showed and no schema reading could have settled: OpenMetadata
answers an *omitted optional* field with an empty relationship set or with the
default its own schema declares. ``owners: []`` on an entity DataSwamp gave no
owner asserts nothing about ownership — it is the storage layer's representation
of "nothing here". Forgiveness is exact and doubly conditional: the plan must
have omitted the field, *and* the returned value must equal the declared default
exactly. ``owners: [someone]`` on that same entity is still a containment
discrepancy, which is the case the rule exists to keep catchable.

**HTML escaping of a free-text description is an encoding, not a value change.**
*Stage 1.* OpenMetadata escapes markup-significant characters in ``description``
on write, so ``study 'x'`` comes back as ``study &#39;x&#39;``. Comparing
literally would report every described entity in the estate as mutated.

This is emphatically **not** an exception to the guardrail above, and must never
be described as one. The description is still compared, in full, against what
DataSwamp sent; what is reconciled is the transport encoding of it. The check is
the inversion itself, and it is
admitted only where that inversion is provably unambiguous: the sent text must
carry no HTML entity of its own, so exactly one decoding round can relate the two
strings, and decoding the retrieved text must then reproduce the sent text
character for character.

That first condition is what closes the ambiguity cases. A description DataSwamp
sent containing a literal ``&#39;`` is never reconciled, so a double-encoded
readback cannot decode onto it and entity-like literal text cannot collapse onto
another sent value. A truncation, a rewrite or a dropped sentence fails too:
none of them is the identity this rule requires.

**Unknown additions are differences.** A field the server adds that is not on one
of the lists below is reported, not silently dropped. The default is suspicion;
forgiveness is opt-in, justified and paired with a test proving an adjacent field
is still caught.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

# Bumped whenever the rules below change in any way. Recorded in every
# round-trip report so a stored report stays interpretable.
#
# 1: the initial contract. Deliberately close to the minimum: it ships with no
#    evidence from a running OpenMetadata, and inventing forgiveness rules for
#    behaviour nobody has observed is exactly the erosion described above.
# 2: the first version with real-server evidence behind it. This counter tracks
#    **stage 2 only** — what the comparison forgives. It moved for exactly one
#    reason: the 1.13.3 canary showed OpenMetadata materializing state DataSwamp
#    never sent, in 830 discrepancies across two verdict-B rule classes (fields
#    absent from every create schema, and optional fields answered with their
#    declared default).
#
#    The stage-1 description reconciliation added at the same time is *not* a
#    reason for this bump and must never be cited as one. It forgives nothing:
#    it decodes a transport encoding before the values are compared, and every
#    description DataSwamp sent is still compared in full.
#
#    Note what changed about the *evidence*, not just the rules. ``entityStatus``
#    was excluded in version 1 on an offline assumption — that only a PATCH sets
#    it. The canary showed the server writing it on create, on 799 entities nobody
#    patched. Live evidence superseded an unverified assumption; a red check is
#    never itself a reason to forgive anything.
OM_NORMALIZATION_VERSION = 2


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


# ==========================================================================
# STAGE 2 — normalization: server-owned state DataSwamp never sent.
#
# Everything from here to the reference-projection banner below is forgiveness,
# and is eligible only where the emitted plan carried no value at the path.
# ==========================================================================

# --------------------------------------------------------------------------
# Platform-generated entity fields.
# --------------------------------------------------------------------------
# Every entry satisfies the create-schema exclusion test described above, has a
# focused forgiveness test, and has a paired test proving an adjacent field that
# is NOT on this list still surfaces as a mutation. See
# ``tests/adapters/openmetadata/test_normalize.py``.
#
# Note what is deliberately absent. ``retentionPeriod``, ``sampleData`` and
# ``certification`` are also missing from the create schemas, but OpenMetadata
# does not *generate* them — a user or another tool sets them through PATCH. A
# value appearing there is somebody else writing to DataSwamp's entities, which
# is precisely what containment exists to notice, so they stay off this list and
# remain discrepancies by default. ``entityStatus`` was on that list in version 1
# for the same reason and left it in version 2, on evidence rather than argument:
# see its entry below.
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
    PlatformGeneratedField(
        path="entityStatus",
        justification=(
            "The server's ingestion/approval lifecycle state, written on create. Absent "
            "from every Create<Entity> schema while the entity schemas declare it, and "
            "the 1.13.3 canary returned it on 799 entities nobody patched — "
            "'Unprocessed' everywhere except a GlossaryTerm, which the server's own "
            "approval workflow settles as 'Approved'. Version 1 excluded it on the "
            "reasoning that only a PATCH sets it; that reasoning was wrong and the "
            "observation is what corrected it."
        ),
    ),
    PlatformGeneratedField(
        path="followers",
        justification=(
            "The set of users following the entity, maintained by the server's follow "
            "endpoints. Absent from every Create<Entity> schema, so it cannot be part of "
            "an export, and DataSwamp models no user subscriptions at all."
        ),
    ),
    PlatformGeneratedField(
        path="lifecycleStage",
        justification=(
            "The DataProduct's stage in OpenMetadata's own product lifecycle, defaulted "
            "by the server. Absent from createDataProduct while dataProduct declares it; "
            "DataSwamp's programmes carry no such stage and inventing one would be a "
            "fabricated governance fact."
        ),
        entity_types=frozenset({"dataProduct"}),
    ),
    PlatformGeneratedField(
        path="childrenCount",
        justification=(
            "The number of child teams, counted by the server from relationships it "
            "already stores. Absent from createTeam while team declares it — a derived "
            "count, not an input."
        ),
        entity_types=frozenset({"team"}),
    ),
    PlatformGeneratedField(
        path="userCount",
        justification=(
            "The number of users in the team, counted by the server the same way and for "
            "the same reason as childrenCount."
        ),
        entity_types=frozenset({"team"}),
    ),
    PlatformGeneratedField(
        path="deprecated",
        justification=(
            "Whether the tag has been deprecated, maintained through OpenMetadata's own "
            "tag lifecycle. Absent from createTag while tag declares it, so DataSwamp "
            "cannot state it; the canary returns the server's false."
        ),
        entity_types=frozenset({"tag"}),
    ),
    PlatformGeneratedField(
        path="disabled",
        justification=(
            "Whether the tag or classification has been disabled, maintained through the "
            "same lifecycle. Absent from createTag and createClassification while both "
            "entity schemas declare it."
        ),
        entity_types=frozenset({"tag", "classification"}),
    ),
)

# --------------------------------------------------------------------------
# Materialized defaults.
# --------------------------------------------------------------------------
# Fields the Create schema *does* accept, which DataSwamp omitted, and which the
# server answered with an empty relationship set or with the default its own
# schema declares. Evidence is the first live canary against 1.13.3, corroborated
# by the vendored schemas: every scalar below is a literal ``default:`` in the
# create or entity schema, and every collection is declared with no default and
# returned as ``[]``.
#
# The forgiveness is exact in both directions. It applies only where the plan
# carried no value at that path, and only where the retrieved value equals the
# declared default *exactly*: ``owners: []`` is forgiven, ``owners: [someone]`` on
# an entity DataSwamp gave no owner is a containment discrepancy, which is the
# entire reason ownership is tracked at all.
EMPTY = "<empty-collection>"


@dataclass(frozen=True)
class MaterializedDefault:
    """One field the server fills in when the request omits it.

    ``value`` is the exact retrieved value forgiven — :data:`EMPTY` for a field
    returned as an empty list, or the literal scalar the schema declares as its
    default. Anything else at that path is still reported.
    """

    path: str
    value: Any
    justification: str
    entity_types: frozenset[str] = frozenset()

    def applies_to(self, entity_type: str) -> bool:
        return not self.entity_types or entity_type in self.entity_types

    def matches(self, retrieved: Any) -> bool:
        if self.value is EMPTY:
            return isinstance(retrieved, list) and not retrieved
        return type(retrieved) is type(self.value) and retrieved == self.value


_EMPTY_SET_JUSTIFICATION = (
    "Declared in the Create schema with no default, and stored by OpenMetadata as a "
    "relationship set. A request that omits it is answered with an empty list, which "
    "asserts nothing: it is the storage layer's representation of 'nothing here'. "
    "Forgiven only when it comes back empty — a populated value DataSwamp never sent "
    "is somebody else writing to its entities and stays a containment discrepancy."
)

# Each collection is scoped to the entity types whose Create schema actually
# accepts it. That is not tidiness: ``dataProducts`` is creatable on a Container
# but entity-only on a GlossaryTerm, so an unscoped rule would forgive, on the
# term, a field the term's own request could never have carried — the stricter
# platform-generated standard, reached by the wrong door.
_EMPTY_COLLECTIONS: tuple[tuple[str, frozenset[str]], ...] = (
    ("assets", frozenset({"dataProduct"})),
    ("conceptMappings", frozenset({"glossaryTerm"})),
    ("dataProducts", frozenset({"container", "storageService"})),
    (
        "domains",
        frozenset(
            {
                "classification",
                "container",
                "dataProduct",
                "glossary",
                "glossaryTerm",
                "storageService",
                "tag",
                "team",
            }
        ),
    ),
    ("experts", frozenset({"dataProduct", "domain"})),
    (
        "owners",
        frozenset(
            {
                "classification",
                "container",
                "dataProduct",
                "domain",
                "glossary",
                "glossaryTerm",
                "storageService",
                "tag",
                "team",
            }
        ),
    ),
    ("recognizers", frozenset({"tag"})),
    ("references", frozenset({"glossaryTerm"})),
    ("reviewers", frozenset({"classification", "dataProduct", "glossary", "glossaryTerm", "tag"})),
    ("synonyms", frozenset({"glossaryTerm"})),
    (
        "tags",
        frozenset(
            {"container", "dataProduct", "domain", "glossary", "glossaryTerm", "storageService"}
        ),
    ),
    ("users", frozenset({"team"})),
)

MATERIALIZED_DEFAULTS: tuple[MaterializedDefault, ...] = tuple(
    MaterializedDefault(
        path=path,
        value=EMPTY,
        justification=_EMPTY_SET_JUSTIFICATION,
        entity_types=entity_types,
    )
    for path, entity_types in _EMPTY_COLLECTIONS
) + (
    MaterializedDefault(
        path="provider",
        value="user",
        entity_types=frozenset({"classification", "glossary", "glossaryTerm", "tag"}),
        justification=(
            "OpenMetadata distinguishes entities it ships with ('system') from those a "
            "user or tool created. The server stamps 'user' on anything it did not seed "
            "itself, so the value is a statement about who created the entity rather "
            "than metadata DataSwamp holds. A 'system' provider on a DataSwamp entity "
            "would still be reported."
        ),
    ),
    MaterializedDefault(
        path="mutuallyExclusive",
        value=False,
        entity_types=frozenset({"classification", "glossary", "glossaryTerm", "tag"}),
        justification=(
            "A literal `default: false` in createTag, createClassification, "
            "createGlossary and createGlossaryTerm. DataSwamp's vocabularies impose no "
            "exclusivity, so the field is omitted and the server's declared default "
            "comes back."
        ),
    ),
    MaterializedDefault(
        path="isJoinable",
        value=True,
        justification="A literal `default: true` in createTeam and in the team entity schema.",
        entity_types=frozenset({"team"}),
    ),
    MaterializedDefault(
        path="autoClassificationEnabled",
        value=False,
        justification=(
            "A literal `default: false` in createTag. DataSwamp never asks OpenMetadata "
            "to auto-apply a tag; the whole point is that the export states what it "
            "means."
        ),
        entity_types=frozenset({"tag"}),
    ),
    MaterializedDefault(
        path="autoClassificationPriority",
        value=50,
        justification=(
            "A literal `default: 50` in createTag, meaningful only when "
            "autoClassificationEnabled is true, which DataSwamp leaves at its default "
            "false."
        ),
        entity_types=frozenset({"tag"}),
    ),
    MaterializedDefault(
        path="visibility",
        value="PRIVATE",
        justification=(
            "The DataProduct's visibility, defaulted by the server to the closed value. "
            "DataSwamp expresses no visibility policy — a synthetic estate has no "
            "audience — so the field is omitted and the server's default returns."
        ),
        entity_types=frozenset({"dataProduct"}),
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


# ==========================================================================
# STAGE 1 — representation reconciliation: one value, two encodings.
#
# Nothing below this banner forgives anything. Each rule relates two encodings
# of a value DataSwamp *did* send, and every such value is still compared. They
# live in this module because canonicalizing a representation and forgiving
# server state are both "put the two sides in comparable form" — but they are
# different operations under different rules, and the banners exist so that
# distinction survives future edits.
# ==========================================================================

# --------------------------------------------------------------------------
# Server-side HTML escaping.
# --------------------------------------------------------------------------
# OpenMetadata escapes markup-significant characters in free-text description
# fields on write, so an apostrophe returns as ``&#39;``. Every one of the 83
# fidelity failures in the first live canary was this and nothing else.
#
# Reconciled, never forgiven: see reconcile_html_escaping for the four conditions
# that keep the inversion exact and unambiguous. This rule is not a reason to
# move OM_NORMALIZATION_VERSION, which counts stage-2 forgiveness alone.
ESCAPED_TEXT_FIELDS: frozenset[str] = frozenset({"description"})

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


def is_materialized_default(entity_type: str, path: str, retrieved: Any) -> bool:
    """Return whether ``retrieved`` at ``path`` is exactly the default the server fills in.

    Callers apply this only where the emitted plan carried no value at ``path``;
    the value check here is the second half of the condition, and it is exact. A
    field that comes back holding something is never forgiven, whatever its
    declared default is.
    """
    return any(
        rule.path == path and rule.applies_to(entity_type) and rule.matches(retrieved)
        for rule in MATERIALIZED_DEFAULTS
    )


def reconcile_html_escaping(field: str, sent: Any, retrieved: Any) -> Any:
    """Decode the server's transport encoding of ``sent``. **Stage 1, not forgiveness.**

    This grants no leniency whatsoever: the description is still compared in full
    against what DataSwamp sent, and this only relates the two encodings of it.
    Four conditions must all hold, and each one closes a specific way the
    reconciliation could otherwise absorb a real change:

    * the field is one OpenMetadata is known to escape, and both sides are
      strings — so this never touches a reference, an enum or an identity;
    * the sent text carries **no HTML entity of its own**, so exactly one decoding
      round can relate the two strings. This is what makes the inversion
      unambiguous: a double-encoded readback cannot decode onto a description that
      already contained an entity, and entity-like literal text cannot collapse
      onto another sent value;
    * decoding the retrieved text reproduces the sent text character for
      character — no word change, no punctuation loss, no truncation.

    Anything else is returned untouched and compared normally, so a rewritten
    description still fails fidelity.
    """
    if field not in ESCAPED_TEXT_FIELDS:
        return retrieved
    if not isinstance(sent, str) or not isinstance(retrieved, str):
        return retrieved
    if retrieved == sent or html.unescape(sent) != sent:
        return retrieved
    if html.unescape(retrieved) == sent:
        return sent
    return retrieved


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
        "comparison_model": (
            "Two stages. Stage 1 reconciles representation: where a value DataSwamp "
            "sent comes back in another encoding of the same value, and the adapter can "
            "prove an exact invertible transformation, the encodings are related before "
            "comparison. That is decoding, not forgiveness, and every sent value is "
            "still compared. Stage 2 is normalization: only server-owned state DataSwamp "
            "did not semantically send is eligible for forgiveness. A DataSwamp-sent "
            "semantic value is never a normalization-forgiveness candidate."
        ),
        "version_counts": (
            "stage 2 only. The normalization_version records what the comparison "
            "forgives; a stage-1 representation rule is never a reason to move it."
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
        "materialized_defaults": {
            "justification": (
                "OpenMetadata answers an omitted optional field with an empty "
                "relationship set or the default its own schema declares. Forgiven only "
                "where the plan omitted the field AND the retrieved value equals the "
                "declared default exactly; a populated value DataSwamp never sent stays "
                "a containment discrepancy."
            ),
            "evidence": (
                "the first live canary against OpenMetadata 1.13.3, corroborated by "
                "literal `default:` declarations in the vendored create schemas"
            ),
            "fields": [
                {
                    "path": rule.path,
                    "value": rule.value,
                    "entity_types": sorted(rule.entity_types) or ["*"],
                    "justification": rule.justification,
                }
                for rule in MATERIALIZED_DEFAULTS
            ],
        },
        "escaped_text_reconciliation": {
            "stage": 1,
            "forgives": False,
            "fields": sorted(ESCAPED_TEXT_FIELDS),
            "justification": (
                "OpenMetadata escapes markup-significant characters in free-text "
                "descriptions on write, so the same value arrives in another encoding. "
                "The two encodings are related, not forgiven: the description is still "
                "compared in full. Admitted only where the inversion is unambiguous — "
                "the sent text carries no HTML entity of its own, so exactly one "
                "decoding round can relate the two strings — and where decoding the "
                "retrieved text then reproduces the sent text character for character. "
                "A truncation, a rewrite, a double-encoded entity or a decode landing "
                "on another sent value all still fail fidelity."
            ),
        },
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
    "EMPTY",
    "PlatformGeneratedField",
    "MaterializedDefault",
    "PLATFORM_GENERATED_FIELDS",
    "MATERIALIZED_DEFAULTS",
    "ESCAPED_TEXT_FIELDS",
    "TAG_LABEL_DERIVED_FIELDS",
    "REFERENCE_FIELDS",
    "UNORDERED_FIELDS",
    "is_platform_generated",
    "is_materialized_default",
    "reconcile_html_escaping",
    "project_reference",
    "normalize_field",
    "forgive_additions",
    "normalization_contract",
]
