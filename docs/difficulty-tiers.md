# Benchmark difficulty tiers

A DataSwamp score is only interpretable if you know what was hard about the
thing being scored. "Recall 0.52" means very different things depending on
whether the missed findings were absent fields or wrong-but-well-formed values
that only a peer comparison exposes. This document defines the difficulty axis,
what it deliberately is *not*, and how to use it.

> **Status.** This is the first of two milestones on benchmark difficulty. It
> ships bronze, silver and gold, tier-restricted generation, and per-tier
> evaluation. **Adversarial scenarios are not implemented** — see
> [Why adversarial is deferred](#why-adversarial-is-deferred).

## Contents

- [What difficulty means here](#what-difficulty-means-here)
- [What difficulty is not](#what-difficulty-is-not)
- [Reasoning scopes](#reasoning-scopes)
- [The tiers](#the-tiers)
- [The classification](#the-classification)
- [Generating a tier](#generating-a-tier)
- [Per-tier evaluation](#per-tier-evaluation)
- [Measured baseline results by tier](#measured-baseline-results-by-tier)
- [Why adversarial is deferred](#why-adversarial-is-deferred)
- [Classifying a new rule](#classifying-a-new-rule)
- [Compatibility](#compatibility)

## What difficulty means here

Difficulty is **how much evidence a detector must relate before it can decide**,
and nothing else. It is a property of the *detection* problem a rule poses.

That definition was chosen because it is the only one that can be checked. "How
hard is this?" is a judgement nobody can audit. "How many records must a detector
read before it can answer?" is a factual claim about the rule, which a reviewer
can agree or disagree with on the evidence.

Difficulty is therefore not declared per rule. Each rule declares a **reasoning
scope** — an objective statement of what a detector must consult — and the tier
follows from the scope by a fixed table. Disagreeing with a tier means
disagreeing with a scope, which is a much more productive argument.

## What difficulty is not

The axis is worthless if it is secretly a restatement of something else. Five
neighbouring concepts, and what each actually controls:

| Concept | Controls | Where it lives |
| --- | --- | --- |
| **maturity** (profile) | *How many* defects are injected | `--profile`, `observed/profiles.py` |
| **scale** | *How large* the estate is | `config/truth/generation-plan.yaml` |
| **category** | *What kind* of governance concern a rule is | `Category` |
| **severity** | *How much it matters* once found | `Severity` |
| **remediation** | *How hard it is to fix*, and who approves | `RemediationAvailability`, `ApprovalPolicy` |
| **difficulty** | *How hard it is to find* | `ReasoningScope` → `Difficulty` |

A high-severity defect can be trivial to spot — a missing owner is critical and
takes one field lookup. A low-severity one can need multi-hop reasoning. A rule
that is automatically remediable can be very hard to detect, and a
non-remediable one can be obvious. So:

- **difficulty is not derived from severity.** Every tier spans multiple
  severities, and no severity is confined to one tier.
- **difficulty is not derived from the maturity profile.** No profile knob is
  keyed by tier; the two are independent filters that compose.
- **difficulty is not derived from remediation availability or approval policy.**
  Every tier spans multiple remediation contracts.

These are not claims in prose. `tests/observed/test_difficulty.py` refutes each
one against the live registry, and `dataswamp validate-defects` fails if a rule
is unclassified.

Difficulty *does* correlate with category, and that is expected rather than a
defect: every metadata-completeness rule genuinely is decidable from one record.
Category is what kind of concern a rule addresses; difficulty is what it takes to
find it. The correlation is a fact about governance, not a smuggled synonym.

## Reasoning scopes

Four scopes, ordered by how much a detector must hold in view at once.

### `single-record`

One record, its own fields. No other record is needed, and no knowledge of what
the value *should* have been. One condition over one dictionary decides it.

Two fields of the *same* record contradicting each other is still a single
record — `USE-EXTERNAL-VS-RESTRICTED` is single-record even though it compares
two values, because both values are right there.

### `cross-record`

The entity plus a record directly attached to it: its governance record, its data
contract, its quality checks, its training approval, its own files. One join, and
the join key is already present on the record.

### `cross-asset`

Two or more catalogue assets, or a lineage path of more than one edge. The defect
is invisible from either end alone — `NAM-DUP-FINAL-VERSION` cannot be seen by
looking at one asset, because the problem *is* the pair.

### `peer-relative`

Correctness is only decidable by comparison against comparable peers: the other
datasets in the study, or the estate's prevailing conventions. Nothing about the
entity is malformed. It is *wrong*, which is strictly harder than being empty —
a detector must know what right looks like before it can see that this is not it.

## The tiers

| Tier | Scopes | Rules | The question a detector must answer |
| --- | --- | ---: | --- |
| **bronze** | `single-record` | 13 | Is this field present and self-consistent? |
| **silver** | `cross-record` | 15 | Does this record agree with the one attached to it? |
| **gold** | `cross-asset`, `peer-relative` | 13 | Does this hold up against the rest of the estate? |
| **adversarial** | — | 0 | *(reserved — not implemented)* |

Peer-relative joins cross-asset at gold rather than forming a fourth tier: both
demand that the detector hold several entities in view at once, and neither is
decidable from a single join. Splitting them would imply an ordering between
"two assets" and "the conventions of the estate" that the benchmark cannot
defend.

The tiers are **nominal, not numeric**. Nothing in this project averages them
into a single "difficulty score", and a gold result is not "three times" a bronze
one.

## The classification

Every one of the 41 rules appears in `RULE_REASONING_SCOPES`
(`src/dataswamp_biosystems/observed/difficulty.py`), in one table, so the whole
tiering can be reviewed on one screen. The assignment *is* the product claim, and
a claim that cannot be read in one place cannot be audited.

Inspect it from the CLI:

```bash
uv run dataswamp list-defects           # each rule shows [category/severity/difficulty]
uv run dataswamp list-defects --json    # + a difficulty_coverage block
uv run dataswamp validate-defects       # fails if any rule is unclassified
```

Or from Python:

```python
from dataswamp_biosystems.observed import (
    difficulty_for, reasoning_scope_for, rules_at, rules_by_difficulty,
)

reasoning_scope_for("OWN-OWNER-MISSING")   # ReasoningScope.SINGLE_RECORD
difficulty_for("OWN-OWNER-MISSING")        # Difficulty.BRONZE
rules_at(Difficulty.GOLD)                  # ('GOV-RESTRICTED-AS-INTERNAL', …)
rules_by_difficulty()                      # every tier, in tier order
```

There is no default. Looking up an unclassified rule raises
`UnknownRuleDifficultyError` naming the rule and the table to add it to, and
`validate_registry` reports it as a registry error — so a new rule cannot be
added without stating what it takes to find.

## Generating a tier

```bash
uv run dataswamp inject-defects \
  --truth generated/truth \
  --profile demo \
  --difficulty bronze \
  --output-dir generated/observed-bronze
```

`--difficulty` accepts `bronze`, `silver`, `gold` and `mixed`. It defaults to
`mixed`, which is the full rule catalogue and is **byte-identical** to the
behaviour before tiers existed.

`--profile` and `--difficulty` are independent filters that compose:

- the profile sets *how many* defects are injected (rates, caps, control
  fraction);
- the tier sets *which rules* may inject them.

A tier restricts the rule set and nothing else. Record schemas, the observed
schema version (3), the generator version (1.2.0) and every file name are
unchanged; a tier run emits the same files as a mixed run, with a smaller rule
scope inside them.

### What a tier run is not

A tier run is **not** a subset of the mixed run. Per-rule selection is keyed by
rule id, so a rule draws the same candidates in either run — but the profile's
global cap, per-entity cap and rule-incompatibility ledger are shared across
whichever rules are present. With fewer rules competing, some entities that lost
to a cap in the mixed run are available in a tier run. Tier and mixed results are
each internally consistent and separately reproducible; they are not arithmetic
rearrangements of each other.

### Empty intersections fail

A tier and a profile that leave no rule anything to draw from is an error, not an
empty benchmark:

```
$ uv run dataswamp inject-defects --profile gold --difficulty bronze ...
Could not inject defects: difficulty 'bronze' and profile 'gold' have an empty
intersection: none of the 13 bronze rule(s) has an eligible entity (the profile
reserves 100% of assets as controls), so no defect could be injected; choose
another profile or tier rather than publishing a benchmark nothing can be scored
against.
```

A benchmark with an empty universe is not a hard benchmark, it is a broken one:
every agent scores identically on it and the report still looks like a result.
The check runs only when a tier was explicitly requested, so `--profile gold`
alone still produces its intended pristine, defect-free scenario.

### Where the tier is recorded

In `provenance.json`, under `scenario.difficulty`, and only when a tier was
chosen. It is deliberately *not* in `profile-summary.json`, `observed-graph.json`
or any ledger record: those are ground truth, covered by the golden digests, and
a mixed run's bytes must not move. `validate-observed` reads the tier back from
provenance so it regenerates the same benchmark it is checking.

## Per-tier evaluation

The evaluator groups results by the difficulty of each pair's rule. Difficulty is
looked up in the rule registry, never read from ground truth — duplicating it
into the emitted ledgers would let a stale file disagree with the live
classification.

**Evaluation schema version 2** adds this. Nothing that existed at schema 1
changed shape or meaning; the new material is additive:

- `summary.findings.by_difficulty` — one block per tier;
- `summary.universe.rules_by_difficulty` — rules contributed per tier;
- `difficulty-metrics.jsonl` — one row per tier, same shape as
  `rule-metrics.jsonl` and `category-metrics.jsonl`;
- a **By difficulty** section in `evaluation-report.md`.

Each `by_difficulty` block carries the full confusion matrix (`tp`, `fp`, `fn`,
`tn`, `positives`, `negatives`, `predicted_positive`, `total`), the standard
metrics, a `reserved_controls` sub-block with false positives and the false
positive rate, and a `remediation` sub-block with coverage, correctness given a
true positive, end-to-end correctness and unsafe-action counts.

The evaluator's existing rules are unchanged and apply per tier:

- **the tiers partition the matrix.** Every scored pair belongs to exactly one
  tier; per-tier cells sum to the overall cells. This is asserted, not assumed.
- **no denominator inflation.** A tier's population is the union of its rules'
  populations, read from `rule-scope.jsonl`, never a cross product.
- **out-of-scope predictions stay outside.** They never enter a tier denominator.
- **undefined metrics are `null`**, with their numerator and denominator, never
  `0.0`. A tier with no pairs — every tier but one, in a tier-restricted run —
  reports `null`, because an unmeasured tier is not a perfect one.
- **counts are summed before dividing.** Tier metrics are micro, computed from
  cells.
- **`unknown` is a defensive bucket only.** It appears in a report only if an
  unclassified rule somehow reached scoring, which `validate-defects` prevents.
  Its presence is itself the signal; it is never reported as an empty routine
  row.

## Measured baseline results by tier

The three reference baselines, unmodified, against the canonical `demo`
scenario at each tier. **Reported as measured — nothing here was tuned**, and
these agents were written before tiers existed.

Confusion matrix and micro metrics per tier:

| tier | agent | TP | FP | FN | TN | precision | recall | specificity | F1 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| bronze (63 defects, 13 rules) | null | 0 | 0 | 63 | 2012 | n/a | 0.0000 | 1.0000 | 0.0000 |
| | naive-metadata | 53 | 0 | 10 | 2012 | 1.0000 | 0.8413 | 1.0000 | 0.9138 |
| | rule-based | 61 | 0 | 2 | 2012 | 1.0000 | 0.9683 | 1.0000 | 0.9839 |
| silver (76 defects, 15 rules) | null | 0 | 0 | 76 | 2798 | n/a | 0.0000 | 1.0000 | 0.0000 |
| | naive-metadata | 0 | 0 | 76 | 2798 | n/a | 0.0000 | 1.0000 | 0.0000 |
| | rule-based | 45 | 0 | 31 | 2798 | 1.0000 | 0.5921 | 1.0000 | 0.7438 |
| gold (62 defects, 13 rules) | null | 0 | 0 | 62 | 2110 | n/a | 0.0000 | 1.0000 | 0.0000 |
| | naive-metadata | 16 | 10 | 46 | 2100 | 0.6154 | 0.2581 | 0.9953 | 0.3636 |
| | rule-based | 0 | 0 | 62 | 2110 | n/a | 0.0000 | 1.0000 | 0.0000 |

And the same agents on the canonical **mixed** benchmark, broken out by tier
(one run, `by_difficulty`):

| agent | tier | pairs | positives | TP | FP | FN | precision | recall | F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| naive-metadata | bronze | 2075 | 54 | 45 | 0 | 9 | 1.0000 | 0.8333 | 0.9091 |
| | silver | 2874 | 70 | 0 | 0 | 70 | n/a | 0.0000 | 0.0000 |
| | gold | 2172 | 53 | 14 | 6 | 39 | 0.7000 | 0.2642 | 0.3836 |
| rule-based | bronze | 2075 | 54 | 52 | 0 | 2 | 1.0000 | 0.9630 | 0.9811 |
| | silver | 2874 | 70 | 40 | 0 | 30 | 1.0000 | 0.5714 | 0.7273 |
| | gold | 2172 | 53 | 0 | 0 | 53 | n/a | 0.0000 | 0.0000 |

### Reading these results

**Tier performance is not monotonic, and the benchmark does not assume it is.**

- The **rule-based** baseline is near-perfect at bronze (F1 0.98), competent at
  silver (0.74) and scores **exactly zero at gold**. That is the honest result:
  it re-implements a transparent subset of the rules against observed metadata,
  and none of the subset it implements is a gold rule. Cross-asset and
  peer-relative detection is not something a small hand-written checker does by
  accident.
- The **naive-metadata** baseline scores *higher at gold than at silver* — 0.36
  versus 0.00. It is not better at gold reasoning; it flags shallow single-field
  signals that happen to coincide with some peer-relative rules, and its
  precision there (0.62, its only false positives anywhere) shows the coincidence
  for what it is.
- The **null** baseline is unchanged everywhere by construction: 0.0000 recall
  and 1.0000 specificity, the floor and the ceiling.

Read together, the tiers say something the mixed score hides: the practical
ceiling for a non-learning metadata-only approach is very high on bronze, real
on silver, and *zero* on gold. That gap is what the tier axis exists to expose.

These numbers are pinned cell by cell in `tests/baselines/test_tier_scores.py`,
written out by hand rather than regenerated, so a behaviour change has to be
re-measured and re-typed by whoever makes it.

## Why adversarial is deferred

`Difficulty.ADVERSARIAL` exists as an enum member and **no rule holds it**.
`rules_at(Difficulty.ADVERSARIAL)` is empty, the CLI does not offer it, and
`selectable_rules` raises `UnavailableDifficultyError` if it is requested through
the Python API.

That is deliberate. Adversarial is a property of a *scenario*, not of a rule: the
same rule can appear in a bronze positive case and in an adversarial near-miss
control — an entity that looks exactly like a defect and is correct. Producing
those needs a scenario layer that can construct near-miss controls and reason
about reserved entities, which is the second milestone.

Relabelling ordinary rules "adversarial" to populate the tier would be a lie
about what the tier means, and generating an empty adversarial benchmark would be
worse: it would look like a result. So the member stays reserved, and requesting
it is an error that says so.

Adversarial scenarios, near-miss controls, `scenarios.jsonl` and the
observed-state schema 3 → 4 migration are the second pull request. **Issue #16 is
not complete.**

## Classifying a new rule

Adding a defect rule requires one line in `RULE_REASONING_SCOPES`. Nothing else —
the tier follows.

Ask, in order:

1. **Can a detector decide from this record's own fields alone?**
   Yes → `single-record`. Comparing two fields of the same record still counts.
2. **Does it need exactly one directly-attached record, via a key the entity
   already carries?** Yes → `cross-record`. Its governance record, contract,
   quality checks, files.
3. **Does it need two or more catalogue assets, or a lineage path longer than
   one edge?** Yes → `cross-asset`.
4. **Is the value well-formed but wrong, decidable only against siblings or the
   estate's conventions?** Yes → `peer-relative`.

Answer the question about *evidence*, not about how clever the fix is or how
much the defect matters. If you find yourself reaching for "this one feels
harder", you are answering a different question.

Then run `uv run dataswamp validate-defects`. An unclassified rule fails there,
and `tests/observed/test_difficulty.py` will fail on the pinned distribution —
update `EXPECTED_DISTRIBUTION`, this document's tier table, and the measured
baseline results together, since they all move.

Changing the *meaning* of a tier, or the scope-to-tier table, means bumping
`DIFFICULTY_MODEL_VERSION`: a previously published tier result stops being
comparable.

## Compatibility

What this milestone did **not** change:

| Contract | Version | Status |
| --- | --- | --- |
| Observed schema | 3 | unchanged |
| Observed generator | 1.2.0 | unchanged |
| Prediction schema | 1 | unchanged |
| Evaluation schema | 1 → **2** | additive only |
| Bundle layout | unchanged | a bundle carries the new file like any other |
| DataHub export | unchanged | reads `observed-graph.json` alone, as before |

- The canonical mixed scenario's bytes are unchanged, and the committed golden
  digests were not regenerated.
- The published canonical baseline scores are unchanged.
- `ControlRecord`, `RuleScopeRecord`, `ExpectedFinding`, `ExpectedRemediation`,
  `observed-graph.json` and `profile-summary.json` gained no difficulty field.
- An evaluation report written at schema 1 remains readable; a schema-2 report
  contains everything a schema-1 reader looked for, in the same places.

## See also

- [`docs/observed-state.md`](observed-state.md) — the imperfection engine and the
  maturity profiles difficulty composes with
- [`docs/evaluation.md`](evaluation.md) — the scoring model the tier blocks sit in
- [`docs/baselines.md`](baselines.md) — the agents measured above
