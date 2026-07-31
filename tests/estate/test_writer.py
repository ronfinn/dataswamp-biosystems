"""Integration tests for estate writing: layout, integrity, safety, budget."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from dataswamp_biosystems.estate import Profile
from dataswamp_biosystems.estate.errors import EstateIssueKind, EstateValidationError
from dataswamp_biosystems.estate.profiles import profile_spec
from dataswamp_biosystems.estate.validate import load_manifest_records
from dataswamp_biosystems.estate.writer import (
    MANIFEST_NAME,
    SUMMARY_JSON_NAME,
    SUMMARY_MD_NAME,
    _safe_join,
    write_estate,
)
from dataswamp_biosystems.truth import serialize
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.estate.conftest import TEST_SEED

_MB = 1_000_000


def test_tiny_layout_and_counts(graph: TruthGraph, tmp_path: Path) -> None:
    out = tmp_path / "estate"
    summary = write_estate(graph, Profile.TINY, TEST_SEED, out)
    assert (out / MANIFEST_NAME).exists()
    assert (out / SUMMARY_JSON_NAME).exists()
    assert (out / SUMMARY_MD_NAME).exists()
    assert (out / "files").is_dir()
    assert summary["counts"]["files"] == 98
    assert summary["sizes"]["total_physical_bytes"] < 50 * _MB


def test_manifest_matches_files_on_disk(graph: TruthGraph, tmp_path: Path) -> None:
    out = tmp_path / "estate"
    write_estate(graph, Profile.TINY, TEST_SEED, out)
    records = load_manifest_records(out)

    for record in records:
        path = out / record.relative_path
        assert path.exists(), record.relative_path
        assert serialize.digest(path.read_bytes()) == record.checksum

    # Every non-sidecar file under files/ corresponds to exactly one record.
    on_disk = [
        p
        for p in (out / "files").rglob("*")
        if p.is_file() and not p.name.endswith(".placeholder.json")
    ]
    assert len(on_disk) == len(records)

    # Each placeholder record has exactly one sidecar.
    sidecars = list((out / "files").rglob("*.placeholder.json"))
    assert len(sidecars) == sum(1 for r in records if r.is_placeholder)


def test_overwrite_replaces_previous_estate(graph: TruthGraph, tmp_path: Path) -> None:
    out = tmp_path / "estate"
    write_estate(graph, Profile.TINY, TEST_SEED, out)
    first = (out / MANIFEST_NAME).read_bytes()
    # A second run replaces cleanly and reproduces byte-identical output.
    write_estate(graph, Profile.TINY, TEST_SEED, out)
    assert (out / MANIFEST_NAME).read_bytes() == first


def test_budget_breach_aborts_without_final_output(
    graph: TruthGraph, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tiny = profile_spec(Profile.TINY)
    starved = dataclasses.replace(tiny, budget_bytes=1000)
    monkeypatch.setattr("dataswamp_biosystems.estate.writer.profile_spec", lambda _p: starved)
    out = tmp_path / "estate"
    with pytest.raises(EstateValidationError) as excinfo:
        write_estate(graph, Profile.TINY, TEST_SEED, out)
    assert any(i.kind is EstateIssueKind.BUDGET for i in excinfo.value.issues)
    assert not out.exists()


def test_safe_join_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(EstateValidationError) as excinfo:
        _safe_join(tmp_path, "../escape.txt")
    assert any(i.kind is EstateIssueKind.PATH_ESCAPE for i in excinfo.value.issues)


def test_safe_join_allows_nested(tmp_path: Path) -> None:
    resolved = _safe_join(tmp_path, "files/group/asset/file.csv")
    assert str(resolved).startswith(str(tmp_path.resolve()))


@pytest.mark.slow
def test_demo_profile_scale_and_budget(graph: TruthGraph, tmp_path: Path) -> None:
    out = tmp_path / "estate"
    summary = write_estate(graph, Profile.DEMO, TEST_SEED, out)
    assert 1000 <= summary["counts"]["files"] <= 2000
    assert summary["sizes"]["total_physical_bytes"] < 500 * _MB
