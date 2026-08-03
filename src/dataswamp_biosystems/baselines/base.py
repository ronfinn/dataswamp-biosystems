"""The one interface every baseline agent implements.

Deliberately minimal: an agent is a name, a version, a documented list of the
observed fields it reads, and a function from :class:`ObservedInput` to a stream
of :class:`~dataswamp_biosystems.evaluation.predictions.Prediction` records.
There is no orchestration framework, no plugin loader and no lifecycle — a
baseline is a function with a label on it.

That shape is also the natural boundary for a future model-backed agent: such an
agent would implement :class:`BaselineAgent`, take its client as a constructor
argument, and emit the same ``Prediction`` records. Nothing in this package
needs to change to accommodate one, and nothing here reaches for a provider,
credentials or the network.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from dataswamp_biosystems.baselines.catalogue import RuleFact
from dataswamp_biosystems.baselines.observed_input import ObservedEntity, ObservedInput
from dataswamp_biosystems.evaluation.predictions import (
    PREDICTION_SCHEMA_VERSION,
    STATUS_FINDING,
    PredictedRemediation,
    Prediction,
)

# Baseline versions are independent of the package version: a baseline's score
# is only meaningful next to the exact heuristic that produced it, so the
# heuristic carries its own version and a change to it is a change to that
# number.
BASELINE_SCHEMA_VERSION = PREDICTION_SCHEMA_VERSION


@dataclass(frozen=True)
class BaselineInfo:
    """Identity and declared reads for one baseline, recorded on every prediction."""

    name: str
    version: str
    summary: str
    #: The observed-graph fields the agent inspects, as ``shard.field`` strings.
    #: Documentation that is checked: the public docs are generated from it.
    reads: tuple[str, ...]

    @property
    def agent_fields(self) -> dict[str, str]:
        """The ``agent`` block written into every prediction this baseline emits."""
        return {"name": self.name, "version": self.version}


@runtime_checkable
class BaselineAgent(Protocol):
    """A benchmark participant: observed state in, predictions out."""

    info: BaselineInfo

    def predict(self, observed: ObservedInput) -> Iterable[Prediction]:
        """Yield predictions for ``observed``. Must be pure and deterministic."""
        ...


def make_prediction(
    *,
    info: BaselineInfo,
    entity_id: str,
    fact: RuleFact,
    evidence: str,
    confidence: float,
    with_remediation: bool,
) -> Prediction:
    """Build one finding prediction from a rule's published facts.

    ``prediction_id`` is derived from the claim itself rather than a counter, so
    it does not depend on emission order and two runs that find the same claims
    agree line for line.
    """
    remediation = None
    if with_remediation:
        remediation = PredictedRemediation(
            action_class=fact.action_class,
            availability=fact.availability,
            approval_policy=fact.approval_policy,
            approver_role=fact.approver_role,
            recommended_value=fact.recommended_value,
        )
    return Prediction(
        schema_version=BASELINE_SCHEMA_VERSION,
        prediction_id=f"{info.name}:{entity_id}:{fact.rule_id}",
        entity_id=entity_id,
        rule_id=fact.rule_id,
        status=STATUS_FINDING,
        category=fact.category,
        severity=fact.severity,
        confidence=confidence,
        evidence=evidence,
        remediation=remediation,
        agent=info.agent_fields,
    )


def in_order(predictions: Iterable[Prediction]) -> Iterator[Prediction]:
    """Yield predictions in the canonical submission order.

    Sorting on ``(entity_id, rule_id)`` — the pair that identifies the claim —
    makes output independent of the order the agent happened to discover things
    in, and therefore of the order records appear in the observed graph.
    """
    yield from sorted(predictions, key=lambda p: (p.entity_id, p.rule_id))


def modality_of(entity: ObservedEntity) -> str:
    """Return an entity's declared modality, or the empty string when it has none."""
    value = entity.get("modality")
    return value if isinstance(value, str) else ""


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "BaselineAgent",
    "BaselineInfo",
    "in_order",
    "make_prediction",
    "modality_of",
]
