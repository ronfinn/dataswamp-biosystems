"""The round-trip contract, against a *real* DataHub Quickstart instance.

Everything else in this directory proves the contract offline against a fake
GMS. That is what makes the contract cheap to test and safe to trust, but a
fake GMS is a model of DataHub written by the same person who wrote the
adapter, so it cannot discover that the model is wrong. These tests exist to
discover exactly that, and nothing else.

They are **deselected by default** (``-m "not live"`` in ``pyproject.toml``) and
skip outright when ``DATAHUB_GMS_URL`` is unset, so an ordinary ``pytest`` run
never collects them and an explicit ``-m live`` run without a server says why
rather than erroring. They are exercised by the ``live-datahub`` workflow,
which stands up a pinned Quickstart, and by anyone who points
``DATAHUB_GMS_URL`` at their own throwaway instance.

The suite is deliberately small. It re-asserts only the claims whose truth
depends on the *server* — reachability, retrievability of every emitted aspect
including the timeseries one, semantic fidelity under normalization, idempotent
upsert, extra-entity scanning and observed non-leakage. Perturbation coverage
stays offline where faults can be planted precisely; planting them in a real
catalogue would test the plant, not the differ.

One negative control is live-specific and load-bearing:
:func:`test_a_withheld_proposal_is_reported_as_an_extra_aspect`. A comparison of
nothing against nothing is also "clean", so a suite of green assertions against
an empty catalogue would look identical to success. That test proves the
readback is genuinely returning the server's data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.datahub.client import (
    GMS_URL_ENV,
    TIMESERIES_ASPECTS,
    DataHubClient,
)
from dataswamp_biosystems.adapters.datahub.ingest import (
    LoadedExport,
    execute_ingestion,
    load_export,
    plan_ingestion,
)
from dataswamp_biosystems.adapters.datahub.readback import read_back
from dataswamp_biosystems.adapters.datahub.report import write_roundtrip
from dataswamp_biosystems.adapters.datahub.roundtrip import (
    SCANNABLE_FAMILIES,
    DiscrepancyKind,
    RoundTripResult,
    compare,
)

pytestmark = pytest.mark.live

# The workflow points this at the export it actually transmitted. Without it the
# session fixture emits an identical one, since the export is deterministic —
# but pointing at the transmitted bytes is what makes the test a statement about
# *that* ingestion rather than about an equivalent one.
EXPORT_DIR_ENV = "DATASWAMP_LIVE_EXPORT_DIR"


@pytest.fixture(scope="module")
def live_client() -> Iterator[DataHubClient]:
    """A client for the live GMS, or a skip explaining that there isn't one."""
    if not os.environ.get(GMS_URL_ENV):
        pytest.skip(f"no live catalogue: {GMS_URL_ENV} is unset")
    yield DataHubClient.from_environment()


@pytest.fixture(scope="module")
def live_export(observed_export_dir: Path) -> LoadedExport:
    """The emitted observed export under test — the live path's only input."""
    override = os.environ.get(EXPORT_DIR_ENV)
    return load_export(Path(override) if override else observed_export_dir)


@pytest.fixture(scope="module")
def ingested(live_client: DataHubClient, live_export: LoadedExport) -> LoadedExport:
    """Transmit the export. Every proposal is an UPSERT, so this converges.

    The workflow has already ingested the same bytes through the CLI; doing it
    again here is not redundant book-keeping but the idempotence claim being
    exercised as a precondition of everything below.
    """
    execute_ingestion(plan_ingestion(live_export), live_client)
    return live_export


@pytest.fixture(scope="module")
def live_result(ingested: LoadedExport, live_client: DataHubClient) -> RoundTripResult:
    readback = read_back(ingested, live_client)
    return compare(list(ingested.proposals), readback, ingested.mode)


# ------------------------------------------------------------- the server


def test_the_live_catalogue_is_reachable_and_holds_what_we_sent(
    live_client: DataHubClient, ingested: LoadedExport
) -> None:
    """The cheapest possible failure, named clearly, before anything subtle."""
    first = ingested.proposals[0]
    retrieved = live_client.fetch_aspects(str(first["entityType"]), str(first["entityUrn"]))
    assert retrieved, f"live GMS returned no aspects for {first['entityUrn']}"


def test_the_export_is_not_empty(ingested: LoadedExport) -> None:
    """Guards every assertion below against being vacuously true."""
    assert len(ingested.proposals) > 100


# --------------------------------------------------------- the four claims


def test_the_real_observed_export_round_trips_cleanly(live_result: RoundTripResult) -> None:
    """The whole point of the job: a real DataHub release, zero discrepancies."""
    assert live_result.clean, [item.as_record() for item in live_result.discrepancies[:10]]


def test_every_emitted_aspect_is_retrievable(
    live_result: RoundTripResult, ingested: LoadedExport
) -> None:
    """Completeness, over all emitted aspects rather than a hand-picked subset."""
    emitted = {(str(p["entityUrn"]), str(p["aspectName"])) for p in ingested.proposals}
    assert set(live_result.sent_keys) == emitted
    assert live_result.counts["matched"] == live_result.counts["sent"] == len(emitted)
    assert not live_result.of_kind(DiscrepancyKind.MISSING)


def test_the_timeseries_aspect_survives_its_own_retrieval_path(
    live_result: RoundTripResult,
) -> None:
    """Timeseries aspects are stored and read differently; assert that explicitly.

    A real GMS is the only thing that can prove the separate timeseries path is
    right, because the fake serves both from one store.
    """
    retrieved = {aspect for _, aspect in live_result.sent_keys}
    assert TIMESERIES_ASPECTS & retrieved, f"expected one of {sorted(TIMESERIES_ASPECTS)}"
    assert not [
        item for item in live_result.discrepancies if item.aspect_name in TIMESERIES_ASPECTS
    ]


def test_no_aspect_is_semantically_mutated(live_result: RoundTripResult) -> None:
    """Fidelity under the versioned normalization contract, against a real store.

    If this fails, the finding is a genuine one and belongs in triage — not in
    the normalization ignore list.
    """
    mutated = live_result.of_kind(DiscrepancyKind.MUTATED)
    assert not mutated, [item.as_record() for item in mutated[:10]]


def test_the_catalogue_holds_no_dataswamp_entity_we_never_sent(
    live_result: RoundTripResult,
) -> None:
    """Containment, and that the scan genuinely ran rather than being skipped."""
    scanned = {family for family, status in live_result.coverage.items() if status == "scanned"}
    assert scanned == {family.entity_type for family in SCANNABLE_FAMILIES}
    assert not live_result.of_kind(DiscrepancyKind.EXTRA_ENTITY)
    assert not live_result.of_kind(DiscrepancyKind.EXTRA_ASPECT)


def test_an_observed_ingestion_leaves_no_ground_truth_in_the_catalogue(
    live_result: RoundTripResult, ingested: LoadedExport, tmp_path: Path
) -> None:
    """Non-leakage, judged on the server's own contents rather than on the file."""
    assert live_result.leak_findings == ()
    report = write_roundtrip(tmp_path / "rt", live_result, ingested, "http://gms.test")
    assert report["claims"]["non-leakage"]["applicable"] is True
    assert report["claims"]["non-leakage"]["status"] == "pass"
    failed = {name for name, claim in report["claims"].items() if claim["status"] != "pass"}
    assert not failed


# ------------------------------------------------------- negative controls


def test_a_second_ingestion_is_idempotent(
    live_client: DataHubClient, ingested: LoadedExport
) -> None:
    """UPSERT semantics against a real store: converge, never duplicate."""
    execute_ingestion(plan_ingestion(ingested), live_client)
    readback = read_back(ingested, live_client)
    result = compare(list(ingested.proposals), readback, ingested.mode)
    assert result.clean, [item.as_record() for item in result.discrepancies[:10]]


def test_a_withheld_proposal_is_reported_as_an_extra_aspect(
    ingested: LoadedExport, live_client: DataHubClient
) -> None:
    """Prove the live readback returns real data, not an empty set.

    Every assertion above would also hold if the server returned nothing and the
    differ compared nothing to nothing. Withholding one proposal from the *sent*
    side of an otherwise identical comparison must therefore make the catalogue
    look like it holds an aspect nobody sent — and must implicate exactly the
    aspect withheld.
    """
    withheld = next(p for p in ingested.proposals if p["aspectName"] == "datasetProperties")
    kept = [p for p in ingested.proposals if p is not withheld]

    readback = read_back(ingested, live_client)
    result = compare(kept, readback, ingested.mode)

    extra = result.of_kind(DiscrepancyKind.EXTRA_ASPECT)
    assert [(item.entity_urn, item.aspect_name) for item in extra] == [
        (str(withheld["entityUrn"]), str(withheld["aspectName"]))
    ]
