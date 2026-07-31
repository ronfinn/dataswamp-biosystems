"""Shared fixtures for canonical-configuration tests.

Negative tests use a *compact* configuration (one programme, one study, one
team, one person, minimal vocabularies) written to a temp directory. Each test
mutates a copy of that config to introduce exactly one defect, so failures are
isolated and the full authored configuration is not duplicated per test.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG_DIR = REPO_ROOT / "config"


def _compact_docs() -> dict[str, dict[str, Any]]:
    """Return a fresh, minimal, fully valid set of config documents."""
    return {
        "company.yaml": {
            "schema_version": 1,
            "company": {
                "id": "dsb",
                "legal_name": "Compact Co.",
                "display_name": "Compact Co.",
                "domain": "dataswamp.example",
            },
        },
        "programmes.yaml": {
            "schema_version": 1,
            "programmes": [
                {
                    "id": "prog-x",
                    "display_name": "Programme X",
                    "indication": "example cancer",
                }
            ],
        },
        "studies.yaml": {
            "schema_version": 1,
            "studies": [
                {
                    "id": "study-x",
                    "programme_id": "prog-x",
                    "display_name": "STUDY X",
                    "scientific_domains": ["dom-x"],
                    "modalities": ["mod-x"],
                    "access_classification": "acc-x",
                    "retention_class": "ret-x",
                    "lifecycle_stage": "life-x",
                    "intended_uses": ["use-x"],
                    "model_training_approval": "train-x",
                }
            ],
        },
        "teams.yaml": {
            "schema_version": 1,
            "teams": [
                {
                    "id": "team-x",
                    "display_name": "Team X",
                    "team_type": "scientific",
                    "programme_id": "prog-x",
                }
            ],
        },
        "people.yaml": {
            "schema_version": 1,
            "roles": [{"id": "role-x", "label": "Role X"}],
            "people": [
                {
                    "id": "person-x",
                    "full_name": "Person X",
                    "email": "person.x@dataswamp.example",
                    "role": "role-x",
                    "team_id": "team-x",
                }
            ],
        },
        "ownership.yaml": {
            "schema_version": 1,
            "ownership": [
                {
                    "id": "own-x",
                    "subject_type": "programme",
                    "subject_id": "prog-x",
                    "owner_type": "team",
                    "owner_id": "team-x",
                }
            ],
        },
        "stewardship.yaml": {
            "schema_version": 1,
            "stewardship": [
                {
                    "id": "stew-x",
                    "subject_type": "study",
                    "subject_id": "study-x",
                    "steward_id": "person-x",
                    "stewardship_type": "data-steward",
                }
            ],
        },
        "generation.yaml": {
            "schema_version": 1,
            "generation": {"seed": 1, "output_dir": "generated"},
        },
        "vocabularies/access-classifications.yaml": {
            "schema_version": 1,
            "terms": [{"id": "acc-x", "label": "Acc X", "sensitivity_level": 0}],
        },
        "vocabularies/retention-classes.yaml": {
            "schema_version": 1,
            "terms": [{"id": "ret-x", "label": "Ret X", "duration": None}],
        },
        "vocabularies/scientific-domains.yaml": {
            "schema_version": 1,
            "terms": [{"id": "dom-x", "label": "Dom X"}],
        },
        "vocabularies/modalities.yaml": {
            "schema_version": 1,
            "terms": [{"id": "mod-x", "label": "Mod X", "scientific_domain": "dom-x"}],
        },
        "vocabularies/lifecycle-stages.yaml": {
            "schema_version": 1,
            "terms": [{"id": "life-x", "label": "Life X", "order": 0}],
        },
        "vocabularies/intended-uses.yaml": {
            "schema_version": 1,
            "terms": [{"id": "use-x", "label": "Use X"}],
        },
        "vocabularies/training-approval-statuses.yaml": {
            "schema_version": 1,
            "terms": [{"id": "train-x", "label": "Train X"}],
        },
        "vocabularies/stewardship-types.yaml": {
            "schema_version": 1,
            "terms": [{"id": "data-steward", "label": "Data Steward"}],
        },
    }


def _write_docs(target_dir: Path, docs: dict[str, dict[str, Any]]) -> Path:
    for relative, content in docs.items():
        path = target_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    return target_dir


@pytest.fixture
def compact_docs() -> dict[str, dict[str, Any]]:
    """A fresh, mutable copy of the minimal valid config documents."""
    return _compact_docs()


@pytest.fixture
def write_config(
    tmp_path: Path,
) -> Callable[[dict[str, dict[str, Any]]], Path]:
    """Return a function that writes config documents to a temp dir and returns it."""

    def _write(docs: dict[str, dict[str, Any]]) -> Path:
        return _write_docs(tmp_path / "config", copy.deepcopy(docs))

    return _write


@pytest.fixture
def real_config_dir() -> Path:
    """Path to the repository's authored canonical configuration."""
    return REAL_CONFIG_DIR
