"""The DataHub mapping-coverage contract.

Coverage *describes* the adapter; it never improves, normalizes or repairs it.
These tests therefore assert two different kinds of thing, and the distinction
matters: the contract's structure (24 families, mandatory reasons, refusals) is
a claim about the declaration, while the counts are claims about what the
existing mapping does with a given source graph.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.adapters.datahub import (
    CONCEPT_NAMES,
    CONCEPTS,
    COVERAGE_SCHEMA_VERSION,
    ConceptCounts,
    ExportMode,
    Fidelity,
    SourceGraph,
    State,
    build_coverage,
    build_coverage_counts,
    build_mapping_coverage,
    build_mcps,
)

from .conftest import MINI_SHARDS

EXPECTED_FAMILIES = {
    "company",
    "programme",
    "study",
    "dataset",
    "physical_file",
    "data_product",
    "data_product_components",
    "team",
    "ownership",
    "stewardship",
    "controlled_vocabulary",
    "vocabulary_term",
    "facet_tag",
    "data_contract",
    "dataset_lineage",
    "file_containment",
    "quality_check",
    "quality_check_result",
    "subject",
    "biospecimen",
    "assay",
    "instrument_run",
    "pipeline_run",
    "non_dataset_lineage",
}


def _rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["source_concept"]: row for row in report["concepts"]}


def _source(**extra: list[dict[str, object]]) -> SourceGraph:
    shards: dict[str, list[dict[str, object]]] = {**MINI_SHARDS, **extra}
    return SourceGraph(mode=ExportMode.OBSERVED, shards=shards)


def _counts_for(**extra: list[dict[str, object]]) -> dict[str, ConceptCounts]:
    return build_coverage_counts(_source(**extra))


# --------------------------------------------------------- contract structure


def test_the_contract_declares_exactly_the_twenty_four_families() -> None:
    assert set(CONCEPT_NAMES) == EXPECTED_FAMILIES
    assert len(CONCEPTS) == 24


def test_no_family_is_declared_twice() -> None:
    names = [concept.source_concept for concept in CONCEPTS]
    assert len(names) == len(set(names))


def test_the_classification_totals_match_the_approved_contract() -> None:
    totals = build_mapping_coverage(_source())["totals"]["by_classification"]
    assert totals == {"exact": 4, "reasonable": 9, "lossy": 4, "unsupported": 7}


def test_every_non_exact_row_carries_a_reason() -> None:
    for concept in CONCEPTS:
        if concept.fidelity is not Fidelity.EXACT:
            assert concept.reason.strip(), concept.source_concept


def test_an_exact_row_needs_no_invented_reasoning() -> None:
    exact = [c for c in CONCEPTS if c.fidelity is Fidelity.EXACT]
    assert {c.source_concept for c in exact} == {
        "dataset",
        "data_product",
        "ownership",
        "stewardship",
    }
    for concept in exact:
        assert concept.reason == ""
    report = _rows(build_mapping_coverage(_source()))
    assert "reason" not in report["dataset"]


def test_every_unsupported_row_has_a_null_target_and_no_emitted_records() -> None:
    report = _rows(build_mapping_coverage(_source()))
    for concept in CONCEPTS:
        if concept.fidelity is Fidelity.UNSUPPORTED:
            assert concept.target is None, concept.source_concept
            row = report[concept.source_concept]
            assert row["datahub_target"] is None
            assert row["emitted_record_count"] == 0


def test_rows_are_in_declaration_order_not_alphabetical() -> None:
    report = build_mapping_coverage(_source())
    order = [row["source_concept"] for row in report["concepts"]]
    assert order == [concept.source_concept for concept in CONCEPTS]
    assert order != sorted(order)


def test_the_report_is_schema_versioned() -> None:
    assert COVERAGE_SCHEMA_VERSION == 1
    assert build_mapping_coverage(_source())["coverage_schema_version"] == 1


def test_datahub_declares_no_deferred_write_and_that_is_the_finding() -> None:
    """DataHub materializes inline everywhere OpenMetadata must defer."""
    states = build_mapping_coverage(_source())["totals"]["by_operational_state"]
    assert states["deferred_live_write"] == 0
    assert State.DEFERRED.value in states


# ------------------------------------------------------------------- refusals


def _valid_counts() -> dict[str, ConceptCounts]:
    return {name: ConceptCounts() for name in CONCEPT_NAMES}


def test_a_missing_family_is_refused_by_name() -> None:
    counts = _valid_counts()
    del counts["stewardship"]
    with pytest.raises(ValueError, match="stewardship"):
        build_coverage(counts)


def test_an_unknown_family_is_refused_by_name() -> None:
    counts = _valid_counts()
    counts["invented_family"] = ConceptCounts()
    with pytest.raises(ValueError, match="invented_family"):
        build_coverage(counts)


def test_an_unreconciled_row_is_refused_by_name() -> None:
    counts = _valid_counts()
    counts["dataset"] = ConceptCounts(source=5, emitted=3, dropped=1)
    with pytest.raises(ValueError, match="source != emitted \\+ dropped.*dataset"):
        build_coverage(counts)


def test_a_negative_count_is_refused_by_name() -> None:
    counts = _valid_counts()
    counts["dataset"] = ConceptCounts(source=-1, emitted=-1, dropped=0)
    with pytest.raises(ValueError, match="negative record count.*dataset"):
        build_coverage(counts)


def test_an_unsupported_family_reporting_emitted_records_is_refused() -> None:
    counts = _valid_counts()
    counts["subject"] = ConceptCounts(source=3, emitted=3, dropped=0)
    with pytest.raises(ValueError, match="unsupported concept.*subject"):
        build_coverage(counts)


def test_a_non_exact_row_without_a_reason_cannot_be_declared() -> None:
    from dataswamp_biosystems.adapters.datahub import Concept

    with pytest.raises(ValueError, match="needs a reason"):
        Concept(
            source_concept="made_up",
            target="thing",
            fidelity=Fidelity.LOSSY,
            state=State.MATERIALIZED,
        )


def test_an_unsupported_row_with_a_target_cannot_be_declared() -> None:
    from dataswamp_biosystems.adapters.datahub import Concept

    with pytest.raises(ValueError, match="no target"):
        Concept(
            source_concept="made_up",
            target="thing",
            fidelity=Fidelity.UNSUPPORTED,
            state=State.NOT_MAPPED,
            reason="because",
        )


# --------------------------------------------------------------------- counts


def test_every_family_reconciles_on_the_mini_source() -> None:
    for name, measured in _counts_for().items():
        assert measured.source == measured.emitted + measured.dropped, name


def test_every_family_reconciles_on_the_real_benchmark(full_bundle_dir: Path) -> None:
    from dataswamp_biosystems.adapters.datahub import build_source
    from dataswamp_biosystems.bundle import BundleReader

    for mode in (ExportMode.OBSERVED, ExportMode.TRUTH):
        with BundleReader.open(full_bundle_dir) as reader:
            counts = build_coverage_counts(build_source(reader, mode))
        for name, measured in counts.items():
            assert measured.source == measured.emitted + measured.dropped, (mode, name)


def test_company_is_a_declared_singleton_with_no_shard() -> None:
    counts = _counts_for()
    assert counts["company"] == ConceptCounts(source=1, emitted=0, dropped=1)
    assert "company" not in MINI_SHARDS


def test_component_references_are_counted_individually_not_per_product() -> None:
    """One product with five references contributes five, not one."""
    product = dict(MINI_SHARDS["data_products"][0])
    product["component_dataset_ids"] = [
        "ds-alpha",
        "ds-bravo",
        "ds-absent-one",
        "ds-absent-two",
        "ds-absent-three",
    ]
    counts = _counts_for(data_products=[product])
    assert counts["data_product"].source == 1
    assert counts["data_product_components"] == ConceptCounts(source=5, emitted=2, dropped=3)


def test_a_dangling_component_reference_is_counted_as_dropped() -> None:
    product = dict(MINI_SHARDS["data_products"][0])
    product["component_dataset_ids"] = ["ds-alpha", "ds-nowhere"]
    counts = _counts_for(data_products=[product])
    assert counts["data_product_components"].dropped == 1


def test_steward_references_are_counted_individually_not_per_asset() -> None:
    dataset = dict(MINI_SHARDS["datasets"][0])
    dataset["steward_refs"] = ["team-a", "team-b", "team-c"]
    counts = build_coverage_counts(
        SourceGraph(
            mode=ExportMode.OBSERVED,
            shards={"datasets": [dataset], "data_products": [], "files": []},
        )
    )
    assert counts["stewardship"] == ConceptCounts(source=3, emitted=3, dropped=0)
    assert counts["ownership"] == ConceptCounts(source=1, emitted=1, dropped=0)


def test_a_deduplicated_steward_reference_is_counted_as_dropped() -> None:
    """The mapper collapses repeats through a set; the collapse is measured, not hidden."""
    dataset = dict(MINI_SHARDS["datasets"][0])
    dataset["steward_refs"] = ["team-a", "team-a", "team-b"]
    source = SourceGraph(
        mode=ExportMode.OBSERVED,
        shards={"datasets": [dataset], "data_products": [], "files": []},
    )
    counts = build_coverage_counts(source)
    assert counts["stewardship"] == ConceptCounts(source=3, emitted=2, dropped=1)

    ownership = [
        mcp["aspect"]["json"] for mcp in build_mcps(source) if mcp["aspectName"] == "ownership"
    ]
    stewards = [o for o in ownership[0]["owners"] if o["type"] == "DATA_STEWARD"]
    assert len(stewards) == 2, "the count must describe the mapping, not contradict it"


def test_file_containment_counts_relationships_not_parent_datasets() -> None:
    """Two files in one dataset are two containment relationships, not one."""
    extra = dict(MINI_SHARDS["files"][0])
    extra["id"] = "file-ds-alpha-2"
    counts = _counts_for(files=[*MINI_SHARDS["files"], extra])
    assert counts["file_containment"] == ConceptCounts(source=3, emitted=3, dropped=0)
    assert counts["dataset"].source == 2


def test_the_lineage_partition_is_total() -> None:
    extra = [
        # dataset -> dataset, emitted
        {"id": "e1", "upstream_id": "ds-alpha", "downstream_id": "ds-bravo"},
        # a self-edge: dataset -> dataset, dropped
        {"id": "e2", "upstream_id": "ds-alpha", "downstream_id": "ds-alpha"},
        # file -> dataset: not dataset lineage, even though a COPY edge exists
        {"id": "e3", "upstream_id": "file-ds-alpha-1", "downstream_id": "ds-alpha"},
        # scientific provenance: neither endpoint is a dataset
        {"id": "e4", "upstream_id": "subject-1", "downstream_id": "biospecimen-1"},
    ]
    counts = _counts_for(lineage=extra)
    assert counts["dataset_lineage"] == ConceptCounts(source=2, emitted=1, dropped=1)
    assert counts["non_dataset_lineage"] == ConceptCounts(source=2, emitted=0, dropped=2)
    total = counts["dataset_lineage"].source + counts["non_dataset_lineage"].source
    assert total == len(extra)


def test_a_file_to_dataset_edge_is_non_dataset_lineage(full_bundle_dir: Path) -> None:
    """The synthesized COPY relationship comes from the files shard, not this edge."""
    from dataswamp_biosystems.adapters.datahub import build_source
    from dataswamp_biosystems.bundle import BundleReader

    with BundleReader.open(full_bundle_dir) as reader:
        source = build_source(reader, ExportMode.OBSERVED)
    counts = build_coverage_counts(source)
    dataset_ids = {str(row.get("id")) for row in source.records("datasets")}
    file_ids = {str(row.get("id")) for row in source.records("files")}
    file_edges = [
        edge
        for edge in source.records("lineage")
        if str(edge.get("upstream_id")) in file_ids
        and str(edge.get("downstream_id")) in dataset_ids
    ]
    assert file_edges, (
        "the canonical estate must carry file->dataset edges for this to mean anything"
    )
    assert counts["non_dataset_lineage"].source >= len(file_edges)
    assert counts["non_dataset_lineage"].emitted == 0


def test_the_unsupported_scientific_families_report_real_source_records(
    full_bundle_dir: Path,
) -> None:
    """Reporting 0/0/0 would claim nothing existed. Records plainly exist."""
    from dataswamp_biosystems.adapters.datahub import build_source
    from dataswamp_biosystems.bundle import BundleReader

    for mode in (ExportMode.OBSERVED, ExportMode.TRUTH):
        with BundleReader.open(full_bundle_dir) as reader:
            counts = build_coverage_counts(build_source(reader, mode))
        for name in ("subject", "biospecimen", "assay", "instrument_run", "pipeline_run"):
            measured = counts[name]
            assert measured.source > 0, (mode, name)
            assert measured.emitted == 0
            assert measured.dropped == measured.source


def test_instrument_and_pipeline_runs_are_counted_separately(full_bundle_dir: Path) -> None:
    from dataswamp_biosystems.adapters.datahub import build_source
    from dataswamp_biosystems.bundle import BundleReader

    with BundleReader.open(full_bundle_dir) as reader:
        source = build_source(reader, ExportMode.TRUTH)
    counts = build_coverage_counts(source)
    kinds = {str(row.get("run_kind")) for row in source.records("instrument_runs")}
    assert kinds == {"instrument"}
    assert {str(row.get("run_kind")) for row in source.records("pipeline_runs")} == {"pipeline"}
    assert counts["instrument_run"].source == len(source.records("instrument_runs"))
    assert counts["pipeline_run"].source == len(source.records("pipeline_runs"))


def test_a_quality_check_against_a_non_dataset_asset_is_counted_as_dropped() -> None:
    check = {
        "id": "qc-dp-1",
        "asset_id": "dp-omics",
        "check_type": "completeness",
        "status": "pass",
        "evidence": "n/a",
        "evaluated_at": "2026-03-01T00:00:00Z",
    }
    counts = _counts_for(quality_checks=[*MINI_SHARDS["quality_checks"], check])
    assert counts["quality_check"] == ConceptCounts(source=2, emitted=1, dropped=1)
    assert counts["quality_check_result"] == counts["quality_check"]


# ---------------------------------------------------- the load-bearing rows


@pytest.mark.parametrize(
    ("family", "fidelity"),
    [
        ("stewardship", Fidelity.EXACT),
        ("ownership", Fidelity.EXACT),
        ("dataset", Fidelity.EXACT),
        ("data_product", Fidelity.EXACT),
        ("quality_check", Fidelity.REASONABLE),
        ("quality_check_result", Fidelity.REASONABLE),
        ("dataset_lineage", Fidelity.LOSSY),
        ("data_contract", Fidelity.LOSSY),
        ("data_product_components", Fidelity.LOSSY),
        ("file_containment", Fidelity.LOSSY),
        ("company", Fidelity.UNSUPPORTED),
        ("subject", Fidelity.UNSUPPORTED),
        ("biospecimen", Fidelity.UNSUPPORTED),
        ("assay", Fidelity.UNSUPPORTED),
        ("instrument_run", Fidelity.UNSUPPORTED),
        ("pipeline_run", Fidelity.UNSUPPORTED),
        ("non_dataset_lineage", Fidelity.UNSUPPORTED),
    ],
)
def test_the_load_bearing_classifications(family: str, fidelity: Fidelity) -> None:
    by_name = {concept.source_concept: concept for concept in CONCEPTS}
    assert by_name[family].fidelity is fidelity


def test_stewardship_is_exact_because_datahub_has_a_native_steward_type() -> None:
    source = _source()
    ownership = [
        mcp["aspect"]["json"] for mcp in build_mcps(source) if mcp["aspectName"] == "ownership"
    ]
    types = {owner["type"] for aspect in ownership for owner in aspect["owners"]}
    assert {"DATAOWNER", "DATA_STEWARD"} <= types


def test_dataset_lineage_is_lossy_because_the_edge_type_is_discarded() -> None:
    source = _source()
    upstreams = [
        mcp["aspect"]["json"]
        for mcp in build_mcps(source)
        if mcp["aspectName"] == "upstreamLineage"
    ]
    emitted_types = {up["type"] for aspect in upstreams for up in aspect["upstreams"]}
    assert emitted_types <= {"COPY", "TRANSFORMED"}
    assert MINI_SHARDS["lineage"][0]["edge_type"] == "derived_from"
    assert "derived_from" not in json.dumps(upstreams)
    by_name = {concept.source_concept: concept for concept in CONCEPTS}
    assert "edge_type" in by_name["dataset_lineage"].reason


def test_the_quality_check_reason_records_the_fixed_scope_without_endorsing_it() -> None:
    """The hardcoded DATASET_COLUMN scope is described, not repaired or excused."""
    by_name = {concept.source_concept: concept for concept in CONCEPTS}
    reason = by_name["quality_check"].reason
    assert "DATASET_COLUMN" in reason
    assert by_name["quality_check"].fidelity is Fidelity.REASONABLE
    emitted = [
        mcp["aspect"]["json"]
        for mcp in build_mcps(_source())
        if mcp["aspectName"] == "assertionInfo"
    ]
    assert emitted[0]["datasetAssertion"]["scope"] == "DATASET_COLUMN"


def test_the_non_dataset_lineage_reason_names_the_synthesized_copy_relationship() -> None:
    by_name = {concept.source_concept: concept for concept in CONCEPTS}
    assert "COPY" in by_name["non_dataset_lineage"].reason


# --------------------------------------------------------------- determinism


def test_the_report_is_a_pure_function_of_the_source() -> None:
    assert build_mapping_coverage(_source()) == build_mapping_coverage(_source())


def test_the_report_carries_no_entity_identifier() -> None:
    """Per-entity coverage would leak which entities were mutated."""
    rendered = json.dumps(build_mapping_coverage(_source()))
    for identifier in ("ds-alpha", "ds-bravo", "dp-omics", "file-ds-alpha-1", "qc-ds-alpha-1"):
        assert identifier not in rendered


def test_measurement_adds_no_proposal_to_the_mapping() -> None:
    """The widened shard dictionary is inert: build_mcps ignores it by name."""
    without = build_mcps(_source())
    with_extra = build_mcps(
        _source(
            subjects=[{"id": "subject-1"}],
            biospecimens=[{"id": "biospecimen-1"}],
            assays=[{"id": "assay-1"}],
            instrument_runs=[{"id": "run-i-1", "run_kind": "instrument"}],
            pipeline_runs=[{"id": "run-p-1", "run_kind": "pipeline"}],
        )
    )
    assert with_extra == without
