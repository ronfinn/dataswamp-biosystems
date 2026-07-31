"""The deterministic imperfection engine.

Given a truth graph, the canonical config, a profile, and a defect seed, this
derives an observed graph plus the four ledgers (defect instances, mutations,
expected findings, expected remediations). It never mutates the truth graph: all
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
    DefectDef,
    FieldChange,
    MutationContext,
    defects_in_order,
)
from dataswamp_biosystems.observed.entities import (
    ChangeOp,
    DefectInstance,
    ExpectedFinding,
    ExpectedRemediation,
    MutationRecord,
    ObservedMeta,
)
from dataswamp_biosystems.observed.index import SHARD_NAMES, GraphIndex, JsonRecord
from dataswamp_biosystems.observed.profiles import ObservedProfile, profile_spec
from dataswamp_biosystems.truth import ids
from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.rng import sub_rng

OBSERVED_GENERATOR_VERSION = "1.0.0"
OBSERVED_SCHEMA_VERSION = 1


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
    """The full output of one engine run: observed graph plus the four ledgers."""

    meta: ObservedMeta
    observed_graph: dict[str, Any]
    instances: list[DefectInstance]
    mutations: list[MutationRecord]
    findings: list[ExpectedFinding]
    remediations: list[ExpectedRemediation]
    summary: dict[str, Any]


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
        remediation_id=remediation_id,
        match_fields={
            "rule_id": definition.rule_id,
            "category": definition.category.value,
            "severity": definition.default_severity.value,
            "entity_id": entity_id,
            "entity_kind": entity_kind,
            "target_fields": target_fields,
        },
    )
    remediation = ExpectedRemediation(
        id=remediation_id,
        finding_id=finding_id,
        instance_id=instance_id,
        rule_id=definition.rule_id,
        action=definition.remediation_action,
        target=f"{primary_shard}/{entity_id}",
        recommended_value=definition.remediation_recommended,
        truth_reference={(c.field or c.shard): c.before for c in changes},
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
    instances: list[DefectInstance],
    ledger: _Ledger,
) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    by_modality_group: dict[str, int] = {}
    by_entity_kind: dict[str, int] = {}
    affected_entities: set[str] = set()
    for instance in instances:
        by_category[instance.category.value] = by_category.get(instance.category.value, 0) + 1
        by_severity[instance.severity.value] = by_severity.get(instance.severity.value, 0) + 1
        by_rule[instance.rule_id] = by_rule.get(instance.rule_id, 0) + 1
        by_entity_kind[instance.entity_kind] = by_entity_kind.get(instance.entity_kind, 0) + 1
        group = _modality_group_of(index, instance.entity_id)
        by_modality_group[group] = by_modality_group.get(group, 0) + 1
        affected_entities.add(instance.entity_id)
    affected_assets = {e for e in affected_entities if e in index.asset_shard}
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
        },
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
    }


def _modality_group_of(index: GraphIndex, entity_id: str) -> str:
    """Return the modality group of an affected entity (via its dataset for files)."""
    shard = _primary_shard(index, entity_id)
    record = index.truth_record(shard, entity_id)
    if record is None:
        return "unknown"
    if shard == "files":
        dataset = index.truth_record("datasets", str(record.get("dataset_id", "")))
        return str(dataset.get("modality_group", "unknown")) if dataset else "unknown"
    return str(record.get("modality_group", "unknown"))


def generate_observed(
    graph: TruthGraph,
    config: CanonicalConfig,
    profile: ObservedProfile,
    defect_seed: int,
) -> ObservedResult:
    """Derive the observed state and full defect ledger deterministically."""
    index = GraphIndex(graph, config)
    spec = profile_spec(profile)
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

    ledger = _Ledger()
    instances: list[DefectInstance] = []
    mutations: list[MutationRecord] = []
    findings: list[ExpectedFinding] = []
    remediations: list[ExpectedRemediation] = []

    for definition in defects_in_order():
        if ledger.applied_total >= spec.global_cap:
            break
        rate = spec.rate_for(definition.category, definition.rule_id)
        eligible = [e for e in definition.population(index) if not _is_control(index, controls, e)]
        k = round(rate * len(eligible))
        if k <= 0:
            continue
        shuffled = list(eligible)
        sub_rng(defect_seed, "select", profile.value, definition.rule_id).shuffle(shuffled)
        selected = sorted(shuffled[:k])

        for entity_id in selected:
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
                f"selected under profile '{profile.value}' for rule "
                f"{definition.rule_id} (category '{definition.category.value}', "
                f"rate {rate:.3f}, {len(eligible)} eligible non-control entities)"
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

    observed_graph = _observed_graph(meta, index)
    summary = _build_summary(meta, index, controls, instances, ledger)
    return ObservedResult(
        meta=meta,
        observed_graph=observed_graph,
        instances=instances,
        mutations=mutations,
        findings=findings,
        remediations=remediations,
        summary=summary,
    )


__all__ = [
    "OBSERVED_GENERATOR_VERSION",
    "OBSERVED_SCHEMA_VERSION",
    "ObservedResult",
    "generate_observed",
]
