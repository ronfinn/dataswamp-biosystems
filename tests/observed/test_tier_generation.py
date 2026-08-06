"""Tier-restricted generation: what fires, what does not, and what stays put.

Two claims matter here. First, a tier is a *filter over rules* and nothing else:
a bronze run injects bronze defects and scopes bronze rules, and the record
schemas are untouched. Second, and more important for anyone with a published
result, the default run is unchanged — byte for byte — by the existence of the
filter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.difficulty import (
    RULE_DIFFICULTIES,
    Difficulty,
    difficulty_for,
    rules_at,
)
from dataswamp_biosystems.observed.engine import (
    OBSERVED_GENERATOR_VERSION,
    OBSERVED_SCHEMA_VERSION,
    generate_observed,
)
from dataswamp_biosystems.observed.errors import ObservedConfigError
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.writer import observed_bytes, write_observed
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.observed.conftest import TEST_SEED

TIERS = sorted(RULE_DIFFICULTIES, key=lambda t: t.value)


@pytest.fixture(scope="module")
def mixed(graph: TruthGraph, config: CanonicalConfig):
    return generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED)


# ---------------------------------------------------------------------------
# The default is untouched
# ---------------------------------------------------------------------------


def test_omitting_the_tier_is_byte_identical_to_the_previous_behaviour(
    graph: TruthGraph, config: CanonicalConfig, mixed
) -> None:
    """``difficulty=None`` must not be a new code path with the same intent."""
    explicit_none = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED, None)
    assert observed_bytes(explicit_none) == observed_bytes(mixed)
    assert mixed.difficulty is None
    assert len(mixed.rule_scopes) == 41


def test_a_mixed_run_still_scopes_and_fires_every_tier(mixed) -> None:
    scoped = {difficulty_for(scope.id) for scope in mixed.rule_scopes}
    fired = {difficulty_for(instance.rule_id) for instance in mixed.instances}
    assert scoped == set(RULE_DIFFICULTIES)
    assert fired == set(RULE_DIFFICULTIES)


# ---------------------------------------------------------------------------
# A tier restricts rules, and only rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier", TIERS, ids=lambda t: t.value)
def test_a_tier_run_contains_only_that_tier(
    graph: TruthGraph, config: CanonicalConfig, tier: Difficulty
) -> None:
    result = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED, tier)
    expected = set(rules_at(tier))

    assert {scope.id for scope in result.rule_scopes} == expected
    for collection in (result.instances, result.findings, result.remediations):
        assert collection, f"{tier.value} produced no records to check"
        assert {record.rule_id for record in collection} <= expected
    assert {m.rule_id for m in result.mutations} <= expected
    assert result.difficulty is tier


@pytest.mark.parametrize("tier", TIERS, ids=lambda t: t.value)
def test_a_tier_run_keeps_the_current_output_contract(
    graph: TruthGraph, config: CanonicalConfig, tier: Difficulty, mixed
) -> None:
    """Tier filtering changes which rules fire, never the shape of a record."""
    result = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED, tier)
    assert result.meta.schema_version == OBSERVED_SCHEMA_VERSION == 4
    assert result.meta.generator_version == OBSERVED_GENERATOR_VERSION == "1.3.0"
    # An ordinary tier is not a scenario run, and must not acquire the scenario
    # ledgers by being near one.
    assert result.scenarios == []
    assert result.transformations == []
    assert set(observed_bytes(result)) == set(observed_bytes(mixed))
    assert set(result.observed_graph) == set(mixed.observed_graph)
    assert set(result.summary) == set(mixed.summary)
    # Meta is what downstream readers key on, and it must not learn a new field:
    # the tier travels in provenance instead.
    assert result.meta.model_dump(mode="json").keys() == mixed.meta.model_dump(mode="json").keys()


def test_the_tiers_together_cover_every_rule_the_mixed_run_scopes(
    graph: TruthGraph, config: CanonicalConfig, mixed
) -> None:
    scoped: set[str] = set()
    for tier in TIERS:
        result = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED, tier)
        tier_rules = {scope.id for scope in result.rule_scopes}
        assert not (scoped & tier_rules), "a rule was scoped by two tiers"
        scoped |= tier_rules
    assert scoped == {scope.id for scope in mixed.rule_scopes}


# ---------------------------------------------------------------------------
# Independence from the maturity profile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", [ObservedProfile.MOSTLY_GOOD, ObservedProfile.POOR])
def test_tier_and_profile_compose_as_independent_filters(
    graph: TruthGraph, config: CanonicalConfig, profile: ObservedProfile
) -> None:
    """The profile sets how many; the tier sets which. Neither overrides the other."""
    counts = {}
    for tier in TIERS:
        result = generate_observed(graph, config, profile, TEST_SEED, tier)
        assert {scope.id for scope in result.rule_scopes} == set(rules_at(tier))
        assert all(difficulty_for(i.rule_id) is tier for i in result.instances)
        counts[tier] = len(result.instances)
    # A stricter profile injects fewer defects at every tier it can reach — the
    # maturity axis still works after filtering.
    poor = {
        tier: len(generate_observed(graph, config, ObservedProfile.POOR, TEST_SEED, tier).instances)
        for tier in TIERS
    }
    if profile is ObservedProfile.MOSTLY_GOOD:
        assert all(counts[tier] <= poor[tier] for tier in TIERS)


def test_an_empty_profile_tier_intersection_fails_and_says_why(
    graph: TruthGraph, config: CanonicalConfig
) -> None:
    """The ``gold`` profile reserves every asset, so no tier has anything to draw."""
    with pytest.raises(ObservedConfigError) as excinfo:
        generate_observed(graph, config, ObservedProfile.GOLD, TEST_SEED, Difficulty.BRONZE)
    message = str(excinfo.value)
    assert "bronze" in message and "gold" in message
    assert "empty intersection" in message


def test_the_default_path_still_permits_a_defect_free_profile(
    graph: TruthGraph, config: CanonicalConfig
) -> None:
    """A pristine estate is a legitimate mixed scenario and must not become an error."""
    result = generate_observed(graph, config, ObservedProfile.GOLD, TEST_SEED)
    assert result.instances == []


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier", TIERS, ids=lambda t: t.value)
def test_a_tier_run_is_deterministic_for_a_fixed_seed(
    graph: TruthGraph, config: CanonicalConfig, tier: Difficulty
) -> None:
    first = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED, tier)
    second = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED, tier)
    assert observed_bytes(first) == observed_bytes(second)


def _cli(args: list[str], hash_seed: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "dataswamp_biosystems.cli", *args],
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
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


def test_tier_generation_is_stable_across_python_hash_seeds(
    config_dir: Path, tmp_path: Path
) -> None:
    """Run in subprocesses: ``PYTHONHASHSEED`` is fixed at interpreter start."""
    truth_dir = tmp_path / "truth"
    result = _cli(
        [
            "generate-truth",
            "--seed",
            str(TEST_SEED),
            "--config-dir",
            str(config_dir),
            "--output-dir",
            str(truth_dir),
        ],
        "0",
    )
    assert result.returncode == 0, result.stderr

    snapshots = []
    for index, hash_seed in enumerate(("0", "12345")):
        output_dir = tmp_path / f"observed-{index}"
        result = _cli(
            [
                "inject-defects",
                "--truth",
                str(truth_dir),
                "--seed",
                str(TEST_SEED),
                "--profile",
                "demo",
                "--difficulty",
                "silver",
                "--config-dir",
                str(config_dir),
                "--output-dir",
                str(output_dir),
            ],
            hash_seed,
        )
        assert result.returncode == 0, result.stderr
        assert "difficulty silver" in result.stdout
        snapshots.append(_snapshot(output_dir))

    assert snapshots[0] == snapshots[1]


def test_the_cli_records_the_tier_in_provenance_only_when_one_was_chosen(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    """Provenance is the one output no digest covers, so it is where the tier goes."""
    import json

    from dataswamp_biosystems.provenance import PROVENANCE_NAME

    default_dir = tmp_path / "mixed"
    write_observed(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED), default_dir)
    default = json.loads((default_dir / PROVENANCE_NAME).read_text(encoding="utf-8"))
    assert "difficulty" not in default["scenario"]

    tier_dir = tmp_path / "bronze"
    write_observed(
        generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED, Difficulty.BRONZE),
        tier_dir,
    )
    tiered = json.loads((tier_dir / PROVENANCE_NAME).read_text(encoding="utf-8"))
    assert tiered["scenario"]["difficulty"] == "bronze"


@pytest.mark.parametrize("tier", TIERS, ids=lambda t: t.value)
def test_a_written_tier_state_re_validates_against_itself(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path, tier: Difficulty
) -> None:
    """``validate-observed`` regenerates, so it has to know which tier to regenerate.

    It recovers the tier from provenance. Without that it would regenerate the
    full catalogue and report every excluded rule as drift — a validator that
    fails on its own correct output.
    """
    from dataswamp_biosystems.observed.validate import (
        read_observed_difficulty,
        validate_observed,
    )

    target = tmp_path / tier.value
    write_observed(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED, tier), target)
    assert read_observed_difficulty(target) is tier
    validate_observed(target, graph, config)


def test_a_mixed_state_reports_no_tier_and_still_validates(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    from dataswamp_biosystems.observed.validate import (
        read_observed_difficulty,
        validate_observed,
    )

    target = tmp_path / "mixed"
    write_observed(generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED), target)
    assert read_observed_difficulty(target) is None
    validate_observed(target, graph, config)


def test_output_written_before_tiers_existed_still_reads_as_mixed(tmp_path: Path) -> None:
    """A directory with no provenance must not become unvalidatable."""
    from dataswamp_biosystems.observed.validate import read_observed_difficulty

    assert read_observed_difficulty(tmp_path) is None


def test_the_cli_still_rejects_a_difficulty_that_is_not_a_tier(config_dir: Path) -> None:
    """The selection enum is closed: an invented tier is rejected, not guessed at."""
    result = _cli(["inject-defects", "--difficulty", "platinum"], "0")
    assert result.returncode != 0
    assert "platinum" in (result.stderr + result.stdout)
