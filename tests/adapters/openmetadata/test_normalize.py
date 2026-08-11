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
    MATERIALIZED_DEFAULTS,
    OM_NORMALIZATION_VERSION,
    PLATFORM_GENERATED_FIELDS,
    REFERENCE_FIELDS,
    TAG_LABEL_DERIVED_FIELDS,
    UNORDERED_FIELDS,
    forgive_additions,
    is_materialized_default,
    is_platform_generated,
    normalization_contract,
    project_reference,
    reconcile_html_escaping,
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
    ("tag", "api/classification/createTag.json", "entity/classification/tag.json"),
    (
        "classification",
        "api/classification/createClassification.json",
        "entity/classification/classification.json",
    ),
    ("glossary", "api/data/createGlossary.json", "entity/data/glossary.json"),
    ("glossaryTerm", "api/data/createGlossaryTerm.json", "entity/data/glossaryTerm.json"),
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


@pytest.mark.parametrize(("entity_type", "create", "entity"), PAIRS)
def test_every_materialized_default_is_a_field_the_create_schema_accepts(
    entity_type: str, create: str, entity: str
) -> None:
    """The other half of the evidence, and the opposite test to the one above.

    A materialized default is precisely *not* a field DataSwamp cannot send — it
    is one the Create schema accepts and the export chose to omit. If a path ever
    disappeared from the create schema it would belong on the platform-generated
    list instead, under that list's stricter standard, so the two rule classes
    stay disjoint rather than overlapping into a general excuse.
    """
    creatable = set(json.loads((SCHEMAS / create).read_text(encoding="utf-8"))["properties"])
    declared = _properties(entity)

    for rule in MATERIALIZED_DEFAULTS:
        if not rule.applies_to(entity_type) or rule.path not in declared:
            continue
        assert rule.path in creatable, (
            f"{rule.path!r} is forgiven as a materialized default on {entity_type} but "
            f"create{entity_type} does not accept it — it is platform-generated, and "
            "belongs on the stricter list"
        )
        assert not is_platform_generated(entity_type, rule.path), (
            f"{rule.path!r} on {entity_type} is on both forgiveness lists"
        )


def test_the_two_stage_two_lists_are_disjoint_and_deterministic() -> None:
    """No path may be reachable by two different rules, on any entity type.

    The per-pair test above can only check entity types whose schemas are
    vendored. This one holds for every type either list names, and also pins the
    lists as ordered, duplicate-free tuples — a forgiveness rule that depended on
    iteration order would be a rule nobody could review.
    """
    generated = {
        (field.path, entity)
        for field in PLATFORM_GENERATED_FIELDS
        for entity in (field.entity_types or {"*"})
    }
    defaults = {
        (rule.path, entity)
        for rule in MATERIALIZED_DEFAULTS
        for entity in (rule.entity_types or {"*"})
    }
    assert not generated & defaults

    wildcard_paths = {field.path for field in PLATFORM_GENERATED_FIELDS if not field.entity_types}
    assert not wildcard_paths & {rule.path for rule in MATERIALIZED_DEFAULTS}

    assert isinstance(PLATFORM_GENERATED_FIELDS, tuple)
    assert isinstance(MATERIALIZED_DEFAULTS, tuple)
    assert len({(f.path, f.entity_types) for f in PLATFORM_GENERATED_FIELDS}) == len(
        PLATFORM_GENERATED_FIELDS
    )
    assert len({(r.path, r.entity_types) for r in MATERIALIZED_DEFAULTS}) == len(
        MATERIALIZED_DEFAULTS
    )


def test_every_entry_carries_a_justification() -> None:
    for field in PLATFORM_GENERATED_FIELDS:
        assert len(field.justification) > 60, f"{field.path} has no real justification"
    for rule in MATERIALIZED_DEFAULTS:
        assert len(rule.justification) > 60, f"{rule.path} has no real justification"


def test_deliberately_excluded_fields_stay_excluded() -> None:
    """These are absent from the create schemas but are *not* server-generated.

    A user or another tool sets them through PATCH, so a value appearing there is
    somebody else writing to DataSwamp's entities — exactly what containment
    exists to notice. They must remain discrepancies by default.

    ``entityStatus`` was on this list in version 1 and is not any more. What moved
    it was a real 1.13.3 canary returning it on 799 entities nobody patched — the
    only kind of evidence that is ever supposed to move it.
    """
    for path in ("retentionPeriod", "sampleData", "certification", "prefix"):
        assert not is_platform_generated("container", path)
        assert not is_materialized_default("container", path, "anything")


def test_a_materialized_default_is_forgiven_only_at_its_exact_value() -> None:
    """The forgiveness test, and its paired adjacent case.

    An empty owner list is the server's way of saying nobody owns this. An owner
    DataSwamp never sent is somebody writing to its entities, and stays visible.
    """
    assert is_materialized_default("container", "owners", [])
    assert not is_materialized_default("container", "owners", [{"fullyQualifiedName": "someone"}])

    assert is_materialized_default("team", "isJoinable", True)
    assert not is_materialized_default("team", "isJoinable", False)

    assert is_materialized_default("tag", "autoClassificationPriority", 50)
    assert not is_materialized_default("tag", "autoClassificationPriority", 90)

    assert is_materialized_default("glossary", "provider", "user")
    assert not is_materialized_default("glossary", "provider", "system")


def test_a_materialized_default_is_scoped_to_the_entity_types_it_names() -> None:
    assert is_materialized_default("dataProduct", "visibility", "PRIVATE")
    assert not is_materialized_default("container", "visibility", "PRIVATE")


def test_a_boolean_default_is_not_matched_by_a_numeric_lookalike() -> None:
    """``0 == False`` in Python. It must not be a reason to forgive a field."""
    assert not is_materialized_default("team", "isJoinable", 1)
    assert not is_materialized_default("tag", "autoClassificationEnabled", 0)


def test_html_escaping_is_reconciled_only_when_the_inversion_is_exact() -> None:
    """Stage 1: the two encodings are related, and only an exact inversion qualifies.

    This is not forgiveness — the description is still compared in full — so the
    paired cases here are the ones that must survive the reconciliation: a word
    change and a truncation.
    """
    sent = "DataSwamp study 'study-crc-01'."
    escaped = "DataSwamp study &#39;study-crc-01&#39;."
    assert reconcile_html_escaping("description", sent, escaped) == sent

    rewritten = "DataSwamp study &#39;study-crc-02&#39;."
    assert reconcile_html_escaping("description", sent, rewritten) == rewritten
    truncated = "DataSwamp study"
    assert reconcile_html_escaping("description", sent, truncated) == truncated
    punctuation_lost = "DataSwamp study &#39;study-crc-01&#39;"
    assert reconcile_html_escaping("description", sent, punctuation_lost) == punctuation_lost


def test_a_double_encoded_readback_is_never_reconciled() -> None:
    """One decoding round, not "decode until it matches"."""
    sent = "DataSwamp study 'study-crc-01'."
    double = "DataSwamp study &amp;#39;study-crc-01&amp;#39;."
    assert reconcile_html_escaping("description", sent, double) == double


def test_a_sent_description_containing_an_entity_is_never_reconciled() -> None:
    """The ambiguity guard, and the reason the rule can claim an exact inversion.

    If DataSwamp itself sent ``&#39;``, a decode of the readback could land on it
    from more than one starting point. The rule refuses the whole case rather
    than guess, so entity-like literal text can never collapse onto another sent
    value.
    """
    sent = "A description that literally contains &#39; as text."
    assert reconcile_html_escaping("description", sent, sent) == sent

    escaped = "A description that literally contains &amp;#39; as text."
    assert reconcile_html_escaping("description", sent, escaped) == escaped

    decoded = "A description that literally contains ' as text."
    assert reconcile_html_escaping("description", sent, decoded) == decoded


def test_html_escaping_is_reconciled_on_no_other_field() -> None:
    """Only free text is escaped. An identity or an enum is compared literally."""
    for field in ("fullyQualifiedName", "displayName", "name", "sourceUrl"):
        assert reconcile_html_escaping(field, "a'b", "a&#39;b") == "a&#39;b"


def test_representation_reconciliation_is_not_counted_as_forgiveness() -> None:
    """The two stages stay separate in the emitted contract as well as in the code."""
    contract = normalization_contract()
    assert contract["escaped_text_reconciliation"]["stage"] == 1
    assert contract["escaped_text_reconciliation"]["forgives"] is False
    assert "stage 2 only" in contract["version_counts"]
    assert "never a normalization-forgiveness candidate" in contract["comparison_model"]


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
    assert contract["normalization_version"] == OM_NORMALIZATION_VERSION == 2
    assert contract["catalogue"] == "openmetadata"
    assert "additionalProperties: false" in contract["evidence_standard"]
    assert "fake server" in contract["evidence_standard"]
    assert len(contract["platform_generated_fields"]) == len(PLATFORM_GENERATED_FIELDS)
    assert len(contract["materialized_defaults"]["fields"]) == len(MATERIALIZED_DEFAULTS)
    assert "1.13.3" in contract["materialized_defaults"]["evidence"]
    assert json.loads(json.dumps(contract)) == contract


def test_the_openmetadata_contract_is_independent_of_the_datahub_one() -> None:
    """Two catalogues, two contracts, two version counters. Never coupled."""
    from dataswamp_biosystems.adapters.datahub.normalize import NORMALIZATION_VERSION

    # The two counters reaching 2 independently is a coincidence, not a coupling:
    # they moved for unrelated reasons, on unrelated evidence, at different times.
    assert OM_NORMALIZATION_VERSION == 2
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
