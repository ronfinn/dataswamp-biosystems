"""Post-generation invariant checks for the truth graph.

A correctly generated graph must satisfy referential integrity, id uniqueness,
count targets, an acyclic lineage DAG, per-asset completeness, temporal
monotonicity, size sanity, and the synthetic/domain locks. All problems are
collected and raised together as :class:`TruthValidationError`, mirroring the
company loader's collect-then-fail style.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from dataswamp_biosystems.company.config import CanonicalConfig
from dataswamp_biosystems.truth.entities import CatalogueAsset
from dataswamp_biosystems.truth.errors import (
    TruthIssueCollector,
    TruthIssueKind,
)
from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.ids import is_slug
from dataswamp_biosystems.truth.plan import GenerationPlan


def _catalogue(graph: TruthGraph) -> list[tuple[str, CatalogueAsset]]:
    """Return (entity-kind label, asset) for every catalogue dataset and product."""
    return [("datasets", d) for d in graph.datasets] + [
        ("data_products", p) for p in graph.data_products
    ]


def validate_truth_graph(
    graph: TruthGraph,
    config: CanonicalConfig,
    plan: GenerationPlan,
) -> None:
    """Validate every truth-graph invariant, raising on any problem."""
    issues = TruthIssueCollector()
    all_ids = _check_ids(graph, issues)
    _check_references(graph, config, all_ids, issues)
    _check_vocabularies(graph, config, issues)
    _check_relationships(graph, config, issues)
    _check_counts(graph, plan, issues)
    _check_lineage(graph, all_ids, issues)
    _check_completeness(graph, issues)
    _check_consistency(graph, issues)
    _check_metadata(graph, plan, issues)
    _check_temporal(graph, issues)
    _check_sizes(graph, issues)
    _check_domain_lock(graph, issues)
    issues.raise_if_any()


def _iter_entities(graph: TruthGraph) -> Iterator[tuple[str, Any]]:
    for name, value in graph:
        if name == "meta":
            continue
        for entity in value:
            yield name, entity


def _check_ids(graph: TruthGraph, issues: TruthIssueCollector) -> set[str]:
    seen: set[str] = set()
    for kind, entity in _iter_entities(graph):
        entity_id = entity.id
        if not is_slug(entity_id):
            issues.add(
                TruthIssueKind.INVALID_ID,
                f"id {entity_id!r} is not a valid slug",
                entity_kind=kind,
                entity_id=entity_id,
            )
        if entity_id in seen:
            issues.add(
                TruthIssueKind.DUPLICATE_ID,
                f"duplicate id {entity_id!r}",
                entity_kind=kind,
                entity_id=entity_id,
            )
        seen.add(entity_id)
        if entity.synthetic is not True:  # pragma: no cover - Literal[True] guards this
            issues.add(
                TruthIssueKind.SYNTHETIC_FLAG,
                "synthetic must be true",
                entity_kind=kind,
                entity_id=entity_id,
            )
    return seen


def _check_references(
    graph: TruthGraph,
    config: CanonicalConfig,
    all_ids: set[str],
    issues: TruthIssueCollector,
) -> None:
    subject_ids = {s.id for s in graph.subjects}
    biospecimen_ids = {b.id for b in graph.biospecimens}
    assay_ids = {a.id for a in graph.assays}
    run_ids = {r.id for r in graph.instrument_runs} | {r.id for r in graph.pipeline_runs}
    file_ids = {f.id for f in graph.files}
    dataset_ids = {d.id for d in graph.datasets}
    product_ids = {p.id for p in graph.data_products}
    asset_ids = dataset_ids | product_ids
    contract_ids = {c.id for c in graph.contracts}
    study_ids = {s.id for s in config.studies}
    programme_ids = {p.id for p in config.programmes}
    org_ids = {t.id for t in config.teams} | {p.id for p in config.people}

    def ref(ok: bool, kind: str, entity_id: str, field: str, target: str) -> None:
        if not ok:
            issues.add(
                TruthIssueKind.UNRESOLVED_REFERENCE,
                f"{kind} {entity_id!r} references nonexistent {field} {target!r}",
                entity_kind=kind,
                entity_id=entity_id,
                field=field,
            )

    for b in graph.biospecimens:
        ref(b.subject_id in subject_ids, "biospecimens", b.id, "subject_id", b.subject_id)
        ref(b.study_id in study_ids, "biospecimens", b.id, "study_id", b.study_id)
    for a in graph.assays:
        ref(a.biospecimen_id in biospecimen_ids, "assays", a.id, "biospecimen_id", a.biospecimen_id)
        ref(a.study_id in study_ids, "assays", a.id, "study_id", a.study_id)
    for ir in graph.instrument_runs:
        ref(ir.assay_id in assay_ids, "instrument_runs", ir.id, "assay_id", ir.assay_id)
    for pr in graph.pipeline_runs:
        for input_id in pr.input_ids:
            ref(
                input_id in run_ids or input_id in dataset_ids,
                "pipeline_runs",
                pr.id,
                "input_ids",
                input_id,
            )
    for f in graph.files:
        ref(f.producing_run_id in run_ids, "files", f.id, "producing_run_id", f.producing_run_id)
        ref(f.dataset_id in dataset_ids, "files", f.id, "dataset_id", f.dataset_id)
    for d in graph.datasets:
        for fid in d.file_ids:
            ref(fid in file_ids, "datasets", d.id, "file_ids", fid)
        ref(d.programme_id in programme_ids, "datasets", d.id, "programme_id", d.programme_id)
        ref(d.study_id in study_ids, "datasets", d.id, "study_id", d.study_id)
        ref(
            d.provenance_run_id in run_ids,
            "datasets",
            d.id,
            "provenance_run_id",
            d.provenance_run_id,
        )
        ref(d.owner_ref in org_ids, "datasets", d.id, "owner_ref", d.owner_ref)
        for steward in d.steward_refs:
            ref(steward in org_ids, "datasets", d.id, "steward_refs", steward)
        ref(d.contract_ref in contract_ids, "datasets", d.id, "contract_ref", d.contract_ref)
    for p in graph.data_products:
        ref(p.programme_id in programme_ids, "data_products", p.id, "programme_id", p.programme_id)
        ref(p.study_id in study_ids, "data_products", p.id, "study_id", p.study_id)
        ref(p.owner_ref in org_ids, "data_products", p.id, "owner_ref", p.owner_ref)
        for steward in p.steward_refs:
            ref(steward in org_ids, "data_products", p.id, "steward_refs", steward)
        ref(p.contract_ref in contract_ids, "data_products", p.id, "contract_ref", p.contract_ref)
        for cid in p.component_dataset_ids:
            ref(cid in dataset_ids, "data_products", p.id, "component_dataset_ids", cid)
    for c in graph.contracts:
        ref(c.asset_id in asset_ids, "contracts", c.id, "asset_id", c.asset_id)
    for q in graph.quality_checks:
        ref(q.asset_id in asset_ids, "quality_checks", q.id, "asset_id", q.asset_id)
    for g in graph.governance_records:
        ref(g.asset_id in asset_ids, "governance_records", g.id, "asset_id", g.asset_id)
        ref(g.owner_ref in org_ids, "governance_records", g.id, "owner_ref", g.owner_ref)
        for steward in g.steward_refs:
            ref(steward in org_ids, "governance_records", g.id, "steward_refs", steward)
    for iu in graph.intended_use_records:
        ref(iu.asset_id in asset_ids, "intended_use_records", iu.id, "asset_id", iu.asset_id)
    for mta in graph.training_approvals:
        ref(mta.asset_id in asset_ids, "training_approvals", mta.id, "asset_id", mta.asset_id)
        ref(
            mta.approver_ref in org_ids,
            "training_approvals",
            mta.id,
            "approver_ref",
            mta.approver_ref,
        )
    for edge in graph.lineage:
        ref(edge.upstream_id in all_ids, "lineage", edge.id, "upstream_id", edge.upstream_id)
        ref(edge.downstream_id in all_ids, "lineage", edge.id, "downstream_id", edge.downstream_id)


def _check_vocabularies(
    graph: TruthGraph, config: CanonicalConfig, issues: TruthIssueCollector
) -> None:
    """Every controlled-vocabulary value on an entity must resolve to a term."""
    vocab = config.vocabularies
    domains = {t.id for t in vocab.scientific_domains}
    modalities = {t.id for t in vocab.modalities}
    lifecycle = {t.id for t in vocab.lifecycle_stages}
    access = {t.id for t in vocab.access_classifications}
    retention = {t.id for t in vocab.retention_classes}
    intended = {t.id for t in vocab.intended_uses}
    training = {t.id for t in vocab.training_approval_statuses}

    def term(ok: bool, kind: str, entity_id: str, field: str, value: str, vocabulary: str) -> None:
        if not ok:
            issues.add(
                TruthIssueKind.INVALID_VOCABULARY,
                f"{field} {value!r} is not a valid {vocabulary} term",
                entity_kind=kind,
                entity_id=entity_id,
                field=field,
            )

    for a in graph.assays:
        term(a.modality in modalities, "assays", a.id, "modality", a.modality, "modality")

    for kind, asset in _catalogue(graph):
        term(asset.modality in modalities, kind, asset.id, "modality", asset.modality, "modality")
        term(
            asset.scientific_domain in domains,
            kind,
            asset.id,
            "scientific_domain",
            asset.scientific_domain,
            "scientific-domain",
        )
        term(
            asset.lifecycle_stage in lifecycle,
            kind,
            asset.id,
            "lifecycle_stage",
            asset.lifecycle_stage,
            "lifecycle-stage",
        )
        term(
            asset.access_classification in access,
            kind,
            asset.id,
            "access_classification",
            asset.access_classification,
            "access-classification",
        )
        term(
            asset.retention_class in retention,
            kind,
            asset.id,
            "retention_class",
            asset.retention_class,
            "retention-class",
        )
        term(
            asset.model_training_status in training,
            kind,
            asset.id,
            "model_training_status",
            asset.model_training_status,
            "training-approval-status",
        )
        for use in asset.intended_uses:
            term(use in intended, kind, asset.id, "intended_uses", use, "intended-use")


def _check_relationships(
    graph: TruthGraph, config: CanonicalConfig, issues: TruthIssueCollector
) -> None:
    """Structural relationship rules beyond simple id resolution."""
    study_programme = {s.id: s.programme_id for s in config.studies}
    subject_study = {s.id: s.study_id for s in graph.subjects}
    specimen_study = {b.id: b.study_id for b in graph.biospecimens}
    specimen_subject = {b.id: b.subject_id for b in graph.biospecimens}

    def bad(kind: str, entity_id: str, field: str, message: str) -> None:
        issues.add(
            TruthIssueKind.RELATIONSHIP,
            message,
            entity_kind=kind,
            entity_id=entity_id,
            field=field,
        )

    # Programme–study consistency for catalogue assets.
    for kind, asset in _catalogue(graph):
        expected = study_programme.get(asset.study_id)
        if expected is not None and expected != asset.programme_id:
            bad(
                kind,
                asset.id,
                "programme_id",
                f"study {asset.study_id!r} belongs to programme {expected!r}, "
                f"not {asset.programme_id!r}",
            )

    # Subject → biospecimen → assay must stay within one study.
    for b in graph.biospecimens:
        subject_study_id = subject_study.get(b.subject_id)
        if subject_study_id is not None and subject_study_id != b.study_id:
            bad(
                "biospecimens",
                b.id,
                "study_id",
                f"specimen study {b.study_id!r} differs from subject study {subject_study_id!r}",
            )
    for a in graph.assays:
        specimen_study_id = specimen_study.get(a.biospecimen_id)
        if specimen_study_id is not None and specimen_study_id != a.study_id:
            bad(
                "assays",
                a.id,
                "study_id",
                f"assay study {a.study_id!r} differs from specimen study {specimen_study_id!r}",
            )
        # And the specimen must trace back to a subject (endpoint completeness).
        if a.biospecimen_id in specimen_subject and specimen_subject[a.biospecimen_id] == "":
            bad("assays", a.id, "biospecimen_id", "assay specimen has no subject")


def _check_metadata(graph: TruthGraph, plan: GenerationPlan, issues: TruthIssueCollector) -> None:
    """Modality metadata keys must be within the supported set for the group."""
    allowed = {
        "scrna-seq": {"assay_chemistry", "estimated_cells"},
        "visium-hd": {"bin_size_um", "capture_area"},
        "wgs-wes": {"reference_build", "mean_coverage_x"},
        "digital-pathology": {"magnification", "slide_count"},
        "radiology": {"dicom_modality", "series_count"},
        "functional-genomics": {"library_type", "guide_count"},
        "reference": {"reference_kind"},
        "multimodal": set(),
    }
    for dataset in graph.datasets:
        supported = allowed.get(dataset.modality_group)
        if supported is None:
            issues.add(
                TruthIssueKind.METADATA,
                f"unknown modality group {dataset.modality_group!r}",
                entity_kind="datasets",
                entity_id=dataset.id,
                field="modality_group",
            )
            continue
        for key in dataset.modality_metadata:
            if key not in supported:
                issues.add(
                    TruthIssueKind.METADATA,
                    f"unsupported modality metadata key {key!r} for group "
                    f"{dataset.modality_group!r}",
                    entity_kind="datasets",
                    entity_id=dataset.id,
                    field="modality_metadata",
                )


def _check_consistency(graph: TruthGraph, issues: TruthIssueCollector) -> None:
    """Denormalised asset governance fields must agree with their evidence records."""
    gov_owner = {g.asset_id: g.owner_ref for g in graph.governance_records}
    gov_stewards = {g.asset_id: set(g.steward_refs) for g in graph.governance_records}
    training_status = {m.asset_id: m.status for m in graph.training_approvals}
    contract_by_asset = {c.asset_id: c.id for c in graph.contracts}

    def mismatch(kind: str, entity_id: str, field: str, message: str) -> None:
        issues.add(
            TruthIssueKind.CONSISTENCY,
            message,
            entity_kind=kind,
            entity_id=entity_id,
            field=field,
        )

    for kind, asset in _catalogue(graph):
        if gov_owner.get(asset.id) != asset.owner_ref:
            mismatch(kind, asset.id, "owner_ref", "asset owner differs from its governance record")
        if gov_stewards.get(asset.id) != set(asset.steward_refs):
            mismatch(
                kind, asset.id, "steward_refs", "asset stewards differ from its governance record"
            )
        if training_status.get(asset.id) != asset.model_training_status:
            mismatch(
                kind,
                asset.id,
                "model_training_status",
                "asset training status differs from its approval",
            )
        if contract_by_asset.get(asset.id) != asset.contract_ref:
            mismatch(
                kind,
                asset.id,
                "contract_ref",
                "asset contract_ref does not match its contract record",
            )
        if asset.quality_status.value != "pass":
            mismatch(kind, asset.id, "quality_status", "asset quality_status is not passing")


def _check_counts(graph: TruthGraph, plan: GenerationPlan, issues: TruthIssueCollector) -> None:
    def count(name: str, actual: int, expected: int) -> None:
        if actual != expected:
            issues.add(
                TruthIssueKind.COUNT_MISMATCH,
                f"expected {expected} {name}, got {actual}",
                entity_kind=name,
            )

    n_studies = len({s.study_id for s in graph.subjects})
    count("subjects", len(graph.subjects), plan.subjects_per_study * max(n_studies, 1))
    count("datasets", len(graph.datasets), plan.total_datasets())
    count("data_products", len(graph.data_products), plan.data_product_count)
    for group in plan.modality_groups:
        actual = sum(
            1 for d in graph.datasets if d.modality_group == group.id and not d.is_reference
        )
        count(f"datasets[{group.id}]", actual, group.dataset_count)


def _check_lineage(graph: TruthGraph, all_ids: set[str], issues: TruthIssueCollector) -> None:
    adjacency: dict[str, list[str]] = {}
    for edge in graph.lineage:
        adjacency.setdefault(edge.upstream_id, []).append(edge.downstream_id)
        if edge.upstream_id == edge.downstream_id:
            issues.add(
                TruthIssueKind.LINEAGE,
                "lineage edge points a node at itself (self-lineage)",
                entity_kind="lineage",
                entity_id=edge.id,
            )

    # Cycle detection via iterative DFS with three-colour marking.
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = dict.fromkeys(all_ids, WHITE)
    found_cycle = False
    for start in sorted(all_ids):
        if colour[start] != WHITE:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                colour[node] = BLACK
                continue
            if colour[node] == GREY:
                continue
            colour[node] = GREY
            stack.append((node, True))
            for nxt in sorted(adjacency.get(node, [])):
                if colour.get(nxt, BLACK) == GREY:
                    found_cycle = True
                elif colour.get(nxt, BLACK) == WHITE:
                    stack.append((nxt, False))
    if found_cycle:
        issues.add(TruthIssueKind.LINEAGE, "lineage graph contains a cycle")

    downstream_nodes = {edge.downstream_id for edge in graph.lineage}
    for dataset in graph.datasets:
        if dataset.id not in downstream_nodes:
            issues.add(
                TruthIssueKind.LINEAGE,
                "dataset has no upstream lineage edge",
                entity_kind="datasets",
                entity_id=dataset.id,
            )
    for product in graph.data_products:
        if product.id not in downstream_nodes:
            issues.add(
                TruthIssueKind.LINEAGE,
                "data product has no upstream lineage edge",
                entity_kind="data_products",
                entity_id=product.id,
            )

    # Lifecycle-transition validity: a dataset processed beyond the raw/ingested
    # stages must have been produced by a pipeline run; raw/ingested datasets are
    # produced directly by an instrument run.
    instrument_ids = {r.id for r in graph.instrument_runs}
    pipeline_ids = {r.id for r in graph.pipeline_runs}
    short_stages = {"raw", "ingested"}
    for dataset in graph.datasets:
        run_id = dataset.provenance_run_id
        if dataset.lifecycle_stage in short_stages:
            if run_id not in instrument_ids:
                issues.add(
                    TruthIssueKind.LINEAGE,
                    f"{dataset.lifecycle_stage} dataset must be produced by an instrument run",
                    entity_kind="datasets",
                    entity_id=dataset.id,
                    field="provenance_run_id",
                )
        elif run_id not in pipeline_ids:
            issues.add(
                TruthIssueKind.LINEAGE,
                f"{dataset.lifecycle_stage} dataset must be produced by a pipeline run",
                entity_kind="datasets",
                entity_id=dataset.id,
                field="provenance_run_id",
            )


def _check_completeness(graph: TruthGraph, issues: TruthIssueCollector) -> None:
    asset_ids = [d.id for d in graph.datasets] + [p.id for p in graph.data_products]
    quality_by_asset: dict[str, int] = {}
    for q in graph.quality_checks:
        quality_by_asset[q.asset_id] = quality_by_asset.get(q.asset_id, 0) + 1
    governance_by_asset: dict[str, int] = {}
    for g in graph.governance_records:
        governance_by_asset[g.asset_id] = governance_by_asset.get(g.asset_id, 0) + 1
    contract_by_asset: dict[str, int] = {}
    for c in graph.contracts:
        contract_by_asset[c.asset_id] = contract_by_asset.get(c.asset_id, 0) + 1
    training_by_asset: dict[str, int] = {}
    for mta in graph.training_approvals:
        training_by_asset[mta.asset_id] = training_by_asset.get(mta.asset_id, 0) + 1
    intended_by_asset: dict[str, int] = {}
    for iu in graph.intended_use_records:
        intended_by_asset[iu.asset_id] = intended_by_asset.get(iu.asset_id, 0) + 1

    for asset_id in asset_ids:
        if quality_by_asset.get(asset_id, 0) < 1:
            _incomplete(issues, asset_id, "missing quality checks")
        if governance_by_asset.get(asset_id, 0) != 1:
            _incomplete(issues, asset_id, "must have exactly one governance record")
        if contract_by_asset.get(asset_id, 0) != 1:
            _incomplete(issues, asset_id, "must have exactly one data contract")
        if training_by_asset.get(asset_id, 0) != 1:
            _incomplete(issues, asset_id, "must have exactly one training approval")
        if intended_by_asset.get(asset_id, 0) < 1:
            _incomplete(issues, asset_id, "missing intended-use records")

    for q in graph.quality_checks:
        if q.status.value != "pass":
            _incomplete(issues, q.asset_id, f"quality check {q.id!r} is not passing")


def _incomplete(issues: TruthIssueCollector, asset_id: str, message: str) -> None:
    issues.add(
        TruthIssueKind.COMPLETENESS,
        message,
        entity_kind="asset",
        entity_id=asset_id,
    )


def _check_temporal(graph: TruthGraph, issues: TruthIssueCollector) -> None:
    subject_origin = {s.id: s.origin_date for s in graph.subjects}
    specimen_collected = {b.id: b.collected_on for b in graph.biospecimens}
    assay_date = {a.id: a.assayed_on for a in graph.assays}
    run_completed: dict[str, datetime] = {}

    for b in graph.biospecimens:
        origin = subject_origin.get(b.subject_id)
        if origin is not None and b.collected_on < origin:
            _temporal(issues, "biospecimens", b.id, "collected before subject origin")
    for a in graph.assays:
        collected = specimen_collected.get(a.biospecimen_id)
        if collected is not None and a.assayed_on < collected:
            _temporal(issues, "assays", a.id, "assayed before specimen collected")
    for ir in graph.instrument_runs:
        run_completed[ir.id] = ir.completed_at
        if ir.started_at > ir.completed_at:
            _temporal(issues, "instrument_runs", ir.id, "started after completed")
        assayed = assay_date.get(ir.assay_id)
        if assayed is not None and ir.started_at.date() < assayed:
            _temporal(issues, "instrument_runs", ir.id, "started before assay date")
    for pr in graph.pipeline_runs:
        run_completed[pr.id] = pr.completed_at
    for pr in graph.pipeline_runs:
        if pr.started_at > pr.completed_at:
            _temporal(issues, "pipeline_runs", pr.id, "started after completed")
        for input_id in pr.input_ids:
            upstream_done = run_completed.get(input_id)
            if upstream_done is not None and input_id != pr.id and upstream_done > pr.started_at:
                _temporal(
                    issues, "pipeline_runs", pr.id, f"started before input {input_id!r} completed"
                )


def _temporal(issues: TruthIssueCollector, kind: str, entity_id: str, message: str) -> None:
    issues.add(TruthIssueKind.TEMPORAL, message, entity_kind=kind, entity_id=entity_id)


def _check_sizes(graph: TruthGraph, issues: TruthIssueCollector) -> None:
    for d in graph.datasets:
        if d.logical_bytes < d.physical_bytes:
            issues.add(
                TruthIssueKind.SIZE,
                "logical_bytes must be >= physical_bytes",
                entity_kind="datasets",
                entity_id=d.id,
                field="logical_bytes",
            )
    for f in graph.files:
        if f.physical_bytes < 0:  # pragma: no cover - Field(ge=0) guards this
            issues.add(
                TruthIssueKind.SIZE,
                "physical_bytes must be >= 0",
                entity_kind="files",
                entity_id=f.id,
                field="physical_bytes",
            )


def _check_domain_lock(graph: TruthGraph, issues: TruthIssueCollector) -> None:
    for kind, entity in _iter_entities(graph):
        for field_name, value in entity.model_dump(mode="json").items():
            for token in _strings(value):
                if "@" in token and not token.endswith("@dataswamp.example"):
                    issues.add(
                        TruthIssueKind.DOMAIN_LOCK,
                        f"value {token!r} uses a non-fictional domain",
                        entity_kind=kind,
                        entity_id=entity.id,
                        field=field_name,
                    )


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


__all__ = ["validate_truth_graph"]
