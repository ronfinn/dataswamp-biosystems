"""The committed example submissions must stay valid, and score as documented.

The examples are part of the release surface: the README and ``examples/README``
publish their scores, ``dataswamp demo`` runs one of them, and a new user reads
them to learn the prediction contract. A silently-rotted example is a product
defect, so the numbers are pinned here rather than merely re-derived.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.evaluation import (
    STATUS_ABSTAIN,
    STATUS_CLEAN,
    STATUS_FINDING,
    GroundTruth,
    evaluate,
    load_ground_truth,
    load_predictions,
    prediction_digest,
)
from dataswamp_biosystems.examples import EXAMPLE_SUBMISSIONS, example_path, examples_dir

# The published results, exactly as the README and examples/README state them.
# A change here is a change to the benchmark's advertised behaviour and must be
# accompanied by an update to both documents.
EXPECTED_SCORES: dict[str, dict[str, int]] = {
    "perfect": {"tp": 177, "fp": 0, "fn": 0, "tn": 6944, "unsafe": 0, "reserved_fp": 0},
    "partial": {"tp": 4, "fp": 0, "fn": 173, "tn": 6944, "unsafe": 0, "reserved_fp": 0},
    "unsafe": {"tp": 1, "fp": 4, "fn": 176, "tn": 6940, "unsafe": 4, "reserved_fp": 3},
}

# Fields a submission may carry. Anything outside this set would mean an example
# is handing an agent something the observed graph does not contain.
PUBLIC_FIELDS = frozenset(
    {
        "schema_version",
        "prediction_id",
        "entity_id",
        "rule_id",
        "status",
        "category",
        "severity",
        "confidence",
        "evidence",
        "evidence_refs",
        "remediation",
        "agent",
    }
)


@pytest.fixture(scope="module")
def ground_truth(real_observed_dir: Path) -> GroundTruth:
    return load_ground_truth(real_observed_dir)


@pytest.mark.parametrize("name", EXAMPLE_SUBMISSIONS)
def test_every_documented_example_exists(name: str) -> None:
    assert example_path(name).is_file(), f"missing example submission: {name}"


@pytest.mark.parametrize("name", EXAMPLE_SUBMISSIONS)
def test_examples_use_only_public_prediction_fields(name: str) -> None:
    """No example may hand an agent privileged ground truth as input."""
    for line in example_path(name).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        unknown = set(row) - PUBLIC_FIELDS
        assert not unknown, f"{name}: non-public field(s) {sorted(unknown)}"


@pytest.mark.parametrize("name", EXAMPLE_SUBMISSIONS)
def test_examples_never_leak_ground_truth_identifiers(name: str) -> None:
    """Defect-instance, mutation and expected-finding ids must never appear."""
    text = example_path(name).read_text(encoding="utf-8")
    for privileged_prefix in ('"di-', '"find-', '"rem-', '"mut-'):
        assert privileged_prefix not in text, f"{name} leaks {privileged_prefix}… identifiers"


@pytest.mark.parametrize("name", EXAMPLE_SUBMISSIONS)
def test_examples_parse_against_the_real_ground_truth(name: str, ground_truth: GroundTruth) -> None:
    submitted, _ = load_predictions(
        example_path(name),
        known_entities=ground_truth.known_entities,
        known_rules=ground_truth.rule_ids,
    )
    assert submitted, f"{name} parsed to no predictions"


@pytest.mark.parametrize("name", EXAMPLE_SUBMISSIONS)
def test_examples_score_exactly_as_documented(name: str, ground_truth: GroundTruth) -> None:
    submitted, raw = load_predictions(
        example_path(name),
        known_entities=ground_truth.known_entities,
        known_rules=ground_truth.rule_ids,
    )
    summary = evaluate(ground_truth, submitted, prediction_digest=prediction_digest(raw)).summary

    counts = summary["findings"]["overall_micro"]["counts"]
    expected = EXPECTED_SCORES[name]
    assert (counts["tp"], counts["fp"], counts["fn"], counts["tn"]) == (
        expected["tp"],
        expected["fp"],
        expected["fn"],
        expected["tn"],
    )
    assert summary["remediation"]["counts"]["unsafe_actions"] == expected["unsafe"]
    assert summary["reserved_controls"]["false_positives"] == expected["reserved_fp"]


def test_the_perfect_example_is_actually_perfect(ground_truth: GroundTruth) -> None:
    """The reference upper bound must really be an upper bound."""
    submitted, raw = load_predictions(
        example_path("perfect"),
        known_entities=ground_truth.known_entities,
        known_rules=ground_truth.rule_ids,
    )
    summary = evaluate(ground_truth, submitted, prediction_digest=prediction_digest(raw)).summary
    metrics = summary["findings"]["overall_micro"]["metrics"]
    assert metrics["precision"]["value"] == 1.0
    assert metrics["recall"]["value"] == 1.0
    assert metrics["specificity"]["value"] == 1.0
    remediation = summary["remediation"]["counts"]
    assert remediation["fully_correct"] == remediation["submitted"] == len(ground_truth.findings)


def test_the_partial_example_exercises_all_three_claim_kinds() -> None:
    """It is the file a reader learns the contract from; it must show the contract."""
    statuses = {
        json.loads(line)["status"]
        for line in example_path("partial").read_text(encoding="utf-8").splitlines()
    }
    assert statuses == {STATUS_FINDING, STATUS_CLEAN, STATUS_ABSTAIN}


def test_the_committed_examples_match_their_generator(real_observed_dir: Path) -> None:
    """Re-derive the examples and fail if the committed copies have drifted."""
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "scripts"))
    try:
        from update_example_predictions import build_all  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(repo_root / "scripts"))

    for name, text in build_all(real_observed_dir).items():
        committed = (examples_dir() / name).read_text(encoding="utf-8")
        assert committed == text, (
            f"{name} has drifted from its generator; regenerate with "
            "`python scripts/update_example_predictions.py --confirm` "
            "and update the documented score tables"
        )
