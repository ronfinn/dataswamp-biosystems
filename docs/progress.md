# Progress

A running log of completed milestones. Newest first.

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
