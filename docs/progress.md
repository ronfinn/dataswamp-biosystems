# Progress

A running log of completed milestones. Newest first.

## Canonical company model — 2026-07-18

Implemented the canonical, catalogue-independent company model.

- **Config (`config/`):** one company; 3 programmes (NSCLC, TNBC, colorectal);
  6 studies (2 per programme); 7 teams (scientific, platform, governance);
  13 fictional people with roles; 9 ownership and 7 stewardship assignments;
  8 controlled vocabularies (51 terms total). All identities fictional under
  `dataswamp.example`.
- **Models (`src/dataswamp_biosystems/company/`):** Pydantic v2 models grouped
  by concern (identifiers, vocabularies, entities, relationships, generation
  config, assembled config, loader, errors); `extra="forbid"` and typed slug
  identifiers throughout; `schema_version` on every file.
- **Validation:** cross-file loader detecting duplicate ids, duplicate emails,
  invalid domains, unresolved programme/team/person references,
  invalid vocabulary values, and dangling owner/steward assignments — all
  issues collected before failing, with project-specific errors.
- **CLI:** `dataswamp validate-config` prints deterministic entity counts on
  success (exit 0), reports actionable issues (exit 1), and distinguishes load
  failures (exit 2).
- **Docs:** [domain-model.md](domain-model.md),
  [ADR 0001](adr/0001-catalogue-independent-canonical-model.md), README.
- **Deliberately excluded:** subjects, biospecimens, assays, datasets, truth
  graphs, scientific files, defects, scenarios, DataHub, and agents.

## Repository foundation

Python packaging (uv, hatchling, src-layout), dev tooling (ruff, mypy strict,
pytest, pre-commit, CI), and a minimal Typer CLI (`dataswamp version`).
