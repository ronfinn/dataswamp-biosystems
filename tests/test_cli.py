"""Tests for the dataswamp CLI."""

from typer.testing import CliRunner

from dataswamp_biosystems import __version__
from dataswamp_biosystems.cli import app

runner = CliRunner()


def test_version_command_exits_successfully() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0


def test_version_command_prints_version() -> None:
    result = runner.invoke(app, ["version"])
    assert __version__ in result.output
