"""Write an :class:`ObservedResult` to the canonical ``generated/observed/`` layout.

Output is staged in a temporary sibling directory and swapped into place with
directory renames (mirroring :mod:`dataswamp_biosystems.truth.writer`), so a
failing run never leaves a partial directory and any previous output is restored
on failure. Every byte goes through the shared canonical serializer.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from dataswamp_biosystems.observed.engine import ObservedResult
from dataswamp_biosystems.truth import serialize

OBSERVED_GRAPH_NAME = "observed-graph.json"
INJECTED_DEFECTS_NAME = "injected-defects.jsonl"
EXPECTED_FINDINGS_NAME = "expected-findings.jsonl"
EXPECTED_REMEDIATIONS_NAME = "expected-remediations.jsonl"
MUTATION_LOG_NAME = "mutation-log.jsonl"
PROFILE_SUMMARY_NAME = "profile-summary.json"
SUMMARY_MD_NAME = "summary.md"
TRUTH_INPUTS_NAME = "truth-inputs.json"


def observed_bytes(result: ObservedResult) -> dict[str, bytes]:
    """Return the canonical bytes of every output file, keyed by filename.

    Computed without touching the filesystem, so callers can compare against
    on-disk files or verify determinism in memory.
    """
    return {
        OBSERVED_GRAPH_NAME: serialize.manifest_bytes(result.observed_graph),
        INJECTED_DEFECTS_NAME: serialize.jsonl_bytes(result.instances),
        EXPECTED_FINDINGS_NAME: serialize.jsonl_bytes(result.findings),
        EXPECTED_REMEDIATIONS_NAME: serialize.jsonl_bytes(result.remediations),
        MUTATION_LOG_NAME: serialize.jsonl_bytes(result.mutations),
        PROFILE_SUMMARY_NAME: serialize.manifest_bytes(result.summary),
    }


def _render_summary_md(result: ObservedResult) -> str:
    meta = result.summary["meta"]
    totals = result.summary["totals"]
    lines = [
        "# Observed-state summary",
        "",
        f"- Generator version: {meta['generator_version']}",
        f"- Profile: {meta['profile']}",
        f"- Defect seed: {meta['defect_seed']}",
        f"- Truth generator version: {meta['truth_generator_version']} (seed {meta['truth_seed']})",
        f"- Epoch anchor: {meta['epoch_anchor']}",
        "",
        "## Totals",
        "",
        f"- Defects injected: {totals['defects']}",
        f"- Rules fired: {totals['rules_fired']} / {totals['rules_defined']}",
        f"- Assets: {totals['assets']} "
        f"({totals['control_assets']} control, {totals['affected_assets']} affected, "
        f"{totals['clean_assets']} clean)",
        "",
        "## Defects by category",
        "",
    ]
    for category, count in result.summary["by_category"].items():
        lines.append(f"- {category}: {count}")
    lines.extend(["", "## Defects by severity", ""])
    for severity, count in result.summary["by_severity"].items():
        lines.append(f"- {severity}: {count}")
    lines.extend(["", "## Defects by modality group", ""])
    for group, count in result.summary["by_modality_group"].items():
        lines.append(f"- {group}: {count}")
    lines.extend(["", "## Defects by rule", ""])
    for rule_id, count in result.summary["by_rule"].items():
        lines.append(f"- {rule_id}: {count}")
    lines.append("")
    return "\n".join(lines)


def write_observed(
    result: ObservedResult,
    output_dir: Path | str,
    extra_files: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Write all outputs atomically into ``output_dir``; return the summary.

    ``extra_files`` (e.g. the truth-input checksum manifest) are written into the
    same staged directory so the whole bundle is swapped into place atomically.
    """
    output_dir = Path(output_dir)
    files = {**observed_bytes(result), **(extra_files or {})}
    summary_md = _render_summary_md(result)

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
        serialize.write_text(tmp / SUMMARY_MD_NAME, summary_md)

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
    "OBSERVED_GRAPH_NAME",
    "INJECTED_DEFECTS_NAME",
    "EXPECTED_FINDINGS_NAME",
    "EXPECTED_REMEDIATIONS_NAME",
    "MUTATION_LOG_NAME",
    "PROFILE_SUMMARY_NAME",
    "SUMMARY_MD_NAME",
    "TRUTH_INPUTS_NAME",
    "observed_bytes",
    "write_observed",
]
