# ADR 0002: Separate canonical truth from future observed state

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

This milestone introduces the **truth graph**: the complete and correct
synthetic scientific/governance state generated from the canonical company
model (subjects, biospecimens, assays, runs, files, datasets, data products,
contracts, quality, governance, and lineage). It is deterministic — the same
config, generator version, and seed produce byte-identical output.

The point of the benchmark, however, is *defects*. Future milestones will
introduce intentional drift, gaps, and errors, and will represent what a
catalogue or governance tool **observes** after imperfect ingestion — the
"observed state". Governance agents and scenarios will then be scored by how
well their view of the observed state recovers, or diverges from, the truth.

If truth and observed state share one mutable representation, the ground truth
we score against can be silently corrupted by the very defects we inject, and a
generator's correct output becomes indistinguishable from a consumer's degraded
view. That destroys the benchmark's value.

## Decision

Keep the **truth graph** and any future **observed graph** as distinct
representations, distinct on disk, and distinct in code:

- **Truth is authoritative and defect-free.** The truth graph
  (`src/dataswamp_biosystems/truth/`, emitted to `generated/truth/`) is always
  complete, valid, and internally consistent. `generate-truth` validates every
  invariant before writing, and `validate-truth` re-checks them; the generator
  never injects defects.
- **Observed state is derived, never in place.** A future observed graph will be
  produced by a *separate* transformation that reads the truth graph and applies
  defects/drift, writing to a *separate* location (e.g. `generated/observed/`).
  It will not mutate `generated/truth/`.
- **Truth is regenerable and stable.** Because truth is deterministic and
  seed-addressable, it can be regenerated at any time and compared byte-for-byte;
  the manifest records per-shard digests for exactly this.
- **No back-contamination.** Defect logic, observed-state fields, and
  consumer-view concerns must not leak into truth entities or the truth
  generator. Injected defects are test fixtures, not bugs, and are never
  "repaired" by truth-side code.

## Consequences

**Positive**

- Scoring always has a trustworthy reference: the truth graph cannot be
  corrupted by defect injection because defects live in a separate derivation.
- Reproducibility: truth can be regenerated and diffed; observed runs can be
  reproduced from (truth seed, defect seed) without ambiguity.
- Clear separation of concerns keeps the truth generator small and the future
  defect/observed layer independently testable.

**Negative / costs**

- Some data is represented twice (truth and, later, a defective copy), costing
  storage and requiring a mapping from observed entities back to their truth
  originals for scoring.
- The future observed layer must re-read and transform truth rather than
  generating in place, adding a pipeline stage.

**Neutral**

- This mirrors ADR 0001's stance: as the catalogue is an adapter *over* the
  canonical model, the observed state is a derivation *over* the truth graph —
  dependencies always point from the derived view toward the authoritative
  source, never the reverse.
