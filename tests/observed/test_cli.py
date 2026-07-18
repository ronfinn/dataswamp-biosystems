"""CLI and cross-process determinism tests for the observed-state commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dataswamp_biosystems.observed.writer import OBSERVED_GRAPH_NAME, TRUTH_INPUTS_NAME
from dataswamp_biosystems.truth.writer import MANIFEST_NAME
from tests.observed.conftest import TEST_SEED


def _run(args: list[str], hash_seed: str = "0") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    return subprocess.run(
        [sys.executable, "-m", "dataswamp_biosystems.cli", *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(directory)): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def _make_truth(config_dir: Path, truth_dir: Path, hash_seed: str = "0") -> None:
    result = _run(
        [
            "generate-truth",
            "--seed",
            str(TEST_SEED),
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(truth_dir),
        ],
        hash_seed=hash_seed,
    )
    assert result.returncode == 0, result.stderr


def test_list_defects_exits_zero() -> None:
    result = _run(["list-defects"])
    assert result.returncode == 0, result.stderr
    assert "defect rule" in result.stdout


def test_validate_defects_exits_zero() -> None:
    result = _run(["validate-defects"])
    assert result.returncode == 0, result.stderr
    assert "valid" in result.stdout


def test_inject_and_validate(config_dir: Path, tmp_path: Path) -> None:
    truth_dir = tmp_path / "truth"
    out = tmp_path / "observed"
    _make_truth(config_dir, truth_dir)
    inject = _run(
        [
            "inject-defects",
            "--truth",
            str(truth_dir / MANIFEST_NAME),
            "--seed",
            str(TEST_SEED),
            "--profile",
            "demo",
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(out),
        ]
    )
    assert inject.returncode == 0, inject.stderr
    assert (out / OBSERVED_GRAPH_NAME).exists()
    assert (out / TRUTH_INPUTS_NAME).exists()

    val = _run(["validate-observed", "--observed-dir", str(out), "--config-dir", str(config_dir)])
    assert val.returncode == 0, val.stderr


def test_invalid_profile_is_rejected(config_dir: Path, tmp_path: Path) -> None:
    truth_dir = tmp_path / "truth"
    _make_truth(config_dir, truth_dir)
    result = _run(
        [
            "inject-defects",
            "--truth",
            str(truth_dir / MANIFEST_NAME),
            "--profile",
            "bogus",
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(tmp_path / "observed"),
        ]
    )
    assert result.returncode != 0


def test_output_inside_truth_is_rejected(config_dir: Path, tmp_path: Path) -> None:
    truth_dir = tmp_path / "truth"
    _make_truth(config_dir, truth_dir)
    result = _run(
        [
            "inject-defects",
            "--truth",
            str(truth_dir / MANIFEST_NAME),
            "--seed",
            str(TEST_SEED),
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(truth_dir / "observed"),
        ]
    )
    assert result.returncode == 2, result.stderr


def test_cross_process_output_is_byte_identical(config_dir: Path, tmp_path: Path) -> None:
    truth_dir = tmp_path / "truth"
    _make_truth(config_dir, truth_dir)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    for out, hs in ((out_a, "0"), (out_b, "1")):
        result = _run(
            [
                "inject-defects",
                "--truth",
                str(truth_dir / MANIFEST_NAME),
                "--seed",
                str(TEST_SEED),
                "--profile",
                "demo",
                "--config-dir",
                str(config_dir),
                "--output-dir",
                str(out),
            ],
            hash_seed=hs,
        )
        assert result.returncode == 0, result.stderr
    assert _snapshot(out_a) == _snapshot(out_b)
