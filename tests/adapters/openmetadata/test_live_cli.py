"""The two live OpenMetadata commands: exit codes, refusals and written output.

Exit codes are a contract other tooling depends on, so each is asserted rather
than assumed. The dry-run guarantee is tested by poisoning the network entry
points themselves, not by mocking the client — mocking the client would only
prove that the code path nobody doubts was not taken.
"""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

from dataswamp_biosystems.adapters.openmetadata import (
    DISCREPANCIES_NAME,
    HOST_PORT_ENV,
    JWT_TOKEN_ENV,
    LEAK_FINDINGS_NAME,
    ROUNDTRIP_REPORT_NAME,
)
from dataswamp_biosystems.adapters.openmetadata.export import ENTITIES_NAME
from dataswamp_biosystems.cli import app

from .conftest import LiveFixture

runner = CliRunner()

SECRET = "cli-must-never-print-this"


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOST_PORT_ENV, raising=False)
    monkeypatch.delenv(JWT_TOKEN_ENV, raising=False)


# ---------------------------------------------------------------------------
# ingest-openmetadata
# ---------------------------------------------------------------------------


def test_dry_run_succeeds_and_opens_no_socket(
    om_observed_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dry run that contacts a server is not a dry run — including a health check."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("--dry-run opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    result = runner.invoke(
        app, ["ingest-openmetadata", "--export-dir", str(om_observed_export_dir), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "no connection was opened" in result.output
    assert "blocked" in result.output


def test_a_dry_run_needs_no_credentials_at_all(om_observed_export_dir: Path) -> None:
    """The environment is empty in this suite, and a dry run must still work."""
    result = runner.invoke(
        app, ["ingest-openmetadata", "--export-dir", str(om_observed_export_dir), "--dry-run"]
    )
    assert result.exit_code == 0


def test_transmission_without_yes_exits_one(om_observed_export_dir: Path) -> None:
    result = runner.invoke(
        app, ["ingest-openmetadata", "--export-dir", str(om_observed_export_dir)]
    )
    assert result.exit_code == 1
    assert "--yes" in result.output


def test_a_privileged_export_needs_its_own_acknowledgement(om_truth_export_dir: Path) -> None:
    result = runner.invoke(
        app, ["ingest-openmetadata", "--export-dir", str(om_truth_export_dir), "--yes"]
    )
    assert result.exit_code == 1
    assert "PRIVILEGED" in result.output


def test_an_unreadable_export_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ingest-openmetadata", "--export-dir", str(tmp_path)])
    assert result.exit_code == 2


def test_a_tampered_export_exits_two(copied_om_export: Path) -> None:
    target = copied_om_export / ENTITIES_NAME
    target.write_bytes(target.read_bytes().replace(b'"description"', b'"descriptioN"', 1))
    result = runner.invoke(
        app, ["ingest-openmetadata", "--export-dir", str(copied_om_export), "--dry-run"]
    )
    assert result.exit_code == 2
    assert "digest" in result.output


def test_a_missing_host_exits_two_and_says_where_credentials_come_from(
    om_observed_export_dir: Path,
) -> None:
    result = runner.invoke(
        app, ["ingest-openmetadata", "--export-dir", str(om_observed_export_dir), "--yes"]
    )
    assert result.exit_code == 2
    assert HOST_PORT_ENV in result.output


def test_the_token_is_not_a_command_line_option(om_observed_export_dir: Path) -> None:
    """A token in argv leaks into shell history and process listings."""
    result = runner.invoke(
        app,
        [
            "ingest-openmetadata",
            "--export-dir",
            str(om_observed_export_dir),
            "--token",
            SECRET,
        ],
    )
    assert result.exit_code != 0
    # Introspected, not read out of rendered help: Typer wraps and colours help
    # text by terminal width, which makes a substring check a test of the
    # terminal rather than of the interface.
    command = typer.main.get_command(app).commands["ingest-openmetadata"]  # type: ignore[attr-defined]
    options = {opt for param in command.params for opt in param.opts}
    assert not any("token" in opt.lower() for opt in options)


def test_a_full_ingestion_reports_what_it_replayed(
    om_observed_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .fake_om import FakeOpenMetadataServer

    with FakeOpenMetadataServer() as server:
        monkeypatch.setenv(HOST_PORT_ENV, server.host_port)
        monkeypatch.setenv(JWT_TOKEN_ENV, SECRET)
        result = runner.invoke(
            app,
            ["ingest-openmetadata", "--export-dir", str(om_observed_export_dir), "--yes"],
        )
    assert result.exit_code == 0, result.output
    assert "Replayed" in result.output
    assert "converges" in result.output
    assert SECRET not in result.output


# ---------------------------------------------------------------------------
# verify-om-ingestion
# ---------------------------------------------------------------------------


def _verify(fixture: LiveFixture, output_dir: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv(HOST_PORT_ENV, fixture.server.host_port)
    monkeypatch.setenv(JWT_TOKEN_ENV, SECRET)
    return runner.invoke(
        app,
        [
            "verify-om-ingestion",
            "--export-dir",
            str(fixture.export.root),
            "--output-dir",
            str(output_dir),
        ],
    )


def test_a_clean_verification_exits_zero_and_writes_four_files(
    om_live: LiveFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "om-roundtrip"
    result = _verify(om_live, output, monkeypatch)
    assert result.exit_code == 0, result.output
    for name in (
        ROUNDTRIP_REPORT_NAME,
        DISCREPANCIES_NAME,
        LEAK_FINDINGS_NAME,
        "provenance.json",
    ):
        assert (output / name).is_file()
    # Always written, even when empty: "the probes found nothing" and "the probes
    # never ran" must not look alike.
    assert (output / LEAK_FINDINGS_NAME).read_text() == ""
    assert SECRET not in (output / ROUNDTRIP_REPORT_NAME).read_text()


def test_discrepancies_exit_one(
    om_live: LiveFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = next(r.fqn for r in om_live.export.records if r.phase == "dataset-container")
    om_live.state.drop.add(("container", victim))
    result = _verify(om_live, tmp_path / "out", monkeypatch)
    assert result.exit_code == 1
    assert "completeness: fail" in result.output


def test_an_unreachable_catalogue_exits_two(
    om_observed_export_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(HOST_PORT_ENV, "http://127.0.0.1:1/api")
    result = runner.invoke(
        app,
        [
            "verify-om-ingestion",
            "--export-dir",
            str(om_observed_export_dir),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 2


def test_an_output_directory_inside_the_export_is_refused(
    om_live: LiveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Output containment: a report may not replace the export it judged."""
    result = _verify(om_live, om_live.export.root / "inside", monkeypatch)
    assert result.exit_code == 2


def test_the_report_is_deterministic_and_records_its_own_limits(
    om_live: LiveFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    assert _verify(om_live, first, monkeypatch).exit_code == 0  # type: ignore[attr-defined]
    assert _verify(om_live, second, monkeypatch).exit_code == 0  # type: ignore[attr-defined]
    assert (first / ROUNDTRIP_REPORT_NAME).read_bytes() == (
        second / ROUNDTRIP_REPORT_NAME
    ).read_bytes()

    report = json.loads((first / ROUNDTRIP_REPORT_NAME).read_text())
    assert report["roundtrip_schema_version"] == 1
    assert report["normalization_version"] == 2
    assert report["catalogue"]["verified_openmetadata_version"] is None
    assert "unverified" in report["catalogue"]["live_support"]
    assert set(report["claims"]) == {
        "completeness",
        "fidelity",
        "containment",
        "non-leakage",
    }
    assert all(claim["status"] == "pass" for claim in report["claims"].values())
    assert report["normalization"]["normalization_version"] == 2
    assert report["unsupported_surfaces"]
    # No wall clock, no host, no path, no user.
    text = (first / ROUNDTRIP_REPORT_NAME).read_text()
    for forbidden in (str(tmp_path), "127.0.0.1"):
        assert forbidden not in text


def test_the_report_names_the_quality_surface_as_unsupported(
    om_live: LiveFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No round-trip coverage may be implied for what the mapping never emits."""
    _verify(om_live, tmp_path / "out", monkeypatch)
    report = json.loads((tmp_path / "out" / ROUNDTRIP_REPORT_NAME).read_text())
    surfaces = {item["surface"] for item in report["unsupported_surfaces"]}
    assert "quality-check results" in surfaces
    quality = next(
        item
        for item in report["unsupported_surfaces"]
        if item["surface"] == "quality-check results"
    )
    assert "TABLE and COLUMN" in quality["reason"]
