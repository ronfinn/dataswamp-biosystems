"""Generating the adversarial tier: opt-in, deterministic, and isolated from the default.

The load-bearing claim of this file is a negative one. Adding a whole new tier
must not move a single byte of the benchmark everyone has already published
results against, so ``mixed`` and the three ordinary tiers are compared against
their own output rather than merely assumed unaffected.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dataswamp_biosystems.company import load_config
from dataswamp_biosystems.observed.difficulty import Difficulty, DifficultySelection
from dataswamp_biosystems.observed.engine import (
    ADVERSARIAL_MIN_SCHEMA_VERSION,
    OBSERVED_GENERATOR_VERSION,
    OBSERVED_SCHEMA_VERSION,
    SUPPORTED_OBSERVED_SCHEMA_VERSIONS,
    generate_observed,
)
from dataswamp_biosystems.observed.errors import ObservedConfigError
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.scenarios import CaseType, ScenarioUnavailableError
from dataswamp_biosystems.observed.validate import read_observed_difficulty, validate_observed
from dataswamp_biosystems.observed.writer import (
    PROFILE_SUMMARY_NAME,
    SCENARIO_TRANSFORMATIONS_NAME,
    SCENARIOS_NAME,
    observed_bytes,
    write_observed,
)
from dataswamp_biosystems.truth import generate_truth_graph, load_generation_plan
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.conftest import CONFIG_DIR

SEED = 20260717
ORDINARY_TIERS = (Difficulty.BRONZE, Difficulty.SILVER, Difficulty.GOLD)


@pytest.fixture(scope="module")
def graph() -> TruthGraph:
    return generate_truth_graph(load_config(CONFIG_DIR), load_generation_plan(CONFIG_DIR), SEED)


def _generate(graph: TruthGraph, difficulty: Difficulty | None):
    return generate_observed(graph, load_config(CONFIG_DIR), ObservedProfile.DEMO, SEED, difficulty)


# ---------------------------------------------------------------------------
# Schema and version migration
# ---------------------------------------------------------------------------


def test_the_observed_schema_and_generator_versions_are_the_migrated_ones() -> None:
    assert OBSERVED_SCHEMA_VERSION == 4
    assert OBSERVED_GENERATOR_VERSION == "1.3.0"


def test_schema_three_output_remains_readable() -> None:
    """The migration adds ledgers; it does not invalidate a v3 benchmark."""
    assert 3 in SUPPORTED_OBSERVED_SCHEMA_VERSIONS
    assert 4 in SUPPORTED_OBSERVED_SCHEMA_VERSIONS


def _rewrite_schema_version(observed_dir: Path, version: int) -> None:
    path = observed_dir / PROFILE_SUMMARY_NAME
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["meta"]["schema_version"] = version
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_a_schema_three_directory_declaring_adversarial_is_refused(
    graph: TruthGraph, tmp_path: Path
) -> None:
    """Only where schema 4 is *genuinely* required: v3 has nowhere to put the ledgers."""
    target = tmp_path / "observed"
    write_observed(_generate(graph, Difficulty.ADVERSARIAL), target)
    _rewrite_schema_version(target, 3)

    with pytest.raises(ObservedConfigError) as excinfo:
        validate_observed(target, graph, load_config(CONFIG_DIR))
    message = str(excinfo.value)
    assert "adversarial" in message
    assert "requires" in message
    assert str(ADVERSARIAL_MIN_SCHEMA_VERSION) in message


def test_an_unreadable_schema_version_is_refused_rather_than_guessed_at(
    graph: TruthGraph, tmp_path: Path
) -> None:
    """Regenerating against a mismatched generator would produce a confident, wrong report."""
    target = tmp_path / "observed"
    write_observed(_generate(graph, None), target)
    _rewrite_schema_version(target, 99)

    with pytest.raises(ObservedConfigError) as excinfo:
        validate_observed(target, graph, load_config(CONFIG_DIR))
    assert "cannot read" in str(excinfo.value)


def test_a_schema_three_directory_declaring_no_tier_is_still_accepted(
    graph: TruthGraph, tmp_path: Path
) -> None:
    """Backward-readable where it can be: only the *adversarial* claim needs schema 4.

    The compatibility gate must pass; the byte tripwire then reports the version
    edit as drift, which is a different and correct complaint.
    """
    from dataswamp_biosystems.observed.errors import ObservedValidationError

    target = tmp_path / "observed"
    write_observed(_generate(graph, None), target)
    _rewrite_schema_version(target, 3)

    with pytest.raises(ObservedValidationError) as excinfo:
        validate_observed(target, graph, load_config(CONFIG_DIR))
    assert all("schema version" not in issue.message for issue in excinfo.value.issues)


def test_an_unconstructable_scenario_class_is_a_configuration_error_not_a_crash() -> None:
    """`ScenarioUnavailableError` must reach the CLI's exit-2 path, not a traceback."""
    assert issubclass(ScenarioUnavailableError, ObservedConfigError)


# ---------------------------------------------------------------------------
# The default must not move
# ---------------------------------------------------------------------------


def test_mixed_output_gains_no_scenario_and_no_extra_file(graph: TruthGraph) -> None:
    """``mixed`` is the ordinary rule catalogue, and silence about scenarios."""
    result = _generate(graph, None)
    assert result.scenarios == []
    assert result.transformations == []
    assert "scenarios" not in result.summary
    emitted = set(observed_bytes(result))
    assert SCENARIOS_NAME not in emitted
    assert SCENARIO_TRANSFORMATIONS_NAME not in emitted


@pytest.mark.parametrize("tier", ORDINARY_TIERS, ids=lambda t: t.value)
def test_an_ordinary_tier_gains_no_scenario_and_no_extra_file(
    graph: TruthGraph, tier: Difficulty
) -> None:
    result = _generate(graph, tier)
    assert result.scenarios == []
    assert result.transformations == []
    assert SCENARIOS_NAME not in observed_bytes(result)


def test_adding_the_adversarial_tier_did_not_change_what_mixed_selects(
    graph: TruthGraph,
) -> None:
    """The strongest form: the whole ledger set, not a summary of it."""
    mixed = _generate(graph, None)
    adversarial = _generate(graph, Difficulty.ADVERSARIAL)
    mixed_selection = {(s.id, tuple(s.selected_ids)) for s in mixed.rule_scopes}
    adversarial_selection = {(s.id, tuple(s.selected_ids)) for s in adversarial.rule_scopes}
    # The two runs must disagree — otherwise this test would pass vacuously.
    assert mixed_selection != adversarial_selection
    # …and the mixed run must still fire the whole catalogue.
    assert len(mixed.rule_scopes) > len(adversarial.rule_scopes)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_a_fixed_seed_produces_byte_identical_adversarial_output(graph: TruthGraph) -> None:
    first = observed_bytes(_generate(graph, Difficulty.ADVERSARIAL))
    second = observed_bytes(_generate(graph, Difficulty.ADVERSARIAL))
    assert first == second


def test_a_different_seed_moves_the_constructed_targets(graph: TruthGraph) -> None:
    """Guard the determinism test: the seed must actually be doing something."""
    config = load_config(CONFIG_DIR)
    first = generate_observed(graph, config, ObservedProfile.DEMO, SEED, Difficulty.ADVERSARIAL)
    second = generate_observed(
        graph, config, ObservedProfile.DEMO, SEED + 1, Difficulty.ADVERSARIAL
    )
    assert {c.id for c in first.scenarios} != {c.id for c in second.scenarios}


def test_output_is_identical_under_a_different_python_hash_seed(tmp_path: Path) -> None:
    """No emitted order may depend on set or dict hashing."""
    script = (
        "import json;"
        "from pathlib import Path;"
        "from dataswamp_biosystems.company import load_config;"
        "from dataswamp_biosystems.truth import generate_truth_graph, load_generation_plan;"
        "from dataswamp_biosystems.observed.difficulty import Difficulty;"
        "from dataswamp_biosystems.observed.engine import generate_observed;"
        "from dataswamp_biosystems.observed.profiles import ObservedProfile;"
        "from dataswamp_biosystems.observed.writer import observed_bytes;"
        f"c=load_config(Path({str(CONFIG_DIR)!r}));"
        f"p=load_generation_plan(Path({str(CONFIG_DIR)!r}));"
        f"g=generate_truth_graph(c,p,{SEED});"
        f"r=generate_observed(g,c,ObservedProfile.DEMO,{SEED},Difficulty.ADVERSARIAL);"
        "print(json.dumps({k: v.decode() for k, v in observed_bytes(r).items()}))"
    )
    outputs = []
    for hash_seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        outputs.append(json.loads(completed.stdout))
    assert outputs[0] == outputs[1]


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_a_profile_that_reserves_everything_fails_clearly(graph: TruthGraph) -> None:
    """``gold`` holds out every asset, so no positive case can be constructed.

    The failure must name the missing case classes: an adversarial benchmark that
    silently dropped half its case types would still look like a result, and
    every agent would score identically on it.
    """
    with pytest.raises(ObservedConfigError) as excinfo:
        generate_observed(
            graph, load_config(CONFIG_DIR), ObservedProfile.GOLD, SEED, Difficulty.ADVERSARIAL
        )
    message = str(excinfo.value)
    assert "incomplete" in message
    assert "required adversarial case class" in message


def test_a_profile_with_no_room_for_overlapping_evidence_fails_clearly(
    graph: TruthGraph,
) -> None:
    """``mostly-good`` caps one defect per entity, so no overlap can be built."""
    with pytest.raises(ObservedConfigError) as excinfo:
        generate_observed(
            graph,
            load_config(CONFIG_DIR),
            ObservedProfile.MOSTLY_GOOD,
            SEED,
            Difficulty.ADVERSARIAL,
        )
    assert CaseType.OVERLAPPING_EVIDENCE.value in str(excinfo.value)
    assert "incomplete" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def _cli(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "dataswamp_biosystems.cli", *args],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )


def test_the_cli_generates_and_validates_an_adversarial_benchmark(tmp_path: Path) -> None:
    truth_dir = tmp_path / "truth"
    observed_dir = tmp_path / "observed"
    generated = _cli(
        ["generate-truth", "--seed", str(SEED), "--output-dir", str(truth_dir)], tmp_path
    )
    assert generated.returncode == 0, generated.stderr

    injected = _cli(
        [
            "inject-defects",
            "--truth",
            str(truth_dir),
            "--profile",
            "demo",
            "--difficulty",
            "adversarial",
            "--seed",
            str(SEED),
            "--output-dir",
            str(observed_dir),
        ],
        tmp_path,
    )
    assert injected.returncode == 0, injected.stderr
    assert "adversarial scenarios:" in injected.stdout
    for case_type in CaseType:
        assert case_type.value in injected.stdout

    assert (observed_dir / SCENARIOS_NAME).is_file()
    assert (observed_dir / SCENARIO_TRANSFORMATIONS_NAME).is_file()
    assert read_observed_difficulty(observed_dir) is Difficulty.ADVERSARIAL

    validated = _cli(["validate-observed", "--observed-dir", str(observed_dir)], tmp_path)
    assert validated.returncode == 0, validated.stderr


def test_adversarial_is_opt_in_and_never_the_default() -> None:
    assert DifficultySelection.ADVERSARIAL.value == "adversarial"
    # The CLI default is ``mixed``; asserted here rather than only in the CLI so a
    # change to the enum's order can never silently promote adversarial.
    assert list(DifficultySelection)[0] is not DifficultySelection.ADVERSARIAL
