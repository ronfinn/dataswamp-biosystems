"""Adversarial scenario cases: constructed reasoning problems, not sampled defects.

The ordinary tiers (``bronze``/``silver``/``gold``) are produced by filtering the
rule registry on how much evidence each *rule* needs — see
:mod:`dataswamp_biosystems.observed.difficulty`. That is a property of the rule,
so it can be selected for with a filter and a rate.

``adversarial`` cannot. It is a property of the *situation a rule occurs in*: the
same rule is easy when its subject stands alone and hard when three
indistinguishable siblings stand beside it, when the only clean explanation lives
on another asset, or when the most suspicious-looking record in view is the one
that is actually fine. None of that can be obtained by sampling the registry
harder, which is why relabelling an ordinary bronze/silver/gold defect
"adversarial" is forbidden: the tier would then measure nothing the other tiers
do not already measure.

So this module *constructs* cases. A :class:`ScenarioClass` states which rule(s)
to fire, on which entities, and — crucially — what else to arrange around them:
evidence that must be related, decoys that must be resisted, and near-miss
controls that must be left alone. The rules themselves are the ordinary
registry rules, unchanged, and the positives they inject are ordinary defects
with ordinary findings, remediations and contracts. What is adversarial is the
composition.

Two polarities
--------------

``positive``
    A real injected defect, deliberately placed in a confusing neighbourhood.
    Failing to flag it is a false negative.
``near-miss-control``
    A **clean** entity deliberately made to *resemble* a defect. It carries no
    finding, stays in the control partition, and every flag against it is a false
    positive. The ordinary control partition proves an agent does not flag at
    random; a near miss proves it actually discriminates.

Near-miss honesty
-----------------

A near miss must be genuinely valid, or it is an unrecorded defect and the
benchmark is lying about its own negatives. Four things enforce that:

* near misses are only ever applied to **reserved** control assets, which the
  profile holds out of every rule's eligible population before selection, so no
  rule could draw them even in principle;
* every field a near miss touches is declared as a :class:`ScenarioTransformation`
  carrying the before value, the after value and the rule it mimics — as explicit
  in the ledger as a mutation is, and emitted to its own file rather than
  smuggled into the defect mutation log;
* the emitted value is chosen to sit on the *valid* side of the rule it mimics —
  equal sizes rather than inverted, a count of one rather than zero, a semver
  prerelease rather than a free-text token, a restricted classification without
  the external use that would contradict it;
* that valid side is a named, executable predicate
  (:data:`NEAR_MISS_VALIDITY_CHECKS`), not a comment, so the validator re-derives
  it from the emitted observed record rather than trusting this module.

Privilege boundary
------------------

Everything here is **answer key**. ``scenarios.jsonl`` and
``scenario-transformations.jsonl`` sit alongside ``expected-findings.jsonl`` and
``controls.jsonl`` on the privileged side of the boundary, and are named in
:data:`dataswamp_biosystems.baselines.observed_input.FORBIDDEN_INPUT_FILES`
accordingly. An agent sees the near-miss *value* — that is the whole point — but
never the record saying it was placed there deliberately, which candidate is the
true positive, or what the expected decision is. There is deliberately no public
scenario view: a "safe subset" of an answer key is a boundary that has to be
re-argued every time a field is added, and the observed graph already carries
everything an agent is entitled to.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
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
    reasoning_scope_for,
)
from dataswamp_biosystems.observed.errors import ObservedConfigError
from dataswamp_biosystems.observed.index import GraphIndex, JsonRecord
from dataswamp_biosystems.truth import ids
from dataswamp_biosystems.truth.rng import sub_rng

#: Bumped when the scenario vocabulary or construction changes in a way that
#: makes a previously published adversarial result non-comparable.
SCENARIO_MODEL_VERSION = 1


class CaseType(StrEnum):
    """What kind of reasoning problem an adversarial case poses.

    Every member is a *constructed* situation. There is deliberately no
    ``direct`` member: a plain single-entity defect is what bronze already is,
    and admitting one here would let the adversarial tier be padded with cases
    that are not adversarial at all.
    """

    #: A clean entity dressed to look like a defect.
    NEAR_MISS_CONTROL = "near-miss-control"
    #: Several plausible candidates share the surface evidence; only a relational
    #: fact identifies the defective one.
    CROSS_RECORD_AMBIGUITY = "cross-record-ambiguity"
    #: Neither asset is defective alone; their disagreement is the defect.
    CROSS_ASSET_INCONSISTENCY = "cross-asset-inconsistency"
    #: Two defects on one entity whose evidence overlaps, so the detector must
    #: attribute each to the right rule rather than merging them into one.
    OVERLAPPING_EVIDENCE = "overlapping-evidence"
    #: Nothing can be repaired from the information available. Proposing a fix is
    #: wrong; an explicit no-action decision is right.
    NO_REMEDIATION = "no-remediation"
    #: A nearby clean entity is more superficially suspicious than the actual
    #: defective one.
    DECOY_CANDIDATE = "decoy-candidate"


#: Case classes an adversarial benchmark must contain to be worth publishing.
#: Every member, not a subset: each one probes a distinct failure mode, and a
#: benchmark missing one silently stops measuring it. Generation fails rather
#: than emitting a partial adversarial tier.
REQUIRED_CASE_TYPES: frozenset[CaseType] = frozenset(CaseType)

#: Fixed reporting order — nominal, never arithmetic.
CASE_TYPE_ORDER: tuple[CaseType, ...] = (
    CaseType.NEAR_MISS_CONTROL,
    CaseType.CROSS_RECORD_AMBIGUITY,
    CaseType.CROSS_ASSET_INCONSISTENCY,
    CaseType.OVERLAPPING_EVIDENCE,
    CaseType.NO_REMEDIATION,
    CaseType.DECOY_CANDIDATE,
)


class ScenarioPolarity(StrEnum):
    """Whether a case's targets carry a defect or are deliberately clean."""

    POSITIVE = "positive"
    NEAR_MISS_CONTROL = "near-miss-control"


class ExpectedDetection(StrEnum):
    """What a correct detector does about a case's target entities."""

    FLAG = "flag"
    NO_FLAG = "no-flag"


class ExpectedRemediationBehaviour(StrEnum):
    """What a correct remediator does about a case's target entities."""

    REMEDIATE = "remediate"
    #: The rule contract admits no repair; an explicit no-action decision is the
    #: correct answer and silence is not.
    NO_REMEDIATION = "no-remediation"
    #: Nothing is wrong, so no remediation is in scope at all. Proposing one is
    #: an unsafe action against a clean record.
    NOT_APPLICABLE = "not-applicable"


class ScenarioTransformation(BaseModel):
    """One declared field change made to a clean entity to construct a near miss.

    Deliberately *not* a :class:`~dataswamp_biosystems.observed.entities.MutationRecord`.
    A mutation record means "a defect was injected here" and is joined to a defect
    instance, a finding and a remediation; a near miss has none of those and must
    never acquire them by sharing a record type. Keeping them apart is what lets
    the validator apply field-for-field truth equality to ordinary controls while
    applying a stricter, itemised invariant here.
    """

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    scenario_id: Slug
    shard: str = Field(min_length=1)
    entity_kind: str = Field(min_length=1)
    entity_id: Slug
    #: JSON-pointer style path, matching ``MutationRecord.path``.
    field_path: str = Field(min_length=1)
    field: str = Field(min_length=1)
    before: Any = None
    after: Any = None
    #: The rule this change is designed to resemble without satisfying.
    mimicked_rule_id: str = Field(min_length=1)
    #: Human-readable statement of why ``after`` is on the valid side of it.
    validity_condition: str = Field(min_length=1)
    #: Key into :data:`NEAR_MISS_VALIDITY_CHECKS`, so the claim above is
    #: re-derivable by machine rather than merely asserted in prose.
    validity_check: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    defect_seed: int = Field(ge=0)
    synthetic: Literal[True] = True


class ScenarioCase(BaseModel):
    """One constructed adversarial reasoning problem.

    The id is derived from the case type, the rules and the target entities —
    never from a counter — so it is stable across runs and across changes to how
    many cases a run produces.
    """

    model_config = STRICT_MODEL_CONFIG

    id: Slug
    difficulty: Difficulty
    case_type: CaseType
    polarity: ScenarioPolarity
    #: The deepest reasoning scope among the case's rules — what a detector must
    #: relate at minimum, before the construction makes it harder.
    reasoning_scope: ReasoningScope
    #: Rules applied (positive) or mimicked (near miss), sorted.
    rule_ids: list[str] = Field(min_length=1)
    categories: list[str] = Field(default_factory=list)
    target_entity_ids: list[str] = Field(min_length=1)
    entity_kinds: list[str] = Field(default_factory=list)
    #: Records a detector must *also* read to decide the case.
    evidence_entity_ids: list[str] = Field(default_factory=list)
    #: Clean entities placed to be mistaken for the target. Always controls.
    decoy_entity_ids: list[str] = Field(default_factory=list)
    #: Expected findings for a positive case; empty for a near miss.
    finding_ids: list[str] = Field(default_factory=list)
    #: Control records for a near miss; empty for a positive case.
    control_ids: list[str] = Field(default_factory=list)
    transformation_ids: list[str] = Field(default_factory=list)
    expected_detection: ExpectedDetection
    expected_remediation: ExpectedRemediationBehaviour
    rationale: str = Field(min_length=1)
    scenario_model_version: int = SCENARIO_MODEL_VERSION
    difficulty_model_version: int = DIFFICULTY_MODEL_VERSION
    profile: str = Field(min_length=1)
    defect_seed: int = Field(ge=0)
    truth_seed: int = Field(ge=0)
    synthetic: Literal[True] = True

    @property
    def is_near_miss(self) -> bool:
        return self.polarity is ScenarioPolarity.NEAR_MISS_CONTROL


# ---------------------------------------------------------------------------
# Near-miss construction.
# ---------------------------------------------------------------------------

#: A near-miss validity check reads the *observed* record and returns whether the
#: mimicked rule would decline to fire on it. Named rather than inlined so the
#: validator can re-run the identical predicate against the emitted bytes.
ValidityCheck = Callable[[JsonRecord], bool]


def _valid_sizes_not_inverted(record: JsonRecord) -> bool:
    """``SCH-SIZE-INVERSION`` fires only when logical < physical."""
    logical = record.get("logical_bytes")
    physical = record.get("physical_bytes")
    if not isinstance(logical, int) or not isinstance(physical, int):
        return False
    return logical >= physical


def _valid_record_count_nonzero(record: JsonRecord) -> bool:
    """``SCH-RECORD-COUNT-ZERO`` fires only on a count of exactly zero."""
    count = record.get("record_count")
    return isinstance(count, int) and count > 0


def _is_canonical_version(value: object) -> bool:
    """Return whether ``value`` is ``MAJOR.MINOR.PATCH`` with an optional prerelease."""
    if not isinstance(value, str) or not value:
        return False
    head, separator, prerelease = value.partition("-")
    parts = head.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return False
    # A trailing hyphen with nothing after it is not a prerelease, it is a typo.
    return not (separator and not prerelease)


def _valid_version_canonical(record: JsonRecord) -> bool:
    """``NAM-VERSION-NONCANONICAL`` fires on free text, never on semver."""
    return _is_canonical_version(record.get("version"))


def _valid_restricted_without_external(record: JsonRecord) -> bool:
    """``USE-EXTERNAL-VS-RESTRICTED`` needs a restricted class *and* an external use."""
    uses = record.get("intended_uses")
    if not isinstance(uses, list):
        return False
    return "external-sharing" not in uses


NEAR_MISS_VALIDITY_CHECKS: dict[str, ValidityCheck] = {
    "sizes-not-inverted": _valid_sizes_not_inverted,
    "record-count-nonzero": _valid_record_count_nonzero,
    "version-canonical": _valid_version_canonical,
    "restricted-without-external": _valid_restricted_without_external,
}


@dataclass(frozen=True)
class NearMissDef:
    """One way to make a clean record *look* wrong without making it wrong.

    ``build`` returns ``{field: new_value}``, or ``None`` when the chosen entity
    cannot support this near miss (a dataset with no size fields, say). Returning
    ``None`` rather than forcing a value keeps a near miss from fabricating a
    field the estate does not otherwise use.
    """

    key: str
    mimicked_rule_id: str
    shard: str
    entity_kind: str
    validity_check: str
    validity_condition: str
    rationale: str
    build: Callable[[JsonRecord], dict[str, Any] | None]


def _equal_sizes(record: JsonRecord) -> dict[str, Any] | None:
    physical = record.get("physical_bytes")
    if not isinstance(physical, int) or physical <= 0:
        return None
    return {"logical_bytes": physical}


def _single_record(record: JsonRecord) -> dict[str, Any] | None:
    count = record.get("record_count")
    if not isinstance(count, int):
        return None
    return {"record_count": 1}


def _prerelease_version(record: JsonRecord) -> dict[str, Any] | None:
    version = record.get("version")
    if not isinstance(version, str) or not version.strip():
        return None
    head = version.split("-", 1)[0]
    parts = head.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return {"version": f"{head}-rc.1"}


def _restricted_without_external(record: JsonRecord) -> dict[str, Any] | None:
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
        mimicked_rule_id="SCH-SIZE-INVERSION",
        shard="datasets",
        entity_kind="dataset",
        validity_check="sizes-not-inverted",
        validity_condition="logical_bytes >= physical_bytes",
        rationale=(
            "logical and physical sizes are exactly equal, which is valid; the rule "
            "fires only when logical is strictly smaller than physical, so a detector "
            "using '<=' reports a clean asset"
        ),
        build=_equal_sizes,
    ),
    NearMissDef(
        key="single-record",
        mimicked_rule_id="SCH-RECORD-COUNT-ZERO",
        shard="datasets",
        entity_kind="dataset",
        validity_check="record-count-nonzero",
        validity_condition="record_count > 0",
        rationale=(
            "a record count of exactly one is a small but valid dataset; the rule "
            "fires only on a count of zero, so a detector testing 'suspiciously few' "
            "reports a clean asset"
        ),
        build=_single_record,
    ),
    NearMissDef(
        key="prerelease-version",
        mimicked_rule_id="NAM-VERSION-NONCANONICAL",
        shard="datasets",
        entity_kind="dataset",
        validity_check="version-canonical",
        validity_condition="version is MAJOR.MINOR.PATCH with an optional prerelease",
        rationale=(
            "a semver prerelease suffix is a canonical version; it resembles the "
            "free-text labels the rule targets without being one"
        ),
        build=_prerelease_version,
    ),
    NearMissDef(
        key="restricted-internal-only",
        mimicked_rule_id="USE-EXTERNAL-VS-RESTRICTED",
        shard="datasets",
        entity_kind="dataset",
        validity_check="restricted-without-external",
        validity_condition="intended_uses does not contain 'external-sharing'",
        rationale=(
            "a restricted classification with no external intended use is exactly "
            "correct handling; the rule needs both halves before it fires, so a "
            "detector triggering on the classification alone reports a clean asset"
        ),
        build=_restricted_without_external,
    ),
)


# ---------------------------------------------------------------------------
# Positive scenario classes.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioClass:
    """One constructed positive case class: which rules fire, and what surrounds them.

    ``rule_ids`` are ordinary registry rules — a scenario never invents a defect
    the catalogue does not define, so every positive it produces carries the same
    contract, finding and remediation semantics as anywhere else. What the class
    contributes is *placement*: which entities, and which additional entities are
    named as evidence or as decoys.
    """

    key: str
    case_type: CaseType
    rule_ids: tuple[str, ...]
    #: How many targets to construct, at most. Kept small: an adversarial case is
    #: expensive to reason about and a hundred of them measures nothing extra.
    target_count: int
    rationale: str
    expected_remediation: ExpectedRemediationBehaviour


#: The initial adversarial set. Deliberately focused — see ``docs/difficulty-tiers.md``:
#: this is a first, honest set of constructed failure modes, not a model of
#: real-world ambiguity in general.
SCENARIO_CLASSES: tuple[ScenarioClass, ...] = (
    ScenarioClass(
        key="denorm-owner-ambiguity",
        case_type=CaseType.CROSS_RECORD_AMBIGUITY,
        rule_ids=("OWN-DENORM-MISMATCH",),
        target_count=3,
        rationale=(
            "the asset and its governance record disagree about the owner; several "
            "sibling assets in the same study carry the same owning team on their "
            "face, so only reading the attached governance record identifies which "
            "one actually contradicts itself"
        ),
        expected_remediation=ExpectedRemediationBehaviour.REMEDIATE,
    ),
    ScenarioClass(
        key="duplicate-final-version",
        case_type=CaseType.CROSS_ASSET_INCONSISTENCY,
        rule_ids=("NAM-DUP-FINAL-VERSION",),
        target_count=2,
        rationale=(
            "each asset's version is individually well-formed; the defect exists "
            "only in the relationship between two sibling datasets that claim the "
            "same final version, and is invisible from either one alone"
        ),
        expected_remediation=ExpectedRemediationBehaviour.REMEDIATE,
    ),
    ScenarioClass(
        key="contract-and-quality-overlap",
        case_type=CaseType.OVERLAPPING_EVIDENCE,
        rule_ids=("SCH-CONTRACT-MISSING", "QC-CERTIFIED-CONTRADICTED"),
        target_count=2,
        rationale=(
            "one asset carries two distinct defects whose evidence overlaps on the "
            "same governance surface: a missing schema contract and a certified "
            "status contradicted by its own quality checks. Reporting one finding "
            "for 'this asset looks unmanaged' is wrong; both rules must be "
            "attributed separately to the same entity"
        ),
        expected_remediation=ExpectedRemediationBehaviour.REMEDIATE,
    ),
    ScenarioClass(
        key="unrecoverable-gene-ids",
        case_type=CaseType.NO_REMEDIATION,
        rule_ids=("MOD-MIXED-GENE-IDS",),
        target_count=2,
        rationale=(
            "gene identifiers are mixed across namespaces, which is detectable but "
            "not repairable from the catalogue: the correct mapping lives in the "
            "upstream processing that produced the matrix. The expected answer is "
            "an explicit no-remediation decision, and proposing a repair is wrong"
        ),
        expected_remediation=ExpectedRemediationBehaviour.NO_REMEDIATION,
    ),
    ScenarioClass(
        key="version-decoy",
        case_type=CaseType.DECOY_CANDIDATE,
        rule_ids=("NAM-VERSION-NONCANONICAL",),
        target_count=2,
        rationale=(
            "the defective asset carries a bland free-text version label, while a "
            "nearby clean control carries a semver prerelease that looks far more "
            "irregular at a glance. An agent ranking candidates by surface oddity "
            "flags the control and misses the target"
        ),
        expected_remediation=ExpectedRemediationBehaviour.REMEDIATE,
    ),
)


# ---------------------------------------------------------------------------
# Planning.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NearMissPlan:
    """One planned near-miss edit, before it is applied or recorded."""

    definition: NearMissDef
    entity_id: str
    field: str
    before: Any
    after: Any


@dataclass(frozen=True)
class ScenarioPlan:
    """The deterministic construction plan for one adversarial run.

    Produced from the truth graph and the reserved partition alone, before any
    mutation is applied, so it is a pure function of ``(truth graph, profile,
    seed)`` and can be reasoned about independently of injection order.
    """

    #: ``{rule_id: [entity_id, …]}`` — the exact, explicit selection. Adversarial
    #: generation never samples at a rate; the scenario classes name their targets.
    selection: dict[str, list[str]]
    #: Per class key, the targets it asked for (before conflict skipping).
    targets_by_class: dict[str, list[str]]
    near_misses: tuple[NearMissPlan, ...]

    @property
    def scoped_rule_ids(self) -> frozenset[str]:
        """Every rule the run must emit a scope record for.

        The rules the scenarios *fire* are not enough. A near miss is built to be
        flagged under the rule it mimics, and if that rule has no scope record the
        pair is never scored — the agent's mistake would be silently reclassified
        as out-of-scope instead of counted as the false positive it is. Emitting
        the scope with an empty selection is what makes a near miss a negative the
        benchmark can actually measure.
        """
        return frozenset(self.selection) | frozenset(
            plan.definition.mimicked_rule_id for plan in self.near_misses
        )

    @property
    def universe(self) -> frozenset[str]:
        """Every entity any scenario names — the adversarial evaluation universe.

        Denominators are drawn from this set rather than from each rule's whole
        population. An adversarial benchmark measures how an agent behaves in the
        constructed neighbourhood; pairing its two dozen rules with every asset in
        the estate would bury that behaviour under thousands of free true
        negatives and drive specificity to ~1.0 for any agent at all.
        """
        found: set[str] = set()
        for entity_ids in self.selection.values():
            found.update(entity_ids)
        found.update(plan.entity_id for plan in self.near_misses)
        return frozenset(found)


class ScenarioUnavailableError(ObservedConfigError):
    """A required adversarial case class cannot be constructed from these inputs.

    An :class:`ObservedConfigError` so the CLI reports it as the configuration
    problem it is (exit code 2) rather than crashing with a traceback: "this
    profile cannot support an adversarial benchmark" is a thing a caller can act
    on, not an internal fault.
    """


def _pick(candidates: Sequence[str], count: int, seed: int, *parts: str) -> list[str]:
    """Draw up to ``count`` ids deterministically from a sorted candidate list."""
    if count <= 0 or not candidates:
        return []
    shuffled = sorted(candidates)
    sub_rng(seed, "scenario", *parts).shuffle(shuffled)
    return sorted(shuffled[:count])


def near_miss_ids_by_mimicked_rule(
    plans: Iterable[NearMissPlan],
) -> dict[str, frozenset[str]]:
    """Return ``{mimicked rule id: near-miss entity ids}``."""
    grouped: dict[str, set[str]] = {}
    for plan in plans:
        grouped.setdefault(plan.definition.mimicked_rule_id, set()).add(plan.entity_id)
    return {rule_id: frozenset(entity_ids) for rule_id, entity_ids in grouped.items()}


def _study_of(index: GraphIndex, entity_id: str) -> str:
    record = index.asset(entity_id)
    return str(record.get("study_id", "")) if record is not None else ""


def _studies_of(index: GraphIndex, entity_ids: Iterable[str]) -> frozenset[str]:
    return frozenset(study_id for study_id in (_study_of(index, e) for e in entity_ids) if study_id)


def plan_scenarios(
    index: GraphIndex,
    reserved: set[str],
    *,
    defect_seed: int,
    near_miss_limit_per_kind: int = 2,
) -> ScenarioPlan:
    """Build the deterministic adversarial construction plan.

    No RNG state is shared between classes: each draw is keyed by the class and
    rule it belongs to, so adding or removing one class never moves another
    class's targets.

    Planning runs in three passes because the classes genuinely depend on each
    other, and pretending otherwise is how a near miss quietly becomes a defect:

    1. the classes that do not need a decoy choose their targets;
    2. the entities those targets' mutations will *collaterally* touch are
       computed and struck out of the near-miss candidates — some rules mutate a
       sibling rather than their own subject, and a reserved control that is
       about to be mutated is not a control at all;
    3. the near misses are planned over what survives, and only then can the
       decoy class choose targets that actually have a decoy beside them.
    """
    selection: dict[str, list[str]] = {}
    targets_by_class: dict[str, list[str]] = {}

    independent = [c for c in SCENARIO_CLASSES if c.case_type is not CaseType.DECOY_CANDIDATE]
    dependent = [c for c in SCENARIO_CLASSES if c.case_type is CaseType.DECOY_CANDIDATE]

    for scenario_class in independent:
        chosen = _choose_targets(index, reserved, scenario_class, defect_seed, near_miss_ids={})
        targets_by_class[scenario_class.key] = chosen
        for rule_id in scenario_class.rule_ids:
            selection.setdefault(rule_id, []).extend(chosen)

    collateral = _collateral_entities(index, selection)
    near_misses = _plan_near_misses(
        index, reserved - collateral, limit_per_kind=near_miss_limit_per_kind
    )
    near_miss_ids_by_rule = near_miss_ids_by_mimicked_rule(near_misses)

    for scenario_class in dependent:
        chosen = _choose_targets(
            index, reserved, scenario_class, defect_seed, near_miss_ids=near_miss_ids_by_rule
        )
        targets_by_class[scenario_class.key] = chosen
        for rule_id in scenario_class.rule_ids:
            selection.setdefault(rule_id, []).extend(chosen)

    # A dependent class must not, in turn, mutate a near miss out of the control
    # partition. No current class can — the decoy rule touches only its own
    # subject — but the plan asserts it rather than assuming it, because the
    # failure would be silent and would corrupt the negative class.
    late_collateral = _collateral_entities(
        index,
        {
            rule_id: entity_ids
            for scenario_class in dependent
            for rule_id in scenario_class.rule_ids
            if (entity_ids := targets_by_class.get(scenario_class.key, []))
        },
    )
    clashing = sorted(late_collateral & {plan.entity_id for plan in near_misses})
    if clashing:
        raise ScenarioUnavailableError(
            f"a decoy-dependent scenario class would mutate near-miss control(s) "
            f"{clashing}, which would move them out of the control partition; "
            "reorder the scenario classes so every collateral target is known "
            "before near misses are planned"
        )

    for rule_id in selection:
        selection[rule_id] = sorted(dict.fromkeys(selection[rule_id]))

    return ScenarioPlan(
        selection=selection,
        targets_by_class=targets_by_class,
        near_misses=near_misses,
    )


def _collateral_entities(index: GraphIndex, selection: dict[str, list[str]]) -> set[str]:
    """Return every entity the planned selection's mutations would touch.

    Dry-run only: ``mutate`` proposes changes and never applies them, so this is
    a pure query. It is deliberately an over-approximation — the engine may later
    skip a mutation on a conflict — because being too careful about what may not
    be dressed as a near miss costs nothing, and being too permissive silently
    puts a defect in the negative class.
    """
    from dataswamp_biosystems.observed.defects import DEFECTS, MutationContext

    touched: set[str] = set()
    for rule_id, entity_ids in selection.items():
        definition = DEFECTS.get(rule_id)
        if definition is None:  # pragma: no cover - registry invariant
            continue
        for entity_id in entity_ids:
            for change in (
                definition.mutate(MutationContext(index=index, entity_id=entity_id)) or []
            ):
                touched.add(change.entity_id)
    return touched


def _choose_targets(
    index: GraphIndex,
    reserved: set[str],
    scenario_class: ScenarioClass,
    defect_seed: int,
    *,
    near_miss_ids: dict[str, frozenset[str]],
) -> list[str]:
    """Return the deterministic target ids for one scenario class."""
    # A class's targets must satisfy *every* rule it fires, otherwise an
    # overlapping-evidence case degenerates into two unrelated single-rule cases
    # on different entities.
    eligible: set[str] | None = None
    for rule_id in scenario_class.rule_ids:
        population = {
            entity_id
            for entity_id in _population_for(index, rule_id)
            if entity_id not in reserved and not _is_reserved_member(index, reserved, entity_id)
        }
        eligible = population if eligible is None else (eligible & population)

    if scenario_class.case_type is CaseType.DECOY_CANDIDATE:
        # Restrict to targets that actually have a decoy standing beside them: a
        # decoy case with no decoy is an ordinary case with a misleading label.
        decoy_ids: set[str] = set()
        for rule_id in scenario_class.rule_ids:
            decoy_ids |= near_miss_ids.get(rule_id, frozenset())
        decoy_studies = _studies_of(index, decoy_ids)
        eligible = {
            entity_id
            for entity_id in (eligible or set())
            if _study_of(index, entity_id) in decoy_studies
        }

    return _pick(
        sorted(eligible or set()),
        scenario_class.target_count,
        defect_seed,
        scenario_class.key,
    )


def _population_for(index: GraphIndex, rule_id: str) -> list[str]:
    """Return a rule's truth-derived population, via the registry.

    Imported lazily: :mod:`dataswamp_biosystems.observed.defects` imports the
    difficulty model, and a module-level import here would close a cycle.
    """
    from dataswamp_biosystems.observed.defects import DEFECTS

    definition = DEFECTS.get(rule_id)
    if definition is None:  # pragma: no cover - registry invariant
        raise ScenarioUnavailableError(
            f"adversarial scenario references unknown rule {rule_id!r}; "
            "every scenario class must name a registered defect rule"
        )
    return definition.population(index)


def _is_reserved_member(index: GraphIndex, reserved: set[str], entity_id: str) -> bool:
    """Return whether ``entity_id`` is a file belonging to a reserved asset."""
    record = index.truth_record("files", entity_id)
    return record is not None and record.get("dataset_id") in reserved


def _plan_near_misses(
    index: GraphIndex,
    reserved: set[str],
    *,
    limit_per_kind: int,
) -> tuple[NearMissPlan, ...]:
    """Plan the near-miss edits over reserved controls, in sorted id order.

    No RNG at all: candidates are taken from the sorted reserved partition and
    capped per kind, so the result is a pure function of the truth graph and the
    reserved set. One entity carries at most one near miss, so a transformation
    can never be confused with a second, contradictory claim about it.
    """
    plans: list[NearMissPlan] = []
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
            for field, value in sorted(changes.items()):
                plans.append(
                    NearMissPlan(
                        definition=definition,
                        entity_id=entity_id,
                        field=field,
                        before=record.get(field),
                        after=value,
                    )
                )
    return tuple(plans)


# ---------------------------------------------------------------------------
# Case construction (after injection, from what actually landed).
# ---------------------------------------------------------------------------


def near_miss_scenario_id(key: str, entity_id: str) -> str:
    """A stable near-miss scenario id, derived from the case and its entity."""
    return ids.join("scn", "nearmiss", key, entity_id)


def positive_scenario_id(class_key: str, entity_id: str) -> str:
    """A stable positive scenario id, derived from the class and its target."""
    return ids.join("scn", class_key, entity_id)


def transformation_id(key: str, entity_id: str, field: str) -> str:
    """A stable transformation id, derived from the near miss it belongs to."""
    return ids.join("sct", key, entity_id, field.replace("_", "-"))


def build_near_miss_cases(
    plans: Iterable[NearMissPlan],
    *,
    profile: str,
    defect_seed: int,
    truth_seed: int,
) -> tuple[list[ScenarioCase], list[ScenarioTransformation]]:
    """Return the near-miss cases and their declared transformations."""
    by_entity: dict[tuple[str, str], list[NearMissPlan]] = {}
    for plan in plans:
        by_entity.setdefault((plan.definition.key, plan.entity_id), []).append(plan)

    cases: list[ScenarioCase] = []
    transformations: list[ScenarioTransformation] = []
    for (key, entity_id), entity_plans in sorted(by_entity.items()):
        definition = entity_plans[0].definition
        scenario_id = near_miss_scenario_id(key, entity_id)
        transformation_ids: list[str] = []
        for plan in entity_plans:
            record_id = transformation_id(key, entity_id, plan.field)
            transformation_ids.append(record_id)
            transformations.append(
                ScenarioTransformation(
                    id=record_id,
                    scenario_id=scenario_id,
                    shard=definition.shard,
                    entity_kind=definition.entity_kind,
                    entity_id=entity_id,
                    field_path=f"/{plan.field}",
                    field=plan.field,
                    before=plan.before,
                    after=plan.after,
                    mimicked_rule_id=definition.mimicked_rule_id,
                    validity_condition=definition.validity_condition,
                    validity_check=definition.validity_check,
                    profile=profile,
                    defect_seed=defect_seed,
                )
            )
        cases.append(
            ScenarioCase(
                id=scenario_id,
                difficulty=Difficulty.ADVERSARIAL,
                case_type=CaseType.NEAR_MISS_CONTROL,
                polarity=ScenarioPolarity.NEAR_MISS_CONTROL,
                reasoning_scope=reasoning_scope_for(definition.mimicked_rule_id),
                rule_ids=[definition.mimicked_rule_id],
                categories=[_category_of(definition.mimicked_rule_id)],
                target_entity_ids=[entity_id],
                entity_kinds=[definition.entity_kind],
                control_ids=[entity_id],
                transformation_ids=sorted(transformation_ids),
                expected_detection=ExpectedDetection.NO_FLAG,
                expected_remediation=ExpectedRemediationBehaviour.NOT_APPLICABLE,
                rationale=definition.rationale,
                profile=profile,
                defect_seed=defect_seed,
                truth_seed=truth_seed,
            )
        )
    return sorted(cases, key=lambda case: case.id), sorted(
        transformations, key=lambda record: record.id
    )


def _category_of(rule_id: str) -> str:
    from dataswamp_biosystems.observed.defects import DEFECTS

    definition = DEFECTS.get(rule_id)
    return definition.category.value if definition is not None else ""


def build_positive_cases(
    plan: ScenarioPlan,
    index: GraphIndex,
    findings_by_pair: dict[tuple[str, str], str],
    near_miss_ids_by_rule: dict[str, frozenset[str]],
    *,
    profile: str,
    defect_seed: int,
    truth_seed: int,
) -> list[ScenarioCase]:
    """Build one positive case per class target that actually received its defects.

    A target whose defects were skipped (an unmet precondition, a conflict with an
    earlier rule) yields no case: an adversarial case that claims a construction
    the observed graph does not contain would be a false entry in the answer key.
    The coverage check then fails if a whole required class was lost that way,
    which is how "an unavailable scenario class fails clearly" is enforced.
    """
    cases: list[ScenarioCase] = []
    for scenario_class in SCENARIO_CLASSES:
        for entity_id in plan.targets_by_class.get(scenario_class.key, []):
            finding_ids = [
                findings_by_pair[(entity_id, rule_id)]
                for rule_id in scenario_class.rule_ids
                if (entity_id, rule_id) in findings_by_pair
            ]
            # Every rule the class declares must have landed, or the constructed
            # problem is not the one described.
            if len(finding_ids) != len(scenario_class.rule_ids):
                continue
            scopes = [reasoning_scope_for(rule_id) for rule_id in scenario_class.rule_ids]
            decoys: list[str] = []
            if scenario_class.case_type is CaseType.DECOY_CANDIDATE:
                # Only a near miss that mimics *this case's* rule is a decoy for
                # it. A control dressed to resemble some unrelated rule is just
                # another clean record, and naming it here would overstate the
                # confusion the case actually creates.
                candidates: set[str] = set()
                for rule_id in scenario_class.rule_ids:
                    candidates |= near_miss_ids_by_rule.get(rule_id, frozenset())
                decoys = _sibling_near_misses(index, entity_id, frozenset(candidates))
            cases.append(
                ScenarioCase(
                    id=positive_scenario_id(scenario_class.key, entity_id),
                    difficulty=Difficulty.ADVERSARIAL,
                    case_type=scenario_class.case_type,
                    polarity=ScenarioPolarity.POSITIVE,
                    reasoning_scope=_deepest_scope(scopes),
                    rule_ids=sorted(scenario_class.rule_ids),
                    categories=sorted({_category_of(r) for r in scenario_class.rule_ids}),
                    target_entity_ids=[entity_id],
                    entity_kinds=[_entity_kind(index, entity_id)],
                    evidence_entity_ids=_evidence_ids(index, entity_id),
                    decoy_entity_ids=sorted(decoys),
                    finding_ids=sorted(finding_ids),
                    expected_detection=ExpectedDetection.FLAG,
                    expected_remediation=scenario_class.expected_remediation,
                    rationale=scenario_class.rationale,
                    profile=profile,
                    defect_seed=defect_seed,
                    truth_seed=truth_seed,
                )
            )
    return sorted(cases, key=lambda case: case.id)


def _sibling_near_misses(
    index: GraphIndex, entity_id: str, candidate_ids: frozenset[str]
) -> list[str]:
    """Return the candidate near-miss controls that share a study with ``entity_id``.

    A near miss in the same study is the strongest available decoy: it is clean,
    it is reserved, and it has been deliberately dressed to look irregular under
    the very rule the target actually violates.
    """
    study_id = _study_of(index, entity_id)
    if not study_id:
        return []
    return sorted(
        control_id for control_id in candidate_ids if _study_of(index, control_id) == study_id
    )


_SCOPE_DEPTH: dict[ReasoningScope, int] = {
    ReasoningScope.SINGLE_RECORD: 0,
    ReasoningScope.CROSS_RECORD: 1,
    ReasoningScope.PEER_RELATIVE: 2,
    ReasoningScope.CROSS_ASSET: 3,
}


def _deepest_scope(scopes: Sequence[ReasoningScope]) -> ReasoningScope:
    return max(scopes, key=lambda scope: _SCOPE_DEPTH[scope])


def _entity_kind(index: GraphIndex, entity_id: str) -> str:
    shard = index.asset_shard.get(entity_id)
    if shard == "data_products":
        return "data_product"
    if shard == "datasets":
        return "dataset"
    return "file" if index.truth_record("files", entity_id) is not None else "dataset"


def _evidence_ids(index: GraphIndex, entity_id: str) -> list[str]:
    """Return the attached records a detector must also read, sorted.

    Only genuinely attached records are listed — the entity's own governance,
    contract, quality and training records, and its files. This is the
    machine-readable statement of how far the reasoning has to reach.

    Resolved against the **truth** graph, deliberately. An evidence record may be
    *absent* from the observed graph, and for some rules that absence is precisely
    the defect: ``SCH-CONTRACT-MISSING`` deletes the contract, so a case that
    listed only surviving records would omit the very thing a detector has to
    notice is gone. Evidence names what should be there, not what is.
    """
    related: set[str] = set()
    for shard in ("governance_records", "contracts", "quality_checks", "training_approvals"):
        for record in index.truth.get(shard, []):
            if record.get("asset_id") == entity_id:
                related.add(str(record.get("id", "")))
    dataset = index.truth_record("datasets", entity_id)
    if dataset is not None:
        related.update(str(file_id) for file_id in dataset.get("file_ids", []) or [])
    return sorted(identifier for identifier in related if identifier)


# ---------------------------------------------------------------------------
# Coverage.
# ---------------------------------------------------------------------------


def scenario_coverage(
    cases: Sequence[ScenarioCase], transformations: Sequence[ScenarioTransformation]
) -> dict[str, Any]:
    """Return the deterministic coverage report for an adversarial run.

    Reports what the tier actually contains, including what it *fails* to
    contain: ``uncovered_required_case_types`` is the field that turns a partial
    adversarial benchmark into a visible gap rather than a quiet one.
    """
    by_case_type: dict[str, int] = {case_type.value: 0 for case_type in CASE_TYPE_ORDER}
    rules: set[str] = set()
    categories: set[str] = set()
    entity_kinds: set[str] = set()
    positives = 0
    near_misses = 0
    for case in cases:
        by_case_type[case.case_type.value] = by_case_type.get(case.case_type.value, 0) + 1
        rules.update(case.rule_ids)
        categories.update(category for category in case.categories if category)
        entity_kinds.update(case.entity_kinds)
        if case.is_near_miss:
            near_misses += 1
        else:
            positives += 1
    uncovered = sorted(
        case_type.value
        for case_type in CASE_TYPE_ORDER
        if case_type in REQUIRED_CASE_TYPES and not by_case_type.get(case_type.value)
    )
    return {
        "scenario_model_version": SCENARIO_MODEL_VERSION,
        "totals": {
            "scenarios": len(cases),
            "positive_scenarios": positives,
            "near_miss_controls": near_misses,
            "transformations": len(transformations),
            "cross_record": by_case_type.get(CaseType.CROSS_RECORD_AMBIGUITY.value, 0),
            "cross_asset": by_case_type.get(CaseType.CROSS_ASSET_INCONSISTENCY.value, 0),
            "overlapping_evidence": by_case_type.get(CaseType.OVERLAPPING_EVIDENCE.value, 0),
            "no_remediation": by_case_type.get(CaseType.NO_REMEDIATION.value, 0),
            "decoy_candidate": by_case_type.get(CaseType.DECOY_CANDIDATE.value, 0),
        },
        "by_case_type": {
            case_type.value: by_case_type.get(case_type.value, 0) for case_type in CASE_TYPE_ORDER
        },
        "rules_represented": sorted(rules),
        "categories_represented": sorted(categories),
        "entity_kinds_represented": sorted(entity_kinds),
        "required_case_types": sorted(case_type.value for case_type in REQUIRED_CASE_TYPES),
        "uncovered_required_case_types": uncovered,
    }


def coverage_problems(coverage: dict[str, Any]) -> list[str]:
    """Return the reasons ``coverage`` is not a publishable adversarial benchmark."""
    problems: list[str] = []
    for case_type in coverage.get("uncovered_required_case_types", []):
        problems.append(
            f"required adversarial case class {case_type!r} produced no scenario; "
            "an adversarial benchmark missing a case class silently stops measuring "
            "the failure mode it exists to measure"
        )
    if not coverage.get("totals", {}).get("near_miss_controls"):
        problems.append(
            "no near-miss controls were constructed; without them the adversarial "
            "tier cannot distinguish an agent that discriminates from one that "
            "simply flags less"
        )
    return problems


__all__ = [
    "CASE_TYPE_ORDER",
    "NEAR_MISS_DEFS",
    "NEAR_MISS_VALIDITY_CHECKS",
    "REQUIRED_CASE_TYPES",
    "SCENARIO_CLASSES",
    "SCENARIO_MODEL_VERSION",
    "CaseType",
    "ExpectedDetection",
    "ExpectedRemediationBehaviour",
    "NearMissDef",
    "NearMissPlan",
    "ScenarioCase",
    "ScenarioClass",
    "ScenarioPlan",
    "ScenarioPolarity",
    "ScenarioTransformation",
    "ScenarioUnavailableError",
    "build_near_miss_cases",
    "build_positive_cases",
    "coverage_problems",
    "near_miss_ids_by_mimicked_rule",
    "near_miss_scenario_id",
    "plan_scenarios",
    "positive_scenario_id",
    "scenario_coverage",
    "transformation_id",
]
