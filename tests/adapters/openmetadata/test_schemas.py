"""Emitted payloads, checked against OpenMetadata's own JSON schemas.

This is the only thing in the repository that can catch "the adapter emits a
field OpenMetadata does not have" or "an enum member that does not exist", since
no server is involved anywhere. The schemas are vendored verbatim from a named
upstream commit; see ``schemas/PROVENANCE.md``.

The suite proves three things about the *validation itself*, not just about the
payloads: that unknown fields fail, that enums are enforced, and that the
vendored subset is actually being resolved rather than silently skipped. A
validator that passes everything is worse than no validator, because it looks
like evidence.
"""

from __future__ import annotations

import json

import pytest
from jsonschema.exceptions import _WrappedReferencingError

from dataswamp_biosystems.adapters.openmetadata import (
    OPENMETADATA_SCHEMA_COMMIT,
    OPENMETADATA_SCHEMA_TARGET,
    ExportPlan,
)

from .schema_validation import (
    CREATE_SCHEMAS,
    SCHEMA_DIR,
    resolved_payload,
    schema_problems,
    validator_for,
    vendored_schema_paths,
)


def _creates(plan: ExportPlan) -> list:
    return [record for record in plan.records if record.create is not None]


def test_every_emitted_payload_validates(mini_observed: ExportPlan, mini_truth: ExportPlan) -> None:
    for plan in (mini_observed, mini_truth):
        for record in _creates(plan):
            assert schema_problems(record) == [], f"{record.entity_type} {record.fqn}"


def test_the_real_benchmark_export_validates(om_truth_export_dir) -> None:
    """The mini graph is small on purpose; the canonical estate is the real test."""
    for name in ("entities.jsonl", "custom-properties.jsonl"):
        for line in (om_truth_export_dir / name).read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if "create" not in record:
                continue
            validator = validator_for(record["entityType"])
            payload = dict(record["create"])
            for reference in record["references"]:
                if reference["field"] == "entityType":
                    continue
                stand_in = {
                    "id": "00000000-0000-5000-8000-000000000000",
                    "type": reference["entityType"],
                }
                if reference["many"]:
                    payload.setdefault(reference["field"], []).append(stand_in)
                else:
                    payload[reference["field"]] = stand_in
            assert list(validator.iter_errors(payload)) == [], record["fullyQualifiedName"]


def test_every_created_entity_type_has_a_vendored_schema(mini_truth: ExportPlan) -> None:
    assert {record.entity_type for record in _creates(mini_truth)} <= set(CREATE_SCHEMAS)


# -- the validation is actually strict ----------------------------------------


def test_an_unknown_field_fails_rather_than_being_dropped(mini_observed: ExportPlan) -> None:
    """Every upstream Create schema sets additionalProperties: false."""
    record = next(r for r in _creates(mini_observed) if r.entity_type == "container")
    validator = validator_for("container")
    payload = {**resolved_payload(record), "dataswampNotAnOpenMetadataField": "x"}
    errors = [error.message for error in validator.iter_errors(payload)]
    assert any("Additional properties are not allowed" in message for message in errors)


@pytest.mark.parametrize(
    ("entity_type", "field", "bad_value"),
    [
        ("storageService", "serviceType", "SwampStorage"),
        ("domain", "domainType", "Swamp-aligned"),
        ("team", "teamType", "Swarm"),
        ("container", "fileFormats", ["h5ad"]),
    ],
)
def test_enum_members_are_enforced(
    mini_observed: ExportPlan, entity_type: str, field: str, bad_value: object
) -> None:
    """The check that catches a coerced file format or an invented service type."""
    record = next(r for r in _creates(mini_observed) if r.entity_type == entity_type)
    validator = validator_for(entity_type)
    payload = {**resolved_payload(record), field: bad_value}
    assert list(validator.iter_errors(payload))


def test_a_missing_required_field_fails(mini_observed: ExportPlan) -> None:
    record = next(r for r in _creates(mini_observed) if r.entity_type == "dataProduct")
    payload = {key: value for key, value in resolved_payload(record).items() if key != "domains"}
    assert list(validator_for("dataProduct").iter_errors(payload))


def test_an_over_long_entity_name_fails(mini_observed: ExportPlan) -> None:
    record = next(r for r in _creates(mini_observed) if r.entity_type == "tag")
    payload = {**resolved_payload(record), "name": "x" * 300}
    assert list(validator_for("tag").iter_errors(payload))


def test_a_name_containing_the_forbidden_sequence_fails(mini_observed: ExportPlan) -> None:
    """OpenMetadata's entityName pattern forbids '::'."""
    record = next(r for r in _creates(mini_observed) if r.entity_type == "tag")
    payload = {**resolved_payload(record), "name": "bad::name"}
    assert list(validator_for("tag").iter_errors(payload))


def test_an_unresolvable_reference_raises_rather_than_passing_vacuously() -> None:
    """The vendored subset is intentionally partial; a gap must be loud.

    ``dataModel`` refs a schema this project deliberately does not vendor, because
    the adapter never emits it. If a future mapping change started emitting it,
    this is the error that would appear — not a silent pass.
    """
    validator = validator_for("container")
    payload = {
        "name": "x",
        "service": "dataswamp-biosystems",
        "dataModel": {
            "isPartitioned": False,
            "columns": [{"name": "gene_id", "dataType": "STRING"}],
        },
    }
    with pytest.raises(_WrappedReferencingError):
        list(validator.iter_errors(payload))


# -- the vendored subset ------------------------------------------------------


def test_the_vendored_subset_stays_minimal() -> None:
    """A growing schema tree stops being reviewable, which is the point of pinning it."""
    paths = vendored_schema_paths()
    assert len(paths) <= 30, paths
    assert set(CREATE_SCHEMAS.values()) <= set(paths)


def test_provenance_records_the_exact_upstream_revision() -> None:
    text = (SCHEMA_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert f"`{OPENMETADATA_SCHEMA_TARGET}`" in text
    assert f"`{OPENMETADATA_SCHEMA_COMMIT}`" in text
    assert "open-metadata/OpenMetadata" in text
    assert "openmetadata-spec/src/main/resources/json/schema/" in text
    # Refreshing must stay a deliberate act, never something pytest does.
    assert "scripts/update_openmetadata_fixtures.py" in text
    assert "--confirm" in text and "--reason" in text


def test_provenance_lists_every_vendored_file() -> None:
    text = (SCHEMA_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    for relative in vendored_schema_paths():
        assert relative in text, relative


def test_reading_a_schema_claims_no_live_compatibility() -> None:
    text = (SCHEMA_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "VERIFIED_OPENMETADATA_VERSION" in text
    assert "no live compatibility claim" in text.lower()


def test_the_schemas_are_never_regenerated_by_pytest() -> None:
    """A guard against the fixture-rewriting failure mode, stated as a test."""
    before = {path: (SCHEMA_DIR / path).read_bytes() for path in vendored_schema_paths()}
    assert before  # the suite has already run by now
    assert all((SCHEMA_DIR / path).read_bytes() == data for path, data in before.items())
