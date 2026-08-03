#!/usr/bin/env python
"""Regenerate the committed canonical baseline scores.

``tests/baselines/fixtures/baseline-scores.json`` pins what each reference
baseline scores against the canonical ``demo`` scenario. It is a *regression*
fixture: its job is to fail loudly when a baseline's behaviour changes, so that
a change to a heuristic is a deliberate, reviewed edit to a published number
rather than a silent drift.

It is necessarily derived from the same code it pins, which is why rewriting it
is gated. ``tests/baselines/test_scores.py`` also asserts a handful of
properties that do *not* come from the fixture — the null baseline predicts
nothing, the naive baseline's precision is below 1.0, the rule-based baseline
emits only rules it declares — so a wholesale regeneration cannot quietly
launder a broken agent into a green suite.

Runtime is deliberately absent from the fixture. It is machine-dependent, and a
pinned wall-clock number would fail on a slow CI runner for no reason.

Usage::

    uv run --frozen python scripts/update_baseline_scores.py --confirm \\
        --reason "rule-based agent now checks contract resolution"

Update the score tables in ``README.md`` and ``docs/baselines.md`` to match, and
review the diff: a change here is a change to a published benchmark result.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dataswamp_biosystems.baselines import (  # noqa: E402
    BASELINE_NAMES,
    ObservedInput,
    get_baseline,
    render_predictions,
    run_baseline,
)
from dataswamp_biosystems.canonical import (  # noqa: E402
    OBSERVED_DIRNAME,
    generate_canonical_from_config_dir,
)
from dataswamp_biosystems.evaluation import (  # noqa: E402
    GroundTruth,
    evaluate,
    load_ground_truth,
    parse_predictions,
    prediction_digest,
)

FIXTURE_PATH = REPO_ROOT / "tests" / "baselines" / "fixtures" / "baseline-scores.json"

# The fixture's own version. Bump it when the *shape* of the file changes, so a
# stale fixture is rejected rather than partially compared.
BASELINE_SCORES_SCHEMA_VERSION = 1


def _metric(block: dict[str, Any], name: str) -> dict[str, Any]:
    metric = block["metrics"][name]
    return {
        "value": metric["value"],
        "numerator": metric["numerator"],
        "denominator": metric["denominator"],
    }


def score_baseline(name: str, truth: GroundTruth, observed: ObservedInput) -> dict[str, Any]:
    """Run one baseline against the canonical benchmark and summarise its score."""
    run = run_baseline(get_baseline(name), observed)
    text = render_predictions(run.predictions)
    submitted = parse_predictions(
        text, known_entities=truth.known_entities, known_rules=truth.rule_ids
    )
    summary = evaluate(
        truth, submitted, prediction_digest=prediction_digest(text.encode("utf-8"))
    ).summary

    micro = summary["findings"]["overall_micro"]
    reserved = summary["reserved_controls"]
    remediation = summary["remediation"]

    return {
        "agent": {"name": run.info.name, "version": run.info.version},
        "predictions": run.prediction_count,
        "rules_used": list(run.rules_used),
        "counts": {key: micro["counts"][key] for key in ("tp", "fp", "fn", "tn")},
        "findings": {
            name: _metric(micro, name) for name in ("precision", "recall", "specificity", "f1")
        },
        "reserved_controls": {
            "pairs": reserved["counts"]["total"],
            "false_positives": reserved["false_positives"],
            # Reported as a rate as well as a count: a count alone cannot be
            # compared between scenarios with different control partitions.
            "false_positive_rate": (
                reserved["false_positives"] / reserved["counts"]["total"]
                if reserved["counts"]["total"]
                else None
            ),
        },
        "out_of_scope_false_positives": summary["out_of_scope"]["false_positives"],
        "remediation": {
            "submitted": remediation["counts"]["submitted"],
            "fully_correct": remediation["counts"]["fully_correct"],
            "unsafe_actions": remediation["counts"]["unsafe_actions"],
            "coverage": _metric(remediation, "coverage"),
            "correctness_given_true_positive": _metric(
                remediation, "correctness_given_true_positive"
            ),
            "end_to_end": _metric(remediation, "end_to_end"),
        },
    }


def build_scores(observed_dir: Path) -> dict[str, Any]:
    """Return the whole fixture document for the benchmark at ``observed_dir``."""
    truth = load_ground_truth(observed_dir)
    observed = ObservedInput.load(observed_dir)
    return {
        "schema_version": BASELINE_SCORES_SCHEMA_VERSION,
        # A baseline score is only comparable to another quoting the same
        # scenario identity, so it is recorded next to the numbers, not in prose.
        "benchmark": {
            "profile": truth.meta["profile"],
            "defect_seed": truth.meta["defect_seed"],
            "truth_seed": truth.meta["truth_seed"],
            "generator_version": truth.meta["generator_version"],
            "truth_generator_version": truth.meta["truth_generator_version"],
            "ground_truth_fingerprint": truth.fingerprint,
            "expected_findings": len(truth.findings),
        },
        "baselines": {name: score_baseline(name, truth, observed) for name in BASELINE_NAMES},
    }


def render(scores: dict[str, Any]) -> str:
    return json.dumps(scores, indent=2, sort_keys=True) + "\n"


def build_from_canonical_config() -> dict[str, Any]:
    """Generate the canonical scenario into a temporary directory and score it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "generated"
        generate_canonical_from_config_dir(root, REPO_ROOT / "config")
        return build_scores(root / OBSERVED_DIRNAME)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Rewrites the committed baseline scores in place.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Why the published baseline scores are changing. Recorded in the commit message.",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("refusing to rewrite the baseline scores without --confirm")

    scores = build_from_canonical_config()
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(render(scores), encoding="utf-8")
    print(f"wrote {FIXTURE_PATH}")
    print(f"reason: {args.reason}")
    for name, block in scores["baselines"].items():
        metrics = block["findings"]
        print(
            f"  {name}: {block['predictions']} prediction(s), "
            f"precision {metrics['precision']['value']}, recall {metrics['recall']['value']}"
        )
    print("\nRemember to update the score tables in README.md and docs/baselines.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
