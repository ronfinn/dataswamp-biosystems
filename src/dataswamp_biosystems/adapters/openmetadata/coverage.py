"""The mapping-coverage contract: what was mapped, how well, and what was not.

``mapping-coverage.json`` ships in **every** OpenMetadata export. It is a
first-class part of the export, not documentation that happens to be machine
readable, because the interesting property of a catalogue adapter is not what it
emits — it is what it quietly loses on the way. An adapter that drops stewardship
and says nothing looks identical, from its output, to one that had no
stewardship to drop.

Two orthogonal axes are reported, and neither substitutes for the other.

**Semantic classification** answers *how faithful is this mapping?*

``exact``
    OpenMetadata has the same concept with the same meaning. Nothing is lost.
``reasonable``
    OpenMetadata has no identical concept, but a defensible one exists and the
    source concept stays recoverable — typically through a ``dataswamp*`` custom
    property. A reader is not misled.
``lossy``
    A distinction DataSwamp draws does not survive. The values are carried, but
    the *meaning* is flattened, and a consumer reading only native OpenMetadata
    fields would draw a weaker conclusion than the source supports.
``unsupported``
    Deliberately not mapped. Either OpenMetadata has no honest home for it, or
    the only available home would require asserting something false.

**Operational state** answers *where does this show up?*

``materialized_in_entity_export``
    Emitted as entity create/update payloads in this export.
``deferred_live_write``
    Emitted as a plan, to be written by a later live path — not an entity here.
``deliberately_not_mapped``
    Emitted nowhere. The record exists so the omission is visible and counted.

The two are genuinely independent: a *reasonable* mapping can be deferred, and an
*unsupported* concept still has a source count worth reporting. Collapsing them
into one field would make "we chose not to" indistinguishable from "we could
not", which is precisely the distinction a governance benchmark should not blur.

Every concept the adapter knows about appears here, including the ones with a
zero emitted count. :func:`build_coverage` refuses to build a report that is
missing a concept or claims one it never declared, so a new emitted concept
cannot appear in an export without someone classifying it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

COVERAGE_SCHEMA_VERSION = 1


class Fidelity(StrEnum):
    """How faithfully OpenMetadata can hold a DataSwamp concept."""

    EXACT = "exact"
    REASONABLE = "reasonable"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"


class State(StrEnum):
    """Where a concept surfaces operationally."""

    MATERIALIZED = "materialized_in_entity_export"
    DEFERRED = "deferred_live_write"
    NOT_MAPPED = "deliberately_not_mapped"


@dataclass(frozen=True)
class Concept:
    """One row of the coverage contract.

    ``reason`` is mandatory for anything that is not :attr:`Fidelity.EXACT`. The
    dataclass enforces that in :meth:`__post_init__` rather than trusting a
    reviewer to notice a blank cell.
    """

    source_concept: str
    target: str | None
    fidelity: Fidelity
    state: State
    reason: str = ""

    def __post_init__(self) -> None:
        if self.fidelity is not Fidelity.EXACT and not self.reason:
            raise ValueError(f"{self.source_concept}: a non-exact mapping needs a reason")
        if self.fidelity is Fidelity.UNSUPPORTED and self.target is not None:
            raise ValueError(f"{self.source_concept}: an unsupported mapping has no target")


# The complete catalogue of DataSwamp concepts this adapter has an opinion about.
# Order is the reading order of the report, which is deliberately the order of the
# load plan rather than alphabetical: a reader following the export sees the same
# sequence here.
CONCEPTS: tuple[Concept, ...] = (
    Concept(
        source_concept="company",
        target="storageService",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "OpenMetadata has no 'organisation' entity that owns a container tree, so the "
            "fictional company becomes the StorageService rooting the hierarchy. serviceType "
            "is CustomStorage and no storage connection is fabricated, because the estate is "
            "not actually in S3, ADLS or GCS."
        ),
    ),
    Concept(
        source_concept="programme",
        target="domain",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "A research programme is a governance grouping, which is what a Domain is. "
            "OpenMetadata requires a domainType from a fixed taxonomy; Source-aligned is the "
            "closest honest member and the source concept is preserved in dataswampEntityType."
        ),
    ),
    Concept(
        source_concept="study",
        target="container",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "A study is a scientific grouping OpenMetadata has no entity for. It becomes an "
            "intermediate Container so the dataset hierarchy stays navigable; that it was a "
            "study, not a folder, is preserved in dataswampEntityType."
        ),
    ),
    Concept(
        source_concept="dataset",
        target="container",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "Container rather than Table: DataSwamp holds no honest relational column "
            "metadata, so no Table, column, database or schema is invented to hold one."
        ),
    ),
    Concept(
        source_concept="physical_file",
        target="container",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "A leaf Container beneath its dataset. OpenMetadata's native size is in KB, so it "
            "is derived conservatively by flooring the byte count; the exact byte count is "
            "preserved in dataswampPhysicalBytes. A file_format outside OpenMetadata's "
            "fileFormat enum is left unset rather than coerced into a wrong member."
        ),
    ),
    Concept(
        source_concept="data_product",
        target="dataProduct",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "OpenMetadata's DataProduct is the same idea, but its name is globally unique "
            "rather than scoped by domain, so the programme is folded into the identity."
        ),
    ),
    Concept(
        source_concept="data_product_components",
        target="dataProduct.assets",
        fidelity=Fidelity.REASONABLE,
        state=State.DEFERRED,
        reason=(
            "Asset attachment is a bulk-assets call against an already-created data product "
            "and its already-created components, so it is emitted as an ordered plan record "
            "rather than folded into the create payload."
        ),
    ),
    Concept(
        source_concept="team",
        target="team",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "teamType Group is the only member that carries no organisational-hierarchy "
            "claim; DataSwamp teams have no parent/child structure to assert."
        ),
    ),
    Concept(
        source_concept="ownership",
        target="owners",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "A DataSwamp owner is a team, and OpenMetadata owners accept a team reference. "
            "The reference needs a server-assigned UUID, so it is emitted as a declared "
            "reference resolved at load time rather than fabricated inline."
        ),
    ),
    Concept(
        source_concept="stewardship",
        target="custom property dataswampStewardRefs",
        fidelity=Fidelity.LOSSY,
        state=State.MATERIALIZED,
        reason=(
            "OpenMetadata draws no owner/steward role distinction. Flattening stewards into "
            "owners would destroy exactly the distinction this benchmark tests for, so they "
            "are kept separate — but only as a custom property. The native experts field is "
            "not a home for them: it takes user login names, and DataSwamp stewards are "
            "teams. A consumer reading only native OpenMetadata fields will not see "
            "stewardship at all."
        ),
    ),
    Concept(
        source_concept="controlled_vocabulary",
        target="glossary",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "A controlled vocabulary is a flat term list; a Glossary is the same shape but "
            "carries review workflow this project does not model."
        ),
    ),
    Concept(
        source_concept="vocabulary_term",
        target="glossaryTerm",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "Term identity and membership survive exactly; the definition text is generated "
            "rather than authored, because the source vocabulary carries none."
        ),
    ),
    Concept(
        source_concept="facet_tag",
        target="tag",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "Coarse browse facets become Tags under a single dataswamp Classification. The "
            "precise controlled-vocabulary values remain glossary terms, so the two do not "
            "duplicate each other."
        ),
    ),
    Concept(
        source_concept="data_contract",
        target="custom properties dataswampContract*",
        fidelity=Fidelity.LOSSY,
        state=State.MATERIALIZED,
        reason=(
            "OpenMetadata has a DataContract entity, but populating it honestly needs schema "
            "and test-suite semantics DataSwamp does not contain. Contract id, version, "
            "schema reference and SLA are preserved as custom properties instead; the "
            "contract's status as a governed agreement is not represented."
        ),
    ),
    Concept(
        source_concept="dataset_lineage",
        target="lineage edge",
        fidelity=Fidelity.REASONABLE,
        state=State.DEFERRED,
        reason=(
            "Dataset-to-dataset edges map to OpenMetadata lineage. The edge endpoints are "
            "EntityReferences needing server-assigned UUIDs, so edges are emitted as a plan. "
            "OpenMetadata's edge model has no typed-relationship field to hold DataSwamp's "
            "edge_type, so the type is carried in the edge description rather than asserted "
            "as a native relationship kind."
        ),
    ),
    Concept(
        source_concept="file_containment",
        target="container.parent",
        fidelity=Fidelity.EXACT,
        state=State.MATERIALIZED,
    ),
    Concept(
        source_concept="quality_check",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "OpenMetadata's TestDefinition.entityType is an enum of exactly TABLE and COLUMN, "
            "so every TestDefinition would have to assert table scope for an entity that is a "
            "Container. Since no Table is invented, emitting TestDefinition/TestSuite/TestCase "
            "would mean fabricating applicability. The check facts are preserved verbatim in "
            "the dataswampQualityChecks custom property. Upgrade path: if a future domain pack "
            "gives datasets honest column-level schema, they can become Tables and the data- "
            "quality mapping becomes available without changing identity."
        ),
    ),
    Concept(
        source_concept="quality_check_result",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.DEFERRED,
        reason=(
            "A TestCaseResult must name a TestCase, and no TestCase is created for the reason "
            "above. Results are emitted into test-results.jsonl as an explicitly blocked plan "
            "so the facts and the blocker travel together rather than disappearing."
        ),
    ),
    Concept(
        source_concept="subject",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "A study subject is scientific provenance, not catalogue metadata. OpenMetadata "
            "has no entity for it and synthesizing one would put fictional participants into "
            "a data catalogue. Upgrade path: a future OpenLineage or graph export."
        ),
    ),
    Concept(
        source_concept="biospecimen",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason="Scientific provenance with no catalogue analogue; see subject.",
    ),
    Concept(
        source_concept="assay",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason="Scientific provenance with no catalogue analogue; see subject.",
    ),
    Concept(
        source_concept="instrument_run",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "OpenMetadata's Pipeline entity models an orchestrated data pipeline under a "
            "PipelineService. An instrument acquisition is neither, and inventing a "
            "PipelineService for it would put a fictional platform connection into the "
            "catalogue. The producing run id is preserved on each file container. Upgrade "
            "path: an OpenLineage run-event export, where a run is a first-class concept."
        ),
    ),
    Concept(
        source_concept="pipeline_run",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "Closer to OpenMetadata's Pipeline than an instrument run is, but still needs a "
            "fabricated PipelineService with a connection that does not exist. Deferred to the "
            "same OpenLineage upgrade path rather than approximated."
        ),
    ),
    Concept(
        source_concept="non_dataset_lineage",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "Lineage edges whose endpoints are subjects, biospecimens, assays or runs cannot "
            "be emitted, because neither endpoint exists in the export. Counted here so the "
            "gap between DataSwamp's lineage graph and the catalogue's is visible."
        ),
    ),
)

_BY_CONCEPT: dict[str, Concept] = {concept.source_concept: concept for concept in CONCEPTS}

CONCEPT_NAMES: frozenset[str] = frozenset(_BY_CONCEPT)


@dataclass(frozen=True)
class ConceptCounts:
    """The measured half of a coverage row."""

    source: int = 0
    emitted: int = 0
    dropped: int = 0


def build_coverage(counts: Mapping[str, ConceptCounts]) -> dict[str, Any]:
    """Return the coverage report for one export.

    ``counts`` must name **every** concept in :data:`CONCEPTS` and nothing else.
    That is the cross-check: a mapping change that starts emitting a new concept
    without classifying it, or that stops counting one, fails here rather than
    shipping a report that quietly under-describes the export.
    """
    missing = sorted(CONCEPT_NAMES - set(counts))
    unknown = sorted(set(counts) - CONCEPT_NAMES)
    if missing or unknown:
        detail = []
        if missing:
            detail.append(f"unclassified or uncounted concept(s): {', '.join(missing)}")
        if unknown:
            detail.append(f"counted but undeclared concept(s): {', '.join(unknown)}")
        raise ValueError("; ".join(detail))

    rows: list[dict[str, Any]] = []
    for concept in CONCEPTS:
        measured = counts[concept.source_concept]
        row: dict[str, Any] = {
            "source_concept": concept.source_concept,
            "openmetadata_target": concept.target,
            "classification": concept.fidelity.value,
            "operational_state": concept.state.value,
            "source_record_count": measured.source,
            "emitted_record_count": measured.emitted,
            "deliberately_dropped_count": measured.dropped,
        }
        if concept.reason:
            row["reason"] = concept.reason
        rows.append(row)

    by_fidelity: dict[str, int] = {member.value: 0 for member in Fidelity}
    by_state: dict[str, int] = {member.value: 0 for member in State}
    for concept in CONCEPTS:
        by_fidelity[concept.fidelity.value] += 1
        by_state[concept.state.value] += 1

    return {
        "coverage_schema_version": COVERAGE_SCHEMA_VERSION,
        "classifications": {
            member.value: doc
            for member, doc in (
                (Fidelity.EXACT, "OpenMetadata holds the same concept with the same meaning."),
                (
                    Fidelity.REASONABLE,
                    "No identical concept exists; a defensible one is used and the source "
                    "concept stays recoverable.",
                ),
                (
                    Fidelity.LOSSY,
                    "A distinction DataSwamp draws does not survive into native "
                    "OpenMetadata fields.",
                ),
                (Fidelity.UNSUPPORTED, "Deliberately not mapped."),
            )
        },
        "operational_states": {
            member.value: doc
            for member, doc in (
                (State.MATERIALIZED, "Emitted as entity payloads in this export."),
                (State.DEFERRED, "Emitted as a plan for a later live write, not as an entity."),
                (State.NOT_MAPPED, "Emitted nowhere; recorded so the omission is counted."),
            )
        },
        "concepts": rows,
        "totals": {
            "concepts": len(CONCEPTS),
            "by_classification": by_fidelity,
            "by_operational_state": by_state,
            "source_records": sum(counts[name].source for name in CONCEPT_NAMES),
            "emitted_records": sum(counts[name].emitted for name in CONCEPT_NAMES),
            "deliberately_dropped_records": sum(counts[name].dropped for name in CONCEPT_NAMES),
        },
    }


__all__ = [
    "COVERAGE_SCHEMA_VERSION",
    "Fidelity",
    "State",
    "Concept",
    "ConceptCounts",
    "CONCEPTS",
    "CONCEPT_NAMES",
    "build_coverage",
]
