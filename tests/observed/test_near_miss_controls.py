"""Near-miss controls: clean entities that resemble defects, and the proof that they are.

A near miss is the only entity in this benchmark that is *deliberately different
from truth and still a negative*. That is a dangerous exception, because a near
miss that drifted into being a real defect would sit in the control partition
labelled clean, and every agent that correctly flagged it would be marked wrong.

So the exception is not a relaxation. Ordinary controls keep field-for-field
truth equality, untouched; a near miss trades that for a stricter itemised
invariant, and each clause of it is attacked separately below by tampering with
a generated benchmark and checking the validator names the right thing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.company import load_config
from dataswamp_biosystems.observed.difficulty import Difficulty
from dataswamp_biosystems.observed.engine import ObservedResult, generate_observed
from dataswamp_biosystems.observed.errors import ObservedIssueKind, ObservedValidationError
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.scenarios import NEAR_MISS_VALIDITY_CHECKS
from dataswamp_biosystems.observed.validate import validate_observed
from dataswamp_biosystems.observed.writer import (
    OBSERVED_GRAPH_NAME,
    SCENARIO_TRANSFORMATIONS_NAME,
    write_observed,
)
from dataswamp_biosystems.truth import generate_truth_graph, load_generation_plan
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.conftest import CONFIG_DIR

SEED = 20260717


@pytest.fixture(scope="module")
def graph() -> TruthGraph:
    return generate_truth_graph(load_config(CONFIG_DIR), load_generation_plan(CONFIG_DIR), SEED)


@pytest.fixture(scope="module")
def result(graph: TruthGraph) -> ObservedResult:
    config = load_config(CONFIG_DIR)
    return generate_observed(graph, config, ObservedProfile.DEMO, SEED, Difficulty.ADVERSARIAL)


@pytest.fixture
def written(result: ObservedResult, tmp_path: Path) -> Path:
    target = tmp_path / "observed"
    write_observed(result, target)
    return target


def _validate(target: Path, graph: TruthGraph) -> list[Any]:
    """Validate ``target`` and return the issues, or an empty list if it is clean."""
    try:
        validate_observed(target, graph, load_config(CONFIG_DIR))
    except ObservedValidationError as exc:
        return exc.issues
    return []


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _rewrite(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# The partition claims
# ---------------------------------------------------------------------------


def test_every_near_miss_entity_is_a_reserved_control(result: ObservedResult) -> None:
    reserved = {control.id for control in result.controls if control.reserved}
    for record in result.transformations:
        assert record.entity_id in reserved, (
            f"{record.entity_id} carries a near miss but is not a reserved control"
        )


def test_no_near_miss_entity_appears_in_any_rules_selected_ids(result: ObservedResult) -> None:
    selected: set[str] = set()
    for scope in result.rule_scopes:
        selected.update(scope.selected_ids)
    assert not selected & {record.entity_id for record in result.transformations}


def test_no_near_miss_entity_is_targeted_by_a_defect_instance(result: ObservedResult) -> None:
    targeted = {instance.entity_id for instance in result.instances}
    assert not targeted & {record.entity_id for record in result.transformations}


def test_no_near_miss_entity_is_targeted_by_an_ordinary_mutation(
    result: ObservedResult,
) -> None:
    """A near miss must never enter the defect mutation ledger.

    Some rules mutate a *sibling* rather than their own subject, so this is a real
    hazard rather than a formality: an entity dressed as a near miss and then
    collaterally mutated would be a defect wearing a clean label.
    """
    mutated = {mutation.entity_id for mutation in result.mutations}
    assert not mutated & {record.entity_id for record in result.transformations}


def test_no_near_miss_entity_carries_an_expected_finding(result: ObservedResult) -> None:
    flagged = {finding.entity_id for finding in result.findings}
    assert not flagged & {record.entity_id for record in result.transformations}


def test_at_most_one_near_miss_is_applied_to_one_entity(result: ObservedResult) -> None:
    scenarios_by_entity: dict[str, set[str]] = {}
    for record in result.transformations:
        scenarios_by_entity.setdefault(record.entity_id, set()).add(record.scenario_id)
    assert all(len(ids) == 1 for ids in scenarios_by_entity.values())


# ---------------------------------------------------------------------------
# The value claim: still on the valid side of the rule it mimics
# ---------------------------------------------------------------------------


def test_every_emitted_near_miss_still_satisfies_its_validity_predicate(
    result: ObservedResult,
) -> None:
    """The claim that makes it a near miss rather than an unrecorded defect."""
    observed: dict[str, dict[str, Any]] = {}
    for shard, records in result.observed_graph.items():
        if shard == "meta" or not isinstance(records, list):
            continue
        for row in records:
            if isinstance(row, dict) and "id" in row:
                observed[str(row["id"])] = row
    for record in result.transformations:
        check = NEAR_MISS_VALIDITY_CHECKS[record.validity_check]
        assert check(observed[record.entity_id]), (
            f"{record.entity_id} fails {record.validity_condition!r} and so would "
            f"genuinely trigger {record.mimicked_rule_id}"
        )


def test_declared_before_and_after_match_the_two_graphs(
    result: ObservedResult, graph: TruthGraph
) -> None:
    truth = {
        str(row["id"]): row
        for shard in ("datasets", "data_products")
        for row in graph.model_dump(mode="json")[shard]
    }
    observed: dict[str, dict[str, Any]] = {}
    for shard, records in result.observed_graph.items():
        if shard == "meta" or not isinstance(records, list):
            continue
        for row in records:
            if isinstance(row, dict) and "id" in row:
                observed[str(row["id"])] = row
    for record in result.transformations:
        assert record.before == truth[record.entity_id][record.field]
        assert record.after == observed[record.entity_id][record.field]
        assert record.before != record.after, "a near miss that changed nothing claims nothing"


def test_only_declared_fields_differ_from_truth(result: ObservedResult, graph: TruthGraph) -> None:
    truth = {
        str(row["id"]): row
        for shard in ("datasets", "data_products")
        for row in graph.model_dump(mode="json")[shard]
    }
    observed: dict[str, dict[str, Any]] = {}
    for shard, records in result.observed_graph.items():
        if shard == "meta" or not isinstance(records, list):
            continue
        for row in records:
            if isinstance(row, dict) and "id" in row:
                observed[str(row["id"])] = row
    declared: dict[str, set[str]] = {}
    for record in result.transformations:
        declared.setdefault(record.entity_id, set()).add(record.field)
    for entity_id, fields in declared.items():
        changed = {
            key
            for key in set(observed[entity_id]) | set(truth[entity_id])
            if observed[entity_id].get(key) != truth[entity_id].get(key)
        }
        assert changed == fields, f"{entity_id} changed {sorted(changed - fields)} undeclared"


# ---------------------------------------------------------------------------
# Ordinary controls keep the strict equality
# ---------------------------------------------------------------------------


def test_ordinary_controls_remain_field_for_field_identical_to_truth(
    result: ObservedResult, graph: TruthGraph
) -> None:
    """The near-miss exception must not have loosened anything globally."""
    dump = graph.model_dump(mode="json")
    truth = {
        str(row["id"]): row
        for shard in ("datasets", "data_products", "files")
        for row in dump[shard]
    }
    observed: dict[str, dict[str, Any]] = {}
    for shard, records in result.observed_graph.items():
        if shard == "meta" or not isinstance(records, list):
            continue
        for row in records:
            if isinstance(row, dict) and "id" in row:
                observed[str(row["id"])] = row
    near_miss_ids = {record.entity_id for record in result.transformations}
    checked = 0
    for control in result.controls:
        if control.id in near_miss_ids or control.id not in truth:
            continue
        assert observed.get(control.id) == truth[control.id], control.id
        checked += 1
    assert checked > 100, "the ordinary-control check must actually be checking something"


def test_a_tampered_ordinary_control_is_still_reported(
    written: Path, graph: TruthGraph, result: ObservedResult
) -> None:
    near_miss_ids = {record.entity_id for record in result.transformations}
    document = json.loads((written / OBSERVED_GRAPH_NAME).read_text(encoding="utf-8"))
    control_ids = {c.id for c in result.controls if not c.reserved} - near_miss_ids
    for row in document["datasets"]:
        if row["id"] in control_ids:
            row["title"] = "quietly edited"
            target = row["id"]
            break
    (written / OBSERVED_GRAPH_NAME).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    issues = _validate(written, graph)
    assert any(
        issue.kind is ObservedIssueKind.CONTROL_PARTITION and issue.entity_id == target
        for issue in issues
    )


# ---------------------------------------------------------------------------
# Tampering: each clause of the near-miss invariant, attacked separately
# ---------------------------------------------------------------------------


def test_a_near_miss_pushed_over_the_line_is_reported_as_an_undeclared_defect(
    written: Path, graph: TruthGraph, result: ObservedResult
) -> None:
    """Push a near miss onto the *defective* side and check the validator says so."""
    target = next(
        record.entity_id
        for record in result.transformations
        if record.validity_check == "record-count-nonzero"
    )
    document = json.loads((written / OBSERVED_GRAPH_NAME).read_text(encoding="utf-8"))
    for row in document["datasets"]:
        if row["id"] == target:
            row["record_count"] = 0  # now genuinely SCH-RECORD-COUNT-ZERO
    (written / OBSERVED_GRAPH_NAME).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    issues = _validate(written, graph)
    near_miss_issues = [i for i in issues if i.kind is ObservedIssueKind.NEAR_MISS]
    assert near_miss_issues, "a near miss that became a defect must be reported"
    reported = [i for i in near_miss_issues if i.entity_id == target]
    assert reported, f"no issue names {target}"
    assert any("undeclared defect" in i.message for i in reported)
    assert any(i.field == "record_count" for i in reported)


def test_an_undeclared_field_change_on_a_near_miss_is_reported(
    written: Path, graph: TruthGraph, result: ObservedResult
) -> None:
    target = result.transformations[0].entity_id
    document = json.loads((written / OBSERVED_GRAPH_NAME).read_text(encoding="utf-8"))
    for row in document["datasets"]:
        if row["id"] == target:
            row["title"] = "smuggled in alongside a declared change"
    (written / OBSERVED_GRAPH_NAME).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    issues = _validate(written, graph)
    assert any(
        i.kind is ObservedIssueKind.NEAR_MISS
        and i.entity_id == target
        and i.field == "title"
        and "undeclared field" in i.message
        for i in issues
    )


def test_a_transformation_whose_before_value_is_wrong_is_reported(
    written: Path, graph: TruthGraph
) -> None:
    path = written / SCENARIO_TRANSFORMATIONS_NAME
    rows = _read(path)
    rows[0]["before"] = "not what truth holds"
    target = rows[0]["entity_id"]
    _rewrite(path, rows)

    issues = _validate(written, graph)
    assert any(
        i.kind is ObservedIssueKind.NEAR_MISS
        and i.entity_id == target
        and "declares before=" in i.message
        for i in issues
    )


def test_a_transformation_whose_after_value_is_wrong_is_reported(
    written: Path, graph: TruthGraph
) -> None:
    path = written / SCENARIO_TRANSFORMATIONS_NAME
    rows = _read(path)
    rows[0]["after"] = "not what the observed graph holds"
    target = rows[0]["entity_id"]
    _rewrite(path, rows)

    issues = _validate(written, graph)
    assert any(
        i.kind is ObservedIssueKind.NEAR_MISS
        and i.entity_id == target
        and "declares after=" in i.message
        for i in issues
    )


def test_a_transformation_naming_an_unknown_validity_check_is_reported(
    written: Path, graph: TruthGraph
) -> None:
    """An unverifiable claim to be a near miss is worth no more than no claim."""
    path = written / SCENARIO_TRANSFORMATIONS_NAME
    rows = _read(path)
    rows[0]["validity_check"] = "trust-me"
    target = rows[0]["entity_id"]
    _rewrite(path, rows)

    issues = _validate(written, graph)
    assert any(
        i.kind is ObservedIssueKind.NEAR_MISS
        and i.entity_id == target
        and "unknown validity check" in i.message
        for i in issues
    )


def test_the_untampered_benchmark_validates_cleanly(written: Path, graph: TruthGraph) -> None:
    """Guard the guards: every tamper test above must be failing for its own reason."""
    assert _validate(written, graph) == []
