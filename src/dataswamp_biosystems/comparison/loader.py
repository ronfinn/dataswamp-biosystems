"""Read one already-emitted evaluation directory, read-only.

The comparison layer sits strictly *downstream* of the evaluation contract: it
consumes what ``dataswamp evaluate`` wrote and never re-scores a submission,
never reads a prediction file, and never touches the observed ground truth. That
is what makes a comparison cheap, reproducible and impossible to disagree with
the evaluation it is comparing — the numbers are the evaluator's own.

Only the files a comparison actually needs are read. ``scenario-metrics.jsonl``
is optional by construction (the evaluator omits it unless the benchmark
declares adversarial scenarios), so its absence is a fact about the run, not an
error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataswamp_biosystems.comparison.errors import ComparisonConfigError
from dataswamp_biosystems.evaluation.writer import (
    DIFFICULTY_METRICS_NAME,
    EVALUATION_SUMMARY_NAME,
    FINDING_RESULTS_NAME,
    REMEDIATION_RESULTS_NAME,
    RULE_METRICS_NAME,
    SCENARIO_METRICS_NAME,
)

# Every file a comparison reads. ``scenario-metrics.jsonl`` is deliberately not
# here: it is emitted only for an adversarial benchmark.
REQUIRED_FILES: tuple[str, ...] = (
    EVALUATION_SUMMARY_NAME,
    FINDING_RESULTS_NAME,
    REMEDIATION_RESULTS_NAME,
    RULE_METRICS_NAME,
    DIFFICULTY_METRICS_NAME,
)

# Summary keys a comparison depends on. Checked up front so a truncated or
# hand-edited summary fails with "malformed evaluation output" rather than with a
# KeyError from somewhere deep in the delta code.
_REQUIRED_SUMMARY_KEYS: tuple[str, ...] = (
    "benchmark",
    "universe",
    "findings",
    "dimensions",
    "remediation",
    "reserved_controls",
    "out_of_scope",
    "abstention",
    "adversarial",
    "evaluator_version",
    "evaluation_schema_version",
    "prediction_schema_version",
    "submission",
)


@dataclass(frozen=True)
class EvaluationRun:
    """One emitted evaluation directory, parsed into the pieces a comparison needs."""

    path: Path
    summary: dict[str, Any]
    finding_results: dict[tuple[str, str], dict[str, Any]]
    remediation_results: dict[tuple[str, str], dict[str, Any]]
    rule_metrics: dict[str, dict[str, Any]]
    difficulty_metrics: dict[str, dict[str, Any]]
    scenario_metrics: dict[str, dict[str, Any]]

    @property
    def benchmark(self) -> dict[str, Any]:
        return dict(self.summary["benchmark"])

    @property
    def prediction_sha256(self) -> str:
        return str(self.summary["submission"].get("prediction_sha256", ""))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ComparisonConfigError(f"could not read {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ComparisonConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComparisonConfigError(f"{path} must contain a JSON object")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, tolerating only a genuinely empty file.

    The evaluator writes zero bytes for an empty record set, so "no lines" is a
    legitimate state; a line that is not a JSON object is not.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ComparisonConfigError(f"could not read {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComparisonConfigError(f"{path} line {number} is not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ComparisonConfigError(f"{path} line {number} must be a JSON object")
        rows.append(row)
    return rows


def _by_pair(rows: list[dict[str, Any]], path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Index records by their ``(entity_id, rule_id)`` pair.

    The pair — not the ``id`` string — is the comparison's join key, because it
    is the unit the evaluator scores on and the unit a regression is attributed
    to.
    """
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        entity_id = row.get("entity_id")
        rule_id = row.get("rule_id")
        if not isinstance(entity_id, str) or not isinstance(rule_id, str):
            raise ComparisonConfigError(
                f"{path} contains a record without a string entity_id/rule_id"
            )
        indexed[(entity_id, rule_id)] = row
    return indexed


def _by_id(rows: list[dict[str, Any]], path: Path) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        group_id = row.get("id")
        if not isinstance(group_id, str):
            raise ComparisonConfigError(f"{path} contains a record without a string id")
        indexed[group_id] = row
    return indexed


def load_run(evaluation_dir: Path | str) -> EvaluationRun:
    """Load one emitted evaluation directory without modifying it."""
    path = Path(evaluation_dir)
    if not path.is_dir():
        raise ComparisonConfigError(f"{path} is not a directory")

    missing = [name for name in REQUIRED_FILES if not (path / name).is_file()]
    if missing:
        raise ComparisonConfigError(
            f"{path} is not an evaluation directory; missing {', '.join(sorted(missing))}"
        )

    summary = _read_json(path / EVALUATION_SUMMARY_NAME)
    absent = [key for key in _REQUIRED_SUMMARY_KEYS if key not in summary]
    if absent:
        raise ComparisonConfigError(
            f"{path / EVALUATION_SUMMARY_NAME} is missing required key(s): "
            f"{', '.join(sorted(absent))}"
        )

    scenario_path = path / SCENARIO_METRICS_NAME
    scenario_rows = _read_jsonl(scenario_path) if scenario_path.is_file() else []

    return EvaluationRun(
        path=path,
        summary=summary,
        finding_results=_by_pair(
            _read_jsonl(path / FINDING_RESULTS_NAME), path / FINDING_RESULTS_NAME
        ),
        remediation_results=_by_pair(
            _read_jsonl(path / REMEDIATION_RESULTS_NAME), path / REMEDIATION_RESULTS_NAME
        ),
        rule_metrics=_by_id(_read_jsonl(path / RULE_METRICS_NAME), path / RULE_METRICS_NAME),
        difficulty_metrics=_by_id(
            _read_jsonl(path / DIFFICULTY_METRICS_NAME), path / DIFFICULTY_METRICS_NAME
        ),
        scenario_metrics=_by_id(scenario_rows, scenario_path),
    )


__all__ = ["REQUIRED_FILES", "EvaluationRun", "load_run"]
