"""Tests for loading and validating the canonical configuration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.company import (
    CanonicalConfig,
    ConfigLoadError,
    ConfigValidationError,
    IssueKind,
    load_config,
)

Docs = dict[str, dict[str, Any]]
WriteConfig = Callable[[Docs], Path]


def _kinds(exc: ConfigValidationError) -> set[IssueKind]:
    return {issue.kind for issue in exc.issues}


def test_valid_full_configuration_loads(real_config_dir: Path) -> None:
    config = load_config(real_config_dir)
    counts = config.entity_counts()
    assert counts == {
        "programmes": 3,
        "studies": 6,
        "teams": 7,
        "people": 13,
        "roles": 8,
        "ownership_assignments": 9,
        "stewardship_assignments": 7,
        "vocabulary_terms": 56,
    }
    # Two studies per programme.
    per_programme: dict[str, int] = {}
    for study in config.studies:
        per_programme[study.programme_id] = per_programme.get(study.programme_id, 0) + 1
    assert set(per_programme.values()) == {2}
    assert len(per_programme) == 3


def test_compact_configuration_is_valid(compact_docs: Docs, write_config: WriteConfig) -> None:
    config = load_config(write_config(compact_docs))
    assert isinstance(config, CanonicalConfig)


def test_duplicate_id_is_rejected(compact_docs: Docs, write_config: WriteConfig) -> None:
    studies = compact_docs["studies.yaml"]["studies"]
    studies.append({**studies[0]})  # same id -> duplicate
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.DUPLICATE_ID in _kinds(excinfo.value)


def test_duplicate_email_is_rejected(compact_docs: Docs, write_config: WriteConfig) -> None:
    people = compact_docs["people.yaml"]["people"]
    people.append(
        {
            "id": "person-y",
            "full_name": "Person Y",
            "email": "person.x@dataswamp.example",  # duplicate of person-x
            "role": "role-x",
            "team_id": "team-x",
        }
    )
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.DUPLICATE_EMAIL in _kinds(excinfo.value)


def test_missing_programme_reference_is_rejected(
    compact_docs: Docs, write_config: WriteConfig
) -> None:
    compact_docs["studies.yaml"]["studies"][0]["programme_id"] = "prog-missing"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.UNRESOLVED_REFERENCE in _kinds(excinfo.value)


def test_missing_team_reference_is_rejected(compact_docs: Docs, write_config: WriteConfig) -> None:
    compact_docs["people.yaml"]["people"][0]["team_id"] = "team-missing"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.UNRESOLVED_REFERENCE in _kinds(excinfo.value)


def test_missing_person_reference_is_rejected(
    compact_docs: Docs, write_config: WriteConfig
) -> None:
    compact_docs["stewardship.yaml"]["stewardship"][0]["steward_id"] = "person-missing"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.UNRESOLVED_REFERENCE in _kinds(excinfo.value)


def test_owner_of_nonexistent_asset_is_rejected(
    compact_docs: Docs, write_config: WriteConfig
) -> None:
    compact_docs["ownership.yaml"]["ownership"][0]["subject_id"] = "prog-missing"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.UNRESOLVED_REFERENCE in _kinds(excinfo.value)


def test_invalid_email_domain_is_rejected(compact_docs: Docs, write_config: WriteConfig) -> None:
    compact_docs["people.yaml"]["people"][0]["email"] = "person.x@real-company.com"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.INVALID_EMAIL_DOMAIN in _kinds(excinfo.value)


def test_invalid_company_domain_is_rejected(compact_docs: Docs, write_config: WriteConfig) -> None:
    compact_docs["company.yaml"]["company"]["domain"] = "acme.test"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.INVALID_EMAIL_DOMAIN in _kinds(excinfo.value)


def test_invalid_vocabulary_reference_is_rejected(
    compact_docs: Docs, write_config: WriteConfig
) -> None:
    compact_docs["studies.yaml"]["studies"][0]["access_classification"] = "not-a-term"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.INVALID_VOCABULARY in _kinds(excinfo.value)


def test_scientific_team_without_programme_is_rejected(
    compact_docs: Docs, write_config: WriteConfig
) -> None:
    compact_docs["teams.yaml"]["teams"][0].pop("programme_id")
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.STRUCTURAL in _kinds(excinfo.value)


def test_unknown_field_is_rejected(compact_docs: Docs, write_config: WriteConfig) -> None:
    compact_docs["studies.yaml"]["studies"][0]["surprise"] = "value"
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.SCHEMA in _kinds(excinfo.value)


def test_wrong_schema_version_is_rejected(compact_docs: Docs, write_config: WriteConfig) -> None:
    compact_docs["company.yaml"]["schema_version"] = 99
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(write_config(compact_docs))
    assert IssueKind.SCHEMA in _kinds(excinfo.value)


def test_missing_file_raises_load_error(compact_docs: Docs, write_config: WriteConfig) -> None:
    config_dir = write_config(compact_docs)
    (config_dir / "studies.yaml").unlink()
    with pytest.raises(ConfigLoadError):
        load_config(config_dir)


def test_serialization_round_trip(real_config_dir: Path) -> None:
    config = load_config(real_config_dir)
    dumped = config.model_dump(mode="json")
    restored = CanonicalConfig.model_validate(dumped)
    assert restored == config
    # JSON dump is stable across repeated serialisation (supports determinism).
    assert config.model_dump_json() == restored.model_dump_json()
