"""A metadata-only view of the published defect-rule catalogue.

The rule catalogue is *public*: ``dataswamp list-defects`` prints every rule id,
category, default severity, the kinds and modalities it applies to, and its
remediation contract. An agent author reads it to know what claims are
expressible. Consuming it is therefore not leakage — it is the benchmark's
question paper, not its answer key.

What *is* leakage is the rest of a :class:`~dataswamp_biosystems.observed.DefectDef`:
``population`` tells an agent which entities a rule drew from, and ``mutate`` is
the injection routine itself. A baseline that called either would be predicting
the injector rather than detecting a defect.

:class:`RuleFact` exists to make that distinction structural. It is a frozen
dataclass of plain values with no callables, projected once from the registry at
import time, and it is the only thing the baseline agents ever see. A test
asserts that no field of it holds anything callable.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from dataswamp_biosystems.observed import defects_in_order
from dataswamp_biosystems.observed.entities import (
    ApprovalPolicy,
    ApproverRole,
    Category,
    RemediationAvailability,
    Severity,
)

# The modality wildcard the registry uses for "any modality".
ANY_MODALITY = "*"


@dataclass(frozen=True)
class RuleFact:
    """The published facts about one rule: what it means and how it is fixed."""

    rule_id: str
    title: str
    category: Category
    severity: Severity
    applies_to_kinds: tuple[str, ...]
    applies_to_modalities: tuple[str, ...]
    action_class: str
    availability: RemediationAvailability
    approval_policy: ApprovalPolicy
    approver_role: ApproverRole
    recommended_value: str | None

    def applies_to(self, kind: str, modality: str) -> bool:
        """Whether this rule could apply to an entity of ``kind`` and ``modality``.

        This mirrors the *declared* applicability the catalogue publishes. It is
        not the rule's population — a baseline cannot know that — but it keeps a
        baseline from filing, say, a dataset-only rule against a data product,
        which the evaluator would score as an out-of-scope false positive.
        """
        if kind not in self.applies_to_kinds:
            return False
        if ANY_MODALITY in self.applies_to_modalities:
            return True
        return modality in self.applies_to_modalities


def _project() -> dict[str, RuleFact]:
    return {
        defect.rule_id: RuleFact(
            rule_id=defect.rule_id,
            title=defect.title,
            category=defect.category,
            severity=defect.default_severity,
            applies_to_kinds=tuple(defect.applies_to_kinds),
            applies_to_modalities=tuple(defect.applies_to_modalities),
            action_class=defect.action_class,
            availability=defect.remediation_availability,
            approval_policy=defect.approval_policy,
            approver_role=defect.approver_role,
            recommended_value=(
                defect.remediation_recommended
                if isinstance(defect.remediation_recommended, str)
                else None
            ),
        )
        for defect in defects_in_order()
    }


RULE_FACTS: dict[str, RuleFact] = _project()

# Field names, so a leakage test can walk a RuleFact generically.
RULE_FACT_FIELDS: tuple[str, ...] = tuple(field.name for field in fields(RuleFact))


def rule_fact(rule_id: str) -> RuleFact:
    """Return the published facts for ``rule_id``, or raise :class:`KeyError`."""
    return RULE_FACTS[rule_id]


__all__ = ["ANY_MODALITY", "RULE_FACTS", "RULE_FACT_FIELDS", "RuleFact", "rule_fact"]
