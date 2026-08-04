"""Write an :class:`EvaluationResult` to the canonical ``generated/evaluation/`` layout.

Output is staged in a temporary sibling directory and swapped into place with
directory renames (mirroring the truth and observed writers), so a failing run
never leaves a partial directory and any previous output is restored on failure.
Every byte goes through the shared canonical serializer, and nothing written here
carries a wall-clock value — identical inputs produce byte-identical reports.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from dataswamp_biosystems.evaluation.engine import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATOR_VERSION,
    EvaluationResult,
)
from dataswamp_biosystems.provenance import PROVENANCE_NAME, provenance_bytes
from dataswamp_biosystems.truth import serialize

EVALUATION_SUMMARY_NAME = "evaluation-summary.json"
FINDING_RESULTS_NAME = "finding-results.jsonl"
REMEDIATION_RESULTS_NAME = "remediation-results.jsonl"
RULE_METRICS_NAME = "rule-metrics.jsonl"
CATEGORY_METRICS_NAME = "category-metrics.jsonl"
DIFFICULTY_METRICS_NAME = "difficulty-metrics.jsonl"
EVALUATION_REPORT_NAME = "evaluation-report.md"


def _fmt(metric: dict[str, Any] | None) -> str:
    """Render one metric with its counts, or an explicit ``n/a`` when undefined."""
    if metric is None:
        return "n/a"
    value = metric.get("value")
    denominator = metric.get("denominator")
    if value is None:
        return "n/a (0 denominator)" if denominator == 0 else "n/a"
    return f"{value:.4f} ({metric.get('numerator')}/{denominator})"


def _metric_row(name: str, block: dict[str, Any]) -> str:
    metrics = block["metrics"]
    counts = block["counts"]
    return (
        f"| {name} | {counts['tp']} | {counts['fp']} | {counts['fn']} | {counts['tn']} | "
        f"{_fmt(metrics['precision'])} | {_fmt(metrics['recall'])} | "
        f"{_fmt(metrics['specificity'])} | {_fmt(metrics['f1'])} |"
    )


_TABLE_HEADER = (
    "| group | TP | FP | FN | TN | precision | recall | specificity | F1 |\n"
    "| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |"
)


def _weakest(blocks: dict[str, dict[str, Any]], limit: int = 5) -> list[tuple[str, float, int]]:
    """Return the groups with the lowest defined F1, worst first.

    Groups where F1 is undefined are omitted rather than sorted to the bottom:
    "not measurable" is not "bad". Ties break on the group name so the list is
    deterministic.
    """
    scored = [
        (name, block["metrics"]["f1"]["value"], block["counts"]["positives"])
        for name, block in blocks.items()
        if block["metrics"]["f1"]["value"] is not None
    ]
    scored.sort(key=lambda row: (row[1], row[0]))
    return scored[:limit]


def render_report(result: EvaluationResult) -> str:
    """Render the deterministic human-readable Markdown report."""
    summary = result.summary
    findings = summary["findings"]
    micro = findings["overall_micro"]
    macro = findings["overall_macro_by_rule"]
    counts = micro["counts"]
    remediation = summary["remediation"]
    benchmark = summary["benchmark"]
    submission = summary["submission"]
    universe = summary["universe"]

    lines = [
        "# Benchmark evaluation report",
        "",
        f"- Evaluator version: {EVALUATOR_VERSION} (schema {EVALUATION_SCHEMA_VERSION})",
        f"- Benchmark profile: {benchmark['profile']} "
        f"(truth seed {benchmark['truth_seed']}, defect seed {benchmark['defect_seed']})",
        f"- Ground-truth fingerprint: `{benchmark['ground_truth_fingerprint']}`",
        f"- Prediction SHA-256: `{submission['prediction_sha256']}`",
        f"- Predictions submitted: {submission['predictions']} "
        f"({submission['rule_level_predictions']} rule-level, "
        f"{submission['unnamed_rule_predictions']} without a rule id)",
        "",
        "## Scorecard",
        "",
        "Five dimensions, reported separately and unweighted — no composite score.",
        "",
        "| dimension | metric | value |",
        "| --- | --- | --- |",
    ]
    for name, block in summary["dimensions"].items():
        lines.append(f"| {name} | {block['metric']} | {_fmt(block)} |")

    lines.extend(
        [
            "",
            "## Confusion matrix",
            "",
            f"Evaluation universe: {universe['evaluated_pairs']} in-scope pairs across "
            f"{universe['rules']} rules "
            f"({universe['positive_pairs']} positive, {universe['negative_pairs']} negative, "
            f"of which {universe['reserved_control_pairs']} reserved-control pairs).",
            "",
            "| | predicted finding | predicted clean/abstain/absent |",
            "| --- | ---: | ---: |",
            f"| **expected present** | TP {counts['tp']} | FN {counts['fn']} |",
            f"| **expected clean** | FP {counts['fp']} | TN {counts['tn']} |",
            "",
            "## Finding metrics",
            "",
            _TABLE_HEADER,
            _metric_row("overall (micro)", micro),
            _metric_row("reserved controls", summary["reserved_controls"]),
            "",
            "Macro (unweighted mean over rules with a defined value):",
            "",
        ]
    )
    for metric_name in ("precision", "recall", "specificity", "f1"):
        entry = macro[metric_name]
        rendered = "n/a" if entry["value"] is None else f"{entry['value']:.4f}"
        lines.append(
            f"- {metric_name}: {rendered} "
            f"(over {entry['group_count']}/{entry['total_groups']} rules)"
        )

    lines.extend(["", "### By category", "", _TABLE_HEADER])
    for name in sorted(findings["by_category"]):
        lines.append(_metric_row(name, findings["by_category"][name]))
    lines.extend(
        [
            "",
            "### By difficulty",
            "",
            "Difficulty is *detection* complexity — how much evidence a detector must "
            "relate before it can decide — derived from each rule's reasoning scope. "
            "It is independent of severity, of the maturity profile, and of how hard "
            "the defect is to fix. Every scored pair belongs to exactly one tier, so "
            "these rows partition the confusion matrix above.",
            "",
            _TABLE_HEADER,
        ]
    )
    # ``by_difficulty`` is already built in tier order (bronze, silver, gold,
    # then any defensive bucket), so iterate it rather than re-deriving an order
    # that could drift from the one the summary published.
    for name, block in findings["by_difficulty"].items():
        lines.append(_metric_row(name, block))
    lines.extend(
        [
            "",
            "Per tier: reserved-control false positives, and remediation quality on the "
            "findings that tier's rules produced.",
            "",
            "| tier | rules | reserved-control FPs | reserved-control FP rate | "
            "remediation coverage | remediation correctness | end-to-end | unsafe |",
            "| --- | ---: | ---: | --- | --- | --- | --- | ---: |",
        ]
    )
    rules_by_difficulty = universe["rules_by_difficulty"]
    for name, block in findings["by_difficulty"].items():
        reserved_block = block["reserved_controls"]
        rem = block["remediation"]
        lines.append(
            f"| {name} | {rules_by_difficulty.get(name, 0)} | "
            f"{reserved_block['false_positives']} | "
            f"{_fmt(reserved_block['false_positive_rate'])} | "
            f"{_fmt(rem['coverage'])} | {_fmt(rem['correctness_given_true_positive'])} | "
            f"{_fmt(rem['end_to_end'])} | {rem['unsafe_actions']} |"
        )

    lines.extend(["", "### By entity class", "", _TABLE_HEADER])
    for name in sorted(findings["by_entity_class"]):
        lines.append(_metric_row(name, findings["by_entity_class"][name]))
    lines.extend(["", "### By severity", "", _TABLE_HEADER])
    for name in sorted(findings["by_severity"]):
        lines.append(_metric_row(name, findings["by_severity"][name]))

    lines.extend(["", "### Weakest rules (lowest defined F1)", ""])
    weakest = _weakest(findings["by_rule"])
    if weakest:
        for name, value, positives in weakest:
            lines.append(f"- {name}: F1 {value:.4f} over {positives} expected finding(s)")
    else:
        lines.append("- no rule has a defined F1 for this submission")

    remediation_counts = remediation["counts"]
    remediation_metrics = remediation["metrics"]
    lines.extend(
        [
            "",
            "## Remediation metrics",
            "",
            f"- Expected remediations: {remediation_counts['expected_remediations']}",
            f"- Findings detected: {remediation_counts['detected_findings']}",
            f"- Remediations submitted: {remediation_counts['submitted']} "
            f"(missing on {remediation_counts['missing']} detected findings)",
            f"- Fully correct: {remediation_counts['fully_correct']}",
            f"- Coverage: {_fmt(remediation_metrics['coverage'])}",
            "- Correctness given a true-positive finding: "
            f"{_fmt(remediation_metrics['correctness_given_true_positive'])}",
            f"- End-to-end (finding + remediation): {_fmt(remediation_metrics['end_to_end'])}",
            f"- Action class correct: {_fmt(remediation_metrics['action_class_correct'])}",
            f"- Availability correct: {_fmt(remediation_metrics['availability_correct'])}",
            f"- Approval policy correct: {_fmt(remediation_metrics['approval_policy_correct'])}",
            f"- Approver role correct: {_fmt(remediation_metrics['approver_role_correct'])}",
            "- Recommended value correct: "
            f"{_fmt(remediation_metrics['recommended_value_correct'])}",
            "- Explicit no-remediation decisions correct (of those detected): "
            f"{_fmt(remediation_metrics['non_remediation_correct'])}",
            "- Explicit no-remediation decisions correct (of all "
            f"{remediation_counts['non_remediable_expected']} non-remediable findings): "
            f"{_fmt(remediation_metrics['non_remediation_end_to_end'])}",
            f"- **Unsafe actions on clean entities: {remediation_counts['unsafe_actions']}** "
            f"({remediation_counts['unsafe_on_reserved_control']} on reserved controls)",
            "",
            "## Reserved controls",
            "",
            "Reserved controls were held out before selection, so no rule could ever "
            "have drawn them; every flag against one is a false positive.",
            "",
            f"- Reserved-control pairs: {summary['reserved_controls']['counts']['total']}",
            f"- False positives on reserved controls: "
            f"{summary['reserved_controls']['false_positives']}",
            f"- Specificity on reserved controls: "
            f"{_fmt(summary['reserved_controls']['metrics']['specificity'])}",
            "",
            "## Out-of-scope, abstention and coverage",
            "",
            "- Out-of-scope false positives: "
            f"{summary['out_of_scope']['false_positives']} "
            "(excluded from every denominator; counted strictly below)",
            f"- Strict false positives (in-matrix + out-of-scope): "
            f"{summary['out_of_scope']['strict_false_positives']}",
            f"- Abstained pairs: {summary['abstention']['abstained_pairs']} "
            f"({summary['abstention']['on_positive_pairs']} on positive pairs, "
            f"{summary['abstention']['on_negative_pairs']} on negative pairs)",
            f"- Abstention rate: {_fmt(summary['abstention']['abstention_rate'])}",
            "- Selective F1 (abstained pairs removed): "
            f"{_fmt(summary['abstention']['selective']['metrics']['f1'])}",
            f"- Explicit clean predictions scored as true negatives: "
            f"{universe['explicit_clean_true_negatives']}",
            "",
            "## Credit without a rule id",
            "",
            "Predictions that name no rule cannot occupy a pair; they are scored in "
            "coarser universes derived from the same rule scopes.",
            "",
            _TABLE_HEADER,
            _metric_row("entity level", findings["coarse_universes"]["entity_level"]),
            _metric_row("category level", findings["coarse_universes"]["category_level"]),
            "",
            "## Submission integrity",
            "",
            "Malformed, duplicate, unknown-id and contradictory predictions are rejected "
            "before evaluation begins, so a scored submission contains none of them.",
            "",
        ]
    )
    return "\n".join(lines)


def evaluation_bytes(result: EvaluationResult) -> dict[str, bytes]:
    """Return the canonical bytes of every output file, keyed by filename."""
    return {
        EVALUATION_SUMMARY_NAME: serialize.manifest_bytes(result.summary),
        FINDING_RESULTS_NAME: serialize.jsonl_bytes(result.finding_results),
        REMEDIATION_RESULTS_NAME: serialize.jsonl_bytes(result.remediation_results),
        RULE_METRICS_NAME: serialize.jsonl_bytes(result.rule_metrics),
        CATEGORY_METRICS_NAME: serialize.jsonl_bytes(result.category_metrics),
        DIFFICULTY_METRICS_NAME: serialize.jsonl_bytes(result.difficulty_metrics),
    }


def write_evaluation(result: EvaluationResult, output_dir: Path | str) -> dict[str, Any]:
    """Write every report atomically into ``output_dir``; return the summary."""
    output_dir = Path(output_dir)
    benchmark = result.summary["benchmark"]
    provenance = provenance_bytes(
        layer="evaluation",
        generator_version=EVALUATOR_VERSION,
        schema_version=EVALUATION_SCHEMA_VERSION,
        scenario={
            "profile": benchmark["profile"],
            "defect_seed": benchmark["defect_seed"],
            "truth_seed": benchmark["truth_seed"],
            "ground_truth_fingerprint": benchmark["ground_truth_fingerprint"],
            "prediction_sha256": result.summary["submission"]["prediction_sha256"],
        },
    )
    files = {**evaluation_bytes(result), PROVENANCE_NAME: provenance}
    report = render_report(result)

    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{output_dir.name}.tmp-{os.getpid()}"
    backup = parent / f".{output_dir.name}.bak-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)

    try:
        tmp.mkdir(parents=True)
        for name, data in files.items():
            serialize.write_bytes(tmp / name, data)
        serialize.write_text(tmp / EVALUATION_REPORT_NAME, report)

        had_existing = output_dir.exists()
        if had_existing:
            os.replace(output_dir, backup)
        try:
            os.replace(tmp, output_dir)
        except OSError:
            if had_existing:  # pragma: no cover - best-effort restore
                os.replace(backup, output_dir)
            raise
        if had_existing:
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return result.summary


__all__ = [
    "EVALUATION_SUMMARY_NAME",
    "FINDING_RESULTS_NAME",
    "REMEDIATION_RESULTS_NAME",
    "RULE_METRICS_NAME",
    "CATEGORY_METRICS_NAME",
    "DIFFICULTY_METRICS_NAME",
    "EVALUATION_REPORT_NAME",
    "render_report",
    "evaluation_bytes",
    "write_evaluation",
]
