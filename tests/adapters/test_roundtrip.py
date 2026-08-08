"""The round-trip differ, exercised as the pure function it is.

Every test here builds both sides by hand: no server, no export, no bundle. That
is deliberate — the four claims are properties of two aspect maps, and proving
them against hand-built inputs is what makes the contract legible.
"""

from __future__ import annotations

from dataswamp_biosystems.adapters.datahub import urns
from dataswamp_biosystems.adapters.datahub.mapping import (
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
)
from dataswamp_biosystems.adapters.datahub.roundtrip import (
    ENTITY_FAMILIES,
    SCANNABLE_FAMILIES,
    Coverage,
    DiscrepancyKind,
    Readback,
    RetrievedAspect,
    compare,
)

DATASET_URN = urns.dataset_urn("ds-alpha")
OTHER_URN = urns.dataset_urn("ds-bravo")


def _proposal(urn: str, aspect_name: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "entityType": "dataset",
        "entityUrn": urn,
        "changeType": "UPSERT",
        "aspectName": aspect_name,
        "aspect": {"json": payload},
    }


def _readback(
    *aspects: RetrievedAspect, scanned: bool = True, extra_urns: tuple[str, ...] = ()
) -> Readback:
    families = {family.entity_type for family in SCANNABLE_FAMILIES} if scanned else set()
    namespace = {item.entity_urn for item in aspects if item.entity_type == "dataset"}
    namespace.update(extra_urns)
    return Readback(
        aspects=aspects,
        scanned_families=frozenset(families),
        namespace_urns=frozenset(namespace),
    )


def _sent_and_back(payload: dict[str, object], aspect_name: str = "datasetProperties"):
    sent = [_proposal(DATASET_URN, aspect_name, payload)]
    return sent, RetrievedAspect("dataset", DATASET_URN, aspect_name, payload)


# ------------------------------------------------------------ clean round-trip


def test_a_clean_round_trip_reports_no_discrepancies() -> None:
    sent, retrieved = _sent_and_back({"name": "alpha", "customProperties": {"k": "v"}})
    result = compare(sent, _readback(retrieved), ExportMode.OBSERVED)
    assert result.clean
    assert result.discrepancies == ()
    assert result.leak_findings == ()
    assert result.counts == {"sent": 1, "retrieved": 1, "matched": 1}


def test_a_clean_round_trip_survives_the_servers_own_metadata() -> None:
    """The realistic clean case: the server adds its ingestion provenance."""
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    retrieved = RetrievedAspect(
        "dataset",
        DATASET_URN,
        "datasetProperties",
        {"name": "alpha", "systemMetadata": {"runId": "r1"}},
    )
    assert compare(sent, _readback(retrieved), ExportMode.OBSERVED).clean


# ---------------------------------------------------------------- completeness


def test_a_missing_aspect_is_reported() -> None:
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    result = compare(sent, _readback(), ExportMode.OBSERVED)
    missing = result.of_kind(DiscrepancyKind.MISSING)
    assert len(missing) == 1
    assert missing[0].entity_urn == DATASET_URN
    assert missing[0].aspect_name == "datasetProperties"
    assert result.counts["matched"] == 0


def test_a_missing_aspect_is_not_also_counted_as_mutated() -> None:
    """Completeness and fidelity are separate claims, so one fault is one finding."""
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    result = compare(sent, _readback(), ExportMode.OBSERVED)
    assert len(result.of_kind(DiscrepancyKind.MUTATED)) == 0


# -------------------------------------------------------------------- fidelity


def test_a_mutated_scalar_reports_an_exact_field_path() -> None:
    sent = [
        _proposal(
            DATASET_URN,
            "datasetProperties",
            {"name": "alpha", "customProperties": {"dataswamp_owner": "team-a"}},
        )
    ]
    retrieved = RetrievedAspect(
        "dataset",
        DATASET_URN,
        "datasetProperties",
        {"name": "alpha", "customProperties": {"dataswamp_owner": "team-z"}},
    )
    mutated = compare(sent, _readback(retrieved), ExportMode.OBSERVED).of_kind(
        DiscrepancyKind.MUTATED
    )
    assert len(mutated) == 1
    assert [(d.path, d.sent, d.retrieved) for d in mutated[0].differences] == [
        ("customProperties.dataswamp_owner", "team-a", "team-z")
    ]


def test_a_mutation_inside_an_ordered_list_reports_its_index() -> None:
    sent = [_proposal(DATASET_URN, "subTypes", {"typeNames": ["Dataset", "View"]})]
    retrieved = RetrievedAspect(
        "dataset", DATASET_URN, "subTypes", {"typeNames": ["Dataset", "Table"]}
    )
    mutated = compare(sent, _readback(retrieved), ExportMode.OBSERVED).of_kind(
        DiscrepancyKind.MUTATED
    )
    assert [d.path for d in mutated[0].differences] == ["typeNames[1]"]


def test_a_dropped_field_and_an_added_field_are_distinguishable() -> None:
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha", "gone": "x"})]
    retrieved = RetrievedAspect(
        "dataset", DATASET_URN, "datasetProperties", {"name": "alpha", "added": "y"}
    )
    mutated = compare(sent, _readback(retrieved), ExportMode.OBSERVED).of_kind(
        DiscrepancyKind.MUTATED
    )
    rendered = {(d.path, d.sent, d.retrieved) for d in mutated[0].differences}
    assert rendered == {("gone", "x", "<absent>"), ("added", "<absent>", "y")}


def test_a_null_value_and_an_absent_field_are_distinguishable() -> None:
    """Observed records carry nulls by design, so the distinction is load-bearing."""
    sent = [_proposal(DATASET_URN, "datasetProperties", {"description": None})]
    retrieved = RetrievedAspect("dataset", DATASET_URN, "datasetProperties", {})
    mutated = compare(sent, _readback(retrieved), ExportMode.OBSERVED).of_kind(
        DiscrepancyKind.MUTATED
    )
    assert [(d.path, d.sent, d.retrieved) for d in mutated[0].differences] == [
        ("description", "null", "<absent>")
    ]


def test_an_unknown_server_addition_is_reported_as_a_mutation() -> None:
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    retrieved = RetrievedAspect(
        "dataset", DATASET_URN, "datasetProperties", {"name": "alpha", "serverGuess": True}
    )
    mutated = compare(sent, _readback(retrieved), ExportMode.OBSERVED).of_kind(
        DiscrepancyKind.MUTATED
    )
    assert [d.path for d in mutated[0].differences] == ["serverGuess"]


# ------------------------------------------------------------------ containment


def test_an_extra_aspect_on_a_sent_urn_is_reported() -> None:
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    readback = _readback(
        RetrievedAspect("dataset", DATASET_URN, "datasetProperties", {"name": "alpha"}),
        RetrievedAspect("dataset", DATASET_URN, "institutionalMemory", {"elements": []}),
    )
    extra = compare(sent, readback, ExportMode.OBSERVED).of_kind(DiscrepancyKind.EXTRA_ASPECT)
    assert len(extra) == 1
    assert extra[0].aspect_name == "institutionalMemory"


def test_an_extra_dataset_inside_the_dataswamp_namespace_is_reported() -> None:
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    readback = _readback(
        RetrievedAspect("dataset", DATASET_URN, "datasetProperties", {"name": "alpha"}),
        extra_urns=(OTHER_URN,),
    )
    extra = compare(sent, readback, ExportMode.OBSERVED).of_kind(DiscrepancyKind.EXTRA_ENTITY)
    assert [item.entity_urn for item in extra] == [OTHER_URN]
    assert extra[0].entity_type == "dataset"


def test_an_unrelated_catalogue_dataset_is_never_reported_as_a_dataswamp_extra() -> None:
    """The false-accusation guard.

    A benchmark is ingested alongside somebody's real estate. Reporting their
    dataset as a DataSwamp extra would be a claim about their data.
    """
    foreign = "urn:li:dataset:(urn:li:dataPlatform:snowflake,warehouse.orders,PROD)"
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    readback = _readback(
        RetrievedAspect("dataset", DATASET_URN, "datasetProperties", {"name": "alpha"}),
        extra_urns=(foreign,),
    )
    assert compare(sent, readback, ExportMode.OBSERVED).of_kind(DiscrepancyKind.EXTRA_ENTITY) == ()


def test_a_dataswamp_platform_dataset_outside_our_namespace_is_not_claimed() -> None:
    """Even the same platform is not enough: the dataset-name namespace must match."""
    foreign = f"urn:li:dataset:({urns.PLATFORM_URN},other_namespace.thing,PROD)"
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    readback = _readback(
        RetrievedAspect("dataset", DATASET_URN, "datasetProperties", {"name": "alpha"}),
        extra_urns=(foreign,),
    )
    assert compare(sent, readback, ExportMode.OBSERVED).of_kind(DiscrepancyKind.EXTRA_ENTITY) == ()


def test_unscannable_families_report_unavailable_coverage() -> None:
    """Honest absence beats invented certainty."""
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    coverage = compare(
        sent,
        _readback(RetrievedAspect("dataset", DATASET_URN, "datasetProperties", {"name": "alpha"})),
        ExportMode.OBSERVED,
    ).coverage
    assert coverage["dataset"] == Coverage.SCANNED.value
    for family in ("corpGroup", "tag", "container", "assertion"):
        assert coverage[family] == Coverage.UNAVAILABLE.value


def test_coverage_is_unavailable_when_no_scan_ran() -> None:
    sent = [_proposal(DATASET_URN, "datasetProperties", {"name": "alpha"})]
    readback = Readback(
        aspects=(RetrievedAspect("dataset", DATASET_URN, "datasetProperties", {"name": "alpha"}),)
    )
    result = compare(sent, readback, ExportMode.OBSERVED)
    assert set(result.coverage.values()) == {Coverage.UNAVAILABLE.value}


def test_every_emitted_entity_family_has_a_documented_scope_decision() -> None:
    """No family may be silently absent from the containment table."""
    from dataswamp_biosystems.adapters.datahub.validate import URN_PATTERNS

    assert {family.entity_type for family in ENTITY_FAMILIES} == set(URN_PATTERNS)
    for family in ENTITY_FAMILIES:
        assert family.reason.strip(), family.entity_type


# ------------------------------------------------------------------ non-leakage


def test_a_truth_only_property_is_a_leak_finding() -> None:
    sent = [_proposal(DATASET_URN, "datasetProperties", {"customProperties": {}})]
    retrieved = RetrievedAspect(
        "dataset",
        DATASET_URN,
        "datasetProperties",
        {"customProperties": {f"{TRUTH_ONLY_PROPERTY_PREFIX}finding_rules": "RULE-ONE"}},
    )
    result = compare(sent, _readback(retrieved), ExportMode.OBSERVED)
    assert [f.probe for f in result.leak_findings] == ["truth-only-property"]
    assert result.leak_findings[0].marker.startswith(TRUTH_ONLY_PROPERTY_PREFIX)


def test_the_privileged_tag_is_a_leak_finding() -> None:
    sent = [_proposal(DATASET_URN, "globalTags", {"tags": []})]
    retrieved = RetrievedAspect(
        "dataset",
        DATASET_URN,
        "globalTags",
        {"tags": [{"tag": urns.tag_urn(TAG_PRIVILEGED)}]},
    )
    result = compare(sent, _readback(retrieved), ExportMode.OBSERVED)
    assert [f.probe for f in result.leak_findings] == ["privileged-truth-tag"]


def test_leak_probes_do_not_run_for_a_truth_export() -> None:
    """A truth export is *supposed* to carry these markers and says so."""
    sent = [_proposal(DATASET_URN, "globalTags", {"tags": []})]
    retrieved = RetrievedAspect(
        "dataset", DATASET_URN, "globalTags", {"tags": [{"tag": urns.tag_urn(TAG_PRIVILEGED)}]}
    )
    assert compare(sent, _readback(retrieved), ExportMode.TRUTH).leak_findings == ()


# -------------------------------------------------------------- determinism


def test_discrepancy_ordering_is_deterministic() -> None:
    sent = [
        _proposal(OTHER_URN, "status", {"removed": False}),
        _proposal(DATASET_URN, "datasetProperties", {"name": "alpha"}),
        _proposal(DATASET_URN, "status", {"removed": False}),
    ]
    first = compare(sent, _readback(), ExportMode.OBSERVED)
    second = compare(list(reversed(sent)), _readback(), ExportMode.OBSERVED)
    assert [d.as_record() for d in first.discrepancies] == [
        d.as_record() for d in second.discrepancies
    ]
    assert [d.entity_urn for d in first.discrepancies] == sorted(
        d.entity_urn for d in first.discrepancies
    )
