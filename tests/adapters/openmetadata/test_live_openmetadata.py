"""The round-trip contract, against a *real* pinned OpenMetadata server.

Everything else in this directory proves the contract offline: the emitted plan
is validated against upstream's own vendored JSON schemas, and the live path is
replayed into ``fake_om.py``, which derives its routes from upstream's resource
classes rather than from our client so that it is able to disagree with us. That
is a great deal of evidence, and none of it is evidence about a running server.
A payload can satisfy every schema and still be refused. A fake can be green
while the model of OpenMetadata encoded in it is wrong — that is exactly how the
DataHub rest.li/OpenAPI dialect mismatch survived 111 offline tests. These tests
exist to find that out, and nothing else.

They are **deselected by default** (``-m "not live and not live_openmetadata"``
in ``pyproject.toml``) and skip outright when ``OPENMETADATA_HOST_PORT`` is
unset, so an ordinary ``pytest`` run never collects them and an explicit
``-m live_openmetadata`` run without a server says why rather than erroring.
They never guess at a local server: no default host, no fallback port.

The suite re-asserts only what depends on the *server*. Perturbation coverage
stays offline, where a fault can be planted precisely; planting one in a real
catalogue would test the plant rather than the differ. What is here instead is
per-family materialization — every supported entity family read back by its
deterministic FQN — and three load-bearing negative controls, because a
comparison of nothing against nothing is also "clean" and a suite of green
assertions against an empty catalogue would look identical to success.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.openmetadata import (
    Claim,
    Coverage,
    DiscrepancyKind,
    LoadedExport,
    OpenMetadataClient,
    Readback,
    RoundTripResult,
    compare,
    execute_ingestion,
    load_export,
    plan_ingestion,
    read_back,
)
from dataswamp_biosystems.adapters.openmetadata.client import HOST_PORT_ENV
from dataswamp_biosystems.adapters.openmetadata.fqn import NAMESPACE, SERVICE_NAME
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
)
from dataswamp_biosystems.adapters.openmetadata.report import write_roundtrip
from dataswamp_biosystems.adapters.openmetadata.roundtrip import CONTAINMENT_FAMILIES

pytestmark = pytest.mark.live_openmetadata

# The workflow points this at the export it actually transmitted. Without it the
# session fixture emits an identical one, since the export is deterministic —
# but pointing at the transmitted bytes is what makes the test a statement about
# *that* ingestion rather than about an equivalent one.
EXPORT_DIR_ENV = "DATASWAMP_LIVE_OM_EXPORT_DIR"

# Every phase the adapter is expected to materialize on a real server. Asserting
# the set rather than a hand-picked sample is what stops a family from quietly
# dropping out of the canary's coverage: a phase that stops being emitted fails
# `test_every_supported_entity_family_materializes` instead of going unnoticed.
EXPECTED_ENTITY_PHASES = frozenset(
    {
        "classification",
        "tag",
        "glossary",
        "glossary-term",
        "team",
        "domain",
        "storage-service",
        "study-container",
        "dataset-container",
        "file-container",
        "data-product",
    }
)


@pytest.fixture(scope="module")
def live_client() -> Iterator[OpenMetadataClient]:
    """A client for the live server, or a skip explaining that there isn't one."""
    if not os.environ.get(HOST_PORT_ENV):
        pytest.skip(f"no live catalogue: {HOST_PORT_ENV} is unset")
    yield OpenMetadataClient.from_environment()


@pytest.fixture(scope="module")
def live_export(om_observed_export_dir: Path) -> LoadedExport:
    """The emitted observed export under test — the live path's only input."""
    override = os.environ.get(EXPORT_DIR_ENV)
    return load_export(Path(override) if override else om_observed_export_dir)


@pytest.fixture(scope="module")
def ingested(live_client: OpenMetadataClient, live_export: LoadedExport) -> LoadedExport:
    """Replay the export in its emitted order.

    The workflow has already ingested the same bytes through the CLI; doing it
    again here is not redundant book-keeping but the idempotence claim being
    exercised as a precondition of everything below.
    """
    execute_ingestion(plan_ingestion(live_export), live_client)
    return live_export


@pytest.fixture(scope="module")
def live_readback(ingested: LoadedExport, live_client: OpenMetadataClient) -> Readback:
    return read_back(ingested, live_client)


@pytest.fixture(scope="module")
def live_result(ingested: LoadedExport, live_readback: Readback) -> RoundTripResult:
    return compare(ingested.records, live_readback, ingested.mode)


def _records_of(export: LoadedExport, phase: str) -> list[object]:
    return [record for record in export.records if record.phase == phase]


# ------------------------------------------------------------------ the server


def test_the_live_catalogue_is_reachable_and_holds_what_we_sent(
    live_client: OpenMetadataClient, ingested: LoadedExport
) -> None:
    """The cheapest possible failure, named clearly, before anything subtle."""
    retrieved = live_client.get_by_name("storageService", SERVICE_NAME)
    assert retrieved, f"the live server returned nothing for storageService {SERVICE_NAME}"
    assert retrieved.get("fullyQualifiedName") == SERVICE_NAME


def test_the_export_is_not_empty(ingested: LoadedExport) -> None:
    """Guards every assertion below against being vacuously true."""
    assert len(ingested.records) > 100
    assert not ingested.privileged


# ------------------------------------------------------------- the four claims


def test_the_real_observed_export_round_trips_cleanly(live_result: RoundTripResult) -> None:
    """The whole point of the job: a real OpenMetadata release, zero findings."""
    assert live_result.clean, [item.as_record() for item in live_result.discrepancies[:10]]


def test_each_claim_passes_independently(live_result: RoundTripResult) -> None:
    """Four claims, judged separately — never collapsed into one success flag."""
    failing = {claim.value for claim in Claim if not live_result.claim_passed(claim)}
    assert not failing, f"claims failing: {sorted(failing)}"


def test_completeness_covers_every_emitted_entity(
    live_result: RoundTripResult, ingested: LoadedExport
) -> None:
    """Completeness, over everything emitted rather than a hand-picked subset."""
    assert live_result.counts["matched_entities"] == live_result.counts["sent_entities"] > 0
    assert live_result.counts["retrieved_entities"] == live_result.counts["sent_entities"]
    assert not live_result.of_kind(DiscrepancyKind.MISSING_ENTITY)
    assert not live_result.of_kind(DiscrepancyKind.MISSING_PROPERTY)
    assert not live_result.of_kind(DiscrepancyKind.MISSING_RELATIONSHIP)


def test_no_entity_is_semantically_mutated(live_result: RoundTripResult) -> None:
    """Fidelity under the versioned normalization contract, against a real store.

    If this fails, the finding is a genuine one and belongs in A/B/C/D triage —
    not in the normalization forgiveness list. The question to ask first is
    whether DataSwamp sent a value at that exact path; if it did and the server
    changed it, that is not a normalization candidate under any circumstances.
    """
    mutated = live_result.of_kind(DiscrepancyKind.MUTATED)
    assert not mutated, [item.as_record() for item in mutated[:10]]


def test_the_catalogue_holds_no_dataswamp_entity_we_never_sent(
    live_result: RoundTripResult,
) -> None:
    """Containment, and that the scan genuinely ran rather than being skipped.

    Coverage is asserted per family and against each family's *declared* value,
    because it is deliberately not uniform: ``provable`` where a server-side
    filter makes ownership structural, ``namespace-prefix`` where it rests on
    the reserved FQN prefix.
    """
    expected = {
        family.entity_type: family.coverage.value
        for family in CONTAINMENT_FAMILIES
        if family.coverage is not Coverage.UNAVAILABLE
    }
    assert live_result.coverage == expected
    assert not live_result.of_kind(DiscrepancyKind.EXTRA_ENTITY)
    assert not live_result.of_kind(DiscrepancyKind.EXTRA_FIELD)
    assert not live_result.of_kind(DiscrepancyKind.EXTRA_RELATIONSHIP)


def test_an_observed_ingestion_leaves_no_ground_truth_in_the_catalogue(
    live_result: RoundTripResult, ingested: LoadedExport, live_readback: Readback, tmp_path: Path
) -> None:
    """Non-leakage, judged on the server's own contents rather than on the file."""
    assert live_result.leak_findings == ()

    # The probes use only markers the export contract itself defines. Asserting
    # their absence directly, over the documents the server returned, is a check
    # on the readback as well as on the export.
    for document in live_readback.entities.values():
        if document is None:
            continue
        rendered = repr(document)
        assert TRUTH_ONLY_PROPERTY_PREFIX not in rendered
        assert TAG_PRIVILEGED not in rendered

    report = write_roundtrip(tmp_path / "rt", live_result, ingested)
    failed = {name for name, claim in report["claims"].items() if claim["status"] != "pass"}
    assert not failed
    assert report["claims"]["non-leakage"]["applicable"] is True


# -------------------------------------------------- per-family materialization


def test_every_supported_entity_family_materializes(
    ingested: LoadedExport, live_readback: Readback
) -> None:
    """Each supported family read back by its deterministic FQN, on a real server.

    The families are those the adapter maps: StorageService, the three Container
    levels, Domain, DataProduct, Team, Glossary, GlossaryTerm, Classification and
    Tag. Nothing here fabricates a Table, Column, Database, Pipeline or test
    entity, because DataSwamp holds no honest fact that would justify one.
    """
    emitted_phases = {record.phase for record in ingested.records}
    assert emitted_phases >= EXPECTED_ENTITY_PHASES, EXPECTED_ENTITY_PHASES - emitted_phases

    for phase in sorted(EXPECTED_ENTITY_PHASES):
        records = _records_of(ingested, phase)
        assert records, f"the export emitted no {phase} record"
        for record in records:
            key = (record.entity_type, record.fqn)  # type: ignore[attr-defined]
            assert key in live_readback.entities, f"{phase}: {key} was never read back"
            assert live_readback.entities[key] is not None, f"{phase}: server has no {key[1]}"


def test_the_container_hierarchy_survives_with_its_parents_intact(
    ingested: LoadedExport, live_readback: Readback
) -> None:
    """Nested Containers, on the server, with the right parent — not merely present.

    A hierarchical FQN is a claim about structure. A server that stored every
    container flat would satisfy every completeness assertion above.
    """
    checked = 0
    for phase in ("study-container", "dataset-container", "file-container"):
        for record in _records_of(ingested, phase):
            document = live_readback.entities[(record.entity_type, record.fqn)]  # type: ignore[attr-defined]
            assert document is not None
            fqn = str(document["fullyQualifiedName"])
            assert fqn.startswith(f"{SERVICE_NAME}.")
            if phase != "study-container":
                parent = document.get("parent")
                assert parent, f"{fqn} lost its parent container"
                assert fqn.startswith(f"{parent['fullyQualifiedName']}.")
            checked += 1
    assert checked > 0


def test_exact_custom_property_values_survive_readback(
    ingested: LoadedExport, live_result: RoundTripResult, live_readback: Readback
) -> None:
    """Custom properties are where DataSwamp's governance facts live.

    They are registered against an entity type and then carried in each entity's
    ``extension``. Both halves have to survive: the registration and the values.
    """
    registered = _records_of(ingested, "custom-property")
    assert registered
    for entity_type, properties in live_readback.custom_properties.items():
        assert properties, f"{entity_type} has no custom properties registered"
    assert live_result.counts["sent_custom_properties"] > 0
    assert not [
        item for item in live_result.discrepancies if item.kind is DiscrepancyKind.MISSING_PROPERTY
    ]


def test_owner_domain_and_glossary_references_survive(
    ingested: LoadedExport, live_readback: Readback
) -> None:
    """The three reference kinds a UUID-keyed API could plausibly lose.

    ``owners`` is an EntityReference list the client resolves by FQN; ``domain``
    and glossary term parentage are carried inline. All three are re-read from
    the server rather than trusted from the write response.
    """
    owned = 0
    for record in _records_of(ingested, "dataset-container"):
        document = live_readback.entities[(record.entity_type, record.fqn)]  # type: ignore[attr-defined]
        assert document is not None
        for owner in document.get("owners") or []:
            assert str(owner["fullyQualifiedName"]).startswith(NAMESPACE)
            owned += 1
        if domain := document.get("domain"):
            assert str(domain["fullyQualifiedName"]).startswith(NAMESPACE)
    assert owned > 0, "no dataset container came back with an owner"

    for record in _records_of(ingested, "glossary-term"):
        document = live_readback.entities[(record.entity_type, record.fqn)]  # type: ignore[attr-defined]
        assert document is not None
        assert str(document["fullyQualifiedName"]).startswith(f"{NAMESPACE}-")


def test_data_product_identity_and_asset_attachments_survive(
    ingested: LoadedExport, live_readback: Readback
) -> None:
    """The correction #37 made, verified against what the server actually stores.

    A DataProduct's identity is a root-level namespaced FQN, and its assets are
    attached through a dedicated endpoint rather than carried in the create body.
    Both were wrong before #37 and both were green against the fake at the time,
    which is precisely why they are asserted here against a real server.
    """
    products = _records_of(ingested, "data-product")
    assert products
    for record in products:
        document = live_readback.entities[(record.entity_type, record.fqn)]  # type: ignore[attr-defined]
        assert document is not None
        assert document["fullyQualifiedName"] == record.fqn  # type: ignore[attr-defined]
        assert str(record.fqn).startswith(f"{NAMESPACE}-")  # type: ignore[attr-defined]

    attachments = _records_of(ingested, "data-product-assets")
    assert attachments
    for record in attachments:
        assets = live_readback.data_product_assets.get(record.fqn)  # type: ignore[attr-defined]
        assert assets, f"{record.fqn} came back with no attached assets"  # type: ignore[attr-defined]


def test_the_container_side_of_an_attachment_is_visible_as_the_server_reports_it(
    ingested: LoadedExport, live_result: RoundTripResult
) -> None:
    """The reverse ``Container.dataProducts`` edge, judged by the comparison.

    Attaching an asset to a DataProduct is expected to surface on the container
    too. Whether it does is a server behaviour, so the expectation is expressed
    in the comparison rather than restated here — this test asserts that the
    comparison found no disagreement about it, which is the honest form of the
    claim.
    """
    assert live_result.counts["sent_asset_attachments"] > 0
    relationship_faults = [
        item
        for item in live_result.discrepancies
        if item.kind in {DiscrepancyKind.MISSING_RELATIONSHIP, DiscrepancyKind.EXTRA_RELATIONSHIP}
    ]
    assert not relationship_faults, [item.as_record() for item in relationship_faults[:10]]


def test_dataset_lineage_survives(ingested: LoadedExport, live_readback: Readback) -> None:
    """Lineage edges are written through their own endpoint and read through another."""
    edges = _records_of(ingested, "lineage")
    assert edges
    assert live_readback.lineage_edges, "the server reported no lineage edges at all"


# ------------------------------------------------------------ negative controls
#
# Three, because the failure this job most needs to rule out is not a wrong
# value but a vacuous green: an empty readback compares clean against an empty
# expectation, and every assertion above would still pass.


def test_a_second_ingestion_is_idempotent(
    live_client: OpenMetadataClient, ingested: LoadedExport
) -> None:
    """Replaying the same plan converges rather than duplicating or conflicting."""
    execute_ingestion(plan_ingestion(ingested), live_client)
    result = compare(ingested.records, read_back(ingested, live_client), ingested.mode)
    assert result.clean, [item.as_record() for item in result.discrepancies[:10]]


def test_a_withheld_entity_is_reported_as_an_extra(
    ingested: LoadedExport, live_readback: Readback
) -> None:
    """Prove the live readback returns real data, not an empty set.

    Withholding one container from the *sent* side of an otherwise identical
    comparison must make the catalogue look like it holds an entity nobody sent
    — and must implicate exactly the container withheld. If the readback were
    empty, or the containment scan silently skipped, this would find nothing.
    """
    withheld = _records_of(ingested, "dataset-container")[0]
    kept = [record for record in ingested.records if record is not withheld]

    result = compare(tuple(kept), live_readback, ingested.mode)

    extra = result.of_kind(DiscrepancyKind.EXTRA_ENTITY)
    assert [item.fqn for item in extra] == [withheld.fqn]  # type: ignore[attr-defined]
    assert not result.claim_passed(Claim.CONTAINMENT)


def test_a_mutated_expectation_is_reported_against_the_real_readback(
    ingested: LoadedExport, live_readback: Readback
) -> None:
    """Prove the differ compares field values, not merely entity existence.

    One field of one *expected* entity is changed to something the server was
    never sent. The real readback must therefore disagree with it, at that exact
    path, failing fidelity and nothing else. The live server is left untouched:
    perturbing it would pollute every assertion that follows.
    """
    target = _records_of(ingested, "dataset-container")[0]
    create = dict(target.create or {})  # type: ignore[attr-defined]
    assert "description" in create, "expected a dataset container to carry a description"
    perturbed = dataclasses.replace(
        target,  # type: ignore[arg-type]
        create={**create, "description": "a description the server was never sent"},
    )
    records = tuple(perturbed if record is target else record for record in ingested.records)

    result = compare(records, live_readback, ingested.mode)

    mutated = result.of_kind(DiscrepancyKind.MUTATED)
    assert [item.fqn for item in mutated] == [target.fqn]  # type: ignore[attr-defined]
    assert not result.claim_passed(Claim.FIDELITY)
    assert result.claim_passed(Claim.COMPLETENESS)


# Last in the file on purpose: it is the only test here that writes something to
# the live server which the export did not send, and every assertion above
# should be judged against a catalogue holding only DataSwamp's own entities.
def test_a_foreign_entity_is_never_accused_of_being_a_dataswamp_extra(
    live_client: OpenMetadataClient, ingested: LoadedExport
) -> None:
    """Somebody else's catalogue entity is somebody else's, not a DataSwamp extra.

    Containment must be able to say "this is not mine" as confidently as it says
    "this is missing". A real shared catalogue is full of entities DataSwamp
    never sent; reporting them would make the claim useless and the report
    alarming. So a genuinely foreign StorageService is created here — outside
    every family's ownership rule — and the comparison is re-run.
    """
    foreign = "not-dataswamp-live-canary"
    live_client.create_or_update(
        "storageService",
        {
            "name": foreign,
            "serviceType": "CustomStorage",
            "description": "A foreign service, planted by the live canary.",
            "connection": {"config": {"type": "CustomStorage"}},
        },
    )
    assert live_client.get_by_name("storageService", foreign), "the foreign service was not created"

    result = compare(ingested.records, read_back(ingested, live_client), ingested.mode)

    accused = [item.fqn for item in result.of_kind(DiscrepancyKind.EXTRA_ENTITY)]
    assert foreign not in accused
    assert not accused, accused
    assert result.claim_passed(Claim.CONTAINMENT)
