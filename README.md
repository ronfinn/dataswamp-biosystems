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

## Current milestone: repository foundation

This repository currently contains **only packaging, tooling, and CLI
scaffolding**. There is no synthetic data generation, no company/programme
model, no truth-graph or lineage generator, no scientific file generation,
and no DataHub integration yet. Those are future milestones — see Roadmap
below.

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

- A canonical company configuration: research programmes, studies, teams,
  fictional people and roles, ownership/stewardship, access classifications,
  retention classes, and a controlled modality vocabulary.
- A deterministic truth-graph generator for synthetic subjects, datasets,
  lineage, quality, and governance manifests.
- A lightweight scientific file-generation layer producing readable example
  files across common bioinformatics and imaging formats.
- Optional integration with DataHub for catalog/governance, kept
  architecturally independent of the core generators.

Do not assume any of the above exists until it has been implemented and
documented here.

## License

MIT — see [LICENSE](LICENSE).
