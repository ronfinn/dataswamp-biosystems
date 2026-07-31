# Progress

A running log of completed milestones. Newest first.

## Imperfection engine (observed state) — 2026-07-18

Implemented the deterministic imperfection engine: a downstream consumer that
derives a deliberately-imperfect *observed* state from the truth graph, with a
full, machine-readable ledger of every injected defect for agent benchmarking.

- **Package (`src/dataswamp_biosystems/observed/`):** taxonomy/record models
  (defect instance, mutation, expected finding, expected remediation, observed
  meta), an in-code defect-definition registry (41 rules across all 12
  categories) with a registry validator, six maturity profiles, a truth-graph
  index with a mutable JSON working copy, the deterministic engine, an on-disk
  injection orchestrator (checksums + path safety), an atomic writer, and an
  output validator. Depends only on `company/` and `truth/`.
- **Reads truth from disk, never mutates it:** `inject-defects` reads the truth
  graph via its manifest, reconstructs the typed graph from the seed and verifies
  it byte-for-byte against the on-disk shards, checksums every truth input before
  processing, and verifies the checksums unchanged after generation and writing —
  recording them in `truth-inputs.json`. Output may not resolve inside the truth
  directory. Mutations apply to independent JSON copies; a guard test proves both
  the truth files and the truth object are unchanged. The observed graph is
  relaxed JSON so defects can express states the strict truth models forbid.
- **Ledgers:** every applied defect yields one `DefectInstance`, one+
  `MutationRecord` (truth `before`/observed `after`, plus severity, seed, profile,
  selection rationale, fix eligibility, approval requirement, and metadata-vs-
  physical manifestation), exactly one `ExpectedFinding` (with `match_fields` for
  prose-independent evaluation, message semantics, and a remediation link), and
  one+ `ExpectedRemediation` (with a `truth_reference`) — all referentially
  intact. The observed graph itself carries no defect annotations.
- **Taxonomy:** metadata completeness, semantic quality, ownership/stewardship,
  naming/versioning, governance/classification, licensing/intended-use,
  lineage/provenance, schema/structural, modality-specific scientific metadata,
  AI/training readiness, lifecycle/staleness, and physical file integrity
  (observed-graph-only). Includes every mandated example (missing/wrong owner,
  generic description, missing genome build, mixed gene ids, H5AD counts layer,
  spatial coords OOB, VCF index, pathology source-slide, stale review,
  restricted-as-internal, absent training approval, cross-study edge, duplicate
  final versions, QC-contradicted certification, checksum mismatch, missing file).
- **Profiles:** `gold` (0 defects) → `mostly-good` → `typical` → `poor` →
  `catastrophic`, plus `demo` (~100–200 defects across all 12 categories with a
  healthy control population). Rates are the only knob; a control partition,
  per-entity cap, conflict ledger, and hard global cap keep runs reproducible and
  non-contradictory.
- **Determinism/safety:** structural — sorted rule/entity iteration, per-selection
  seeded RNG, single canonical serializer. `validate-observed` regenerates and
  byte-compares all seven outputs, then checks structural, fidelity, and
  non-contamination invariants (but not truth invariants — the observed graph is
  meant to be broken).
- **Output (git-ignored `generated/observed/`):** `observed-graph.json`, the four
  ledger `.jsonl` files, `profile-summary.json` (with category/severity/rule/
  modality distributions), `truth-inputs.json`, and `summary.md`.
- **CLI:** `dataswamp list-defects`, `dataswamp validate-defects`, `dataswamp
  inject-defects --truth generated/truth/truth-graph.json` (`--seed`, `--profile`,
  `--config-dir`, `--output-dir`, `--force`), and `dataswamp validate-observed`.
- **Tests (`tests/observed/`):** registry, engine, injection, validation, and CLI
  behaviour.
- **Docs:** [observed-state.md](observed-state.md),
  [ADR 0003](adr/0003-imperfection-engine.md), README, CLAUDE.md.
- **Deliberately excluded:** scenario packs, DataHub, LLMs, assessment agents,
  automatic remediation, write-back, and estate byte corruption.

## Scientific-file estate — 2026-07-18

Implemented the deterministic, lightweight scientific-file generation layer: a
downstream consumer that materializes small, genuinely-readable example files
for the truth graph's assets.

- **Package (`src/dataswamp_biosystems/estate/`):** manifest/sidecar Pydantic
  models, three generation profiles, per-format content writers with a registry,
  a truth-consuming generator, an atomic path-safe budget-capped writer, and a
  validator. Depends only on `company/` and `truth/`.
- **Formats:** genuine and re-readable — H5AD (AnnData), Parquet (pyarrow),
  OME-TIFF (tifffile, reads back as OME), PNG (Pillow), GeoJSON, VCF, BED, Matrix
  Market, CSV, TSV, JSON, YAML, JSONL, gzip text, and tiny FASTQ. Declared
  placeholders (never faked as valid binaries) for BAM, CRAM, DICOM, SVS, and
  large Zarr — each a stub plus a `.placeholder.json` sidecar recording intended
  format, represented logical size, and limitations.
- **Profiles:** `tiny` (~100 files, <50 MB, full format coverage), `demo`
  (~1,175 files, <500 MB), `stress` (~10,800 catalogue-shard records, minimal
  physical content). Each carries a hard byte budget enforced mid-generation;
  content sizes are decoupled from the truth graph's represented sizes.
- **Determinism:** structural — sorted iteration, per-file seeded RNG keyed by
  stable id, no wall-clock. gzip `mtime=0`, fixed OME-TIFF UUID, timestamp-free
  HDF5/Parquet. Byte-identical across processes and `PYTHONHASHSEED` values.
- **Integrity/safety:** SHA-256 per file computed after writing; represented
  logical size recorded separately from physical size; path-containment checks;
  atomic staged output; `validate-files` regenerates and byte-compares the
  manifest, then verifies checksums, asset references, and placeholder sidecars.
- **Output (git-ignored `generated/estate/`):** `files/` tree,
  `file-manifest.jsonl`, `generation-summary.json`, `summary.md`.
- **CLI:** `dataswamp generate-files` (`--profile`, `--seed`, `--output-dir`,
  `--force`) and `dataswamp validate-files`.
- **Dependencies:** added `numpy`, `pyarrow`, `Pillow`, `tifffile`, `anndata`.
- **Docs:** [file-generation.md](file-generation.md), README, CLAUDE.md.
- **Deliberately excluded:** injected defects, observed state, DataHub, agents;
  genuine DICOM/Zarr (declared placeholders per scope).

## Deterministic truth graph — 2026-07-18

Implemented the deterministic truth-graph generator: the complete, correct
synthetic scientific/governance state generated from the canonical model.

- **Package (`src/dataswamp_biosystems/truth/`):** entity models (14 scientific
  and governance entities, all `synthetic=true`, frozen + `extra="forbid"`), a
  seeded generator, plan loader/allocation, invariant validator, canonical
  serializer, and writer — all catalogue-independent (depend only on `company/`).
  Each catalogue asset is self-describing (title, description, programme, study,
  domain, modality, lifecycle, version, owner, stewards, classification,
  retention, intended uses, training status, contract ref, quality status,
  provenance run, generator version, seed), with governance evidence also held as
  separate records.
- **Validation (pre-write):** unique ids, complete references, valid controlled
  vocabularies, programme–study and subject–biospecimen–assay relationships,
  lifecycle transitions, exact counts, acyclic lineage with no self-lineage,
  per-asset governance/quality/contract completeness, denormalised-vs-record
  consistency, supported modality metadata, temporal monotonicity, and the
  synthetic/domain locks. Output is staged and swapped in atomically, so a failed
  run never leaves a partial directory and prior output is restored.
- **Config:** a new `config/truth/generation-plan.yaml` fixing exact target
  counts, consuming the company model's vocabularies and study modality lists.
- **Output (git-ignored `generated/truth/`):** JSONL shards, a `truth-graph.json`
  manifest with per-shard SHA-256 digests, and `summary.md`. For any seed: 60
  subjects, 165 datasets (155 modality + 10 reference), 15 data products = 180
  catalogue assets.
- **Determinism:** structural — sorted iteration, per-entity seeded RNG keyed by
  stable id, fixed epoch anchor (no wall-clock), integer byte sizes, single
  canonical serializer. Byte-identical across processes and `PYTHONHASHSEED`
  values, verified by tests.
- **CLI:** `dataswamp generate-truth` (writes + validates the graph) and
  `dataswamp validate-truth` (invariants + byte-for-byte regeneration check).
- **Tests (`tests/truth/`):** counts, allocation, referential integrity, DAG
  acyclicity, completeness, in-process and cross-process determinism, and CLI
  behaviour.
- **Deliberately excluded:** injected defects, observed state, scientific file
  contents, scenarios, DataHub, and agents.

## Canonical company model — 2026-07-18

Implemented the canonical, catalogue-independent company model.

- **Config (`config/`):** one company; 3 programmes (NSCLC, TNBC, colorectal);
  6 studies (2 per programme); 7 teams (scientific, platform, governance);
  13 fictional people with roles; 9 ownership and 7 stewardship assignments;
  8 controlled vocabularies (51 terms total). All identities fictional under
  `dataswamp.example`.
- **Models (`src/dataswamp_biosystems/company/`):** Pydantic v2 models grouped
  by concern (identifiers, vocabularies, entities, relationships, generation
  config, assembled config, loader, errors); `extra="forbid"` and typed slug
  identifiers throughout; `schema_version` on every file.
- **Validation:** cross-file loader detecting duplicate ids, duplicate emails,
  invalid domains, unresolved programme/team/person references,
  invalid vocabulary values, and dangling owner/steward assignments — all
  issues collected before failing, with project-specific errors.
- **CLI:** `dataswamp validate-config` prints deterministic entity counts on
  success (exit 0), reports actionable issues (exit 1), and distinguishes load
  failures (exit 2).
- **Docs:** [domain-model.md](domain-model.md),
  [ADR 0001](adr/0001-catalogue-independent-canonical-model.md), README.
- **Deliberately excluded:** subjects, biospecimens, assays, datasets, truth
  graphs, scientific files, defects, scenarios, DataHub, and agents.

## Repository foundation

Python packaging (uv, hatchling, src-layout), dev tooling (ruff, mypy strict,
pytest, pre-commit, CI), and a minimal Typer CLI (`dataswamp version`).
