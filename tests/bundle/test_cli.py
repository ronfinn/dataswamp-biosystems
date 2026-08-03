"""CLI behaviour for build-bundle, verify-bundle and export-datahub.

Path safety, non-empty handling and ``--force`` are covered here for the three
new commands specifically; ``tests/test_cli_output_safety.py`` covers the shared
policy itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataswamp_biosystems.bundle import CHECKSUMS_NAME, MANIFEST_NAME, Layer
from dataswamp_biosystems.cli import app

runner = CliRunner()


def _build(target: Path, layers: dict[Layer, Path], *extra: str) -> object:
    args = ["build-bundle", "--output-dir", str(target)]
    for layer, path in layers.items():
        args += [f"--{layer.value}-dir", str(path), "--layer", layer.value]
    return runner.invoke(app, [*args, *extra])


def test_build_and_verify_round_trip(generated_layers: dict[Layer, Path], tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    built = _build(target, generated_layers)
    assert built.exit_code == 0, built.output
    assert "Bundle written to" in built.output

    verified = runner.invoke(app, ["verify-bundle", str(target)])
    assert verified.exit_code == 0, verified.output
    assert "is valid" in verified.output
    assert "truth, estate, observed, evaluation" in verified.output


def test_build_defaults_to_every_layer_that_exists(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    target = tmp_path / "bundle"
    result = runner.invoke(
        app,
        [
            "build-bundle",
            "--truth-dir",
            str(generated_layers[Layer.TRUTH]),
            "--estate-dir",
            str(generated_layers[Layer.ESTATE]),
            "--observed-dir",
            str(tmp_path / "absent"),
            "--evaluation-dir",
            str(tmp_path / "absent"),
            "--output-dir",
            str(target),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads((target / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert payload["layers"] == ["truth", "estate"]


def test_build_without_a_truth_graph_fails_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "build-bundle",
            "--truth-dir",
            str(tmp_path / "absent"),
            "--estate-dir",
            str(tmp_path / "absent"),
            "--observed-dir",
            str(tmp_path / "absent"),
            "--evaluation-dir",
            str(tmp_path / "absent"),
            "--output-dir",
            str(tmp_path / "bundle"),
        ],
    )
    assert result.exit_code == 2
    assert "must include the truth layer" in result.output


def test_build_refuses_a_protected_output_directory(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    """A bundle may not replace a layer it is packaging."""
    truth = generated_layers[Layer.TRUTH]
    result = _build(truth.parent, {Layer.TRUTH: truth})
    assert result.exit_code == 2
    assert "Refusing to generate into" in result.output


def test_build_refuses_the_config_directory(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    result = _build(Path("config"), {Layer.TRUTH: generated_layers[Layer.TRUTH]})
    assert result.exit_code == 2
    assert "canonical configuration directory" in result.output


def test_build_refuses_a_non_empty_output_without_force(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    target = tmp_path / "bundle"
    target.mkdir()
    (target / "keep.txt").write_text("mine", encoding="utf-8")
    result = _build(target, {Layer.TRUTH: generated_layers[Layer.TRUTH]})
    assert result.exit_code == 2
    assert "pass --force" in result.output
    assert (target / "keep.txt").exists()

    forced = _build(target, {Layer.TRUTH: generated_layers[Layer.TRUTH]}, "--force")
    assert forced.exit_code == 0
    assert not (target / "keep.txt").exists()


def test_invalid_input_fails_before_replacing_a_previous_bundle(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    target = tmp_path / "bundle"
    assert _build(target, {Layer.TRUTH: generated_layers[Layer.TRUTH]}).exit_code == 0
    before = (target / MANIFEST_NAME).read_bytes()

    broken = tmp_path / "broken-truth"
    broken.mkdir()
    (broken / "assets.jsonl").write_text("", encoding="utf-8")
    result = _build(target, {Layer.TRUTH: broken}, "--force")
    assert result.exit_code == 2
    assert (target / MANIFEST_NAME).read_bytes() == before


def test_verify_reports_a_tampered_file_and_exits_one(mutable_bundle: Path) -> None:
    target = mutable_bundle / "truth" / "assets.jsonl"
    target.write_bytes(b"tampered\n")
    result = runner.invoke(app, ["verify-bundle", str(mutable_bundle)])
    assert result.exit_code == 1
    assert "truth/assets.jsonl" in result.output
    assert "checksum-mismatch" in result.output


def test_verify_reports_a_missing_manifest_and_exits_two(tmp_path: Path) -> None:
    empty = tmp_path / "bundle"
    empty.mkdir()
    result = runner.invoke(app, ["verify-bundle", str(empty)])
    assert result.exit_code == 2
    assert "no bundle manifest" in result.output


def test_verify_accepts_extra_files_with_no_strict(mutable_bundle: Path) -> None:
    (mutable_bundle / "NOTES.txt").write_text("local scratch", encoding="utf-8")
    assert runner.invoke(app, ["verify-bundle", str(mutable_bundle)]).exit_code == 1
    relaxed = runner.invoke(app, ["verify-bundle", str(mutable_bundle), "--no-strict"])
    assert relaxed.exit_code == 0


def test_export_datahub_defaults_to_observed(full_bundle_dir: Path, tmp_path: Path) -> None:
    target = tmp_path / "export"
    result = runner.invoke(
        app, ["export-datahub", "--bundle", str(full_bundle_dir), "--output-dir", str(target)]
    )
    assert result.exit_code == 0, result.output
    assert "mode observed" in result.output
    assert "PRIVILEGED" not in result.output


def test_export_datahub_truth_mode_announces_privilege(
    full_bundle_dir: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "export-datahub",
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


def test_export_refuses_to_write_inside_the_bundle(full_bundle_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-datahub",
            "--bundle",
            str(full_bundle_dir),
            "--output-dir",
            str(full_bundle_dir / "adapters"),
        ],
    )
    assert result.exit_code == 2
    assert "benchmark bundle directory" in result.output


def test_export_refuses_a_broken_bundle(mutable_bundle: Path, tmp_path: Path) -> None:
    (mutable_bundle / CHECKSUMS_NAME).write_text("garbage\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["export-datahub", "--bundle", str(mutable_bundle), "--output-dir", str(tmp_path / "e")],
    )
    assert result.exit_code == 2
    assert not (tmp_path / "e").exists()


@pytest.mark.parametrize("command", ["build-bundle", "verify-bundle", "export-datahub"])
def test_commands_are_registered_with_help(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert command in result.output
