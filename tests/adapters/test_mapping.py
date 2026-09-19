"""The DataHub mapping contract: aspects, identity, lineage, ownership, privilege."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.adapters.datahub import (
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
    SourceGraph,
    build_mcps,
    urns,
    validate_export,
)
from dataswamp_biosystems.adapters.datahub.validate import DATASET_ASSERTION_SCOPES
from dataswamp_biosystems.truth import serialize
from tests.adapters.conftest import MINI_OBSERVED_FIXTURE, MINI_TRUTH_FIXTURE


def _by_urn(mcps: list[dict[str, Any]], urn: str) -> dict[str, Any]:
    return {mcp["aspectName"]: mcp["aspect"]["json"] for mcp in mcps if mcp["entityUrn"] == urn}


# -- structure ----------------------------------------------------------------


def test_every_proposal_is_well_formed(mini_observed: SourceGraph) -> None:
    for mcp in build_mcps(mini_observed):
        assert set(mcp) == {"entityType", "entityUrn", "changeType", "aspectName", "aspect"}
        assert mcp["changeType"] == "UPSERT"
        assert set(mcp["aspect"]) == {"json"}


def test_the_payload_validates(mini_observed: SourceGraph, mini_truth: SourceGraph) -> None:
    assert validate_export(build_mcps(mini_observed), ExportMode.OBSERVED) == []
    assert validate_export(build_mcps(mini_truth), ExportMode.TRUTH) == []


def test_no_duplicate_urn_and_aspect_pairs(mini_observed: SourceGraph) -> None:
    seen = [(mcp["entityUrn"], mcp["aspectName"]) for mcp in build_mcps(mini_observed)]
    assert len(seen) == len(set(seen))


def test_required_aspects_are_present(mini_observed: SourceGraph) -> None:
    mcps = build_mcps(mini_observed)
    dataset = _by_urn(mcps, urns.dataset_urn("ds-alpha"))
    assert {"datasetProperties", "subTypes", "status", "ownership", "globalTags"} <= set(dataset)
    assert dataset["subTypes"]["typeNames"] == ["Dataset"]
    product = _by_urn(mcps, urns.data_product_urn("dp-omics"))
    assert {"dataProductProperties", "ownership", "globalTags", "domains"} <= set(product)


def test_every_referenced_urn_is_emitted(mini_observed: SourceGraph) -> None:
    """A reference to an entity nobody defined would ingest as a dangling stub."""
    assert validate_export(build_mcps(mini_observed), ExportMode.OBSERVED) == []


# -- identity -----------------------------------------------------------------


def test_the_dataswamp_id_travels_with_every_entity(mini_observed: SourceGraph) -> None:
    mcps = build_mcps(mini_observed)
    properties = _by_urn(mcps, urns.dataset_urn("ds-alpha"))["datasetProperties"]
    assert properties["customProperties"]["dataswamp_id"] == "ds-alpha"
    container = _by_urn(mcps, urns.container_urn("study-nsclc-01"))["containerProperties"]
    assert container["customProperties"]["dataswamp_id"] == "study-nsclc-01"


def test_identity_never_derives_from_a_display_name(mini_observed: SourceGraph) -> None:
    """Retitling an asset must not move its URN."""
    renamed = SourceGraph(
        mode=ExportMode.OBSERVED,
        shards={
            **mini_observed.shards,
            "datasets": [
                {**record, "title": "Totally different", "description": "Rewritten."}
                for record in mini_observed.records("datasets")
            ],
        },
    )
    original = {mcp["entityUrn"] for mcp in build_mcps(mini_observed)}
    assert {mcp["entityUrn"] for mcp in build_mcps(renamed)} == original


# -- ownership, tags, glossary ------------------------------------------------


def test_owner_and_stewards_map_to_distinct_ownership_types(mini_observed: SourceGraph) -> None:
    owners = _by_urn(build_mcps(mini_observed), urns.dataset_urn("ds-alpha"))["ownership"]["owners"]
    assert {"owner": urns.corp_group_urn("team-genomics"), "type": "DATAOWNER"} in owners
    assert {"owner": urns.corp_group_urn("team-quality"), "type": "DATA_STEWARD"} in owners
    assert sum(1 for owner in owners if owner["type"] == "DATAOWNER") == 1


def test_owning_and_stewarding_teams_are_emitted_as_groups(mini_observed: SourceGraph) -> None:
    mcps = build_mcps(mini_observed)
    for team in ("team-genomics", "team-governance", "team-quality"):
        assert _by_urn(mcps, urns.corp_group_urn(team))["corpGroupInfo"]["displayName"] == team


def test_controlled_vocabulary_values_become_glossary_terms(mini_observed: SourceGraph) -> None:
    mcps = build_mcps(mini_observed)
    terms = {
        term["urn"]
        for term in _by_urn(mcps, urns.dataset_urn("ds-alpha"))["glossaryTerms"]["terms"]
    }
    assert urns.glossary_term_urn("modality", "bulk-rna-seq") in terms
    assert urns.glossary_term_urn("intended-use", "model-training") in terms
    info = _by_urn(mcps, urns.glossary_term_urn("modality", "bulk-rna-seq"))["glossaryTermInfo"]
    assert info["parentNode"] == urns.glossary_node_urn("modality")


def test_tags_carry_coarse_facets_only(mini_observed: SourceGraph) -> None:
    tags = {
        tag["tag"]
        for tag in _by_urn(build_mcps(mini_observed), urns.dataset_urn("ds-alpha"))["globalTags"][
            "tags"
        ]
    }
    assert urns.tag_urn("dataswamp-synthetic") in tags
    assert urns.tag_urn("modality-group-sequencing") in tags


def test_programme_becomes_a_domain_and_study_a_container(mini_observed: SourceGraph) -> None:
    dataset = _by_urn(build_mcps(mini_observed), urns.dataset_urn("ds-alpha"))
    assert dataset["domains"]["domains"] == [urns.domain_urn("prog-nsclc")]
    assert dataset["container"]["container"] == urns.container_urn("study-nsclc-01")


def test_contract_metadata_rides_on_the_dataset(mini_observed: SourceGraph) -> None:
    properties = _by_urn(build_mcps(mini_observed), urns.dataset_urn("ds-alpha"))[
        "datasetProperties"
    ]["customProperties"]
    assert properties["dataswamp_contract_version"] == "2.1.0"
    assert properties["dataswamp_schema_ref"] == "schemas/alpha.json"


# -- lineage and file relationships -------------------------------------------


def test_files_are_emitted_as_file_subtype_datasets(mini_observed: SourceGraph) -> None:
    file_aspects = _by_urn(build_mcps(mini_observed), urns.dataset_urn("file-ds-alpha-1"))
    assert file_aspects["subTypes"]["typeNames"] == ["File"]
    properties = file_aspects["datasetProperties"]["customProperties"]
    assert properties["dataswamp_dataset_id"] == "ds-alpha"
    assert properties["dataswamp_file_format"] == "parquet"


def test_a_dataset_is_downstream_of_its_files(mini_observed: SourceGraph) -> None:
    upstreams = _by_urn(build_mcps(mini_observed), urns.dataset_urn("ds-alpha"))["upstreamLineage"][
        "upstreams"
    ]
    assert {
        "auditStamp": {"actor": "urn:li:corpuser:dataswamp", "time": 0},
        "dataset": urns.dataset_urn("file-ds-alpha-1"),
        "type": "COPY",
    } in upstreams


def test_dataset_to_dataset_lineage_is_mapped(mini_observed: SourceGraph) -> None:
    upstreams = _by_urn(build_mcps(mini_observed), urns.dataset_urn("ds-bravo"))["upstreamLineage"][
        "upstreams"
    ]
    assert any(
        entry["dataset"] == urns.dataset_urn("ds-alpha") and entry["type"] == "TRANSFORMED"
        for entry in upstreams
    )


def test_data_product_lists_its_component_datasets(mini_observed: SourceGraph) -> None:
    assets = _by_urn(build_mcps(mini_observed), urns.data_product_urn("dp-omics"))[
        "dataProductProperties"
    ]["assets"]
    assert [entry["destinationUrn"] for entry in assets] == [
        urns.dataset_urn("ds-alpha"),
        urns.dataset_urn("ds-bravo"),
    ]


def test_quality_checks_become_dataset_assertions(mini_observed: SourceGraph) -> None:
    aspects = _by_urn(build_mcps(mini_observed), urns.assertion_urn("qc-ds-alpha-1"))
    assert aspects["assertionInfo"]["datasetAssertion"]["dataset"] == urns.dataset_urn("ds-alpha")
    run = aspects["assertionRunEvent"]
    assert run["result"]["type"] == "SUCCESS"
    assert run["timestampMillis"] == 1772323200000, "derived from evaluated_at, never a clock"


# The one mini quality check's assertion, field for field. Only `scope` moved in
# #44 (DATASET_COLUMN -> UNKNOWN); pinning the rest proves nothing else did.
_ALPHA_DATASET = "urn:li:dataset:(urn:li:dataPlatform:dataswamp,dataswamp_biosystems.ds-alpha,PROD)"
_EXPECTED_ASSERTION_INFO: dict[str, Any] = {
    "type": "DATASET",
    "datasetAssertion": {
        "dataset": _ALPHA_DATASET,
        "scope": "UNKNOWN",
        "operator": "_NATIVE_",
        "aggregation": "_NATIVE_",
        "nativeType": "completeness",
    },
    "description": "all required columns present",
    "customProperties": {
        "dataswamp_id": "qc-ds-alpha-1",
        "dataswamp_asset_id": "ds-alpha",
        "dataswamp_check_type": "completeness",
        "dataswamp_status": "pass",
    },
}
_EXPECTED_RUN_EVENT: dict[str, Any] = {
    "timestampMillis": 1772323200000,
    "runId": "qc-ds-alpha-1",
    "assertionUrn": urns.assertion_urn("qc-ds-alpha-1"),
    "asserteeUrn": _ALPHA_DATASET,
    "status": "COMPLETE",
    "result": {"type": "SUCCESS", "nativeResults": {"evidence": "all required columns present"}},
}


@pytest.mark.parametrize("graph", ["mini_observed", "mini_truth"])
def test_quality_check_assertion_payload_is_pinned(
    graph: str, request: pytest.FixtureRequest
) -> None:
    """The scope is UNKNOWN and every other assertion field is exactly as before."""
    source: SourceGraph = request.getfixturevalue(graph)
    aspects = _by_urn(build_mcps(source), urns.assertion_urn("qc-ds-alpha-1"))
    assert aspects["assertionInfo"] == _EXPECTED_ASSERTION_INFO
    assert aspects["assertionRunEvent"] == _EXPECTED_RUN_EVENT


def test_quality_check_assertions_claim_no_column(mini_observed: SourceGraph) -> None:
    """A DataSwamp check names a dataset and nothing narrower (#44)."""
    infos = [
        mcp["aspect"]["json"]
        for mcp in build_mcps(mini_observed)
        if mcp["aspectName"] == "assertionInfo"
    ]
    assert infos
    for info in infos:
        dataset_assertion = info["datasetAssertion"]
        assert dataset_assertion["scope"] == "UNKNOWN"
        assert dataset_assertion["scope"] in DATASET_ASSERTION_SCOPES
        assert "fields" not in dataset_assertion
        assert dataset_assertion["dataset"] == urns.dataset_urn(
            info["customProperties"]["dataswamp_asset_id"]
        )


def test_the_pinned_scope_enum_is_datahubs() -> None:
    """Copied from DatasetAssertionScope at v1.7.0 (and v0.13.0); not invented."""
    assert {
        "DATASET_COLUMN",
        "DATASET_ROWS",
        "DATASET_STORAGE_SIZE",
        "DATASET_SCHEMA",
        "UNKNOWN",
    } == DATASET_ASSERTION_SCOPES


def _with_scope(
    mcps: list[dict[str, Any]], scope: str, fields: list[str] | None = None
) -> list[dict[str, Any]]:
    mutated = copy.deepcopy(mcps)
    for mcp in mutated:
        if mcp["aspectName"] == "assertionInfo":
            mcp["aspect"]["json"]["datasetAssertion"]["scope"] = scope
            if fields is not None:
                mcp["aspect"]["json"]["datasetAssertion"]["fields"] = fields
    return mutated


def test_a_column_scope_without_fields_is_refused(mini_observed: SourceGraph) -> None:
    """Schema-valid upstream (``fields`` is optional), but a DataSwamp contract breach."""
    problems = validate_export(
        _with_scope(build_mcps(mini_observed), "DATASET_COLUMN"), ExportMode.OBSERVED
    )
    assert len(problems) == 1
    assert problems[0].endswith("DATASET_COLUMN assertion names no column in 'fields'")


def test_a_column_scope_naming_a_column_is_not_a_scope_problem(
    mini_observed: SourceGraph,
) -> None:
    """Paired with the refusal: the rule is about the missing column, not the value."""
    column = f"urn:li:schemaField:({_ALPHA_DATASET},sample_id)"
    problems = validate_export(
        _with_scope(build_mcps(mini_observed), "DATASET_COLUMN", [column]), ExportMode.OBSERVED
    )
    assert problems == []


def test_a_scope_outside_the_enum_is_refused(mini_observed: SourceGraph) -> None:
    problems = validate_export(
        _with_scope(build_mcps(mini_observed), "DATASET"), ExportMode.OBSERVED
    )
    assert len(problems) == 1
    assert problems[0].endswith("assertion scope 'DATASET' is not a DataHub DatasetAssertionScope")


# -- privilege ----------------------------------------------------------------


def test_observed_export_contains_no_truth_only_field(mini_observed: SourceGraph) -> None:
    rendered = serialize.canonical_json(build_mcps(mini_observed))
    assert TRUTH_ONLY_PROPERTY_PREFIX not in rendered
    assert TAG_PRIVILEGED not in rendered
    assert "RULE-ONE" not in rendered


def test_truth_export_is_explicitly_marked_privileged(mini_truth: SourceGraph) -> None:
    mcps = build_mcps(mini_truth)
    tags = {tag["tag"] for tag in _by_urn(mcps, urns.dataset_urn("ds-alpha"))["globalTags"]["tags"]}
    assert urns.tag_urn(TAG_PRIVILEGED) in tags
    properties = _by_urn(mcps, urns.dataset_urn("ds-alpha"))["datasetProperties"][
        "customProperties"
    ]
    assert properties[f"{TRUTH_ONLY_PROPERTY_PREFIX}expected_finding_rules"] == "RULE-ONE,RULE-TWO"


def test_the_validator_catches_a_leak_into_an_observed_export(
    mini_truth: SourceGraph,
) -> None:
    """The privilege boundary is enforced, not merely intended."""
    problems = validate_export(build_mcps(mini_truth), ExportMode.OBSERVED)
    assert any("leaks truth-only" in problem for problem in problems)


def test_the_validator_catches_an_unmarked_truth_export(mini_observed: SourceGraph) -> None:
    problems = validate_export(build_mcps(mini_observed), ExportMode.TRUTH)
    assert any("not tagged privileged" in problem for problem in problems)


# -- determinism and drift ----------------------------------------------------


def test_mapping_is_deterministic(mini_observed: SourceGraph) -> None:
    assert build_mcps(mini_observed) == build_mcps(mini_observed)


def test_mapping_is_independent_of_input_order(mini_observed: SourceGraph) -> None:
    reversed_shards = {
        shard: list(reversed(records)) for shard, records in mini_observed.shards.items()
    }
    shuffled = SourceGraph(mode=ExportMode.OBSERVED, shards=reversed_shards)
    assert build_mcps(shuffled) == build_mcps(mini_observed)


@pytest.mark.parametrize(
    ("fixture_path", "mode_name"),
    [(MINI_OBSERVED_FIXTURE, "observed"), (MINI_TRUTH_FIXTURE, "truth")],
)
def test_payload_matches_the_committed_fixture(
    fixture_path: Path,
    mode_name: str,
    mini_observed: SourceGraph,
    mini_truth: SourceGraph,
) -> None:
    """Pins the mapping. Regenerate deliberately with scripts/update_datahub_fixtures.py."""
    source = mini_observed if mode_name == "observed" else mini_truth
    rendered = "".join(f"{serialize.canonical_json(mcp)}\n" for mcp in build_mcps(source))
    assert rendered == fixture_path.read_text(encoding="utf-8")
