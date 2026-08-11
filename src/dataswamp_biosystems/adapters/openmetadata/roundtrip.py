"""Compare what an OpenMetadata catalogue holds against what the export sent.

Pure comparison. No filesystem, no network, no clock: everything here is a
function of an emitted plan and a :class:`Readback` structure that
:mod:`.readback` filled in. That is what makes the perturbation tests possible —
a fault can be injected into either side and the exact discrepancy asserted,
without a server.

Four claims, reported separately
--------------------------------
Collapsing them into one verdict would hide the distinction that matters most in
practice. A catalogue missing entities has a different problem from one that
mutated them, and both differ from one holding entities nobody sent it.

**completeness** — every emitted operation that should materialise did. An entity
the plan created is retrievable by its FQN; a declared asset attachment and a
declared lineage edge are present; a registered custom property exists.

**fidelity** — every value DataSwamp sent survives a normalization-equivalent
readback. The sent side is built from the *emitted plan*, not from what the
transport happened to put on the wire, so a transport that quietly altered a
payload would fail this claim rather than hide inside it.

**containment** — no unexpected DataSwamp-owned state, within scopes where
ownership can actually be proved. Coverage is declared per entity family and
reported honestly as unavailable where it cannot be established. A foreign entity
is never a DataSwamp discrepancy.

**observed-mode non-leakage** — no truth-only marker is present after ingesting an
observed export. The probes use only markers the *OpenMetadata export contract*
itself defines: the reserved ``dataswampTruth*`` custom-property namespace and the
privileged truth-export tag. Nothing here opens a bundle, a defect ledger, a rule
scope, a scenario file or an expected-finding set to build a stronger probe —
that would make verification a privileged operation, which is exactly what an
observed export exists to avoid.

A fault fails only the claim it violates wherever the semantics permit, and
``tests/adapters/openmetadata/test_roundtrip.py`` asserts that per fault.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dataswamp_biosystems.adapters.openmetadata.fqn import (
    CLASSIFICATION_NAME,
    NAMESPACE,
    SERVICE_NAME,
    tag_fqn,
)
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
    PlanRecord,
)
from dataswamp_biosystems.adapters.openmetadata.normalize import (
    TAG_LABEL_DERIVED_FIELDS,
    UNORDERED_FIELDS,
    forgive_additions,
    is_materialized_default,
    is_platform_generated,
    normalize_field,
    reconcile_html_escaping,
)

# Bumped when the emitted round-trip report's shape changes. Entirely separate
# from the DataHub round-trip schema: the two reports describe different
# catalogues and share no fields beyond the four claim names.
OM_ROUNDTRIP_SCHEMA_VERSION = 1

ABSENT = "<absent>"


class Claim(StrEnum):
    """The four things a round-trip judges, independently."""

    COMPLETENESS = "completeness"
    FIDELITY = "fidelity"
    CONTAINMENT = "containment"
    NON_LEAKAGE = "non-leakage"


class DiscrepancyKind(StrEnum):
    """What kind of disagreement was found."""

    MISSING_ENTITY = "missing-entity"
    MISSING_PROPERTY = "missing-custom-property"
    MISSING_RELATIONSHIP = "missing-relationship"
    MUTATED = "mutated"
    EXTRA_FIELD = "extra-field"
    EXTRA_RELATIONSHIP = "extra-relationship"
    EXTRA_ENTITY = "extra-entity"


class Coverage(StrEnum):
    """How well DataSwamp ownership can be established for one entity family."""

    #: A server-side scope filter proves ownership structurally.
    PROVABLE = "provable"
    #: Enumerated globally; ownership evidenced by DataSwamp's reserved FQN prefix.
    NAMESPACE = "namespace-prefix"
    #: Not enumerated. Extra-entity detection is not claimed for this family.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ContainmentFamily:
    """One entity family, and what can honestly be said about extras in it.

    ``list_params`` are the server-side filters that make ownership structural
    rather than nominal. Where they exist, an enumerated entity is DataSwamp's
    because of *where it sits* — a container under DataSwamp's StorageService, a
    tag under DataSwamp's Classification — which no naming coincidence can fake.

    Where they do not, ownership rests on the reserved FQN prefix that
    :mod:`~dataswamp_biosystems.adapters.openmetadata.fqn` puts on every
    root-level identity. That is good evidence and it is stated as exactly that:
    a third party who chose the same prefix would be misattributed, which is why
    the coverage value says ``namespace-prefix`` and not ``provable``.
    """

    entity_type: str
    coverage: Coverage
    prefix: str = ""
    list_params: tuple[tuple[str, str], ...] = ()
    reason: str = ""

    def owns(self, fqn: str) -> bool:
        """Whether ``fqn`` is unambiguously DataSwamp's, under this family's rule."""
        if self.coverage is Coverage.UNAVAILABLE:
            return False
        if not self.prefix:
            return True
        return (
            fqn == self.prefix
            or fqn.startswith(f"{self.prefix}.")
            or fqn.startswith(f"{self.prefix}-")
        )

    @property
    def params(self) -> dict[str, str]:
        return dict(self.list_params)


# Ownership is settled per family, never by scanning the whole catalogue. An
# entity outside every rule below is somebody else's and is ignored entirely —
# it is not a DataSwamp extra and must never be reported as one.
CONTAINMENT_FAMILIES: tuple[ContainmentFamily, ...] = (
    ContainmentFamily(
        entity_type="container",
        coverage=Coverage.PROVABLE,
        prefix=SERVICE_NAME,
        list_params=(("service", SERVICE_NAME),),
        reason=(
            "ContainerResource's list endpoint accepts a `service` filter, so the "
            "enumeration is scoped to DataSwamp's own StorageService by the server. "
            "Ownership is structural: a container under this service is in DataSwamp's "
            "hierarchy regardless of what it is named."
        ),
    ),
    ContainmentFamily(
        entity_type="tag",
        coverage=Coverage.PROVABLE,
        prefix=CLASSIFICATION_NAME,
        list_params=(("parent", CLASSIFICATION_NAME),),
        reason=(
            "TagResource's list endpoint accepts a `parent` filter, so the enumeration "
            "is scoped to DataSwamp's own Classification by the server."
        ),
    ),
    ContainmentFamily(
        entity_type="domain",
        coverage=Coverage.NAMESPACE,
        prefix=NAMESPACE,
        reason=(
            "OpenMetadata's Domain namespace is global and its list endpoint offers no "
            "ownership filter, so ownership rests on the reserved `dataswamp-` prefix "
            "every root-level DataSwamp identity carries."
        ),
    ),
    ContainmentFamily(
        entity_type="dataProduct",
        coverage=Coverage.NAMESPACE,
        prefix=NAMESPACE,
        reason="Global namespace; ownership from the reserved `dataswamp-` prefix.",
    ),
    ContainmentFamily(
        entity_type="team",
        coverage=Coverage.NAMESPACE,
        prefix=NAMESPACE,
        reason="Global namespace; ownership from the reserved `dataswamp-` prefix.",
    ),
    ContainmentFamily(
        entity_type="glossary",
        coverage=Coverage.NAMESPACE,
        prefix=NAMESPACE,
        reason="Global namespace; ownership from the reserved `dataswamp-` prefix.",
    ),
    ContainmentFamily(
        entity_type="glossaryTerm",
        coverage=Coverage.NAMESPACE,
        prefix=NAMESPACE,
        reason=(
            "A term's FQN begins with its glossary's, which carries the reserved "
            "`dataswamp-` prefix."
        ),
    ),
    ContainmentFamily(
        entity_type="classification",
        coverage=Coverage.NAMESPACE,
        prefix=CLASSIFICATION_NAME,
        reason="Global namespace; DataSwamp owns exactly the `dataswamp` Classification.",
    ),
    ContainmentFamily(
        entity_type="storageService",
        coverage=Coverage.NAMESPACE,
        prefix=SERVICE_NAME,
        reason="Global namespace; DataSwamp owns exactly the `dataswamp-biosystems` service.",
    ),
)

SCANNABLE_FAMILIES: tuple[ContainmentFamily, ...] = tuple(
    family for family in CONTAINMENT_FAMILIES if family.coverage is not Coverage.UNAVAILABLE
)


@dataclass(frozen=True)
class LeakProbe:
    """One structural check for benchmark ground truth in a live catalogue."""

    name: str
    description: str


# Every probe uses a marker the OpenMetadata *export contract* defines, and
# nothing else. No bundle, ledger, rule scope, scenario or expected-finding set
# is consulted — verifying an observed export must stay unprivileged.
LEAK_PROBES: tuple[LeakProbe, ...] = (
    LeakProbe(
        name="truth-only-extension-key",
        description=(
            f"No entity carries a custom-property key beginning {TRUTH_ONLY_PROPERTY_PREFIX!r}. "
            "That namespace is reserved by the mapping for privileged truth exports."
        ),
    ),
    LeakProbe(
        name="privileged-truth-tag",
        description=(
            f"No entity carries the {tag_fqn(TAG_PRIVILEGED)!r} tag, which a truth export "
            "applies to every asset and an observed export never emits."
        ),
    ),
    LeakProbe(
        name="truth-only-custom-property-registered",
        description=(
            f"No custom property named {TRUTH_ONLY_PROPERTY_PREFIX}* is registered against "
            "an OpenMetadata type."
        ),
    ),
)


@dataclass(frozen=True)
class FieldDifference:
    """One field-level disagreement, at an exact recursive path."""

    path: str
    sent: str
    retrieved: str

    def as_record(self) -> dict[str, Any]:
        return {"path": self.path, "sent": self.sent, "retrieved": self.retrieved}


@dataclass(frozen=True)
class Discrepancy:
    """One disagreement between the emitted plan and the catalogue."""

    kind: DiscrepancyKind
    claim: Claim
    entity_type: str
    fqn: str
    detail: str = ""
    differences: tuple[FieldDifference, ...] = ()

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "kind": self.kind.value,
            "claim": self.claim.value,
            "entityType": self.entity_type,
            "fullyQualifiedName": self.fqn,
        }
        if self.detail:
            record["detail"] = self.detail
        if self.differences:
            record["differences"] = [item.as_record() for item in self.differences]
        return record

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.entity_type, self.fqn, self.kind.value)


@dataclass(frozen=True)
class LeakFinding:
    """One piece of benchmark ground truth found in a live catalogue."""

    probe: str
    entity_type: str
    fqn: str
    marker: str

    def as_record(self) -> dict[str, Any]:
        return {
            "probe": self.probe,
            "entityType": self.entity_type,
            "fullyQualifiedName": self.fqn,
            "marker": self.marker,
        }


@dataclass(frozen=True)
class Readback:
    """Everything retrieved from a catalogue, in a shape comparison can use.

    Filled in by :mod:`.readback`; constructed directly by tests. Keeping this a
    plain structure is what lets every perturbation test run without a server.
    """

    #: {(entity_type, fqn): entity document, or None where the catalogue lacked it}
    entities: dict[tuple[str, str], dict[str, Any] | None] = field(default_factory=dict)
    #: {om_entity_type: {property name: property document}}
    custom_properties: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    #: {data product FQN: [asset FQN]}, or absent where the product was not retrievable
    data_product_assets: dict[str, list[str]] = field(default_factory=dict)
    #: {container FQN: [(from FQN, to FQN)]} as the catalogue reports them
    lineage_edges: set[tuple[str, str]] = field(default_factory=set)
    #: {entity_type: {fqn}} for the families that were enumerated
    enumerated: dict[str, set[str]] = field(default_factory=dict)
    #: Families actually scanned, so the report can say what coverage it has
    scanned_families: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RoundTripResult:
    """The judged outcome of one round-trip."""

    mode: ExportMode
    discrepancies: tuple[Discrepancy, ...]
    leak_findings: tuple[LeakFinding, ...]
    counts: dict[str, int]
    coverage: dict[str, str]

    def of_claim(self, claim: Claim) -> tuple[Discrepancy, ...]:
        return tuple(item for item in self.discrepancies if item.claim is claim)

    def of_kind(self, kind: DiscrepancyKind) -> tuple[Discrepancy, ...]:
        return tuple(item for item in self.discrepancies if item.kind is kind)

    def claim_passed(self, claim: Claim) -> bool:
        if claim is Claim.NON_LEAKAGE:
            return not self.leak_findings
        return not self.of_claim(claim)

    @property
    def clean(self) -> bool:
        return not self.discrepancies and not self.leak_findings


# ---------------------------------------------------------------------------
# Building the sent view from the emitted plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SentEntity:
    """What the emitted plan says one entity should look like."""

    entity_type: str
    fqn: str
    fields: dict[str, Any]


def build_sent_view(
    records: Sequence[PlanRecord],
) -> tuple[
    tuple[SentEntity, ...],
    dict[str, dict[str, dict[str, Any]]],
    dict[str, list[str]],
    set[tuple[str, str]],
]:
    """Project the emitted plan into the four things a readback is compared against.

    The sent side is derived from the plan, never from the transport. A reference
    the plan declares as a :class:`Reference` block contributes its *target FQN*
    to the field it belongs in — which is the value the plan asserts, and the
    value a readback's expanded ``EntityReference`` projects back to.
    """
    entities: list[SentEntity] = []
    properties: dict[str, dict[str, dict[str, Any]]] = {}
    assets: dict[str, list[str]] = {}
    lineage: set[tuple[str, str]] = set()

    for record in records:
        if record.phase == "custom-property":
            target = next(
                (ref.target for ref in record.references if ref.field == "entityType"), ""
            )
            body = dict(record.create or {})
            name = str(body.get("name", ""))
            properties.setdefault(target, {})[name] = body
            continue
        if record.phase == "data-product-assets":
            assets[record.fqn] = sorted(
                str(item.get("fullyQualifiedName"))
                for item in (record.plan or {}).get("assets", [])
                if isinstance(item, dict)
            )
            continue
        if record.phase == "lineage":
            plan = record.plan or {}
            source = plan.get("fromEntity")
            target_side = plan.get("toEntity")
            if isinstance(source, dict) and isinstance(target_side, dict):
                lineage.add(
                    (
                        str(source.get("fullyQualifiedName")),
                        str(target_side.get("fullyQualifiedName")),
                    )
                )
            continue
        if record.phase == "test-result" or record.create is None:
            # Deferred, explicitly blocked results are never transmitted, so they
            # are never expected back. See mapping-coverage.json.
            continue

        fields = dict(record.create)
        for reference in record.references:
            if reference.builtin:
                continue
            if reference.many:
                existing = fields.get(reference.field)
                items = list(existing) if isinstance(existing, list) else []
                items.append(reference.target)
                fields[reference.field] = items
            else:
                fields[reference.field] = reference.target
        # The FQN is DataSwamp's identity and the address the readback used, so
        # it is asserted rather than assumed: a server that answered a different
        # entity must not compare equal.
        fields["fullyQualifiedName"] = record.fqn
        entities.append(SentEntity(record.entity_type, record.fqn, fields))

    _expect_attachment_reverse_edges(entities, assets)
    return tuple(entities), properties, assets, lineage


def _expect_attachment_reverse_edges(
    entities: list[SentEntity], assets: dict[str, list[str]]
) -> None:
    """Record the ``dataProducts`` an attachment makes appear on its assets.

    ``bulkAddAssets`` writes a single ``DATA_PRODUCT --HAS--> asset``
    relationship, and OpenMetadata reads that same relationship back to populate
    the *asset's* ``dataProducts`` field. So a container carrying the product it
    was attached to is not the catalogue volunteering something — it is the
    visible half of a write the export itself asked for.

    That distinction decides how it is handled. Forgiving the field would mean
    ignoring the only readable evidence that the attachment landed on the right
    asset, and would hide a product attached to a container DataSwamp never
    named. So the expectation is *derived from the plan's own attachments* and
    compared like any other reference field: right products, no discrepancy;
    wrong or extra ones, a difference at an exact path.

    The plan's asset lists are keyed by product and this field is keyed by asset,
    so the relation is simply inverted here rather than re-derived from anything.
    """
    products_by_asset: dict[str, list[str]] = {}
    for product_fqn, asset_fqns in assets.items():
        for asset_fqn in asset_fqns:
            products_by_asset.setdefault(asset_fqn, []).append(product_fqn)

    for entity in entities:
        expected = products_by_asset.get(entity.fqn)
        if expected is not None:
            entity.fields["dataProducts"] = sorted(expected)


# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------


def _render(value: Any) -> str:
    if isinstance(value, str):
        return value
    return repr(value)


def _key(value: Any) -> str:
    """A stable ordering key for multiset comparison of an unordered list."""
    if isinstance(value, dict):
        return repr(sorted((str(k), _key(v)) for k, v in value.items()))
    if isinstance(value, list):
        return repr([_key(item) for item in value])
    return repr(value)


def _diff(sent: Any, retrieved: Any, path: str, unordered: bool = False) -> list[FieldDifference]:
    """Recursively compare two values, returning exact-path differences."""
    if isinstance(sent, dict) and isinstance(retrieved, dict):
        differences: list[FieldDifference] = []
        for key in sorted(set(sent) | set(retrieved)):
            child = f"{path}.{key}" if path else key
            if key not in sent:
                differences.append(FieldDifference(child, ABSENT, _render(retrieved[key])))
            elif key not in retrieved:
                differences.append(FieldDifference(child, _render(sent[key]), ABSENT))
            else:
                differences.extend(_diff(sent[key], retrieved[key], child))
        return differences
    if isinstance(sent, list) and isinstance(retrieved, list):
        if unordered:
            return _diff_unordered(sent, retrieved, path)
        differences = []
        for index in range(max(len(sent), len(retrieved))):
            child = f"{path}[{index}]"
            if index >= len(sent):
                differences.append(FieldDifference(child, ABSENT, _render(retrieved[index])))
            elif index >= len(retrieved):
                differences.append(FieldDifference(child, _render(sent[index]), ABSENT))
            else:
                differences.extend(_diff(sent[index], retrieved[index], child))
        return differences
    if sent != retrieved:
        return [FieldDifference(path, _render(sent), _render(retrieved))]
    return []


def _diff_unordered(sent: list[Any], retrieved: list[Any], path: str) -> list[FieldDifference]:
    """Compare two lists as multisets, reporting only what is genuinely absent."""
    remaining = [_key(item) for item in retrieved]
    differences: list[FieldDifference] = []
    for item in sent:
        key = _key(item)
        if key in remaining:
            remaining.remove(key)
        else:
            differences.append(FieldDifference(f"{path}[]", _render(item), ABSENT))
    for index, key in enumerate(remaining):
        original = next((item for item in retrieved if _key(item) == key), key)
        differences.append(FieldDifference(f"{path}[]", ABSENT, _render(original)))
        del index
    return differences


def _normalize_tag_labels(sent: Any, retrieved: Any) -> Any:
    """Strip the server's denormalized tag-label copies, additively."""
    if not isinstance(retrieved, list):
        return retrieved
    sent_by_fqn = {
        str(item.get("tagFQN")): item
        for item in (sent if isinstance(sent, list) else [])
        if isinstance(item, dict)
    }
    stripped: list[Any] = []
    for item in retrieved:
        if not isinstance(item, dict):
            stripped.append(item)
            continue
        counterpart = sent_by_fqn.get(str(item.get("tagFQN")), {})
        stripped.append(forgive_additions(counterpart, item, TAG_LABEL_DERIVED_FIELDS))
    return stripped


def compare_entity(sent: SentEntity, retrieved: dict[str, Any]) -> list[Discrepancy]:
    """Compare one retrieved entity against what the plan said it should be."""
    discrepancies: list[Discrepancy] = []
    differences: list[FieldDifference] = []

    for name in sorted(sent.fields):
        sent_value = normalize_field(name, sent.fields[name])
        if name not in retrieved:
            differences.append(FieldDifference(name, _render(sent_value), ABSENT))
            continue
        retrieved_value = normalize_field(name, retrieved[name])
        retrieved_value = reconcile_html_escaping(name, sent_value, retrieved_value)
        if name == "tags":
            retrieved_value = _normalize_tag_labels(sent.fields.get(name), retrieved_value)
        differences.extend(
            _diff(sent_value, retrieved_value, name, unordered=name in UNORDERED_FIELDS)
        )

    if differences:
        discrepancies.append(
            Discrepancy(
                kind=DiscrepancyKind.MUTATED,
                claim=Claim.FIDELITY,
                entity_type=sent.entity_type,
                fqn=sent.fqn,
                detail="a value the export sent did not survive readback",
                differences=tuple(sorted(differences, key=lambda item: item.path)),
            )
        )

    # A field the plan never sent is an extra unless the contract recognises it:
    # either the server generates it outright, or it is the exact default the
    # server materializes for an omitted optional. Both conditions are checked
    # against what actually came back, so a populated value is still reported.
    extra = sorted(
        name
        for name in retrieved
        if name not in sent.fields
        and not is_platform_generated(sent.entity_type, name)
        and not is_materialized_default(sent.entity_type, name, retrieved[name])
    )
    if extra:
        discrepancies.append(
            Discrepancy(
                kind=DiscrepancyKind.EXTRA_FIELD,
                claim=Claim.CONTAINMENT,
                entity_type=sent.entity_type,
                fqn=sent.fqn,
                detail=(
                    "the catalogue holds field(s) the export never sent and the "
                    "normalization contract recognises as neither platform-generated nor "
                    "a materialized default"
                ),
                differences=tuple(
                    FieldDifference(name, ABSENT, _render(retrieved[name])) for name in extra
                ),
            )
        )
    return discrepancies


# ---------------------------------------------------------------------------
# Leak probes
# ---------------------------------------------------------------------------


def _probe_entity(entity_type: str, fqn: str, document: dict[str, Any]) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    extension = document.get("extension")
    if isinstance(extension, dict):
        for key in sorted(extension):
            if str(key).startswith(TRUTH_ONLY_PROPERTY_PREFIX):
                findings.append(LeakFinding("truth-only-extension-key", entity_type, fqn, str(key)))
    privileged = tag_fqn(TAG_PRIVILEGED)
    tags = document.get("tags")
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, dict) and item.get("tagFQN") == privileged:
                findings.append(LeakFinding("privileged-truth-tag", entity_type, fqn, privileged))
    return findings


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------


def compare(  # noqa: C901 - one pass over four independent claims, by design
    records: Sequence[PlanRecord],
    readback: Readback,
    mode: ExportMode,
) -> RoundTripResult:
    """Judge the four claims for one emitted plan against one readback."""
    entities, properties, assets, lineage = build_sent_view(records)
    discrepancies: list[Discrepancy] = []
    leaks: list[LeakFinding] = []

    retrieved_count = 0
    matched = 0

    # -- entities: completeness, fidelity, containment-of-fields --------------
    for sent in entities:
        document = readback.entities.get((sent.entity_type, sent.fqn))
        if document is None:
            discrepancies.append(
                Discrepancy(
                    kind=DiscrepancyKind.MISSING_ENTITY,
                    claim=Claim.COMPLETENESS,
                    entity_type=sent.entity_type,
                    fqn=sent.fqn,
                    detail="the export created this entity but the catalogue does not hold it",
                )
            )
            continue
        retrieved_count += 1
        found = compare_entity(sent, document)
        if not any(item.claim is Claim.FIDELITY for item in found):
            matched += 1
        discrepancies.extend(found)
        if mode is ExportMode.OBSERVED:
            leaks.extend(_probe_entity(sent.entity_type, sent.fqn, document))

    # -- custom properties -----------------------------------------------------
    for entity_type in sorted(properties):
        registered = readback.custom_properties.get(entity_type, {})
        for name in sorted(properties[entity_type]):
            if name not in registered:
                discrepancies.append(
                    Discrepancy(
                        kind=DiscrepancyKind.MISSING_PROPERTY,
                        claim=Claim.COMPLETENESS,
                        entity_type="customProperty",
                        fqn=f"{entity_type}.{name}",
                        detail=(
                            "the export registered this custom property but the "
                            "catalogue's type does not declare it"
                        ),
                    )
                )
        for name in sorted(registered):
            if name.startswith(TRUTH_ONLY_PROPERTY_PREFIX) and mode is ExportMode.OBSERVED:
                leaks.append(
                    LeakFinding(
                        "truth-only-custom-property-registered",
                        "customProperty",
                        f"{entity_type}.{name}",
                        name,
                    )
                )
            if name.startswith(NAMESPACE) and name not in properties[entity_type]:
                discrepancies.append(
                    Discrepancy(
                        kind=DiscrepancyKind.EXTRA_FIELD,
                        claim=Claim.CONTAINMENT,
                        entity_type="customProperty",
                        fqn=f"{entity_type}.{name}",
                        detail=(
                            "the catalogue declares a DataSwamp-namespaced custom "
                            "property the export never registered"
                        ),
                    )
                )

    # -- data-product asset attachments ---------------------------------------
    for product in sorted(assets):
        expected = assets[product]
        actual = readback.data_product_assets.get(product)
        if actual is None:
            discrepancies.append(
                Discrepancy(
                    kind=DiscrepancyKind.MISSING_RELATIONSHIP,
                    claim=Claim.COMPLETENESS,
                    entity_type="dataProduct",
                    fqn=product,
                    detail="the catalogue reports no assets for this data product",
                )
            )
            continue
        for asset in expected:
            if asset not in actual:
                discrepancies.append(
                    Discrepancy(
                        kind=DiscrepancyKind.MISSING_RELATIONSHIP,
                        claim=Claim.COMPLETENESS,
                        entity_type="dataProduct",
                        fqn=product,
                        detail=f"asset {asset} is not attached",
                    )
                )
        for asset in sorted(set(actual) - set(expected)):
            discrepancies.append(
                Discrepancy(
                    kind=DiscrepancyKind.EXTRA_RELATIONSHIP,
                    claim=Claim.CONTAINMENT,
                    entity_type="dataProduct",
                    fqn=product,
                    detail=f"asset {asset} is attached but was never sent",
                )
            )

    # -- lineage ---------------------------------------------------------------
    for source, target in sorted(lineage):
        if (source, target) not in readback.lineage_edges:
            discrepancies.append(
                Discrepancy(
                    kind=DiscrepancyKind.MISSING_RELATIONSHIP,
                    claim=Claim.COMPLETENESS,
                    entity_type="lineageEdge",
                    fqn=f"{source}->{target}",
                    detail="the catalogue does not report this lineage edge",
                )
            )
    for source, target in sorted(readback.lineage_edges - lineage):
        discrepancies.append(
            Discrepancy(
                kind=DiscrepancyKind.EXTRA_RELATIONSHIP,
                claim=Claim.CONTAINMENT,
                entity_type="lineageEdge",
                fqn=f"{source}->{target}",
                detail="the catalogue reports a lineage edge the export never sent",
            )
        )

    # -- extra entities, within provable scopes only ---------------------------
    sent_fqns: dict[str, set[str]] = {}
    for sent in entities:
        sent_fqns.setdefault(sent.entity_type, set()).add(sent.fqn)

    coverage: dict[str, str] = {}
    for family in CONTAINMENT_FAMILIES:
        if family.entity_type not in readback.scanned_families:
            coverage[family.entity_type] = Coverage.UNAVAILABLE.value
            continue
        coverage[family.entity_type] = family.coverage.value
        known = sent_fqns.get(family.entity_type, set())
        for fqn in sorted(readback.enumerated.get(family.entity_type, set())):
            if not family.owns(fqn):
                # Somebody else's entity. Not a DataSwamp discrepancy, and never
                # reported as one.
                continue
            if fqn not in known:
                discrepancies.append(
                    Discrepancy(
                        kind=DiscrepancyKind.EXTRA_ENTITY,
                        claim=Claim.CONTAINMENT,
                        entity_type=family.entity_type,
                        fqn=fqn,
                        detail=(
                            "the catalogue holds a DataSwamp-owned entity the export "
                            f"never sent (ownership evidence: {family.coverage.value})"
                        ),
                    )
                )

    counts = {
        "sent_entities": len(entities),
        "retrieved_entities": retrieved_count,
        "matched_entities": matched,
        "sent_custom_properties": sum(len(items) for items in properties.values()),
        "sent_asset_attachments": sum(len(items) for items in assets.values()),
        "sent_lineage_edges": len(lineage),
    }

    return RoundTripResult(
        mode=mode,
        discrepancies=tuple(sorted(discrepancies, key=lambda item: item.sort_key)),
        leak_findings=tuple(
            sorted(leaks, key=lambda item: (item.probe, item.entity_type, item.fqn, item.marker))
        ),
        counts=counts,
        coverage=dict(sorted(coverage.items())),
    )


__all__ = [
    "OM_ROUNDTRIP_SCHEMA_VERSION",
    "ABSENT",
    "Claim",
    "DiscrepancyKind",
    "Coverage",
    "ContainmentFamily",
    "CONTAINMENT_FAMILIES",
    "SCANNABLE_FAMILIES",
    "LeakProbe",
    "LEAK_PROBES",
    "FieldDifference",
    "Discrepancy",
    "LeakFinding",
    "Readback",
    "RoundTripResult",
    "SentEntity",
    "build_sent_view",
    "compare_entity",
    "compare",
]
