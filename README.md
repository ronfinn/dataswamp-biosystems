# Data Swamp Biosystems

> **All data, entities, patients, clinicians, institutions, studies, and
> scenarios in this repository — now and in every future milestone — are
> entirely fictional and synthetically generated. No real patient data, real
> health records, or real PHI/PII is used, stored, or processed anywhere in
> this repository, at any milestone.**

Data Swamp Biosystems is an open, entirely fictional synthetic oncology data
estate and governance benchmark. It exists to exercise and demonstrate data
governance, cataloguing, and quality patterns against a realistic-looking but
wholly invented oncology research data landscape.

## Current milestone: scientific-file estate

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

All three layers are deliberately catalogue-independent: they know nothing about
DataHub or any downstream consumer. The imperfection engine / observed state and
DataHub integration are future milestones — see Roadmap below.

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Running the CLI

```bash
uv run dataswamp version
```

Prints the installed package version and exits successfully.

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

## Tests and quality checks

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pre-commit run --all-files
```

## Roadmap

Future milestones (not yet implemented):

- An **imperfection engine**: a deliberately-imperfect observed state derived
  from the truth graph, with a machine-readable ledger of every injected defect.
- Scenario packs and assessment agents scored against expected findings.
- Optional integration with DataHub for catalog/governance, kept
  architecturally independent of the core model.

Do not assume any of the above exists until it has been implemented and
documented here.

## License

MIT — see [LICENSE](LICENSE).
