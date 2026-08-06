"""What the three reference baselines actually score on the adversarial tier.

The numbers below are written out by hand from a measured run, exactly as the
tier scores are, so a behaviour change has to be re-read and re-typed by whoever
makes it rather than laundered into a green suite.

Nothing here is tuned. These are the agents published in ``docs/baselines.md``,
run unmodified, and the results are reported as measured — including the fact
that the naive agent's near-miss false-positive rate is *worse* than its
false-positive rate anywhere else, and that the rule-based agent scores zero on
three of the six case classes. The adversarial tier is not assumed to rank agents
the same way the ordinary tiers do, and the suite must not start assuming it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.baselines import (
    ADVERSARIAL_ONLY_INPUT_FILES,
    BASELINE_NAMES,
    FORBIDDEN_INPUT_FILES,
    ObservedInput,
    get_baseline,
    render_predictions,
    run_baseline,
)
from dataswamp_biosystems.evaluation import evaluate, load_ground_truth, prediction_digest
from dataswamp_biosystems.evaluation.predictions import parse_predictions
from dataswamp_biosystems.observed.scenarios import CaseType

# Measured against the canonical scenario (demo profile, canonical truth and
# defect seeds) at ``--difficulty adversarial``. Keys: tp, fp, fn, tn.
EXPECTED: dict[str, tuple[int, int, int, int]] = {
    "null": (0, 0, 13, 6),
    "naive-metadata": (2, 2, 11, 4),
    "rule-based": (7, 0, 6, 6),
}

# The number the tier exists to produce: how often each agent was fooled by a
# control deliberately dressed to look defective.
EXPECTED_NEAR_MISS_FALSE_POSITIVES: dict[str, int] = {
    "null": 0,
    "naive-metadata": 2,
    "rule-based": 0,
}

# Right rule, wrong subject. Counted over every false positive in the benchmark
# whose rule a scenario does fire somewhere, not only over declared scenario
# pairs — flagging the right rule on an entity no case names is the same mistake.
# The naive agent walks into the decoy twice and misattributes twice more.
EXPECTED_WRONG_ENTITY: dict[str, int] = {
    "null": 0,
    "naive-metadata": 4,
    "rule-based": 0,
}

# The constructed universe, pinned because every number above is relative to it.
EXPECTED_UNIVERSE = {"scenario_pairs": 19, "positive_support": 13, "near_miss_negatives": 6}


def _score(observed_dir: Path, agent_name: str) -> Any:
    truth = load_ground_truth(observed_dir)
    run = run_baseline(get_baseline(agent_name), ObservedInput.load(observed_dir))
    raw = render_predictions(run.predictions).encode("utf-8")
    submitted = parse_predictions(
        raw.decode("utf-8"),
        known_entities=truth.known_entities,
        known_rules=truth.rule_ids,
    )
    return evaluate(truth, submitted, prediction_digest=prediction_digest(raw))


@pytest.fixture(scope="module")
def blocks(adversarial_observed_dir: Path) -> dict[str, dict[str, Any]]:
    return {name: _score(adversarial_observed_dir, name).summary for name in BASELINE_NAMES}


def test_the_constructed_universe_is_the_one_the_scores_are_relative_to(
    blocks: dict[str, dict[str, Any]],
) -> None:
    block = blocks["null"]["adversarial"]
    assert block["scenario_pairs"] == EXPECTED_UNIVERSE["scenario_pairs"]
    assert block["positive_support"] == EXPECTED_UNIVERSE["positive_support"]
    assert block["near_miss_negative_support"] == EXPECTED_UNIVERSE["near_miss_negatives"]


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_the_measured_adversarial_confusion_matrix(
    blocks: dict[str, dict[str, Any]], name: str
) -> None:
    matrix = blocks[name]["adversarial"]["confusion_matrix"]
    assert (matrix["tp"], matrix["fp"], matrix["fn"], matrix["tn"]) == EXPECTED[name]


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_the_measured_near_miss_false_positives(
    blocks: dict[str, dict[str, Any]], name: str
) -> None:
    near_miss = blocks[name]["adversarial"]["near_miss_controls"]
    assert near_miss["false_positives"] == EXPECTED_NEAR_MISS_FALSE_POSITIVES[name]


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_the_measured_wrong_entity_attributions(
    blocks: dict[str, dict[str, Any]], name: str
) -> None:
    attribution = blocks[name]["adversarial"]["attribution"]
    assert attribution["wrong_entity_predictions"] == EXPECTED_WRONG_ENTITY[name]


def test_no_agent_proposes_a_repair_against_a_near_miss(
    blocks: dict[str, dict[str, Any]],
) -> None:
    """None of the three submits remediations at all, so this is a floor, not a win."""
    for name in BASELINE_NAMES:
        assert blocks[name]["adversarial"]["near_miss_controls"]["unsafe_remediations"] == 0


def test_no_agent_produces_a_correct_no_remediation_decision(
    blocks: dict[str, dict[str, Any]],
) -> None:
    """Reported as measured: the reference agents do not reason about remediation."""
    for name in BASELINE_NAMES:
        remediation = blocks[name]["adversarial"]["remediation"]
        assert remediation["no_remediation_expected"] == 2
        assert remediation["correct_no_remediation"] == 0


def test_the_hardest_case_classes_defeat_every_reference_agent(
    blocks: dict[str, dict[str, Any]],
) -> None:
    """Recorded honestly rather than hidden: three classes are unsolved by all three.

    That is the point of publishing an adversarial tier — a benchmark everything
    passes discriminates nothing — and it is asserted so that a future agent
    change which *does* solve one is a visible, reviewed event.
    """
    unsolved = (
        CaseType.CROSS_ASSET_INCONSISTENCY,
        CaseType.NO_REMEDIATION,
    )
    for name in BASELINE_NAMES:
        by_case = blocks[name]["adversarial"]["by_case_type"]
        for case_type in unsolved:
            assert by_case[case_type.value]["counts"]["tp"] == 0, f"{name} solved {case_type}"


def test_the_ordinary_tier_scores_are_untouched_by_the_adversarial_run(
    blocks: dict[str, dict[str, Any]],
) -> None:
    """An adversarial benchmark scopes only its own rules; it is not a superset."""
    universe = blocks["null"]["universe"]
    assert universe["rules_by_difficulty"]["adversarial"] == 0, (
        "no *rule* is adversarial; the tier is a property of the constructed case"
    )


# ---------------------------------------------------------------------------
# Anti-leakage
# ---------------------------------------------------------------------------


def test_the_adversarial_benchmark_really_contains_the_privileged_scenario_ledgers(
    adversarial_observed_dir: Path,
) -> None:
    """Guard the guard below: the prohibition must be prohibiting something."""
    present = {path.name for path in adversarial_observed_dir.iterdir()}
    assert present >= FORBIDDEN_INPUT_FILES
    assert present >= ADVERSARIAL_ONLY_INPUT_FILES


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_an_agent_opens_no_scenario_ledger(
    name: str, adversarial_observed_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Path] = []
    real_read_text = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        opened.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    run_baseline(get_baseline(name), ObservedInput.load(adversarial_observed_dir))
    assert not {path.name for path in opened} & FORBIDDEN_INPUT_FILES


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_an_agent_produces_identical_output_without_the_scenario_ledgers(
    name: str, adversarial_observed_dir: Path, tmp_path: Path
) -> None:
    """Delete the answer key from disk; the submission must not move."""
    import shutil

    isolated = tmp_path / "observed"
    isolated.mkdir()
    shutil.copy(adversarial_observed_dir / "observed-graph.json", isolated / "observed-graph.json")
    agent = get_baseline(name)
    with_answers = render_predictions(
        run_baseline(agent, ObservedInput.load(adversarial_observed_dir)).predictions
    )
    without_answers = render_predictions(
        run_baseline(agent, ObservedInput.load(isolated)).predictions
    )
    assert with_answers == without_answers


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_an_agent_is_deterministic_on_the_adversarial_benchmark(
    name: str, adversarial_observed_dir: Path
) -> None:
    agent = get_baseline(name)
    first = render_predictions(
        run_baseline(agent, ObservedInput.load(adversarial_observed_dir)).predictions
    )
    second = render_predictions(
        run_baseline(agent, ObservedInput.load(adversarial_observed_dir)).predictions
    )
    assert first == second
