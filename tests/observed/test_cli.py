"""CLI and cross-process determinism tests for the observed-state commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dataswamp_biosystems.observed.defects import (
    DEFECTS,
    REQUIRED_CONTRACT_STATES,
    contract_coverage,
    registry_rows,
)
from dataswamp_biosystems.observed.writer import (
    CONTROLS_NAME,
    INJECTED_DEFECTS_NAME,
    OBSERVED_GRAPH_NAME,
    RULE_SCOPE_NAME,
    TRUTH_INPUTS_NAME,
)
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


def test_list_defects_reports_counts_by_category() -> None:
    result = _run(["list-defects"])
    assert result.returncode == 0, result.stderr

    rows = registry_rows()
    expected: dict[str, int] = {}
    for row in rows:
        expected[row["category"]] = expected.get(row["category"], 0) + 1

    assert f"{len(rows)} defect rule(s) across {len(expected)} categories:" in result.stdout
    assert "Rules by category:" in result.stdout
    for category, count in expected.items():
        assert f"  {category}: {count}" in result.stdout


def test_list_defects_reports_severity_remediation_and_approval() -> None:
    """Each rule line names both contract dimensions, not one derived flag."""
    result = _run(["list-defects"])
    assert result.returncode == 0, result.stderr

    lines = {
        line.strip().split(" ", 1)[0]: line
        for line in result.stdout.splitlines()
        if line.startswith("  ")
    }
    seen_availability: set[str] = set()
    seen_approval: set[str] = set()
    for row in registry_rows():
        line = lines[row["rule_id"]]
        assert f"[{row['category']}/{row['severity']}]" in line
        assert f"remediation={row['remediation_availability']}" in line
        assert f"approval={row['approval_policy']}" in line
        if row["approver_role"] != "none":
            assert f"approver={row['approver_role']}" in line
        if row["non_remediable_reason"] != "none":
            assert f"reason={row['non_remediable_reason']}" in line
        seen_availability.add(row["remediation_availability"])
        seen_approval.add(row["approval_policy"])
    assert seen_availability == {"automatic", "manual", "none"}
    assert seen_approval == {"not-required", "required"}


def test_list_defects_reports_contract_state_coverage() -> None:
    result = _run(["list-defects"])
    assert result.returncode == 0, result.stderr
    assert "Rules by contract state:" in result.stdout
    for state, rule_ids in contract_coverage().items():
        assert f"  {state}: {len(rule_ids)}" in result.stdout


def test_list_defects_json_carries_rules_and_coverage() -> None:
    """The JSON form is the structured contract surface a scorer consumes."""
    result = _run(["list-defects", "--json"])
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert {row["rule_id"] for row in payload["rules"]} == set(DEFECTS)
    assert payload["contract_state_coverage"] == contract_coverage()
    for state in REQUIRED_CONTRACT_STATES:
        assert payload["contract_state_coverage"][state], f"state {state!r} is unpopulated"
    for row in payload["rules"]:
        # The declaration must be present as data, not implied by prose.
        assert row["remediation_availability"] in {"automatic", "manual", "none"}
        assert row["approval_policy"] in {"not-required", "required"}
        assert row["mutation_ops"]


def test_list_defects_json_is_deterministic() -> None:
    first = _run(["list-defects", "--json"])
    second = _run(["list-defects", "--json"])
    assert first.stdout == second.stdout


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
    snapshot = _snapshot(out_a)
    assert snapshot == _snapshot(out_b)
    # The control partition is part of the byte-identical output contract.
    assert snapshot[CONTROLS_NAME]
    assert snapshot[RULE_SCOPE_NAME]


def test_gold_profile_emits_a_control_only_estate(config_dir: Path, tmp_path: Path) -> None:
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
            "gold",
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(out),
        ]
    )
    assert inject.returncode == 0, inject.stderr
    assert (out / INJECTED_DEFECTS_NAME).read_bytes() == b""

    controls = [
        json.loads(line)
        for line in (out / CONTROLS_NAME).read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert controls
    assert all(control["reserved"] is True for control in controls)

    val = _run(["validate-observed", "--observed-dir", str(out), "--config-dir", str(config_dir)])
    assert val.returncode == 0, val.stderr


def test_validate_observed_reports_a_tampered_control(config_dir: Path, tmp_path: Path) -> None:
    """A control declared clean but actually mutated must fail with exit code 1."""
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

    lines = (out / CONTROLS_NAME).read_text(encoding="utf-8").splitlines()
    control_id = json.loads(lines[0])["id"]
    (out / CONTROLS_NAME).write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")

    val = _run(["validate-observed", "--observed-dir", str(out), "--config-dir", str(config_dir)])
    assert val.returncode == 1
    assert "control-partition" in val.stderr
    assert control_id in val.stderr
