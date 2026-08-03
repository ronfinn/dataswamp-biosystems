"""The ``run-baseline`` and ``list-baselines`` commands.

Output-path safety gets the most attention here: ``run-baseline`` is the first
command that writes a *file* rather than replacing a directory, so it applies the
shared containment policy to the file itself, and that difference is worth
pinning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataswamp_biosystems.baselines import BASELINE_NAMES
from dataswamp_biosystems.cli import app
from dataswamp_biosystems.observed.writer import OBSERVED_GRAPH_NAME

runner = CliRunner()


def test_list_baselines_names_every_agent_and_its_reads() -> None:
    result = runner.invoke(app, ["list-baselines"])
    assert result.exit_code == 0
    for name in BASELINE_NAMES:
        assert name in result.stdout
    assert "reads:" in result.stdout


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_run_baseline_writes_a_submission(
    name: str, real_observed_dir: Path, tmp_path: Path
) -> None:
    output = tmp_path / "predictions.jsonl"
    result = runner.invoke(
        app,
        [
            "run-baseline",
            "--agent",
            name,
            "--observed-dir",
            str(real_observed_dir),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert output.is_file()
    for line in output.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert record["schema_version"] == 1
        assert record["agent"]["name"] == name
    assert name in result.stdout
    assert "scenario:" in result.stdout


def test_run_baseline_reports_an_unknown_agent(real_observed_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run-baseline",
            "--agent",
            "nonesuch",
            "--observed-dir",
            str(real_observed_dir),
            "--output",
            str(tmp_path / "p.jsonl"),
        ],
    )
    assert result.exit_code == 2
    assert "unknown baseline" in result.output


def test_run_baseline_refuses_to_overwrite_without_force(
    real_observed_dir: Path, tmp_path: Path
) -> None:
    output = tmp_path / "predictions.jsonl"
    output.write_text("existing work\n", encoding="utf-8")
    args = [
        "run-baseline",
        "--agent",
        "null",
        "--observed-dir",
        str(real_observed_dir),
        "--output",
        str(output),
    ]
    refused = runner.invoke(app, args)
    assert refused.exit_code == 2
    assert "--force" in refused.output
    assert output.read_text(encoding="utf-8") == "existing work\n"

    forced = runner.invoke(app, [*args, "--force"])
    assert forced.exit_code == 0
    assert output.read_text(encoding="utf-8") == ""


def test_run_baseline_refuses_to_write_inside_the_observed_state(
    real_observed_dir: Path,
) -> None:
    """The submission must never be written into the ground truth it is scored against."""
    result = runner.invoke(
        app,
        [
            "run-baseline",
            "--agent",
            "null",
            "--observed-dir",
            str(real_observed_dir),
            "--output",
            str(real_observed_dir / "predictions.jsonl"),
        ],
    )
    assert result.exit_code == 2
    assert "Refusing to write" in result.output


def test_run_baseline_refuses_to_replace_the_observed_state(real_observed_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run-baseline",
            "--agent",
            "null",
            "--observed-dir",
            str(real_observed_dir),
            "--output",
            str(real_observed_dir),
        ],
    )
    assert result.exit_code == 2
    assert "Refusing to write" in result.output


def test_run_baseline_reports_an_unreadable_observed_state(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run-baseline",
            "--agent",
            "null",
            "--observed-dir",
            str(tmp_path / "missing"),
            "--output",
            str(tmp_path / "p.jsonl"),
        ],
    )
    assert result.exit_code == 2
    assert "Could not read the observed state" in result.output


def test_run_baseline_reports_a_malformed_observed_graph(tmp_path: Path) -> None:
    observed = tmp_path / "observed"
    observed.mkdir()
    (observed / OBSERVED_GRAPH_NAME).write_text("{oops", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "run-baseline",
            "--agent",
            "rule-based",
            "--observed-dir",
            str(observed),
            "--output",
            str(tmp_path / "p.jsonl"),
        ],
    )
    assert result.exit_code == 2
    assert "not valid JSON" in result.output


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_run_baseline_can_score_in_one_step(
    name: str, real_observed_dir: Path, tmp_path: Path
) -> None:
    """``--evaluate`` reuses the ordinary evaluator rather than a second scorer."""
    output = tmp_path / "predictions.jsonl"
    evaluation_dir = tmp_path / "evaluation"
    result = runner.invoke(
        app,
        [
            "run-baseline",
            "--agent",
            name,
            "--observed-dir",
            str(real_observed_dir),
            "--output",
            str(output),
            "--evaluate",
            "--evaluation-dir",
            str(evaluation_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (evaluation_dir / "evaluation-summary.json").is_file()
    assert (evaluation_dir / "evaluation-report.md").is_file()
    assert "precision" in result.stdout


def test_evaluate_scores_a_baseline_submission_the_ordinary_way(
    real_observed_dir: Path, tmp_path: Path
) -> None:
    """A baseline submission is an ordinary submission: no special-casing anywhere."""
    output = tmp_path / "predictions.jsonl"
    runner.invoke(
        app,
        [
            "run-baseline",
            "--agent",
            "rule-based",
            "--observed-dir",
            str(real_observed_dir),
            "--output",
            str(output),
        ],
    )
    result = runner.invoke(
        app,
        [
            "evaluate",
            "--observed-dir",
            str(real_observed_dir),
            "--predictions",
            str(output),
            "--output-dir",
            str(tmp_path / "evaluation"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    summary = json.loads(
        (tmp_path / "evaluation" / "evaluation-summary.json").read_text(encoding="utf-8")
    )
    assert summary["findings"]["overall_micro"]["counts"]["tp"] > 0


def test_two_runs_write_byte_identical_submissions(real_observed_dir: Path, tmp_path: Path) -> None:
    outputs = []
    for index in range(2):
        output = tmp_path / f"run-{index}.jsonl"
        result = runner.invoke(
            app,
            [
                "run-baseline",
                "--agent",
                "rule-based",
                "--observed-dir",
                str(real_observed_dir),
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.stdout
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
