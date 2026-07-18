# Data Swamp Biosystems

> **A deterministic synthetic biotech data estate for testing data catalogues, governance controls, lineage systems and AI agents—without proprietary, confidential or patient data.**

[![CI](https://github.com/ronfinn/dataswamp-biosystems/actions/workflows/ci.yml/badge.svg)](https://github.com/ronfinn/dataswamp-biosystems/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Project status](https://img.shields.io/badge/status-pre--alpha-orange)

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

The current repository provides the initial Python package, command-line interface, automated testing, linting, type checking and continuous-integration foundation.

The deterministic organisation generator, scientific file-estate generator, defect-injection engine and benchmark reports described below represent the target capabilities for the first public releases and are being developed incrementally.

| Item                              | Status           |
| --------------------------------- | ---------------- |
| Python package foundation         | Available        |
| Command-line application          | Available        |
| Automated CI checks               | Available        |
| Strict static type checking       | Available        |
| Canonical organisation model      | In development   |
| Truth graph generation            | In development   |
| Scientific file-estate generation | Planned for v0.1 |
| Controlled defect injection       | Planned for v0.1 |
| Truth-versus-observed reports     | Planned for v0.1 |
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

The observed state represents the imperfect version of the organisation that a catalogue, governance platform, validator or AI agent might encounter.

Controlled defects may include:

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

Every defect will be generated from a known truth state and recorded in a machine-readable defect manifest.

### 3. Benchmark Results

Because the authoritative truth and injected defects are known, tools can be evaluated against measurable expected results.

Potential measures include:

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

A versioned catalogue of supported defects, their expected effects and their detection criteria.

### Defect-Injection Engine

A deterministic mechanism for transforming the truth state into an imperfect observed state.

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

A future defect record may contain information such as:

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

The final schema will be versioned and documented before the first stable benchmark release.

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

* Versioned configuration schema
* Canonical fictional biotech organisation
* Authoritative truth graph
* Representative scientific file estate
* Versioned defect registry
* Deterministic defect injection
* Truth-versus-observed comparison
* Machine-readable benchmark reports
* Human-readable benchmark reports
* End-to-end demonstration
* Reproducibility and snapshot tests
* First official GitHub release

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
