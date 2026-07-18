# Data Swamp Biosystems

> **A deterministic synthetic scientific data platform for generating governed organisations, metadata, scientific datasets, lineage and controlled data-quality defects for developing and testing modern data platforms, governance systems and AI-powered tooling.**

![Project Status](https://img.shields.io/badge/status-active-success)
![Python](https://img.shields.io/badge/python-3.13+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 🚧 Project Status

**Data Swamp Biosystems** is an active and evolving open-source project.

The architecture and capabilities will continue to expand as additional scientific workflows, metadata standards, governance models and integrations are developed.

Contributions, discussions, feature requests and constructive feedback are all welcomed.

---

## 📦 Current Version

**Current Version:** **v0.1.0**

| Version | Status | Description |
|----------|--------|-------------|
| v0.1.0 | Current | Canonical company model, deterministic truth graph, scientific file estate and observed-state defect engine |

A detailed history of changes can be found in the GitHub Releases and CHANGELOG (coming soon).

---

# Overview

Modern scientific organisations generate highly interconnected data spanning experiments, samples, sequencing, imaging, analysis pipelines, metadata, governance records and derived datasets. Access to realistic development data is often limited by confidentiality, privacy, intellectual property or regulatory constraints.

**Data Swamp Biosystems** provides a fully synthetic yet realistic environment for developing and validating scientific software without relying on proprietary or sensitive data.

Every dataset, organisation and generated file is deterministic and reproducible from a single random seed, enabling repeatable testing across development, continuous integration and benchmarking.

---

# Why this project exists

Building software for scientific organisations is difficult because realistic data is rarely available outside production environments.

This project aims to provide an open, reproducible platform for developing and testing:

- Data catalogues
- Metadata management platforms
- Governance frameworks
- Lineage systems
- Validation pipelines
- AI agents
- Scientific software
- Data ingestion pipelines
- Data quality monitoring
- Synthetic benchmarking datasets

without exposing any proprietary, confidential or patient data.

---

# Features

Current capabilities include:

- Deterministic synthetic company generation
- Canonical organisational model
- Synthetic programmes and studies
- Deterministic truth graph generation
- Scientific file generation
- Metadata validation
- Controlled defect injection
- Truth vs observed state comparison
- Reproducible random seeds
- Comprehensive automated test suite

---

# Architecture

```text
                         Configuration
                                │
                                ▼
                     Canonical Company
                                │
                                ▼
                         Truth Graph
                                │
                                ▼
                  Scientific File Estate
                                │
                                ▼
                       Observed State
                                │
                                ▼
                  Validation & Governance
```

## Component Overview

### Configuration

Version-controlled YAML configuration defining the synthetic organisation.

↓

### Canonical Company

Creates organisational structures, teams, programmes, studies, governance metadata and ownership.

↓

### Truth Graph

Produces the authoritative representation of the synthetic organisation.

↓

### Scientific File Estate

Generates realistic scientific files and metadata derived from the truth graph.

↓

### Observed State

Introduces deterministic defects and inconsistencies that mimic real operational environments.

↓

### Validation & Governance

Validates generated data and compares observed state against the intended truth.

---

# Quick Start

Clone the repository

```bash
git clone https://github.com/ronfinn/dataswamp-biosystems.git

cd dataswamp-biosystems
```

Install dependencies

```bash
uv sync
```

View available commands

```bash
uv run dataswamp --help
```

Generate a deterministic truth graph

```bash
uv run dataswamp generate-truth
```

Generate representative scientific files

```bash
uv run dataswamp generate-files
```

Inject controlled defects

```bash
uv run dataswamp inject-defects
```

Validate the generated observed state

```bash
uv run dataswamp validate-observed
```

---

# Example Outputs

Data Swamp Biosystems can generate:

- Organisational hierarchies
- Programmes
- Studies
- Samples
- Synthetic datasets
- Scientific file estates
- Metadata
- Lineage
- Governance information
- Controlled defects
- Validation reports

> Screenshots and example datasets will be added in future releases.

---

# Command Line Interface

```
validate-config

generate-truth
validate-truth

generate-files
validate-files

list-defects
validate-defects

inject-defects
validate-observed
```

---

# Project Structure

```text
config/
docs/
examples/
src/
tests/

company/
truth/
estate/
observed/
```

---

# Roadmap

Planned areas of development include:

- DataHub metadata emitter
- OpenMetadata integration
- OpenLineage export
- Neo4j graph export
- Interactive visualisations
- Synthetic Benchling exports
- Synthetic Nextflow outputs
- Cloud object storage generation
- Data Product generation
- AI metadata generation
- Web interface
- Plugin architecture

---

# Vision

Data Swamp Biosystems aims to become an open platform for generating realistic synthetic scientific organisations and governed data ecosystems.

Rather than producing isolated example datasets, the goal is to model complete scientific environments—including organisational structures, metadata, lineage, governance, scientific file systems and controlled defects—that can be used to develop, benchmark and validate the next generation of scientific data platforms, AI systems and governance tooling.

The project is intended to evolve alongside the scientific data ecosystem, with community feedback and contributions helping guide future capabilities.

---

# Contributing

Contributions, discussions, feature requests and constructive feedback are very welcome.

This project is intentionally designed as an evolving platform rather than a finished product.

Whether you:

- discover a bug
- have an idea for a feature
- want to improve documentation
- would like to contribute code
- have suggestions for new scientific workflows
- want to improve governance models

please feel free to:

- Open an Issue
- Start a Discussion
- Submit a Pull Request
- Share ideas and suggestions

Community feedback will help shape the future direction of Data Swamp Biosystems.

---

# License

This project is released under the MIT License.
