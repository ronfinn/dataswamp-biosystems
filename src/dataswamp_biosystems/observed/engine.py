"""The deterministic imperfection engine.

Given a truth graph, the canonical config, a profile, and a defect seed, this
derives an observed graph plus the six ledgers (defect instances, mutations,
expected findings, expected remediations, controls, rule scope). Every emitted
record carries its rule's remediation contract — availability, approval policy
and approver — so remediation capability and authorisation stay independently
scorable. It never mutates the truth graph: all
edits land on the :class:`~dataswamp_biosystems.observed.index.GraphIndex`
working copy (independent JSON dicts).

Determinism is structural: defects are applied in sorted rule-id order over
sorted, seed-shuffled eligible populations; every random draw comes from
``sub_rng(defect_seed, …)`` keyed by profile and rule; and a control partition
plus a conflict ledger keep selection reproducible and mutually consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dataswamp_biosystems.company.config import CanonicalConfig
from dataswamp_biosystems.observed.defects import (
    DEFECTS,
    REQUIRED_CONTRACT_STATES,
    DefectDef,
    FieldChange,
    MutationContext,
    contract_coverage,
    defects_in_order,
)
from dataswamp_biosystems.observed.difficulty import (
    Difficulty,
    selectable_rules,
)
from dataswamp_biosystems.observed.entities import (
    NO_REMEDIATION_ACTION,
    ChangeOp,
    ControlReason,
    ControlRecord,
    DefectInstance,
    ExpectedFinding,
    ExpectedRemediation,
    MutationRecord,
    ObservedMeta,
    RuleScopeRecord,
)
from dataswamp_biosystems.observed.errors import ObservedConfigError
from dataswamp_biosystems.observed.index import SHARD_NAMES, GraphIndex, JsonRecord
from dataswamp_biosystems.observed.profiles import ObservedProfile, profile_spec
from dataswamp_biosystems.observed.scenarios import (
    ScenarioCase,
    ScenarioPlan,
    ScenarioTransformation,
    build_near_miss_cases,
    build_positive_cases,
    coverage_problems,
    near_miss_ids_by_mimicked_rule,
    plan_scenarios,
    scenario_coverage,
)
from dataswamp_biosystems.truth import ids
from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.rng import sub_rng

# 1.3.0 / schema 4 — the adversarial tier: constructed scenario cases, declared
# near-miss transformations over reserved controls, and the two ledgers that
# record them. Nothing that existed at schema 3 changed shape or meaning; a
# ``mixed`` run's ledgers are byte-identical apart from the version fields in
# ``meta``.
OBSERVED_GENERATOR_VERSION = "1.3.0"
OBSERVED_SCHEMA_VERSION = 4

#: Schema versions this generator can still read and validate. Schema 3 output
#: remains interpretable — it simply carries no scenario ledgers — so a v3
#: benchmark is not invalidated by this migration.
SUPPORTED_OBSERVED_SCHEMA_VERSIONS: frozenset[int] = frozenset({3, 4})

#: The lowest schema version that can express an adversarial benchmark. A v3
#: directory claiming ``difficulty: adversarial`` is malformed rather than merely
#: old, because v3 has nowhere to put the scenario ledgers.
ADVERSARIAL_MIN_SCHEMA_VERSION = 4


def _symmetric_incompatibilities() -> dict[str, set[str]]:
    """Close the declared incompatibilities so the relation is symmetric."""
    closure: dict[str, set[str]] = {rule_id: set() for rule_id in DEFECTS}
    for rule_id, definition in DEFECTS.items():
        for other in definition.incompatibilities:
            closure[rule_id].add(other)
            if other in closure:
                closure[other].add(rule_id)
    return closure


_INCOMPATIBLE = _symmetric_incompatibilities()


@dataclass(frozen=True)
class ObservedResult:
    """The full output of one engine run: observed graph plus the six ledgers."""

    meta: ObservedMeta
    observed_graph: dict[str, Any]
    instances: list[DefectInstance]
    mutations: list[MutationRecord]
    findings: list[ExpectedFinding]
    remediations: list[ExpectedRemediation]
    controls: list[ControlRecord]
    rule_scopes: list[RuleScopeRecord]
    summary: dict[str, Any]
    #: Constructed adversarial cases, and the declared field changes that build
    #: their near-miss controls. Both are empty for every non-adversarial run, so
    #: a default run emits neither file and its bytes cannot move.
    scenarios: list[ScenarioCase] = field(default_factory=list)
    transformations: list[ScenarioTransformation] = field(default_factory=list)
    #: The tier this run was restricted to, or ``None`` for the full catalogue.
    #: Deliberately *not* part of :class:`ObservedMeta`: meta is serialized into
    #: the observed graph and the profile summary, and a default run's bytes must
    #: not move. It travels in provenance instead, which no digest covers.
    difficulty: Difficulty | None = None


@dataclass
class _Ledger:
    """Mutable bookkeeping shared across the application pass."""

    applied_rules: dict[str, set[str]] = field(default_factory=dict)
    locked_paths: set[tuple[str, str, str]] = field(default_factory=set)
    locked_records: set[tuple[str, str]] = field(default_factory=set)
    deleted_records: set[tuple[str, str]] = field(default_factory=set)
    per_entity_count: dict[str, int] = field(default_factory=dict)
    applied_total: int = 0
    skipped_precondition: int = 0
    skipped_conflict: int = 0
    skipped_incompatible: int = 0
    skipped_cap: int = 0


def _controls(index: GraphIndex, spec_fraction: float, defect_seed: int, profile: str) -> set[str]:
    """Reserve a deterministic prefix of shuffled assets as never-eligible controls."""
    asset_ids = index.asset_ids()
    n = round(spec_fraction * len(asset_ids))
    if n <= 0:
        return set()
    shuffled = list(asset_ids)
    sub_rng(defect_seed, "control", profile).shuffle(shuffled)
    return set(shuffled[:n])


def _is_control(index: GraphIndex, controls: set[str], entity_id: str) -> bool:
    if entity_id in controls:
        return True
    file_rec = index.truth_record("files", entity_id)
    if file_rec is not None:
        return file_rec.get("dataset_id") in controls
    return False


def _build_controls(
    index: GraphIndex,
    reserved: set[str],
    meta: ObservedMeta,
    control_fraction: float,
    instances: list[DefectInstance],
    mutations: list[MutationRecord],
    eligible_rule_count: dict[str, int],
) -> list[ControlRecord]:
    """Return every asset and file that carries no injected defect, id-sorted.

    An entity is a control when it anchors no defect instance *and* is named by
    no mutation, so an entity touched only indirectly (via its governance or
    contract record) is correctly excluded — those mutations name the asset's
    own instance anchor. The reserved partition is recorded explicitly, since it
    is the subset held out from selection rather than merely never drawn.
    """
    defective = {instance.entity_id for instance in instances}
    defective |= {mutation.entity_id for mutation in mutations}

    records: list[ControlRecord] = []
    for entity_id in sorted(set(index.asset_ids()) | set(index.file_ids())):
        if entity_id in defective:
            continue
        shard = _primary_shard(index, entity_id)
        truth_record = index.truth_record(shard, entity_id) or {}
        parent_asset_id = str(truth_record.get("dataset_id", "")) if shard == "files" else ""
        if entity_id in reserved:
            reason = ControlReason.RESERVED_ASSET
        elif parent_asset_id and parent_asset_id in reserved:
            reason = ControlReason.MEMBER_OF_RESERVED_ASSET
        elif eligible_rule_count.get(entity_id, 0) > 0:
            reason = ControlReason.ELIGIBLE_UNSELECTED
        else:
            reason = ControlReason.NEVER_ELIGIBLE
        records.append(
            ControlRecord(
                id=entity_id,
                entity_kind=_entity_kind(index, entity_id),
                shard=shard,
                reason=reason,
                reserved=reason
                in (ControlReason.RESERVED_ASSET, ControlReason.MEMBER_OF_RESERVED_ASSET),
                parent_asset_id=parent_asset_id,
                modality=str(truth_record.get("modality", "")),
                modality_group=modality_group_of(index, entity_id),
                eligible_rule_count=eligible_rule_count.get(entity_id, 0),
                profile=meta.profile,
                defect_seed=meta.defect_seed,
                truth_seed=meta.truth_seed,
                control_fraction=control_fraction,
            )
        )
    return records


def _primary_shard(index: GraphIndex, entity_id: str) -> str:
    if entity_id in index.asset_shard:
        return index.asset_shard[entity_id]
    if index.truth_record("files", entity_id) is not None:
        return "files"
    return "datasets"


def _entity_kind(index: GraphIndex, entity_id: str) -> str:
    shard = _primary_shard(index, entity_id)
    return {"data_products": "data_product", "files": "file"}.get(shard, "dataset")


def _has_conflict(ledger: _Ledger, changes: list[FieldChange]) -> bool:
    for change in changes:
        key = (change.shard, change.entity_id)
        if key in ledger.deleted_records:
            return True
        if change.op is ChangeOp.DELETE_RECORD:
            # A record may not be deleted once any of its fields has been mutated.
            if key in ledger.locked_records:
                return True
        elif change.op is not ChangeOp.ADD_RECORD and (
            (change.shard, change.entity_id, change.field) in ledger.locked_paths
        ):
            return True
    return False


def _apply(index: GraphIndex, ledger: _Ledger, changes: list[FieldChange]) -> None:
    for change in changes:
        if change.op is ChangeOp.DELETE_RECORD:
            index.delete_working_record(change.shard, change.entity_id)
            ledger.deleted_records.add((change.shard, change.entity_id))
            ledger.locked_paths.add((change.shard, change.entity_id, "*"))
        elif change.op is ChangeOp.ADD_RECORD:
            index.add_working_record(change.shard, change.after)
        else:
            index.set_working_field(change.shard, change.entity_id, change.field, change.after)
            ledger.locked_paths.add((change.shard, change.entity_id, change.field))
            ledger.locked_records.add((change.shard, change.entity_id))


def _rule_lower(rule_id: str) -> str:
    return rule_id.lower()


def _emit(
    definition: DefectDef,
    index: GraphIndex,
    entity_id: str,
    changes: list[FieldChange],
    profile: str,
    defect_seed: int,
    truth_seed: int,
    rationale: str,
) -> tuple[DefectInstance, list[MutationRecord], ExpectedFinding, ExpectedRemediation]:
    rule_lower = _rule_lower(definition.rule_id)
    instance_id = ids.join("di", rule_lower, entity_id)
    finding_id = ids.join("find", rule_lower, entity_id)
    remediation_id = ids.join("rem", rule_lower, entity_id)

    mutations: list[MutationRecord] = []
    for n, change in enumerate(changes, start=1):
        mutations.append(
            MutationRecord(
                id=ids.join("mut", rule_lower, entity_id, ids.ordinal(n)),
                instance_id=instance_id,
                rule_id=definition.rule_id,
                shard=change.shard,
                entity_kind=change.entity_kind,
                entity_id=change.entity_id,
                operation=change.op,
                path=change.path,
                field=change.field,
                before=change.before,
                after=change.after,
                severity=definition.default_severity,
                seed=defect_seed,
                profile=profile,
                selection_rationale=rationale,
                auto_fixable=definition.auto_fixable,
                requires_human_approval=definition.requires_human_approval,
                reversible=change.reversible,
                manifestation="physical" if definition.physically_manifested else "metadata",
            )
        )

    primary_shard = _primary_shard(index, entity_id)
    truth_rec = index.truth_record(primary_shard, entity_id) or {}
    modality = str(truth_rec.get("modality", ""))
    target_fields = sorted({c.field for c in changes if c.field} or {c.shard for c in changes})
    entity_kind = _entity_kind(index, entity_id)

    instance = DefectInstance(
        id=instance_id,
        rule_id=definition.rule_id,
        category=definition.category,
        severity=definition.default_severity,
        entity_kind=entity_kind,
        entity_id=entity_id,
        modality=modality,
        target_fields=target_fields,
        profile=profile,
        defect_seed=defect_seed,
        truth_seed=truth_seed,
        remediation_availability=definition.remediation_availability,
        approval_policy=definition.approval_policy,
        approver_role=definition.approver_role,
        mutation_ids=[m.id for m in mutations],
        finding_id=finding_id,
        remediation_ids=[remediation_id],
    )
    finding = ExpectedFinding(
        id=finding_id,
        instance_id=instance_id,
        rule_id=definition.rule_id,
        category=definition.category,
        severity=definition.default_severity,
        entity_kind=entity_kind,
        entity_id=entity_id,
        title=definition.title,
        description=definition.description,
        observable_evidence=definition.expected_evidence,
        expected_message_semantics=definition.expected_finding.format(id=entity_id),
        detection_locator=f"{primary_shard}:{entity_id}",
        remediation_available=definition.remediation_availability,
        non_remediable_reason=definition.non_remediable_reason,
        remediation_id=remediation_id,
        match_fields={
            "rule_id": definition.rule_id,
            "category": definition.category.value,
            "severity": definition.default_severity.value,
            "entity_id": entity_id,
            "entity_kind": entity_kind,
            "target_fields": target_fields,
            "remediation_available": definition.remediation_availability.value,
            "approval_policy": definition.approval_policy.value,
        },
    )
    # A non-remediable finding still gets exactly one record, but it is an
    # explicit *no-action decision* rather than a hollow fix: no action string,
    # no recommended value, and a stated reason. An agent that proposes a repair
    # here is wrong; one that abstains is right.
    remediable = definition.is_remediable
    remediation = ExpectedRemediation(
        id=remediation_id,
        finding_id=finding_id,
        instance_id=instance_id,
        rule_id=definition.rule_id,
        action=definition.remediation_action if remediable else NO_REMEDIATION_ACTION,
        action_class=definition.action_class,
        target=f"{primary_shard}/{entity_id}",
        recommended_value=definition.remediation_recommended if remediable else None,
        # The truth reference is retained even when nothing can be remediated:
        # it is the scoring ground truth, not a repair instruction.
        truth_reference={(c.field or c.shard): c.before for c in changes},
        availability=definition.remediation_availability,
        approval_policy=definition.approval_policy,
        approver_role=definition.approver_role,
        approval_evidence=definition.approval_evidence,
        non_remediable_reason=definition.non_remediable_reason,
        auto_fixable=definition.auto_fixable,
        requires_human_approval=definition.requires_human_approval,
        reversible=definition.reversible,
    )
    return instance, mutations, finding, remediation


def _observed_graph(meta: ObservedMeta, index: GraphIndex) -> dict[str, Any]:
    graph: dict[str, Any] = {"meta": meta.model_dump(mode="json")}
    for shard in SHARD_NAMES:
        records: list[JsonRecord] = sorted(index.working.get(shard, []), key=lambda r: r["id"])
        graph[shard] = records
    return graph


def _build_summary(
    meta: ObservedMeta,
    index: GraphIndex,
    controls: set[str],
    control_records: list[ControlRecord],
    instances: list[DefectInstance],
    mutations: list[MutationRecord],
    ledger: _Ledger,
) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    by_modality_group: dict[str, int] = {}
    by_entity_kind: dict[str, int] = {}
    by_contract_state: dict[str, int] = {}
    by_action_class: dict[str, int] = {}
    by_mutation_op: dict[str, int] = {}
    affected_entities: set[str] = set()
    for mutation in mutations:
        op = mutation.operation.value
        by_mutation_op[op] = by_mutation_op.get(op, 0) + 1
    for instance in instances:
        definition = DEFECTS[instance.rule_id]
        state = definition.contract_state
        by_contract_state[state] = by_contract_state.get(state, 0) + 1
        action = definition.action_class
        by_action_class[action] = by_action_class.get(action, 0) + 1
        by_category[instance.category.value] = by_category.get(instance.category.value, 0) + 1
        by_severity[instance.severity.value] = by_severity.get(instance.severity.value, 0) + 1
        by_rule[instance.rule_id] = by_rule.get(instance.rule_id, 0) + 1
        by_entity_kind[instance.entity_kind] = by_entity_kind.get(instance.entity_kind, 0) + 1
        group = modality_group_of(index, instance.entity_id)
        by_modality_group[group] = by_modality_group.get(group, 0) + 1
        affected_entities.add(instance.entity_id)
    affected_assets = {e for e in affected_entities if e in index.asset_shard}
    controls_by_reason: dict[str, int] = {}
    controls_by_entity_kind: dict[str, int] = {}
    for control in control_records:
        reason = control.reason.value
        controls_by_reason[reason] = controls_by_reason.get(reason, 0) + 1
        controls_by_entity_kind[control.entity_kind] = (
            controls_by_entity_kind.get(control.entity_kind, 0) + 1
        )
    return {
        "meta": meta.model_dump(mode="json"),
        "totals": {
            "defects": len(instances),
            "rules_defined": len(DEFECTS),
            "rules_fired": len(by_rule),
            "assets": len(index.asset_ids()),
            "control_assets": len(controls),
            "affected_assets": len(affected_assets),
            "affected_entities": len(affected_entities),
            "clean_assets": len(index.asset_ids()) - len(affected_assets),
            "control_records": len(control_records),
            "reserved_controls": sum(1 for c in control_records if c.reserved),
        },
        "by_control_reason": dict(sorted(controls_by_reason.items())),
        "by_control_entity_kind": dict(sorted(controls_by_entity_kind.items())),
        "skipped": {
            "precondition": ledger.skipped_precondition,
            "conflict": ledger.skipped_conflict,
            "incompatible": ledger.skipped_incompatible,
            "cap": ledger.skipped_cap,
        },
        "by_category": dict(sorted(by_category.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "by_rule": dict(sorted(by_rule.items())),
        "by_modality_group": dict(sorted(by_modality_group.items())),
        "by_entity_kind": dict(sorted(by_entity_kind.items())),
        # Contract coverage as structured data, so a gap is visible rather than
        # assumed. ``by_contract_state`` counts what this profile actually fired;
        # ``contract_state_coverage`` records which rules the catalogue declares
        # for each state, including states this profile did not reach.
        "by_contract_state": dict(sorted(by_contract_state.items())),
        "by_action_class": dict(sorted(by_action_class.items())),
        "by_mutation_op": dict(sorted(by_mutation_op.items())),
        "contract_state_coverage": {
            state: len(rule_ids) for state, rule_ids in contract_coverage().items()
        },
        "uncovered_contract_states": [
            state for state in REQUIRED_CONTRACT_STATES if not by_contract_state.get(state)
        ],
    }


def modality_group_of(index: GraphIndex, entity_id: str) -> str:
    """Return the modality group of an affected entity (via its dataset for files)."""
    shard = _primary_shard(index, entity_id)
    record = index.truth_record(shard, entity_id)
    if record is None:
        return "unknown"
    if shard == "files":
        dataset = index.truth_record("datasets", str(record.get("dataset_id", "")))
        return str(dataset.get("modality_group", "unknown")) if dataset else "unknown"
    return str(record.get("modality_group", "unknown"))


def _require_non_empty_intersection(
    difficulty: Difficulty,
    profile: ObservedProfile,
    control_fraction: float,
    rule_scopes: list[RuleScopeRecord],
) -> None:
    """Fail loudly when a tier and a profile leave no rule anything to draw from.

    A benchmark with an empty universe is not a hard benchmark, it is a broken
    one: every agent scores identically on it and the report looks like a result.
    The check runs only when a tier was explicitly requested, so the default path
    keeps its previous behaviour — including profiles such as ``gold`` that
    legitimately inject nothing across the *whole* catalogue.
    """
    if any(scope.eligible_count for scope in rule_scopes):
        return
    raise ObservedConfigError(
        f"difficulty {difficulty.value!r} and profile {profile.value!r} have an empty "
        f"intersection: none of the {len(rule_scopes)} {difficulty.value} rule(s) has an "
        f"eligible entity (the profile reserves {control_fraction:.0%} of assets as "
        f"controls), so no defect could be injected; choose another profile or tier "
        f"rather than publishing a benchmark nothing can be scored against"
    )


def _rules_for_run(difficulty: Difficulty | None, plan: ScenarioPlan | None) -> list[DefectDef]:
    """Return the definitions this run may draw from, in the fixed apply order.

    ``None`` means the whole catalogue — the pre-existing behaviour, reproduced
    exactly, including the order. A rule-filtered tier restricts *which* rules may
    fire and nothing else: the per-rule selection RNG is keyed by rule id, so a
    rule draws the same candidates whichever run it takes part in.

    The adversarial tier is not a filter over this table at all: its rules are
    whichever ones its scenario classes construct with, and they are applied in
    the same fixed catalogue order so the apply sequence stays a property of the
    registry rather than of the scenario list.
    """
    definitions = defects_in_order()
    if difficulty is None:
        return definitions
    permitted = set(plan.scoped_rule_ids) if plan is not None else set(selectable_rules(difficulty))
    return [d for d in definitions if d.rule_id in permitted]


def generate_observed(
    graph: TruthGraph,
    config: CanonicalConfig,
    profile: ObservedProfile,
    defect_seed: int,
    difficulty: Difficulty | None = None,
) -> ObservedResult:
    """Derive the observed state and full defect ledger deterministically.

    ``difficulty`` restricts generation to the rules at one benchmark tier —
    *reasoning complexity*, independent of ``profile``, which controls how many
    defects are injected. ``None`` is the full catalogue and is byte-for-byte the
    behaviour this argument did not exist for.

    :attr:`Difficulty.ADVERSARIAL` is different in kind: it is not a filter but a
    switch to the scenario engine, which names its own targets explicitly, dresses
    reserved controls into near misses, and scopes every rule's population to the
    constructed neighbourhood rather than to the whole estate.
    """
    index = GraphIndex(graph, config)
    spec = profile_spec(profile)
    adversarial = difficulty is Difficulty.ADVERSARIAL
    meta = ObservedMeta(
        generator_version=OBSERVED_GENERATOR_VERSION,
        schema_version=OBSERVED_SCHEMA_VERSION,
        defect_seed=defect_seed,
        profile=profile.value,
        truth_generator_version=graph.meta.generator_version,
        truth_seed=graph.meta.seed,
        epoch_anchor=graph.meta.epoch_anchor,
    )
    controls = _controls(index, spec.control_fraction, defect_seed, profile.value)

    # Planned before anything is applied, so the construction is a pure function
    # of the truth graph, the reserved partition and the seed — never of the order
    # in which defects happened to land.
    plan = plan_scenarios(index, controls, defect_seed=defect_seed) if adversarial else None
    universe = plan.universe if plan is not None else None

    ledger = _Ledger()
    instances: list[DefectInstance] = []
    mutations: list[MutationRecord] = []
    findings: list[ExpectedFinding] = []
    remediations: list[ExpectedRemediation] = []

    eligible_rule_count: dict[str, int] = {}
    rule_scopes: list[RuleScopeRecord] = []

    for definition in _rules_for_run(difficulty, plan):
        population = definition.population(index)
        if universe is not None:
            # The adversarial evaluation universe is the constructed
            # neighbourhood, not the estate. Widening it here would hand every
            # agent thousands of true negatives it never had to reason about.
            population = [e for e in population if e in universe]
        excluded = [e for e in population if _is_control(index, controls, e)]
        eligible = [e for e in population if not _is_control(index, controls, e)]
        for entity_id in eligible:
            eligible_rule_count[entity_id] = eligible_rule_count.get(entity_id, 0) + 1

        candidates: list[str] = []
        if plan is not None:
            # Explicit, named targets — the scenario decides, not a rate. The
            # rate is then *derived* for the ledger so a reader can still see how
            # much of the population was drawn.
            candidates = sorted(set(plan.selection.get(definition.rule_id, [])) & set(eligible))
            rate = len(candidates) / len(eligible) if eligible else 0.0
        else:
            rate = spec.rate_for(definition.category, definition.rule_id)
            k = round(rate * len(eligible))
            if k > 0:
                shuffled = list(eligible)
                sub_rng(defect_seed, "select", profile.value, definition.rule_id).shuffle(shuffled)
                candidates = sorted(shuffled[:k])

        applied_ids: list[str] = []
        for entity_id in candidates:
            if ledger.applied_total >= spec.global_cap:
                break
            applied_here = ledger.applied_rules.setdefault(entity_id, set())
            if _INCOMPATIBLE[definition.rule_id] & applied_here:
                ledger.skipped_incompatible += 1
                continue
            if ledger.per_entity_count.get(entity_id, 0) >= spec.max_per_entity:
                ledger.skipped_cap += 1
                continue
            changes = definition.mutate(MutationContext(index=index, entity_id=entity_id))
            if not changes:
                ledger.skipped_precondition += 1
                continue
            if _has_conflict(ledger, changes):
                ledger.skipped_conflict += 1
                continue

            _apply(index, ledger, changes)
            rationale = (
                (
                    f"constructed as an adversarial scenario target under profile "
                    f"'{profile.value}' for rule {definition.rule_id} (category "
                    f"'{definition.category.value}', {len(eligible)} eligible "
                    f"non-control entities in the scenario universe)"
                )
                if plan is not None
                else (
                    f"selected under profile '{profile.value}' for rule "
                    f"{definition.rule_id} (category '{definition.category.value}', "
                    f"rate {rate:.3f}, {len(eligible)} eligible non-control entities)"
                )
            )
            instance, muts, finding, remediation = _emit(
                definition,
                index,
                entity_id,
                changes,
                profile.value,
                defect_seed,
                meta.truth_seed,
                rationale,
            )
            instances.append(instance)
            mutations.extend(muts)
            findings.append(finding)
            remediations.append(remediation)

            applied_here.add(definition.rule_id)
            ledger.per_entity_count[entity_id] = ledger.per_entity_count.get(entity_id, 0) + 1
            ledger.applied_total += 1
            applied_ids.append(entity_id)

        rule_scopes.append(
            RuleScopeRecord(
                id=definition.rule_id,
                category=definition.category,
                severity=definition.default_severity,
                profile=profile.value,
                defect_seed=defect_seed,
                injection_rate=rate,
                population_count=len(population),
                control_excluded_count=len(excluded),
                eligible_count=len(eligible),
                candidate_count=len(candidates),
                selected_count=len(applied_ids),
                eligible_ids=sorted(eligible),
                control_excluded_ids=sorted(excluded),
                selected_ids=sorted(applied_ids),
            )
        )

    if difficulty is not None and not adversarial:
        _require_non_empty_intersection(difficulty, profile, spec.control_fraction, rule_scopes)

    scenarios: list[ScenarioCase] = []
    transformations: list[ScenarioTransformation] = []
    coverage: dict[str, Any] | None = None
    if plan is not None:
        scenarios, transformations = _construct_scenarios(
            index, plan, findings, meta, defect_seed=defect_seed, profile=profile.value
        )
        coverage = scenario_coverage(scenarios, transformations)
        problems = coverage_problems(coverage)
        if problems:
            raise ObservedConfigError(
                f"adversarial generation under profile {profile.value!r} is incomplete: "
                + "; ".join(problems)
            )

    control_records = _build_controls(
        index, controls, meta, spec.control_fraction, instances, mutations, eligible_rule_count
    )
    observed_graph = _observed_graph(meta, index)
    summary = _build_summary(meta, index, controls, control_records, instances, mutations, ledger)
    # Added only for an adversarial run, so no default-run byte moves.
    if coverage is not None:
        summary["scenarios"] = coverage
    return ObservedResult(
        meta=meta,
        observed_graph=observed_graph,
        instances=instances,
        mutations=mutations,
        findings=findings,
        remediations=remediations,
        controls=control_records,
        rule_scopes=rule_scopes,
        summary=summary,
        scenarios=scenarios,
        transformations=transformations,
        difficulty=difficulty,
    )


def _construct_scenarios(
    index: GraphIndex,
    plan: ScenarioPlan,
    findings: list[ExpectedFinding],
    meta: ObservedMeta,
    *,
    defect_seed: int,
    profile: str,
) -> tuple[list[ScenarioCase], list[ScenarioTransformation]]:
    """Apply the planned near misses and build the case ledger from what landed.

    Near-miss edits are applied *after* every defect, straight onto the working
    graph, and are recorded only as :class:`ScenarioTransformation` records. They
    never enter the defect ledger, never anchor a :class:`DefectInstance`, and
    never lock a mutation path, because they are not defects — the entities they
    touch are reserved controls and stay in the negative class.
    """
    near_miss_cases, transformations = build_near_miss_cases(
        plan.near_misses,
        profile=profile,
        defect_seed=defect_seed,
        truth_seed=meta.truth_seed,
    )
    for record in transformations:
        index.set_working_field(record.shard, record.entity_id, record.field, record.after)

    findings_by_pair = {(f.entity_id, f.rule_id): f.id for f in findings}
    positive_cases = build_positive_cases(
        plan,
        index,
        findings_by_pair,
        near_miss_ids_by_mimicked_rule(plan.near_misses),
        profile=profile,
        defect_seed=defect_seed,
        truth_seed=meta.truth_seed,
    )
    return sorted(near_miss_cases + positive_cases, key=lambda case: case.id), transformations


__all__ = [
    "ADVERSARIAL_MIN_SCHEMA_VERSION",
    "OBSERVED_GENERATOR_VERSION",
    "OBSERVED_SCHEMA_VERSION",
    "SUPPORTED_OBSERVED_SCHEMA_VERSIONS",
    "ObservedResult",
    "generate_observed",
    "modality_group_of",
]
