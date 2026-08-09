"""The normalization contract, and the evidence behind every entry in it.

The forgiveness tests and their paired adjacent-mutation tests live in
``test_live_roundtrip.py``, where a real readback makes them meaningful. What is
proved here is the thing that would otherwise be an assertion in a docstring:
that each forgiven field really is one OpenMetadata generates, checked
mechanically against OpenMetadata's own vendored schemas rather than against
somebody's recollection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.openmetadata.normalize import (
    OM_NORMALIZATION_VERSION,
    PLATFORM_GENERATED_FIELDS,
    REFERENCE_FIELDS,
    TAG_LABEL_DERIVED_FIELDS,
    UNORDERED_FIELDS,
    forgive_additions,
    is_platform_generated,
    normalization_contract,
    project_reference,
)

SCHEMAS = Path(__file__).resolve().parent / "schemas"

# The create/entity schema pairs the contract's evidence rests on.
PAIRS = (
    ("container", "api/data/createContainer.json", "entity/data/container.json"),
    ("dataProduct", "api/domains/createDataProduct.json", "entity/domains/dataProduct.json"),
    ("domain", "api/domains/createDomain.json", "entity/domains/domain.json"),
    ("team", "api/teams/createTeam.json", "entity/teams/team.json"),
    (
        "storageService",
        "api/services/createStorageService.json",
        "entity/services/storageService.json",
    ),
)


def _properties(name: str) -> set[str]:
    return set(json.loads((SCHEMAS / name).read_text(encoding="utf-8"))["properties"])


@pytest.mark.parametrize(("entity_type", "create", "entity"), PAIRS)
def test_every_forgiven_field_is_one_dataswamp_cannot_send(
    entity_type: str, create: str, entity: str
) -> None:
    """The mechanical form of the contract's evidence standard.

    A field is forgiven only where the ``Create<Entity>`` schema sets
    ``additionalProperties: false`` and omits it while the entity schema declares
    it. That combination proves DataSwamp cannot have sent it, so any value found
    at that path in a readback is the platform's.
    """
    schema = json.loads((SCHEMAS / create).read_text(encoding="utf-8"))
    assert schema.get("additionalProperties") is False, f"{create} would admit extra fields"
    creatable = set(schema["properties"])
    declared = _properties(entity)

    for field in PLATFORM_GENERATED_FIELDS:
        if not field.applies_to(entity_type) or field.path not in declared:
            continue
        assert field.path not in creatable, (
            f"{field.path!r} is forgiven on {entity_type} but create{entity_type} accepts it — "
            "DataSwamp could send it, so it must not be normalized away"
        )


def test_no_forgiven_field_is_a_field_the_mapping_actually_emits(mini_observed: object) -> None:
    """Belt and braces: nothing the emitted plan writes may be forgiven on its own type.

    Scope is what makes this pass rather than luck. ``serviceType`` *is* emitted —
    once, on the StorageService, where it is the service's own fact — and is
    forgiven only on a Container, where OpenMetadata copies it in. A rule that
    forgot to name its entity types would fail here.
    """
    for record in mini_observed.records:  # type: ignore[attr-defined]
        for key in record.create or {}:
            assert not is_platform_generated(record.entity_type, key), (
                f"{record.fqn} emits {key!r} as a {record.entity_type}, "
                "which normalization would forgive"
            )


def test_every_entry_carries_a_justification() -> None:
    for field in PLATFORM_GENERATED_FIELDS:
        assert len(field.justification) > 60, f"{field.path} has no real justification"


def test_deliberately_excluded_fields_stay_excluded() -> None:
    """These are absent from the create schemas but are *not* server-generated.

    A user or another tool sets them through PATCH, so a value appearing there is
    somebody else writing to DataSwamp's entities — exactly what containment
    exists to notice. They must remain discrepancies by default.
    """
    for path in ("retentionPeriod", "sampleData", "certification", "entityStatus", "prefix"):
        assert not is_platform_generated("container", path)


def test_forgiveness_is_scoped_to_the_entity_types_it_names() -> None:
    assert is_platform_generated("container", "serviceType")
    assert not is_platform_generated("domain", "serviceType")
    assert is_platform_generated("domain", "id")


def test_forgiveness_is_additive_only() -> None:
    """A value DataSwamp sent is compared even when its key is on a derived list."""
    sent = {"tagFQN": "dataswamp.x", "description": "ours"}
    retrieved = {"tagFQN": "dataswamp.x", "description": "theirs", "href": "http://x"}
    kept = forgive_additions(sent, retrieved, TAG_LABEL_DERIVED_FIELDS)
    assert kept == {"tagFQN": "dataswamp.x", "description": "theirs"}


def test_reference_projection_handles_every_form_openmetadata_uses() -> None:
    assert project_reference("dataswamp-prog") == "dataswamp-prog"
    expanded = {"id": "u", "fullyQualifiedName": "dataswamp-prog"}
    assert project_reference(expanded) == "dataswamp-prog"
    assert project_reference([{"fullyQualifiedName": "a"}, "b"]) == ["a", "b"]


def test_an_unresolvable_reference_is_not_projected_onto_something_that_matches() -> None:
    """A reference with no FQN stays visible as a difference rather than vanishing."""
    value = {"id": "some-uuid", "type": "container"}
    assert project_reference(value) == value


def test_the_contract_is_embeddable_and_names_its_evidence_standard() -> None:
    contract = normalization_contract()
    assert contract["normalization_version"] == OM_NORMALIZATION_VERSION == 1
    assert contract["catalogue"] == "openmetadata"
    assert "additionalProperties: false" in contract["evidence_standard"]
    assert "fake server" in contract["evidence_standard"]
    assert len(contract["platform_generated_fields"]) == len(PLATFORM_GENERATED_FIELDS)
    assert json.loads(json.dumps(contract)) == contract


def test_the_openmetadata_contract_is_independent_of_the_datahub_one() -> None:
    """Two catalogues, two contracts, two version counters. Never coupled."""
    from dataswamp_biosystems.adapters.datahub.normalize import NORMALIZATION_VERSION

    assert OM_NORMALIZATION_VERSION == 1
    assert NORMALIZATION_VERSION == 2
    source = (
        Path(__file__).resolve().parents[3]
        / "src/dataswamp_biosystems/adapters/openmetadata/normalize.py"
    ).read_text(encoding="utf-8")
    assert "import" not in source.split("datahub")[0].rsplit("\n", 1)[-1]
    assert "from dataswamp_biosystems.adapters.datahub" not in source


def test_the_unordered_and_reference_sets_are_deliberate() -> None:
    """``fileFormats`` order is the mapping's, so it stays positional."""
    assert "fileFormats" not in UNORDERED_FIELDS
    assert "extension" not in UNORDERED_FIELDS
    assert "extension" not in REFERENCE_FIELDS
