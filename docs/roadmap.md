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
* The adversarial tier — constructed scenario cases, near-miss controls,
  `scenarios.jsonl`, scenario-aware scoring and measured adversarial baselines
  (see [adversarial-scenarios.md](adversarial-scenarios.md))

* A designated licence for generated benchmark data — CC BY-NC 4.0, with the
  software staying MIT and commercial permission handled separately
  (see [ADR 0004](adr/0004-generated-data-licensing.md))

**v0.1 is complete and released.** Everything scoped for it is implemented, the
package is versioned `0.1.0`, and the release is tagged and published. PyPI
publication remains a separate, undecided question.

All four difficulty tiers now ship. Bronze, silver and gold are a filter over the
rule catalogue; adversarial is a *constructed* set of scenario cases, because
adversarial is a property of a scenario rather than of a rule — no rule holds
`Difficulty.ADVERSARIAL`, and `selectable_rules` still refuses it.

The adversarial set is deliberately a **focused initial six case classes** over a
small constructed universe, not a model of real-world ambiguity; its limits are
listed in
[adversarial-scenarios.md](adversarial-scenarios.md#limitations). Widening it —
multi-field and multi-entity near misses, file- and lineage-level construction,
and cases where the observed graph genuinely underdetermines the *finding* rather
than only the remediation — is future work.

**Run-to-run comparison shipped after v0.1.0** ([#17]): `dataswamp compare-runs`
differences two emitted evaluation directories and reports metric deltas,
rule-level regressions, control-preservation regressions, per-tier and
adversarial movement, and remediation changes. It refuses to compare runs from
different universes rather than producing a meaningless delta, and applies no
threshold — it answers what changed, not whether that is acceptable. See
[run-comparison.md](run-comparison.md).

Beyond that, scenario packs composing profiles and defect sets into named
benchmark cases, threshold/gating policy on top of comparison, and assessment
agents scored against the observed state's expected findings and remediations,
remain future work.

[#17]: https://github.com/ronfinn/dataswamp-biosystems/issues/17
[#27]: https://github.com/ronfinn/dataswamp-biosystems/issues/27
[#28]: https://github.com/ronfinn/dataswamp-biosystems/issues/28
[#29]: https://github.com/ronfinn/dataswamp-biosystems/issues/29
[#33]: https://github.com/ronfinn/dataswamp-biosystems/issues/33
[#35]: https://github.com/ronfinn/dataswamp-biosystems/issues/35
[#39]: https://github.com/ronfinn/dataswamp-biosystems/issues/39

### v0.2 — Metadata and Lineage Integrations

* DataHub live ingestion and round-trip validation — **the offline-testable core
  has shipped** ([#27]): `dataswamp ingest-datahub` transmits an emitted DataHub
  export to a running catalogue, and `dataswamp verify-ingestion` reads it back
  and judges completeness, fidelity, containment and observed-mode non-leakage
  as four separately-reported claims. It adds no dependency — the client is
  standard-library REST, with every endpoint confined to one module (see
  [ADR 0005](adr/0005-direct-rest-datahub-client.md)) — and the whole contract is
  provable offline against a local fake GMS.

  Live GMS support is **verified against exactly one release, DataHub `v1.7.0`**
  ([#28]) — a compatibility *point*, not a range. An optional weekly Quickstart
  canary establishes and re-checks it, and every round-trip report names that
  release rather than claiming a range. The canary earned its keep immediately:
  it caught a rest.li/OpenAPI dialect mismatch that the whole offline suite had
  missed, because the fake GMS accepted any request envelope the client chose.

  A drift-canary and model-version policy ([#29]) governs what a red run means —
  a four-branch triage (DataSwamp bug, server-derived metadata, upstream DataHub
  change, infrastructure flake), each with a different permitted response, and a
  rule that normalization is never widened merely to turn the canary green. See
  [datahub.md](datahub.md#when-the-canary-goes-red) and
  [ADR 0006](adr/0006-compatibility-points-not-ranges.md).
* OpenMetadata integration — **in progress, not shipped.** The deterministic
  offline mapping and export have landed ([#33]): `dataswamp export-openmetadata`
  emits an ordered, load-order-aware plan of whole-entity `Create<Entity>`
  requests against OpenMetadata's **native** model — a `CustomStorage`
  StorageService over a study → dataset → file Container hierarchy, plus Domains,
  Data Products, Teams, Glossaries and a Classification — together with a
  first-class `mapping-coverage.json` recording, per DataSwamp concept, how
  faithfully it maps and what was deliberately dropped.

  It is deliberately **not** a copy of the DataHub adapter's entity/aspect
  architecture, and no `adapters/common/` exists yet: with two adapters it is now
  possible to see what is genuinely common rather than merely similar, and that
  judgement is better made once than guessed at twice.

  Three decisions are worth knowing before reading the export. Datasets become
  **Containers, not Tables**, because DataSwamp holds no honest relational column
  metadata. Stewardship is preserved *separately* from ownership and the mapping
  is classified **lossy**, because OpenMetadata draws no owner/steward
  distinction. Quality checks are classified **unsupported**, because
  OpenMetadata's `TestDefinition.entityType` admits only `TABLE` and `COLUMN` and
  emitting one for a Container would fabricate applicability.

  **Live ingestion and round-trip validation have now landed too** ([#35]):
  `dataswamp ingest-openmetadata` replays the emitted export in its emitted order
  without remapping it, and `dataswamp verify-om-ingestion` reads the catalogue
  back by fully-qualified name and reports completeness, fidelity, containment and
  observed-mode non-leakage as four separate claims. Credentials are
  environment-only, `--dry-run` opens no socket, and the whole path is testable
  offline against a strict fake that validates requests against OpenMetadata's own
  vendored schemas rather than against the client. Still no catalogue-client
  dependency ([ADR 0007](adr/0007-no-catalogue-client-dependency.md)).

  **There is still no compatibility claim.** Nothing has been loaded into a
  running OpenMetadata; `VERIFIED_OPENMETADATA_VERSION` is `None` and stays `None`
  until a real-server canary earns a point, per
  [ADR 0006](adr/0006-compatibility-points-not-ranges.md). A green offline fake is
  not evidence about a server — that is what the fake being a *contract simulator*
  means.

  The optional `live-openmetadata` canary ([#39]) now exists to earn that point:
  it stands up a real, pinned, throwaway OpenMetadata `1.13.3` — upstream's own
  quickstart compose, sanitized for CI, with no repository secret — and runs the
  whole product path through it. It is non-blocking and never a required check.
  **Implementing a canary is not running one**, so the constant is unchanged
  until a completely green real-server run exists. See
  [openmetadata.md](openmetadata.md).
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
* Agent scoring and comparison reports (run comparison shipped; agent-side scoring remains)
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
