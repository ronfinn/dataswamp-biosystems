"""CLI and cross-process determinism tests for the estate commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dataswamp_biosystems.estate.writer import MANIFEST_NAME
from tests.estate.conftest import TEST_SEED


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


def test_generate_and_validate_tiny(config_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "estate"
    gen = _run(
        [
            "generate-files",
            "--profile",
            "tiny",
            "--seed",
            str(TEST_SEED),
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(out),
        ]
    )
    assert gen.returncode == 0, gen.stderr
    assert (out / MANIFEST_NAME).exists()

    val = _run(["validate-files", "--estate-dir", str(out), "--config-dir", str(config_dir)])
    assert val.returncode == 0, val.stderr


def test_invalid_profile_is_rejected(config_dir: Path, tmp_path: Path) -> None:
    result = _run(
        [
            "generate-files",
            "--profile",
            "catastrophic",
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(tmp_path / "estate"),
        ]
    )
    assert result.returncode != 0


def test_cross_process_output_is_byte_identical(config_dir: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    for out, hs in ((out_a, "0"), (out_b, "1")):
        result = _run(
            [
                "generate-files",
                "--profile",
                "tiny",
                "--seed",
                str(TEST_SEED),
                "--config-dir",
                str(config_dir),
                "--output-dir",
                str(out),
            ],
            hash_seed=hs,
        )
        assert result.returncode == 0, result.stderr
    assert _snapshot(out_a) == _snapshot(out_b)
