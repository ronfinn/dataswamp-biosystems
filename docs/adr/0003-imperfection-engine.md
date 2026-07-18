# ADR 0003: Derive the observed state with a defect registry over truth copies

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

[ADR 0002](0002-truth-vs-observed-state.md) committed to keeping the correct
**truth graph** and a future **observed state** distinct — in code, on disk, and
in dependency direction. This milestone builds the engine that produces the
observed state: a deliberately-imperfect view for benchmarking governance agents.

The benchmark needs more than a degraded graph. For each injected defect it must
record what changed (before → after), what an agent should find, and what the fix
is — machine-readably — and it must be exactly reproducible from a seed. It must
also avoid corrupting the truth it scores against, and must not produce
contradictory or impossible states that would make scoring ambiguous.

Two shaping decisions were required:

1. **How to represent the observed graph.** The strict, frozen truth models
   reject the very states defects need to express (empty owner, invalid term,
   inverted size, dangling reference).
2. **How to author defect definitions.** Either declaratively in YAML (like the
   vocabularies and generation plan) or in code (like the estate's file sets and
   profile specs).

## Decision

- **Mutate JSON copies, never truth instances.** The engine regenerates the truth
  graph in memory, dumps it to plain JSON, and applies mutations to an
  independent working copy. Truth entities are never mutated; a guard test proves
  the truth object is unchanged after a run. The observed graph is a relaxed
  collection of JSON objects so defects can express states the truth models
  forbid.
- **Author defects in an in-code registry.** Each defect type is a `DefectDef`
  pairing metadata (rule id, severity, applicability, remediation semantics,
  compatibility, multiplicity) with a `population` predicate and a `mutate`
  callable. This keeps the mutation logic and its metadata together, type-checked,
  and directly testable — mirroring the estate's in-code approach.
- **Record everything explicitly.** Four ledgers (`injected-defects`,
  `mutation-log`, `expected-findings`, `expected-remediations`) make every defect,
  every field change with before/after, and every expected finding and
  remediation first-class and machine-readable. The observed graph itself carries
  no defect annotations.
- **Deterministic selection with controls and a conflict ledger.** Defects are
  applied in sorted rule-id order over sorted, seed-shuffled eligible populations;
  a control partition reserves clean assets; and a conflict ledger blocks
  incompatible rules, locked-path collisions, and deletion of already-mutated
  records — so runs are replayable and never self-contradictory.
- **Observed-graph-only file integrity (for now).** Checksum and missing-file
  defects mutate the observed file view; the materialized estate is not touched.
  Real estate corruption is a declared future extension.

## Consequences

**Positive**

- Scoring has trustworthy ground truth: the truth graph cannot be corrupted, and
  every mutation stores the correct `before` value.
- Full reproducibility from `(config, truth seed, defect seed, profile)`, verified
  by a byte-for-byte regeneration tripwire.
- Adding or tuning a defect is a localized change to one registry entry; profiles
  are pure rate knobs.

**Negative / costs**

- Working on JSON dicts loses the truth models' static guarantees inside the
  engine; fidelity and structural checks in `validate-observed` compensate.
- Data is represented twice (truth and its defective copy), and scoring needs the
  mutation log to map observed entities back to truth.

**Neutral**

- Dependencies point only from the derived observed layer toward truth, never the
  reverse — consistent with ADR 0001 and ADR 0002.
