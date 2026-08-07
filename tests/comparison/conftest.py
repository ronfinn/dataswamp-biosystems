"""Fixtures for the comparison tests.

Built entirely on the evaluator's existing tiny ground truth (see
``tests/evaluation/conftest.py``): four rules, eleven in-scope pairs, small
enough that every transition asserted below can be counted on paper. Inventing a
second benchmark universe here would mean maintaining two answer keys and
proving the comparison against the one the evaluator does not use.

Submissions are written as prediction JSONL and scored through the *real*
evaluator, so the evaluation directories a comparison reads are the genuine
article rather than hand-assembled summaries. That matters: the comparison's job
is to difference the evaluator's own output, and a fixture that skipped the
evaluator could not catch a drift between them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.evaluation import (
    evaluate,
    load_ground_truth,
    load_predictions,
    write_evaluation,
)

# Re-exported so the comparison tests name the same rules the evaluator's own
# fixtures do.
from tests.evaluation.conftest import (  # noqa: F401  (fixture import for pytest)
    RULE_APPROVE,
    RULE_AUTO,
    RULE_MANUAL,
    RULE_NONE,
    tiny_observed_dir,
)

# One prediction per rule, matching the tiny ground truth's expected findings.
_REMEDIATIONS: dict[str, dict[str, Any]] = {
    RULE_AUTO: {
        "action_class": "restore_field",
        "availability": "automatic",
        "approval_policy": "not-required",
        "approver_role": "none",
        "recommended_value": "Restored title",
    },
    RULE_APPROVE: {
        "action_class": "reclassify_asset",
        "availability": "automatic",
        "approval_policy": "required",
        "approver_role": "access-steward",
        "recommended_value": "restricted",
    },
    RULE_MANUAL: {
        "action_class": "rewrite_field",
        "availability": "manual",
        "approval_policy": "not-required",
        "approver_role": "none",
    },
    RULE_NONE: {
        "action_class": "no-remediation",
        "availability": "none",
        "approval_policy": "not-required",
        "approver_role": "none",
    },
}

_CATEGORIES = {
    RULE_AUTO: ("metadata-completeness", "high"),
    RULE_APPROVE: ("governance-classification", "medium"),
    RULE_MANUAL: ("semantic-quality", "low"),
    RULE_NONE: ("file-integrity", "high"),
}

# The four positive pairs of the tiny ground truth.
DEFECTS: tuple[tuple[str, str], ...] = (
    ("ds-alpha", RULE_AUTO),
    ("ds-bravo", RULE_APPROVE),
    ("ds-charlie", RULE_MANUAL),
    ("file-one", RULE_NONE),
)

# A reserved control: held out before selection, so it could never carry a
# defect and every flag against it is a false positive by construction.
RESERVED_CONTROL = "ds-reserved"
# An ordinary (eligible-but-unselected) control.
ORDINARY_CONTROL = "ds-delta"


def finding(
    entity_id: str,
    rule_id: str,
    *,
    remediation: bool = True,
    prediction_id: str | None = None,
) -> dict[str, Any]:
    """One prediction claiming a finding, optionally carrying its remediation."""
    category, severity = _CATEGORIES[rule_id]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "prediction_id": prediction_id or f"{rule_id}-{entity_id}",
        "entity_id": entity_id,
        "rule_id": rule_id,
        "status": "finding",
        "category": category,
        "severity": severity,
        "confidence": 0.9,
        "evidence": "synthetic fixture evidence",
    }
    if remediation:
        payload["remediation"] = dict(_REMEDIATIONS[rule_id])
    return payload


def wrong_remediation(entity_id: str, rule_id: str) -> dict[str, Any]:
    """A detected finding whose remediation decision is wrong in every field."""
    payload = finding(entity_id, rule_id)
    payload["remediation"] = {
        "action_class": "delete_asset",
        "availability": "manual",
        "approval_policy": "required",
        "approver_role": "data-owner",
        "recommended_value": "definitely-not-the-expected-value",
    }
    return payload


def write_evaluation_dir(
    observed_dir: Path,
    target: Path,
    predictions: list[dict[str, Any]],
) -> Path:
    """Score ``predictions`` against ``observed_dir`` and emit a real evaluation."""
    submission = target.parent / f"{target.name}-predictions.jsonl"
    submission.parent.mkdir(parents=True, exist_ok=True)
    submission.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in predictions),
        encoding="utf-8",
    )

    truth = load_ground_truth(observed_dir)
    parsed, _ = load_predictions(
        submission, known_entities=truth.known_entities, known_rules=truth.rule_ids
    )
    result = evaluate(truth, parsed, prediction_digest=f"digest-{target.name}")
    write_evaluation(result, target)
    return target


@pytest.fixture()
def make_run(tiny_observed_dir: Path, tmp_path: Path):  # noqa: ANN201, F811 - pytest factory
    """Return a factory writing a named evaluation directory from predictions."""

    def _make(name: str, predictions: list[dict[str, Any]]) -> Path:
        return write_evaluation_dir(tiny_observed_dir, tmp_path / name, predictions)

    return _make


@pytest.fixture()
def perfect_run(make_run) -> Path:  # noqa: ANN001
    """Every defect found, every remediation correct, no control flagged."""
    return make_run("perfect", [finding(entity, rule) for entity, rule in DEFECTS])


@pytest.fixture()
def silent_run(make_run) -> Path:  # noqa: ANN001
    """Predicts nothing: the recall floor and the specificity ceiling."""
    return make_run("silent", [])
