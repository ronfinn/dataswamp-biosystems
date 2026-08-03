# Data Swamp Biosystems

> **A deterministic synthetic biotech data estate for testing data catalogues, governance controls, lineage systems and AI agents—without proprietary, confidential or patient data.**

[![CI](https://github.com/ronfinn/dataswamp-biosystems/actions/workflows/ci.yml/badge.svg)](https://github.com/ronfinn/dataswamp-biosystems/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Project status](https://img.shields.io/badge/status-pre--alpha-orange)

## Current milestone: benchmark evaluation and scoring

This repository contains packaging, tooling, a CLI, the **canonical company
model** — a fictional oncology company (programmes, studies, teams, people,
ownership/stewardship, and controlled vocabularies) defined in YAML under
`config/` and validated by typed Pydantic models — and a **deterministic truth
graph**: the complete, correct synthetic scientific and governance state
(subjects, biospecimens, assays, runs, files, datasets, data products,
contracts, quality, governance, and lineage) generated from that model. See
[docs/domain-model.md](docs/domain-model.md) and
[docs/truth-graph-schema.md](docs/truth-graph-schema.md).

A downstream **scientific-file estate** materializes small, genuinely-readable
example files (H5AD, Parquet, OME-TIFF, PNG, VCF, BED, GeoJSON, Matrix Market,
CSV/TSV/JSON/YAML/JSONL, gzip, FASTQ) for the truth graph's assets, with
explicitly-declared placeholders for heavy binaries (BAM, CRAM, DICOM, SVS,
Zarr). See [docs/file-generation.md](docs/file-generation.md).

An **imperfection engine** derives a deliberately-imperfect **observed state**
from the truth graph — what a catalogue might report after defects and drift —
alongside a full, machine-readable ledger of every injected defect and its
expected finding and remediation, plus an emitted and validated **control
partition** naming every entity left clean, so true negatives and precision are
measurable. It never mutates the truth graph. See
[docs/observed-state.md](docs/observed-state.md).

An **evaluation engine** scores an agent's predictions against that ground truth
(`dataswamp evaluate`): a versioned prediction schema, pair-level matching on
`(entity_id, rule_id)` with per-rule denominators read from `rule-scope.jsonl`,
confusion-matrix and remediation metrics, separate reporting for reserved
controls and out-of-scope predictions, and byte-identical reports for identical
inputs. It computes evidence, not opinion: no weights, no composite score. See
[docs/evaluation.md](docs/evaluation.md).

All five layers are deliberately catalogue-independent: they know nothing about
DataHub or any downstream consumer. The truth graph remains the ground truth for
benchmarks. Scenario packs, assessment agents and DataHub integration are future
milestones — see Roadmap below.

---

## Overview


Scientific organisations generate interconnected data spanning programmes, studies, experiments, samples, assays, sequencing, imaging, analytical pipelines, metadata, lineage, ownership and governance controls.

Developing software against these environments is difficult because realistic scientific data is often:

* Proprietary or commercially sensitive
* Confidential or contractually restricted
* Distributed across multiple systems
* Inconsistently documented
* Difficult to reproduce outside production
* Associated with privacy or regulatory constraints

**Data Swamp Biosystems** is an open-source project for generating a completely fictional but structurally realistic biotech data estate.

The project is designed to provide a safe and reproducible development environment for testing:

* Scientific data catalogues
* Metadata ingestion pipelines
* Data-governance controls
* Data-quality validation
* Lineage systems
* Data-product frameworks
* AI metadata agents
* Governance and remediation agents
* Scientific software integrations

No real patients, employees, organisations, studies or proprietary datasets are represented.

---

## Project Status

> [!IMPORTANT]
> Data Swamp Biosystems is currently **pre-alpha** and under active development.

The current repository provides the Python package, command-line interface,
automated testing, linting, type checking and continuous-integration foundation,
together with the canonical organisation model, the deterministic truth graph,
the scientific file-estate generator and the deterministic defect-injection
(imperfection) engine.

The benchmark reports described below represent the remaining target capabilities
for the first public release and are being developed incrementally.

| Item                              | Status           |
| --------------------------------- | ---------------- |
| Python package foundation         | Available        |
| Command-line application          | Available        |
| Automated CI checks               | Available        |
| Strict static type checking       | Available        |
| Canonical organisation model      | Available        |
| Truth graph generation            | Available        |
| Scientific file-estate generation | Available        |
| Controlled defect injection       | Available        |
| Benchmark evaluation and scoring   | Available        |
| DataHub integration               | Planned          |
| OpenMetadata integration          | Planned          |
| OpenLineage export                | Planned          |
| AI-agent benchmark harness        | Planned          |

**Source package version:** `0.1.0`

An official GitHub release will be published when the first end-to-end benchmark workflow is complete.

---

## The Core Concept

Data Swamp Biosystems models a fictional scientific organisation in two connected states.

### 1. Truth State

The truth state represents the authoritative and internally consistent version of the organisation.

It is intended to describe:

* Organisational structures
* Research teams
* Scientific programmes
* Studies and experiments
* Samples and biospecimens
* Scientific datasets
* Files and storage locations
* Data owners and stewards
* Governance classifications
* Metadata relationships
* Analytical workflows
* Data lineage

### 2. Observed State

The observed state represents the imperfect version of the organisation that a catalogue, governance platform, validator or AI agent might encounter. It is implemented by the imperfection engine (`dataswamp inject-defects`), which derives it from the truth graph without ever modifying that graph.

The defect registry covers twelve categories, including:

* Missing ownership
* Incomplete metadata
* Invalid identifiers
* Broken lineage
* Orphaned datasets
* Inconsistent classifications
* Incorrect sensitivity labels
* Duplicate assets
* Unexpected file locations
* Schema violations
* Naming-standard violations
* Unregistered derived datasets

Every defect is generated from a known truth state and recorded in machine-readable ledgers, together with its expected finding and expected remediation.

Each rule's declarations are an enforced contract, not documentation. Whether a fix can be derived (`automatic`, `manual` or `none`) and whether it needs authorisation are independent dimensions, and some findings are explicitly **non-remediable** — an agent that abstains there is right. Generated evidence is validated against every declaration; see [docs/observed-state.md](docs/observed-state.md#the-rule-and-remediation-contract).

### 3. Benchmark Results

Because the authoritative truth and injected defects are known, tools can be evaluated against measurable expected results. `dataswamp evaluate` does exactly that: it scores a JSONL prediction file against the emitted ground truth and writes confusion-matrix and remediation metrics as both JSON and a Markdown scorecard. See [docs/evaluation.md](docs/evaluation.md).

Measures include:

* Defect-detection precision
* Defect-detection recall
* Metadata completeness
* Ownership coverage
* Lineage reconstruction accuracy
* Classification accuracy
* Data-product readiness
* Remediation success
* Reproducibility across runs

---

## Why Deterministic Generation Matters

Every generated organisation, asset, relationship and defect is intended to be reproducible from a defined configuration and random seed.

The same configuration and seed should produce an equivalent synthetic environment.

This supports:

* Repeatable development
* Regression testing
* Continuous integration
* Integration testing
* Platform comparisons
* AI-agent evaluation
* Reproducible demonstrations
* Controlled benchmark scenarios

A platform can therefore be tested against the same data estate before and after a change, or compared with another platform using an equivalent input.

### Where byte-identity is guaranteed

The guarantee is stated precisely rather than broadly:

* **Canonical environment** — the committed `uv.lock` on Python 3.12 or 3.13:
  every generated artefact is byte-identical, including the binary scientific
  files.
* **Supported dependency range** — the declared minimums upwards: generation is
  functionally correct and the truth-graph and observed-state artefacts are
  byte-identical, but the materialized estate is not. Parquet, TIFF, PNG and
  H5AD payloads are written by `pyarrow`, `Pillow`, `tifffile` and `anndata`,
  whose encodings legitimately change between releases.
* **Across operating systems** — not claimed; only Linux and macOS are tested.

A committed golden SHA-256 contract (`tests/golden/canonical-digests.json`)
pins a small canonical scenario, and every generated output directory carries a
`provenance.json` recording the Python version, platform, direct dependency
versions and an environment fingerprint. CI tests all four cells of
locked/lowest-direct × Python 3.12/3.13.

Full mechanics, the golden-update review checklist, and how to reproduce a
canonical benchmark: [docs/reproducibility.md](docs/reproducibility.md).

---

## Intended Users

Data Swamp Biosystems is designed for:

* Scientific software engineers
* Data engineers
* Data-platform engineers
* Data-governance teams
* Metadata and ontology engineers
* AI and machine-learning engineers
* Bioinformaticians
* Research informatics teams
* DataHub users
* OpenMetadata users
* OpenLineage users
* Developers building scientific AI agents
* Developers testing data-ingestion and validation systems

---

## Potential Use Cases

### Test a scientific data catalogue

Generate a fictional organisation containing programmes, studies, datasets, owners, classifications and lineage, and then ingest that metadata into a catalogue.

### Evaluate governance controls

Introduce known governance defects and measure whether a platform identifies missing ownership, incorrect classifications or incomplete metadata.

### Benchmark AI agents

Provide an AI agent with an imperfect observed state and evaluate whether it can identify, explain and propose remediation for known defects.

### Test ingestion pipelines

Generate predictable directory structures, manifests and metadata records for repeatable ingestion testing.

### Validate lineage systems

Create a known lineage graph and test whether an external system preserves or reconstructs its relationships correctly.

### Demonstrate data products

Model governed data products with defined owners, inputs, outputs, quality expectations and readiness states.

### Develop scientific software safely

Build and demonstrate software against realistic scientific structures without using production or partner data.

---

## Current Quick Start

### Prerequisites

* Python 3.12 or later
* [`uv`](https://docs.astral.sh/uv/)
* Git

### Clone the repository

```bash
git clone https://github.com/ronfinn/dataswamp-biosystems.git
cd dataswamp-biosystems
```

### Install the project

```bash
uv sync
```

To install all development dependency groups:

```bash
uv sync --locked --all-groups
```

### View the command-line interface

```bash
uv run dataswamp --help
```

### Display the installed version

```bash
uv run dataswamp version
```

---

## Validating the canonical configuration

The canonical company model lives in `config/`. Validate it with:

```bash
uv run dataswamp validate-config
```

On success it prints entity counts (programmes, studies, teams, people,
ownership and stewardship assignments, and vocabulary terms) and exits 0. It
exits non-zero with actionable messages when the configuration is invalid:

- exit code `1` — validation failures (duplicate IDs, duplicate emails,
  non-`dataswamp.example` email/company domains, unresolved
  programme/team/person references, invalid controlled-vocabulary values,
  and owners/stewards pointing at nonexistent assets or units);
- exit code `2` — the configuration could not be loaded (a file is missing
  or the YAML is malformed).

Point it at an alternative directory with `--config-dir PATH`.

## Generating the truth graph

Generate the deterministic truth graph into the git-ignored `generated/truth/`:

```bash
uv run dataswamp generate-truth --seed 20260717
```

The same seed, configuration, and generator version always produce
byte-identical output. It writes JSONL shards (subjects, biospecimens, assays,
runs, files, assets, contracts, quality, governance, lineage), a
`truth-graph.json` manifest (provenance, counts, and per-shard SHA-256
digests), and a `summary.md`. Override the seed with `--seed`, the destination
with `--output-dir`, and overwrite a non-empty directory with `--force`.

> [!IMPORTANT]
> Generation **replaces the entire output directory**. Every generation command
> therefore refuses an `--output-dir` that is, contains, or sits inside its
> protected inputs — the configuration directory, the truth directory it reads,
> and by extension the repository root. Paths are canonicalised before
> comparison, so symlink aliases, `..` segments and — on a case-insensitive
> filesystem — differently cased spellings cannot bypass the check, and
> `--force` never overrides it. Unsafe usage exits with code `2` without
> touching anything. See
> [docs/file-generation.md](docs/file-generation.md#output-directory-safety).

Validate an existing generated graph — invariants plus a byte-for-byte
determinism/integrity check against a regeneration from the recorded seed:

```bash
uv run dataswamp validate-truth
```

## Generating the scientific-file estate

Materialize representative example files for the truth graph's assets into the
git-ignored `generated/estate/`:

```bash
uv run dataswamp generate-files --seed 20260717 --profile tiny
uv run dataswamp generate-files --seed 20260717 --profile demo
uv run dataswamp generate-files --seed 20260717 --profile stress
```

The truth graph is regenerated in memory from the same seed (consumed, never
re-invented) and a per-asset file set is written under `files/`, alongside a
`file-manifest.jsonl`, a machine-readable `generation-summary.json`, and a
`summary.md`. Profiles trade off scale against disk:

| Profile | Files | Disk | Purpose |
| --- | --- | --- | --- |
| `tiny` (default) | ~100 | <50 MB | tests and rapid demos; covers every format |
| `demo` | ~1,000–2,000 | <500 MB | DataHub / agent demonstrations |
| `stress` | ~10k records | minimal content | catalogue-scale testing |

Each profile carries a **hard byte budget**; generation aborts before exceeding
it rather than filling the disk. The same truth graph, profile, generator
version, and seed produce byte-identical files and manifest. Override with
`--seed`, `--profile`, `--output-dir`, and `--force`.

**Supported formats.** Genuine, re-readable: H5AD (AnnData), Parquet, OME-TIFF,
PNG, GeoJSON, VCF, BED, Matrix Market, CSV, TSV, JSON, YAML, JSONL, gzip text,
and tiny FASTQ. **Declared placeholders** (never faked as valid binaries): BAM,
CRAM, DICOM, SVS, and large Zarr — each a tiny stub with a `.placeholder.json`
sidecar recording the intended format, represented logical size, and
limitations. Files carry no scientific claims beyond structural validity.

Validate an existing estate — checksums, path safety, asset references,
placeholder sidecars, and a byte-for-byte manifest match:

```bash
uv run dataswamp validate-files
```

## Injecting defects (the observed state)

Inspect the defect registry, then derive a deliberately-imperfect observed state
and its defect ledger from an on-disk truth graph into the git-ignored
`generated/observed/`:

```bash
uv run dataswamp list-defects          # print every defect rule
uv run dataswamp validate-defects      # validate the registry itself
uv run dataswamp inject-defects --truth generated/truth/truth-graph.json --seed 20260717 --profile demo
```

The truth graph is read from disk (never modified): its inputs are checksummed
before processing and verified unchanged afterwards, and defects are applied to
independent JSON copies. The output may not resolve inside the truth directory.
It writes `observed-graph.json`, six ledger files (`injected-defects.jsonl`,
`expected-findings.jsonl`, `expected-remediations.jsonl`, `mutation-log.jsonl`,
`controls.jsonl`, `rule-scope.jsonl`), a `profile-summary.json`, a
`truth-inputs.json` checksum manifest, and a `summary.md`. Profiles set how many defects are injected:

| Profile | Character |
| --- | --- |
| `gold` | pristine — no defects |
| `mostly-good` | a few defects, mostly clean |
| `typical` | a moderate mix across every category |
| `poor` | pervasive defects |
| `catastrophic` | defects almost everywhere |
| `demo` (default) | ~100–200 defects across all 12 categories, healthy controls |

Every applied defect records a before/after mutation, an expected finding, and an
expected remediation, so an agent's detections can be scored against known truth
by matching structured fields (rule, entity, category, severity) rather than
exact prose. `controls.jsonl` names every truth asset and file left clean — the
benchmark's negative class — and `rule-scope.jsonl` records each rule's eligible,
control-excluded and selected populations, so an evaluator can compute true
negatives, precision, recall and specificity from the emitted artefacts alone
without parsing any prose. The observed graph itself carries no defect
annotations. `--seed` is
the defect seed (the truth seed comes from the truth manifest); override
`--profile`, `--output-dir`, and `--force` as needed.

Validate an existing observed state — a byte-for-byte regeneration check plus
ledger structural, fidelity, and non-contamination invariants, and an
independent reconstruction of the control partition (no defect or mutation may
target a control, and every control must be unchanged from truth):

```bash
uv run dataswamp validate-observed
```

## Scoring an agent (evaluation)

Score a JSONL prediction file against an emitted observed state, into the
git-ignored `generated/evaluation/`:

```bash
uv run dataswamp evaluate \
  --observed-dir generated/observed \
  --predictions predictions.jsonl \
  --output-dir generated/evaluation
```

Ground truth and the submission are fully validated before anything is written,
so an invalid submission never replaces a previous evaluation. Malformed,
duplicate, unknown-id and contradictory predictions are rejected with the line,
field, value and expected contract — never silently dropped.

Scoring is pair-level on `(entity_id, rule_id)`, with each rule's population read
from `rule-scope.jsonl`, so entities that were never in a rule's population
cannot inflate specificity. Predictions against a known entity outside a rule's
population are reported separately as out-of-scope rather than folded into the
matrix. False positives against reserved controls — held out before selection —
are broken out on their own, and an actionable remediation proposed against a
clean entity is flagged as an unsafe action.

It writes `evaluation-summary.json`, `finding-results.jsonl`,
`remediation-results.jsonl`, `rule-metrics.jsonl`, `category-metrics.jsonl`, an
`evaluation-report.md` scorecard, and `provenance.json`. Identical inputs produce
byte-identical reports. The prediction schema, the exact metric definitions,
undefined-metric behaviour, abstention handling and remediation scoring are all
documented in [docs/evaluation.md](docs/evaluation.md).

## Development

### Run the test suite

```bash
uv run pytest
```

### Run the linter

```bash
uv run ruff check .
```

### Check formatting

```bash
uv run ruff format --check .
```

### Apply formatting

```bash
uv run ruff format .
```

### Run static type checking

```bash
uv run mypy src
```

### Run all pre-commit checks

```bash
uv run pre-commit run --all-files
```

---

## Target Architecture

The target architecture separates authoritative synthetic truth from the imperfect state presented to external tools.

```text
                         Versioned Configuration
                                   │
                                   ▼
                         Canonical Organisation
                                   │
                                   ▼
                              Truth Graph
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
           Scientific File Estate         Governance Metadata
                    │                             │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                          Controlled Defects
                                   │
                                   ▼
                            Observed State
                                   │
             ┌─────────────────────┼─────────────────────┐
             │                     │                     │
             ▼                     ▼                     ▼
        Data Catalogue       Validation Tool         AI Agent
             │                     │                     │
             └─────────────────────┼─────────────────────┘
                                   │
                                   ▼
                      Truth Comparison and Scoring
                                   │
                                   ▼
                           Benchmark Reports
```

---

## Target Components

### Configuration

Version-controlled configuration defining the fictional organisation, scientific scope, scale, random seed and enabled defect scenarios.

### Canonical Organisation

A structured representation of teams, programmes, studies, experiments, responsibilities and governance roles.

### Truth Graph

The authoritative graph of scientific assets and their relationships.

The truth graph provides the expected state against which external systems can be evaluated.

### Scientific File Estate

A generated directory and object hierarchy representing scientific data stored across realistic projects, studies and analytical workflows.

### Governance Metadata

Ownership, stewardship, classifications, domains, policies, glossary terms, retention requirements and data-product metadata.

### Defect Registry

A versioned catalogue of supported defects, their expected effects and their detection criteria. Implemented as an in-code registry of 41 rules spanning 12 categories, inspectable with `dataswamp list-defects`.

### Defect-Injection Engine

A deterministic mechanism for transforming the truth state into an imperfect observed state. Implemented in `src/dataswamp_biosystems/observed/`, with six maturity profiles and checksum-verified protection of the truth graph.

### Validation and Benchmarking

Comparison of detected findings with the known defect manifest and authoritative truth graph.

### Integration Emitters

Adapters that translate the generated estate into platform-specific metadata formats or APIs.

---

## Intended v0.1 Output Contract

The first end-to-end release is intended to generate a structure similar to the following:

```text
dataswamp-output/
├── configuration/
│   └── scenario.yaml
├── truth/
│   ├── organisation.json
│   ├── programmes.jsonl
│   ├── studies.jsonl
│   ├── assets.jsonl
│   ├── governance.jsonl
│   └── lineage.jsonl
├── estate/
│   ├── programmes/
│   ├── studies/
│   └── shared/
├── observed/
│   ├── programmes/
│   ├── studies/
│   └── shared/
├── defects/
│   └── injected-defects.json
├── manifests/
│   └── run-manifest.json
└── reports/
    ├── benchmark.json
    └── benchmark.md
```

This structure remains subject to change while the v0.1 benchmark contract is developed.

---

## Example Defect Model

Illustrative shape only — the implemented ledger records are documented in [docs/observed-state.md](docs/observed-state.md). A defect record carries information such as:

```json
{
  "defect_id": "missing-owner-001",
  "defect_type": "missing_owner",
  "asset_id": "dataset:osteomics:study-0042:expression-matrix",
  "expected_owner": "team:computational-biology",
  "observed_owner": null,
  "severity": "high",
  "deterministic_seed": 42
}
```

The schema will continue to be versioned and documented ahead of the first stable benchmark release.

---

## Scientific Scope

The project is intended to support modular scientific-domain packs rather than hard-coding a single workflow.

Potential packs include:

### Organisational and governance metadata

* Teams
* Programmes
* Studies
* Data owners
* Data stewards
* Domains
* Classifications
* Policies
* Data products

### Sequencing and genomics

* FASTQ files
* BAM and CRAM files
* VCF and gVCF files
* Sample sheets
* Demultiplexing reports
* Pipeline manifests
* Quality-control reports

### Single-cell and spatial data

* AnnData and H5AD files
* Zarr stores
* Count matrices
* Cell-level metadata
* Spatial coordinates
* Image associations
* Differential-expression results

### Imaging and phenomics

* Microscopy images
* Cell-painting outputs
* Digital pathology images
* Segmentation masks
* Image-derived features
* Imaging quality-control results

### Analytical workflows

* Nextflow execution metadata
* Pipeline inputs and outputs
* Software environments
* Parameters
* Execution reports
* Derived datasets
* Lineage relationships

These domain packs are roadmap items and are not all implemented in the current release.

---

## Design Principles

### Entirely fictional

The generated organisation and data estate must not reproduce a real company, patient, study, partner or proprietary dataset.

### Deterministic

Equivalent configuration and seeds should produce equivalent results.

### Auditable

Every generated asset, relationship and defect should be traceable to its configuration and generation process.

### Measurable

Defects should have defined expected findings so that tools and agents can be scored.

### Vendor-neutral

The core data model should remain independent of any individual catalogue, governance platform or cloud provider.

### Extensible

Scientific domains, asset types, defect types and integrations should be implementable as modular extensions.

### Safe by design

The project must not require real patient data, personal data or confidential scientific information.

### Honest about maturity

Documentation should distinguish implemented functionality from experimental and planned capabilities.

---

## Roadmap

### v0.1 — Deterministic Benchmark Core

Implemented:

* Versioned configuration schema
* Canonical fictional biotech organisation
* Authoritative truth graph
* Representative scientific file estate
* Versioned defect registry
* Deterministic defect injection
* Reproducibility and snapshot tests

Remaining for v0.1:

* Truth-versus-observed comparison reporting
* Machine-readable benchmark reports
* Human-readable benchmark reports
* End-to-end demonstration
* First official GitHub release

Beyond v0.1, scenario packs composing profiles and defect sets into named
benchmark cases, and assessment agents scored against the observed state's
expected findings and remediations, remain future work.

### v0.2 — Metadata and Lineage Integrations

* DataHub metadata emitter
* OpenMetadata integration
* OpenLineage event export
* Neo4j graph export
* Integration examples
* Integration-specific validation reports

### v0.3 — Scientific Domain Packs

* Sequencing and genomics pack
* Single-cell and AnnData pack
* Spatial data pack
* Imaging and cell-painting pack
* Digital pathology pack
* Synthetic Nextflow outputs
* Synthetic research-system exports

### v0.4 — AI-Agent Evaluation

* Agent-accessible benchmark interface
* Metadata-enrichment scenarios
* Defect-detection tasks
* Governance-remediation tasks
* Expected-answer datasets
* Agent scoring and comparison reports
* Reproducible evaluation suites

### Longer-Term Possibilities

* Cloud object-storage generation
* Data-product modelling
* Interactive visualisations
* Web interface
* Plugin architecture
* Large-scale benchmark profiles
* Community-contributed domain packs
* Community-contributed defect catalogues

The roadmap may change in response to implementation experience and community feedback.

---

## Non-Goals

Data Swamp Biosystems is not intended to be:

* A source of real patient or clinical data
* A production laboratory information-management system
* A production electronic laboratory notebook
* A substitute for formal compliance validation
* A certification that a platform is regulatorily compliant
* An exact representation of any existing biotechnology company
* A replacement for domain-specific scientific simulators
* A security-testing environment for offensive activity

The benchmark may help test individual controls, but passing a benchmark does not establish regulatory or legal compliance.

---

## Contributing

Contributions, discussions, bug reports and feature proposals are welcome.

Useful contribution areas include:

* Scientific data models
* Metadata schemas
* Governance scenarios
* Defect definitions
* Validation rules
* Platform integrations
* Documentation
* Example configurations
* Reproducibility testing
* Scientific-domain packs

Before beginning a substantial change, please open a GitHub issue describing:

1. The problem or use case
2. The proposed behaviour
3. The expected output
4. Relevant scientific or metadata standards
5. How the change could be tested

Browse or open an issue through the repository’s [GitHub Issues](https://github.com/ronfinn/dataswamp-biosystems/issues).

---

## Feedback Requested

The project would particularly benefit from feedback on:

* The minimum useful fictional biotech organisation
* High-value scientific metadata relationships
* Common catalogue-ingestion failure modes
* Realistic governance and data-quality defects
* Useful benchmark measures
* DataHub and OpenMetadata mappings
* OpenLineage scenarios
* AI-agent evaluation tasks
* Scientific workflow priorities

---

## Independence and Data Statement

Data Swamp Biosystems is an independent open-source project.

It does not contain or reproduce:

* Patient data
* Personal data
* Employer data
* Partner data
* Proprietary datasets
* Confidential scientific information
* Production schemas copied from a real organisation

Any similarity between generated entities and real organisations, people, programmes or studies is unintended.

---

## Security

Please do not use public issues to report a vulnerability that could place users or their systems at risk.

A formal security-reporting process will be documented in `SECURITY.md` as the project approaches its first public release.

---

## License

Data Swamp Biosystems is released under the [MIT License](LICENSE).

---

## Author

Created and maintained by [Ron Finn](https://github.com/ronfinn).

---

## Acknowledgements

Data Swamp Biosystems is inspired by the challenges involved in developing scientific data platforms, catalogues, governance systems and AI-powered tooling when safe and realistic development data is unavailable.
