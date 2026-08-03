"""The v0.1 public surface: the CLI contract, the demo, and the stable imports.

These tests protect what a new user actually touches. They are deliberately
about *behaviour* — that a documented command exists and works, that the demo is
deterministic, that a name promised as stable is importable — and never about
documentation prose.
"""

from __future__ import annotations

import filecmp
import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataswamp_biosystems.cli import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"

# The public workflow, in the order the documentation presents it. A command
# disappearing or being renamed is a breaking change to the release surface.
DOCUMENTED_COMMANDS = (
    "version",
    "validate-config",
    "generate-truth",
    "validate-truth",
    "generate-files",
    "validate-files",
    "list-defects",
    "validate-defects",
    "inject-defects",
    "validate-observed",
    "evaluate",
    "build-bundle",
    "verify-bundle",
    "export-datahub",
    "list-baselines",
    "run-baseline",
    "demo",
)

# Names ``docs/public-api.md`` promises are importable and stable.
STABLE_IMPORTS: dict[str, tuple[str, ...]] = {
    "dataswamp_biosystems": ("__version__",),
    "dataswamp_biosystems.bundle": (
        "BundleReader",
        "BundleManifest",
        "Layer",
        "verify_bundle",
        "BundleError",
        "BundleConfigError",
        "BundleValidationError",
    ),
    "dataswamp_biosystems.evaluation": (
        "Prediction",
        "PredictedRemediation",
        "PREDICTION_SCHEMA_VERSION",
        "parse_predictions",
        "load_predictions",
        "GroundTruth",
        "load_ground_truth",
        "evaluate",
        "prediction_digest",
        "write_evaluation",
        "EvaluationError",
        "EvaluationConfigError",
        "PredictionValidationError",
    ),
    "dataswamp_biosystems.baselines": (
        "BASELINE_NAMES",
        "BaselineAgent",
        "BaselineInfo",
        "BaselineRun",
        "ObservedInput",
        "baseline_infos",
        "get_baseline",
        "run_baseline",
        "render_predictions",
        "write_predictions",
        "BaselineError",
        "UnknownBaselineError",
        "ObservedInputError",
    ),
    "dataswamp_biosystems.adapters.datahub": ("ExportMode", "export_datahub"),
    "dataswamp_biosystems.examples": ("example_path", "examples_dir", "EXAMPLE_SUBMISSIONS"),
}


@pytest.mark.parametrize("module_name, names", sorted(STABLE_IMPORTS.items()))
def test_stable_public_imports_are_available(module_name: str, names: tuple[str, ...]) -> None:
    module = importlib.import_module(module_name)
    missing = [name for name in names if not hasattr(module, name)]
    assert not missing, f"{module_name} no longer exports {missing}"


@pytest.mark.parametrize("command", DOCUMENTED_COMMANDS)
def test_every_documented_command_exists_and_has_help(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0, result.output


def test_the_root_help_lists_every_documented_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Typer wraps long lines, so match on the command name alone.
    for command in DOCUMENTED_COMMANDS:
        assert command in result.output, f"{command} is missing from the root help"


class TestDemo:
    """The quick start a new user runs first."""

    @pytest.fixture(scope="class")
    @classmethod
    def demo_dir(cls, tmp_path_factory: pytest.TempPathFactory) -> Path:
        target = tmp_path_factory.mktemp("demo") / "run"
        result = runner.invoke(
            app, ["demo", "--output-dir", str(target), "--config-dir", str(CONFIG_DIR)]
        )
        assert result.exit_code == 0, result.output
        return target

    @pytest.mark.slow
    def test_it_produces_every_advertised_artefact(self, demo_dir: Path) -> None:
        for relative in (
            "generated/truth/truth-graph.json",
            "generated/estate",
            "generated/observed/expected-findings.jsonl",
            "generated/observed/controls.jsonl",
            "generated/observed/rule-scope.jsonl",
            "generated/evaluation/evaluation-report.md",
            "bundle/benchmark-manifest.json",
            "bundle/LICENSES.md",
            "bundle/checksums.sha256",
            "export/datahub",
        ):
            assert (demo_dir / relative).exists(), f"demo did not produce {relative}"

    @pytest.mark.slow
    def test_a_baseline_runs_against_what_the_demo_generated(
        self, demo_dir: Path, tmp_path: Path
    ) -> None:
        """The documented follow-on step: run a baseline over the demo's output."""
        output = tmp_path / "baseline.jsonl"
        result = runner.invoke(
            app,
            [
                "run-baseline",
                "--agent",
                "rule-based",
                "--observed-dir",
                str(demo_dir / "generated" / "observed"),
                "--output",
                str(output),
                "--evaluate",
                "--evaluation-dir",
                str(tmp_path / "evaluation"),
            ],
        )
        assert result.exit_code == 0, result.output
        assert output.read_text(encoding="utf-8").strip()
        assert (tmp_path / "evaluation" / "evaluation-report.md").is_file()

    @pytest.mark.slow
    def test_the_bundle_it_builds_verifies(self, demo_dir: Path) -> None:
        result = runner.invoke(app, ["verify-bundle", str(demo_dir / "bundle")])
        assert result.exit_code == 0, result.output

    @pytest.mark.slow
    def test_it_is_deterministic(self, demo_dir: Path, tmp_path: Path) -> None:
        """A second run into a fresh directory must be byte-identical."""
        second = tmp_path / "again"
        result = runner.invoke(
            app, ["demo", "--output-dir", str(second), "--config-dir", str(CONFIG_DIR)]
        )
        assert result.exit_code == 0, result.output

        mismatches = _compare_trees(demo_dir, second)
        assert not mismatches, f"demo output differs between runs: {sorted(mismatches)}"

    def test_it_refuses_a_non_empty_directory_without_force(self, tmp_path: Path) -> None:
        target = tmp_path / "occupied"
        target.mkdir()
        (target / "important.txt").write_text("do not clobber me", encoding="utf-8")

        result = runner.invoke(app, ["demo", "--output-dir", str(target)])

        assert result.exit_code == 2
        assert "not empty" in result.output
        assert (target / "important.txt").read_text(encoding="utf-8") == "do not clobber me"

    def test_it_refuses_to_write_over_its_own_configuration(self) -> None:
        result = runner.invoke(
            app, ["demo", "--output-dir", str(CONFIG_DIR), "--config-dir", str(CONFIG_DIR)]
        )
        assert result.exit_code == 2
        assert "Refusing" in result.output

    def test_it_reports_a_missing_submission_without_generating(self, tmp_path: Path) -> None:
        target = tmp_path / "out"
        result = runner.invoke(
            app,
            [
                "demo",
                "--output-dir",
                str(target),
                "--predictions",
                str(tmp_path / "nope.jsonl"),
            ],
        )
        assert result.exit_code == 2
        assert "no such file" in result.output
        assert not target.exists() or not any(target.iterdir())


def _compare_trees(left: Path, right: Path) -> set[str]:
    """Return the relative paths that differ between two generated trees."""
    left_files = {p.relative_to(left).as_posix() for p in left.rglob("*") if p.is_file()}
    right_files = {p.relative_to(right).as_posix() for p in right.rglob("*") if p.is_file()}
    mismatches = left_files ^ right_files
    for relative in left_files & right_files:
        if not filecmp.cmp(left / relative, right / relative, shallow=False):
            mismatches.add(relative)
    return mismatches
