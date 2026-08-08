"""The normalization contract, and the guard rails that keep it narrow.

Every ignored server-owned field gets two tests: one showing that the field is
normalized away, and a **paired** one showing that an adjacent field which is
*not* on the list still surfaces as a difference. The pairing is the point. A
test that only proves forgiveness would pass equally well if normalization
deleted the entire payload.
"""

from __future__ import annotations

from pathlib import Path

from dataswamp_biosystems.adapters.datahub import urns
from dataswamp_biosystems.adapters.datahub.ingest import (
    execute_ingestion,
    load_export,
    plan_ingestion,
)
from dataswamp_biosystems.adapters.datahub.normalize import (
    KEY_ASPECT_JUSTIFICATION,
    NORMALIZATION_VERSION,
    SERVER_ADDED_FIELDS,
    SERVER_DERIVED_ASPECTS,
    SERVER_OWNED_FIELDS,
    UNORDERED_FIELDS,
    is_server_derived_aspect,
    is_unordered,
    normalization_contract,
    normalize_aspect,
)
from dataswamp_biosystems.adapters.datahub.readback import read_back
from dataswamp_biosystems.adapters.datahub.roundtrip import (
    DiscrepancyKind,
    RoundTripResult,
    _diff,
    compare,
    forgive_server_additions,
)

from .fake_gms import FakeGMS, FakeGMSServer


def _filtered(sent: object, retrieved: object, aspect_name: str) -> list:
    """Diff two payloads exactly as `compare` does, forgiveness included."""
    return forgive_server_additions(_diff(sent, retrieved, "", aspect_name), aspect_name)


def _roundtrip_with(export_dir: Path, state: object) -> RoundTripResult:
    """Ingest an export into a perturbed fake catalogue and compare it back."""
    export = load_export(export_dir)
    with FakeGMSServer(state) as server:  # type: ignore[arg-type]
        execute_ingestion(plan_ingestion(export), server.client())
        populated = server.state
    with FakeGMSServer(populated) as server:
        readback = read_back(export, server.client())
    return compare(list(export.proposals), readback, export.mode)


# ---------------------------------------------------------------- the list


def test_every_server_owned_field_carries_a_justification() -> None:
    """An entry without a stated reason is how an ignore list starts eroding."""
    for entry in SERVER_OWNED_FIELDS:
        assert entry.justification.strip(), entry.path
        assert len(entry.justification) > 80, f"{entry.path}: justification is too thin"


def test_the_ignore_list_is_deliberately_small() -> None:
    """A tripwire, not a style rule.

    This module ships with no evidence from a real DataHub server, so the list
    should stay near-empty until the live integration job earns additions. If a
    change pushes it past a handful of entries, that is a decision worth forcing
    a reviewer to look at rather than something to discover later.
    """
    assert len(SERVER_OWNED_FIELDS) <= 3


def test_normalization_version_is_recorded_in_the_contract() -> None:
    contract = normalization_contract()
    assert contract["normalization_version"] == NORMALIZATION_VERSION
    assert contract["unknown_server_additions"] == "reported as mutations"
    assert [entry["path"] for entry in contract["server_owned_fields"]] == sorted(
        entry.path for entry in SERVER_OWNED_FIELDS
    )


# ------------------------------------------------------- systemMetadata


def test_system_metadata_is_normalized_away() -> None:
    """Justification: server-owned ingestion provenance, never sent by us."""
    stored = {
        "name": "alpha",
        "systemMetadata": {"runId": "abc", "lastObserved": 1_700_000_000},
    }
    assert normalize_aspect("datasetProperties", stored) == {"name": "alpha"}


def test_system_metadata_changing_between_runs_is_not_a_difference() -> None:
    """The reason the field is ignored: it changes on every ingestion.

    Without this rule the idempotence claim would be untestable, because a
    second identical ingestion would report every aspect as mutated.
    """
    first = {"name": "alpha", "systemMetadata": {"runId": "run-1"}}
    second = {"name": "alpha", "systemMetadata": {"runId": "run-2"}}
    assert (
        _diff(
            normalize_aspect("datasetProperties", first),
            normalize_aspect("datasetProperties", second),
            "",
            "datasetProperties",
        )
        == []
    )


def test_a_field_adjacent_to_system_metadata_is_still_compared() -> None:
    """The paired test: forgiveness is scoped to the named field and nothing else."""
    sent = {"name": "alpha", "systemMetadata": {"runId": "run-1"}}
    retrieved = {"name": "bravo", "systemMetadata": {"runId": "run-2"}}
    differences = _diff(
        normalize_aspect("datasetProperties", sent),
        normalize_aspect("datasetProperties", retrieved),
        "",
        "datasetProperties",
    )
    assert [(d.path, d.sent, d.retrieved) for d in differences] == [("name", "alpha", "bravo")]


def test_a_nested_key_named_like_a_server_field_is_not_stripped() -> None:
    """The rule is a path, not a name.

    ``customProperties.systemMetadata`` is a property value we emitted, not the
    server's envelope, and stripping it would silently drop real content.
    """
    payload = {"customProperties": {"systemMetadata": "value-we-sent"}}
    assert normalize_aspect("datasetProperties", payload) == payload


# --------------------------------------------------- unknown server additions


def test_an_unknown_server_added_field_remains_a_mutation() -> None:
    """The default is suspicion. Forgiveness is opt-in and reviewed."""
    sent = {"name": "alpha"}
    retrieved = {"name": "alpha", "someNewServerField": {"x": 1}}
    differences = _diff(
        normalize_aspect("datasetProperties", sent),
        normalize_aspect("datasetProperties", retrieved),
        "",
        "datasetProperties",
    )
    assert [d.path for d in differences] == ["someNewServerField"]


def test_normalization_adds_nothing_and_coerces_nothing() -> None:
    """No key is invented, no default materialised, no type coerced."""
    payload = {"a": None, "b": [], "c": {}, "d": 0, "e": False, "f": ""}
    assert normalize_aspect("status", payload) == payload


# ------------------------------------------------------- ordering semantics


def test_unordered_fields_are_only_those_documented() -> None:
    """Restraint is the contract. Notably ``subTypes.typeNames`` is not here."""
    assert "subTypes" not in UNORDERED_FIELDS
    assert not is_unordered("subTypes", "typeNames")
    assert is_unordered("ownership", "owners")
    assert is_unordered("upstreamLineage", "upstreams")


def test_reordering_an_unordered_field_is_not_a_difference() -> None:
    sent = {"owners": [{"owner": "urn:li:corpGroup:a"}, {"owner": "urn:li:corpGroup:b"}]}
    retrieved = {"owners": [{"owner": "urn:li:corpGroup:b"}, {"owner": "urn:li:corpGroup:a"}]}
    assert _diff(sent, retrieved, "", "ownership") == []


def test_changing_a_member_of_an_unordered_field_is_still_a_difference() -> None:
    """The paired test: order-insensitivity is not value-insensitivity."""
    sent = {"owners": [{"owner": "urn:li:corpGroup:a"}]}
    retrieved = {"owners": [{"owner": "urn:li:corpGroup:z"}]}
    differences = _diff(sent, retrieved, "", "ownership")
    assert {d.path for d in differences} == {"owners[*]"}
    assert len(differences) == 2  # one removed member, one added


def test_reordering_an_ordered_field_is_a_difference() -> None:
    """``typeNames`` conventionally leads with the primary subtype."""
    sent = {"typeNames": ["Dataset", "View"]}
    retrieved = {"typeNames": ["View", "Dataset"]}
    differences = _diff(sent, retrieved, "", "subTypes")
    assert [d.path for d in differences] == ["typeNames[0]", "typeNames[1]"]


def test_unordered_comparison_applies_only_to_the_named_aspect() -> None:
    """``owners`` is unordered in ``ownership``, not universally."""
    sent = {"owners": ["a", "b"]}
    retrieved = {"owners": ["b", "a"]}
    assert _diff(sent, retrieved, "", "ownership") == []
    assert _diff(sent, retrieved, "", "datasetProperties") != []


# ------------------------------------------------ version 2: server derivation
#
# Every rule below is paired. The forgiveness test proves the rule works; the
# test beside it proves the rule cannot be stretched to cover a real change.
# A rule with only the first half of that pair is how an ignore list becomes a
# function that always returns "identical".


def test_a_key_aspect_is_recognised_as_server_derived() -> None:
    """DataHub materialises ``<entityType>Key`` from the URN we sent."""
    assert is_server_derived_aspect("dataset", "datasetKey")
    assert is_server_derived_aspect("assertion", "assertionKey")
    assert is_server_derived_aspect("glossaryNode", "glossaryNodeKey")


def test_a_key_aspect_of_the_wrong_entity_type_is_not_derived() -> None:
    """The paired test: it is a rule about *that* entity's key, not a suffix.

    A ``datasetKey`` sitting on a tag was not derived from the tag's URN, so
    somebody put it there and containment must say so.
    """
    assert not is_server_derived_aspect("tag", "datasetKey")
    assert not is_server_derived_aspect("dataset", "assertionKey")


def test_only_the_named_aspects_are_treated_as_derived() -> None:
    """The paired test for the enumerated entries: the list is exhaustive."""
    for aspect in ("browsePathsV2", "aliases", "dataPlatformInstance"):
        assert is_server_derived_aspect("dataset", aspect), aspect
    for aspect in ("datasetProperties", "ownership", "globalTags", "institutionalMemory"):
        assert not is_server_derived_aspect("dataset", aspect), aspect


def test_a_derived_aspect_does_not_fail_containment(mini_export_dir: Path) -> None:
    export = load_export(mini_export_dir)
    urn = str(next(p for p in export.proposals if p["entityType"] == "dataset")["entityUrn"])
    state = FakeGMS(inject={(urn, "datasetKey"): {"name": "x"}})
    result = _roundtrip_with(mini_export_dir, state)
    assert not result.of_kind(DiscrepancyKind.EXTRA_ASPECT)
    assert result.clean


def test_an_undeclared_extra_aspect_still_fails_containment(mini_export_dir: Path) -> None:
    """The paired test: derivation is not a blanket amnesty for extra aspects."""
    export = load_export(mini_export_dir)
    urn = str(export.proposals[0]["entityUrn"])
    state = FakeGMS(inject={(urn, "institutionalMemory"): {"elements": []}})
    result = _roundtrip_with(mini_export_dir, state)
    assert [
        (i.entity_urn, i.aspect_name) for i in result.of_kind(DiscrepancyKind.EXTRA_ASPECT)
    ] == [(urn, "institutionalMemory")]


def test_a_derived_aspect_on_an_entity_nobody_sent_is_still_an_extra_entity(
    mini_export_dir: Path,
) -> None:
    """The exemption reaches aspects, never entities.

    A key aspect proves an entity exists; it does not make an entity we never
    sent acceptable.
    """

    intruder = urns.dataset_urn("ds-nobody-sent-this")
    state = FakeGMS(inject_entities={intruder: {"datasetKey": {"name": "x"}}})
    result = _roundtrip_with(mini_export_dir, state)
    assert [i.entity_urn for i in result.of_kind(DiscrepancyKind.EXTRA_ENTITY)] == [intruder]


def test_a_declared_server_added_field_is_forgiven_when_we_sent_nothing() -> None:
    sent = {"owners": [{"owner": "urn:li:corpGroup:a"}]}
    retrieved = sent | {"ownerTypes": {"urn:li:ownershipType:__system__dataowner": ["a"]}}
    assert _filtered(sent, retrieved, "ownership") == []


def test_a_declared_server_added_field_we_did_send_is_still_compared() -> None:
    """The paired test, and the reason this is not a strip rule.

    Forgiveness is conditional on the field being *added*. If the emitted
    payload carries the path and the server returns something else, that is a
    mutation — the list cannot hide it.
    """
    sent = {"owners": [], "ownerTypes": {"a": ["x"]}}
    retrieved = {"owners": [], "ownerTypes": {"a": ["CHANGED"]}}
    differences = _filtered(sent, retrieved, "ownership")
    assert [d.path for d in differences] == ["ownerTypes.a[0]"]


def test_server_added_forgiveness_is_scoped_to_its_aspect() -> None:
    """``ownerTypes`` is forgiven in ``ownership``, not everywhere."""
    sent: dict[str, object] = {}
    retrieved = {"ownerTypes": {"a": ["x"]}}
    assert _filtered(sent, retrieved, "ownership") == []
    assert [d.path for d in _filtered(sent, retrieved, "datasetProperties")] == ["ownerTypes"]


def test_an_undeclared_added_field_is_still_a_mutation() -> None:
    """The default stays suspicion: only the three declared paths are forgiven."""
    sent: dict[str, object] = {"name": "x"}
    retrieved = {"name": "x", "somethingNew": 1}
    assert [d.path for d in _filtered(sent, retrieved, "datasetProperties")] == ["somethingNew"]


def test_every_declared_rule_carries_a_justification() -> None:
    """A rule without a stated reason cannot be reviewed, so it cannot be added."""
    for item in SERVER_ADDED_FIELDS:
        assert len(item.justification) > 80, item.path
    for item in SERVER_DERIVED_ASPECTS:
        assert len(item.justification) > 80, item.aspect
    assert len(KEY_ASPECT_JUSTIFICATION) > 80


def test_the_contract_is_reported_with_its_scope() -> None:
    """A stored report must be interpretable without this source tree."""
    contract = normalization_contract()
    assert contract["normalization_version"] == NORMALIZATION_VERSION == 2
    assert "containment only" in contract["server_derived_aspects"]["scope"]
    assert "still a mutation" in contract["server_added_fields_scope"]
    assert {item["path"] for item in contract["server_added_fields"]} == {
        "entityUrn",
        "domainAssociations",
        "ownerTypes",
    }
