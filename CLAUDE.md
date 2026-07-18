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

This repository currently contains **repository foundation only**: Python
packaging, dev tooling, and a minimal CLI. There is no company/programme
model, no truth-graph generator, no scientific file generation, and no
DataHub integration yet.

Do not implement future-milestone capabilities (below) speculatively. Add
them only when a task explicitly scopes them, and do not create placeholder
modules or packages "to anticipate" that future work.

## Commands

```bash
uv sync                        # install/sync the environment
uv run dataswamp version       # run the CLI
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
  - No internal subpackages exist yet; future milestones will add them once
    their designs are settled, rather than being pre-guessed here.
- `tests/` — mirrors the package for test discovery.

### Architectural independence from DataHub

DataHub integration is a future, optional milestone. Core generation and
governance logic must never depend on DataHub types, clients, or schemas.
Any future DataHub integration should be an adapter layer that consumes this
project's own manifests/APIs — not the other way around.

### Separation of truth and observed state (forthcoming principle)

Future milestones will introduce a deterministic "truth graph" (what is
correct and complete) separate from "observed state" (what a catalog or
governance tool reports after defects, drift, or partial ingestion are
introduced). When that work begins, keep these two representations distinct
in code and on disk — do not conflate a generator's ground truth with a
consumer's view of it.

### Deterministic generation (forthcoming requirement)

Any future generator (truth graph, scientific files, defects, etc.) must be
seeded and deterministic: the same seed must produce byte-identical
structured outputs (JSON/JSONL manifests) across runs. Do not introduce
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
- **Never silently remediate injected defects.** Once a future milestone
  introduces intentional defects/drift for benchmark purposes, do not "fix"
  them as a side effect of unrelated work — defects are test fixtures, not
  bugs.
- Never add DataHub as a dependency or import until a task explicitly scopes
  DataHub integration.
- Never generate scientific/synthetic datasets until a task explicitly
  scopes data generation.
- Never add placeholder packages or modules for capabilities that haven't
  been designed yet.
