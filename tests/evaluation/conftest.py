"""Fixtures for the evaluation tests.

Two ground truths are used, deliberately.

The **tiny** ground truth below is written by hand: four rules, seven entities
and eleven in-scope pairs, small enough that every confusion-matrix cell can be
counted on paper and asserted exactly. It exercises all four remediation
contract states (automatic/no-approval, automatic/approval, manual/no-approval
and non-remediable), a reserved control, an eligible-unselected control, and an
entity that is in no rule's population at all.

The **real** ground truth is the canonical scenario's observed state, generated
once per session. It is what proves the engine behaves on the actual benchmark:
a perfect agent scores 1.0, an empty submission scores 0 recall and full
specificity, and an agent flagging everything scores full recall and near-zero
specificity.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dataswamp_biosystems.observed.entities import (
    NO_REMEDIATION_ACTION,
    ApprovalEvidence,
    ApprovalPolicy,
    ApproverRole,
    Category,
    ControlReason,
    ControlRecord,
    ExpectedFinding,
    ExpectedRemediation,
    NonRemediableReason,
    RemediationAvailability,
    RuleScopeRecord,
    Severity,
)
from dataswamp_biosystems.observed.writer import (
    CONTROLS_NAME,
    EXPECTED_FINDINGS_NAME,
    EXPECTED_REMEDIATIONS_NAME,
    PROFILE_SUMMARY_NAME,
    RULE_SCOPE_NAME,
)
from dataswamp_biosystems.truth import (
    serialize,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG_DIR = REPO_ROOT / "config"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

CANONICAL_SEED = 20260717

TINY_PROFILE = "tiny-eval"
TINY_SEED = 7

# -- the tiny ground truth ----------------------------------------------------

RULE_AUTO = "TINY-AUTO"  # automatic remediation, no approval
RULE_APPROVE = "TINY-APPROVE"  # automatic remediation, approval required
RULE_MANUAL = "TINY-MANUAL"  # manual remediation, no approval
RULE_NONE = "TINY-NONE"  # non-remediable

_SCOPES = (
    # rule, category, severity, eligible, control-excluded (reserved), selected
    (
        RULE_AUTO,
        Category.METADATA_COMPLETENESS,
        Severity.HIGH,
        ["ds-alpha", "ds-bravo", "ds-charlie"],
        ["ds-reserved"],
        ["ds-alpha"],
    ),
    (
        RULE_APPROVE,
        Category.GOVERNANCE_CLASSIFICATION,
        Severity.MEDIUM,
        ["ds-alpha", "ds-bravo"],
        ["ds-reserved"],
        ["ds-bravo"],
    ),
    (
        RULE_MANUAL,
        Category.SEMANTIC_QUALITY,
        Severity.LOW,
        ["ds-charlie", "ds-delta"],
        [],
        ["ds-charlie"],
    ),
    (
        RULE_NONE,
        Category.FILE_INTEGRITY,
        Severity.HIGH,
        ["file-one"],
        ["ds-reserved"],
        ["file-one"],
    ),
)

_REMEDIATION_CONTRACTS = {
    RULE_AUTO: (
        RemediationAvailability.AUTOMATIC,
        ApprovalPolicy.NOT_REQUIRED,
        ApproverRole.NONE,
        "restore_field",
        "Restored title",
    ),
    RULE_APPROVE: (
        RemediationAvailability.AUTOMATIC,
        ApprovalPolicy.REQUIRED,
        ApproverRole.ACCESS_STEWARD,
        "reclassify_asset",
        "restricted",
    ),
    RULE_MANUAL: (
        RemediationAvailability.MANUAL,
        ApprovalPolicy.NOT_REQUIRED,
        ApproverRole.NONE,
        "rewrite_field",
        None,
    ),
    RULE_NONE: (
        RemediationAvailability.NONE,
        ApprovalPolicy.NOT_REQUIRED,
        ApproverRole.NONE,
        NO_REMEDIATION_ACTION,
        None,
    ),
}

_ENTITY_KINDS = {
    "ds-alpha": "dataset",
    "ds-bravo": "dataset",
    "ds-charlie": "dataset",
    "ds-delta": "dataset",
    "ds-reserved": "dataset",
    "ds-outside": "dataset",
    "file-one": "file",
}

# Entities carrying no defect at all. ``ds-outside`` is in no rule population,
# so it must never contribute a true negative anywhere.
_CONTROLS = (
    ("ds-delta", ControlReason.ELIGIBLE_UNSELECTED, False, 1),
    ("ds-reserved", ControlReason.RESERVED_ASSET, True, 0),
    ("ds-outside", ControlReason.NEVER_ELIGIBLE, False, 0),
)


def _slug(rule_id: str, entity_id: str) -> str:
    return f"{rule_id.lower()}-{entity_id}"


def _build_tiny_ledgers() -> dict[str, bytes]:
    scopes: list[RuleScopeRecord] = []
    findings: list[ExpectedFinding] = []
    remediations: list[ExpectedRemediation] = []

    for rule_id, category, severity, eligible, excluded, selected in _SCOPES:
        scopes.append(
            RuleScopeRecord(
                id=rule_id,
                category=category,
                severity=severity,
                profile=TINY_PROFILE,
                defect_seed=TINY_SEED,
                injection_rate=0.5,
                population_count=len(eligible) + len(excluded),
                control_excluded_count=len(excluded),
                eligible_count=len(eligible),
                candidate_count=len(eligible),
                selected_count=len(selected),
                eligible_ids=list(eligible),
                control_excluded_ids=list(excluded),
                selected_ids=list(selected),
            )
        )
        availability, policy, role, action_class, recommended = _REMEDIATION_CONTRACTS[rule_id]
        for entity_id in selected:
            finding_id = f"finding-{_slug(rule_id, entity_id)}"
            remediation_id = f"remediation-{_slug(rule_id, entity_id)}"
            instance_id = f"instance-{_slug(rule_id, entity_id)}"
            kind = _ENTITY_KINDS[entity_id]
            findings.append(
                ExpectedFinding(
                    id=finding_id,
                    instance_id=instance_id,
                    rule_id=rule_id,
                    category=category,
                    severity=severity,
                    entity_kind=kind,
                    entity_id=entity_id,
                    title=f"{rule_id} on {entity_id}",
                    description="synthetic fixture finding",
                    observable_evidence="synthetic fixture evidence",
                    expected_message_semantics="synthetic fixture semantics",
                    detection_locator=f"{kind}:{entity_id}",
                    remediation_available=availability,
                    non_remediable_reason=(
                        NonRemediableReason.SOURCE_SYSTEM_RECOVERY
                        if availability is RemediationAvailability.NONE
                        else NonRemediableReason.NONE
                    ),
                    remediation_id=remediation_id,
                    match_fields={"rule_id": rule_id, "entity_id": entity_id},
                )
            )
            remediations.append(
                ExpectedRemediation(
                    id=remediation_id,
                    finding_id=finding_id,
                    instance_id=instance_id,
                    rule_id=rule_id,
                    action=action_class,
                    action_class=action_class,
                    target=f"{kind}/{entity_id}",
                    recommended_value=recommended,
                    truth_reference={"field": "value"},
                    availability=availability,
                    approval_policy=policy,
                    approver_role=role,
                    approval_evidence=(
                        ApprovalEvidence.ACCESS_REVIEW_RECORD
                        if policy is ApprovalPolicy.REQUIRED
                        else ApprovalEvidence.NONE
                    ),
                    non_remediable_reason=(
                        NonRemediableReason.SOURCE_SYSTEM_RECOVERY
                        if availability is RemediationAvailability.NONE
                        else NonRemediableReason.NONE
                    ),
                    auto_fixable=availability is RemediationAvailability.AUTOMATIC,
                    requires_human_approval=policy is ApprovalPolicy.REQUIRED,
                    reversible=True,
                )
            )

    controls = [
        ControlRecord(
            id=entity_id,
            entity_kind=_ENTITY_KINDS[entity_id],
            shard="datasets" if _ENTITY_KINDS[entity_id] == "dataset" else "files",
            reason=reason,
            reserved=reserved,
            eligible_rule_count=eligible_rule_count,
            profile=TINY_PROFILE,
            defect_seed=TINY_SEED,
            truth_seed=TINY_SEED,
            control_fraction=0.25,
        )
        for entity_id, reason, reserved, eligible_rule_count in _CONTROLS
    ]

    summary = {
        "meta": {
            "generator_version": "tiny-fixture",
            "schema_version": 1,
            "defect_seed": TINY_SEED,
            "profile": TINY_PROFILE,
            "truth_generator_version": "tiny-fixture",
            "truth_seed": TINY_SEED,
            "epoch_anchor": "2026-01-01",
        },
        "totals": {"defects": len(findings)},
    }

    return {
        RULE_SCOPE_NAME: serialize.jsonl_bytes(scopes),
        EXPECTED_FINDINGS_NAME: serialize.jsonl_bytes(findings),
        EXPECTED_REMEDIATIONS_NAME: serialize.jsonl_bytes(remediations),
        CONTROLS_NAME: serialize.jsonl_bytes(controls),
        PROFILE_SUMMARY_NAME: serialize.manifest_bytes(summary),
    }


@pytest.fixture(scope="session")
def tiny_observed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Materialize the hand-built ground truth into a temporary directory."""
    target = tmp_path_factory.mktemp("tiny-observed")
    for name, data in _build_tiny_ledgers().items():
        (target / name).write_bytes(data)
    return target


# ``real_observed_dir`` lives in the root ``tests/conftest.py``: the example
# submissions are scored against the same canonical ground truth, and generating
# it twice per session would be pure waste.
