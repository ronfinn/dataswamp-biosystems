"""Validate an emitted OpenMetadata load plan without an OpenMetadata server.

Every check here is a property of the plan itself, so the adapter is provable
offline: FQN shape and namespacing, uniqueness, entity-type coherence, load
ordering, reference closure, containment consistency, custom-property key syntax
and — the check that matters most for a benchmark — that an ``observed`` export
carries no privileged ground-truth marker.

Two of these deserve their reason stated, because they are the ones a future
change is most likely to want to weaken.

**Reference closure is forward-looking, not merely existential.** It is not
enough that a target FQN appears somewhere in the plan; it must appear at a
*lower* order than the record pointing at it. A load that walks the plan in order
must never meet a reference to something it has not created yet, and "it exists
in the file" is not that guarantee.

**The outside-reference allow-list is closed.** Exactly three references may
resolve outside the export — OpenMetadata's built-in ``string`` property type and
the ``container`` and ``dataProduct`` entity types — because every server ships
with them and DataSwamp must not try to create them. There is no general "this
one is external" flag, deliberately: an escape hatch would turn closure into a
suggestion.

Problems are returned as a sorted list of human-readable strings, matching the
DataHub validator's convention, so the CLI can print them directly.
"""

from __future__ import annotations

import re

from dataswamp_biosystems.adapters.openmetadata.fqn import (
    CLASSIFICATION_NAME,
    NAMESPACE,
    SAFE_SEGMENT,
    SEPARATOR,
    SERVICE_NAME,
    parent_fqn,
    tag_fqn,
)
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    BUILTIN_REFERENCES,
    PHASES,
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
    ExportPlan,
    PlanRecord,
)

_SEGMENT = r"[a-z0-9~-]+"

# One FQN pattern per emitted entity type. An FQN that does not match was either
# built from something other than a stable id or has had an unescaped character
# smuggled into it; both are identity bugs, so both fail here.
FQN_PATTERNS: dict[str, re.Pattern[str]] = {
    "customProperty": re.compile(r"^(container|dataProduct)\.[A-Za-z][A-Za-z0-9]*$"),
    "classification": re.compile(rf"^{re.escape(CLASSIFICATION_NAME)}$"),
    "tag": re.compile(rf"^{re.escape(CLASSIFICATION_NAME)}\.{_SEGMENT}$"),
    "glossary": re.compile(rf"^{NAMESPACE}-{_SEGMENT}$"),
    "glossaryTerm": re.compile(rf"^{NAMESPACE}-{_SEGMENT}\.{_SEGMENT}$"),
    "team": re.compile(rf"^{NAMESPACE}-{_SEGMENT}$"),
    "domain": re.compile(rf"^{NAMESPACE}-{_SEGMENT}$"),
    "storageService": re.compile(rf"^{re.escape(SERVICE_NAME)}$"),
    "container": re.compile(rf"^{re.escape(SERVICE_NAME)}(\.{_SEGMENT}){{1,3}}$"),
    "dataProduct": re.compile(rf"^{NAMESPACE}-{_SEGMENT}\.{_SEGMENT}$"),
    "lineageEdge": re.compile(
        rf"^{re.escape(SERVICE_NAME)}(\.{_SEGMENT}){{1,3}}"
        rf"->{re.escape(SERVICE_NAME)}(\.{_SEGMENT}){{1,3}}$"
    ),
    "testCaseResult": re.compile(rf"^{re.escape(SERVICE_NAME)}(\.{_SEGMENT}){{1,3}}$"),
}

# OpenMetadata's ``customPropertyName`` pattern, narrowed. Upstream permits a
# wide punctuation set; this adapter emits camelCase only, so the emitted keys are
# held to the stricter rule. A narrower rule can only reject things upstream would
# also have rejected... plus things this adapter never means to emit.
CUSTOM_PROPERTY_NAME = re.compile(r"^dataswamp[A-Za-z0-9]*$")

# The entity types that are *catalogue assets* — the ones a truth export must
# visibly mark as privileged.
ASSET_ENTITY_TYPES: frozenset[str] = frozenset({"container", "dataProduct"})

# Phases whose records stand for an actual asset rather than a structural or
# vocabulary entity.
ASSET_PHASES: frozenset[str] = frozenset({"dataset-container", "file-container", "data-product"})


def _extension(record: PlanRecord) -> dict[str, object]:
    if not isinstance(record.create, dict):
        return {}
    extension = record.create.get("extension")
    return extension if isinstance(extension, dict) else {}


def _tag_fqns(record: PlanRecord) -> list[str]:
    if not isinstance(record.create, dict):
        return []
    tags = record.create.get("tags")
    if not isinstance(tags, list):
        return []
    return [
        str(tag["tagFQN"])
        for tag in tags
        if isinstance(tag, dict) and isinstance(tag.get("tagFQN"), str)
    ]


def validate_plan(plan: ExportPlan) -> list[str]:  # noqa: C901 - one pass, many properties
    """Return every problem with ``plan``, or an empty list if it is sound."""
    problems: list[str] = []
    mode = plan.mode
    privileged_tag = tag_fqn(TAG_PRIVILEGED)

    records = plan.records
    order_of: dict[tuple[str, str], int] = {}
    type_of: dict[str, str] = {}
    seen_orders: set[int] = set()
    phase_index = -1
    previous_order = 0

    for record in records:
        where = f"{record.phase} record {record.fqn!r}"

        # -- ordering ---------------------------------------------------------
        if record.phase not in PHASES:
            problems.append(f"{where}: unknown load phase {record.phase!r}")
        else:
            index = PHASES.index(record.phase)
            if index < phase_index:
                problems.append(
                    f"{where}: phase {record.phase!r} appears after a later phase; "
                    "the load order is part of the export contract"
                )
            phase_index = max(phase_index, index)
        if record.order <= previous_order:
            problems.append(
                f"{where}: order {record.order} does not increase (previous {previous_order})"
            )
        if record.order in seen_orders:
            problems.append(f"{where}: duplicate order {record.order}")
        seen_orders.add(record.order)
        previous_order = max(previous_order, record.order)

        # -- identity ---------------------------------------------------------
        pattern = FQN_PATTERNS.get(record.entity_type)
        if pattern is None:
            problems.append(f"{where}: unexpected entity type {record.entity_type!r}")
        elif not pattern.fullmatch(record.fqn):
            problems.append(f"{where}: not a well-formed {record.entity_type} fully-qualified name")
        for segment in record.fqn.split(SEPARATOR):
            if record.entity_type in {"customProperty", "lineageEdge"}:
                continue
            if not SAFE_SEGMENT.fullmatch(segment):
                problems.append(f"{where}: name segment {segment!r} is outside the safe alphabet")

        # Only a record that *creates* an entity defines an identity. Plan-only
        # records — asset attachment, lineage, deferred results — legitimately
        # name an entity created earlier, so they are not duplicates of it.
        key = (record.entity_type, record.fqn)
        if record.create is not None:
            if key in order_of:
                problems.append(f"{where}: duplicate fully-qualified name for this entity type")
            order_of[key] = record.order
            existing = type_of.get(record.fqn)
            if existing is not None and existing != record.entity_type:
                problems.append(
                    f"{record.fqn}: emitted as both {existing!r} and {record.entity_type!r}"
                )
            type_of[record.fqn] = record.entity_type

        # -- containment ------------------------------------------------------
        if record.entity_type == "container" and record.create is not None:
            expected_parent = parent_fqn(record.fqn)
            declared = [ref for ref in record.references if ref.field == "parent"]
            if expected_parent == SERVICE_NAME:
                if declared:
                    problems.append(
                        f"{where}: a top-level container's parent is its service, not a container"
                    )
            elif not declared:
                problems.append(f"{where}: nested container declares no parent reference")
            else:
                for reference in declared:
                    if reference.target != expected_parent:
                        problems.append(
                            f"{where}: parent reference {reference.target!r} is not the "
                            f"containing FQN {expected_parent!r}"
                        )
                    if reference.target == record.fqn:
                        problems.append(f"{where}: container is its own parent")

        # -- lineage ----------------------------------------------------------
        if record.entity_type == "lineageEdge":
            targets = [ref.target for ref in record.references]
            if len(set(targets)) != len(targets):
                problems.append(f"{where}: self-lineage — both endpoints are the same entity")

        # -- custom-property keys ---------------------------------------------
        if record.entity_type == "customProperty":
            name = str((record.create or {}).get("name", ""))
            if not CUSTOM_PROPERTY_NAME.fullmatch(name):
                problems.append(f"{where}: custom-property name {name!r} is not valid")

        # -- the privilege boundary -------------------------------------------
        leaked = sorted(
            key for key in _extension(record) if str(key).startswith(TRUTH_ONLY_PROPERTY_PREFIX)
        )
        property_name = str((record.create or {}).get("name", ""))
        if record.entity_type == "customProperty" and property_name.startswith(
            TRUTH_ONLY_PROPERTY_PREFIX
        ):
            leaked = [property_name]
        if leaked and mode is ExportMode.OBSERVED:
            problems.append(
                f"{where}: observed export carries truth-only propert(ies) {', '.join(leaked)}"
            )
        if privileged_tag in _tag_fqns(record) and mode is ExportMode.OBSERVED:
            problems.append(f"{where}: observed export carries the privileged truth-export tag")
        if mode is ExportMode.OBSERVED and record.fqn == privileged_tag:
            problems.append("observed export emits the privileged truth-export tag")

        if mode is ExportMode.TRUTH and record.phase in ASSET_PHASES:
            if privileged_tag not in _tag_fqns(record):
                problems.append(f"{where}: truth export asset is not tagged privileged")
            if _extension(record).get(f"{TRUTH_ONLY_PROPERTY_PREFIX}Export") != "true":
                problems.append(
                    f"{where}: truth export asset lacks the "
                    f"{TRUTH_ONLY_PROPERTY_PREFIX}Export marker"
                )

    # -- reference closure -----------------------------------------------------
    for record in records:
        where = f"{record.phase} record {record.fqn!r}"
        for reference in record.references:
            if reference.builtin:
                if (reference.field, reference.target) not in BUILTIN_REFERENCES:
                    problems.append(
                        f"{where}: {reference.field}={reference.target!r} is not on the "
                        "OpenMetadata built-in allow-list"
                    )
                continue
            target_key = (reference.entity_type, reference.target)
            target_order = order_of.get(target_key)
            if target_order is None:
                problems.append(
                    f"{where}: references {reference.entity_type} {reference.target!r}, "
                    "which this export never emits"
                )
            elif target_order >= record.order:
                problems.append(
                    f"{where}: references {reference.target!r}, which is emitted later "
                    f"(order {target_order} >= {record.order})"
                )

    # Inline FQN-valued references are resolved the same way, because "emitted
    # inline" is a payload detail, not an exemption from closure.
    inline_fields = (
        ("service", "storageService"),
        ("glossary", "glossary"),
        ("classification", "classification"),
    )
    for record in records:
        create = record.create if isinstance(record.create, dict) else {}
        where = f"{record.phase} record {record.fqn!r}"
        for field_name, entity_type in inline_fields:
            value = create.get(field_name)
            if isinstance(value, str) and (entity_type, value) not in order_of:
                problems.append(
                    f"{where}: {field_name}={value!r} is never emitted as a {entity_type}"
                )
        for domain in create.get("domains", []) or []:
            if isinstance(domain, str) and ("domain", domain) not in order_of:
                problems.append(f"{where}: domain {domain!r} is never emitted")
        for tag in _tag_fqns(record):
            if ("tag", tag) not in order_of and ("glossaryTerm", tag) not in order_of:
                problems.append(f"{where}: tag {tag!r} is never emitted")

    return sorted(problems)


__all__ = [
    "FQN_PATTERNS",
    "CUSTOM_PROPERTY_NAME",
    "ASSET_ENTITY_TYPES",
    "ASSET_PHASES",
    "validate_plan",
]
