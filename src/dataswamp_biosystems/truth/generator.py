"""The deterministic truth-graph generator.

Given the canonical company config, the generation plan, and a seed, this builds
a complete and correct :class:`TruthGraph`. Determinism is structural: every
collection is iterated in sorted order, every random value is drawn from
``sub_rng(seed, kind, stable_id)`` so it depends only on the entity's key, and
every date derives from the plan's fixed epoch anchor. No wall-clock, no global
RNG, no set-iteration for output order.

The build is topological — upstream ids exist before anything references them:
subjects → biospecimens → assays → instrument runs → pipeline runs → files →
datasets → data products → contracts → quality → governance → lineage.
"""

from __future__ import annotations

from datetime import date, datetime
from random import Random

from dataswamp_biosystems.company.config import CanonicalConfig
from dataswamp_biosystems.company.entities import Study
from dataswamp_biosystems.company.relationships import SubjectType
from dataswamp_biosystems.truth import ids
from dataswamp_biosystems.truth.dates import at_days, at_offset
from dataswamp_biosystems.truth.entities import (
    Assay,
    Biospecimen,
    DataContract,
    DataProduct,
    Dataset,
    EdgeType,
    GovernanceRecord,
    InstrumentRun,
    IntendedUseRecord,
    LineageEdge,
    ModelTrainingApproval,
    PhysicalFileRecord,
    PipelineRun,
    QualityCheck,
    Subject,
    SubjectKind,
)
from dataswamp_biosystems.truth.graph import (
    TRUTH_SCHEMA_VERSION,
    TruthGraph,
    TruthGraphMeta,
)
from dataswamp_biosystems.truth.plan import GenerationPlan, ModalityGroup, even_split
from dataswamp_biosystems.truth.rng import sub_rng

# Governance fallbacks (valid company-model ids) guaranteeing non-empty refs.
_FALLBACK_OWNER_TEAM = "team-data-governance"
_FALLBACK_STEWARD_TEAM = "team-data-governance"
_TRAINING_APPROVER = "team-privacy-compliance"

# Dataset lifecycle stages, ordered; ordinal cycles through these for spread.
_DATASET_STAGES = ["ingested", "processed", "curated", "analysis-ready", "published"]
# Stages at or below this order index get a shorter chain (no pipeline run).
_SHORT_CHAIN_STAGES = {"ingested"}

_QUALITY_CHECK_TYPES = ["completeness", "schema-conformance", "referential-integrity"]

# Deterministic descriptive vocab per modality group (fictional, no real vendors).
_INSTRUMENT_BY_GROUP = {
    "scrna-seq": "swamp-seq-x",
    "visium-hd": "swamp-spatial-hd",
    "wgs-wes": "swamp-seq-w",
    "digital-pathology": "swamp-slide-scanner",
    "radiology": "swamp-imager",
    "functional-genomics": "swamp-screen-bench",
}
_PLATFORM_BY_MODALITY = {
    "scrna-seq": "droplet-3prime-v3",
    "visium-hd": "visium-hd-2um",
    "wgs": "pcr-free-wgs",
    "wes": "exome-capture-v2",
    "digital-pathology-wsi": "brightfield-40x",
    "ct-imaging": "ct-helical",
    "mri-imaging": "mri-3t",
    "perturb-seq": "pooled-crispr-scrna",
    "crispr-screen": "pooled-viability-screen",
}
_FORMAT_BY_GROUP = {
    "scrna-seq": "h5ad",
    "visium-hd": "h5",
    "wgs-wes": "cram",
    "digital-pathology": "ome-tiff",
    "radiology": "dicom",
    "functional-genomics": "h5ad",
    "reference": "parquet",
}


def _strip(prefix: str, value: str) -> str:
    return value[len(prefix) :] if value.startswith(prefix) else value


class _Builder:
    """Accumulates entities during a single deterministic generation pass."""

    def __init__(self, config: CanonicalConfig, plan: GenerationPlan, seed: int) -> None:
        self.config = config
        self.plan = plan
        self.seed = seed
        self.anchor: date = plan.epoch_anchor

        self.subjects: list[Subject] = []
        self.biospecimens: list[Biospecimen] = []
        self.assays: list[Assay] = []
        self.instrument_runs: list[InstrumentRun] = []
        self.pipeline_runs: list[PipelineRun] = []
        self.files: list[PhysicalFileRecord] = []
        self.datasets: list[Dataset] = []
        self.data_products: list[DataProduct] = []
        self.contracts: list[DataContract] = []
        self.quality_checks: list[QualityCheck] = []
        self.governance_records: list[GovernanceRecord] = []
        self.intended_use_records: list[IntendedUseRecord] = []
        self.training_approvals: list[ModelTrainingApproval] = []
        self._edges: set[tuple[str, str, str]] = set()

        # Lookups derived once from config.
        self._study_by_id = {s.id: s for s in config.studies}
        self._programme_by_id = {p.id: p for p in config.programmes}
        self._modality_domain = {m.id: m.scientific_domain for m in config.vocabularies.modalities}
        self._modality_label = {m.id: m.label for m in config.vocabularies.modalities}
        self._study_owner: dict[str, str] = {}
        self._programme_owner: dict[str, str] = {}
        for own in config.ownership:
            if own.subject_type is SubjectType.STUDY:
                self._study_owner[own.subject_id] = own.owner_id
            elif own.subject_type is SubjectType.PROGRAMME:
                self._programme_owner[own.subject_id] = own.owner_id
        self._study_stewards: dict[str, list[str]] = {}
        self._programme_stewards: dict[str, list[str]] = {}
        for stew in config.stewardship:
            if stew.subject_type is SubjectType.STUDY:
                self._study_stewards.setdefault(stew.subject_id, []).append(stew.steward_id)
            elif stew.subject_type is SubjectType.PROGRAMME:
                self._programme_stewards.setdefault(stew.subject_id, []).append(stew.steward_id)

        # Subject pools, filled by _build_subjects: study -> kind -> [subject ids].
        self._subject_pool: dict[str, dict[SubjectKind, list[str]]] = {}
        self._subject_origin: dict[str, date] = {}
        self._pool_cursor: dict[tuple[str, str], int] = {}

    # -- helpers ---------------------------------------------------------------

    def _rng(self, *key: str) -> Random:
        return sub_rng(self.seed, *key)

    def _study_code(self, study_id: str) -> str:
        return _strip("study-", study_id)

    def _programme_code(self, programme_id: str) -> str:
        return _strip("prog-", programme_id)

    def _functional_groups(self) -> set[str]:
        return {
            g.id
            for g in self.plan.modality_groups
            if g.subject_kind is SubjectKind.EXPERIMENTAL_MODEL
        }

    def _owner_for_study(self, study_id: str, programme_id: str) -> str:
        return (
            self._study_owner.get(study_id)
            or self._programme_owner.get(programme_id)
            or _FALLBACK_OWNER_TEAM
        )

    def _stewards_for_study(self, study_id: str, programme_id: str) -> list[str]:
        stewards = self._study_stewards.get(study_id) or self._programme_stewards.get(programme_id)
        return sorted(set(stewards)) if stewards else [_FALLBACK_STEWARD_TEAM]

    def _add_edge(self, upstream: str, downstream: str, edge_type: EdgeType) -> None:
        self._edges.add((upstream, downstream, edge_type.value))

    # -- stage 1: subjects -----------------------------------------------------

    def _build_subjects(self) -> None:
        functional = self._functional_groups()
        # Which studies carry model vs human modalities.
        study_needs_model: dict[str, bool] = {s.id: False for s in self.config.studies}
        study_needs_human: dict[str, bool] = {s.id: False for s in self.config.studies}
        for group in self.plan.modality_groups:
            model = group.id in functional
            for study_id in group.studies:
                if model:
                    study_needs_model[study_id] = True
                else:
                    study_needs_human[study_id] = True

        per_study = self.plan.subjects_per_study
        for study in sorted(self.config.studies, key=lambda s: s.id):
            code = self._study_code(study.id)
            needs_model = study_needs_model[study.id]
            needs_human = study_needs_human[study.id]
            if needs_model and needs_human:
                model_count = min(4, per_study)
            elif needs_model:
                model_count = per_study
            else:
                model_count = 0
            human_count = per_study - model_count
            self._subject_pool[study.id] = {
                SubjectKind.HUMAN_SUBJECT: [],
                SubjectKind.EXPERIMENTAL_MODEL: [],
            }
            for index in range(per_study):
                kind = (
                    SubjectKind.EXPERIMENTAL_MODEL
                    if index >= human_count
                    else SubjectKind.HUMAN_SUBJECT
                )
                subject_id = ids.join("subj", code, ids.ordinal(index + 1))
                rng = self._rng("subject", subject_id)
                origin = at_days(self.anchor, -(400 + rng.randint(0, 400)))
                self._subject_origin[subject_id] = origin
                if kind is SubjectKind.EXPERIMENTAL_MODEL:
                    system = rng.choice(["pdx", "organoid", "cell-line"])
                    line = f"dsb-{code}-line-{ids.ordinal(index + 1)}"
                    library = rng.choice(["genome-wide-ko", "focused-activation", "dual-guide"])
                    subject = Subject(
                        id=subject_id,
                        kind=kind,
                        study_id=study.id,
                        programme_id=study.programme_id,
                        subject_code=f"{code}-model-{ids.ordinal(index + 1)}",
                        origin_date=origin,
                        model_system=system,
                        cell_line=line,
                        perturbation_library=library,
                    )
                else:
                    subject = Subject(
                        id=subject_id,
                        kind=kind,
                        study_id=study.id,
                        programme_id=study.programme_id,
                        subject_code=f"{code}-subj-{ids.ordinal(index + 1)}",
                        origin_date=origin,
                    )
                self.subjects.append(subject)
                self._subject_pool[study.id][kind].append(subject_id)
            # Guarantee human_count/model_count referenced (documents intent).
            assert human_count + model_count == per_study

    def _next_subject(self, study_id: str, kind: SubjectKind) -> str:
        pool = self._subject_pool[study_id][kind]
        if not pool:  # pragma: no cover - guarded by plan/subject construction
            pool = self._subject_pool[study_id][SubjectKind.HUMAN_SUBJECT]
        cursor_key = (study_id, kind.value)
        index = self._pool_cursor.get(cursor_key, 0)
        self._pool_cursor[cursor_key] = index + 1
        return pool[index % len(pool)]

    # -- stage 2: modality datasets and their provenance -----------------------

    def _build_modality_datasets(self) -> None:
        for group in sorted(self.plan.modality_groups, key=lambda g: g.id):
            per_study = even_split(group.dataset_count, group.studies)
            for study_id in sorted(group.studies):
                study = self._study_by_id[study_id]
                allowed = sorted(m for m in group.modalities if m in set(study.modalities))
                for index in range(per_study[study_id]):
                    modality = allowed[index % len(allowed)]
                    self._build_one_modality_dataset(group, study, modality, index + 1)

    def _build_one_modality_dataset(
        self, group: ModalityGroup, study: Study, modality: str, ordinal_n: int
    ) -> None:
        code = ids.join(self._study_code(study.id), group.id, ids.ordinal(ordinal_n))
        dataset_id = ids.join("ds", code)
        rng = self._rng("dataset", dataset_id)
        stage = _DATASET_STAGES[(ordinal_n - 1) % len(_DATASET_STAGES)]
        short_chain = stage in _SHORT_CHAIN_STAGES

        subject_id = self._next_subject(study.id, group.subject_kind)
        origin = self._subject_origin[subject_id]

        # Provenance timeline (each step strictly after the previous).
        collected_on = at_days(origin, 10 + rng.randint(0, 300))
        assayed_on = at_days(collected_on, 3 + rng.randint(0, 45))
        irun_start = at_offset(assayed_on, seconds=rng.randint(0, 6 * 3600))
        irun_end = at_offset(assayed_on, seconds=rng.randint(6 * 3600, 14 * 3600))
        # Biospecimen.
        specimen_id = ids.join("spec", code)
        self.biospecimens.append(
            Biospecimen(
                id=specimen_id,
                subject_id=subject_id,
                study_id=study.id,
                specimen_type=rng.choice(["tumour-tissue", "blood", "cell-pellet", "biopsy-core"]),
                collected_on=collected_on,
                preservation=rng.choice(["ffpe", "fresh-frozen", "cryopreserved"]),
            )
        )
        # Assay.
        assay_id = ids.join("assay", code)
        self.assays.append(
            Assay(
                id=assay_id,
                biospecimen_id=specimen_id,
                study_id=study.id,
                modality=modality,
                platform=_PLATFORM_BY_MODALITY.get(modality, "generic-platform"),
                assayed_on=assayed_on,
            )
        )
        # Instrument run.
        irun_id = ids.join("irun", code)
        self.instrument_runs.append(
            InstrumentRun(
                id=irun_id,
                assay_id=assay_id,
                instrument_model=_INSTRUMENT_BY_GROUP.get(group.id, "swamp-instrument"),
                started_at=irun_start,
                completed_at=irun_end,
            )
        )
        producing_run_id = irun_id
        latest_completion = irun_end
        # Pipeline run (only for the longer-chain lifecycle stages).
        if not short_chain:
            prun_id = ids.join("prun", code)
            prun_start = at_offset(assayed_on, days=1, seconds=rng.randint(0, 6 * 3600))
            if prun_start <= irun_end:
                prun_start = at_offset(assayed_on, days=2)
            prun_end = at_offset(
                prun_start.date(), days=0, seconds=rng.randint(6 * 3600, 20 * 3600)
            )
            if prun_end <= prun_start:
                prun_end = at_offset(prun_start.date(), days=1)
            self.pipeline_runs.append(
                PipelineRun(
                    id=prun_id,
                    pipeline_name=f"{group.id}-primary",
                    pipeline_version=f"{1 + (ordinal_n % 3)}.{ordinal_n % 5}.0",
                    input_ids=[irun_id],
                    started_at=prun_start,
                    completed_at=prun_end,
                )
            )
            producing_run_id = prun_id
            latest_completion = prun_end
            self._add_edge(irun_id, prun_id, EdgeType.PROCESSED_BY)

        # Files.
        file_ids = self._build_files(code, group.id, producing_run_id, dataset_id, rng)
        physical_bytes = sum(f.physical_bytes for f in self.files if f.id in set(file_ids))
        logical_bytes = physical_bytes * (2 + (ordinal_n % 4))

        owner = self._owner_for_study(study.id, study.programme_id)
        stewards = self._stewards_for_study(study.id, study.programme_id)
        modality_label = self._modality_label.get(modality, modality)
        programme = self._programme_by_id[study.programme_id]
        contract_ref = ids.join("contract", dataset_id)

        dataset = Dataset(
            id=dataset_id,
            title=f"{study.display_name} {modality_label} dataset {ordinal_n:02d}",
            description=(
                f"Synthetic {modality_label} dataset for study {study.display_name} in the "
                f"{programme.display_name} ({programme.indication}); lifecycle stage {stage}."
            ),
            programme_id=study.programme_id,
            study_id=study.id,
            scientific_domain=self._modality_domain[modality],
            modality=modality,
            modality_group=group.id,
            lifecycle_stage=stage,
            version=f"{1 + (ordinal_n % 3)}.{ordinal_n % 6}.0",
            owner_ref=owner,
            steward_refs=stewards,
            access_classification=study.access_classification,
            retention_class=study.retention_class,
            intended_uses=list(study.intended_uses),
            model_training_status=study.model_training_approval,
            contract_ref=contract_ref,
            generator_version=self.plan.generator_version,
            generation_seed=self.seed,
            physical_bytes=physical_bytes,
            logical_bytes=logical_bytes,
            record_count=1000 * (1 + rng.randint(0, 50)),
            file_ids=sorted(file_ids),
            provenance_run_id=producing_run_id,
            modality_metadata=_modality_metadata(group.id, modality, rng),
            is_reference=False,
        )
        self.datasets.append(dataset)

        # Lineage for the scientific chain.
        self._add_edge(subject_id, specimen_id, EdgeType.COLLECTED_FROM)
        self._add_edge(specimen_id, assay_id, EdgeType.ASSAYED_FROM)
        self._add_edge(assay_id, irun_id, EdgeType.PROFILED_BY)
        for file_id in file_ids:
            self._add_edge(producing_run_id, file_id, EdgeType.PRODUCED)
            self._add_edge(file_id, dataset_id, EdgeType.DERIVED_FROM)

        self._build_asset_governance(
            asset_id=dataset_id,
            owner=owner,
            stewards=stewards,
            access=study.access_classification,
            retention=study.retention_class,
            intended_uses=list(study.intended_uses),
            training_status=study.model_training_approval,
            decided_after=latest_completion,
        )

    def _build_files(
        self, code: str, group_id: str, run_id: str, dataset_id: str, rng: Random
    ) -> list[str]:
        count = 2 + rng.randint(0, 3)
        file_format = _FORMAT_BY_GROUP.get(group_id, "bin")
        made: list[str] = []
        for n in range(1, count + 1):
            file_id = ids.join("file", code, ids.ordinal(n))
            frng = self._rng("file", file_id)
            size = (32 + frng.randint(0, 4064)) * 1_000_000
            checksum = ids.stable_suffix(file_id, str(size), digest_size=16)
            self.files.append(
                PhysicalFileRecord(
                    id=file_id,
                    producing_run_id=run_id,
                    dataset_id=dataset_id,
                    relative_path=f"{group_id}/{code}/part-{ids.ordinal(n)}.{file_format}",
                    file_format=file_format,
                    physical_bytes=size,
                    checksum=checksum,
                )
            )
            made.append(file_id)
        return made

    # -- stage 3: reference datasets -------------------------------------------

    def _build_reference_datasets(self) -> None:
        programmes = sorted(p.id for p in self.config.programmes)
        per_programme = even_split(self.plan.reference_dataset_count, programmes)
        datasets_by_programme: dict[str, list[str]] = {}
        for ds in self.datasets:
            datasets_by_programme.setdefault(ds.programme_id, []).append(ds.id)
        for programme_id in programmes:
            prog_code = self._programme_code(programme_id)
            sources = sorted(datasets_by_programme.get(programme_id, []))
            for index in range(per_programme[programme_id]):
                self._build_one_reference_dataset(programme_id, prog_code, sources, index + 1)

    def _build_one_reference_dataset(
        self, programme_id: str, prog_code: str, sources: list[str], ordinal_n: int
    ) -> None:
        code = ids.join(prog_code, "reference", ids.ordinal(ordinal_n))
        dataset_id = ids.join("ds", code)
        rng = self._rng("reference", dataset_id)
        stage = "curated" if ordinal_n % 2 else "published"
        access = self._programme_default_access(programme_id)
        retention = self._programme_default_retention(programme_id)

        # Aggregate a few source datasets deterministically (may be empty edge-wise).
        picked = sources[:3] if sources else []
        prun_id = ids.join("prun", code)
        prun_start = at_offset(self.anchor, days=-(30 + rng.randint(0, 60)))
        prun_end = at_offset(prun_start.date(), days=1)
        self.pipeline_runs.append(
            PipelineRun(
                id=prun_id,
                pipeline_name="reference-assembly",
                pipeline_version=f"1.{ordinal_n % 5}.0",
                input_ids=sorted(picked) if picked else [prun_id],
                started_at=prun_start,
                completed_at=prun_end,
            )
        )
        for source in picked:
            self._add_edge(source, prun_id, EdgeType.PROCESSED_BY)

        file_ids = self._build_files(code, "reference", prun_id, dataset_id, rng)
        physical_bytes = sum(f.physical_bytes for f in self.files if f.id in set(file_ids))

        # Reference datasets are cross-modal; for catalogue completeness they take
        # a representative modality/study from a dataset they aggregate (or the
        # programme's first study when there are no sources yet).
        by_id = {d.id: d for d in self.datasets}
        rep = by_id[picked[0]] if picked else None
        programme = self._programme_by_id[programme_id]
        if rep is not None:
            primary_study = rep.study_id
            rep_modality = rep.modality
        else:  # pragma: no cover - every programme has modality datasets first
            primary_study = sorted(
                s.id for s in self.config.studies if s.programme_id == programme_id
            )[0]
            rep_modality = self._study_by_id[primary_study].modalities[0]
        owner = self._owner_for_study(primary_study, programme_id)
        stewards = self._stewards_for_study(primary_study, programme_id)
        contract_ref = ids.join("contract", dataset_id)
        training_status = "model-training-under-review"
        intended = ["research-only", "internal-analytics"]

        dataset = Dataset(
            id=dataset_id,
            title=f"{programme.display_name} reference dataset {ordinal_n:02d}",
            description=(
                f"Synthetic shared reference/supporting dataset for the "
                f"{programme.display_name} ({programme.indication}); "
                f"aggregates {len(picked)} programme datasets."
            ),
            programme_id=programme_id,
            study_id=primary_study,
            scientific_domain=self._modality_domain[rep_modality],
            modality=rep_modality,
            modality_group="reference",
            lifecycle_stage=stage,
            version=f"1.{ordinal_n % 4}.0",
            owner_ref=owner,
            steward_refs=stewards,
            access_classification=access,
            retention_class=retention,
            intended_uses=intended,
            model_training_status=training_status,
            contract_ref=contract_ref,
            generator_version=self.plan.generator_version,
            generation_seed=self.seed,
            physical_bytes=physical_bytes,
            logical_bytes=physical_bytes * 2,
            record_count=500 * (1 + rng.randint(0, 20)),
            file_ids=sorted(file_ids),
            provenance_run_id=prun_id,
            modality_metadata={"reference_kind": rng.choice(["manifest", "annotation", "panel"])},
            is_reference=True,
        )
        self.datasets.append(dataset)
        for file_id in file_ids:
            self._add_edge(prun_id, file_id, EdgeType.PRODUCED)
            self._add_edge(file_id, dataset_id, EdgeType.DERIVED_FROM)

        self._build_asset_governance(
            asset_id=dataset_id,
            owner=owner,
            stewards=stewards,
            access=access,
            retention=retention,
            intended_uses=intended,
            training_status=training_status,
            decided_after=prun_end,
        )

    # -- stage 4: data products ------------------------------------------------

    def _build_data_products(self) -> None:
        programmes = sorted(p.id for p in self.config.programmes)
        per_programme = even_split(self.plan.data_product_count, programmes)
        datasets_by_programme: dict[str, list[str]] = {}
        for ds in self.datasets:
            if not ds.is_reference:
                datasets_by_programme.setdefault(ds.programme_id, []).append(ds.id)
        for programme_id in programmes:
            prog_code = self._programme_code(programme_id)
            components = sorted(datasets_by_programme.get(programme_id, []))
            for index in range(per_programme[programme_id]):
                self._build_one_data_product(programme_id, prog_code, components, index + 1)

    def _build_one_data_product(
        self, programme_id: str, prog_code: str, components: list[str], ordinal_n: int
    ) -> None:
        product_id = ids.join("dp", prog_code, "multimodal", ids.ordinal(ordinal_n))
        rng = self._rng("data_product", product_id)
        access = self._programme_default_access(programme_id)
        retention = self._programme_default_retention(programme_id)
        # Deterministic rotating window of component datasets (2-4).
        size = min(len(components), 2 + (ordinal_n % 3))
        start = (ordinal_n * 2) % max(1, len(components))
        chosen = sorted({components[(start + k) % len(components)] for k in range(size)})
        prun_end = at_offset(self.anchor, days=rng.randint(0, 30))

        # Representative study/modality/domain taken from the first component.
        by_id = {d.id: d for d in self.datasets}
        rep = by_id[chosen[0]]
        programme = self._programme_by_id[programme_id]
        owner = self._owner_for_study(rep.study_id, programme_id)
        stewards = self._stewards_for_study(rep.study_id, programme_id)
        contract_ref = ids.join("contract", product_id)
        training_status = "model-training-under-review"
        intended = ["research-only", "internal-analytics"]

        product = DataProduct(
            id=product_id,
            title=f"{programme.display_name} multimodal product {ordinal_n:02d}",
            description=(
                f"Curated multimodal data product integrating {len(chosen)} datasets "
                f"across the {programme.display_name} ({programme.indication})."
            ),
            programme_id=programme_id,
            study_id=rep.study_id,
            scientific_domain=rep.scientific_domain,
            modality=rep.modality,
            modality_group="multimodal",
            lifecycle_stage="published" if ordinal_n % 2 else "curated",
            version=f"1.{ordinal_n % 5}.0",
            owner_ref=owner,
            steward_refs=stewards,
            access_classification=access,
            retention_class=retention,
            intended_uses=intended,
            model_training_status=training_status,
            contract_ref=contract_ref,
            generator_version=self.plan.generator_version,
            generation_seed=self.seed,
            component_dataset_ids=chosen,
        )
        self.data_products.append(product)
        for component in chosen:
            self._add_edge(component, product_id, EdgeType.AGGREGATED_INTO)
        self._build_asset_governance(
            asset_id=product_id,
            owner=owner,
            stewards=stewards,
            access=access,
            retention=retention,
            intended_uses=intended,
            training_status=training_status,
            decided_after=prun_end,
        )

    # -- per-asset governance / quality / contract -----------------------------

    def _build_asset_governance(
        self,
        *,
        asset_id: str,
        owner: str,
        stewards: list[str],
        access: str,
        retention: str,
        intended_uses: list[str],
        training_status: str,
        decided_after: datetime,
    ) -> None:
        rng = self._rng("governance", asset_id)

        reviewed_at = at_offset(decided_after.date(), days=rng.randint(0, 20))
        # Contract.
        self.contracts.append(
            DataContract(
                id=ids.join("contract", asset_id),
                asset_id=asset_id,
                contract_version=f"1.{rng.randint(0, 4)}.0",
                schema_ref=f"schemas/{asset_id}.json",
                sla="99.5% availability; refreshed per release",
                quality_expectations=list(_QUALITY_CHECK_TYPES),
            )
        )
        # Quality checks (all pass).
        for check_type in _QUALITY_CHECK_TYPES:
            self.quality_checks.append(
                QualityCheck(
                    id=ids.join("qc", asset_id, check_type),
                    asset_id=asset_id,
                    check_type=check_type,
                    evidence=f"{check_type} verified for {asset_id}",
                    evaluated_at=reviewed_at,
                )
            )
        # Governance record.
        self.governance_records.append(
            GovernanceRecord(
                id=ids.join("gov", asset_id),
                asset_id=asset_id,
                owner_ref=owner,
                steward_refs=stewards,
                access_classification=access,
                retention_class=retention,
                reviewed_at=reviewed_at,
            )
        )
        # Intended-use records (one per declared use, deterministic order).
        for use in sorted(set(intended_uses)):
            self.intended_use_records.append(
                IntendedUseRecord(
                    id=ids.join("iu", asset_id, use),
                    asset_id=asset_id,
                    intended_use=use,
                    approved=True,
                    decided_at=reviewed_at,
                )
            )
        # Model-training approval.
        self.training_approvals.append(
            ModelTrainingApproval(
                id=ids.join("mta", asset_id),
                asset_id=asset_id,
                status=training_status,
                approver_ref=_TRAINING_APPROVER,
                decided_at=reviewed_at,
                conditions="" if training_status == "model-training-approved" else "see governance",
            )
        )

    def _programme_default_access(self, programme_id: str) -> str:
        for programme in self.config.programmes:
            if programme.id == programme_id and programme.default_access_classification:
                return programme.default_access_classification
        return "confidential"

    def _programme_default_retention(self, programme_id: str) -> str:
        for programme in self.config.programmes:
            if programme.id == programme_id and programme.default_retention_class:
                return programme.default_retention_class
        return "retention-7y"

    # -- stage 5: lineage ------------------------------------------------------

    def _build_lineage(self) -> list[LineageEdge]:
        ordered = sorted(self._edges)
        edges: list[LineageEdge] = []
        for index, (upstream, downstream, edge_type) in enumerate(ordered, start=1):
            edges.append(
                LineageEdge(
                    id=ids.join("edge", ids.ordinal(index)),
                    upstream_id=upstream,
                    downstream_id=downstream,
                    edge_type=EdgeType(edge_type),
                )
            )
        return edges

    # -- assembly --------------------------------------------------------------

    def build(self) -> TruthGraph:
        self._build_subjects()
        self._build_modality_datasets()
        self._build_reference_datasets()
        self._build_data_products()
        lineage = self._build_lineage()
        meta = TruthGraphMeta(
            generator_version=self.plan.generator_version,
            schema_version=TRUTH_SCHEMA_VERSION,
            seed=self.seed,
            epoch_anchor=self.anchor.isoformat(),
        )
        return TruthGraph(
            meta=meta,
            subjects=self.subjects,
            biospecimens=self.biospecimens,
            assays=self.assays,
            instrument_runs=self.instrument_runs,
            pipeline_runs=self.pipeline_runs,
            files=self.files,
            datasets=self.datasets,
            data_products=self.data_products,
            contracts=self.contracts,
            quality_checks=self.quality_checks,
            governance_records=self.governance_records,
            intended_use_records=self.intended_use_records,
            training_approvals=self.training_approvals,
            lineage=lineage,
        )


def _modality_metadata(group_id: str, modality: str, rng: Random) -> dict[str, str | int]:
    """Deterministic, modality-specific descriptive metadata."""
    if group_id == "scrna-seq":
        return {"assay_chemistry": "3prime-v3", "estimated_cells": 1000 * (1 + rng.randint(0, 20))}
    if group_id == "visium-hd":
        return {"bin_size_um": 2, "capture_area": rng.choice(["6.5mm", "11mm"])}
    if group_id == "wgs-wes":
        return {"reference_build": "grch38", "mean_coverage_x": 30 + rng.randint(0, 70)}
    if group_id == "digital-pathology":
        return {"magnification": rng.choice(["20x", "40x"]), "slide_count": 1 + rng.randint(0, 8)}
    if group_id == "radiology":
        dicom = "CT" if modality == "ct-imaging" else "MR"
        return {"dicom_modality": dicom, "series_count": 1 + rng.randint(0, 6)}
    if group_id == "functional-genomics":
        return {"library_type": modality, "guide_count": 1000 * (5 + rng.randint(0, 90))}
    return {"kind": "supporting"}


def generate_truth_graph(config: CanonicalConfig, plan: GenerationPlan, seed: int) -> TruthGraph:
    """Build a complete, correct :class:`TruthGraph` deterministically."""
    return _Builder(config, plan, seed).build()


__all__ = ["generate_truth_graph"]
