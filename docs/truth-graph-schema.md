# Truth-graph schema

The truth graph is the complete, correct synthetic scientific and governance
state generated from the [canonical company model](domain-model.md). It is
emitted (git-ignored) under `generated/truth/` by `dataswamp generate-truth` and
re-checked by `dataswamp validate-truth`. This document describes the on-disk
schema; the authoritative source is the Pydantic models in
`src/dataswamp_biosystems/truth/entities.py` and `graph.py`.

Every entity carries `id` (a canonical slug) and `synthetic: true`. All money-
free sizes are integer bytes; all timestamps are UTC ISO-8601 with a trailing
`Z`; all dates are `YYYY-MM-DD`. Records within a shard are sorted by `id`.

## Files

```text
generated/truth/
├── truth-graph.json     # manifest: meta, counts, per-shard record counts + SHA-256
├── subjects.jsonl       # Subject / ExperimentalModel
├── biospecimens.jsonl   # Biospecimen
├── assays.jsonl         # Assay
├── runs.jsonl           # InstrumentRun + PipelineRun  (discriminator: run_kind)
├── files.jsonl          # PhysicalFileRecord
├── assets.jsonl         # Dataset + DataProduct         (discriminator: asset_type)
├── contracts.jsonl      # DataContract
├── quality.jsonl        # QualityCheck
├── governance.jsonl     # GovernanceRecord + IntendedUseRecord + ModelTrainingApproval
│                        #                                (discriminator: record_type)
├── lineage.jsonl        # LineageEdge
└── summary.md           # human-readable counts and per-modality breakdown
```

## Manifest (`truth-graph.json`)

```jsonc
{
  "meta": {
    "generator_version": "1.0.0",   // from the generation plan
    "schema_version": 1,            // truth-graph schema version
    "seed": 20260717,               // the seed used
    "epoch_anchor": "2024-01-08"    // fixed date all timestamps derive from
  },
  "counts": { "subjects": 60, "datasets": 165, ... },
  "files": { "subjects.jsonl": { "records": 60, "sha256": "…" }, ... }
}
```

The per-shard `sha256` makes the manifest a determinism/integrity tripwire:
`validate-truth` regenerates from `meta.seed` and confirms both the invariants
and a byte-for-byte match against the on-disk shards.

## Entities

### Subject (`subjects.jsonl`)
`kind` (`human_subject` | `experimental_model`), `study_id`, `programme_id`,
`subject_code`, `origin_date`. Experimental models additionally set
`model_system`, `cell_line`, `perturbation_library`; human subjects leave these
null.

### Biospecimen (`biospecimens.jsonl`)
`subject_id`, `study_id`, `specimen_type`, `collected_on`, `preservation`.

### Assay (`assays.jsonl`)
`biospecimen_id`, `study_id`, `modality` (a controlled-vocabulary term),
`platform`, `assayed_on`.

### Runs (`runs.jsonl`)
`run_kind` discriminates. **InstrumentRun**: `assay_id`, `instrument_model`,
`run_status`, `started_at`, `completed_at`. **PipelineRun**: `pipeline_name`,
`pipeline_version`, `input_ids` (upstream runs/datasets), `run_status`,
`started_at`, `completed_at`. In the truth graph every `run_status` is
`succeeded`.

### PhysicalFileRecord (`files.jsonl`)
`producing_run_id`, `dataset_id`, `relative_path`, `file_format`,
`physical_bytes`, `checksum`. The checksum is a deterministic digest of the
file's *metadata* — no scientific file contents exist at this milestone.

### Catalogue assets (`assets.jsonl`)
`asset_type` discriminates `dataset` vs `data_product`. Both share the
self-describing catalogue/governance fields:

`title`, `description`, `programme_id`, `study_id`, `scientific_domain`,
`modality`, `modality_group`, `lifecycle_stage`, `version`, `owner_ref`,
`steward_refs`, `access_classification`, `retention_class`, `intended_uses`,
`model_training_status`, `contract_ref`, `quality_status`, `generator_version`,
`generation_seed`.

- **Dataset** adds `physical_bytes`, `logical_bytes` (represented/uncompressed,
  always ≥ physical), `record_count`, `file_ids`, `provenance_run_id`,
  `modality_metadata`, and `is_reference`. Modality datasets set `modality_group`
  to a benchmark group (`scrna-seq`, `visium-hd`, `wgs-wes`, `digital-pathology`,
  `radiology`, `functional-genomics`); shared reference/supporting datasets set
  `is_reference: true` and `modality_group: reference`, taking a representative
  study and modality from a dataset they aggregate so the catalogue entry is
  complete.
- **DataProduct** adds `component_dataset_ids` and sets `modality_group:
  multimodal`, taking its representative study/modality/domain from its first
  component.

`owner_ref`, `steward_refs`, `model_training_status`, and `contract_ref` are
denormalised summaries; the authoritative evidence lives in the governance and
contract records, and the validator checks the two agree.

### DataContract (`contracts.jsonl`)
`asset_id`, `contract_version`, `schema_ref`, `sla`, `quality_expectations`.

### QualityCheck (`quality.jsonl`)
`asset_id`, `check_type`, `status` (`pass` throughout the truth graph),
`evidence`, `evaluated_at`.

### Governance records (`governance.jsonl`)
`record_type` discriminates. **GovernanceRecord**: `asset_id`, `owner_ref`,
`steward_refs`, `access_classification`, `retention_class`, `reviewed_at`.
**IntendedUseRecord**: `asset_id`, `intended_use`, `approved`, `decided_at`.
**ModelTrainingApproval**: `asset_id`, `status`, `approver_ref`, `decided_at`,
`conditions`.

### LineageEdge (`lineage.jsonl`)
`upstream_id`, `downstream_id`, `edge_type`. Edges form a DAG spanning
subject → biospecimen → assay → instrument run → (pipeline run) → file →
dataset → data product. No edge points a node at itself.

## Validated invariants

Before any output is written, `validate_truth_graph` checks (collecting all
problems, then failing): unique slug ids; complete references (including
owner/steward into the company model); valid controlled vocabularies; valid
programme–study and subject–biospecimen–assay relationships; lifecycle-transition
validity (raw/ingested produced by an instrument run, later stages by a pipeline
run); exact counts (per modality group and overall); an acyclic lineage DAG with
no self-lineage and every asset reachable from upstream; per-asset completeness
of contract, quality, governance, intended-use, and training records;
denormalised-vs-record consistency; supported modality-metadata keys; temporal
monotonicity along provenance; `logical_bytes ≥ physical_bytes`; `synthetic ==
true` everywhere; and the `dataswamp.example` domain lock.
