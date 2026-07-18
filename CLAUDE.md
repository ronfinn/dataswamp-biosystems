# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

Data Swamp Biosystems is an open, entirely fictional synthetic oncology data
estate and governance benchmark. It provides a realistic-looking but wholly
invented oncology research data landscape for exercising data governance,
cataloguing, lineage, and quality patterns.

## Synthetic-data safety (non-negotiable)

- **No real patient or proprietary data, ever.** Every person, institution,
  study, dataset, and identifier in this repository must be fictional and
  synthetically generated, at every milestone, with no exceptions.
- Use the `dataswamp.example` domain for all fictional email addresses,
  institution domains, and similar identities. Never use a real
  organization's domain, a real person's name, or a real dataset identifier.
- If you are ever asked to import, reference, or derive content from a real
  clinical dataset, real patient records, or real proprietary research data,
  stop and raise the concern instead of proceeding.

## Current status

This repository contains the **repository foundation** (Python packaging, dev
tooling, minimal CLI), the **canonical company model** (the fictional company,
programmes, studies, teams, people, ownership/stewardship, and controlled
vocabularies in `config/`, with Pydantic models and validation in
`src/dataswamp_biosystems/company/` and a `dataswamp validate-config` command),
the **deterministic truth graph** (the complete, correct synthetic
scientific/governance state generated from that model by
`src/dataswamp_biosystems/truth/`, emitted under git-ignored `generated/truth/`
via `dataswamp generate-truth` and checked by `dataswamp validate-truth`), and
the **scientific-file estate** (small, genuinely-readable example files
materialized for the truth graph's assets by
`src/dataswamp_biosystems/estate/`, emitted under git-ignored
`generated/estate/` via `dataswamp generate-files` and checked by `dataswamp
validate-files`, with explicitly-declared placeholders for heavy binaries). See
`docs/domain-model.md`, `docs/truth-graph-schema.md`, and
`docs/file-generation.md`.

All three layers are deliberately catalogue-independent. There is no imperfection
engine / observed state, no scenario-pack layer, no assessment agents, and no
DataHub integration yet.

Do not implement future-milestone capabilities (below) speculatively. Add
them only when a task explicitly scopes them, and do not create placeholder
modules or packages "to anticipate" that future work.

## Commands

```bash
uv sync                        # install/sync the environment
uv run dataswamp version       # run the CLI
uv run dataswamp validate-config  # validate the canonical config in config/
uv run dataswamp generate-truth --seed 20260717  # generate the truth graph
uv run dataswamp validate-truth   # validate a generated truth graph
uv run dataswamp generate-files --seed 20260717 --profile tiny  # generate the file estate
uv run dataswamp validate-files   # validate a generated file estate
uv run pytest                  # run tests
uv run ruff check .            # lint
uv run ruff format --check .   # format check
uv run mypy src                # type check
uv run pre-commit run --all-files  # all local quality hooks
```

Run a single test with `uv run pytest tests/test_cli.py::test_version_command_exits_successfully`.

## Architecture

- `src/dataswamp_biosystems/` — the single top-level package (src-layout).
  - `cli.py` — Typer-based CLI, exposed as the `dataswamp` console script.
  - `company/` — the canonical company model: identifiers, controlled
    vocabularies, entities, relationships, generation config, the assembled
    `CanonicalConfig`, the YAML loader, and project-specific errors. Independent
    of DataHub.
  - `truth/` — the deterministic truth-graph generator: scientific/governance
    entities, seeded RNG and date helpers, the generation-plan loader and
    allocation, the generator pipeline, canonical serializer, writer, and
    invariant validator. Depends only on `company/`, never on DataHub. See
    `docs/truth-graph-schema.md`.
  - `estate/` — the deterministic scientific-file generator: manifest/sidecar
    entities, generation profiles, per-format content writers + registry, the
    truth-consuming generator, atomic writer (path-safe, budget-capped), and
    validator. Depends only on `company/` and `truth/`, never on DataHub. See
    `docs/file-generation.md`.
- `config/` — hand-authored canonical business configuration (YAML) plus
  `config/vocabularies/` and `config/truth/generation-plan.yaml`. Tracked;
  distinct from the git-ignored `generated/`.
- `tests/` — mirrors the package for test discovery; `tests/company/`,
  `tests/truth/`, and `tests/estate/` cover the model, generators, invariants,
  file contents, and CLI commands.

### Architectural independence from DataHub

DataHub integration is a future, optional milestone. Core generation and
governance logic must never depend on DataHub types, clients, or schemas.
Any future DataHub integration should be an adapter layer that consumes this
project's own manifests/APIs — not the other way around.

### Separation of truth and observed state

The deterministic "truth graph" (what is correct and complete) is implemented in
`src/dataswamp_biosystems/truth/`. A future "observed state" (what a catalog or
governance tool reports after defects, drift, or partial ingestion) will be a
*separate* representation derived from the truth graph, not the truth graph
itself. Keep these two distinct in code and on disk — do not conflate a
generator's ground truth with a consumer's view of it, and never let defect or
observed-state concerns leak into the truth generator. See
`docs/adr/0002-truth-vs-observed-state.md`.

### Deterministic generation (requirement)

The truth-graph generator is seeded and deterministic: the same config,
generator version, and seed produce byte-identical structured output (JSONL
shards + a manifest with per-shard digests). Any future generator (scientific
files, defects, etc.) must uphold the same guarantee. Do not introduce
non-deterministic sources (wall-clock time, unseeded randomness, unordered
set/dict iteration relied upon for output order) into generator code.

### Generated outputs stay untracked

Any synthetic output a future generator produces belongs under `generated/`,
which is git-ignored. Never commit generated data, manifests, or files —
only the generator code and its tests are tracked.

## Test and quality requirements

All of the following must pass with zero errors before considering a change
complete:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pre-commit run --all-files
```

New code (generators, CLI commands, governance logic) needs tests covering
its behavior — for future deterministic generators, that includes explicit
tests for determinism (same seed → identical output), record counts, and
referential integrity, not just happy-path execution.

## Things Claude must never do in this repository

- **Never create a Git commit automatically.** Leave staged/unstaged changes
  for the user to review and commit themselves, unless a task explicitly
  asks for a commit.
- Never add DataHub as a dependency or import until a task explicitly scopes
  DataHub integration.
- Never generate scientific/synthetic datasets until a task explicitly
  scopes data generation.
- Never add placeholder packages or modules for capabilities that haven't
  been designed yet.
