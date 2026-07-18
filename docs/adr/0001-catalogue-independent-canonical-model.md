# ADR 0001: Maintain a catalogue-independent canonical company model

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

Data Swamp Biosystems needs a stable, machine-readable description of a
fictional oncology company — programmes, studies, teams, people, ownership and
stewardship relationships, and controlled vocabularies — that later milestones
(truth-graph generation, scenarios, catalogue adapters, governance agents) can
all reuse.

A tempting shortcut would be to model this data directly in the vocabulary of a
catalogue or governance product such as DataHub (its URNs, aspects, and entity
types), so that catalogue integration is "free". DataHub integration is,
however, an explicitly optional and future milestone, and the project's
guiding principle is that core generation and governance logic must not depend
on catalogue types, clients, or schemas.

## Decision

We maintain our own canonical model as the single source of truth:

- Business content lives in plain YAML under `config/`, and controlled
  vocabularies under `config/vocabularies/`.
- Typed Pydantic v2 models (`src/dataswamp_biosystems/company/`) define,
  load, and validate it, with our own identifier scheme and project-specific
  validation errors.
- The model imports nothing from any catalogue or governance product, and no
  such product is a dependency.

Any future catalogue integration (e.g. DataHub) will be an **adapter layer**
that consumes this model's manifests/APIs and maps *out* to the catalogue —
never the reverse. The canonical model does not know the catalogue exists.

## Consequences

**Positive**

- The model stays portable across any downstream catalogue, or none.
- Generators, validation, and tests have no third-party catalogue coupling and
  stay fast and offline.
- Identifiers, vocabularies, and schema versioning are ours to evolve
  deliberately via `schema_version`, independent of external release cycles.

**Negative / costs**

- We own an identifier scheme and validation logic that a catalogue might
  otherwise have provided.
- A future adapter must maintain an explicit mapping from our terms to the
  catalogue's model, and keep it in step as either side evolves.

**Neutral**

- Round-tripping to JSON/YAML is straightforward because the models are plain
  Pydantic, easing any future export to a catalogue-specific format.
