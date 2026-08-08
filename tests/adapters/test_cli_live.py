"""The two live CLI commands: exit codes, containment, and refusing by default.

The interesting assertions here are the refusals. ``ingest-datahub`` writes to a
system outside this repository, and a truth-mode export writes the benchmark's
answer key into it, so both need to be hard to trigger by accident and easy to
prove refused.
"""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataswamp_biosystems.adapters.datahub.client import GMS_TOKEN_ENV, GMS_URL_ENV
from dataswamp_biosystems.adapters.datahub.report import (
    LEAK_FINDINGS_NAME,
    ROUNDTRIP_REPORT_NAME,
)
from dataswamp_biosystems.cli import app

from .fake_gms import FakeGMS, FakeGMSServer

runner = CliRunner()
TOKEN = "cli-secret-token"


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a developer's real instance be reached by the test suite."""
    monkeypatch.delenv(GMS_URL_ENV, raising=False)
    monkeypatch.delenv(GMS_TOKEN_ENV, raising=False)


def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("this command must not perform any network activity")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


# ------------------------------------------------------------ ingest-datahub


def test_dry_run_reports_the_plan_and_opens_no_socket(
    mini_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dry run that contacts a server is not a dry run.

    Note there is no ``DATAHUB_GMS_URL`` set either: a dry run must not even
    require configuration it will not use.
    """
    _forbid_network(monkeypatch)
    result = runner.invoke(
        app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "no connection was opened" in result.output
    assert "proposals:" in result.output


def test_ingestion_refuses_without_yes(
    mini_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_network(monkeypatch)
    result = runner.invoke(app, ["ingest-datahub", "--export-dir", str(mini_export_dir)])
    assert result.exit_code == 1
    assert "--yes" in result.output


def test_a_truth_export_refuses_without_the_privileged_acknowledgement(
    mini_truth_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing the answer key must be hard to do by accident."""
    _forbid_network(monkeypatch)
    result = runner.invoke(
        app, ["ingest-datahub", "--export-dir", str(mini_truth_export_dir), "--yes"]
    )
    assert result.exit_code == 1
    assert "PRIVILEGED" in result.output
    assert "--i-understand-this-is-ground-truth" in result.output


def test_a_truth_export_transmits_with_both_acknowledgements(
    mini_truth_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeGMSServer() as server:
        monkeypatch.setenv(GMS_URL_ENV, server.url)
        result = runner.invoke(
            app,
            [
                "ingest-datahub",
                "--export-dir",
                str(mini_truth_export_dir),
                "--yes",
                "--i-understand-this-is-ground-truth",
            ],
        )
        received = len(server.state.received)
    assert result.exit_code == 0, result.output
    assert received > 0


def test_ingestion_transmits_with_yes(
    mini_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeGMSServer() as server:
        monkeypatch.setenv(GMS_URL_ENV, server.url)
        monkeypatch.setenv(GMS_TOKEN_ENV, TOKEN)
        result = runner.invoke(
            app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--yes"]
        )
        auth = set(server.state.auth_headers)
    assert result.exit_code == 0, result.output
    assert auth == {f"Bearer {TOKEN}"}
    assert TOKEN not in result.output


def test_the_token_is_not_a_command_line_option(mini_export_dir: Path) -> None:
    """A token in ``argv`` leaks into shell history and process listings."""
    help_text = runner.invoke(app, ["ingest-datahub", "--help"]).output
    assert "--token" not in help_text
    rejected = runner.invoke(
        app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--token", TOKEN]
    )
    assert rejected.exit_code != 0


def test_a_missing_gms_url_exits_two(
    mini_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = runner.invoke(app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--yes"])
    assert result.exit_code == 2
    assert GMS_URL_ENV in result.output


def test_an_unreadable_export_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ingest-datahub", "--export-dir", str(tmp_path / "absent")])
    assert result.exit_code == 2


def test_an_unreachable_catalogue_exits_two(
    mini_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GMS_URL_ENV, "http://127.0.0.1:1")
    result = runner.invoke(app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--yes"])
    assert result.exit_code == 2


# --------------------------------------------------------- verify-ingestion


def test_a_clean_verification_exits_zero_and_writes_a_report(
    mini_export_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeGMSServer() as server:
        monkeypatch.setenv(GMS_URL_ENV, server.url)
        runner.invoke(app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--yes"])
        result = runner.invoke(
            app,
            [
                "verify-ingestion",
                "--export-dir",
                str(mini_export_dir),
                "--output-dir",
                str(tmp_path / "rt"),
            ],
        )
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / "rt" / ROUNDTRIP_REPORT_NAME).read_text(encoding="utf-8"))
    assert report["clean"] is True
    for claim in ("completeness", "fidelity", "containment", "non-leakage"):
        assert f"{claim}: pass" in result.output


def test_discrepancies_exit_one(
    mini_export_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 1 = the input was read but the state is wrong."""
    state = FakeGMS()
    with FakeGMSServer(state) as server:
        monkeypatch.setenv(GMS_URL_ENV, server.url)
        runner.invoke(app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--yes"])
        urn = next(iter(sorted(state.store)))
        state.drop = {(urn, name) for name in state.store[urn]}
        result = runner.invoke(
            app,
            [
                "verify-ingestion",
                "--export-dir",
                str(mini_export_dir),
                "--output-dir",
                str(tmp_path / "rt"),
            ],
        )
    assert result.exit_code == 1
    assert "completeness: fail" in result.output


def test_verification_reports_unavailable_extra_entity_coverage(
    mini_export_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeGMSServer() as server:
        monkeypatch.setenv(GMS_URL_ENV, server.url)
        runner.invoke(app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--yes"])
        result = runner.invoke(
            app,
            [
                "verify-ingestion",
                "--export-dir",
                str(mini_export_dir),
                "--output-dir",
                str(tmp_path / "rt"),
            ],
        )
    assert "coverage unavailable for" in result.output
    assert "container" in result.output


def test_the_output_directory_may_not_be_the_export_it_reads(
    mini_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared containment policy: generation replaces a whole directory."""
    _forbid_network(monkeypatch)
    result = runner.invoke(
        app,
        [
            "verify-ingestion",
            "--export-dir",
            str(mini_export_dir),
            "--output-dir",
            str(mini_export_dir),
        ],
    )
    assert result.exit_code == 2
    assert "DataHub export directory" in result.output


def test_the_output_directory_may_not_contain_the_export(
    mini_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_network(monkeypatch)
    result = runner.invoke(
        app,
        [
            "verify-ingestion",
            "--export-dir",
            str(mini_export_dir),
            "--output-dir",
            str(mini_export_dir.parent),
        ],
    )
    assert result.exit_code == 2


def test_a_non_empty_output_directory_needs_force(
    mini_export_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_network(monkeypatch)
    target = tmp_path / "rt"
    target.mkdir()
    (target / "existing.txt").write_text("keep me", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "verify-ingestion",
            "--export-dir",
            str(mini_export_dir),
            "--output-dir",
            str(target),
        ],
    )
    assert result.exit_code == 2
    assert "--force" in result.output


def test_verification_never_writes_a_token_into_its_report(
    mini_export_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeGMSServer() as server:
        monkeypatch.setenv(GMS_URL_ENV, server.url)
        monkeypatch.setenv(GMS_TOKEN_ENV, TOKEN)
        runner.invoke(app, ["ingest-datahub", "--export-dir", str(mini_export_dir), "--yes"])
        runner.invoke(
            app,
            [
                "verify-ingestion",
                "--export-dir",
                str(mini_export_dir),
                "--output-dir",
                str(tmp_path / "rt"),
            ],
        )
    for path in (tmp_path / "rt").iterdir():
        assert TOKEN.encode() not in path.read_bytes(), path.name
    assert (tmp_path / "rt" / LEAK_FINDINGS_NAME).is_file()
