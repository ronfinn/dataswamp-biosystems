"""``dataswamp export-openmetadata``: exit codes, containment and honesty.

Exit codes are part of the public CLI contract — scripts branch on them, not on
message text — so each documented code gets a test. The other thing checked here
is that the command never opens a socket: the whole adapter is offline at this
milestone, and "we did not mean to" is not a guarantee.
"""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataswamp_biosystems.adapters.openmetadata import (
    EXPORT_MANIFEST_NAME,
    MAPPING_COVERAGE_NAME,
)
from dataswamp_biosystems.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing in this command may reach a network. Prove it, don't assume it."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("export-openmetadata attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)


def test_an_observed_export_succeeds(full_bundle_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(full_bundle_dir),
            "--output-dir",
            str(tmp_path / "export"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "mode observed" in result.output
    assert (tmp_path / "export" / MAPPING_COVERAGE_NAME).is_file()


def test_the_default_mode_is_observed(full_bundle_dir: Path, tmp_path: Path) -> None:
    """The unprivileged mode is what you get if you do not think about it."""
    runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(full_bundle_dir),
            "--output-dir",
            str(tmp_path / "export"),
        ],
    )
    manifest = json.loads((tmp_path / "export" / EXPORT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["mode"] == "observed"
    assert manifest["privileged"] is False


def test_truth_mode_warns_that_it_is_privileged(full_bundle_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(full_bundle_dir),
            "--mode",
            "truth",
            "--output-dir",
            str(tmp_path / "export"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "PRIVILEGED" in result.output
    assert "ground truth" in result.output


def test_the_command_says_no_live_compatibility_is_claimed(
    full_bundle_dir: Path, tmp_path: Path
) -> None:
    """A user should not have to read an ADR to learn what has not been tested."""
    result = runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(full_bundle_dir),
            "--output-dir",
            str(tmp_path / "export"),
        ],
    )
    assert "No live OpenMetadata compatibility point is claimed" in result.output


def test_an_unreadable_bundle_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(tmp_path / "nowhere"),
            "--output-dir",
            str(tmp_path / "export"),
        ],
    )
    assert result.exit_code == 2
    assert "Could not read the bundle" in result.output


def test_a_truth_only_bundle_cannot_serve_observed_and_exits_two(
    truth_only_bundle_dir: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(truth_only_bundle_dir),
            "--output-dir",
            str(tmp_path / "export"),
        ],
    )
    assert result.exit_code == 2


def test_an_output_directory_inside_the_bundle_is_refused(full_bundle_dir: Path) -> None:
    """The shared containment policy: never replace the artefact being translated."""
    result = runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(full_bundle_dir),
            "--output-dir",
            str(full_bundle_dir / "export"),
        ],
    )
    assert result.exit_code == 2
    assert "Refusing to generate into" in result.output


def test_the_bundle_itself_as_output_is_refused(full_bundle_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(full_bundle_dir),
            "--output-dir",
            str(full_bundle_dir),
        ],
    )
    assert result.exit_code == 2


def test_a_non_empty_output_directory_needs_force(full_bundle_dir: Path, tmp_path: Path) -> None:
    target = tmp_path / "export"
    target.mkdir()
    (target / "something.txt").write_text("keep me", encoding="utf-8")
    args = [
        "export-openmetadata",
        "--bundle",
        str(full_bundle_dir),
        "--output-dir",
        str(target),
    ]
    refused = runner.invoke(app, args)
    assert refused.exit_code == 2
    assert "--force" in refused.output

    forced = runner.invoke(app, [*args, "--force"])
    assert forced.exit_code == 0, forced.output
    assert not (target / "something.txt").exists()


def test_an_invalid_plan_exits_one_without_writing(
    full_bundle_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 1 is 'the input was read but is invalid', and nothing is replaced."""
    target = tmp_path / "export"
    monkeypatch.setattr(
        "dataswamp_biosystems.cli.validate_openmetadata_plan",
        lambda plan: ["a deliberately injected problem"],
    )
    result = runner.invoke(
        app,
        [
            "export-openmetadata",
            "--bundle",
            str(full_bundle_dir),
            "--output-dir",
            str(target),
        ],
    )
    assert result.exit_code == 1
    assert "a deliberately injected problem" in result.output
    assert not target.exists()


def test_the_command_appears_in_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert "export-openmetadata" in result.output


def test_no_ingestion_command_exists_yet() -> None:
    """Issue A is offline. A live command would be a claim this project cannot back."""
    result = runner.invoke(app, ["--help"])
    assert "ingest-openmetadata" not in result.output
    assert "verify-om-ingestion" not in result.output
