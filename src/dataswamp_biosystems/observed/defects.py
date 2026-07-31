"""The defect-definition registry: the catalogue of injectable imperfections.

Each defect type is a :class:`DefectDef` pairing stable metadata (rule id,
severity, applicability, remediation semantics, compatibility) with two callables:
``population`` (the sorted primary entities a rule *could* apply to, derived from
the truth graph) and ``mutate`` (which proposes the field-level changes for one
entity, or returns ``None`` when a precondition is unmet). Mutations are proposed,
not applied: the engine checks conflicts, then applies and logs them, so nothing
here mutates a canonical instance or the truth graph.

All values are fictional; no real vendors, people, or datasets appear.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dataswamp_biosystems.observed.entities import (
    Category,
    ChangeOp,
    Multiplicity,
    Severity,
)
from dataswamp_biosystems.observed.index import GraphIndex, JsonRecord
from dataswamp_biosystems.truth import ids

# A timestamp far before the epoch anchor (2024-01-08), used for staleness defects.
_FAR_PAST = "2021-01-04T00:00:00Z"
# A plausible-looking but deliberately unresolved owner reference.
_GHOST_OWNER = "person-unassigned"
_GHOST_RUN = "prun-unresolved-provenance"
_RESTRICTED = {"restricted", "highly-restricted"}


@dataclass(frozen=True)
class FieldChange:
    """One proposed change to the observed working graph (applied by the engine)."""

    shard: str
    entity_kind: str
    entity_id: str
    op: ChangeOp
    path: str
    field: str
    before: Any
    after: Any
    reversible: bool


@dataclass(frozen=True)
class MutationContext:
    """Everything a mutation needs: the graph index and the target entity."""

    index: GraphIndex
    entity_id: str


Population = Callable[[GraphIndex], list[str]]
Mutate = Callable[[MutationContext], list[FieldChange] | None]


@dataclass(frozen=True)
class DefectDef:
    """A single defect type: metadata plus its population and mutation callables."""

    rule_id: str
    title: str
    description: str
    category: Category
    default_severity: Severity
    applies_to_kinds: list[str]
    applies_to_modalities: list[str]
    prerequisites: str
    operation: str
    expected_evidence: str
    expected_finding: str
    remediation_action: str
    remediation_recommended: Any
    auto_fixable: bool
    requires_human_approval: bool
    reversible: bool
    # False when the defect exists only in the observed graph (metadata-only);
    # True would mean a physically-manifested defect on a separate observed file
    # tree. Every rule this milestone is metadata-only.
    physically_manifested: bool
    incompatibilities: list[str]
    multiplicity: Multiplicity
    validation_rules: list[str]
    population: Population
    mutate: Mutate

    @property
    def manifestation(self) -> str:
        return "physical" if self.physically_manifested else "metadata"


# ---------------------------------------------------------------------------
# Small helpers shared by mutation functions.
# ---------------------------------------------------------------------------


def _set(
    shard: str,
    kind: str,
    entity_id: str,
    field_name: str,
    before: Any,
    after: Any,
    *,
    reversible: bool = True,
    is_list: bool = False,
) -> FieldChange:
    return FieldChange(
        shard=shard,
        entity_kind=kind,
        entity_id=entity_id,
        op=ChangeOp.SET_LIST if is_list else ChangeOp.SET,
        path=f"/{field_name}",
        field=field_name,
        before=before,
        after=after,
        reversible=reversible,
    )


def _delete(shard: str, kind: str, entity_id: str, record: JsonRecord) -> FieldChange:
    return FieldChange(
        shard=shard,
        entity_kind=kind,
        entity_id=entity_id,
        op=ChangeOp.DELETE_RECORD,
        path="",
        field="",
        before=record,
        after=None,
        reversible=True,
    )


def _add(shard: str, kind: str, record: JsonRecord) -> FieldChange:
    return FieldChange(
        shard=shard,
        entity_kind=kind,
        entity_id=record["id"],
        op=ChangeOp.ADD_RECORD,
        path="",
        field="",
        before=None,
        after=record,
        reversible=True,
    )


def _asset_kind(idx: GraphIndex, asset_id: str) -> str:
    return "data_product" if idx.asset_shard.get(asset_id) == "data_products" else "dataset"


def _all_assets(idx: GraphIndex) -> list[str]:
    return idx.asset_ids()


def _datasets(idx: GraphIndex) -> list[str]:
    return idx.dataset_ids()


def _datasets_in_groups(idx: GraphIndex, groups: set[str]) -> list[str]:
    return sorted(r["id"] for r in idx.truth["datasets"] if r.get("modality_group") in groups)


# ---------------------------------------------------------------------------
# Mutation functions, grouped by category.
# ---------------------------------------------------------------------------


def _clear_asset_field(field_name: str, empty: Any, *, is_list: bool) -> Mutate:
    def _fn(ctx: MutationContext) -> list[FieldChange] | None:
        aid = ctx.entity_id
        shard = ctx.index.asset_shard[aid]
        rec = ctx.index.truth_record(shard, aid)
        if rec is None or rec.get(field_name) in (empty, None):
            return None
        return [
            _set(
                shard,
                _asset_kind(ctx.index, aid),
                aid,
                field_name,
                rec[field_name],
                empty,
                is_list=is_list,
            )
        ]

    return _fn


def _set_asset_field(field_name: str, after: Any, reversible: bool = True) -> Mutate:
    def _fn(ctx: MutationContext) -> list[FieldChange] | None:
        aid = ctx.entity_id
        shard = ctx.index.asset_shard[aid]
        rec = ctx.index.truth_record(shard, aid)
        if rec is None or rec.get(field_name) == after:
            return None
        return [
            _set(
                shard,
                _asset_kind(ctx.index, aid),
                aid,
                field_name,
                rec[field_name],
                after,
                reversible=reversible,
            )
        ]

    return _fn


def _owner_change(new_owner: str, *, reversible: bool = True) -> Mutate:
    """Set both the denormalised asset owner and its governance record owner."""

    def _fn(ctx: MutationContext) -> list[FieldChange] | None:
        idx, aid = ctx.index, ctx.entity_id
        shard = idx.asset_shard[aid]
        rec = idx.truth_record(shard, aid)
        gov_id = idx.gov_by_asset.get(aid)
        if rec is None or gov_id is None:
            return None
        resolved = new_owner if new_owner != rec.get("owner_ref") else _GHOST_OWNER
        gov = idx.truth_record("governance_records", gov_id)
        changes = [
            _set(
                shard,
                _asset_kind(idx, aid),
                aid,
                "owner_ref",
                rec["owner_ref"],
                resolved,
                reversible=reversible,
            ),
        ]
        if gov is not None:
            changes.append(
                _set(
                    "governance_records",
                    "governance_record",
                    gov_id,
                    "owner_ref",
                    gov["owner_ref"],
                    resolved,
                    reversible=reversible,
                )
            )
        return changes

    return _fn


def _wrong_team(ctx: MutationContext) -> list[FieldChange] | None:
    idx, aid = ctx.index, ctx.entity_id
    shard = idx.asset_shard[aid]
    rec = idx.truth_record(shard, aid)
    if rec is None:
        return None
    current = rec.get("owner_ref")
    candidates = [t for t in sorted(idx.team_ids) if t != current]
    if not candidates:
        return None
    return _owner_change(candidates[0])(ctx)


def _steward_missing(ctx: MutationContext) -> list[FieldChange] | None:
    idx, aid = ctx.index, ctx.entity_id
    shard = idx.asset_shard[aid]
    rec = idx.truth_record(shard, aid)
    gov_id = idx.gov_by_asset.get(aid)
    if rec is None or gov_id is None or not rec.get("steward_refs"):
        return None
    gov = idx.truth_record("governance_records", gov_id)
    changes = [
        _set(
            shard, _asset_kind(idx, aid), aid, "steward_refs", rec["steward_refs"], [], is_list=True
        ),
    ]
    if gov is not None:
        changes.append(
            _set(
                "governance_records",
                "governance_record",
                gov_id,
                "steward_refs",
                gov["steward_refs"],
                [],
                is_list=True,
            )
        )
    return changes


def _denorm_owner_mismatch(ctx: MutationContext) -> list[FieldChange] | None:
    """Change only the denormalised asset owner, leaving the governance record."""
    idx, aid = ctx.index, ctx.entity_id
    shard = idx.asset_shard[aid]
    rec = idx.truth_record(shard, aid)
    if rec is None:
        return None
    current = rec.get("owner_ref")
    candidates = [t for t in sorted(idx.team_ids) if t != current]
    if not candidates:
        return None
    return [_set(shard, _asset_kind(idx, aid), aid, "owner_ref", rec["owner_ref"], candidates[0])]


def _stale_review(ctx: MutationContext) -> list[FieldChange] | None:
    gov_id = ctx.index.gov_by_asset.get(ctx.entity_id)
    if gov_id is None:
        return None
    gov = ctx.index.truth_record("governance_records", gov_id)
    if gov is None or gov.get("reviewed_at") == _FAR_PAST:
        return None
    return [
        _set(
            "governance_records",
            "governance_record",
            gov_id,
            "reviewed_at",
            gov["reviewed_at"],
            _FAR_PAST,
        )
    ]


def _restricted_as_internal(ctx: MutationContext) -> list[FieldChange] | None:
    return _set_asset_field("access_classification", "internal")(ctx)


def _mislabel_domain(ctx: MutationContext) -> list[FieldChange] | None:
    idx, aid = ctx.index, ctx.entity_id
    shard = idx.asset_shard[aid]
    rec = idx.truth_record(shard, aid)
    if rec is None:
        return None
    current = rec.get("scientific_domain")
    other = [d for d in idx.domain_ids if d != current]
    if not other:
        return None
    return [_set(shard, _asset_kind(idx, aid), aid, "scientific_domain", current, other[0])]


def _add_intended_use(use: str) -> Mutate:
    def _fn(ctx: MutationContext) -> list[FieldChange] | None:
        idx, aid = ctx.index, ctx.entity_id
        shard = idx.asset_shard[aid]
        rec = idx.truth_record(shard, aid)
        if rec is None:
            return None
        current = list(rec.get("intended_uses", []))
        if use in current:
            return None
        return [
            _set(
                shard,
                _asset_kind(idx, aid),
                aid,
                "intended_uses",
                current,
                sorted([*current, use]),
                is_list=True,
            )
        ]

    return _fn


def _modality_meta(transform: Callable[[dict[str, Any]], dict[str, Any] | None]) -> Mutate:
    def _fn(ctx: MutationContext) -> list[FieldChange] | None:
        rec = ctx.index.dataset(ctx.entity_id)
        if rec is None:
            return None
        current = dict(rec.get("modality_metadata", {}))
        after = transform(dict(current))
        if after is None or after == current:
            return None
        return [_set("datasets", "dataset", ctx.entity_id, "modality_metadata", current, after)]

    return _fn


def _drop_key(key: str) -> Callable[[dict[str, Any]], dict[str, Any] | None]:
    def _t(meta: dict[str, Any]) -> dict[str, Any] | None:
        if key not in meta:
            return None
        meta.pop(key)
        return meta

    return _t


def _add_key(key: str, value: Any) -> Callable[[dict[str, Any]], dict[str, Any] | None]:
    def _t(meta: dict[str, Any]) -> dict[str, Any] | None:
        meta[key] = value
        return meta

    return _t


def _dup_final_version(ctx: MutationContext) -> list[FieldChange] | None:
    """Give this dataset and a same-study/group sibling identical 'final' versions."""
    idx, did = ctx.index, ctx.entity_id
    rec = idx.dataset(did)
    if rec is None:
        return None
    siblings = sorted(
        r["id"]
        for r in idx.truth["datasets"]
        if r["id"] != did
        and r.get("study_id") == rec.get("study_id")
        and r.get("modality_group") == rec.get("modality_group")
    )
    if not siblings:
        return None
    sibling_id = siblings[0]
    sibling = idx.dataset(sibling_id)
    if sibling is None:
        return None
    final = "final"
    return [
        _set("datasets", "dataset", did, "version", rec["version"], final),
        _set("datasets", "dataset", sibling_id, "version", sibling["version"], final),
    ]


def _bad_path(ctx: MutationContext) -> list[FieldChange] | None:
    rec = ctx.index.truth_record("files", ctx.entity_id)
    if rec is None:
        return None
    original = str(rec.get("relative_path", ""))
    corrupted = original.upper().replace("/", " /")
    if corrupted == original:
        return None
    return [_set("files", "file", ctx.entity_id, "relative_path", original, corrupted)]


def _no_upstream(edge_type: str, groups: set[str] | None) -> Mutate:
    def _fn(ctx: MutationContext) -> list[FieldChange] | None:
        idx, did = ctx.index, ctx.entity_id
        rec = idx.dataset(did)
        if rec is None:
            return None
        if groups is not None and rec.get("modality_group") not in groups:
            return None
        edges = [e for e in idx.edges_into.get(did, []) if e.get("edge_type") == edge_type]
        if not edges:
            return None
        return [_delete("lineage", "lineage_edge", e["id"], e) for e in edges]

    return _fn


def _no_slide_source(ctx: MutationContext) -> list[FieldChange] | None:
    """Remove the produced-edges feeding a pathology dataset's files (lost provenance)."""
    idx, did = ctx.index, ctx.entity_id
    rec = idx.dataset(did)
    if rec is None or rec.get("modality_group") != "digital-pathology":
        return None
    file_ids = set(rec.get("file_ids", []))
    edges = [
        e
        for e in idx.truth["lineage"]
        if e.get("edge_type") == "produced" and e.get("downstream_id") in file_ids
    ]
    if not edges:
        return None
    return [
        _delete("lineage", "lineage_edge", e["id"], e) for e in sorted(edges, key=lambda e: e["id"])
    ]


def _vcf_index_missing(ctx: MutationContext) -> list[FieldChange] | None:
    idx, did = ctx.index, ctx.entity_id
    rec = idx.dataset(did)
    if rec is None or rec.get("modality_group") != "wgs-wes":
        return None
    file_ids = list(rec.get("file_ids", []))
    if len(file_ids) < 2:
        return None
    index_file = sorted(file_ids)[-1]
    file_rec = idx.truth_record("files", index_file)
    if file_rec is None:
        return None
    remaining = [f for f in file_ids if f != index_file]
    return [
        _set("datasets", "dataset", did, "file_ids", file_ids, remaining, is_list=True),
        _delete("files", "file", index_file, file_rec),
    ]


def _cross_study_edge(ctx: MutationContext) -> list[FieldChange] | None:
    idx, did = ctx.index, ctx.entity_id
    rec = idx.dataset(did)
    if rec is None:
        return None
    study = rec.get("study_id")
    partner = next(
        (r["id"] for r in idx.truth["datasets"] if r.get("study_id") != study),
        None,
    )
    if partner is None:
        return None
    edge = {
        "id": ids.join("edge", "xstudy", ids.stable_suffix(did, partner, digest_size=6)),
        "upstream_id": partner,
        "downstream_id": did,
        "edge_type": "derived_from",
        "synthetic": True,
    }
    return [_add("lineage", "lineage_edge", edge)]


def _provenance_dangling(ctx: MutationContext) -> list[FieldChange] | None:
    return _set_asset_field("provenance_run_id", _GHOST_RUN)(ctx)


def _contract_missing(ctx: MutationContext) -> list[FieldChange] | None:
    contract_id = ctx.index.contract_by_asset.get(ctx.entity_id)
    if contract_id is None:
        return None
    rec = ctx.index.truth_record("contracts", contract_id)
    if rec is None:
        return None
    return [_delete("contracts", "contract", contract_id, rec)]


def _record_count_zero(ctx: MutationContext) -> list[FieldChange] | None:
    rec = ctx.index.dataset(ctx.entity_id)
    if rec is None or rec.get("record_count") == 0:
        return None
    return [_set("datasets", "dataset", ctx.entity_id, "record_count", rec["record_count"], 0)]


def _size_inversion(ctx: MutationContext) -> list[FieldChange] | None:
    rec = ctx.index.dataset(ctx.entity_id)
    if rec is None:
        return None
    physical = int(rec.get("physical_bytes", 0))
    if physical < 1:
        return None
    return [
        _set(
            "datasets",
            "dataset",
            ctx.entity_id,
            "logical_bytes",
            rec["logical_bytes"],
            physical - 1,
        )
    ]


def _training_absent(ctx: MutationContext) -> list[FieldChange] | None:
    training_id = ctx.index.training_by_asset.get(ctx.entity_id)
    if training_id is None:
        return None
    rec = ctx.index.truth_record("training_approvals", training_id)
    if rec is None:
        return None
    return [_delete("training_approvals", "training_approval", training_id, rec)]


def _training_mismatch(ctx: MutationContext) -> list[FieldChange] | None:
    idx, aid = ctx.index, ctx.entity_id
    shard = idx.asset_shard[aid]
    rec = idx.truth_record(shard, aid)
    if rec is None:
        return None
    current = rec.get("model_training_status")
    after = (
        "model-training-not-approved"
        if current == "model-training-approved"
        else "model-training-approved"
    )
    return [_set(shard, _asset_kind(idx, aid), aid, "model_training_status", current, after)]


def _stale_asset(ctx: MutationContext) -> list[FieldChange] | None:
    idx, aid = ctx.index, ctx.entity_id
    gov_id = idx.gov_by_asset.get(aid)
    changes: list[FieldChange] = []
    if gov_id is not None:
        gov = idx.truth_record("governance_records", gov_id)
        if gov is not None and gov.get("reviewed_at") != _FAR_PAST:
            changes.append(
                _set(
                    "governance_records",
                    "governance_record",
                    gov_id,
                    "reviewed_at",
                    gov["reviewed_at"],
                    _FAR_PAST,
                )
            )
    for qc_id in sorted(idx.quality_by_asset.get(aid, []))[:1]:
        qc = idx.truth_record("quality_checks", qc_id)
        if qc is not None and qc.get("evaluated_at") != _FAR_PAST:
            changes.append(
                _set(
                    "quality_checks",
                    "quality_check",
                    qc_id,
                    "evaluated_at",
                    qc["evaluated_at"],
                    _FAR_PAST,
                )
            )
    return changes or None


def _stage_regression(ctx: MutationContext) -> list[FieldChange] | None:
    idx, did = ctx.index, ctx.entity_id
    rec = idx.dataset(did)
    if rec is None or rec.get("provenance_run_id") not in idx.pipeline_run_ids:
        return None
    if rec.get("lifecycle_stage") == "raw":
        return None
    return [_set("datasets", "dataset", did, "lifecycle_stage", rec["lifecycle_stage"], "raw")]


def _certified_contradicted(ctx: MutationContext) -> list[FieldChange] | None:
    idx, aid = ctx.index, ctx.entity_id
    qc_ids = sorted(idx.quality_by_asset.get(aid, []))
    if not qc_ids:
        return None
    qc_id = qc_ids[0]
    qc = idx.truth_record("quality_checks", qc_id)
    if qc is None:
        return None
    evidence = f"FAILED: {qc.get('check_type', 'check')} did not pass for {aid}"
    return [
        _set("quality_checks", "quality_check", qc_id, "status", qc.get("status"), "fail"),
        _set("quality_checks", "quality_check", qc_id, "evidence", qc.get("evidence"), evidence),
    ]


def _checksum_mismatch(ctx: MutationContext) -> list[FieldChange] | None:
    rec = ctx.index.truth_record("files", ctx.entity_id)
    if rec is None:
        return None
    corrupted = ids.stable_suffix(ctx.entity_id, "corrupt", digest_size=16)
    if corrupted == rec.get("checksum"):
        return None
    return [_set("files", "file", ctx.entity_id, "checksum", rec["checksum"], corrupted)]


def _file_missing(ctx: MutationContext) -> list[FieldChange] | None:
    rec = ctx.index.truth_record("files", ctx.entity_id)
    if rec is None or rec.get("present") is False:
        return None
    return [_set("files", "file", ctx.entity_id, "present", None, False)]


# ---------------------------------------------------------------------------
# Population helpers folding prerequisites in.
# ---------------------------------------------------------------------------


def _restricted_assets(idx: GraphIndex) -> list[str]:
    out = []
    for aid in idx.asset_ids():
        rec = idx.asset(aid)
        if rec is not None and rec.get("access_classification") in _RESTRICTED:
            out.append(aid)
    return sorted(out)


def _dup_group_reps(idx: GraphIndex) -> list[str]:
    """One representative dataset (smallest id) per study+group with ≥2 members."""
    groups: dict[tuple[str, str], list[str]] = {}
    for r in idx.truth["datasets"]:
        groups.setdefault((r.get("study_id", ""), r.get("modality_group", "")), []).append(r["id"])
    return sorted(min(members) for members in groups.values() if len(members) >= 2)


def _pipeline_datasets(idx: GraphIndex) -> list[str]:
    return sorted(
        r["id"]
        for r in idx.truth["datasets"]
        if r.get("provenance_run_id") in idx.pipeline_run_ids and r.get("lifecycle_stage") != "raw"
    )


def _stale_candidates(idx: GraphIndex) -> list[str]:
    stages = {"published", "analysis-ready"}
    return sorted(
        aid
        for aid in idx.asset_ids()
        if (rec := idx.asset(aid)) is not None and rec.get("lifecycle_stage") in stages
    )


def _big_datasets(idx: GraphIndex) -> list[str]:
    return sorted(r["id"] for r in idx.truth["datasets"] if int(r.get("physical_bytes", 0)) >= 1)


# ---------------------------------------------------------------------------
# The registry.
# ---------------------------------------------------------------------------


def _def(**kwargs: Any) -> DefectDef:
    kwargs.setdefault("incompatibilities", [])
    kwargs.setdefault("multiplicity", Multiplicity.PER_ENTITY)
    kwargs.setdefault("validation_rules", [])
    kwargs.setdefault("remediation_recommended", "restore-from-truth")
    kwargs.setdefault("physically_manifested", False)
    return DefectDef(**kwargs)


_DEFS: list[DefectDef] = [
    # 1. metadata completeness -------------------------------------------------
    _def(
        rule_id="META-TITLE-MISSING",
        title="Missing title",
        description="Catalogue asset has no title.",
        category=Category.METADATA_COMPLETENESS,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset title is non-empty",
        operation="clear_field:title",
        expected_evidence="title is an empty string",
        expected_finding="Asset {id} is missing a human-readable title.",
        remediation_action="restore_field:title",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["SEM-TITLE-UNINFORMATIVE"],
        population=_all_assets,
        mutate=_clear_asset_field("title", "", is_list=False),
    ),
    _def(
        rule_id="META-DESC-MISSING",
        title="Missing description",
        description="Catalogue asset has no description.",
        category=Category.METADATA_COMPLETENESS,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset description is non-empty",
        operation="clear_field:description",
        expected_evidence="description is an empty string",
        expected_finding="Asset {id} is missing a description.",
        remediation_action="restore_field:description",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["SEM-DESC-GENERIC"],
        population=_all_assets,
        mutate=_clear_asset_field("description", "", is_list=False),
    ),
    _def(
        rule_id="META-VERSION-MISSING",
        title="Missing version",
        description="Catalogue asset has no version string.",
        category=Category.METADATA_COMPLETENESS,
        default_severity=Severity.LOW,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset version is non-empty",
        operation="clear_field:version",
        expected_evidence="version is an empty string",
        expected_finding="Asset {id} is missing a version.",
        remediation_action="restore_field:version",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["NAM-VERSION-NONCANONICAL", "NAM-DUP-FINAL-VERSION"],
        population=_all_assets,
        mutate=_clear_asset_field("version", "", is_list=False),
    ),
    _def(
        rule_id="META-MODALITY-META-EMPTY",
        title="Empty modality metadata",
        description="Dataset has lost its modality-specific descriptive metadata.",
        category=Category.METADATA_COMPLETENESS,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["*"],
        prerequisites="dataset modality_metadata is non-empty",
        operation="set_field:modality_metadata={}",
        expected_evidence="modality_metadata is an empty object",
        expected_finding="Dataset {id} has no modality-specific metadata.",
        remediation_action="restore_field:modality_metadata",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=[
            "MOD-GENOME-BUILD-MISSING",
            "MOD-MIXED-GENE-IDS",
            "MOD-H5AD-NO-COUNTS-LAYER",
            "MOD-SPATIAL-COORDS-OOB",
        ],
        population=_datasets,
        mutate=_modality_meta(lambda meta: {} if meta else None),
    ),
    # 2. semantic metadata quality --------------------------------------------
    _def(
        rule_id="SEM-DESC-GENERIC",
        title="Generic description",
        description="Asset description is a meaningless placeholder.",
        category=Category.SEMANTIC_QUALITY,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset description differs from the placeholder",
        operation="set_field:description=placeholder",
        expected_evidence="description reads 'data' / 'TODO' with no substance",
        expected_finding="Asset {id} has a generic, uninformative description.",
        remediation_action="rewrite_field:description",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["META-DESC-MISSING"],
        population=_all_assets,
        mutate=_set_asset_field("description", "data"),
    ),
    _def(
        rule_id="SEM-TITLE-UNINFORMATIVE",
        title="Uninformative title",
        description="Asset title is a bare placeholder.",
        category=Category.SEMANTIC_QUALITY,
        default_severity=Severity.LOW,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset title differs from the placeholder",
        operation="set_field:title=dataset",
        expected_evidence="title reads 'dataset' with no specifics",
        expected_finding="Asset {id} has an uninformative title.",
        remediation_action="rewrite_field:title",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["META-TITLE-MISSING"],
        population=_all_assets,
        mutate=_set_asset_field("title", "dataset"),
    ),
    _def(
        rule_id="SEM-DOMAIN-MISLABELLED",
        title="Mislabelled scientific domain",
        description="Asset is tagged with a valid but incorrect scientific domain.",
        category=Category.SEMANTIC_QUALITY,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="another scientific domain term exists",
        operation="set_field:scientific_domain=other",
        expected_evidence="scientific_domain disagrees with the modality",
        expected_finding="Asset {id} is labelled with the wrong scientific domain.",
        remediation_action="correct_field:scientific_domain",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        population=_all_assets,
        mutate=_mislabel_domain,
    ),
    # 3. ownership & stewardship ----------------------------------------------
    _def(
        rule_id="OWN-OWNER-MISSING",
        title="Missing owner",
        description="Asset and its governance record have no owner.",
        category=Category.OWNERSHIP,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset has a governance record",
        operation="clear_owner",
        expected_evidence="owner_ref is empty on the asset and its governance record",
        expected_finding="Asset {id} has no assigned owner.",
        remediation_action="assign_owner",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=[
            "OWN-OWNER-WRONG-TEAM",
            "OWN-OWNER-DANGLING",
            "OWN-DENORM-MISMATCH",
        ],
        population=_all_assets,
        mutate=_owner_change(""),
    ),
    _def(
        rule_id="OWN-OWNER-WRONG-TEAM",
        title="Owner from the wrong team",
        description="Asset owner points at a team that does not own it.",
        category=Category.OWNERSHIP,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="a different team id exists",
        operation="reassign_owner:wrong-team",
        expected_evidence="owner_ref is a team unrelated to the asset's study/programme",
        expected_finding="Asset {id} is owned by the wrong team.",
        remediation_action="reassign_owner",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["OWN-OWNER-MISSING", "OWN-OWNER-DANGLING", "OWN-DENORM-MISMATCH"],
        population=_all_assets,
        mutate=_wrong_team,
    ),
    _def(
        rule_id="OWN-STEWARD-MISSING",
        title="Missing steward",
        description="Asset and its governance record have no stewards.",
        category=Category.OWNERSHIP,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset has stewards and a governance record",
        operation="clear_stewards",
        expected_evidence="steward_refs is empty on the asset and its governance record",
        expected_finding="Asset {id} has no assigned steward.",
        remediation_action="assign_steward",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        population=_all_assets,
        mutate=_steward_missing,
    ),
    _def(
        rule_id="OWN-OWNER-DANGLING",
        title="Dangling owner reference",
        description="Asset owner points at a person id that does not exist.",
        category=Category.OWNERSHIP,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset has a governance record",
        operation="reassign_owner:ghost",
        expected_evidence="owner_ref does not resolve to any team or person",
        expected_finding="Asset {id} references a non-existent owner.",
        remediation_action="assign_owner",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["OWN-OWNER-MISSING", "OWN-OWNER-WRONG-TEAM", "OWN-DENORM-MISMATCH"],
        population=_all_assets,
        mutate=_owner_change(_GHOST_OWNER),
    ),
    _def(
        rule_id="OWN-DENORM-MISMATCH",
        title="Owner denormalisation mismatch",
        description="Denormalised asset owner disagrees with its governance record.",
        category=Category.OWNERSHIP,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="a different team id exists",
        operation="set_field:owner_ref (asset only)",
        expected_evidence="asset owner_ref differs from governance-record owner_ref",
        expected_finding="Asset {id} owner disagrees with its governance record.",
        remediation_action="reconcile_owner",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["OWN-OWNER-MISSING", "OWN-OWNER-WRONG-TEAM", "OWN-OWNER-DANGLING"],
        population=_all_assets,
        mutate=_denorm_owner_mismatch,
    ),
    # 4. naming & versioning ---------------------------------------------------
    _def(
        rule_id="NAM-VERSION-NONCANONICAL",
        title="Non-canonical version",
        description="Asset version is a free-text label, not semantic.",
        category=Category.NAMING_VERSIONING,
        default_severity=Severity.LOW,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset version differs from the label",
        operation="set_field:version=final",
        expected_evidence="version reads 'final' / 'latest' rather than semver",
        expected_finding="Asset {id} uses a non-canonical version label.",
        remediation_action="normalise_version",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["META-VERSION-MISSING", "NAM-DUP-FINAL-VERSION"],
        population=_all_assets,
        mutate=_set_asset_field("version", "latest"),
    ),
    _def(
        rule_id="NAM-DUP-FINAL-VERSION",
        title="Duplicate final versions",
        description="Two sibling datasets share an identical 'final' version.",
        category=Category.NAMING_VERSIONING,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["*"],
        prerequisites="dataset has a same-study, same-group sibling",
        operation="set_field:version=final (pair)",
        expected_evidence="two datasets in one study/group share version 'final'",
        expected_finding="Datasets in {id}'s group have duplicate final versions.",
        remediation_action="disambiguate_versions",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["META-VERSION-MISSING", "NAM-VERSION-NONCANONICAL"],
        population=_dup_group_reps,
        mutate=_dup_final_version,
    ),
    _def(
        rule_id="NAM-PATH-CONVENTION",
        title="Path convention violation",
        description="File relative path violates the naming convention.",
        category=Category.NAMING_VERSIONING,
        default_severity=Severity.LOW,
        applies_to_kinds=["file"],
        applies_to_modalities=["*"],
        prerequisites="path contains lowercase/slash characters to corrupt",
        operation="set_field:relative_path=uppercased",
        expected_evidence="relative_path has spaces and uppercase segments",
        expected_finding="File {id} has a non-conforming path.",
        remediation_action="rename_path",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        population=lambda idx: idx.file_ids(),
        mutate=_bad_path,
    ),
    # 5. governance & classification ------------------------------------------
    _def(
        rule_id="GOV-CLASS-MISSING",
        title="Missing access classification",
        description="Asset has no access classification.",
        category=Category.GOVERNANCE_CLASSIFICATION,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset access_classification is non-empty",
        operation="clear_field:access_classification",
        expected_evidence="access_classification is an empty string",
        expected_finding="Asset {id} has no access classification.",
        remediation_action="classify_asset",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["GOV-RESTRICTED-AS-INTERNAL"],
        population=_all_assets,
        mutate=_clear_asset_field("access_classification", "", is_list=False),
    ),
    _def(
        rule_id="GOV-RESTRICTED-AS-INTERNAL",
        title="Restricted asset marked internal",
        description="A restricted asset is under-classified as internal.",
        category=Category.GOVERNANCE_CLASSIFICATION,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset access is restricted or highly-restricted",
        operation="set_field:access_classification=internal",
        expected_evidence="access_classification downgraded to internal",
        expected_finding="Restricted asset {id} is misclassified as internal.",
        remediation_action="reclassify_asset",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["GOV-CLASS-MISSING"],
        population=_restricted_assets,
        mutate=_restricted_as_internal,
    ),
    _def(
        rule_id="GOV-STALE-REVIEW",
        title="Stale governance review",
        description="Governance review date is far in the past.",
        category=Category.GOVERNANCE_CLASSIFICATION,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset has a governance record",
        operation="set_field:reviewed_at=far-past",
        expected_evidence="governance reviewed_at predates the estate by years",
        expected_finding="Asset {id} has a stale governance review.",
        remediation_action="schedule_review",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["LIF-STALE-ASSET"],
        population=_all_assets,
        mutate=_stale_review,
    ),
    _def(
        rule_id="GOV-RETENTION-MISSING",
        title="Missing retention class",
        description="Asset has no retention class.",
        category=Category.GOVERNANCE_CLASSIFICATION,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset retention_class is non-empty",
        operation="clear_field:retention_class",
        expected_evidence="retention_class is an empty string",
        expected_finding="Asset {id} has no retention class.",
        remediation_action="assign_retention",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        population=_all_assets,
        mutate=_clear_asset_field("retention_class", "", is_list=False),
    ),
    # 6. licensing & intended use ---------------------------------------------
    _def(
        rule_id="USE-INTENDED-USE-MISSING",
        title="Missing intended use",
        description="Asset declares no intended uses.",
        category=Category.LICENSING_INTENDED_USE,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset intended_uses is non-empty",
        operation="clear_field:intended_uses",
        expected_evidence="intended_uses is an empty list",
        expected_finding="Asset {id} declares no intended use.",
        remediation_action="declare_intended_use",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["USE-TRAINING-WITHOUT-APPROVAL", "USE-EXTERNAL-VS-RESTRICTED"],
        population=_all_assets,
        mutate=_clear_asset_field("intended_uses", [], is_list=True),
    ),
    _def(
        rule_id="USE-TRAINING-WITHOUT-APPROVAL",
        title="Training use without approval",
        description="Asset lists model-training use without an approval.",
        category=Category.LICENSING_INTENDED_USE,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset does not already list model-training use",
        operation="add_intended_use:model-training",
        expected_evidence="intended_uses includes model-training while status is unapproved",
        expected_finding="Asset {id} claims model-training use without approval.",
        remediation_action="review_training_use",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["USE-INTENDED-USE-MISSING"],
        population=_all_assets,
        mutate=_add_intended_use("model-training"),
    ),
    _def(
        rule_id="USE-EXTERNAL-VS-RESTRICTED",
        title="External sharing of restricted asset",
        description="A restricted asset lists external-sharing use.",
        category=Category.LICENSING_INTENDED_USE,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset is restricted and lacks external-sharing use",
        operation="add_intended_use:external-sharing",
        expected_evidence="intended_uses includes external-sharing on a restricted asset",
        expected_finding="Restricted asset {id} is marked for external sharing.",
        remediation_action="review_sharing_use",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["USE-INTENDED-USE-MISSING"],
        population=_restricted_assets,
        mutate=_add_intended_use("external-sharing"),
    ),
    # 7. lineage & provenance --------------------------------------------------
    _def(
        rule_id="LIN-DATASET-NO-UPSTREAM",
        title="Dataset without upstream lineage",
        description="Dataset has lost its incoming lineage edges.",
        category=Category.LINEAGE_PROVENANCE,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["*"],
        prerequisites="dataset has incoming derived_from edges",
        operation="remove_edges:derived_from",
        expected_evidence="dataset has no upstream lineage edge",
        expected_finding="Dataset {id} has no upstream lineage.",
        remediation_action="restore_lineage",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["LIN-VCF-INDEX-MISSING"],
        population=_datasets,
        mutate=_no_upstream("derived_from", None),
    ),
    _def(
        rule_id="LIN-CROSS-STUDY-EDGE",
        title="Lineage edge crossing studies",
        description="A fabricated lineage edge links datasets from different studies.",
        category=Category.LINEAGE_PROVENANCE,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["*"],
        prerequisites="a dataset in a different study exists",
        operation="add_edge:cross-study",
        expected_evidence="an upstream edge originates in a different study",
        expected_finding="Dataset {id} has an implausible cross-study lineage edge.",
        remediation_action="remove_edge",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        population=_datasets,
        mutate=_cross_study_edge,
    ),
    _def(
        rule_id="LIN-PROVENANCE-DANGLING",
        title="Dangling provenance run",
        description="Dataset provenance run id does not resolve.",
        category=Category.LINEAGE_PROVENANCE,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["*"],
        prerequisites="dataset has a provenance run id",
        operation="set_field:provenance_run_id=ghost",
        expected_evidence="provenance_run_id references a non-existent run",
        expected_finding="Dataset {id} points at a non-existent provenance run.",
        remediation_action="repair_provenance",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        population=_datasets,
        mutate=_provenance_dangling,
    ),
    _def(
        rule_id="LIN-VCF-INDEX-MISSING",
        title="Missing VCF index relationship",
        description="A WGS/WES dataset lost one file and its lineage link.",
        category=Category.LINEAGE_PROVENANCE,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["wgs-wes"],
        prerequisites="wgs-wes dataset has at least two files",
        operation="drop_file+link",
        expected_evidence="a referenced index file is absent from the dataset",
        expected_finding="Dataset {id} is missing its VCF index relationship.",
        remediation_action="restore_index_file",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["LIN-DATASET-NO-UPSTREAM"],
        population=lambda idx: _datasets_in_groups(idx, {"wgs-wes"}),
        mutate=_vcf_index_missing,
    ),
    _def(
        rule_id="LIN-PATH-NO-SLIDE-SOURCE",
        title="Pathology feature table without source-slide lineage",
        description="A digital-pathology dataset's files lost their producing-run lineage.",
        category=Category.LINEAGE_PROVENANCE,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["digital-pathology"],
        prerequisites="pathology dataset has produced edges into its files",
        operation="remove_edges:produced",
        expected_evidence="dataset files have no producing-run lineage (no source slide)",
        expected_finding="Pathology dataset {id} has no source-slide lineage.",
        remediation_action="restore_lineage",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        population=lambda idx: _datasets_in_groups(idx, {"digital-pathology"}),
        mutate=_no_slide_source,
    ),
    # 8. schema & structural quality ------------------------------------------
    _def(
        rule_id="SCH-CONTRACT-MISSING",
        title="Missing data contract",
        description="Asset's data contract record is absent.",
        category=Category.SCHEMA_STRUCTURAL,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset has a contract record",
        operation="delete_record:contract",
        expected_evidence="contract_ref resolves to no contract record",
        expected_finding="Asset {id} has no data contract.",
        remediation_action="author_contract",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        population=_all_assets,
        mutate=_contract_missing,
    ),
    _def(
        rule_id="SCH-RECORD-COUNT-ZERO",
        title="Zero record count",
        description="Dataset reports zero records despite having files.",
        category=Category.SCHEMA_STRUCTURAL,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["*"],
        prerequisites="dataset record_count is non-zero",
        operation="set_field:record_count=0",
        expected_evidence="record_count is 0 while files are present",
        expected_finding="Dataset {id} reports zero records.",
        remediation_action="recompute_record_count",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        population=_datasets,
        mutate=_record_count_zero,
    ),
    _def(
        rule_id="SCH-SIZE-INVERSION",
        title="Inverted logical/physical size",
        description="Logical bytes are smaller than physical bytes.",
        category=Category.SCHEMA_STRUCTURAL,
        default_severity=Severity.LOW,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["*"],
        prerequisites="dataset physical_bytes >= 1",
        operation="set_field:logical_bytes=physical-1",
        expected_evidence="logical_bytes < physical_bytes",
        expected_finding="Dataset {id} has an impossible size inversion.",
        remediation_action="recompute_sizes",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        population=_big_datasets,
        mutate=_size_inversion,
    ),
    # 9. modality-specific scientific metadata --------------------------------
    _def(
        rule_id="MOD-GENOME-BUILD-MISSING",
        title="Missing genome build",
        description="A WGS/WES dataset omits its reference genome build.",
        category=Category.MODALITY_SCIENTIFIC,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["wgs-wes"],
        prerequisites="dataset metadata declares reference_build",
        operation="drop_meta_key:reference_build",
        expected_evidence="modality_metadata has no reference_build",
        expected_finding="Dataset {id} does not declare a genome build.",
        remediation_action="declare_genome_build",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["META-MODALITY-META-EMPTY"],
        population=lambda idx: _datasets_in_groups(idx, {"wgs-wes"}),
        mutate=_modality_meta(_drop_key("reference_build")),
    ),
    _def(
        rule_id="MOD-MIXED-GENE-IDS",
        title="Mixed gene identifier systems",
        description="Dataset declares conflicting gene identifier systems.",
        category=Category.MODALITY_SCIENTIFIC,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["scrna-seq", "functional-genomics"],
        prerequisites="dataset metadata lacks a single gene_id_system",
        operation="add_meta_key:gene_id_system=mixed",
        expected_evidence="gene_id_system reads 'mixed:ensembl+symbol'",
        expected_finding="Dataset {id} mixes gene identifier systems.",
        remediation_action="harmonise_gene_ids",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["META-MODALITY-META-EMPTY"],
        population=lambda idx: _datasets_in_groups(idx, {"scrna-seq", "functional-genomics"}),
        mutate=_modality_meta(_add_key("gene_id_system", "mixed:ensembl+symbol")),
    ),
    _def(
        rule_id="MOD-H5AD-NO-COUNTS-LAYER",
        title="H5AD missing declared counts layer",
        description="An scRNA-seq dataset declares its counts layer absent.",
        category=Category.MODALITY_SCIENTIFIC,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["scrna-seq"],
        prerequisites="dataset metadata does not already flag counts_layer",
        operation="add_meta_key:counts_layer=absent",
        expected_evidence="counts_layer is declared 'absent'",
        expected_finding="Dataset {id} has no declared counts layer.",
        remediation_action="declare_counts_layer",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["META-MODALITY-META-EMPTY"],
        population=lambda idx: _datasets_in_groups(idx, {"scrna-seq"}),
        mutate=_modality_meta(_add_key("counts_layer", "absent")),
    ),
    _def(
        rule_id="MOD-SPATIAL-COORDS-OOB",
        title="Spatial coordinates outside image bounds",
        description="A Visium-HD dataset declares coordinates beyond the capture area.",
        category=Category.MODALITY_SCIENTIFIC,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["visium-hd"],
        prerequisites="dataset metadata does not already flag max_coord_um",
        operation="add_meta_key:max_coord_um=oob",
        expected_evidence="max_coord_um exceeds the declared capture area",
        expected_finding="Dataset {id} has spatial coordinates outside the image bounds.",
        remediation_action="clip_coordinates",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["META-MODALITY-META-EMPTY"],
        population=lambda idx: _datasets_in_groups(idx, {"visium-hd"}),
        mutate=_modality_meta(_add_key("max_coord_um", 999999)),
    ),
    # 10. AI & model-training readiness ---------------------------------------
    _def(
        rule_id="AIR-TRAINING-APPROVAL-ABSENT",
        title="Model-training approval absent",
        description="Asset's model-training approval record is missing.",
        category=Category.AI_TRAINING_READINESS,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset has a training-approval record",
        operation="delete_record:training_approval",
        expected_evidence="no model-training approval backs the asset's status",
        expected_finding="Asset {id} has no model-training approval record.",
        remediation_action="record_training_decision",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["AIR-TRAINING-STATUS-MISMATCH"],
        population=_all_assets,
        mutate=_training_absent,
    ),
    _def(
        rule_id="AIR-TRAINING-STATUS-MISMATCH",
        title="Training status denormalisation mismatch",
        description="Denormalised training status disagrees with the approval record.",
        category=Category.AI_TRAINING_READINESS,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset has a model_training_status",
        operation="set_field:model_training_status",
        expected_evidence="asset training status differs from its approval record",
        expected_finding="Asset {id} training status disagrees with its approval.",
        remediation_action="reconcile_training_status",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["AIR-TRAINING-APPROVAL-ABSENT"],
        population=_all_assets,
        mutate=_training_mismatch,
    ),
    # 11. lifecycle & staleness -----------------------------------------------
    _def(
        rule_id="LIF-STALE-ASSET",
        title="Stale published asset",
        description="A published asset has stale governance and quality dates.",
        category=Category.LIFECYCLE_STALENESS,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset is published or analysis-ready",
        operation="set_field:reviewed_at+evaluated_at=far-past",
        expected_evidence="governance and quality dates predate the estate by years",
        expected_finding="Asset {id} is stale (old review and quality dates).",
        remediation_action="refresh_asset",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["GOV-STALE-REVIEW"],
        population=_stale_candidates,
        mutate=_stale_asset,
    ),
    _def(
        rule_id="LIF-STAGE-REGRESSION",
        title="Lifecycle stage regression",
        description="A pipeline-produced dataset is mislabelled as raw.",
        category=Category.LIFECYCLE_STALENESS,
        default_severity=Severity.MEDIUM,
        applies_to_kinds=["dataset"],
        applies_to_modalities=["*"],
        prerequisites="dataset was produced by a pipeline run",
        operation="set_field:lifecycle_stage=raw",
        expected_evidence="lifecycle_stage is raw despite pipeline provenance",
        expected_finding="Dataset {id} has an inconsistent lifecycle stage.",
        remediation_action="correct_lifecycle_stage",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        population=_pipeline_datasets,
        mutate=_stage_regression,
    ),
    _def(
        rule_id="QC-CERTIFIED-CONTRADICTED",
        title="Certified status contradicted by QC evidence",
        description="Asset stays 'pass' while a quality check reports failure.",
        category=Category.LIFECYCLE_STALENESS,
        default_severity=Severity.HIGH,
        applies_to_kinds=["dataset", "data_product"],
        applies_to_modalities=["*"],
        prerequisites="asset has at least one quality check",
        operation="set_field:quality_check.status=fail",
        expected_evidence="a quality check fails while the asset remains passing",
        expected_finding="Asset {id}'s passing status is contradicted by QC evidence.",
        remediation_action="reconcile_quality_status",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        population=_all_assets,
        mutate=_certified_contradicted,
    ),
    # 12. physical file integrity (observed-graph only) -----------------------
    _def(
        rule_id="FILE-CHECKSUM-MISMATCH",
        title="Checksum mismatch",
        description="A file's recorded checksum no longer matches its truth digest.",
        category=Category.FILE_INTEGRITY,
        default_severity=Severity.HIGH,
        applies_to_kinds=["file"],
        applies_to_modalities=["*"],
        prerequisites="file has a checksum",
        operation="set_field:checksum=corrupted",
        expected_evidence="observed checksum differs from the truth checksum",
        expected_finding="File {id} has a mismatched checksum.",
        remediation_action="reverify_checksum",
        auto_fixable=True,
        requires_human_approval=False,
        reversible=True,
        incompatibilities=["FILE-MISSING"],
        population=lambda idx: idx.file_ids(),
        mutate=_checksum_mismatch,
    ),
    _def(
        rule_id="FILE-MISSING",
        title="Missing file",
        description="A file is tombstoned while its dataset still references it.",
        category=Category.FILE_INTEGRITY,
        default_severity=Severity.HIGH,
        applies_to_kinds=["file"],
        applies_to_modalities=["*"],
        prerequisites="file is not already tombstoned",
        operation="set_field:present=false",
        expected_evidence="file is marked not present but still referenced",
        expected_finding="File {id} is missing but still referenced.",
        remediation_action="restore_file",
        auto_fixable=False,
        requires_human_approval=True,
        reversible=True,
        incompatibilities=["FILE-CHECKSUM-MISMATCH"],
        population=lambda idx: idx.file_ids(),
        mutate=_file_missing,
    ),
]

DEFECTS: dict[str, DefectDef] = {d.rule_id: d for d in _DEFS}

# The entity kinds a rule may declare it applies to.
_KNOWN_KINDS = {"dataset", "data_product", "file"}


def defects_in_order() -> list[DefectDef]:
    """Return every defect definition sorted by rule id (the fixed apply order)."""
    return [DEFECTS[rule_id] for rule_id in sorted(DEFECTS)]


def validate_registry(defects: dict[str, DefectDef]) -> list[str]:
    """Return a sorted list of problems with a defect registry (empty if valid).

    Checks structural well-formedness so a malformed definition is rejected long
    before it is ever injected: unique keys, non-empty required text, known entity
    kinds, formattable finding templates, resolvable and non-self
    incompatibilities, and callable population/mutation hooks.
    """
    problems: list[str] = []
    for key, definition in defects.items():
        rule_id = definition.rule_id
        prefix = f"{key}:"
        if not rule_id:
            problems.append(f"{prefix} empty rule_id")
        if key != rule_id:
            problems.append(f"{prefix} registry key does not match rule_id {rule_id!r}")
        if not definition.title:
            problems.append(f"{prefix} empty title")
        if not definition.description:
            problems.append(f"{prefix} empty description")
        if not definition.remediation_action:
            problems.append(f"{prefix} empty remediation_action")
        if not definition.applies_to_kinds:
            problems.append(f"{prefix} no applies_to_kinds")
        for kind in definition.applies_to_kinds:
            if kind not in _KNOWN_KINDS:
                problems.append(f"{prefix} unknown entity kind {kind!r}")
        if not definition.applies_to_modalities:
            problems.append(f"{prefix} no applies_to_modalities")
        try:
            definition.expected_finding.format(id="example")
        except (KeyError, IndexError, ValueError):
            problems.append(f"{prefix} expected_finding template is not formattable")
        if rule_id in definition.incompatibilities:
            problems.append(f"{prefix} rule is incompatible with itself")
        for other in definition.incompatibilities:
            if other not in defects:
                problems.append(f"{prefix} incompatibility references unknown rule {other!r}")
        if not callable(definition.population):
            problems.append(f"{prefix} population is not callable")
        if not callable(definition.mutate):
            problems.append(f"{prefix} mutate is not callable")
    return sorted(problems)


def registry_rows() -> list[dict[str, Any]]:
    """Return a stable, presentation-ready summary of every defect definition."""
    rows: list[dict[str, Any]] = []
    for definition in defects_in_order():
        rows.append(
            {
                "rule_id": definition.rule_id,
                "title": definition.title,
                "category": definition.category.value,
                "severity": definition.default_severity.value,
                "applies_to": ",".join(definition.applies_to_kinds),
                "modalities": ",".join(definition.applies_to_modalities),
                "auto_fixable": definition.auto_fixable,
                "requires_human_approval": definition.requires_human_approval,
                "reversible": definition.reversible,
                "manifestation": definition.manifestation,
                "multiplicity": definition.multiplicity.value,
                "incompatibilities": ",".join(sorted(definition.incompatibilities)),
            }
        )
    return rows


__all__ = [
    "FieldChange",
    "MutationContext",
    "DefectDef",
    "DEFECTS",
    "defects_in_order",
    "validate_registry",
    "registry_rows",
]
