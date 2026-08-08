"""The normalization contract, and the guard rails that keep it narrow.

Every ignored server-owned field gets two tests: one showing that the field is
normalized away, and a **paired** one showing that an adjacent field which is
*not* on the list still surfaces as a difference. The pairing is the point. A
test that only proves forgiveness would pass equally well if normalization
deleted the entire payload.
"""

from __future__ import annotations

from dataswamp_biosystems.adapters.datahub.normalize import (
    NORMALIZATION_VERSION,
    SERVER_OWNED_FIELDS,
    UNORDERED_FIELDS,
    is_unordered,
    normalization_contract,
    normalize_aspect,
)
from dataswamp_biosystems.adapters.datahub.roundtrip import _diff

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
