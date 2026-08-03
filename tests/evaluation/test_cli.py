"""CLI behaviour for ``dataswamp evaluate``: outputs, exit codes and path safety.

Every path used here lives under ``tmp_path`` or a session temporary directory,
so no test can reach the real repository, ``config/`` or any user directory —
including the cases that deliberately request an unsafe output path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataswamp_biosystems.cli import app
from dataswamp_biosystems.evaluation import (
    CATEGORY_METRICS_NAME,
    EVALUATION_REPORT_NAME,
    EVALUATION_SUMMARY_NAME,
    FINDING_RESULTS_NAME,
    REMEDIATION_RESULTS_NAME,
    RULE_METRICS_NAME,
)
from dataswamp_biosystems.provenance import PROVENANCE_NAME

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]

runner = CliRunner()

ALL_OUTPUTS = (
    EVALUATION_SUMMARY_NAME,
    FINDING_RESULTS_NAME,
    REMEDIATION_RESULTS_NAME,
    RULE_METRICS_NAME,
    CATEGORY_METRICS_NAME,
    EVALUATION_REPORT_NAME,
    PROVENANCE_NAME,
)


def _run(observed: Path, predictions: Path, output: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "evaluate",
            "--observed-dir",
            str(observed),
            "--predictions",
            str(predictions),
            "--output-dir",
            str(output),
            *extra,
        ],
    )


@pytest.fixture()
def predictions(tmp_path: Path) -> Path:
    target = tmp_path / "predictions.jsonl"
    shutil.copyfile(FIXTURE_DIR / "partial.jsonl", target)
    return target


def test_a_successful_evaluation_writes_every_report(
    tiny_observed_dir: Path, predictions: Path, tmp_path: Path
) -> None:
    out = tmp_path / "evaluation"
    result = _run(tiny_observed_dir, predictions, out)
    assert result.exit_code == 0, result.output
    for name in ALL_OUTPUTS:
        assert (out / name).is_file(), name
    summary = json.loads((out / EVALUATION_SUMMARY_NAME).read_text())
    assert summary["findings"]["overall_micro"]["counts"]["tp"] == 3
    assert summary["submission"]["prediction_sha256"]
    assert summary["benchmark"]["ground_truth_fingerprint"]


def test_the_terminal_summary_reports_the_headline_numbers(
    tiny_observed_dir: Path, predictions: Path, tmp_path: Path
) -> None:
    result = _run(tiny_observed_dir, predictions, tmp_path / "evaluation")
    assert "TP 3" in result.output
    assert "reserved-control false positives: 0" in result.output
    assert "out-of-scope false positives: 1" in result.output


def test_invalid_predictions_fail_before_any_output_is_replaced(
    tiny_observed_dir: Path, tmp_path: Path
) -> None:
    """The previous evaluation must survive a broken submission."""
    out = tmp_path / "evaluation"
    good = tmp_path / "good.jsonl"
    shutil.copyfile(FIXTURE_DIR / "perfect.jsonl", good)
    assert _run(tiny_observed_dir, good, out).exit_code == 0
    before = (out / EVALUATION_SUMMARY_NAME).read_bytes()

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"schema_version":1,"prediction_id":"x","entity_id":"ds-nowhere"}\n')
    result = _run(tiny_observed_dir, bad, out, "--force")
    assert result.exit_code == 1
    assert "unknown-entity" in result.output
    assert (out / EVALUATION_SUMMARY_NAME).read_bytes() == before


def test_a_non_empty_output_directory_is_refused_without_force(
    tiny_observed_dir: Path, predictions: Path, tmp_path: Path
) -> None:
    out = tmp_path / "evaluation"
    assert _run(tiny_observed_dir, predictions, out).exit_code == 0
    again = _run(tiny_observed_dir, predictions, out)
    assert again.exit_code == 2
    assert "not empty" in again.output


def test_force_replaces_the_output_safely(
    tiny_observed_dir: Path, predictions: Path, tmp_path: Path
) -> None:
    out = tmp_path / "evaluation"
    assert _run(tiny_observed_dir, predictions, out).exit_code == 0
    (out / "stale-artefact.txt").write_text("left over from a previous run")
    assert _run(tiny_observed_dir, predictions, out, "--force").exit_code == 0
    assert not (out / "stale-artefact.txt").exists()
    assert (out / EVALUATION_SUMMARY_NAME).is_file()


def test_the_ground_truth_directory_cannot_be_the_output(
    tiny_observed_dir: Path, predictions: Path
) -> None:
    result = _run(tiny_observed_dir, predictions, tiny_observed_dir, "--force")
    assert result.exit_code == 2
    assert "observed ground-truth directory" in result.output


def test_the_output_may_not_contain_the_ground_truth(
    tiny_observed_dir: Path, predictions: Path
) -> None:
    result = _run(tiny_observed_dir, predictions, tiny_observed_dir.parent, "--force")
    assert result.exit_code == 2
    assert "contains" in result.output


def test_the_output_may_not_contain_the_prediction_file(
    tiny_observed_dir: Path, predictions: Path, tmp_path: Path
) -> None:
    """``--force`` must never become a route to deleting the submission itself."""
    result = _run(tiny_observed_dir, predictions, predictions.parent, "--force")
    assert result.exit_code == 2
    assert "prediction file" in result.output
    assert predictions.is_file()


def test_a_missing_ground_truth_directory_exits_two(predictions: Path, tmp_path: Path) -> None:
    result = _run(tmp_path / "nowhere", predictions, tmp_path / "evaluation")
    assert result.exit_code == 2
    assert "Could not read ground truth" in result.output


def test_an_incomplete_ground_truth_directory_names_what_is_missing(
    tiny_observed_dir: Path, predictions: Path, tmp_path: Path
) -> None:
    partial = tmp_path / "partial-observed"
    partial.mkdir()
    shutil.copyfile(tiny_observed_dir / "controls.jsonl", partial / "controls.jsonl")
    result = _run(partial, predictions, tmp_path / "evaluation")
    assert result.exit_code == 2
    assert "rule-scope.jsonl" in result.output


def test_a_missing_prediction_file_exits_two(tiny_observed_dir: Path, tmp_path: Path) -> None:
    result = _run(tiny_observed_dir, tmp_path / "missing.jsonl", tmp_path / "evaluation")
    assert result.exit_code == 2
    assert "Could not read predictions" in result.output


def test_report_files_are_byte_identical_across_runs(
    tiny_observed_dir: Path, predictions: Path, tmp_path: Path
) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    assert _run(tiny_observed_dir, predictions, first).exit_code == 0
    assert _run(tiny_observed_dir, predictions, second).exit_code == 0
    for name in ALL_OUTPUTS:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_reports_are_identical_across_processes_and_hash_seeds(
    tiny_observed_dir: Path, predictions: Path, tmp_path: Path
) -> None:
    """A different ``PYTHONHASHSEED`` must not move a single byte.

    Run in real subprocesses: ``PYTHONHASHSEED`` is fixed at interpreter start,
    so an in-process check could not detect a dependence on it.
    """
    digests: list[bytes] = []
    for index, hash_seed in enumerate(("0", "12345")):
        out = tmp_path / f"proc-{index}"
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "dataswamp_biosystems.cli",
                "evaluate",
                "--observed-dir",
                str(tiny_observed_dir),
                "--predictions",
                str(predictions),
                "--output-dir",
                str(out),
            ],
            capture_output=True,
            env=env,
            cwd=REPO_ROOT,
        )
        assert completed.returncode == 0, completed.stderr.decode()
        digests.append(
            b"".join((out / name).read_bytes() for name in ALL_OUTPUTS if name != PROVENANCE_NAME)
        )
    assert digests[0] == digests[1]
