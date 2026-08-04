# Roadmap, scope and non-goals

The long-form project direction, moved out of the README so that first contact
stays short. Nothing here is a commitment; the roadmap changes in response to
implementation experience and feedback.

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

Also implemented:

* Benchmark evaluation and scoring against expected findings and remediations
* Versioned, checksummed benchmark bundles
* Stable streaming reader API for bundle consumers
* Deterministic DataHub metadata export
* End-to-end demonstration (`dataswamp demo`) and example submissions
* Reference baseline agents with published canonical scores
  (see [baselines.md](baselines.md))
* Benchmark difficulty tiers — bronze, silver and gold, derived from a per-rule
  reasoning scope — with tier-restricted generation and per-tier evaluation
  (see [difficulty-tiers.md](difficulty-tiers.md))

Remaining for v0.1:

* A designated licence for generated benchmark data
  (see [generated-data-licensing-decision.md](generated-data-licensing-decision.md))
* First official GitHub release

Difficulty tiers ship in two parts. Bronze, silver and gold are complete; the
**adversarial** tier is not. Adversarial is a property of a *scenario* rather
than of a rule — a near-miss control that looks exactly like a defect and is
correct — so it needs a scenario layer rather than a filter over the existing
rule catalogue. `Difficulty.ADVERSARIAL` is reserved and no rule holds it.

Beyond v0.1, adversarial scenarios and near-miss controls, scenario packs
composing profiles and defect sets into named benchmark cases, run-to-run
comparison reporting, and assessment agents scored against the observed state's
expected findings and remediations, remain future work.

### v0.2 — Metadata and Lineage Integrations

* DataHub live ingestion and round-trip validation
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
