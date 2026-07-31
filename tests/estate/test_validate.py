"""Tests for estate validation: integrity, safety, drift, and error paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.estate import Profile, validate_estate, write_estate
from dataswamp_biosystems.estate.errors import (
    EstateConfigError,
    EstateIssueKind,
    EstateValidationError,
)
from dataswamp_biosystems.estate.writer import MANIFEST_NAME
from dataswamp_biosystems.truth import serialize
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.estate.conftest import TEST_SEED


def _estate(graph: TruthGraph, tmp_path: Path) -> Path:
    out = tmp_path / "estate"
    write_estate(graph, Profile.TINY, TEST_SEED, out)
    return out


def test_freshly_written_estate_is_valid(graph: TruthGraph, tmp_path: Path) -> None:
    out = _estate(graph, tmp_path)
    validate_estate(out, graph)  # must not raise


def _kinds(exc: EstateValidationError) -> set[EstateIssueKind]:
    return {issue.kind for issue in exc.issues}


def test_tampered_content_fails_checksum(graph: TruthGraph, tmp_path: Path) -> None:
    out = _estate(graph, tmp_path)
    victim = next((out / "files").rglob("*.csv"))
    victim.write_bytes(victim.read_bytes() + b"tampered\n")
    with pytest.raises(EstateValidationError) as excinfo:
        validate_estate(out, graph)
    assert EstateIssueKind.CHECKSUM in _kinds(excinfo.value)


def test_missing_file_is_detected(graph: TruthGraph, tmp_path: Path) -> None:
    out = _estate(graph, tmp_path)
    next((out / "files").rglob("*.png")).unlink()
    with pytest.raises(EstateValidationError) as excinfo:
        validate_estate(out, graph)
    assert EstateIssueKind.CONSISTENCY in _kinds(excinfo.value)


def test_removed_sidecar_is_detected(graph: TruthGraph, tmp_path: Path) -> None:
    out = _estate(graph, tmp_path)
    next((out / "files").rglob("*.placeholder.json")).unlink()
    with pytest.raises(EstateValidationError) as excinfo:
        validate_estate(out, graph)
    assert EstateIssueKind.PLACEHOLDER in _kinds(excinfo.value)


def test_manifest_drift_is_detected(graph: TruthGraph, tmp_path: Path) -> None:
    out = _estate(graph, tmp_path)
    manifest = out / MANIFEST_NAME
    lines = manifest.read_text().splitlines()
    # Dropping a record leaves the remaining rows valid but the manifest no longer
    # matches a freshly regenerated one.
    manifest.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(EstateValidationError) as excinfo:
        validate_estate(out, graph)
    assert EstateIssueKind.CONSISTENCY in _kinds(excinfo.value)


def test_foreign_asset_reference_is_detected(graph: TruthGraph, tmp_path: Path) -> None:
    out = _estate(graph, tmp_path)
    manifest = out / MANIFEST_NAME
    lines = manifest.read_text().splitlines()
    first = json.loads(lines[0])
    first["asset_id"] = "ds-nonexistent-asset"
    lines[0] = serialize.canonical_json(first)
    manifest.write_text("\n".join(lines) + "\n")
    with pytest.raises(EstateValidationError) as excinfo:
        validate_estate(out, graph)
    assert EstateIssueKind.UNRESOLVED_ASSET in _kinds(excinfo.value)


def test_missing_summary_raises_config_error(graph: TruthGraph, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(EstateConfigError):
        validate_estate(empty, graph)


def test_unsupported_profile_value_rejected() -> None:
    with pytest.raises(ValueError):
        Profile("catastrophic")
