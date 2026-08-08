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
validate-files`, with explicitly-declared placeholders for heavy binaries), and
the **imperfection engine** (a deliberately-imperfect *observed state* derived
from the truth graph by `src/dataswamp_biosystems/observed/`, with a full
machine-readable ledger of every injected defect and its expected finding and
remediation, emitted under git-ignored `generated/observed/` via `dataswamp
inject-defects` — which reads the truth graph from disk, checksums it, and
verifies it is unmodified — with `dataswamp list-defects`/`validate-defects` for
the registry and `dataswamp validate-observed` to re-check output), the
**adversarial scenario engine** (`--difficulty adversarial`, which constructs
near-miss controls, decoys and overlapping evidence in
`src/dataswamp_biosystems/observed/scenarios.py` and emits the privileged
`scenarios.jsonl`/`scenario-transformations.jsonl` answer key), and the
**evaluation engine** (a deterministic scorer in
`src/dataswamp_biosystems/evaluation/` that consumes an emitted observed state as
ground truth and a versioned JSONL prediction file, emitting confusion-matrix and
remediation reports under git-ignored `generated/evaluation/` via `dataswamp
evaluate`), the **run-comparison layer** (a read-only differ in
`src/dataswamp_biosystems/comparison/` that consumes two *already-emitted*
evaluation directories and reports metric deltas, rule-level regressions,
control-preservation regressions and remediation changes, emitted under
git-ignored `generated/comparison/` via `dataswamp compare-runs`), the
**benchmark bundle** (a versioned, checksummed, portable
directory packaged from emitted layer output by
`src/dataswamp_biosystems/bundle/` via `dataswamp build-bundle`, checked by
`dataswamp verify-bundle`, and read through the stable streaming `BundleReader`),
and the **DataHub adapter** (a deterministic Metadata Change Proposal emitter in
`src/dataswamp_biosystems/adapters/datahub/` via `dataswamp export-datahub`, plus
a **live path** strictly downstream of that emitted export — `dataswamp
ingest-datahub` transmits it verbatim to a running catalogue and `dataswamp
verify-ingestion` reads it back and reports completeness, fidelity, containment
and observed-mode non-leakage as four separate claims, verified against a pinned
real DataHub Quickstart by the optional, non-blocking `live-datahub` workflow),
and
the **release surface** (a `dataswamp demo` command running the whole workflow
into one directory, committed example submissions under `examples/predictions/`,
and the canonical `config/` tree plus those examples shipped *inside* the
distribution so an installed package needs no checkout). See
`docs/domain-model.md`, `docs/truth-graph-schema.md`, `docs/file-generation.md`,
`docs/observed-state.md`, `docs/difficulty-tiers.md`,
`docs/adversarial-scenarios.md`, `docs/evaluation.md`, `docs/bundles.md`,
`docs/datahub.md`, `docs/run-comparison.md`, and `docs/public-api.md`.

All five generation layers, the comparison layer and the bundle packager are
deliberately catalogue-independent. The observed layer never mutates the truth
graph, the evaluation layer mutates nothing at all, the comparison layer writes
nothing into either run it reads, and the bundle layer copies emitted bytes
without reinterpreting them. The DataHub adapter is the *only* place a
catalogue is named, it consumes bundles rather than generators, and no DataHub
package is a dependency. There is no scenario-pack layer and no assessment
agents yet.

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
uv run dataswamp list-defects      # list the defect registry
uv run dataswamp validate-defects  # validate the defect registry
uv run dataswamp inject-defects --truth generated/truth/truth-graph.json --seed 20260717 --profile demo  # derive observed state
uv run dataswamp inject-defects --truth generated/truth --profile demo --difficulty adversarial  # the adversarial tier
uv run dataswamp validate-observed  # validate a generated observed state
uv run dataswamp evaluate --observed-dir generated/observed --predictions predictions.jsonl  # score an agent
uv run dataswamp compare-runs --baseline generated/eval-v1 --candidate generated/eval-v2 --output-dir generated/comparison  # diff two scored runs
uv run dataswamp build-bundle --output-dir dist/benchmark --release v0.1.0  # package a portable bundle
uv run dataswamp verify-bundle dist/benchmark      # verify a bundle end to end
uv run dataswamp export-datahub --bundle dist/benchmark --mode observed --output-dir export/datahub
uv run dataswamp ingest-datahub --export-dir export/datahub --dry-run   # plan only; opens no socket
uv run dataswamp verify-ingestion --export-dir export/datahub --output-dir generated/roundtrip
uv run dataswamp demo --output-dir ./dataswamp-demo  # the whole workflow, end to end
uv run pytest                  # run tests
uv run ruff check .            # lint
uv run ruff format --check .   # format check
uv run mypy src                # type check
uv run pre-commit run --all-files  # all local quality hooks
```

Byte-determinism is guaranteed for the committed `uv.lock` on Python 3.12/3.13;
across the wider declared dependency range only the truth and observed layers are
byte-identical. The committed golden digests
(`tests/golden/canonical-digests.json`) are **never** rewritten by `pytest` —
regenerate them deliberately with
`uv run --frozen python scripts/update_golden_digests.py --confirm --reason ... --cause ...`
and follow the reviewer checklist in `docs/reproducibility.md`.

Run a single test with `uv run pytest tests/test_cli.py::test_version_command_exits_successfully`.

## Architecture

- `src/dataswamp_biosystems/` — the single top-level package (src-layout).
  - `cli.py` — Typer-based CLI, exposed as the `dataswamp` console script.
  - `paths.py` — the shared output-directory containment policy. Generation
    replaces a whole directory, so every command that writes one must call
    `ensure_safe_output_dir` before staging: it refuses an output that is,
    contains, or sits inside a protected input (config dir, truth dir — and so
    the repository root). Comparison uses `resolve_path`, which resolves
    symlinks and `..` *and* canonicalises each existing component's on-disk
    case, so a case-varied alias cannot bypass it on a case-insensitive
    filesystem. Dependency-free (no Typer, no layer imports); the CLI maps
    `UnsafeOutputDirectoryError` to exit code 2. Do not add a second path-safety
    implementation.
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
  - `observed/` — the deterministic imperfection engine: taxonomy/ledger entity
    models, the in-code defect-definition registry (41 rules across 12
    categories), six maturity profiles, a truth-graph index with a mutable JSON
    working copy, the selection/mutation engine, an on-disk injection
    orchestrator (checksums + path safety), atomic writer, and validator. It
    also emits and independently re-validates the **control partition**
    (`controls.jsonl` + `rule-scope.jsonl`) — every asset/file left clean, so
    downstream evaluation can measure true negatives and precision.
    Mutates only JSON copies of the truth graph (never the truth entities) and
    depends only on `company/` and `truth/`, never on DataHub. `scenarios.py`
    holds the **adversarial** tier: constructed case classes, near-miss
    definitions with named executable validity predicates, the deterministic
    plan, and coverage. A near miss is recorded as a `ScenarioTransformation`,
    never as a `MutationRecord` — ordinary controls keep field-for-field truth
    equality, and a near miss is held to a stricter itemised invariant instead.
    See `docs/observed-state.md` and `docs/adversarial-scenarios.md`.
  - `evaluation/` — the deterministic scoring engine: the versioned prediction
    contract and its total validator, a read-only ground-truth loader over the
    emitted observed state, count-based metrics, the pair-level scoring engine,
    and the atomic report writer. It is **read-only** with respect to every other
    layer — it consumes emitted artefacts and never regenerates or rewrites them.
    Scoring is pair-level on `(entity_id, rule_id)` with each rule's population
    read from `rule-scope.jsonl`; entities outside a rule's population never
    enter its denominators, and a prediction against one is reported as an
    out-of-scope false positive rather than folded into the matrix. Undefined
    metrics are emitted as `null` with their numerator and denominator, never as
    `0.0`. Depends only on `company/`, `truth/` and `observed/`, never on
    DataHub. See `docs/evaluation.md`.
  - `comparison/` — the deterministic run-comparison layer: the emitted-run
    loader, the benchmark-identity compatibility gate, the delta primitives, the
    engine, record models and the atomic writer. It is **read-only** with
    respect to every other layer and strictly *downstream of the evaluation
    contract*: it re-scores nothing, reads no prediction file, and never opens
    the observed ground truth or the privileged scenario answer key — every
    number it reports is the evaluator's own, differenced. Two runs must share
    every benchmark-identity field or the comparison is refused with the
    differing field named. Undefined metrics difference to `null`, never `0.0`,
    and direction is an explicit field rather than the sign of a number. It
    versions its own `comparison_schema_version` and changes no other layer's
    schema. Depends only on `company/`, `truth/` and `evaluation/`, never on
    DataHub. See `docs/run-comparison.md`.
  - `bundle/` — the versioned benchmark bundle: layout and path rules, the
    manifest models, the packager, the total verifier, and the stable streaming
    `BundleReader`. It is a *packager and reader*, never a generator: it copies
    emitted bytes verbatim and never regenerates or rewrites a layer. The
    manifest declares every content file; `checksums.sha256` covers the manifest
    in turn and is itself verified by exact recomputation. A bundle is a
    directory, not an archive — deliberately, to avoid archive-header
    nondeterminism. Depends only on the layers it packages, never on an adapter.
    See `docs/bundles.md`.
  - `adapters/datahub/` — the deterministic DataHub adapter: URN construction,
    the entity/aspect mapping, the file emitter and the offline payload
    validator. It consumes a verified bundle through `BundleReader` and nothing
    else. `observed` mode reads `observed-graph.json` *alone* — never the
    findings, remediations, controls, rule scope or mutation log — which is the
    structural guarantee against truth leakage; `truth` mode is privileged and
    marked as such in tags, custom properties and the export manifest. Emits
    schemas directly rather than depending on `acryl-datahub`. See
    `docs/datahub.md`.
  - `examples.py` — resolves the committed example submissions, preferring a
    checkout's `examples/predictions/`, then the copy force-included into the
    distribution, then the source tree (for an editable install run from
    elsewhere). `company/loader.py::resolve_config_dir` does the same for
    `config/`. Only the *default* falls back; an explicit `--config-dir` that
    does not exist must still fail loudly.
  - `provenance.py` — the shared environment/scenario provenance object written
    into every generated output directory (no wall-clock values; excluded from
    the golden digests by design).
  - `canonical.py` — the fixed canonical benchmark scenario and the digest
    helpers behind the golden contract. See `docs/reproducibility.md`.
- `config/` — hand-authored canonical business configuration (YAML) plus
  `config/vocabularies/` and `config/truth/generation-plan.yaml`. Tracked;
  distinct from the git-ignored `generated/`.
- `tests/` — mirrors the package for test discovery; `tests/company/`,
  `tests/truth/`, `tests/estate/`, `tests/observed/`, and `tests/evaluation/`
  cover the model, generators, the defect registry and engine, invariants, file
  contents, and scoring semantics; `tests/bundle/` and `tests/adapters/` cover
  packaging, verification and tamper detection, the reader API, URN determinism,
  the DataHub mapping (pinned by committed fixtures under
  `tests/adapters/fixtures/`), the privilege boundary, and CLI commands. Shared
  benchmark fixtures live in `tests/conftest.py` (including `real_observed_dir`,
the canonical observed state, generated once per session).
`tests/test_release_surface.py`, `tests/test_examples.py` and
`tests/test_distribution.py` cover the public release surface: the documented
commands, the demo's output and determinism, the example submissions' pinned
scores, the stable public imports, and what the built wheel must and must not
contain. The DataHub fixtures are never
  rewritten by `pytest` — regenerate them deliberately with
  `uv run --frozen python scripts/update_datahub_fixtures.py --confirm --reason ...`.

### Architectural independence from DataHub

DataHub integration exists only as an *adapter*, and the direction is one-way.
Core generation and governance logic must never depend on DataHub types, clients
or schemas. The adapter consumes this project's own emitted artefacts — in
practice a verified benchmark bundle — and translates them outward; nothing
consumes the adapter. Adding a catalogue import to a core layer, or a catalogue
client to the dependencies, is a breaking architectural change and is caught by
`tests/adapters/test_isolation.py`.

### Separation of truth and observed state

The deterministic "truth graph" (what is correct and complete) is implemented in
`src/dataswamp_biosystems/truth/`. The "observed state" (what a catalog or
governance tool reports after defects, drift, or partial ingestion) is a
*separate* representation in `src/dataswamp_biosystems/observed/`, derived from
the truth graph rather than being the truth graph itself. Keep these two
distinct in code and on disk — do not conflate a
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
- **Never silently remediate injected defects.** The imperfection engine
  introduces intentional defects/drift for benchmark purposes; do not "fix"
  them as a side effect of unrelated work — defects are test fixtures, not bugs.
- **Never let observed-state concerns leak into the truth generator**, and never
  mutate the truth graph from the observed layer.
- **Never let the evaluator regenerate or rewrite ground truth.** It consumes
  the emitted observed state and nothing else; if a scoring need seems to
  require a ground-truth schema change, justify and test that change on its own
  terms before touching the golden digests.
- **Never report an undefined metric as zero**, and never widen a metric's
  denominator with pairs outside the relevant rule's population — inflated true
  negatives make every agent look good and are the failure mode this benchmark
  exists to avoid. The adversarial universe is the constructed neighbourhood,
  not the estate, for exactly this reason.
- **Never let a near-miss control be a real defect.** A near miss is applied only
  to a *reserved* control, declares every field it touches, and must still
  satisfy the named validity predicate of the rule it mimics. Never weaken the
  ordinary-control equality check to accommodate one, and never relabel an
  ordinary bronze/silver/gold defect as adversarial — the tier is a property of
  the constructed scenario, not of a rule.
- **Never let `mixed` include adversarial scenarios.** It means the ordinary rule
  catalogue; folding constructed cases in would move the canonical bytes and every
  published baseline score.
- **Never expose `scenarios.jsonl` or `scenario-transformations.jsonl` to an
  agent or baseline.** They are answer key, alongside the expected findings and
  the control partition.
- **Never let the comparison layer re-score, regenerate or write to an input.**
  It consumes two emitted evaluation directories and nothing else; if a
  comparison seems to need a fact the evaluator does not emit, add it to the
  evaluation contract on its own terms rather than reaching past it into the
  registry, the observed state or the answer key.
- **Never difference two runs from different universes.** Compatibility is a
  refusal, not a warning, and the error must name every differing field.
- **Never let a core layer import or name DataHub.** `company/`, `truth/`,
  `estate/`, `observed/`, `evaluation/`, `comparison/` and `bundle/` must stay
  catalogue-independent; the adapter depends on them, never the reverse.
  `tests/adapters/test_isolation.py` enforces this.
- **Never add `acryl-datahub` (or another catalogue client) as a dependency.**
  The adapter emits documented payload shapes and is testable with no server, no
  network and no credentials; keep it that way.
- **Never leak ground truth into an observed DataHub export.** The observed
  source graph reads the observed graph alone; do not widen it.
- **Never let the live DataHub path open a privileged artefact.** `ingest-datahub`
  and `verify-ingestion` consume an emitted export; they must never read the
  bundle, defect ledgers, rule scope, scenarios, expected findings or
  remediations, or the control partition — not even to strengthen a leak probe.
  `tests/adapters/test_isolation.py` enforces this.
- **Never widen the normalization ignore list to make a failing round-trip
  green.** Each entry needs a justification, a test proving the field is
  forgiven, and a paired test proving an adjacent non-ignored mutation is still
  caught; bump `NORMALIZATION_VERSION` when the rules change. An ignore list that
  grows on failure turns fidelity validation into a function that always passes.
  This applies with full force when the *live* job goes red: diagnose first, and
  triage a genuine normalization or model-version question under its own issue.
- **Never claim a DataHub compatibility point that was not run.**
  `VERIFIED_DATAHUB_VERSION`, the `live-datahub` workflow's pin and the pin in
  `docs/datahub.md` move together or not at all
  (`tests/adapters/test_live_pin.py`). It is a point, never a range. Never make
  the live job a required check, never let it run on `push` or on an unlabelled
  pull request, and never give it a repository secret or point it at a
  third-party catalogue — it stands up its own throwaway instance with
  metadata-service auth disabled.
- **Never report an unrelated catalogue entity as a DataSwamp extra**, and never
  claim live DataHub compatibility the endpoints have not been tested against.
  Where a family's URNs cannot settle ownership, report coverage as unavailable.
- **Never accept a GMS token as a CLI argument**, and never write one into a log,
  report, exception or provenance record.
- **Never let the bundle layer regenerate or rewrite what it packages**, and
  never let an adapter write inside the bundle it reads.
- Never generate scientific/synthetic datasets until a task explicitly
  scopes data generation.
- Never add placeholder packages or modules for capabilities that haven't
  been designed yet.
- **Never conflate the two licences.** The software is MIT; the *official
  generated benchmark data the project distributes* (v0.1.0 onward) is
  CC BY-NC 4.0, and bundles declare `generated_data_license: CC-BY-NC-4.0`. See
  `docs/adr/0004-generated-data-licensing.md` and `DATA-LICENSE.md`, which is the
  single authoritative wording — `src/dataswamp_biosystems/licensing.py` is its
  only programmatic source and bundles ship a verbatim copy, so never paraphrase
  it into a second place. Never describe the generated data as "open source",
  never claim the data licence covers output a third party generates
  independently from the MIT software, never relicense retroactively, and never
  invent licence terms, prices or legal conclusions beyond CC BY-NC 4.0.
- **Never change a committed example submission by hand.** Regenerate with
  `scripts/update_example_predictions.py --confirm` and update the score tables
  in `README.md` and `examples/README.md` — they are pinned by
  `tests/test_examples.py` because they are published results.
