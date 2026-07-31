# Canonical company domain model

Data Swamp Biosystems is a wholly fictional oncology biotechnology company.
This document describes its canonical model: the entities, controlled
vocabularies, relationships, and validation rules that later generators,
scenarios, catalogue adapters, and governance tooling reuse.

Every identity is fictional. All email, institution, and identity domains are
`dataswamp.example`. No real organisation, person, study, or dataset is
represented.

## Where it lives

- **Business configuration:** `config/*.yaml` (tracked; authored by hand).
- **Controlled vocabularies:** `config/vocabularies/*.yaml`.
- **Python models & loader:** `src/dataswamp_biosystems/company/`.
- **CLI:** `dataswamp validate-config`.

The model is deliberately independent of any catalogue or governance tool
(e.g. DataHub). See [ADR 0001](adr/0001-catalogue-independent-canonical-model.md).

## Entities

| Entity | File | Key fields |
| --- | --- | --- |
| Company | `company.yaml` | `id`, `legal_name`, `display_name`, `domain` |
| Programme | `programmes.yaml` | `id`, `indication`, optional vocabulary defaults |
| Study | `studies.yaml` | `id`, `programme_id`, vocabulary references |
| Team | `teams.yaml` | `id`, `team_type`, optional `programme_id` |
| Person | `people.yaml` | `id`, `email`, `role`, `team_id` |
| OwnershipAssignment | `ownership.yaml` | subject (programme/study/team) → owner (team/person) |
| StewardshipAssignment | `stewardship.yaml` | subject (programme/study) → steward (person), typed |

### Relationships

```
Company ──owns──▶ Programme ──contains──▶ Study
                                  ▲
Team (scientific) ─aligned to─────┘
Team (platform | governance) ── cross-programme (no programme_id)
Person ──member_of──▶ Team,  ──holds──▶ Role

OwnershipAssignment:   (team | person) ──owns──▶ (programme | study | team)
StewardshipAssignment: (person) ──stewards[type]──▶ (programme | study)
```

Cardinality: each study belongs to exactly one programme; each person has one
primary team; stewardship is many-to-many.

## Controlled vocabularies

Each vocabulary is a list of terms with a stable `id` referenced elsewhere.

| Vocabulary | File | Notes |
| --- | --- | --- |
| Access classifications | `access-classifications.yaml` | ordinal `sensitivity_level` |
| Retention classes | `retention-classes.yaml` | ISO-8601 `duration`, or null for permanent |
| Scientific domains | `scientific-domains.yaml` | |
| Modalities | `modalities.yaml` | each names its `scientific_domain` |
| Lifecycle stages | `lifecycle-stages.yaml` | explicit `order` |
| Intended uses | `intended-uses.yaml` | |
| Model-training approval statuses | `training-approval-statuses.yaml` | |
| Roles | `people.yaml` (`roles:`) | |
| Stewardship types | `stewardship-types.yaml` | |

## Identifier conventions

Lowercase kebab-case ASCII slugs matching `^[a-z0-9]+(-[a-z0-9]+)*$`, with a
typed prefix per family: `prog-`, `study-`, `team-`, `person-`, `own-`,
`stew-`. Identifiers are **stable** — renaming a display label never changes an
id, because future generators key on these strings. Satire may appear in
descriptive prose but never in identifiers.

## Validation rules

Field-level (Pydantic): id pattern, required fields, email format, no unknown
fields (`extra="forbid"`), non-empty required lists, enum membership.

Cross-file (loader; all issues collected before failing):

1. **Duplicate ids** within every collection and vocabulary.
2. **Duplicate emails** across people.
3. **Domain lock** — company `domain` and every person `email` domain must be
   `dataswamp.example`.
4. **Reference resolution** — study→programme, person→team, team→programme,
   and every ownership/stewardship subject, owner, and steward.
5. **Controlled-value resolution** — every vocabulary reference (including
   modality→scientific-domain and person→role) resolves to a known term.
6. **Per-record structure** — scientific teams must set `programme_id`;
   platform and governance teams must not.

Dataset-shape expectations (three programmes, six studies, two per programme)
are asserted by the test suite against the authored configuration rather than
enforced by the loader, so that compact test fixtures remain valid.

## Schema versioning

Every file carries `schema_version: 1`, and the assembled model carries a
`SCHEMA_VERSION` constant. Both are checked on load, giving a forward-compatible
hook for future migrations.

## Current entity counts

3 programmes · 6 studies · 7 teams · 13 people · 9 ownership assignments ·
7 stewardship assignments · 56 vocabulary terms.

## Truth graph

The **truth graph** is the complete and correct synthetic scientific/governance
state generated *from* this canonical model — the ground truth a future observed
graph and benchmarks are scored against. It lives in
`src/dataswamp_biosystems/truth/` and is emitted (git-ignored) under
`generated/truth/` by `dataswamp generate-truth`. The on-disk schema is
documented in [truth-graph-schema.md](truth-graph-schema.md); the truth-vs-
observed separation in [ADR 0002](adr/0002-truth-vs-observed-state.md).

### Scientific and governance entities

Subject/ExperimentalModel · Biospecimen · Assay · InstrumentRun · PipelineRun ·
PhysicalFileRecord · Dataset · DataProduct · DataContract · QualityCheck ·
GovernanceRecord · IntendedUseRecord · ModelTrainingApproval · LineageEdge.

Provenance is topological: subject → biospecimen → assay → instrument run →
(pipeline run) → files → dataset; datasets aggregate into multimodal data
products. Every entity carries `synthetic: true`.

Each catalogue asset (dataset and data product) is **self-describing**: it
directly carries title, description, programme, study, scientific domain,
modality, lifecycle stage, version, owner, stewards, access classification,
retention class, intended uses, model-training status, contract reference,
quality status, provenance run, and the generator version and seed. The
authoritative governance *evidence* also exists as separate records
(GovernanceRecord, DataContract, QualityCheck, IntendedUseRecord,
ModelTrainingApproval); the validator checks the denormalised summary agrees
with those records. `owner_ref`/`steward_refs` resolve into the company model's
teams/people. Cross-modal reference/supporting datasets and multimodal products
take a representative study/modality from a dataset they aggregate, so every
catalogue entry is complete.

### Counts and modality allocation

The plan (`config/truth/generation-plan.yaml`) fixes exact targets. For the
authored configuration and any seed: **60 subjects** (10 per study), **165
datasets** (155 modality + 10 shared reference), **15 data products** — **180
catalogue-level assets**. Modality dataset counts: scRNA-seq 35 · Visium HD 25 ·
WGS/WES 25 · digital pathology 30 · radiology 20 · Perturb-seq/CRISPR-screen 20.
Each group's total is spread across its studies by a deterministic
largest-remainder split (remainder to the lowest-sorted study ids). The
canonical config was extended to back these: the `spatial-transcriptomics` and
`functional-genomics` scientific domains, the `visium-hd`, `perturb-seq`, and
`crispr-screen` modalities, and broadened per-study modality lists.

### Determinism

`generate-truth --seed S` run twice against the same config and generator
version produces byte-identical output. Determinism is structural: sorted
iteration everywhere, per-entity seeded RNG keyed by stable id (never global
RNG or set-iteration order), all dates derived from a fixed `epoch_anchor` (no
wall-clock), integer byte sizes (no float formatting), and a single canonical
serializer (sorted keys, UTF-8, `\n`, records sorted by id). The
`truth-graph.json` manifest records per-shard SHA-256 digests; `validate-truth`
regenerates from the recorded seed and checks both invariants and a
byte-for-byte match against the on-disk shards.

### Output layout (`generated/truth/`)

`truth-graph.json` (manifest) · `subjects.jsonl` · `biospecimens.jsonl` ·
`assays.jsonl` · `runs.jsonl` · `files.jsonl` · `assets.jsonl` ·
`contracts.jsonl` · `quality.jsonl` · `governance.jsonl` · `lineage.jsonl` ·
`summary.md`. Heterogeneous shards use a discriminator field: `runs.jsonl`
(`run_kind`), `assets.jsonl` (`asset_type`), `governance.jsonl` (`record_type`).
