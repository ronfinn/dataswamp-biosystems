#!/usr/bin/env python
"""Regenerate the committed example prediction submissions under ``examples/``.

The examples must reference entity and rule identifiers that actually exist in
the canonical benchmark, so they are *derived* from the canonical ground truth
rather than hand-written — a hand-written example silently rots the moment a
rule or an identifier changes.

Deriving them from ground truth is a convenience for the maintainer, not a
capability an agent under test has: every emitted field is one a submitting
agent supplies itself (``entity_id``, ``rule_id``, ``status`` and the public
remediation fields), and nothing privileged — defect instance ids, mutation
ids, truth ``before`` values — is ever written into an example.

Usage::

    uv run --frozen python scripts/update_example_predictions.py --confirm

The generated files are committed. ``tests/test_examples.py`` re-derives them
and fails if the committed copies have drifted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dataswamp_biosystems.canonical import (  # noqa: E402
    OBSERVED_DIRNAME,
    generate_canonical_from_config_dir,
)
from dataswamp_biosystems.evaluation import GroundTruth, load_ground_truth  # noqa: E402

EXAMPLES_DIR = REPO_ROOT / "examples" / "predictions"

# Deliberately small. These are read by humans first and executed second, so a
# handful of representative rows beats a faithful dump of all 177 findings.
SAMPLE_FINDINGS = 8
SAMPLE_CONTROLS = 4


def _row(**fields: object) -> dict[str, object]:
    return {"schema_version": 1, **fields}


def _sample_findings(truth: GroundTruth) -> list:
    """Return a stable, rule-diverse sample of expected findings.

    One finding per rule, in rule order, so the sample exercises several
    categories and remediation shapes rather than several instances of one rule.
    """
    seen: set[str] = set()
    chosen = []
    for finding in truth.findings:
        if finding.rule_id in seen:
            continue
        seen.add(finding.rule_id)
        chosen.append(finding)
        if len(chosen) == SAMPLE_FINDINGS:
            break
    return chosen


def _sample_controls(truth: GroundTruth, rule_id: str) -> list[str]:
    """Return control entities that are genuinely inside ``rule_id``'s population."""
    population = truth.population(rule_id)
    control_ids = {control.id for control in truth.controls}
    return sorted(population & control_ids)[:SAMPLE_CONTROLS]


def _remediation(expected) -> dict[str, object]:
    return {
        "action_class": expected.action_class,
        "availability": expected.availability.value,
        "approval_policy": expected.approval_policy.value,
        "approver_role": expected.approver_role.value,
        "recommended_value": expected.recommended_value,
    }


def build_perfect(truth: GroundTruth) -> list[dict[str, object]]:
    """Every expected finding detected, with the expected remediation.

    Complete rather than sampled: this is the reference upper bound, so it must
    actually score recall 1.0. It is machine-generated and long; ``partial`` and
    ``unsafe`` are the short files meant to be read.
    """
    remediations = truth.remediation_by_finding
    return [
        _row(
            prediction_id=f"perfect-{index:04d}",
            entity_id=finding.entity_id,
            rule_id=finding.rule_id,
            status="finding",
            category=finding.category.value,
            severity=finding.severity.value,
            confidence=0.95,
            evidence=finding.observable_evidence,
            remediation=_remediation(remediations[finding.id]),
        )
        for index, finding in enumerate(truth.findings, start=1)
    ]


def build_partial(truth: GroundTruth) -> list[dict[str, object]]:
    """A realistic mixed submission: some hits, some misses, some restraint."""
    remediations = truth.remediation_by_finding
    findings = _sample_findings(truth)
    rows: list[dict[str, object]] = []

    # Detected, with a correct remediation.
    for index, finding in enumerate(findings[:3], start=1):
        rows.append(
            _row(
                prediction_id=f"partial-hit-{index:02d}",
                entity_id=finding.entity_id,
                rule_id=finding.rule_id,
                status="finding",
                category=finding.category.value,
                severity=finding.severity.value,
                confidence=0.8,
                evidence=finding.observable_evidence,
                remediation=_remediation(remediations[finding.id]),
            )
        )

    # Detected, but no remediation proposed: a true positive whose remediation
    # is scored as missing rather than wrong.
    detected_only = findings[3]
    rows.append(
        _row(
            prediction_id="partial-hit-04",
            entity_id=detected_only.entity_id,
            rule_id=detected_only.rule_id,
            status="finding",
            confidence=0.55,
            evidence="looks wrong; unsure how to fix",
        )
    )

    # Explicit restraint on genuinely clean entities: the only way to earn an
    # explicit true negative.
    for index, entity_id in enumerate(_sample_controls(truth, findings[0].rule_id), start=1):
        rows.append(
            _row(
                prediction_id=f"partial-clean-{index:02d}",
                entity_id=entity_id,
                rule_id=findings[0].rule_id,
                status="clean",
                confidence=0.7,
                evidence="checked; the rule's required metadata is present",
            )
        )

    # An honest abstention: recorded and reported, never folded into the matrix.
    abstained = findings[5]
    rows.append(
        _row(
            prediction_id="partial-abstain-01",
            entity_id=abstained.entity_id,
            rule_id=abstained.rule_id,
            status="abstain",
            evidence="insufficient evidence in the observed graph to decide",
        )
    )

    # findings[4], [6] and [7] are simply absent: silence is a false negative.
    return rows


def build_unsafe(truth: GroundTruth) -> list[dict[str, object]]:
    """An over-confident submission that a benchmark must penalise."""
    findings = _sample_findings(truth)
    remediations = truth.remediation_by_finding
    rule_id = findings[0].rule_id
    rows: list[dict[str, object]] = []

    # Flag clean entities: false positives against the control partition.
    for index, entity_id in enumerate(_sample_controls(truth, rule_id), start=1):
        rows.append(
            _row(
                prediction_id=f"unsafe-fp-{index:02d}",
                entity_id=entity_id,
                rule_id=rule_id,
                status="finding",
                confidence=1.0,
                evidence="flagged without checking",
                remediation={
                    "action_class": "restore_field",
                    "availability": "automatic",
                    "approval_policy": "not-required",
                    "approver_role": "none",
                    "recommended_value": "restore-from-truth",
                },
            )
        )

    # A real finding detected, then paired with an unapproved automatic fix
    # where the contract requires a human decision.
    real = findings[0]
    expected = remediations[real.id]
    rows.append(
        _row(
            prediction_id="unsafe-remediation-01",
            entity_id=real.entity_id,
            rule_id=real.rule_id,
            status="finding",
            category=real.category.value,
            severity=real.severity.value,
            confidence=1.0,
            evidence=real.observable_evidence,
            remediation={
                "action_class": expected.action_class,
                "availability": "automatic",
                "approval_policy": "not-required",
                "approver_role": "none",
                "recommended_value": expected.recommended_value,
            },
        )
    )

    # A real finding asserted clean: a confidently wrong negative.
    missed = findings[1]
    rows.append(
        _row(
            prediction_id="unsafe-fn-01",
            entity_id=missed.entity_id,
            rule_id=missed.rule_id,
            status="clean",
            confidence=1.0,
            evidence="assumed fine",
        )
    )
    return rows


BUILDERS = {
    "perfect.jsonl": build_perfect,
    "partial.jsonl": build_partial,
    "unsafe.jsonl": build_unsafe,
}


def render(rows: list[dict[str, object]]) -> str:
    """Render rows as JSONL with stable key order — one readable line each."""
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def build_all(observed_dir: Path) -> dict[str, str]:
    """Return ``{filename: JSONL text}`` for every example submission."""
    truth = load_ground_truth(observed_dir)
    return {name: render(builder(truth)) for name, builder in BUILDERS.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Rewrites the committed example submissions in place.",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("refusing to rewrite the examples without --confirm")

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "generated"
        generate_canonical_from_config_dir(root, REPO_ROOT / "config")
        rendered = build_all(root / OBSERVED_DIRNAME)

    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (EXAMPLES_DIR / name).write_text(text, encoding="utf-8")
        print(f"wrote {EXAMPLES_DIR / name} ({len(text.splitlines())} predictions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
