"""End-to-end: ingest an emitted export, read it back, and judge it.

Everything runs against the local fake GMS, so the whole live contract is
provable with no Docker, no network and no credentials. The perturbation tests
are the substance: a differ that has only ever been shown matching inputs proves
nothing, so each fault is planted deliberately and asserted on by kind.

Most tests use the small emitted export, because a perturbation is a property of
the differ rather than of the estate's size and paying for the whole canonical
estate on each one would make the suite slow enough that people skip it. The
final section runs the same contract over the *real* emitted export, so nothing
here depends on the small payload being representative.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.datahub import urns
from dataswamp_biosystems.adapters.datahub.ingest import (
    execute_ingestion,
    load_export,
    plan_ingestion,
)
from dataswamp_biosystems.adapters.datahub.mapping import (
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
)
from dataswamp_biosystems.adapters.datahub.normalize import NORMALIZATION_VERSION
from dataswamp_biosystems.adapters.datahub.readback import read_back
from dataswamp_biosystems.adapters.datahub.report import (
    DISCREPANCIES_NAME,
    LEAK_FINDINGS_NAME,
    ROUNDTRIP_REPORT_NAME,
    write_roundtrip,
)
from dataswamp_biosystems.adapters.datahub.roundtrip import (
    ROUNDTRIP_SCHEMA_VERSION,
    DiscrepancyKind,
    compare,
)
from dataswamp_biosystems.provenance import PROVENANCE_NAME

from .fake_gms import FakeGMS, FakeGMSServer


def _ingested(export_dir: Path, state: FakeGMS | None = None):
    """Ingest an export into a fresh fake catalogue and return (export, state)."""
    export = load_export(export_dir)
    server = FakeGMSServer(state)
    with server:
        execute_ingestion(plan_ingestion(export), server.client())
    return export, server.state


def _roundtrip(export_dir: Path, state: FakeGMS | None = None):
    export, populated = _ingested(export_dir, state)
    with FakeGMSServer(populated) as server:
        readback = read_back(export, server.client())
    return export, compare(list(export.proposals), readback, export.mode)


# ------------------------------------------------------------- clean state


def test_a_faithful_catalogue_round_trips_cleanly(mini_export_dir: Path) -> None:
    _, result = _roundtrip(mini_export_dir)
    assert result.clean, [item.as_record() for item in result.discrepancies[:5]]
    assert result.counts["matched"] == result.counts["sent"]


def test_every_emitted_aspect_is_round_tripped(mini_export_dir: Path) -> None:
    """All supported aspects, not a hand-selected subset — including timeseries."""
    export, result = _roundtrip(mini_export_dir)
    emitted = {(str(p["entityUrn"]), str(p["aspectName"])) for p in export.proposals}
    assert set(result.sent_keys) == emitted
    assert "assertionRunEvent" in {aspect for _, aspect in result.sent_keys}


def test_a_second_ingestion_still_round_trips_cleanly(mini_export_dir: Path) -> None:
    """Idempotence, observed through the round-trip rather than the store."""
    export = load_export(mini_export_dir)
    state = FakeGMS()
    with FakeGMSServer(state) as server:
        client = server.client()
        execute_ingestion(plan_ingestion(export), client)
        execute_ingestion(plan_ingestion(export), client)
        readback = read_back(export, client)
    assert compare(list(export.proposals), readback, export.mode).clean


# ------------------------------------------------------------ perturbations


def test_a_dropped_aspect_is_a_completeness_failure(mini_export_dir: Path) -> None:
    export = load_export(mini_export_dir)
    target = (str(export.proposals[0]["entityUrn"]), str(export.proposals[0]["aspectName"]))
    _, result = _roundtrip(mini_export_dir, FakeGMS(drop={target}))
    missing = result.of_kind(DiscrepancyKind.MISSING)
    assert [(item.entity_urn, item.aspect_name) for item in missing] == [target]


def test_an_invented_aspect_is_a_containment_failure(mini_export_dir: Path) -> None:
    export = load_export(mini_export_dir)
    urn = str(export.proposals[0]["entityUrn"])
    state = FakeGMS(inject={(urn, "institutionalMemory"): {"elements": []}})
    _, result = _roundtrip(mini_export_dir, state)
    extra = result.of_kind(DiscrepancyKind.EXTRA_ASPECT)
    assert [(item.entity_urn, item.aspect_name) for item in extra] == [(urn, "institutionalMemory")]


def test_an_invented_dataswamp_dataset_is_a_containment_failure(
    mini_export_dir: Path,
) -> None:
    intruder = urns.dataset_urn("ds-nobody-sent-this")
    state = FakeGMS(inject_entities={intruder: {"datasetProperties": {"name": "x"}}})
    _, result = _roundtrip(mini_export_dir, state)
    extra = result.of_kind(DiscrepancyKind.EXTRA_ENTITY)
    assert [item.entity_urn for item in extra] == [intruder]


def test_a_foreign_dataset_is_not_a_containment_failure(mini_export_dir: Path) -> None:
    """Somebody else's catalogue content is not a DataSwamp extra."""
    foreign = "urn:li:dataset:(urn:li:dataPlatform:bigquery,project.table,PROD)"
    state = FakeGMS(inject_entities={foreign: {"datasetProperties": {"name": "theirs"}}})
    _, result = _roundtrip(mini_export_dir, state)
    assert result.of_kind(DiscrepancyKind.EXTRA_ENTITY) == ()


def test_a_mutated_field_is_a_fidelity_failure_with_an_exact_path(
    mini_export_dir: Path,
) -> None:
    export = load_export(mini_export_dir)
    target = next(
        proposal for proposal in export.proposals if proposal["aspectName"] == "datasetProperties"
    )
    urn = str(target["entityUrn"])
    corrupted = json.loads(json.dumps(target["aspect"]["json"]))
    corrupted["customProperties"]["dataswamp_id"] = "not-the-real-id"

    _, result = _roundtrip(mini_export_dir, FakeGMS(mutate={(urn, "datasetProperties"): corrupted}))
    mutated = result.of_kind(DiscrepancyKind.MUTATED)
    assert len(mutated) == 1
    assert [d.path for d in mutated[0].differences] == ["customProperties.dataswamp_id"]
    assert mutated[0].differences[0].retrieved == "not-the-real-id"


def test_an_unknown_server_addition_is_a_fidelity_failure(mini_export_dir: Path) -> None:
    export = load_export(mini_export_dir)
    target = next(p for p in export.proposals if p["aspectName"] == "status")
    urn = str(target["entityUrn"])
    corrupted = dict(target["aspect"]["json"]) | {"somethingNew": 1}
    _, result = _roundtrip(mini_export_dir, FakeGMS(mutate={(urn, "status"): corrupted}))
    mutated = result.of_kind(DiscrepancyKind.MUTATED)
    assert [d.path for d in mutated[0].differences] == ["somethingNew"]


# -------------------------------------------------------------- non-leakage


def test_an_observed_round_trip_finds_no_truth_markers(mini_export_dir: Path) -> None:
    _, result = _roundtrip(mini_export_dir)
    assert result.leak_findings == ()


def test_a_truth_payload_makes_the_observed_probes_fire(mini_truth_export_dir: Path) -> None:
    """The leak detector, proven to be capable of firing.

    A privileged truth export is ingested and then judged *as if* it were an
    observed one. The probes must find the markers. Everything needed to do this
    comes from the emitted export contract — the truth-only property prefix and
    the privileged tag — and not from the bundle, the ledgers or the answer key.
    """
    export = load_export(mini_truth_export_dir)
    with FakeGMSServer() as server:
        client = server.client()
        execute_ingestion(plan_ingestion(export), client)
        readback = read_back(export, client)

    judged_as_observed = compare(list(export.proposals), readback, ExportMode.OBSERVED)
    probes = {finding.probe for finding in judged_as_observed.leak_findings}
    assert probes == {"truth-only-property", "privileged-truth-tag"}

    markers = {finding.marker for finding in judged_as_observed.leak_findings}
    assert any(marker.startswith(TRUTH_ONLY_PROPERTY_PREFIX) for marker in markers)
    assert urns.tag_urn(TAG_PRIVILEGED) in markers

    # And judged in its own mode, a truth export is not a leak: it is privileged
    # by declaration, which is a different statement from being compromised.
    assert compare(list(export.proposals), readback, ExportMode.TRUTH).leak_findings == ()


# ------------------------------------------------------------------ report


def test_the_report_directory_holds_the_documented_files(
    mini_export_dir: Path, tmp_path: Path
) -> None:
    export, result = _roundtrip(mini_export_dir)
    write_roundtrip(tmp_path / "rt", result, export, "http://gms.example.com")
    for name in (
        ROUNDTRIP_REPORT_NAME,
        DISCREPANCIES_NAME,
        LEAK_FINDINGS_NAME,
        PROVENANCE_NAME,
    ):
        assert (tmp_path / "rt" / name).is_file(), name


def test_an_empty_leak_file_is_still_written(mini_export_dir: Path, tmp_path: Path) -> None:
    """ "The probes ran and found nothing" and "the probes never ran" differ."""
    export, result = _roundtrip(mini_export_dir)
    write_roundtrip(tmp_path / "rt", result, export, "http://gms.example.com")
    assert (tmp_path / "rt" / LEAK_FINDINGS_NAME).read_bytes() == b""


def test_the_report_states_the_four_claims_separately(
    mini_export_dir: Path, tmp_path: Path
) -> None:
    export, result = _roundtrip(mini_export_dir)
    report = write_roundtrip(tmp_path / "rt", result, export, "http://gms.example.com")
    assert set(report["claims"]) == {
        "completeness",
        "fidelity",
        "containment",
        "non-leakage",
    }
    assert all(claim["status"] == "pass" for claim in report["claims"].values())
    assert report["roundtrip_schema_version"] == ROUNDTRIP_SCHEMA_VERSION
    assert report["normalization_version"] == NORMALIZATION_VERSION


def test_the_report_names_the_families_it_could_not_scan(
    mini_export_dir: Path, tmp_path: Path
) -> None:
    export, result = _roundtrip(mini_export_dir)
    report = write_roundtrip(tmp_path / "rt", result, export, "http://gms.example.com")
    containment = report["claims"]["containment"]
    assert containment["entity_family_coverage"]["dataset"] == "scanned"
    assert containment["entity_family_coverage"]["container"] == "unavailable"
    assert "opaque GUID" in containment["unavailable_reasons"]["container"]


def test_the_report_records_the_live_support_status(mini_export_dir: Path, tmp_path: Path) -> None:
    """A stored report must never overstate the evidence behind it."""
    export, result = _roundtrip(mini_export_dir)
    report = write_roundtrip(tmp_path / "rt", result, export, "http://gms.example.com")
    assert report["catalogue"]["live_support"].startswith("experimental")


def test_the_report_carries_no_wall_clock_and_is_byte_deterministic(
    mini_export_dir: Path, tmp_path: Path
) -> None:
    export, result = _roundtrip(mini_export_dir)
    first = tmp_path / "a"
    second = tmp_path / "b"
    write_roundtrip(first, result, export, "http://gms.example.com")
    write_roundtrip(second, result, export, "http://gms.example.com")
    for name in (ROUNDTRIP_REPORT_NAME, DISCREPANCIES_NAME, LEAK_FINDINGS_NAME):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_a_token_embedded_in_the_endpoint_never_reaches_the_report(
    mini_export_dir: Path, tmp_path: Path
) -> None:
    from dataswamp_biosystems.adapters.datahub.client import DataHubClient

    export, result = _roundtrip(mini_export_dir)
    endpoint = DataHubClient("https://user:secret-token@gms.example.com/api/gms").endpoint
    write_roundtrip(tmp_path / "rt", result, export, endpoint)
    for path in (tmp_path / "rt").iterdir():
        assert b"secret-token" not in path.read_bytes(), path.name


def test_discrepancy_records_are_written_in_canonical_order(
    mini_export_dir: Path, tmp_path: Path
) -> None:
    export = load_export(mini_export_dir)
    targets = {
        (str(proposal["entityUrn"]), str(proposal["aspectName"]))
        for proposal in export.proposals[:6]
    }
    _, result = _roundtrip(mini_export_dir, FakeGMS(drop=targets))
    write_roundtrip(tmp_path / "rt", result, export, "http://gms.example.com")
    records = [
        json.loads(line)
        for line in (tmp_path / "rt" / DISCREPANCIES_NAME).read_text(encoding="utf-8").splitlines()
    ]
    keys = [
        (record["kind"], record["entity_urn"], record.get("aspect_name", "")) for record in records
    ]
    assert keys == sorted(keys)
    assert len(records) == len(targets)


@pytest.mark.parametrize(
    ("kind", "claim"),
    [
        (DiscrepancyKind.MISSING, "completeness"),
        (DiscrepancyKind.MUTATED, "fidelity"),
        (DiscrepancyKind.EXTRA_ASPECT, "containment"),
    ],
)
def test_each_fault_fails_only_its_own_claim(
    mini_export_dir: Path, tmp_path: Path, kind: DiscrepancyKind, claim: str
) -> None:
    """Four claims, not one opaque verdict: a fault must not smear across them."""
    export = load_export(mini_export_dir)
    proposal = next(p for p in export.proposals if p["aspectName"] == "datasetProperties")
    urn = str(proposal["entityUrn"])
    state = FakeGMS()
    if kind is DiscrepancyKind.MISSING:
        state.drop = {(urn, "datasetProperties")}
    elif kind is DiscrepancyKind.MUTATED:
        corrupted = json.loads(json.dumps(proposal["aspect"]["json"])) | {"name": "changed"}
        state.mutate = {(urn, "datasetProperties"): corrupted}
    else:
        state.inject = {(urn, "institutionalMemory"): {"elements": []}}

    _, result = _roundtrip(mini_export_dir, state)
    report = write_roundtrip(tmp_path / "rt", result, export, "http://gms.example.com")
    failed = {name for name, value in report["claims"].items() if value["status"] == "fail"}
    assert failed == {claim}


# ------------------------------------------------------ the real emitted export


def test_the_real_observed_export_round_trips_cleanly(observed_export_dir: Path) -> None:
    """The contract, over the artefact the project actually publishes."""
    _, result = _roundtrip(observed_export_dir)
    assert result.clean, [item.as_record() for item in result.discrepancies[:5]]
    assert result.counts["sent"] == result.counts["matched"]


def test_the_real_observed_export_leaves_no_truth_marker(
    observed_export_dir: Path, tmp_path: Path
) -> None:
    export, result = _roundtrip(observed_export_dir)
    report = write_roundtrip(tmp_path / "rt", result, export, "http://gms.example.com")
    assert result.leak_findings == ()
    assert report["claims"]["non-leakage"]["status"] == "pass"
    assert report["claims"]["non-leakage"]["applicable"] is True
