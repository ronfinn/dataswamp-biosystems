"""Tests for the ``dataswamp validate-config`` CLI command."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from dataswamp_biosystems.cli import app

Docs = dict[str, dict[str, Any]]
WriteConfig = Callable[[Docs], Path]

runner = CliRunner()


def test_cli_success_reports_counts(real_config_dir: Path) -> None:
    result = runner.invoke(app, ["validate-config", "--config-dir", str(real_config_dir)])
    assert result.exit_code == 0
    assert "Configuration is valid" in result.output
    for label in (
        "programmes: 3",
        "studies: 6",
        "teams: 7",
        "people: 13",
        "ownership assignments: 9",
        "stewardship assignments: 7",
        "vocabulary terms: 56",
    ):
        assert label in result.output


def test_cli_validation_failure_exits_nonzero(
    compact_docs: Docs, write_config: WriteConfig
) -> None:
    compact_docs["studies.yaml"]["studies"][0]["programme_id"] = "prog-missing"
    config_dir = write_config(compact_docs)
    result = runner.invoke(app, ["validate-config", "--config-dir", str(config_dir)])
    assert result.exit_code == 1
    assert "Configuration is invalid" in result.output
    assert "prog-missing" in result.output


def test_cli_load_failure_exits_code_two(compact_docs: Docs, write_config: WriteConfig) -> None:
    config_dir = write_config(compact_docs)
    (config_dir / "company.yaml").unlink()
    result = runner.invoke(app, ["validate-config", "--config-dir", str(config_dir)])
    assert result.exit_code == 2
    assert "Could not load configuration" in result.output
