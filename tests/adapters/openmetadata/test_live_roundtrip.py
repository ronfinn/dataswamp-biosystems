"""Round-trip comparison, proved by perturbation.

A differ that has only ever seen matching inputs is not evidence of anything.
Every test here starts from a *clean, successful* ingestion of the real emitted
export into the strict fake, breaks exactly one thing, and asserts that the
break is caught — with the right kind, at the right path, failing the right
claim and only that claim.

The negative controls matter as much as the positives:

* a foreign entity is planted and must **not** be reported;
* a truth marker is planted and the leak probe must fire, so "no leaks found" is
  known to mean something;
* an adjacent field beside every normalized one is mutated and must still be
  seen, so forgiveness is known to be narrow;
* the whole comparison is re-run against an emptied readback, so a clean
  empty-versus-empty result cannot masquerade as success.
"""

from __future__ import annotations

import dataclasses

import pytest

from dataswamp_biosystems.adapters.openmetadata import (
    Claim,
    Coverage,
    DiscrepancyKind,
    Readback,
    compare,
)
from dataswamp_biosystems.adapters.openmetadata.fqn import tag_fqn
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
)

from .conftest import LiveFixture

# A container that exists in every emitted observed export of the canonical
# bundle, resolved from the export itself rather than hard-coded.


def _a_dataset_container(fixture: LiveFixture) -> str:
    for record in fixture.export.records:
        if record.phase == "dataset-container":
            return record.fqn
    raise AssertionError("the export has no dataset container")


def _a_data_product(fixture: LiveFixture) -> str:
    for record in fixture.export.records:
        if record.phase == "data-product-assets":
            return record.fqn
    raise AssertionError("the export attaches no data-product assets")


def _only_claim_failing(result: object, claim: Claim) -> None:
    """Assert exactly one claim failed, and it is the expected one."""
    failing = {
        candidate
        for candidate in Claim
        if not result.claim_passed(candidate)  # type: ignore[attr-defined]
    }
    assert failing == {claim}, f"expected only {claim.value} to fail, got {failing}"


# ---------------------------------------------------------------------------
# The clean case
# ---------------------------------------------------------------------------


def test_a_clean_round_trip_passes_all_four_claims(om_live: LiveFixture) -> None:
    result = om_live.compare()
    assert result.clean
    for claim in Claim:
        assert result.claim_passed(claim)
    assert result.counts["retrieved_entities"] == result.counts["sent_entities"]
    assert result.counts["sent_entities"] > 100


def test_the_clean_case_actually_compared_something(om_live: LiveFixture) -> None:
    """A load-bearing guard against a vacuously green round-trip."""
    result = om_live.compare()
    assert result.counts["matched_entities"] == result.counts["sent_entities"] > 0
    assert result.counts["sent_custom_properties"] > 0
    assert result.counts["sent_asset_attachments"] > 0
    assert result.counts["sent_lineage_edges"] > 0


def test_an_empty_readback_cannot_masquerade_as_success(om_live: LiveFixture) -> None:
    """The negative control the whole suite rests on.

    If comparison could report "clean" when the catalogue holds nothing, every
    other green result in this file would be worthless.
    """
    result = compare(om_live.export.records, Readback(), om_live.export.mode)
    assert not result.clean
    missing = result.of_kind(DiscrepancyKind.MISSING_ENTITY)
    assert len(missing) == result.counts["sent_entities"]
    assert not result.claim_passed(Claim.COMPLETENESS)


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------


def test_a_missing_entity_fails_completeness_and_names_it(om_live: LiveFixture) -> None:
    fqn = _a_dataset_container(om_live)
    om_live.state.drop.add(("container", fqn))
    result = om_live.compare()
    missing = result.of_kind(DiscrepancyKind.MISSING_ENTITY)
    assert [item.fqn for item in missing] == [fqn]
    assert missing[0].claim is Claim.COMPLETENESS


def test_a_missing_custom_property_fails_completeness(om_live: LiveFixture) -> None:
    name, _ = om_live.state.custom_properties["container"].popitem()
    result = om_live.compare()
    missing = result.of_kind(DiscrepancyKind.MISSING_PROPERTY)
    assert [item.fqn for item in missing] == [f"container.{name}"]


def test_a_missing_asset_attachment_fails_completeness(om_live: LiveFixture) -> None:
    product = _a_data_product(om_live)
    attached = om_live.state.get_assets(product)
    assert attached and attached["data"]
    victim = attached["data"][0]["fullyQualifiedName"]
    om_live.state.drop_assets[product] = [victim]
    result = om_live.compare()
    missing = result.of_kind(DiscrepancyKind.MISSING_RELATIONSHIP)
    assert any(victim in item.detail for item in missing)
    _only_claim_failing(result, Claim.COMPLETENESS)


def test_a_missing_lineage_edge_fails_completeness(om_live: LiveFixture) -> None:
    edge = next(iter(sorted(om_live.state.lineage)))
    pair = (om_live.state.by_id[edge[0]][1], om_live.state.by_id[edge[1]][1])
    om_live.state.drop_lineage.add(pair)
    result = om_live.compare()
    missing = result.of_kind(DiscrepancyKind.MISSING_RELATIONSHIP)
    assert [item.fqn for item in missing] == [f"{pair[0]}->{pair[1]}"]
    _only_claim_failing(result, Claim.COMPLETENESS)


# ---------------------------------------------------------------------------
# Fidelity
# ---------------------------------------------------------------------------


def test_a_mutated_field_is_reported_at_its_exact_path(om_live: LiveFixture) -> None:
    fqn = _a_dataset_container(om_live)
    om_live.state.mutate[("container", fqn)] = {"description": "tampered by the catalogue"}
    result = om_live.compare()
    mutated = result.of_kind(DiscrepancyKind.MUTATED)
    assert [item.fqn for item in mutated] == [fqn]
    paths = {difference.path for difference in mutated[0].differences}
    assert paths == {"description"}
    assert mutated[0].differences[0].retrieved == "tampered by the catalogue"
    _only_claim_failing(result, Claim.FIDELITY)


def test_a_mutated_nested_extension_value_is_reported_at_its_recursive_path(
    om_live: LiveFixture,
) -> None:
    fqn = _a_dataset_container(om_live)
    stored = om_live.state.entities[("container", fqn)]
    extension = dict(stored["extension"])
    extension["dataswampId"] = "wrong-id"
    om_live.state.mutate[("container", fqn)] = {"extension": extension}
    result = om_live.compare()
    mutated = result.of_kind(DiscrepancyKind.MUTATED)
    paths = {difference.path for difference in mutated[0].differences}
    assert paths == {"extension.dataswampId"}


def test_a_reference_pointed_somewhere_else_still_fails_fidelity(om_live: LiveFixture) -> None:
    """Projection changes representation, not value. A wrong target is a mutation."""
    fqn = _a_dataset_container(om_live)
    stored = om_live.state.entities[("container", fqn)]
    elsewhere = dict(stored["service"])
    elsewhere["fullyQualifiedName"] = "somebody-elses-service"
    om_live.state.mutate[("container", fqn)] = {"service": elsewhere}
    result = om_live.compare()
    mutated = result.of_kind(DiscrepancyKind.MUTATED)
    assert [item.fqn for item in mutated] == [fqn]
    assert mutated[0].differences[0].path == "service"
    assert mutated[0].differences[0].retrieved == "somebody-elses-service"


def test_a_dropped_tag_fails_fidelity(om_live: LiveFixture) -> None:
    fqn = _a_dataset_container(om_live)
    stored = om_live.state.entities[("container", fqn)]
    om_live.state.mutate[("container", fqn)] = {"tags": stored["tags"][1:]}
    result = om_live.compare()
    mutated = result.of_kind(DiscrepancyKind.MUTATED)
    assert mutated
    assert any("tags" in difference.path for difference in mutated[0].differences)


def test_the_addressed_fqn_is_asserted_not_assumed(om_live: LiveFixture) -> None:
    """A server answering a different entity must not compare equal."""
    fqn = _a_dataset_container(om_live)
    om_live.state.mutate[("container", fqn)] = {"fullyQualifiedName": "some.other.entity"}
    result = om_live.compare()
    mutated = result.of_kind(DiscrepancyKind.MUTATED)
    assert any(difference.path == "fullyQualifiedName" for difference in mutated[0].differences)


# ---------------------------------------------------------------------------
# Normalization: forgiven, and the paired adjacent mutation still caught
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "forgiven",
    ["id", "href", "version", "updatedAt", "updatedBy", "changeDescription", "deleted"],
)
def test_a_platform_generated_field_is_forgiven(om_live: LiveFixture, forgiven: str) -> None:
    fqn = _a_dataset_container(om_live)
    om_live.state.mutate[("container", fqn)] = {forgiven: "a value the server chose"}
    assert om_live.compare().clean


@pytest.mark.parametrize(
    "adjacent",
    ["description", "displayName", "sourceUrl", "fullPath"],
)
def test_an_adjacent_field_beside_the_forgiven_ones_is_still_caught(
    om_live: LiveFixture, adjacent: str
) -> None:
    """The paired half of every forgiveness rule.

    Forgiving ``id`` must not mean forgiving the field next to it, and this is
    the test that would fail if the ignore list were ever widened by path prefix
    rather than by exact path.
    """
    fqn = _a_dataset_container(om_live)
    om_live.state.mutate[("container", fqn)] = {"id": "forgiven", adjacent: "not forgiven"}
    result = om_live.compare()
    assert not result.claim_passed(Claim.FIDELITY) or not result.claim_passed(Claim.CONTAINMENT)
    reported = {
        difference.path
        for item in result.discrepancies
        if item.fqn == fqn
        for difference in item.differences
    }
    assert adjacent in reported


def test_an_unknown_server_added_field_is_a_discrepancy_by_default(
    om_live: LiveFixture,
) -> None:
    """Suspicion is the default; forgiveness is opt-in and justified."""
    fqn = _a_dataset_container(om_live)
    om_live.state.mutate[("container", fqn)] = {"somethingNobodySent": 42}
    result = om_live.compare()
    extra = result.of_kind(DiscrepancyKind.EXTRA_FIELD)
    assert [item.fqn for item in extra] == [fqn]
    assert extra[0].differences[0].path == "somethingNobodySent"
    _only_claim_failing(result, Claim.CONTAINMENT)


def test_a_server_denormalized_tag_label_field_is_forgiven_additively(
    om_live: LiveFixture,
) -> None:
    fqn = _a_dataset_container(om_live)
    stored = om_live.state.entities[("container", fqn)]
    decorated = [dict(label, description="copied from the Tag") for label in stored["tags"]]
    om_live.state.mutate[("container", fqn)] = {"tags": decorated}
    assert om_live.compare().clean


def test_a_mutated_tag_fqn_beside_a_forgiven_label_field_is_still_caught(
    om_live: LiveFixture,
) -> None:
    fqn = _a_dataset_container(om_live)
    stored = om_live.state.entities[("container", fqn)]
    decorated = [dict(label, description="copied") for label in stored["tags"]]
    decorated[0]["tagFQN"] = "dataswamp.something-else"
    om_live.state.mutate[("container", fqn)] = {"tags": decorated}
    assert not om_live.compare().claim_passed(Claim.FIDELITY)


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------


def test_an_extra_dataswamp_container_is_reported(om_live: LiveFixture) -> None:
    """Ownership here is structural — the fake's `service` filter scopes it."""
    intruder = "dataswamp-biosystems.planted-study"
    om_live.state.put_entity(
        "container", {"name": "planted-study", "service": "dataswamp-biosystems"}
    )
    result = om_live.compare()
    extra = result.of_kind(DiscrepancyKind.EXTRA_ENTITY)
    assert [item.fqn for item in extra] == [intruder]
    _only_claim_failing(result, Claim.CONTAINMENT)


def test_a_foreign_entity_is_never_reported_as_a_dataswamp_extra(
    om_live: LiveFixture,
) -> None:
    """Somebody else's catalogue content is not this benchmark's business."""
    om_live.state.put_entity(
        "storageService", {"name": "acme-warehouse", "serviceType": "CustomStorage"}
    )
    om_live.state.put_entity("container", {"name": "acme-data", "service": "acme-warehouse"})
    om_live.state.put_entity(
        "domain", {"name": "acme-sales", "description": "d", "domainType": "Source-aligned"}
    )
    result = om_live.compare()
    assert result.clean, [item.as_record() for item in result.discrepancies]


def test_an_extra_lineage_edge_is_reported(om_live: LiveFixture) -> None:
    records = [r for r in om_live.export.records if r.phase == "dataset-container"]
    planted = (records[0].fqn, records[-1].fqn)
    om_live.state.inject_lineage.add(planted)
    result = om_live.compare()
    extra = result.of_kind(DiscrepancyKind.EXTRA_RELATIONSHIP)
    assert any(item.fqn == f"{planted[0]}->{planted[1]}" for item in extra)


def test_an_extra_asset_attachment_is_reported(om_live: LiveFixture) -> None:
    product = _a_data_product(om_live)
    om_live.state.inject_assets[product] = ["dataswamp-biosystems.study-x.uninvited"]
    result = om_live.compare()
    extra = result.of_kind(DiscrepancyKind.EXTRA_RELATIONSHIP)
    assert any("uninvited" in item.detail for item in extra)
    _only_claim_failing(result, Claim.CONTAINMENT)


def test_an_extra_dataswamp_namespaced_custom_property_is_reported(
    om_live: LiveFixture,
) -> None:
    om_live.state.inject_properties["container"] = ["dataswampPlanted"]
    result = om_live.compare()
    assert any(
        item.fqn == "container.dataswampPlanted"
        for item in result.of_kind(DiscrepancyKind.EXTRA_FIELD)
    )


def test_containment_coverage_is_declared_per_family(om_live: LiveFixture) -> None:
    coverage = om_live.compare().coverage
    assert coverage["container"] == Coverage.PROVABLE.value
    assert coverage["tag"] == Coverage.PROVABLE.value
    assert coverage["domain"] == Coverage.NAMESPACE.value


def test_coverage_is_reported_unavailable_when_nothing_was_enumerated(
    om_live: LiveFixture,
) -> None:
    """ "The scan did not run" and "the scan was clean" must not look alike."""
    readback = dataclasses.replace(om_live.read(), scanned_families=frozenset())
    result = compare(om_live.export.records, readback, om_live.export.mode)
    assert set(result.coverage.values()) == {Coverage.UNAVAILABLE.value}
    assert not result.of_kind(DiscrepancyKind.EXTRA_ENTITY)


# ---------------------------------------------------------------------------
# Observed-mode non-leakage
# ---------------------------------------------------------------------------


def test_an_observed_round_trip_finds_no_truth_markers(om_live: LiveFixture) -> None:
    assert om_live.compare().leak_findings == ()


def test_a_planted_truth_extension_key_makes_the_probe_fire(om_live: LiveFixture) -> None:
    fqn = _a_dataset_container(om_live)
    stored = om_live.state.entities[("container", fqn)]
    leaked = dict(stored["extension"], **{f"{TRUTH_ONLY_PROPERTY_PREFIX}Export": "true"})
    om_live.state.mutate[("container", fqn)] = {"extension": leaked}
    result = om_live.compare()
    assert [finding.probe for finding in result.leak_findings] == ["truth-only-extension-key"]
    assert not result.claim_passed(Claim.NON_LEAKAGE)


def test_a_planted_privileged_tag_makes_the_probe_fire(om_live: LiveFixture) -> None:
    fqn = _a_dataset_container(om_live)
    stored = om_live.state.entities[("container", fqn)]
    privileged = {
        "tagFQN": tag_fqn(TAG_PRIVILEGED),
        "source": "Classification",
        "labelType": "Manual",
        "state": "Confirmed",
    }
    om_live.state.mutate[("container", fqn)] = {"tags": [*stored["tags"], privileged]}
    result = om_live.compare()
    assert "privileged-truth-tag" in {finding.probe for finding in result.leak_findings}


def test_a_planted_truth_custom_property_makes_the_probe_fire(om_live: LiveFixture) -> None:
    om_live.state.inject_properties["container"] = [f"{TRUTH_ONLY_PROPERTY_PREFIX}Export"]
    result = om_live.compare()
    assert "truth-only-custom-property-registered" in {
        finding.probe for finding in result.leak_findings
    }


def test_a_real_truth_export_trips_every_leak_probe(om_live_truth: LiveFixture) -> None:
    """The negative control: a genuinely privileged catalogue must be detected.

    The export is ingested in truth mode and then judged as though it were an
    observed one. If the probes could not tell the difference, "no leaks found"
    on an observed run would mean nothing.
    """
    readback = om_live_truth.read()
    result = compare(om_live_truth.export.records, readback, ExportMode.OBSERVED)
    probes = {finding.probe for finding in result.leak_findings}
    assert probes == {
        "truth-only-extension-key",
        "privileged-truth-tag",
        "truth-only-custom-property-registered",
    }
    assert not result.claim_passed(Claim.NON_LEAKAGE)


def test_truth_mode_does_not_report_its_own_markers_as_leaks(om_live_truth: LiveFixture) -> None:
    """A privileged export is *meant* to carry them; the probe is observed-only."""
    result = compare(om_live_truth.export.records, om_live_truth.read(), ExportMode.TRUTH)
    assert result.leak_findings == ()
