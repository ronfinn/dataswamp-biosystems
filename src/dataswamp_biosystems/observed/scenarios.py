"""Scenario cases: the unit a difficulty tier is actually composed of.

A *rule* says what can go wrong. A *scenario case* says what a detector is being
asked to do about one concrete occurrence, and it is the thing that carries a
difficulty tier. The distinction matters because the same rule can appear in a
straightforward positive case and in an adversarial near-miss control, and a
benchmark that tiered rules instead of cases could not express that.

Two polarities exist:

``positive``
    A real injected defect. Its tier is the rule's tier
    (:mod:`dataswamp_biosystems.observed.difficulty`), unless the case type
    overrides it.
``near-miss-control``
    A **clean** entity deliberately made to *resemble* a defect. It carries no
    finding, stays in the control partition, and every flag against it is a false
    positive. These are the reason the adversarial tier exists: the ordinary
    control partition proves an agent does not flag at random, whereas a
    near-miss proves it actually discriminates.

Near-miss honesty
-----------------

A near-miss must be genuinely valid, or it is simply an unrecorded defect and the
benchmark is lying. Three things enforce that here:

* near-misses are only ever applied to **reserved** control assets, which are
  held out of every rule's eligible population before selection, so no rule could
  draw them even in principle;
* each case names the exact fields it touches and records their before/after, so
  the change is as explicit in the ledger as a mutation is;
* the emitted value is chosen to sit on the *valid* side of the rule it mimics —
  equal sizes rather than inverted, a count of one rather than zero, a
  prerelease version rather than a non-canonical token, a recorded negative
  decision rather than a missing one.

The validator then re-derives all three and fails naming the scenario id, so a
near-miss that drifted into being a real defect cannot ship quietly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.identifiers import Slug
from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG
from dataswamp_biosystems.observed.difficulty import (
    DIFFICULTY_MODEL_VERSION,
    Difficulty,
    ReasoningScope,
    difficulty_for,
    reasoning_scope_for,
)
from dataswamp_biosystems.observed.entities import RemediationAvailability
from dataswamp_biosystems.observed.index import GraphIndex, JsonRecord
from dataswamp_biosystems.truth import ids


class CaseType(StrEnum):
    """What kind of reasoning problem a case poses."""

    #: An ordinary injected defect, tiered by its rule's reasoning scope.
    DIRECT = "direct"
    #: A clean entity dressed to look like a defect.
    NEAR_MISS_CONTROL = "near-miss-control"
    #: Several plausible candidates; only relational evidence identifies the
    #: defective one.
    CROSS_RECORD_AMBIGUITY = "cross-record-ambiguity"
    #: Invisible from either asset alone.
    CROSS_ASSET_INCONSISTENCY = "cross-asset-inconsistency"
    #: Two or more defects whose evidence overlaps on one entity, so the
    #: detector must attribute each to the right rule.
    OVERLAPPING_EVIDENCE = "overlapping-evidence"
    #: Nothing can be remediated from the information available. Proposing a
    #: repair is wrong; an explicit no-action decision is right.
    NO_REMEDIATION = "no-remediation"


#: Case types that are adversarial regardless of the rule's own tier. These are
#: the cases designed to *cost* a careless detector rather than merely to be far
#: away, which is what separates the adversarial tier from gold.
ADVERSARIAL_CASE_TYPES: frozenset[str] = frozenset(
    {
        CaseType.NEAR_MISS_CONTROL,
        CaseType.OVERLAPPING_EVIDENCE,
        CaseType.NO_REMEDIATION,
    }
)


class ScenarioCase(BaseModel):
    """One tiered reasoning problem, positive or near-miss.

    Emitted to ``scenarios.jsonl``. The id is derived from the case type, the
    rule and the entity — never from a counter — so it is stable across runs and
    across changes to the number of cases generated.
    """

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    difficulty: Difficulty
    case_type: str = Field(min_length=1)
    reasoning_scope: ReasoningScope
    polarity: Literal["positive", "near-miss-control"]
    rule_ids: list[str] = Field(min_length=1)
    target_entity_ids: list[str] = Field(min_length=1)
    #: Entities a detector must *also* consult to decide the case. Empty for a
    #: single-record case; this is the machine-readable statement of how far the
    #: reasoning has to reach.
    evidence_entity_ids: list[str] = Field(default_factory=list)
    #: The expected finding this case corresponds to, for a positive case, or the
    #: control record it annotates, for a near miss.
    finding_id: str = ""
    control_id: str = ""
    #: Fields the case touched, with their before/after — the near-miss
    #: equivalent of a mutation record.
    changed_fields: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    difficulty_model_version: int = DIFFICULTY_MODEL_VERSION
    profile: str = Field(min_length=1)
    defect_seed: int = Field(ge=0)
    synthetic: Literal[True] = True

    @property
    def is_near_miss(self) -> bool:
        return self.polarity == "near-miss-control"


def case_difficulty(rule_id: str, case_type: str) -> Difficulty:
    """Return the tier of a case: the case type wins, else the rule's own tier."""
    if case_type in ADVERSARIAL_CASE_TYPES:
        return Difficulty.ADVERSARIAL
    if case_type == CaseType.CROSS_ASSET_INCONSISTENCY:
        return Difficulty.GOLD
    if case_type == CaseType.CROSS_RECORD_AMBIGUITY:
        return max(
            (difficulty_for(rule_id), Difficulty.SILVER),
            key=lambda tier: ("bronze", "silver", "gold", "adversarial").index(tier.value),
        )
    return difficulty_for(rule_id)


# ---------------------------------------------------------------------------
# Near-miss construction.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NearMissDef:
    """One way to make a clean record *look* wrong without making it wrong.

    ``build`` returns ``{field: new_value}`` for the record, or ``None`` when the
    chosen entity cannot support this near miss (a dataset with no size fields,
    say). Returning ``None`` rather than forcing a value keeps a near miss from
    fabricating a field the estate does not otherwise use.
    """

    key: str
    resembles_rule_id: str
    shard: str
    rationale: str
    build: Callable[[JsonRecord], dict[str, Any] | None]


def _equal_sizes(record: JsonRecord) -> dict[str, Any] | None:
    """Logical size exactly equal to physical: unusual, compressible-free, valid.

    ``SCH-SIZE-INVERSION`` fires only when logical < physical. Equality sits one
    step the correct side of it, so a detector using ``<=`` reports a clean asset.
    """
    physical = record.get("physical_bytes")
    if not isinstance(physical, int) or physical <= 0:
        return None
    return {"logical_bytes": physical}


def _single_record(record: JsonRecord) -> dict[str, Any] | None:
    """A record count of exactly one. ``SCH-RECORD-COUNT-ZERO`` fires only on zero."""
    count = record.get("record_count")
    if not isinstance(count, int):
        return None
    return {"record_count": 1}


def _prerelease_version(record: JsonRecord) -> dict[str, Any] | None:
    """A valid semver prerelease. Resembles a non-canonical version token."""
    version = record.get("version")
    if not isinstance(version, str) or not version.strip():
        return None
    head = version.split("-", 1)[0]
    parts = head.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return {"version": f"{head}-rc.1"}


def _restricted_without_external(record: JsonRecord) -> dict[str, Any] | None:
    """Restricted classification with no external use: valid, and looks alarming.

    ``USE-EXTERNAL-VS-RESTRICTED`` needs *both* a restricted classification and an
    external intended use. A detector that flags on the classification alone
    reports this clean asset.
    """
    uses = record.get("intended_uses")
    if not isinstance(uses, list) or not uses:
        return None
    if "external-sharing" in uses:
        return None
    if record.get("access_classification") == "restricted":
        return None
    return {"access_classification": "restricted"}


NEAR_MISS_DEFS: tuple[NearMissDef, ...] = (
    NearMissDef(
        key="equal-sizes",
        resembles_rule_id="SCH-SIZE-INVERSION",
        shard="datasets",
        rationale=(
            "logical and physical sizes are exactly equal, which is valid; the rule "
            "fires only when logical is strictly smaller than physical"
        ),
        build=_equal_sizes,
    ),
    NearMissDef(
        key="single-record",
        resembles_rule_id="SCH-RECORD-COUNT-ZERO",
        shard="datasets",
        rationale=(
            "a record count of exactly one is a small but valid dataset; the rule "
            "fires only on a count of zero"
        ),
        build=_single_record,
    ),
    NearMissDef(
        key="prerelease-version",
        resembles_rule_id="NAM-VERSION-NONCANONICAL",
        shard="datasets",
        rationale=(
            "a semver prerelease suffix is a canonical version; it resembles the "
            "free-text tokens the rule targets without being one"
        ),
        build=_prerelease_version,
    ),
    NearMissDef(
        key="restricted-internal-only",
        resembles_rule_id="USE-EXTERNAL-VS-RESTRICTED",
        shard="datasets",
        rationale=(
            "a restricted classification with no external intended use is exactly "
            "correct handling; the rule needs both halves before it fires"
        ),
        build=_restricted_without_external,
    ),
)


def near_miss_id(key: str, entity_id: str) -> str:
    """A stable scenario id, derived from the case and its entity."""
    return ids.join("scn", "nearmiss", key, entity_id)


def positive_case_id(rule_id: str, entity_id: str) -> str:
    """A stable scenario id for a positive case."""
    return ids.join("scn", rule_id.lower(), entity_id)


def build_near_miss_cases(
    index: GraphIndex,
    reserved: set[str],
    *,
    profile: str,
    defect_seed: int,
    limit_per_kind: int,
) -> tuple[list[ScenarioCase], list[tuple[str, str, str, Any]]]:
    """Return near-miss cases and the field edits they imply.

    Edits are returned rather than applied so the caller stays the only place that
    writes to the working graph. Each edit is
    ``(shard, entity_id, field, new_value)``.

    Candidates are drawn from **reserved** control assets in sorted id order and
    capped per kind, so the result is a deterministic function of the truth graph
    and the reserved partition — no RNG is consulted here at all.
    """
    cases: list[ScenarioCase] = []
    edits: list[tuple[str, str, str, Any]] = []
    used: set[str] = set()

    for definition in NEAR_MISS_DEFS:
        taken = 0
        for entity_id in sorted(reserved):
            if taken >= limit_per_kind:
                break
            if entity_id in used:
                continue
            if index.asset_shard.get(entity_id) != definition.shard:
                continue
            record = index.truth_record(definition.shard, entity_id)
            if record is None:
                continue
            changes = definition.build(record)
            if not changes:
                continue
            # Never dress a record in a value it already has: a "near miss" that
            # changes nothing is an empty claim in the ledger.
            changes = {
                field: value for field, value in changes.items() if record.get(field) != value
            }
            if not changes:
                continue

            used.add(entity_id)
            taken += 1
            cases.append(
                ScenarioCase(
                    id=near_miss_id(definition.key, entity_id),
                    difficulty=Difficulty.ADVERSARIAL,
                    case_type=CaseType.NEAR_MISS_CONTROL,
                    reasoning_scope=reasoning_scope_for(definition.resembles_rule_id),
                    polarity="near-miss-control",
                    rule_ids=[definition.resembles_rule_id],
                    target_entity_ids=[entity_id],
                    control_id=entity_id,
                    changed_fields={
                        field: {"before": record.get(field), "after": value}
                        for field, value in changes.items()
                    },
                    rationale=definition.rationale,
                    profile=profile,
                    defect_seed=defect_seed,
                )
            )
            for field, value in changes.items():
                edits.append((definition.shard, entity_id, field, value))

    return cases, edits


def build_positive_cases(
    findings: list[Any],
    index: GraphIndex,
    *,
    profile: str,
    defect_seed: int,
) -> list[ScenarioCase]:
    """Derive one scenario case per injected defect, tiered by its rule.

    Positive cases are *derived*, not authored: every injected defect is already
    a reasoning problem, and re-stating it as a case is what lets a tier report
    cover positives and near misses in one vocabulary. The evidence entities are
    the records a detector must consult beyond the target, which is exactly what
    the rule's reasoning scope names.
    """
    cases: list[ScenarioCase] = []
    for finding in findings:
        rule_id = finding.rule_id
        scope = reasoning_scope_for(rule_id)
        case_type = (
            CaseType.NO_REMEDIATION
            if finding.remediation_available is RemediationAvailability.NONE
            else _CASE_TYPE_BY_SCOPE[scope]
        )
        cases.append(
            ScenarioCase(
                id=positive_case_id(rule_id, finding.entity_id),
                difficulty=case_difficulty(rule_id, case_type),
                case_type=case_type,
                reasoning_scope=scope,
                polarity="positive",
                rule_ids=[rule_id],
                target_entity_ids=[finding.entity_id],
                evidence_entity_ids=_evidence_ids(index, finding.entity_id, scope),
                finding_id=finding.id,
                rationale=(f"{scope.value} detection: {finding.observable_evidence}"),
                profile=profile,
                defect_seed=defect_seed,
            )
        )
    return sorted(cases, key=lambda case: case.id)


_CASE_TYPE_BY_SCOPE: dict[ReasoningScope, str] = {
    ReasoningScope.SINGLE_RECORD: CaseType.DIRECT,
    ReasoningScope.CROSS_RECORD: CaseType.CROSS_RECORD_AMBIGUITY,
    ReasoningScope.CROSS_ASSET: CaseType.CROSS_ASSET_INCONSISTENCY,
    ReasoningScope.PEER_RELATIVE: CaseType.CROSS_ASSET_INCONSISTENCY,
}


def _evidence_ids(index: GraphIndex, entity_id: str, scope: ReasoningScope) -> list[str]:
    """Return the attached records a detector must also read, sorted.

    Only genuinely attached records are listed — the entity's own governance,
    contract, quality, training and file records. A single-record case lists
    nothing, which is the point of the tier.
    """
    if scope is ReasoningScope.SINGLE_RECORD:
        return []
    related: set[str] = set()
    for shard in ("governance_records", "contracts", "quality_checks", "training_approvals"):
        for record in index.working.get(shard, []):
            if record.get("asset_id") == entity_id:
                related.add(str(record.get("id", "")))
    dataset = index.truth_record("datasets", entity_id)
    if dataset is not None:
        for file_id in dataset.get("file_ids", []) or []:
            related.add(str(file_id))
    return sorted(identifier for identifier in related if identifier)


__all__ = [
    "ADVERSARIAL_CASE_TYPES",
    "NEAR_MISS_DEFS",
    "CaseType",
    "NearMissDef",
    "ScenarioCase",
    "build_near_miss_cases",
    "build_positive_cases",
    "case_difficulty",
    "near_miss_id",
    "positive_case_id",
]
