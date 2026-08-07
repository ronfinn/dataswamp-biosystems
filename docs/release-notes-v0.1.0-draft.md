# Draft release notes — v0.1.0

**Draft. No release has been published and no tag has been created.** This file
is prepared for copying into a GitHub Release once the remaining pre-release
decisions are made. Nothing here should be read as an announcement.

Before publishing, resolve:

1. The final version — `0.1.0` rather than `0.1.0rc1` — and the corresponding
   `pyproject.toml`, `__init__.py` and `tests/test_package.py` update.
2. Whether to publish to PyPI. The "Try it" section below assumes so; if the
   release ships as a GitHub artefact only, replace `pip install
   dataswamp-biosystems` with the wheel-from-checkout instructions the README
   gives.

Then follow [the release checklist](release-checklist.md).

---

## Data Swamp Biosystems v0.1.0

**A deterministic synthetic biotech data estate and governance benchmark.**

Tools that find problems in data estates — catalogues, data-quality suites,
governance agents — are usually demonstrated on data with no known problems in
it. Data Swamp Biosystems supplies the missing half: a realistic, entirely
fictional oncology research data estate **with a published answer key**.

It generates a complete and correct synthetic estate, derives a deliberately
imperfect view of it by injecting a curated taxonomy of governance defects, and
records exactly what it broke and what it deliberately left clean — so a tool or
an agent can be scored on what it found, what it missed, what it wrongly flagged
and what it proposed to do about it.

### Try it

```bash
pip install dataswamp-biosystems
dataswamp demo --output-dir ./dataswamp-demo
dataswamp run-baseline --agent rule-based \
    --observed-dir ./dataswamp-demo/generated/observed \
    --output baseline.jsonl --evaluate \
    --evaluation-dir ./dataswamp-demo/baseline-evaluation
```

A couple of seconds, no credentials, no network, no server. Run it twice and the
output is byte-identical.

### What's in it

- **A fictional company model** — programmes, studies, teams, people, ownership,
  stewardship and controlled vocabularies, as versioned YAML.
- **A deterministic truth graph** — subjects, biospecimens, assays, instrument
  and pipeline runs, files, datasets, data products, contracts, quality checks,
  governance records and ~1 800 lineage edges.
- **A readable scientific file estate** — real H5AD, Parquet, OME-TIFF, VCF,
  BED, GeoJSON, FASTQ and more, small enough to inspect, with declared
  placeholders for heavy binaries.
- **An imperfection engine** — 41 defect rules across 12 categories, six
  maturity profiles, and a machine-readable ledger of every injected defect with
  its expected finding and remediation.
- **Four difficulty tiers** — bronze, silver and gold derived from what evidence
  each rule needs, plus an **adversarial** tier of constructed cases: near-miss
  controls that look like defects and are not, decoys, overlapping evidence, and
  problems where the correct answer is an explicit no-remediation decision.
- **A control partition** — every clean entity named, with a strict reserved
  subset held out of every rule's population, so precision and specificity are
  measurable and flagging everything is visibly penalised.
- **A deterministic evaluator** — pair-level scoring on `(entity, rule)` with
  per-rule denominators, five separately reported dimensions, no weights and no
  composite score.
- **Portable benchmark bundles** — one self-describing, checksummed directory
  that can be published, cited and verified without this repository.
- **Reference baseline agents** — `null`, `naive-metadata` and `rule-based`,
  each reading the observed graph and nothing else, with published canonical
  scores so a new result has something to be compared against. They are
  deliberately simple, and are not production-quality governance agents.
- **An offline DataHub adapter** — Metadata Change Proposals and a ready-to-run
  recipe, with a structural guarantee that the observed export carries no ground
  truth. No DataHub package is a dependency.

### What it is careful about

- **Undefined metrics are `null`, never `0.0`**, and always reported with their
  numerator and denominator.
- **A rule's denominator is its declared population.** A prediction against an
  entity outside it is reported as an out-of-scope false positive rather than
  inflating that rule's true negatives.
- **Determinism is claimed per artefact, not globally.** The truth graph and the
  observed ledgers are byte-identical across the whole supported dependency
  range; the materialized binary files are byte-identical within one environment
  fingerprint, because their writers change between releases. Both are pinned by
  committed golden digests and verified in CI.
- **Truth and observed state stay separate**, in code and on disk. The observed
  layer never mutates the truth graph, and the evaluator mutates nothing.

### Synthetic data only

Every person, institution, study, dataset and identifier is fictional and
synthetically generated; fictional identities use the `dataswamp.example`
domain. There is no patient data, personal data, employer or partner data,
proprietary dataset, confidential scientific information or production schema
copied from any real organisation. The generated data is structurally realistic
and scientifically meaningless: it must not be used to develop or validate
analytical or clinical methods, and passing this benchmark is not evidence of
regulatory compliance.

### Known limitations

- Small by design — a correctness benchmark, not a load test.
- One estate shape and one defect taxonomy. All four difficulty tiers ship:
  bronze, silver and gold are derived from a per-rule reasoning scope
  ([difficulty-tiers.md](difficulty-tiers.md)), and adversarial is a
  *constructed* set of scenario cases
  ([adversarial-scenarios.md](adversarial-scenarios.md)). The adversarial set is
  a **focused initial six case classes** over a small constructed universe — 19
  scored pairs at the demo profile — and is not a model of real-world ambiguity.
  Near misses are single-field and asset-level only; no case yet leaves the
  *finding* itself genuinely underdetermined.
- The published baselines are metadata-only and deliberately simple; none opens
  a materialized scientific file, and no LLM-backed agent ships.
- No run-to-run comparison or regression reporting.
- DataHub export is offline emission only; no live ingestion, no other
  catalogue.
- Scores compare only within one generator version, config fingerprint, profile
  and seed.

### Licensing

Two licences, for two different things:

- **Software — MIT.** Commercial use included, no permission needed.
- **Official generated benchmark data — CC BY-NC 4.0.** The datasets and bundles
  this project distributes, from v0.1.0 onward. Noncommercial research,
  education and noncommercial AI/model/agent evaluation are permitted with
  attribution; commercial use requires separate permission from the project
  owner. Publicly available for noncommercial research — not open source.

Data you generate yourself from the MIT generators is outside the scope of the
data licence. Bundles declare `generated_data_license: CC-BY-NC-4.0` and carry a
verbatim `DATA-LICENSE.md`. See [ADR 0004](adr/0004-generated-data-licensing.md)
and [COMMERCIAL-LICENSING.md](../COMMERCIAL-LICENSING.md).

### Full detail

[CHANGELOG.md](../CHANGELOG.md) · [README](../README.md) ·
[Public API and stability](public-api.md)
