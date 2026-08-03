"""What every baseline agent must do, regardless of how well it scores.

Behaviour, not numbers: the canonical scores live in ``test_scores.py``. These
tests are about the contract a benchmark participant has to keep — valid output,
stable output, and output that does not depend on how the input file happened to
be laid out.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dataswamp_biosystems.baselines import (
    BASELINE_NAMES,
    ObservedInput,
    ObservedInputError,
    UnknownBaselineError,
    baseline_infos,
    get_baseline,
    render_predictions,
    run_baseline,
    write_predictions,
)
from dataswamp_biosystems.baselines.base import BaselineAgent, BaselineInfo
from dataswamp_biosystems.baselines.catalogue import RULE_FACTS
from dataswamp_biosystems.baselines.rule_agent import RuleBasedBaseline
from dataswamp_biosystems.evaluation import GroundTruth, parse_predictions
from dataswamp_biosystems.evaluation.predictions import (
    PREDICTION_SCHEMA_VERSION,
    STATUS_FINDING,
)
from dataswamp_biosystems.observed.writer import OBSERVED_GRAPH_NAME

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_documented_baseline_is_registered() -> None:
    assert BASELINE_NAMES == ("null", "naive-metadata", "rule-based")


def test_an_unknown_baseline_names_the_ones_that_exist() -> None:
    with pytest.raises(UnknownBaselineError) as excinfo:
        get_baseline("gradient-boosted-wishful-thinking")
    for name in BASELINE_NAMES:
        assert name in str(excinfo.value)


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_agents_satisfy_the_protocol(name: str) -> None:
    assert isinstance(get_baseline(name), BaselineAgent)


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_output_satisfies_the_prediction_contract(
    name: str, observed_input: ObservedInput, ground_truth: GroundTruth
) -> None:
    """The evaluator's own total validator must accept every baseline submission."""
    run = run_baseline(get_baseline(name), observed_input)
    parsed = parse_predictions(
        render_predictions(run.predictions),
        known_entities=ground_truth.known_entities,
        known_rules=ground_truth.rule_ids,
    )
    assert len(parsed) == run.prediction_count
    for prediction in parsed:
        assert prediction.schema_version == PREDICTION_SCHEMA_VERSION
        assert prediction.status == STATUS_FINDING
        assert prediction.agent == {"name": name, "version": run.info.version}


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_predictions_are_emitted_in_canonical_order(
    name: str, observed_input: ObservedInput
) -> None:
    predictions = run_baseline(get_baseline(name), observed_input).predictions
    keys = [(p.entity_id, p.rule_id) for p in predictions]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys), "a pair may be claimed at most once"


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_repeated_runs_are_byte_identical(name: str, real_observed_dir: Path) -> None:
    agent = get_baseline(name)
    first = render_predictions(
        run_baseline(agent, ObservedInput.load(real_observed_dir)).predictions
    )
    second = render_predictions(
        run_baseline(agent, ObservedInput.load(real_observed_dir)).predictions
    )
    assert first == second


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_output_survives_a_different_python_hash_seed(name: str, real_observed_dir: Path) -> None:
    """Hash randomisation must not reach the output.

    Run in a subprocess because ``PYTHONHASHSEED`` is fixed at interpreter start;
    a same-process test could not observe a difference even if one existed.
    """
    script = textwrap.dedent(
        """
        import sys
        from dataswamp_biosystems.baselines import (
            ObservedInput, get_baseline, render_predictions, run_baseline,
        )
        agent = get_baseline(sys.argv[1])
        run = run_baseline(agent, ObservedInput.load(sys.argv[2]))
        sys.stdout.write(render_predictions(run.predictions))
        """
    )
    outputs = []
    for seed in ("0", "1", "4242"):
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", script, name, str(real_observed_dir)],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "", "PYTHONPATH": str(REPO_ROOT / "src")},
        )
        outputs.append(completed.stdout)
    assert len(set(outputs)) == 1


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_record_order_inside_a_shard_does_not_change_the_output(
    name: str, real_observed_dir: Path, reordered_observed_dir: Path
) -> None:
    """Equivalent observations must produce an equivalent submission.

    Reversing every shard changes the file but not the estate it describes. Only
    the ``prediction_id`` — which is derived from the claim, not a counter — and
    the emission order could plausibly move, and neither does.
    """
    agent = get_baseline(name)
    original = run_baseline(agent, ObservedInput.load(real_observed_dir)).predictions
    shuffled = run_baseline(agent, ObservedInput.load(reordered_observed_dir)).predictions
    assert render_predictions(original) == render_predictions(shuffled)


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_agents_run_against_a_gold_profile(name: str, gold_observed_dir: Path) -> None:
    """A defect-free scenario must produce a silent submission.

    The gold profile injects nothing, so every prediction here would be a false
    positive against a clean estate. All three baselines are silent, including
    the naive one: its shallow thresholds are loose enough to misfire on a
    *defective* estate, but the clean estate gives them nothing to catch on.
    """
    run = run_baseline(get_baseline(name), ObservedInput.load(gold_observed_dir))
    assert run.prediction_count == 0


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_an_empty_but_well_formed_graph_yields_an_empty_submission(
    name: str, tmp_path: Path
) -> None:
    observed_dir = tmp_path / "observed"
    observed_dir.mkdir()
    (observed_dir / OBSERVED_GRAPH_NAME).write_text(json.dumps({"meta": {}}), encoding="utf-8")
    run = run_baseline(get_baseline(name), ObservedInput.load(observed_dir))
    assert run.prediction_count == 0


def test_a_missing_observed_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ObservedInputError, match="no observed state directory"):
        ObservedInput.load(tmp_path / "nowhere")


def test_a_missing_observed_graph_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ObservedInputError, match="could not read"):
        ObservedInput.load(tmp_path)


def test_malformed_json_is_reported_rather_than_guessed(tmp_path: Path) -> None:
    (tmp_path / OBSERVED_GRAPH_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(ObservedInputError, match="not valid JSON"):
        ObservedInput.load(tmp_path)


def test_a_json_document_that_is_not_an_object_is_reported(tmp_path: Path) -> None:
    (tmp_path / OBSERVED_GRAPH_NAME).write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ObservedInputError, match="must contain a JSON object"):
        ObservedInput.load(tmp_path)


@pytest.mark.parametrize("shard_value", ["not-a-list", {"id": "x"}, 42])
def test_a_malformed_shard_is_reported(tmp_path: Path, shard_value: object) -> None:
    (tmp_path / OBSERVED_GRAPH_NAME).write_text(
        json.dumps({"meta": {}, "datasets": shard_value}), encoding="utf-8"
    )
    observed = ObservedInput.load(tmp_path)
    with pytest.raises(ObservedInputError, match="is not a list"):
        _ = observed.assets


def test_a_shard_holding_a_non_object_record_is_reported(tmp_path: Path) -> None:
    (tmp_path / OBSERVED_GRAPH_NAME).write_text(
        json.dumps({"meta": {}, "datasets": ["oops"]}), encoding="utf-8"
    )
    observed = ObservedInput.load(tmp_path)
    with pytest.raises(ObservedInputError, match="is not an object"):
        _ = observed.assets


def test_the_rule_based_agent_only_emits_rules_it_declares(
    observed_input: ObservedInput,
) -> None:
    run = run_baseline(RuleBasedBaseline(), observed_input)
    declared = set(RuleBasedBaseline.IMPLEMENTED_RULES)
    assert set(run.rules_used) <= declared
    unused = declared - set(run.rules_used)
    assert not unused, f"declared but never emitted on the canonical scenario: {sorted(unused)}"


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_every_emitted_rule_id_exists_in_the_published_catalogue(
    name: str, observed_input: ObservedInput
) -> None:
    run = run_baseline(get_baseline(name), observed_input)
    assert set(run.rules_used) <= set(RULE_FACTS)


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_no_baseline_files_a_rule_against_an_inapplicable_entity_kind(
    name: str, observed_input: ObservedInput, ground_truth: GroundTruth
) -> None:
    """Out-of-scope claims are a scoring outcome, and no baseline should make one."""
    run = run_baseline(get_baseline(name), observed_input)
    for prediction in run.predictions:
        fact = RULE_FACTS[prediction.rule_id]
        assert ground_truth.entity_kind(prediction.entity_id) in fact.applies_to_kinds


def test_writing_a_submission_is_atomic_and_leaves_no_temporary_file(
    tmp_path: Path, observed_input: ObservedInput
) -> None:
    run = run_baseline(get_baseline("rule-based"), observed_input)
    target = tmp_path / "nested" / "predictions.jsonl"
    write_predictions(run, target)
    assert target.is_file()
    assert sorted(p.name for p in target.parent.iterdir()) == ["predictions.jsonl"]


def test_the_null_baseline_writes_a_real_empty_file(
    tmp_path: Path, observed_input: ObservedInput
) -> None:
    """An empty submission is a submission, not a skipped write."""
    run = run_baseline(get_baseline("null"), observed_input)
    target = tmp_path / "predictions.jsonl"
    write_predictions(run, target)
    assert target.is_file()
    assert target.read_bytes() == b""


@pytest.mark.parametrize("info", baseline_infos(), ids=lambda info: info.name)
def test_declared_reads_are_sorted_and_unique(info: BaselineInfo) -> None:
    assert list(info.reads) == sorted(set(info.reads))
