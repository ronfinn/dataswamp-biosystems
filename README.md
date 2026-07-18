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

## Current milestone: canonical company model

This repository contains packaging, tooling, a CLI, and the **canonical company
model** — a fictional oncology company (programmes, studies, teams, people,
ownership/stewardship, and controlled vocabularies) defined in YAML under
`config/` and validated by typed Pydantic models. See
[docs/domain-model.md](docs/domain-model.md).

The company model is deliberately catalogue-independent: it knows nothing about
DataHub, any truth graph, or any downstream consumer. Those are future
milestones — see Roadmap below.

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

- A deterministic **truth graph**: the complete, correct synthetic scientific
  and governance state generated from the canonical model.
- A **scientific-file estate**: small, genuinely-readable example files
  materialized for the truth graph's assets.
- An **imperfection engine**: a deliberately-imperfect observed state derived
  from the truth graph, with a machine-readable ledger of every injected defect.
- Scenario packs and assessment agents scored against expected findings.
- Optional integration with DataHub for catalog/governance, kept
  architecturally independent of the core model.

Do not assume any of the above exists until it has been implemented and
documented here.

## License

MIT — see [LICENSE](LICENSE).
