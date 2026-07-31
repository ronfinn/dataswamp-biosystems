"""Determinism tests: same seed must yield byte-identical output.

Two layers of guard: in-process (regenerate and compare shard bytes) and
cross-process (run the CLI twice, under *different* ``PYTHONHASHSEED`` values, so
any reliance on hash-randomised set/dict ordering would surface as drift).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.truth import GenerationPlan, generate_truth_graph
from dataswamp_biosystems.truth.writer import shard_bytes
from tests.truth.conftest import TEST_SEED


def test_in_process_generation_is_deterministic(
    config: CanonicalConfig, plan: GenerationPlan
) -> None:
    first = shard_bytes(generate_truth_graph(config, plan, TEST_SEED))
    second = shard_bytes(generate_truth_graph(config, plan, TEST_SEED))
    assert first == second


def test_different_seed_changes_output(config: CanonicalConfig, plan: GenerationPlan) -> None:
    first = shard_bytes(generate_truth_graph(config, plan, TEST_SEED))
    other = shard_bytes(generate_truth_graph(config, plan, TEST_SEED + 1))
    assert first != other


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir()) if path.is_file()}


def _run_cli(config_dir: Path, output_dir: Path, hash_seed: str) -> None:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dataswamp_biosystems.cli",
            "generate-truth",
            "--seed",
            str(TEST_SEED),
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(output_dir),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_cross_process_output_is_byte_identical(config_dir: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    _run_cli(config_dir, out_a, hash_seed="0")
    _run_cli(config_dir, out_b, hash_seed="1")
    assert _snapshot(out_a) == _snapshot(out_b)
