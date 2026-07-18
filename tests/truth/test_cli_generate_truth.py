"""Tests for the ``generate-truth`` and ``validate-truth`` CLI commands."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dataswamp_biosystems.cli import app
from dataswamp_biosystems.truth.writer import MANIFEST_NAME, SUMMARY_NAME
from tests.truth.conftest import TEST_SEED

runner = CliRunner()

_EXPECTED_FILES = {
    "subjects.jsonl",
    "biospecimens.jsonl",
    "assays.jsonl",
    "runs.jsonl",
    "files.jsonl",
    "assets.jsonl",
    "contracts.jsonl",
    "quality.jsonl",
    "governance.jsonl",
    "lineage.jsonl",
    MANIFEST_NAME,
    SUMMARY_NAME,
}


def _generate(config_dir: Path, out: Path, *extra: str) -> object:
    return runner.invoke(
        app,
        [
            "generate-truth",
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(out),
            "--seed",
            str(TEST_SEED),
            *extra,
        ],
    )


def test_generate_writes_all_files(config_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "truth"
    result = _generate(config_dir, out)
    assert result.exit_code == 0, result.output
    written = {path.name for path in out.iterdir()}
    assert written >= _EXPECTED_FILES
    assert "datasets: 165" in result.output


def test_generate_then_validate_succeeds(config_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "truth"
    assert _generate(config_dir, out).exit_code == 0
    result = runner.invoke(
        app,
        ["validate-truth", "--truth-dir", str(out), "--config-dir", str(config_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "is valid" in result.output


def test_generate_refuses_nonempty_without_force(config_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "truth"
    out.mkdir()
    (out / "sentinel.txt").write_text("keep me", encoding="utf-8")
    result = _generate(config_dir, out)
    assert result.exit_code == 1
    assert "not empty" in result.output


def test_generate_overwrites_with_force(config_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "truth"
    out.mkdir()
    (out / "sentinel.txt").write_text("stale", encoding="utf-8")
    result = _generate(config_dir, out, "--force")
    assert result.exit_code == 0, result.output


def test_generate_missing_config_exits_two(tmp_path: Path) -> None:
    empty = tmp_path / "empty-config"
    empty.mkdir()
    result = _generate(empty, tmp_path / "truth")
    assert result.exit_code == 2


def test_validate_missing_manifest_exits_two(config_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["validate-truth", "--truth-dir", str(tmp_path), "--config-dir", str(config_dir)],
    )
    assert result.exit_code == 2


def test_generate_rejects_negative_seed(config_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "truth"
    result = runner.invoke(
        app,
        [
            "generate-truth",
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(out),
            "--seed",
            "-1",
        ],
    )
    assert result.exit_code == 2
    assert not out.exists()


def test_regeneration_safely_replaces_previous_output(config_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "truth"
    assert _generate(config_dir, out).exit_code == 0
    # A stale file from a hypothetical earlier layout must not survive a rerun.
    (out / "stale.jsonl").write_text("stale\n", encoding="utf-8")
    assert _generate(config_dir, out, "--force").exit_code == 0
    assert not (out / "stale.jsonl").exists()
    # The freshly written output still validates.
    result = runner.invoke(
        app,
        ["validate-truth", "--truth-dir", str(out), "--config-dir", str(config_dir)],
    )
    assert result.exit_code == 0, result.output


def test_validate_detects_on_disk_drift(config_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "truth"
    assert _generate(config_dir, out).exit_code == 0
    # Corrupt a shard so it no longer matches the regenerated graph.
    (out / "subjects.jsonl").write_bytes(b'{"id":"tampered"}\n')
    result = runner.invoke(
        app,
        ["validate-truth", "--truth-dir", str(out), "--config-dir", str(config_dir)],
    )
    assert result.exit_code == 1
    assert "differ" in result.output
