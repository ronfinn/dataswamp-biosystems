"""The mapping-coverage contract: what was mapped, how well, and what was not.

``mapping-coverage.json`` ships in **every** DataHub export. It is a first-class
part of the export rather than documentation that happens to be machine
readable, because the interesting property of a catalogue adapter is not what it
emits — it is what it quietly loses on the way. An adapter that drops the lineage
edge type and says nothing looks identical, from its output, to one that had no
edge type to drop.

Two orthogonal axes are reported, and neither substitutes for the other.

**Semantic classification** answers *how faithful is this mapping?*

``exact``
    DataHub preserves the DataSwamp semantic with no meaningful compromise.
``reasonable``
    Represented appropriately, but transformed into a catalogue-native model
    that is not an exact expression of DataSwamp's concept. The source concept
    stays recoverable — typically through a ``dataswamp_*`` custom property.
``lossy``
    Material information is not preserved natively, or is reduced to custom
    metadata or prose. A consumer reading only native DataHub fields would draw
    a weaker conclusion than the source supports.
``unsupported``
    No honest DataHub target representation exists **in the current adapter**.
    That is a statement about this adapter, not about DataHub the product.

**Operational state** answers *where does this show up?*

``materialized_in_entity_export``
    Emitted as Metadata Change Proposals in this export.
``deferred_live_write``
    Emitted as a plan for a later live write, not as an entity here.
``deliberately_not_mapped``
    Emitted nowhere. The record exists so the omission is visible and counted.

The two are independent, and fidelity is never a function of operational timing:
materialized-inline versus written-later is an operational distinction. DataHub
uses **no** ``deferred_live_write`` row, and that zero is itself the finding —
DataHub's file-source MCP model has no server-assigned-UUID problem, so lineage
and data-product assets are materialized inline where the OpenMetadata adapter
must defer. The member is declared anyway so the two state vocabularies stay
identical and a later cross-catalogue reader needs no name-mapping table.

Counts use each family's **natural semantic grain** — entity occurrences for
entity families, reference occurrences for ownership, stewardship and
data-product components, edge occurrences for lineage, one containment
relationship per physical file — and
``source == emitted + dropped`` holds for every row.
:func:`build_coverage` refuses a report that is missing a concept, claims one it
never declared, or fails to reconcile, so a mapping change cannot quietly
under-describe the export.

The report carries **counts only, never an entity identifier**: per-entity
coverage would let a reader infer which entities were mutated by comparing two
exports, so aggregation is a privilege property here, not merely a design
preference.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Independent of the OpenMetadata adapter's identically-numbered constant: the
# two contracts share no rows, no vocabulary registry and no evidence, and the
# equal numbers are a coincidence.
COVERAGE_SCHEMA_VERSION = 1


class Fidelity(StrEnum):
    """How faithfully DataHub holds a DataSwamp concept."""

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
# Order is the reading order of the report, deliberately the emission order of
# the export rather than alphabetical: a reader following the MCPs sees the same
# sequence here.
CONCEPTS: tuple[Concept, ...] = (
    Concept(
        source_concept="company",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "The adapter materializes no company entity. The 'dataswamp' dataPlatform token "
            "namespaces every emitted URN, but namespacing an identifier is not representing "
            "the organisation that owns the estate, so it is not counted as a company. This "
            "describes the current adapter, not a DataHub limitation."
        ),
    ),
    Concept(
        source_concept="programme",
        target="domain + domainProperties",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "A research programme is a governance grouping, which is what a DataHub Domain is. "
            "The programme is derived from the assets that reference it rather than read from a "
            "programme shard, so only its id and a generated description survive; there is no "
            "programme entity in the source the adapter reads."
        ),
    ),
    Concept(
        source_concept="study",
        target='container + containerProperties + subTypes:["Study"]',
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "DataHub has no study entity. A study becomes a Container carrying the Study "
            "subtype, so the estate stays navigable, and the source id travels in "
            "dataswamp_id because the container URN is a non-reversible GUID."
        ),
    ),
    Concept(
        source_concept="dataset",
        target='dataset + datasetProperties + subTypes:["Dataset"]',
        fidelity=Fidelity.EXACT,
        state=State.MATERIALIZED,
    ),
    Concept(
        source_concept="physical_file",
        target='dataset + subTypes:["File"]',
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "DataHub has no file entity, so a file is a File-subtyped dataset. Path, format, "
            "checksum, producing run id and the exact physical_bytes survive as custom "
            "properties, so nothing about the file is lost — but a consumer browsing datasets "
            "sees files alongside datasets and must read subTypes to tell them apart."
        ),
    ),
    Concept(
        source_concept="data_product",
        target="dataProduct + dataProductProperties",
        fidelity=Fidelity.EXACT,
        state=State.MATERIALIZED,
    ),
    Concept(
        source_concept="data_product_components",
        target="dataProductProperties.assets",
        fidelity=Fidelity.LOSSY,
        state=State.MATERIALIZED,
        reason=(
            "Component references are filtered to ids that resolve to an emitted dataset, and a "
            "reference that does not resolve is discarded with nothing recorded in the export. "
            "The input carries no guarantee that it would: component_dataset_ids is an "
            "unconstrained list of slugs, the referential invariant lives in the truth-layer "
            "validator, and observed mode deliberately permits broken referential integrity. "
            "The deliberately_dropped_count is the only place such a removal becomes visible."
        ),
    ),
    Concept(
        source_concept="team",
        target="corpGroup + corpGroupInfo",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "Teams are derived from the owner_ref and steward_refs on assets rather than read "
            "from a team shard, so a team that owns nothing is never emitted, and admins, "
            "members and groups are emitted empty because no corpUser is invented."
        ),
    ),
    Concept(
        source_concept="ownership",
        target="ownership aspect (DATAOWNER)",
        fidelity=Fidelity.EXACT,
        state=State.MATERIALIZED,
    ),
    Concept(
        source_concept="stewardship",
        target="ownership aspect (DATA_STEWARD)",
        fidelity=Fidelity.EXACT,
        state=State.MATERIALIZED,
    ),
    Concept(
        source_concept="controlled_vocabulary",
        target="glossaryNode + glossaryNodeInfo",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "A controlled vocabulary is a flat term list; a glossary node is the same shape but "
            "sits in a glossary hierarchy this project does not model. The node is derived from "
            "the terms assets actually reference, so an unreferenced vocabulary is not emitted."
        ),
    ),
    Concept(
        source_concept="vocabulary_term",
        target="glossaryTerm + glossaryTermInfo",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "Term identity and vocabulary membership survive exactly; the definition text is "
            "generated rather than authored, because the source vocabulary carries none, and "
            "only terms referenced by an asset become entities."
        ),
    ),
    Concept(
        source_concept="facet_tag",
        target="tag + tagProperties, globalTags",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "DataHub tags are flat and global with no classification namespace to group them "
            "under, so the field name and its value are concatenated into one opaque token "
            "(modality-group-imaging). The precise controlled-vocabulary values stay glossary "
            "terms, so tags and terms do not duplicate each other."
        ),
    ),
    Concept(
        source_concept="data_contract",
        target="dataswamp_contract_* custom properties",
        fidelity=Fidelity.LOSSY,
        state=State.MATERIALIZED,
        reason=(
            "Contract id, version, schema_ref and SLA are carried as custom properties on the "
            "asset they govern. DataHub's native data-contract entity is not emitted, so the "
            "contract's status as a governed agreement — and its existence as an entity that "
            "can be owned, versioned or asserted against — is not represented natively."
        ),
    ),
    Concept(
        source_concept="dataset_lineage",
        target="upstreamLineage (type TRANSFORMED)",
        fidelity=Fidelity.LOSSY,
        state=State.MATERIALIZED,
        reason=(
            "Only the endpoints are read; edge_type is never read and every surviving edge is "
            "emitted as TRANSFORMED. DataSwamp's seven edge types — collected_from, "
            "assayed_from, profiled_by, processed_by, produced, derived_from, aggregated_into — "
            "are not recoverable from the export. Self-edges and duplicate edges between the "
            "same pair are also discarded."
        ),
    ),
    Concept(
        source_concept="file_containment",
        target="upstreamLineage (COPY) + dataswamp_dataset_id",
        fidelity=Fidelity.LOSSY,
        state=State.MATERIALIZED,
        reason=(
            "DataSwamp declares file inside dataset inside study. The file's container aspect "
            "points at the study, skipping the dataset level, and the file-to-dataset "
            "relationship is re-expressed as a COPY lineage edge plus a dataswamp_dataset_id "
            "property. Containment is represented as lineage and the two-level hierarchy is "
            "flattened; every relationship is carried, so the loss is of meaning, not of count."
        ),
    ),
    Concept(
        source_concept="quality_check",
        target="assertion + assertionInfo",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "DataHub's Assertion preserves the check, the dataset it applies to, its status and "
            "its evidence, but operator and aggregation are the _NATIVE_ escape hatch and the "
            "check type survives only as an opaque nativeType string, because DataSwamp's "
            "checks are not expressed as comparisons. The emitted datasetAssertion.scope is the "
            "fixed constant DATASET_COLUMN even though the check names no column; that is "
            "recorded here as emitted behaviour, not endorsed. Only checks whose asset_id "
            "resolves to an emitted dataset become assertions."
        ),
    ),
    Concept(
        source_concept="quality_check_result",
        target="assertionRunEvent",
        fidelity=Fidelity.REASONABLE,
        state=State.MATERIALIZED,
        reason=(
            "The result, its evidence and the source-derived evaluation time survive. It is one "
            "run event and never a series, and the status collapses to SUCCESS when it is "
            "'pass' and FAILURE for every other value, so a warning and a failure become "
            "indistinguishable natively; the source status stays readable on the assertion's "
            "dataswamp_status property."
        ),
    ),
    Concept(
        source_concept="subject",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "A study subject is scientific provenance, not catalogue metadata. DataHub has no "
            "entity for it and synthesizing one would put fictional participants into a data "
            "catalogue. The records exist in the source and are counted here so the omission is "
            "visible. Upgrade path: a future OpenLineage or graph export."
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
            "DataHub's dataJob models a job in an orchestrated flow under a dataFlow. An "
            "instrument acquisition is neither, and forcing one into a dataJob would assert it "
            "is a scheduled job. The producing run id survives on each file as "
            "dataswamp_producing_run_id, so a run id stays traceable while the run is not an "
            "entity."
        ),
    ),
    Concept(
        source_concept="pipeline_run",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "Closer to a dataJob than an instrument run is, but it is a single execution rather "
            "than the job definition a dataJob describes, and no dataFlow exists to hold it. "
            "The producing run id survives on each file; the run is not an entity."
        ),
    ),
    Concept(
        source_concept="non_dataset_lineage",
        target=None,
        fidelity=Fidelity.UNSUPPORTED,
        state=State.NOT_MAPPED,
        reason=(
            "Lineage edges with at least one endpoint outside the dataset set — subjects, "
            "biospecimens, assays, runs and files — are not emitted, because the endpoint does "
            "not exist in the export. A file-to-dataset edge belongs here even though an "
            "equivalent COPY relationship is separately synthesized from the files shard: that "
            "relationship is built from the file record, not from this edge, so the edge itself "
            "is genuinely unmapped and is not hidden behind the synthesized one."
        ),
    ),
)

_BY_CONCEPT: dict[str, Concept] = {concept.source_concept: concept for concept in CONCEPTS}

CONCEPT_NAMES: frozenset[str] = frozenset(_BY_CONCEPT)


@dataclass(frozen=True)
class ConceptCounts:
    """The measured half of a coverage row, at the family's natural grain."""

    source: int = 0
    emitted: int = 0
    dropped: int = 0


def build_coverage(counts: Mapping[str, ConceptCounts]) -> dict[str, Any]:
    """Return the coverage report for one export.

    ``counts`` must name **every** concept in :data:`CONCEPTS` and nothing else,
    and every row must reconcile. That is the cross-check: a mapping change that
    starts emitting a new concept without classifying it, that stops counting
    one, or that loses records between the source and the export without saying
    so, fails here rather than shipping a report that quietly under-describes
    the export. Nothing is silently repaired.
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

    negative = sorted(
        name
        for name, measured in counts.items()
        if min(measured.source, measured.emitted, measured.dropped) < 0
    )
    if negative:
        raise ValueError(f"negative record count(s): {', '.join(negative)}")

    unreconciled = sorted(
        name
        for name, measured in counts.items()
        if measured.source != measured.emitted + measured.dropped
    )
    if unreconciled:
        raise ValueError("source != emitted + dropped for concept(s): " + ", ".join(unreconciled))

    emitting_unsupported = sorted(
        name
        for name, measured in counts.items()
        if _BY_CONCEPT[name].fidelity is Fidelity.UNSUPPORTED and measured.emitted > 0
    )
    if emitting_unsupported:
        raise ValueError(
            "unsupported concept(s) reporting emitted records: " + ", ".join(emitting_unsupported)
        )

    rows: list[dict[str, Any]] = []
    for concept in CONCEPTS:
        measured = counts[concept.source_concept]
        row: dict[str, Any] = {
            "source_concept": concept.source_concept,
            "datahub_target": concept.target,
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
                (Fidelity.EXACT, "DataHub preserves the semantic with no meaningful compromise."),
                (
                    Fidelity.REASONABLE,
                    "Transformed into a catalogue-native model that is not an exact expression "
                    "of the source concept, which stays recoverable.",
                ),
                (
                    Fidelity.LOSSY,
                    "Material information does not survive into native DataHub fields.",
                ),
                (
                    Fidelity.UNSUPPORTED,
                    "No honest target representation exists in the current adapter.",
                ),
            )
        },
        "operational_states": {
            member.value: doc
            for member, doc in (
                (State.MATERIALIZED, "Emitted as proposals in this export."),
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
