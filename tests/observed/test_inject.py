"""Tests for on-disk injection: truth immutability, path safety, and determinism."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.errors import ObservedConfigError
from dataswamp_biosystems.observed.inject import (
    compute_truth_checksums,
    inject_defects,
)
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.writer import TRUTH_INPUTS_NAME
from dataswamp_biosystems.truth import GenerationPlan, generate_truth_graph
from dataswamp_biosystems.truth.writer import MANIFEST_NAME, write_truth_graph
from tests.observed.conftest import TEST_SEED


@pytest.fixture
def truth_dir(config: CanonicalConfig, plan: GenerationPlan, tmp_path: Path) -> Path:
    out = tmp_path / "truth"
    write_truth_graph(generate_truth_graph(config, plan, TEST_SEED), out)
    return out


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(directory)): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def test_truth_files_are_unchanged_by_injection(
    truth_dir: Path, config: CanonicalConfig, plan: GenerationPlan, tmp_path: Path
) -> None:
    before = _snapshot(truth_dir)
    inject_defects(
        truth_dir / MANIFEST_NAME, config, plan, ObservedProfile.DEMO, TEST_SEED, tmp_path / "obs"
    )
    assert _snapshot(truth_dir) == before


def test_truth_input_checksums_recorded(
    truth_dir: Path, config: CanonicalConfig, plan: GenerationPlan, tmp_path: Path
) -> None:
    report = inject_defects(
        truth_dir / MANIFEST_NAME, config, plan, ObservedProfile.DEMO, TEST_SEED, tmp_path / "obs"
    )
    assert report.truth_inputs["verified_unchanged"] is True
    assert report.truth_inputs["checksums"] == compute_truth_checksums(truth_dir)
    assert (tmp_path / "obs" / TRUTH_INPUTS_NAME).exists()


def test_output_inside_truth_is_refused(
    truth_dir: Path, config: CanonicalConfig, plan: GenerationPlan
) -> None:
    with pytest.raises(ObservedConfigError):
        inject_defects(
            truth_dir / MANIFEST_NAME,
            config,
            plan,
            ObservedProfile.DEMO,
            TEST_SEED,
            truth_dir / "observed",
        )


def test_injection_is_deterministic(
    truth_dir: Path, config: CanonicalConfig, plan: GenerationPlan, tmp_path: Path
) -> None:
    inject_defects(
        truth_dir / MANIFEST_NAME, config, plan, ObservedProfile.DEMO, TEST_SEED, tmp_path / "a"
    )
    inject_defects(
        truth_dir / MANIFEST_NAME, config, plan, ObservedProfile.DEMO, TEST_SEED, tmp_path / "b"
    )
    assert _snapshot(tmp_path / "a") == _snapshot(tmp_path / "b")


def test_drifted_truth_on_disk_is_rejected(
    truth_dir: Path, config: CanonicalConfig, plan: GenerationPlan, tmp_path: Path
) -> None:
    # Corrupt a shard so it no longer matches a regeneration from its seed.
    shard = truth_dir / "assets.jsonl"
    shard.write_bytes(shard.read_bytes() + b"\n")
    with pytest.raises(ObservedConfigError):
        inject_defects(
            truth_dir / MANIFEST_NAME,
            config,
            plan,
            ObservedProfile.DEMO,
            TEST_SEED,
            tmp_path / "obs",
        )
