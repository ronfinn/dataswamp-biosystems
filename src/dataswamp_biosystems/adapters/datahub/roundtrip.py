"""Compare what DataSwamp emitted against what a catalogue actually holds.

Everything here is a **pure function of two aspect maps** — the proposals the
export contains, and the aspects read back from a server. No socket is opened,
no file is read and no clock is consulted, which is what makes the whole
round-trip contract testable offline with hand-built inputs. All I/O lives in
:mod:`~dataswamp_biosystems.adapters.datahub.client` and
:mod:`~dataswamp_biosystems.adapters.datahub.readback`.

Four claims are computed and reported **separately**, never collapsed into one
pass/fail:

completeness
    Every ``(URN, aspect)`` the export contains is retrievable from the server.
fidelity
    Each retrieved aspect is semantically equal to the emitted one, after the
    versioned normalization contract. Differences are reported as precise
    recursive field paths, because "datasetProperties differs" is not a
    diagnosis.
containment
    The server holds no DataSwamp aspect or entity the export did not contain —
    within a deliberately conservative scope, described below.
non-leakage
    An ``observed`` export leaves no ground-truth marker in the catalogue.

Containment scope is conservative on purpose. A DataSwamp benchmark is ingested
into somebody's DataHub, alongside their real estate. Reporting one of their
datasets as a "DataSwamp extra" would be a false accusation about their data, so
namespace-wide enumeration is permitted only where a URN *unambiguously*
identifies DataSwamp ownership. Where it does not, coverage is reported as
unavailable rather than guessed at — see :data:`ENTITY_FAMILIES`.

Non-leakage probes read only the **emitted export contract**: the truth-only
property prefix and the privileged truth-export tag that the mapping layer
already defines. They never open the bundle, the defect ledgers, the rule scope,
the scenarios, the expected findings or remediations, or the control partition.
Strengthening a probe by consulting the answer key would make the live commands
privileged, and the whole point of an observed export is that it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dataswamp_biosystems.adapters.datahub import urns
from dataswamp_biosystems.adapters.datahub.mapping import (
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
)
from dataswamp_biosystems.adapters.datahub.normalize import is_unordered, normalize_aspect
from dataswamp_biosystems.truth import serialize

# Bumped when the emitted round-trip report's shape changes. Owned by this
# layer alone; no other schema in the project moves with it.
ROUNDTRIP_SCHEMA_VERSION = 1

# Rendered into a difference record when one side has no value at all, so an
# added field and a field set to null stay distinguishable.
ABSENT = "<absent>"


class Claim(StrEnum):
    """The four things a round-trip proves, reported independently."""

    COMPLETENESS = "completeness"
    FIDELITY = "fidelity"
    CONTAINMENT = "containment"
    NON_LEAKAGE = "non-leakage"


class DiscrepancyKind(StrEnum):
    """What kind of disagreement was found between export and catalogue."""

    MISSING = "missing"
    MUTATED = "mutated"
    EXTRA_ASPECT = "extra-aspect"
    EXTRA_ENTITY = "extra-entity"


class Coverage(StrEnum):
    """Whether extra-entity scanning is possible for an entity family."""

    SCANNED = "scanned"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class EntityFamily:
    """One DataHub entity type, and whether DataSwamp ownership is decidable.

    ``urn_prefix`` is the prefix that unambiguously marks a URN as DataSwamp's.
    When it is ``None`` the family cannot be enumerated safely: either the URN
    carries no namespace at all (a bare id, which any producer could also use),
    or identity is an opaque GUID that says nothing about its origin. Those
    families report :attr:`Coverage.UNAVAILABLE` rather than pretending to a
    certainty the URN scheme does not support.
    """

    entity_type: str
    urn_prefix: str | None
    reason: str

    @property
    def scannable(self) -> bool:
        return self.urn_prefix is not None

    def owns(self, urn: str) -> bool:
        return self.urn_prefix is not None and urn.startswith(self.urn_prefix)


# Every entity type the adapter emits, and whether its URN namespace settles the
# question of ownership. Documented in ``docs/datahub.md``; changing a family
# from unavailable to scanned is a claim about URN uniqueness and needs the same
# scrutiny as widening the normalization ignore list.
ENTITY_FAMILIES: tuple[EntityFamily, ...] = (
    EntityFamily(
        "dataset",
        f"urn:li:dataset:({urns.PLATFORM_URN},{urns.NAMESPACE}.",
        "the platform and dataset-name namespace are both DataSwamp's",
    ),
    EntityFamily(
        "dataProduct",
        f"urn:li:dataProduct:{urns.PLATFORM_ID}.",
        "data-product URNs are namespaced by the DataSwamp platform id",
    ),
    EntityFamily(
        "domain",
        f"urn:li:domain:{urns.PLATFORM_ID}.",
        "domain URNs are namespaced by the DataSwamp platform id",
    ),
    EntityFamily(
        "glossaryNode",
        f"urn:li:glossaryNode:{urns.PLATFORM_ID}.",
        "glossary-node URNs are namespaced by the DataSwamp platform id",
    ),
    EntityFamily(
        "glossaryTerm",
        f"urn:li:glossaryTerm:{urns.PLATFORM_ID}.",
        "glossary-term URNs are namespaced by the DataSwamp platform id",
    ),
    EntityFamily(
        "corpGroup",
        None,
        "group URNs are a bare team id with no namespace, so a group of the same "
        "name from the user's own directory is indistinguishable from ours",
    ),
    EntityFamily(
        "tag",
        None,
        "tag URNs are a bare tag name with no namespace; a user's own tag could "
        "share it, and reporting theirs as a DataSwamp extra would be a false claim",
    ),
    EntityFamily(
        "container",
        None,
        "container identity is an opaque GUID, which carries no evidence of who created it",
    ),
    EntityFamily(
        "assertion",
        None,
        "assertion identity is an opaque GUID, which carries no evidence of who created it",
    ),
)

SCANNABLE_FAMILIES: tuple[EntityFamily, ...] = tuple(f for f in ENTITY_FAMILIES if f.scannable)


@dataclass(frozen=True)
class LeakProbe:
    """One universal ground-truth marker, checked against retrieved metadata.

    Both probes below are drawn from the adapter's own emitted-export contract —
    the truth-only property prefix and the privileged tag — so a probe never
    needs the benchmark answer key to be meaningful.
    """

    name: str
    description: str


LEAK_PROBES: tuple[LeakProbe, ...] = (
    LeakProbe(
        "truth-only-property",
        f"no custom property may begin with {TRUTH_ONLY_PROPERTY_PREFIX!r}, which the "
        "mapping layer uses exclusively for privileged truth-export fields",
    ),
    LeakProbe(
        "privileged-truth-tag",
        f"neither the tag URN {urns.tag_urn(TAG_PRIVILEGED)!r} nor a reference to it may "
        "appear, since it marks a privileged truth export",
    ),
)


@dataclass(frozen=True, order=True)
class FieldDifference:
    """One precise disagreement inside an aspect payload."""

    path: str
    sent: str
    retrieved: str

    def as_record(self) -> dict[str, Any]:
        return {"path": self.path, "sent": self.sent, "retrieved": self.retrieved}


@dataclass(frozen=True, order=True)
class Discrepancy:
    """One disagreement between the emitted export and the catalogue."""

    kind: DiscrepancyKind
    entity_type: str
    entity_urn: str
    aspect_name: str = ""
    differences: tuple[FieldDifference, ...] = ()
    detail: str = ""

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "kind": self.kind.value,
            "entity_type": self.entity_type,
            "entity_urn": self.entity_urn,
        }
        if self.aspect_name:
            record["aspect_name"] = self.aspect_name
        if self.differences:
            record["differences"] = [difference.as_record() for difference in self.differences]
        if self.detail:
            record["detail"] = self.detail
        return record


@dataclass(frozen=True, order=True)
class LeakFinding:
    """One ground-truth marker found in the catalogue for an observed export."""

    probe: str
    entity_urn: str
    aspect_name: str
    marker: str

    def as_record(self) -> dict[str, Any]:
        return {
            "probe": self.probe,
            "entity_urn": self.entity_urn,
            "aspect_name": self.aspect_name,
            "marker": self.marker,
        }


@dataclass(frozen=True)
class RetrievedAspect:
    """One aspect as the catalogue holds it."""

    entity_type: str
    entity_urn: str
    aspect_name: str
    payload: Any


@dataclass(frozen=True)
class Readback:
    """Everything read back from a catalogue for one round-trip.

    ``scanned_families`` records which entity families were actually enumerated
    for extra entities; anything absent from it is reported as unavailable
    coverage rather than as "clean".
    """

    aspects: tuple[RetrievedAspect, ...]
    scanned_families: frozenset[str] = frozenset()
    namespace_urns: frozenset[str] = frozenset()


@dataclass
class RoundTripResult:
    """The outcome of one comparison: four claims, and the evidence for each."""

    mode: ExportMode
    sent_keys: tuple[tuple[str, str], ...]
    discrepancies: tuple[Discrepancy, ...]
    leak_findings: tuple[LeakFinding, ...]
    coverage: dict[str, str]
    counts: dict[str, int] = field(default_factory=dict)

    def of_kind(self, kind: DiscrepancyKind) -> tuple[Discrepancy, ...]:
        return tuple(item for item in self.discrepancies if item.kind is kind)

    @property
    def clean(self) -> bool:
        return not self.discrepancies and not self.leak_findings


def _render(value: Any) -> str:
    """Render one side of a difference compactly and deterministically."""
    if isinstance(value, str):
        return value
    return serialize.canonical_json(value)


def _key(value: Any) -> str:
    """Return a stable comparison key for an unordered list member."""
    return serialize.canonical_json(value)


def _diff(sent: Any, retrieved: Any, path: str, aspect_name: str) -> list[FieldDifference]:
    """Return every difference between two normalized payloads, as field paths.

    Recursion is structural: mappings are compared key by key (an added key is a
    difference, which is what makes an unknown server addition visible), lists
    positionally unless the field is documented as unordered, and scalars by
    equality. Paths read like ``customProperties.dataswamp_owner`` or
    ``upstreams[2].type``, so a reader can go straight to the field.
    """
    if isinstance(sent, dict) and isinstance(retrieved, dict):
        differences: list[FieldDifference] = []
        for name in sorted(set(sent) | set(retrieved)):
            child = f"{path}.{name}" if path else name
            if name not in retrieved:
                differences.append(FieldDifference(child, _render(sent[name]), ABSENT))
            elif name not in sent:
                differences.append(FieldDifference(child, ABSENT, _render(retrieved[name])))
            else:
                differences.extend(_diff(sent[name], retrieved[name], child, aspect_name))
        return differences

    if isinstance(sent, list) and isinstance(retrieved, list):
        if is_unordered(aspect_name, path):
            return _diff_unordered(sent, retrieved, path)
        differences = []
        for index in range(max(len(sent), len(retrieved))):
            child = f"{path}[{index}]"
            if index >= len(retrieved):
                differences.append(FieldDifference(child, _render(sent[index]), ABSENT))
            elif index >= len(sent):
                differences.append(FieldDifference(child, ABSENT, _render(retrieved[index])))
            else:
                differences.extend(_diff(sent[index], retrieved[index], child, aspect_name))
        return differences

    if sent != retrieved or type(sent) is not type(retrieved):
        return [FieldDifference(path, _render(sent), _render(retrieved))]
    return []


def _diff_unordered(sent: list[Any], retrieved: list[Any], path: str) -> list[FieldDifference]:
    """Compare an unordered field as a multiset.

    Members are reported as present-only-in-export or present-only-in-catalogue
    at ``path[*]``. Index-wise paths would be actively misleading here: for a
    field with no ordering semantics, "index 2 changed" describes an artefact of
    serialisation rather than a change to the data.
    """
    sent_keys = sorted(_key(item) for item in sent)
    retrieved_keys = sorted(_key(item) for item in retrieved)
    if sent_keys == retrieved_keys:
        return []
    remaining = list(retrieved_keys)
    differences: list[FieldDifference] = []
    for key in sent_keys:
        if key in remaining:
            remaining.remove(key)
        else:
            differences.append(FieldDifference(f"{path}[*]", key, ABSENT))
    differences.extend(FieldDifference(f"{path}[*]", ABSENT, key) for key in remaining)
    return sorted(differences)


def _entity_type_of(urn: str, fallback: str = "unknown") -> str:
    """Return the DataHub entity type named in a URN, without parsing its body."""
    parts = urn.split(":", 3)
    return parts[2] if len(parts) > 3 and parts[0] == "urn" and parts[1] == "li" else fallback


def _probe_payload(entity_urn: str, aspect_name: str, payload: Any) -> list[LeakFinding]:
    """Run every leak probe over one retrieved aspect payload."""
    findings: list[LeakFinding] = []
    privileged = urns.tag_urn(TAG_PRIVILEGED)

    def walk(node: Any, in_custom_properties: bool) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if in_custom_properties and key.startswith(TRUTH_ONLY_PROPERTY_PREFIX):
                    findings.append(
                        LeakFinding("truth-only-property", entity_urn, aspect_name, key)
                    )
                walk(value, in_custom_properties or key == "customProperties")
        elif isinstance(node, list):
            for item in node:
                walk(item, in_custom_properties)
        elif isinstance(node, str) and node == privileged:
            findings.append(LeakFinding("privileged-truth-tag", entity_urn, aspect_name, node))

    walk(payload, False)
    if entity_urn == privileged:
        findings.append(LeakFinding("privileged-truth-tag", entity_urn, aspect_name, entity_urn))
    return findings


def compare(
    sent: list[dict[str, Any]],
    readback: Readback,
    mode: ExportMode,
) -> RoundTripResult:
    """Compare an emitted proposal list against what a catalogue returned.

    ``sent`` is the export's proposals verbatim — the same records
    ``mcps.jsonl`` holds. Nothing is re-derived from a bundle or a generator:
    the emitted export *is* the statement of what should be in the catalogue.
    """
    sent_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    entity_types: dict[str, str] = {}
    for proposal in sent:
        urn = str(proposal["entityUrn"])
        aspect_name = str(proposal["aspectName"])
        sent_by_key[(urn, aspect_name)] = proposal
        entity_types[urn] = str(proposal["entityType"])

    retrieved_by_key = {(item.entity_urn, item.aspect_name): item for item in readback.aspects}

    discrepancies: list[Discrepancy] = []
    leak_findings: list[LeakFinding] = []
    matched = 0

    # Claim 1 — completeness, and claim 2 — fidelity, over the sent key set.
    for key in sorted(sent_by_key):
        urn, aspect_name = key
        entity_type = entity_types[urn]
        found = retrieved_by_key.get(key)
        if found is None:
            discrepancies.append(
                Discrepancy(DiscrepancyKind.MISSING, entity_type, urn, aspect_name)
            )
            continue
        expected = normalize_aspect(aspect_name, sent_by_key[key]["aspect"]["json"])
        actual = normalize_aspect(aspect_name, found.payload)
        differences = _diff(expected, actual, "", aspect_name)
        if differences:
            discrepancies.append(
                Discrepancy(
                    DiscrepancyKind.MUTATED,
                    entity_type,
                    urn,
                    aspect_name,
                    tuple(sorted(differences)),
                )
            )
        else:
            matched += 1

    # Claim 3 — containment. Extra aspects on URNs we sent, then extra entities
    # within the families whose URN namespace makes ownership unambiguous.
    for key in sorted(retrieved_by_key):
        if key in sent_by_key:
            continue
        urn, aspect_name = key
        if urn not in entity_types:
            continue  # An entity we never sent; handled as an extra entity below.
        discrepancies.append(
            Discrepancy(
                DiscrepancyKind.EXTRA_ASPECT,
                entity_types[urn],
                urn,
                aspect_name,
                detail="the catalogue holds an aspect this export never contained",
            )
        )

    coverage: dict[str, str] = {}
    for family in ENTITY_FAMILIES:
        scanned = family.scannable and family.entity_type in readback.scanned_families
        coverage[family.entity_type] = (
            Coverage.SCANNED.value if scanned else Coverage.UNAVAILABLE.value
        )
    for urn in sorted(readback.namespace_urns):
        if urn in entity_types:
            continue
        for family in SCANNABLE_FAMILIES:
            if family.owns(urn) and family.entity_type in readback.scanned_families:
                discrepancies.append(
                    Discrepancy(
                        DiscrepancyKind.EXTRA_ENTITY,
                        family.entity_type,
                        urn,
                        detail=(
                            "the catalogue holds an entity inside the DataSwamp namespace "
                            "that this export never contained"
                        ),
                    )
                )
                break

    # Claim 4 — non-leakage. Only meaningful for an observed export: a truth
    # export is *supposed* to carry these markers, and says so in its manifest.
    if mode is ExportMode.OBSERVED:
        for item in sorted(readback.aspects, key=lambda a: (a.entity_urn, a.aspect_name)):
            leak_findings.extend(_probe_payload(item.entity_urn, item.aspect_name, item.payload))

    counts = {
        "sent": len(sent_by_key),
        "retrieved": len(retrieved_by_key),
        "matched": matched,
    }
    return RoundTripResult(
        mode=mode,
        sent_keys=tuple(sorted(sent_by_key)),
        discrepancies=tuple(sorted(discrepancies)),
        leak_findings=tuple(sorted(set(leak_findings))),
        coverage=coverage,
        counts=counts,
    )


__all__ = [
    "ROUNDTRIP_SCHEMA_VERSION",
    "ABSENT",
    "Claim",
    "Coverage",
    "DiscrepancyKind",
    "Discrepancy",
    "FieldDifference",
    "EntityFamily",
    "ENTITY_FAMILIES",
    "SCANNABLE_FAMILIES",
    "LeakProbe",
    "LEAK_PROBES",
    "LeakFinding",
    "RetrievedAspect",
    "Readback",
    "RoundTripResult",
    "compare",
]
