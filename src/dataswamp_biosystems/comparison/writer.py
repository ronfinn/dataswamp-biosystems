"""Write a :class:`ComparisonResult` to the canonical comparison layout.

Staged in a temporary sibling directory and swapped into place with directory
renames, exactly like the truth, observed and evaluation writers, so a failing
run never leaves a partial directory. Every byte goes through the shared
canonical serializer and nothing carries a wall-clock value — identical inputs
produce byte-identical output.

Neither input evaluation directory is opened for writing at any point; the
comparison layer is read-only with respect to everything it consumes.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from dataswamp_biosystems.comparison.engine import (
    COMPARATOR_VERSION,
    COMPARISON_SCHEMA_VERSION,
    ComparisonResult,
)
from dataswamp_biosystems.provenance import PROVENANCE_NAME, provenance_bytes
from dataswamp_biosystems.truth import serialize

COMPARISON_SUMMARY_NAME = "comparison-summary.json"
METRIC_DELTAS_NAME = "metric-deltas.json"
PAIR_TRANSITIONS_NAME = "pair-transitions.jsonl"
RULE_REGRESSIONS_NAME = "rule-regressions.jsonl"
CONTROL_REGRESSIONS_NAME = "control-regressions.jsonl"
REMEDIATION_REGRESSIONS_NAME = "remediation-regressions.jsonl"
COMPARISON_REPORT_NAME = "comparison-report.md"

_ARROWS = {
    "improved": "improved",
    "regressed": "**regressed**",
    "unchanged": "unchanged",
    "undefined": "n/a",
}


def _value(side: dict[str, Any] | None) -> str:
    """Render one side of a metric delta, undefined values stated as such."""
    if side is None:
        return "n/a"
    value = side.get("value")
    if value is None:
        return "n/a (0 denominator)" if side.get("denominator") == 0 else "n/a"
    return f"{value:.4f} ({side.get('numerator')}/{side.get('denominator')})"


def _delta(delta: dict[str, Any]) -> str:
    """Render a metric delta as a signed number, or ``n/a`` when undefined."""
    raw = delta.get("delta")
    if raw is None:
        return "n/a"
    return f"{raw:+.4f}"


def _metric_row(name: str, delta: dict[str, Any]) -> str:
    return (
        f"| {name} | {_value(delta['baseline'])} | {_value(delta['candidate'])} | "
        f"{_delta(delta)} | {_ARROWS[delta['direction']]} |"
    )


def _count_row(name: str, delta: dict[str, Any]) -> str:
    return (
        f"| {name} | {delta['baseline']} | {delta['candidate']} | "
        f"{delta['delta']:+d} | {_ARROWS[delta['direction']]} |"
    )


_METRIC_HEADER = (
    "| metric | baseline | candidate | delta | direction |\n| --- | --- | --- | ---: | --- |"
)
_COUNT_HEADER = (
    "| count | baseline | candidate | delta | direction |\n| --- | ---: | ---: | ---: | --- |"
)


def _block_rows(block: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    return [_metric_row(name, block["metrics"][name]) for name in names]


def render_report(result: ComparisonResult) -> str:
    """Render the deterministic human-readable Markdown comparison report."""
    summary = result.summary
    headline = summary["headline"]
    identity = summary["benchmark"]
    controls = summary["control_preservation"]
    runs = summary["runs"]

    lines = [
        "# Benchmark run comparison",
        "",
        f"- Comparator version: {COMPARATOR_VERSION} "
        f"(comparison schema {COMPARISON_SCHEMA_VERSION})",
        f"- Benchmark profile: {identity['profile']} "
        f"(truth seed {identity['truth_seed']}, defect seed {identity['defect_seed']})",
        f"- Ground-truth fingerprint: `{identity['ground_truth_fingerprint']}`",
        f"- Evaluator: {identity['evaluator_version']} "
        f"(evaluation schema {identity['evaluation_schema_version']})",
        f"- Baseline submission: `{runs['baseline']['prediction_sha256']}` "
        f"({runs['baseline']['predictions']} prediction(s))",
        f"- Candidate submission: `{runs['candidate']['prediction_sha256']}` "
        f"({runs['candidate']['predictions']} prediction(s))",
        "",
        "Both runs scored the same ground truth: every identity field matched, so the "
        "deltas below difference like for like.",
        "",
        "## Headline",
        "",
        f"- Pairs that changed outcome: {headline['pairs_changed']}",
        f"- Newly solved (a missed defect is now detected): {headline['newly_solved']}",
        f"- **Newly broken (a detected defect is now missed): {headline['newly_broken']}**",
        f"- **New control false positives: {headline['new_control_false_positives']}** "
        f"(of which {headline['new_reserved_control_false_positives']} on reserved controls)",
        f"- Resolved control false positives: {headline['resolved_control_false_positives']}",
        f"- Rules regressed: {headline['rules_regressed']}; improved: {headline['rules_improved']}",
        f"- Remediation decisions changed: {headline['remediations_changed']} "
        f"({headline['remediations_regressed']} regressed)",
        "",
        summary["verdict_note"],
        "",
        "## Scorecard dimensions",
        "",
        "The evaluator's five dimensions, differenced separately and unweighted — "
        "there is no composite score here either.",
        "",
        _METRIC_HEADER,
    ]
    for name in sorted(summary["dimensions"]):
        lines.append(_metric_row(name, summary["dimensions"][name]))

    lines.extend(
        [
            "",
            "## Control preservation",
            "",
            "Reported first among the detail sections, and deliberately: a candidate "
            "that buys recall by flagging clean entities must not be able to hide it "
            "behind an improved F1. Reserved controls could never have carried a "
            "defect, so every flag against one is a false positive by construction.",
            "",
            _COUNT_HEADER,
            _count_row("false positives (in matrix)", controls["false_positives"]),
            _count_row(
                "reserved-control false positives",
                controls["reserved_control_false_positives"],
            ),
            "",
            _METRIC_HEADER,
            _metric_row("specificity", controls["specificity"]),
            _metric_row("reserved-control specificity", controls["reserved_control_specificity"]),
            "",
            f"- Newly introduced control false positives: "
            f"{controls['new_control_false_positives']}",
            f"- Resolved control false positives: {controls['resolved_control_false_positives']}",
            f"- **New reserved-control false positives: "
            f"{controls['new_reserved_control_false_positives']}**",
            f"- Resolved reserved-control false positives: "
            f"{controls['resolved_reserved_control_false_positives']}",
            f"- Unsafe remediations attached to new control false positives: "
            f"{controls['unsafe_remediations_on_new_control_false_positives']}",
            "",
            "## Overall (micro)",
            "",
            _COUNT_HEADER,
        ]
    )
    for cell in ("tp", "fp", "fn", "tn"):
        lines.append(_count_row(cell.upper(), summary["overall_micro"]["counts"][cell]))
    lines.extend(["", _METRIC_HEADER])
    lines.extend(
        _block_rows(summary["overall_micro"], ("precision", "recall", "specificity", "f1"))
    )

    lines.extend(
        [
            "",
            "## By difficulty",
            "",
            "Each tier is differenced independently. A tier neither run measured is "
            "absent rather than invented, and an undefined metric on either side "
            "leaves the delta undefined.",
            "",
        ]
    )
    for tier in sorted(summary["by_difficulty"]):
        block = summary["by_difficulty"][tier]
        lines.extend([f"### {tier}", "", _METRIC_HEADER])
        lines.extend(_block_rows(block, ("precision", "recall", "specificity", "f1")))
        lines.append("")
    if not summary["by_difficulty"]:
        lines.append("Neither run published a difficulty breakdown.\n")

    adversarial = summary["adversarial"]
    lines.extend(["## Adversarial scenarios", ""])
    if not adversarial["declared_scenarios"]:
        lines.append(
            "Neither run declares adversarial scenarios, so the adversarial tier is "
            "empty rather than passed."
        )
    else:
        near = adversarial["near_miss_controls"]
        lines.extend(
            [
                f"{adversarial['declared_scenarios']} scenario(s) over "
                f"{adversarial['scenario_pairs']} scored pairs.",
                "",
                adversarial["attribution_note"],
                "",
                _COUNT_HEADER,
                _count_row("adversarial true positives", adversarial["net_newly_solved"]),
                _count_row("adversarial false negatives", adversarial["net_missed"]),
                _count_row("near-miss false positives", near["false_positives"]),
                _count_row("near-miss unsafe remediations", near["unsafe_remediations"]),
                "",
                _METRIC_HEADER,
                _metric_row("near-miss false-positive rate", near["false_positive_rate"]),
            ]
        )
    lines.append("")

    remediation = summary["remediation"]
    lines.extend(
        [
            "## Remediation",
            "",
            _COUNT_HEADER,
        ]
    )
    for name in sorted(remediation["counts"]):
        lines.append(_count_row(name, remediation["counts"][name]))
    lines.extend(["", _METRIC_HEADER])
    for name in sorted(remediation["metrics"]):
        lines.append(_metric_row(name, remediation["metrics"][name]))

    lines.extend(
        [
            "",
            "## Ranked rule regressions",
            "",
            "Ranked by pairs that got worse — defects newly missed plus clean entities "
            "newly flagged, with reserved-control false positives weighted above "
            "ordinary ones. Ties break on the rule id, so the order is total and "
            "reproducible.",
            "",
        ]
    )
    ranked = summary["ranked_regressions"]
    if ranked:
        lines.extend(
            [
                "| rank | rule | newly broken | new FPs | new reserved-control FPs |",
                "| ---: | --- | ---: | ---: | ---: |",
            ]
        )
        for row in ranked:
            lines.append(
                f"| {row['rank']} | {row['rule_id']} | {row['newly_broken']} | "
                f"{row['new_false_positives']} | "
                f"{row['new_reserved_control_false_positives']} |"
            )
    else:
        lines.append("No rule regressed.")

    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- `{COMPARISON_SUMMARY_NAME}` — the whole comparison, machine-readable",
            f"- `{METRIC_DELTAS_NAME}` — every metric delta, including the breakdowns "
            "not rendered above",
            f"- `{PAIR_TRANSITIONS_NAME}` — every `(entity, rule)` pair whose outcome moved",
            f"- `{RULE_REGRESSIONS_NAME}` — per-rule change with an explicit `rank`",
            f"- `{CONTROL_REGRESSIONS_NAME}` — control false positives gained and lost",
            f"- `{REMEDIATION_REGRESSIONS_NAME}` — remediation decisions that changed",
            "",
        ]
    )
    return "\n".join(lines)


def comparison_bytes(result: ComparisonResult) -> dict[str, bytes]:
    """Return the canonical bytes of every output file, keyed by filename."""
    return {
        COMPARISON_SUMMARY_NAME: serialize.manifest_bytes(result.summary),
        METRIC_DELTAS_NAME: serialize.manifest_bytes(result.metric_deltas),
        PAIR_TRANSITIONS_NAME: serialize.jsonl_bytes(result.pair_transitions),
        RULE_REGRESSIONS_NAME: serialize.jsonl_bytes(result.rule_regressions),
        CONTROL_REGRESSIONS_NAME: serialize.jsonl_bytes(result.control_regressions),
        REMEDIATION_REGRESSIONS_NAME: serialize.jsonl_bytes(result.remediation_regressions),
    }


def write_comparison(result: ComparisonResult, output_dir: Path | str) -> dict[str, Any]:
    """Write every comparison file atomically into ``output_dir``; return the summary."""
    output_dir = Path(output_dir)
    identity = result.summary["benchmark"]
    provenance = provenance_bytes(
        layer="comparison",
        generator_version=COMPARATOR_VERSION,
        schema_version=COMPARISON_SCHEMA_VERSION,
        scenario={
            "profile": identity["profile"],
            "defect_seed": identity["defect_seed"],
            "truth_seed": identity["truth_seed"],
            "ground_truth_fingerprint": identity["ground_truth_fingerprint"],
            "baseline_prediction_sha256": result.summary["runs"]["baseline"]["prediction_sha256"],
            "candidate_prediction_sha256": result.summary["runs"]["candidate"]["prediction_sha256"],
        },
    )
    files = {**comparison_bytes(result), PROVENANCE_NAME: provenance}
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
        serialize.write_text(tmp / COMPARISON_REPORT_NAME, report)

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
    "COMPARISON_SUMMARY_NAME",
    "METRIC_DELTAS_NAME",
    "PAIR_TRANSITIONS_NAME",
    "RULE_REGRESSIONS_NAME",
    "CONTROL_REGRESSIONS_NAME",
    "REMEDIATION_REGRESSIONS_NAME",
    "COMPARISON_REPORT_NAME",
    "render_report",
    "comparison_bytes",
    "write_comparison",
]
