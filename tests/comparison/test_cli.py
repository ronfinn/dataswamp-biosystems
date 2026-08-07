"""CLI behaviour, determinism and read-only guarantees for ``compare-runs``.

The determinism and read-only tests are the load-bearing ones. A comparison that
moved between runs would make every published regression unciteable, and a
comparison that wrote into an evaluation directory would corrupt the very
artefact the next comparison reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataswamp_biosystems.cli import app
from dataswamp_biosystems.comparison import (
    COMPARISON_REPORT_NAME,
    COMPARISON_SCHEMA_VERSION,
    COMPARISON_SUMMARY_NAME,
    CONTROL_REGRESSIONS_NAME,
    METRIC_DELTAS_NAME,
    PAIR_TRANSITIONS_NAME,
    REMEDIATION_REGRESSIONS_NAME,
    RULE_REGRESSIONS_NAME,
)
from dataswamp_biosystems.evaluation.writer import EVALUATION_SUMMARY_NAME
from dataswamp_biosystems.provenance import PROVENANCE_NAME
from tests.comparison.conftest import DEFECTS, RESERVED_CONTROL, finding
from tests.evaluation.conftest import RULE_AUTO

runner = CliRunner()

EXPECTED_FILES = {
    COMPARISON_SUMMARY_NAME,
    METRIC_DELTAS_NAME,
    PAIR_TRANSITIONS_NAME,
    RULE_REGRESSIONS_NAME,
    CONTROL_REGRESSIONS_NAME,
    REMEDIATION_REGRESSIONS_NAME,
    COMPARISON_REPORT_NAME,
    PROVENANCE_NAME,
}


def _compare(baseline: Path, candidate: Path, output: Path, *extra: str):  # noqa: ANN202
    return runner.invoke(
        app,
        [
            "compare-runs",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--output-dir",
            str(output),
            *extra,
        ],
    )


def _tree(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_comparing_two_runs_succeeds_and_writes_every_file(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    output = tmp_path / "comparison"
    result = _compare(perfect_run, silent_run, output)
    assert result.exit_code == 0, result.output
    assert {path.name for path in output.iterdir()} == EXPECTED_FILES


def test_the_summary_declares_its_own_schema_version(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    """A comparison-specific schema. No other layer's version is touched."""
    output = tmp_path / "comparison"
    _compare(perfect_run, silent_run, output)
    summary = json.loads((output / COMPARISON_SUMMARY_NAME).read_text(encoding="utf-8"))
    assert summary["comparison_schema_version"] == COMPARISON_SCHEMA_VERSION
    assert summary["comparator_version"]


def test_provenance_records_the_comparison_layer(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    output = tmp_path / "comparison"
    _compare(perfect_run, silent_run, output)
    provenance = json.loads((output / PROVENANCE_NAME).read_text(encoding="utf-8"))
    assert provenance["layer"] == "comparison"
    assert provenance["scenario"]["baseline_prediction_sha256"]
    assert provenance["scenario"]["candidate_prediction_sha256"]


# -- determinism --------------------------------------------------------------


def test_two_comparison_runs_are_byte_identical(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert _compare(perfect_run, silent_run, first).exit_code == 0
    assert _compare(perfect_run, silent_run, second).exit_code == 0
    assert _tree(first) == _tree(second)


def test_rerunning_into_the_same_directory_is_byte_identical(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    output = tmp_path / "comparison"
    assert _compare(perfect_run, silent_run, output).exit_code == 0
    before = _tree(output)
    assert _compare(perfect_run, silent_run, output, "--force").exit_code == 0
    assert _tree(output) == before


# -- read-only ----------------------------------------------------------------


def test_neither_input_evaluation_directory_is_modified(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    baseline_before = _tree(perfect_run)
    candidate_before = _tree(silent_run)
    assert _compare(perfect_run, silent_run, tmp_path / "comparison").exit_code == 0
    assert _tree(perfect_run) == baseline_before
    assert _tree(silent_run) == candidate_before


def test_the_output_may_not_replace_an_input_evaluation_directory(
    perfect_run: Path, silent_run: Path
) -> None:
    """``--force`` overrides the non-empty check, never path safety."""
    result = _compare(perfect_run, silent_run, perfect_run, "--force")
    assert result.exit_code == 2
    assert "Refusing" in result.output


def test_the_output_may_not_contain_an_input_evaluation_directory(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    result = _compare(perfect_run, silent_run, perfect_run.parent, "--force")
    assert result.exit_code == 2


def test_a_non_empty_output_directory_needs_force(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    output = tmp_path / "comparison"
    output.mkdir()
    (output / "existing.txt").write_text("keep me", encoding="utf-8")
    result = _compare(perfect_run, silent_run, output)
    assert result.exit_code == 2
    assert "not empty" in result.output
    assert (output / "existing.txt").read_text(encoding="utf-8") == "keep me"


# -- error handling -----------------------------------------------------------


def test_an_incompatible_pair_of_runs_exits_one_and_names_the_field(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    path = silent_run / EVALUATION_SUMMARY_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["benchmark"]["profile"] = "some-other-profile"
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    output = tmp_path / "comparison"
    result = _compare(perfect_run, silent_run, output)
    assert result.exit_code == 1
    assert "profile" in result.output
    assert "some-other-profile" in result.output
    assert not output.exists()


def test_a_missing_evaluation_directory_exits_two(perfect_run: Path, tmp_path: Path) -> None:
    result = _compare(perfect_run, tmp_path / "nowhere", tmp_path / "comparison")
    assert result.exit_code == 2
    assert "Could not read" in result.output


def test_a_directory_that_is_not_an_evaluation_exits_two(perfect_run: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _compare(perfect_run, empty, tmp_path / "comparison")
    assert result.exit_code == 2
    assert "missing" in result.output


def test_malformed_evaluation_json_exits_two(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    (silent_run / EVALUATION_SUMMARY_NAME).write_text("{not json", encoding="utf-8")
    result = _compare(perfect_run, silent_run, tmp_path / "comparison")
    assert result.exit_code == 2
    assert "not valid JSON" in result.output


def test_a_truncated_summary_exits_two(perfect_run: Path, silent_run: Path, tmp_path: Path) -> None:
    """A summary missing the keys a comparison needs is malformed, not empty."""
    (silent_run / EVALUATION_SUMMARY_NAME).write_text('{"benchmark": {}}', encoding="utf-8")
    result = _compare(perfect_run, silent_run, tmp_path / "comparison")
    assert result.exit_code == 2
    assert "missing required key" in result.output


def test_a_malformed_jsonl_record_exits_two(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    (silent_run / "finding-results.jsonl").write_text("[]\n", encoding="utf-8")
    result = _compare(perfect_run, silent_run, tmp_path / "comparison")
    assert result.exit_code == 2


# -- reporting ----------------------------------------------------------------


def test_a_regression_does_not_fail_the_command(
    perfect_run: Path, silent_run: Path, tmp_path: Path
) -> None:
    """Issue #17 answers what changed; gating is a policy question, not this one."""
    result = _compare(perfect_run, silent_run, tmp_path / "comparison")
    assert result.exit_code == 0
    assert "newly broken" in result.output


def test_control_damage_appears_in_the_command_output(
    perfect_run: Path, make_run, tmp_path: Path
) -> None:  # noqa: ANN001
    candidate = make_run(
        "flags-reserved",
        [finding(e, r) for e, r in DEFECTS] + [finding(RESERVED_CONTROL, RULE_AUTO)],
    )
    result = _compare(perfect_run, candidate, tmp_path / "comparison")
    assert result.exit_code == 0
    assert "1 new (1 on reserved controls)" in result.output


def test_the_markdown_report_names_the_reserved_control_regression(
    perfect_run: Path, make_run, tmp_path: Path
) -> None:  # noqa: ANN001
    candidate = make_run(
        "flags-reserved",
        [finding(e, r) for e, r in DEFECTS] + [finding(RESERVED_CONTROL, RULE_AUTO)],
    )
    output = tmp_path / "comparison"
    _compare(perfect_run, candidate, output)
    report = (output / COMPARISON_REPORT_NAME).read_text(encoding="utf-8")
    assert "New reserved-control false positives: 1" in report
    assert "Control preservation" in report


@pytest.mark.parametrize("name", sorted(EXPECTED_FILES - {COMPARISON_REPORT_NAME}))
def test_every_json_output_is_parseable(
    perfect_run: Path, silent_run: Path, tmp_path: Path, name: str
) -> None:
    output = tmp_path / "comparison"
    _compare(perfect_run, silent_run, output)
    text = (output / name).read_text(encoding="utf-8")
    if name.endswith(".jsonl"):
        for line in text.splitlines():
            if line.strip():
                json.loads(line)
    else:
        json.loads(text)
