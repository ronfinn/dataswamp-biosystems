"""The prediction contract: what a submission must look like, and how it fails.

Nothing here is about scoring. These tests pin the promise that a broken
submission is *reported*, never silently dropped or best-effort coerced, and
that every rejection names the line, field, value and expected contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.evaluation import (
    EvaluationConfigError,
    PredictionIssueKind,
    PredictionValidationError,
    load_ground_truth,
    parse_predictions,
)

VALID = {
    "schema_version": 1,
    "prediction_id": "p1",
    "entity_id": "ds-alpha",
    "rule_id": "TINY-AUTO",
    "status": "finding",
}


@pytest.fixture()
def universe(tiny_observed_dir: Path) -> tuple[frozenset[str], frozenset[str]]:
    truth = load_ground_truth(tiny_observed_dir)
    return truth.known_entities, truth.rule_ids


def _parse(rows: list[dict], universe: tuple[frozenset[str], frozenset[str]]):
    entities, rules = universe
    text = "\n".join(json.dumps(row) for row in rows) + "\n"
    return parse_predictions(text, known_entities=entities, known_rules=rules)


def _issues(rows: list[dict] | str, universe: tuple[frozenset[str], frozenset[str]]):
    entities, rules = universe
    text = rows if isinstance(rows, str) else "\n".join(json.dumps(r) for r in rows) + "\n"
    with pytest.raises(PredictionValidationError) as excinfo:
        parse_predictions(text, known_entities=entities, known_rules=rules)
    return excinfo.value.issues


# -- what is accepted ---------------------------------------------------------


def test_a_minimal_finding_is_valid(universe) -> None:
    (prediction,) = _parse([VALID], universe)
    assert prediction.claims_finding
    assert prediction.confidence is None
    assert prediction.remediation is None


def test_a_finding_with_a_remediation_is_valid(universe) -> None:
    row = {
        **VALID,
        "confidence": 0.5,
        "remediation": {
            "action_class": "restore_field",
            "availability": "automatic",
            "approval_policy": "not-required",
        },
    }
    (prediction,) = _parse([row], universe)
    assert prediction.remediation is not None
    assert prediction.remediation.action_class == "restore_field"


def test_an_explicit_clean_and_an_abstention_are_both_valid(universe) -> None:
    rows = [
        {**VALID, "prediction_id": "c", "status": "clean"},
        {**VALID, "prediction_id": "a", "rule_id": "TINY-APPROVE", "status": "abstain"},
    ]
    abstain, clean = sorted(_parse(rows, universe), key=lambda p: p.status)
    assert abstain.abstains
    assert not clean.claims_finding and not clean.abstains


def test_a_prediction_may_omit_the_rule_id(universe) -> None:
    row = {**VALID, "rule_id": "", "category": "metadata-completeness"}
    (prediction,) = _parse([row], universe)
    assert prediction.rule_id == ""


def test_blank_lines_are_not_records(universe) -> None:
    entities, rules = universe
    assert parse_predictions("\n\n", known_entities=entities, known_rules=rules) == []


def test_parsed_predictions_are_ordered_independently_of_file_order(universe) -> None:
    rows = [
        {**VALID, "prediction_id": "z", "entity_id": "ds-charlie"},
        {**VALID, "prediction_id": "a", "entity_id": "ds-bravo"},
    ]
    assert [p.entity_id for p in _parse(rows, universe)] == ["ds-bravo", "ds-charlie"]


# -- what is rejected ---------------------------------------------------------


def test_malformed_json_is_reported_with_its_line(universe) -> None:
    text = json.dumps(VALID) + "\n{not json\n"
    (issue,) = _issues(text, universe)
    assert issue.kind is PredictionIssueKind.MALFORMED_JSON
    assert issue.line == 2


def test_a_non_object_line_is_rejected(universe) -> None:
    (issue,) = _issues("[1, 2, 3]\n", universe)
    assert issue.kind is PredictionIssueKind.MALFORMED_JSON
    assert "object" in issue.expected


def test_an_unsupported_schema_version_is_rejected(universe) -> None:
    (issue,) = _issues([{**VALID, "schema_version": 99}], universe)
    assert issue.kind is PredictionIssueKind.SCHEMA_VERSION
    assert issue.field == "schema_version"


def test_a_duplicate_pair_is_rejected(universe) -> None:
    rows = [VALID, {**VALID, "prediction_id": "p2"}]
    (issue,) = _issues(rows, universe)
    assert issue.kind is PredictionIssueKind.DUPLICATE_PAIR
    assert issue.line == 2


def test_a_duplicate_prediction_id_is_rejected(universe) -> None:
    rows = [VALID, {**VALID, "rule_id": "TINY-APPROVE"}]
    (issue,) = _issues(rows, universe)
    assert issue.kind is PredictionIssueKind.DUPLICATE_ID


def test_an_unknown_entity_is_rejected(universe) -> None:
    (issue,) = _issues([{**VALID, "entity_id": "ds-nowhere"}], universe)
    assert issue.kind is PredictionIssueKind.UNKNOWN_ENTITY
    assert issue.value == "ds-nowhere"


def test_an_unknown_rule_is_rejected(universe) -> None:
    (issue,) = _issues([{**VALID, "rule_id": "NOT-A-RULE"}], universe)
    assert issue.kind is PredictionIssueKind.UNKNOWN_RULE


def test_an_unknown_status_is_rejected(universe) -> None:
    (issue,) = _issues([{**VALID, "status": "maybe"}], universe)
    assert issue.kind is PredictionIssueKind.INVALID_FIELD
    assert issue.field == "status"


def test_an_invalid_enum_value_is_rejected(universe) -> None:
    (issue,) = _issues([{**VALID, "severity": "catastrophic"}], universe)
    assert issue.kind is PredictionIssueKind.INVALID_FIELD
    assert issue.field == "severity"


def test_an_unknown_field_is_rejected(universe) -> None:
    (issue,) = _issues([{**VALID, "smugness": 11}], universe)
    assert issue.kind is PredictionIssueKind.INVALID_FIELD


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_confidence_outside_the_supported_range_is_rejected(universe, value: float) -> None:
    (issue,) = _issues([{**VALID, "confidence": value}], universe)
    assert issue.field == "confidence"


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_confidence_is_rejected(universe, literal: str) -> None:
    """JSON's NaN/Infinity extensions parse happily; the contract must not."""
    text = json.dumps(VALID).replace('"status"', f'"confidence": {literal}, "status"')
    (issue,) = _issues(text + "\n", universe)
    assert issue.field == "confidence"


def test_a_remediation_on_a_clean_prediction_is_contradictory(universe) -> None:
    row = {
        **VALID,
        "status": "clean",
        "remediation": {
            "action_class": "restore_field",
            "availability": "automatic",
            "approval_policy": "not-required",
        },
    }
    (issue,) = _issues([row], universe)
    assert issue.kind is PredictionIssueKind.CONTRADICTION
    assert issue.field == "remediation"


def test_an_actionable_remediation_declared_non_remediable_is_contradictory(universe) -> None:
    row = {
        **VALID,
        "remediation": {
            "action_class": "restore_field",
            "availability": "none",
            "approval_policy": "not-required",
        },
    }
    (issue,) = _issues([row], universe)
    assert issue.kind is PredictionIssueKind.CONTRADICTION
    assert issue.field == "remediation.action_class"


def test_a_no_remediation_action_with_an_actionable_availability_is_contradictory(
    universe,
) -> None:
    row = {
        **VALID,
        "remediation": {
            "action_class": "no-remediation",
            "availability": "automatic",
            "approval_policy": "not-required",
        },
    }
    (issue,) = _issues([row], universe)
    assert issue.field == "remediation.availability"


def test_required_approval_without_an_approver_is_rejected(universe) -> None:
    row = {
        **VALID,
        "remediation": {
            "action_class": "reclassify_asset",
            "availability": "automatic",
            "approval_policy": "required",
        },
    }
    (issue,) = _issues([row], universe)
    assert issue.kind is PredictionIssueKind.CONTRADICTION
    assert issue.field == "remediation.approver_role"


def test_every_problem_in_a_file_is_reported_at_once(universe) -> None:
    """A submission is validated in full, so one run fixes the whole file."""
    rows = [
        {**VALID, "prediction_id": "p1", "entity_id": "ds-nowhere"},
        {**VALID, "prediction_id": "p1", "rule_id": "NOT-A-RULE"},
    ]
    issues = _issues(rows, universe)
    kinds = {issue.kind for issue in issues}
    assert PredictionIssueKind.UNKNOWN_ENTITY in kinds
    assert PredictionIssueKind.UNKNOWN_RULE in kinds
    assert PredictionIssueKind.DUPLICATE_ID in kinds


def test_issues_render_the_line_field_value_and_contract(universe) -> None:
    (issue,) = _issues([{**VALID, "rule_id": "NOT-A-RULE"}], universe)
    rendered = issue.render()
    assert "line 1" in rendered
    assert "field=rule_id" in rendered
    assert "NOT-A-RULE" in rendered
    assert "rule-scope.jsonl" in rendered


def test_a_missing_prediction_file_is_a_config_error(tiny_observed_dir: Path) -> None:
    from dataswamp_biosystems.evaluation import load_predictions

    truth = load_ground_truth(tiny_observed_dir)
    with pytest.raises(EvaluationConfigError):
        load_predictions(
            tiny_observed_dir / "nope.jsonl",
            known_entities=truth.known_entities,
            known_rules=truth.rule_ids,
        )
