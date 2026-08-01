"""``validate-observed`` control-partition tests: every tamper must be caught.

Each test writes a valid observed estate to a temporary directory, tampers with
exactly one emitted artefact, and asserts that validation fails with an issue
that names both the affected entity and the violated invariant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.engine import generate_observed
from dataswamp_biosystems.observed.errors import (
    ObservedIssue,
    ObservedIssueKind,
    ObservedValidationError,
)
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.validate import validate_observed
from dataswamp_biosystems.observed.writer import (
    CONTROLS_NAME,
    INJECTED_DEFECTS_NAME,
    MUTATION_LOG_NAME,
    OBSERVED_GRAPH_NAME,
    RULE_SCOPE_NAME,
    write_observed,
)
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.observed.conftest import TEST_SEED


def _write(graph: TruthGraph, config: CanonicalConfig, out: Path) -> Path:
    result = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED)
    write_observed(result, out)
    return out


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_rows(path: Path, rows: list[dict]) -> None:
    text = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
    path.write_text(text + "\n", encoding="utf-8")


def _issues(graph: TruthGraph, config: CanonicalConfig, out: Path) -> list[ObservedIssue]:
    with pytest.raises(ObservedValidationError) as excinfo:
        validate_observed(out, graph, config)
    return excinfo.value.issues


def _kinds(issues: list[ObservedIssue]) -> set[ObservedIssueKind]:
    return {issue.kind for issue in issues}


def test_valid_control_partition_passes(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    validate_observed(out, graph, config)  # must not raise


def test_missing_control_record_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / CONTROLS_NAME)
    dropped = rows[0]["id"]
    _write_rows(out / CONTROLS_NAME, rows[1:])

    issues = _issues(graph, config, out)
    assert ObservedIssueKind.CONTROL_PARTITION in _kinds(issues)
    assert any(
        issue.entity_id == dropped and "not emitted" in issue.message
        for issue in issues
        if issue.kind is ObservedIssueKind.CONTROL_PARTITION
    )


def test_extra_control_record_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    """An entity that actually carries a defect may not be declared clean."""
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / CONTROLS_NAME)
    mutated_id = _rows(out / INJECTED_DEFECTS_NAME)[0]["entity_id"]
    extra = {**rows[0], "id": mutated_id}
    _write_rows(out / CONTROLS_NAME, [*rows, extra])

    issues = _issues(graph, config, out)
    assert ObservedIssueKind.CONTROL_PARTITION in _kinds(issues)
    assert ObservedIssueKind.CONTAMINATION in _kinds(issues)
    assert any(issue.entity_id == mutated_id for issue in issues)


def test_duplicate_control_identifier_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / CONTROLS_NAME)
    _write_rows(out / CONTROLS_NAME, [*rows, rows[0]])

    issues = _issues(graph, config, out)
    assert ObservedIssueKind.DUPLICATE_ID in _kinds(issues)
    assert any(
        issue.entity_id == rows[0]["id"] and "duplicate control id" in issue.message
        for issue in issues
    )


def test_unknown_control_identifier_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / CONTROLS_NAME)
    rows[0] = {**rows[0], "id": "ds-does-not-exist-9999"}
    _write_rows(out / CONTROLS_NAME, rows)

    issues = _issues(graph, config, out)
    assert ObservedIssueKind.UNRESOLVED_REFERENCE in _kinds(issues)
    assert any(
        issue.entity_id == "ds-does-not-exist-9999" and "does not resolve" in issue.message
        for issue in issues
    )


def test_defect_instance_targeting_a_control_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    control_id = _rows(out / CONTROLS_NAME)[0]["id"]
    rows = _rows(out / INJECTED_DEFECTS_NAME)
    rows[0] = {**rows[0], "entity_id": control_id}
    _write_rows(out / INJECTED_DEFECTS_NAME, rows)

    issues = _issues(graph, config, out)
    assert ObservedIssueKind.CONTAMINATION in _kinds(issues)
    assert any(
        issue.entity_id == control_id and "targets control entity" in issue.message
        for issue in issues
    )


def test_mutation_record_targeting_a_control_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    control_id = _rows(out / CONTROLS_NAME)[0]["id"]
    rows = _rows(out / MUTATION_LOG_NAME)
    rows[0] = {**rows[0], "entity_id": control_id}
    _write_rows(out / MUTATION_LOG_NAME, rows)

    issues = _issues(graph, config, out)
    contamination = [i for i in issues if i.kind is ObservedIssueKind.CONTAMINATION]
    assert any(i.entity_id == control_id and i.entity_kind == "mutation" for i in contamination)


def test_modified_control_entity_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    """A control whose observed record drifts from truth is reported by name."""
    out = _write(graph, config, tmp_path / "observed")
    control = next(row for row in _rows(out / CONTROLS_NAME) if row["shard"] == "datasets")
    payload = json.loads((out / OBSERVED_GRAPH_NAME).read_text(encoding="utf-8"))
    for record in payload["datasets"]:
        if record["id"] == control["id"]:
            record["description"] = ""
    (out / OBSERVED_GRAPH_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    issues = _issues(graph, config, out)
    partition = [i for i in issues if i.kind is ObservedIssueKind.CONTROL_PARTITION]
    assert any(
        i.entity_id == control["id"] and "differs from truth" in i.message and i.field
        for i in partition
    )


def test_control_metadata_inconsistency_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / CONTROLS_NAME)
    target = next(row for row in rows if row["reserved"] is True)
    target["reserved"] = False
    _write_rows(out / CONTROLS_NAME, rows)

    issues = _issues(graph, config, out)
    assert any(
        i.kind is ObservedIssueKind.CONTROL_PARTITION
        and i.entity_id == target["id"]
        and i.field == "reserved"
        for i in issues
    )


def test_missing_controls_file_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    (out / CONTROLS_NAME).unlink()

    issues = _issues(graph, config, out)
    assert any(CONTROLS_NAME in i.message for i in issues)


def test_unparsable_controls_file_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    (out / CONTROLS_NAME).write_text("{not json}\n", encoding="utf-8")

    issues = _issues(graph, config, out)
    assert any("not valid JSON" in i.message for i in issues)


# -- rule scope ---------------------------------------------------------------


def test_rule_scope_count_inconsistency_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / RULE_SCOPE_NAME)
    rows[0]["eligible_count"] = rows[0]["eligible_count"] + 5
    _write_rows(out / RULE_SCOPE_NAME, rows)

    issues = _issues(graph, config, out)
    assert any(
        i.kind is ObservedIssueKind.CONTROL_PARTITION and i.field == "eligible_count"
        for i in issues
    )


def test_rule_scope_listing_a_control_as_eligible_and_excluded_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / RULE_SCOPE_NAME)
    target = next(row for row in rows if row["control_excluded_ids"])
    target["eligible_ids"] = [*target["eligible_ids"], target["control_excluded_ids"][0]]
    target["eligible_count"] = len(target["eligible_ids"])
    _write_rows(out / RULE_SCOPE_NAME, rows)

    issues = _issues(graph, config, out)
    assert any(
        i.kind is ObservedIssueKind.CONTROL_PARTITION
        and i.entity_id == target["id"]
        and "both" in i.message
        for i in issues
    )


def test_rule_scope_listing_a_reserved_control_as_eligible_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    """A reserved control may never appear in a rule's eligible population."""
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / RULE_SCOPE_NAME)
    target = next(row for row in rows if row["control_excluded_ids"])
    moved = target["control_excluded_ids"][0]
    target["control_excluded_ids"] = [i for i in target["control_excluded_ids"] if i != moved]
    target["control_excluded_count"] = len(target["control_excluded_ids"])
    target["eligible_ids"] = sorted([*target["eligible_ids"], moved])
    target["eligible_count"] = len(target["eligible_ids"])
    _write_rows(out / RULE_SCOPE_NAME, rows)

    issues = _issues(graph, config, out)
    assert any(
        i.kind is ObservedIssueKind.CONTROL_PARTITION
        and i.entity_id == target["id"]
        and "reserved control entities" in i.message
        for i in issues
    )


def test_rule_scope_selecting_a_control_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    control_id = _rows(out / CONTROLS_NAME)[0]["id"]
    rows = _rows(out / RULE_SCOPE_NAME)
    target = next(row for row in rows if row["selected_ids"])
    target["selected_ids"] = sorted([*target["selected_ids"], control_id])
    target["selected_count"] = len(target["selected_ids"])
    target["eligible_ids"] = sorted([*target["eligible_ids"], control_id])
    target["eligible_count"] = len(target["eligible_ids"])
    _write_rows(out / RULE_SCOPE_NAME, rows)

    issues = _issues(graph, config, out)
    assert any(
        i.kind is ObservedIssueKind.CONTAMINATION and i.entity_kind == "rule-scope" for i in issues
    )


def test_missing_rule_scope_record_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / RULE_SCOPE_NAME)
    dropped = rows[0]["id"]
    _write_rows(out / RULE_SCOPE_NAME, rows[1:])

    issues = _issues(graph, config, out)
    assert any(
        i.kind is ObservedIssueKind.CONTROL_PARTITION
        and i.entity_id == dropped
        and "no emitted rule-scope record" in i.message
        for i in issues
    )


def test_rule_scope_unknown_rule_fails(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / RULE_SCOPE_NAME)
    rows[0] = {**rows[0], "id": "NO-SUCH-RULE"}
    _write_rows(out / RULE_SCOPE_NAME, rows)

    issues = _issues(graph, config, out)
    assert any(
        i.kind is ObservedIssueKind.UNKNOWN_RULE and i.entity_id == "NO-SUCH-RULE" for i in issues
    )


def test_issue_messages_identify_entity_and_invariant(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    """Every control-partition issue must render an actionable location."""
    out = _write(graph, config, tmp_path / "observed")
    rows = _rows(out / CONTROLS_NAME)
    _write_rows(out / CONTROLS_NAME, rows[1:])

    issues = _issues(graph, config, out)
    partition = [i for i in issues if i.kind is ObservedIssueKind.CONTROL_PARTITION]
    assert partition
    for issue in partition:
        rendered = issue.render()
        assert issue.kind.value in rendered
        assert issue.entity_id in rendered
        assert issue.message in rendered
