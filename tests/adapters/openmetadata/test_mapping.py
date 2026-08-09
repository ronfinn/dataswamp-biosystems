"""What the mapping emits, what it refuses to invent, and what it admits losing.

The tests that matter most here are the negative ones. It is easy to check that a
container was emitted; the interesting property of this adapter is that no Table
was, no Pipeline was, and no DataContract was — because each of those would have
been the convenient thing to do and each would have put a false fact in a
catalogue.
"""

from __future__ import annotations

import json

from dataswamp_biosystems.adapters.openmetadata import (
    CONCEPT_NAMES,
    FILE_FORMATS,
    PHASES,
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
    ExportPlan,
    Fidelity,
    SourceGraph,
    State,
    build_plan,
    property_specs,
)
from dataswamp_biosystems.adapters.openmetadata import fqn as om_fqn


def _by_phase(plan: ExportPlan, phase: str) -> list:
    return [record for record in plan.records if record.phase == phase]


def _record(plan: ExportPlan, fqn: str):
    return next(record for record in plan.records if record.fqn == fqn and record.create)


# -- what is NOT invented -----------------------------------------------------

FORBIDDEN_ENTITY_TYPES = frozenset(
    {
        "table",
        "column",
        "database",
        "databaseSchema",
        "databaseService",
        "pipeline",
        "pipelineService",
        "dataContract",
        "testDefinition",
        "testSuite",
        "testCase",
        "mlmodel",
        "topic",
        "dashboard",
    }
)


def test_no_table_column_or_database_entity_is_invented(mini_truth: ExportPlan) -> None:
    """DataSwamp has no honest relational schema, so it gets no relational entity."""
    emitted = {record.entity_type for record in mini_truth.records}
    assert not (emitted & FORBIDDEN_ENTITY_TYPES)


def test_no_field_level_schema_is_invented(mini_truth: ExportPlan) -> None:
    """``dataModel`` is where a fabricated column list would hide."""
    for record in mini_truth.records:
        if record.create is not None:
            assert "dataModel" not in record.create


def test_no_pipeline_or_pipeline_service_is_synthesized(mini_truth: ExportPlan) -> None:
    serialized = json.dumps([record.as_json() for record in mini_truth.records])
    assert "pipelineService" not in serialized
    assert '"entityType": "pipeline"' not in serialized


def test_no_storage_connection_is_fabricated(mini_truth: ExportPlan) -> None:
    """A CustomStorage service with no connection is honest; an invented one is not."""
    service = _record(mini_truth, om_fqn.service_fqn())
    assert service.create["serviceType"] == "CustomStorage"
    assert "connection" not in service.create


def test_no_test_entities_are_emitted_for_quality_checks(mini_truth: ExportPlan) -> None:
    """OpenMetadata's TestDefinition.entityType admits only TABLE and COLUMN."""
    assert not [
        record
        for record in mini_truth.records
        if "test" in record.entity_type.lower() and record.create is not None
    ]
    assert "testDefinition" not in PHASES
    assert "test-suite" not in PHASES


# -- containers, sizes and formats --------------------------------------------


def test_the_container_hierarchy_is_service_study_dataset_file(mini_observed: ExportPlan) -> None:
    assert [record.fqn for record in _by_phase(mini_observed, "study-container")] == [
        "dataswamp-biosystems.study-nsclc-01"
    ]
    assert [record.fqn for record in _by_phase(mini_observed, "dataset-container")] == [
        "dataswamp-biosystems.study-nsclc-01.ds-alpha",
        "dataswamp-biosystems.study-nsclc-01.ds-bravo",
    ]
    assert [record.fqn for record in _by_phase(mini_observed, "file-container")] == [
        "dataswamp-biosystems.study-nsclc-01.ds-alpha.file-ds-alpha-1",
        "dataswamp-biosystems.study-nsclc-01.ds-bravo.file-ds-bravo-1",
    ]


def test_the_exact_byte_count_survives_the_native_kb_size(mini_observed: ExportPlan) -> None:
    """1500 bytes is 1 KB floored, and 1500 must still be recoverable exactly."""
    record = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-bravo.file-ds-bravo-1")
    assert record.create["size"] == 1.0
    assert record.create["extension"]["dataswampPhysicalBytes"] == "1500"


def test_the_kb_size_is_floored_not_rounded(mini_observed: ExportPlan) -> None:
    """Flooring is conservative: a container never claims to hold more than it does."""
    record = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-alpha.file-ds-alpha-1")
    assert record.create["size"] == 2.0  # 2048 bytes
    assert record.create["extension"]["dataswampPhysicalBytes"] == "2048"


def test_a_supported_file_format_is_declared_natively(mini_observed: ExportPlan) -> None:
    record = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-alpha.file-ds-alpha-1")
    assert record.create["fileFormats"] == ["parquet"]
    assert "parquet" in FILE_FORMATS


def test_an_unsupported_file_format_is_not_coerced(mini_observed: ExportPlan) -> None:
    """h5ad is not json, and saying it is would put a false fact in a catalogue."""
    record = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-bravo.file-ds-bravo-1")
    assert "h5ad" not in FILE_FORMATS
    assert "fileFormats" not in record.create
    assert record.create["extension"]["dataswampFileFormat"] == "h5ad"


def test_a_corrupt_byte_count_omits_the_native_size_rather_than_guessing() -> None:
    shards = {
        "datasets": [
            {
                "id": "ds-x",
                "asset_type": "dataset",
                "study_id": "study-1",
                "programme_id": "prog-1",
                "physical_bytes": "quite large",
            }
        ]
    }
    plan = build_plan(SourceGraph(mode=ExportMode.OBSERVED, shards=shards))
    record = _record(plan, "dataswamp-biosystems.study-1.ds-x")
    assert "size" not in record.create
    assert record.create["extension"]["dataswampPhysicalBytes"] == "quite large"


# -- ownership and stewardship ------------------------------------------------


def test_the_owner_is_a_native_owner_reference(mini_observed: ExportPlan) -> None:
    record = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-alpha")
    owners = [reference for reference in record.references if reference.field == "owners"]
    assert [reference.target for reference in owners] == ["dataswamp-team-genomics"]
    assert all(reference.entity_type == "team" for reference in owners)


def test_stewards_are_not_flattened_into_owners(mini_observed: ExportPlan) -> None:
    """The distinction this benchmark tests for must not be destroyed to fit a schema."""
    record = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-alpha")
    owner_targets = {
        reference.target for reference in record.references if reference.field == "owners"
    }
    assert "dataswamp-team-governance" not in owner_targets
    assert "dataswamp-team-quality" not in owner_targets
    assert record.create["extension"]["dataswampStewardRefs"] == ("team-governance,team-quality")


def test_stewarding_teams_are_still_emitted_as_teams(mini_observed: ExportPlan) -> None:
    """Kept as a property, but the teams themselves are real entities."""
    teams = {record.fqn for record in _by_phase(mini_observed, "team")}
    assert teams == {
        "dataswamp-team-genomics",
        "dataswamp-team-governance",
        "dataswamp-team-quality",
    }


def test_no_expert_field_is_used_for_a_team() -> None:
    """OpenMetadata experts take user login names; DataSwamp stewards are teams."""
    plan = build_plan(
        SourceGraph(
            mode=ExportMode.OBSERVED,
            shards={
                "datasets": [
                    {
                        "id": "ds-x",
                        "asset_type": "dataset",
                        "study_id": "s",
                        "programme_id": "p",
                        "steward_refs": ["team-a"],
                    }
                ]
            },
        )
    )
    for record in plan.records:
        if record.create is not None:
            assert "experts" not in record.create


# -- contracts and quality ----------------------------------------------------


def test_contract_facts_are_preserved_as_properties(mini_observed: ExportPlan) -> None:
    extension = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-alpha").create[
        "extension"
    ]
    assert extension["dataswampContractId"] == "contract-ds-alpha"
    assert extension["dataswampContractVersion"] == "2.1.0"
    assert extension["dataswampSchemaRef"] == "schemas/alpha.json"
    assert extension["dataswampSla"] == "monthly"


def test_quality_check_facts_are_preserved_even_though_the_concept_is_unsupported(
    mini_observed: ExportPlan,
) -> None:
    extension = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-alpha").create[
        "extension"
    ]
    assert extension["dataswampQualityChecks"] == "qc-ds-alpha-1:completeness:pass"


def test_quality_results_are_a_blocked_plan_naming_their_blocker(
    mini_observed: ExportPlan,
) -> None:
    results = _by_phase(mini_observed, "test-result")
    assert len(results) == 1
    plan = results[0].plan
    assert plan["status"] == "blocked"
    assert "TABLE and COLUMN" in plan["blockedBy"]
    assert plan["checkType"] == "completeness"
    assert plan["evidence"] == "all required columns present"


# -- lineage ------------------------------------------------------------------


def test_dataset_lineage_becomes_an_edge_plan(mini_observed: ExportPlan) -> None:
    edges = _by_phase(mini_observed, "lineage")
    assert len(edges) == 1
    plan = edges[0].plan
    assert plan["fromEntity"]["fullyQualifiedName"].endswith("ds-alpha")
    assert plan["toEntity"]["fullyQualifiedName"].endswith("ds-bravo")


def test_the_edge_type_is_carried_honestly_not_asserted_natively(
    mini_observed: ExportPlan,
) -> None:
    """OpenMetadata has no typed-relationship field, so the type goes in a description."""
    plan = _by_phase(mini_observed, "lineage")[0].plan
    assert plan["dataswampEdgeType"] == "derived_from"
    assert "derived_from" in plan["description"]


def test_file_to_dataset_is_containment_not_lineage(mini_observed: ExportPlan) -> None:
    file_record = _record(
        mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-alpha.file-ds-alpha-1"
    )
    parents = [reference for reference in file_record.references if reference.field == "parent"]
    assert [reference.target for reference in parents] == [
        "dataswamp-biosystems.study-nsclc-01.ds-alpha"
    ]
    edge_targets = {
        edge.plan["fromEntity"]["fullyQualifiedName"]
        for edge in _by_phase(mini_observed, "lineage")
    }
    assert file_record.fqn not in edge_targets


def test_self_lineage_is_dropped_and_counted() -> None:
    shards = {
        "datasets": [{"id": "ds-x", "asset_type": "dataset", "study_id": "s", "programme_id": "p"}],
        "lineage": [
            {"id": "e", "upstream_id": "ds-x", "downstream_id": "ds-x", "edge_type": "derived_from"}
        ],
    }
    plan = build_plan(SourceGraph(mode=ExportMode.OBSERVED, shards=shards))
    assert not _by_phase(plan, "lineage")
    row = next(
        row for row in plan.coverage["concepts"] if row["source_concept"] == "dataset_lineage"
    )
    assert row["deliberately_dropped_count"] == 1


def test_lineage_to_a_non_dataset_is_counted_as_unsupported() -> None:
    shards = {
        "datasets": [{"id": "ds-x", "asset_type": "dataset", "study_id": "s", "programme_id": "p"}],
        "lineage": [
            {"id": "e", "upstream_id": "run-1", "downstream_id": "ds-x", "edge_type": "produced"}
        ],
    }
    plan = build_plan(SourceGraph(mode=ExportMode.OBSERVED, shards=shards))
    row = next(
        row for row in plan.coverage["concepts"] if row["source_concept"] == "non_dataset_lineage"
    )
    assert row["classification"] == Fidelity.UNSUPPORTED.value
    assert row["source_record_count"] == 1
    assert row["emitted_record_count"] == 0


# -- ordering -----------------------------------------------------------------


def test_load_phases_appear_in_contract_order(mini_truth: ExportPlan) -> None:
    seen = [record.phase for record in mini_truth.records]
    indices = [PHASES.index(phase) for phase in seen]
    assert indices == sorted(indices)


def test_order_increases_monotonically_from_one(mini_truth: ExportPlan) -> None:
    orders = [record.order for record in mini_truth.records]
    assert orders == list(range(1, len(orders) + 1))


def test_custom_properties_are_registered_before_any_entity_uses_them(
    mini_truth: ExportPlan,
) -> None:
    last_registration = max(record.order for record in mini_truth.custom_properties)
    first_extension = min(
        record.order
        for record in mini_truth.records
        if record.create is not None and "extension" in record.create
    )
    assert last_registration < first_extension


# -- custom properties --------------------------------------------------------


def test_property_names_are_camel_case_and_prefixed(mini_observed: ExportPlan) -> None:
    for record in mini_observed.custom_properties:
        name = record.create["name"]
        assert name.startswith("dataswamp")
        assert name.isalnum()


def test_data_products_do_not_register_file_only_properties() -> None:
    container = {name for name, _ in property_specs("container", privileged=False)}
    product = {name for name, _ in property_specs("dataProduct", privileged=False)}
    assert "dataswampChecksum" in container
    assert "dataswampChecksum" not in product
    assert "dataswampStewardRefs" in product


def test_truth_only_properties_are_registered_only_in_truth_mode() -> None:
    observed = {name for name, _ in property_specs("container", privileged=False)}
    truth = {name for name, _ in property_specs("container", privileged=True)}
    assert not [name for name in observed if name.startswith(TRUTH_ONLY_PROPERTY_PREFIX)]
    assert {name for name in truth if name.startswith(TRUTH_ONLY_PROPERTY_PREFIX)} == {
        "dataswampTruthExport",
        "dataswampTruthExpectedFindingRules",
    }


# -- coverage -----------------------------------------------------------------


def test_every_emitted_concept_is_classified(mini_truth: ExportPlan) -> None:
    """The cross-check: a new concept cannot appear without someone classifying it."""
    emitted = {record.concept for record in mini_truth.records} - {"custom_property"}
    assert emitted <= CONCEPT_NAMES


def test_coverage_lists_every_declared_concept(mini_observed: ExportPlan) -> None:
    listed = {row["source_concept"] for row in mini_observed.coverage["concepts"]}
    assert listed == CONCEPT_NAMES


def test_every_non_exact_row_carries_a_reason(mini_observed: ExportPlan) -> None:
    for row in mini_observed.coverage["concepts"]:
        if row["classification"] != Fidelity.EXACT.value:
            assert row.get("reason"), row["source_concept"]


def test_stewardship_is_reported_lossy_with_the_reason(mini_observed: ExportPlan) -> None:
    row = next(
        row for row in mini_observed.coverage["concepts"] if row["source_concept"] == "stewardship"
    )
    assert row["classification"] == Fidelity.LOSSY.value
    assert "owner/steward" in row["reason"]
    assert row["source_record_count"] == 6  # three assets, two stewards each


def test_the_data_contract_is_reported_lossy(mini_observed: ExportPlan) -> None:
    row = next(
        row
        for row in mini_observed.coverage["concepts"]
        if row["source_concept"] == "data_contract"
    )
    assert row["classification"] == Fidelity.LOSSY.value
    assert row["openmetadata_target"] != "dataContract"


def test_unsupported_concepts_are_present_and_targetless(mini_observed: ExportPlan) -> None:
    unsupported = {
        row["source_concept"]
        for row in mini_observed.coverage["concepts"]
        if row["classification"] == Fidelity.UNSUPPORTED.value
    }
    assert {
        "quality_check",
        "quality_check_result",
        "subject",
        "biospecimen",
        "assay",
        "instrument_run",
        "pipeline_run",
        "non_dataset_lineage",
    } <= unsupported
    for row in mini_observed.coverage["concepts"]:
        if row["classification"] == Fidelity.UNSUPPORTED.value:
            assert row["openmetadata_target"] is None


def test_semantic_and_operational_axes_are_reported_separately(
    mini_observed: ExportPlan,
) -> None:
    """A deferred mapping can be reasonable; an unsupported one can be deferred."""
    rows = {row["source_concept"]: row for row in mini_observed.coverage["concepts"]}
    assert rows["dataset_lineage"]["classification"] == Fidelity.REASONABLE.value
    assert rows["dataset_lineage"]["operational_state"] == State.DEFERRED.value
    assert rows["quality_check_result"]["classification"] == Fidelity.UNSUPPORTED.value
    assert rows["quality_check_result"]["operational_state"] == State.DEFERRED.value
    assert rows["quality_check"]["operational_state"] == State.NOT_MAPPED.value


def test_coverage_counts_match_what_was_emitted(mini_observed: ExportPlan) -> None:
    rows = {row["source_concept"]: row for row in mini_observed.coverage["concepts"]}
    assert rows["dataset"]["emitted_record_count"] == len(
        _by_phase(mini_observed, "dataset-container")
    )
    assert rows["physical_file"]["emitted_record_count"] == len(
        _by_phase(mini_observed, "file-container")
    )
    assert rows["data_product"]["emitted_record_count"] == len(
        _by_phase(mini_observed, "data-product")
    )
    assert rows["quality_check"]["emitted_record_count"] == 0
    assert rows["quality_check"]["deliberately_dropped_count"] == 1


def test_coverage_is_identical_in_both_modes(
    mini_observed: ExportPlan, mini_truth: ExportPlan
) -> None:
    """Coverage describes the mapping, not the privilege level.

    The *counts* legitimately differ by one: a truth export emits the additional
    privileged facet tag. Nothing about how faithfully a concept maps may depend
    on which mode is running, so the classifications, targets and reasons are
    compared exactly.
    """

    def semantics(coverage: dict) -> list[tuple]:
        return [
            (
                row["source_concept"],
                row["openmetadata_target"],
                row["classification"],
                row["operational_state"],
                row.get("reason"),
            )
            for row in coverage["concepts"]
        ]

    assert semantics(mini_observed.coverage) == semantics(mini_truth.coverage)
    observed_counts = {
        row["source_concept"]: row["emitted_record_count"]
        for row in mini_observed.coverage["concepts"]
    }
    truth_counts = {
        row["source_concept"]: row["emitted_record_count"]
        for row in mini_truth.coverage["concepts"]
    }
    differing = {key for key in observed_counts if observed_counts[key] != truth_counts[key]}
    assert differing == {"facet_tag"}
    assert truth_counts["facet_tag"] == observed_counts["facet_tag"] + 1


# -- privilege markers --------------------------------------------------------


def test_a_truth_export_marks_every_asset_three_independent_ways(
    mini_truth: ExportPlan,
) -> None:
    privileged_tag = om_fqn.tag_fqn(TAG_PRIVILEGED)
    for phase in ("dataset-container", "file-container", "data-product"):
        for record in _by_phase(mini_truth, phase):
            tags = {tag["tagFQN"] for tag in record.create["tags"]}
            assert privileged_tag in tags
            assert record.create["extension"]["dataswampTruthExport"] == "true"


def test_expected_finding_rules_travel_only_in_truth_mode(
    mini_truth: ExportPlan, mini_observed: ExportPlan
) -> None:
    truth_record = _record(mini_truth, "dataswamp-biosystems.study-nsclc-01.ds-alpha")
    assert truth_record.create["extension"]["dataswampTruthExpectedFindingRules"] == (
        "RULE-ONE,RULE-TWO"
    )
    observed_record = _record(mini_observed, "dataswamp-biosystems.study-nsclc-01.ds-alpha")
    assert not [
        key
        for key in observed_record.create["extension"]
        if key.startswith(TRUTH_ONLY_PROPERTY_PREFIX)
    ]


def test_an_observed_export_never_emits_the_privileged_tag(mini_observed: ExportPlan) -> None:
    assert om_fqn.tag_fqn(TAG_PRIVILEGED) not in {record.fqn for record in mini_observed.records}
    assert TAG_PRIVILEGED not in json.dumps([record.as_json() for record in mini_observed.records])
