# Adversarial scenarios

The bronze, silver and gold tiers ask how much evidence a *rule* needs. The
adversarial tier asks something else: given several plausible candidates, can a
detector pick the one that is actually wrong — and leave alone the one that
merely looks it?

That is a property of the situation a rule occurs in, not of the rule. So
adversarial cases are **constructed** rather than sampled, and this document
describes what is constructed, what is guaranteed about it, and what it does not
cover.

> **Scope.** This is a focused *initial* set of six constructed failure modes. It
> is not a model of real-world ambiguity, and it is not exhaustive. See
> [Limitations](#limitations).

## Contents

- [Why the tier cannot be a rule filter](#why-the-tier-cannot-be-a-rule-filter)
- [The six case classes](#the-six-case-classes)
- [Near-miss controls](#near-miss-controls)
- [Control validation: two invariants, not one weakened one](#control-validation-two-invariants-not-one-weakened-one)
- [The privilege boundary](#the-privilege-boundary)
- [`scenarios.jsonl` and `scenario-transformations.jsonl`](#scenariosjsonl-and-scenario-transformationsjsonl)
- [Generating an adversarial benchmark](#generating-an-adversarial-benchmark)
- [Coverage](#coverage)
- [Evaluation](#evaluation)
- [Measured baseline results](#measured-baseline-results)
- [Schema migration](#schema-migration)
- [Limitations](#limitations)

## Why the tier cannot be a rule filter

The other three tiers are a filter over `RULE_REASONING_SCOPES`: pick the rules
whose declared scope is `single-record`, and you have bronze. There is no
equivalent filter for adversarial, because no rule is adversarial. `OWN-DENORM-
MISMATCH` is a silver rule; it becomes an adversarial *case* when three sibling
assets in the same study carry the same owning team on their face and only the
attached governance record distinguishes them.

Two consequences follow, and both are enforced:

- **Relabelling is forbidden.** Taking an ordinary bronze defect and calling it
  adversarial would make the tier measure nothing the other tiers do not already
  measure. There is deliberately no `direct` case class.
- **`selectable_rules(Difficulty.ADVERSARIAL)` still raises.** Returning an empty
  tuple would silently produce a defect-free "adversarial" benchmark, which is
  worse than an error because it looks like a result.

The positives an adversarial run injects are ordinary registry defects, with
ordinary findings, remediations and contracts. What is adversarial is the
composition around them.

## The six case classes

Every class is required. A run that cannot construct one fails, naming it.

| Case class | The reasoning problem | How it is built |
| --- | --- | --- |
| `near-miss-control` | A clean entity that resembles a defect. Every flag is a false positive. | A declared field change on a **reserved** control, chosen to land on the valid side of the rule it mimics. |
| `cross-record-ambiguity` | Several plausible candidates share the surface evidence; only a relational fact identifies the defective one. | `OWN-DENORM-MISMATCH` on an asset whose siblings look identical until the governance record is read. |
| `cross-asset-inconsistency` | Neither asset is defective alone; their disagreement is the defect. | `NAM-DUP-FINAL-VERSION` across two sibling datasets claiming the same final version. |
| `overlapping-evidence` | Two defects on one entity whose evidence overlaps, so each must be attributed to the right rule. | `SCH-CONTRACT-MISSING` **and** `QC-CERTIFIED-CONTRADICTED` on the same asset. Reporting one finding for "this asset looks unmanaged" is wrong. |
| `no-remediation` | Detectable, but not repairable from the catalogue. An explicit no-action decision is correct; proposing a fix is wrong; silence is also wrong. | `MOD-MIXED-GENE-IDS`, whose correct mapping lives in upstream processing. |
| `decoy-candidate` | A nearby clean entity is more superficially suspicious than the defective one. | `NAM-VERSION-NONCANONICAL` on an asset with a bland free-text label, standing beside a reserved control carrying a semver *prerelease* that looks far more irregular. |

The decoy class depends on the near-miss class: a decoy is only a decoy if it is
a control that has actually been dressed to look irregular **under the same rule**
the target violates. A reserved control that merely exists nearby is a
distractor, and calling it a decoy in the answer key would overstate the case.
Targets for that class are therefore restricted to studies that contain such a
near miss, and the planner fails loudly if a later class would mutate one.

## Near-miss controls

A near miss is the only entity in the benchmark that is **deliberately different
from truth and still a negative**. That is a dangerous exception: a near miss
that drifted into being a real defect would sit in the control partition labelled
clean, and every agent that correctly flagged it would be marked wrong.

Four things make the exception safe:

1. **Reserved only.** Near misses are applied exclusively to assets the profile
   holds out of every rule's eligible population *before* selection, so no rule
   could have drawn them even in principle.
2. **Fully declared.** Every field touched is recorded as a
   `ScenarioTransformation` carrying the before value, the after value and the
   rule it mimics — as explicit in the ledger as a mutation is.
3. **On the valid side.** The emitted value is chosen to sit one principled step
   the correct side of the rule's boundary, never as arbitrary noise:

   | Near miss | Mimics | Why it is valid |
   | --- | --- | --- |
   | `logical_bytes == physical_bytes` | `SCH-SIZE-INVERSION` | The rule fires only when logical is *strictly* smaller. Equality is uncompressed, not inverted. |
   | `record_count == 1` | `SCH-RECORD-COUNT-ZERO` | The rule fires only on zero. One is a small but valid dataset. |
   | `version == "1.3.0-rc.1"` | `NAM-VERSION-NONCANONICAL` | A semver prerelease is canonical. It resembles the free-text labels the rule targets without being one. |
   | `access_classification == "restricted"`, no external use | `USE-EXTERNAL-VS-RESTRICTED` | The rule needs *both* halves. Restricted-and-internal is exactly correct handling. |

4. **Machine-checkable.** Each transformation names an executable predicate
   (`NEAR_MISS_VALIDITY_CHECKS`), and the validator re-runs it against the
   *emitted* record. The claim is re-derived from the bytes, not trusted from the
   generator.

A collateral hazard is handled explicitly: some rules mutate a *sibling* rather
than their own subject, so an entity dressed as a near miss could be mutated out
of the control partition. The planner dry-runs the selection's mutations and
strikes every collateral target out of the near-miss candidates before choosing.

## Control validation: two invariants, not one weakened one

The pre-existing rule is that **every control's observed record equals its truth
record, field for field**. That rule is unchanged, and
`tests/observed/test_near_miss_controls.py` re-asserts it over the ordinary
controls of an adversarial run.

A near miss trades that equality for a *stricter, itemised* invariant. All of
the following must hold, and the validator names the scenario, entity, field and
violated clause when one does not:

1. the entity is a reserved control;
2. it appears in no rule's `selected_ids`;
3. it is the target of no `DefectInstance`;
4. it is the target of no ordinary `MutationRecord`;
5. every field that differs from truth is declared by a transformation;
6. no undeclared field differs;
7. each declared change records field path, before value and after value, and
   they match the truth and observed graphs respectively;
8. the emitted record still satisfies the named validity predicate of the rule it
   mimics;
9. it carries no expected finding and sits outside every positive partition.

Both ledgers are read back **from disk** before checking, exactly as
`controls.jsonl` is: a validator that inspected only the regenerated result would
prove the generator consistent with itself and say nothing about the bytes anyone
consumes.

## The privilege boundary

`scenarios.jsonl` and `scenario-transformations.jsonl` are **answer key**. They
sit alongside `expected-findings.jsonl` and `controls.jsonl` on the privileged
side and are listed in `FORBIDDEN_INPUT_FILES`, so no baseline can open one.

An agent *sees* the near-miss value — that is the entire point of the tier — but
never the record saying it was planted, which candidate is the true positive,
what the expected detection or remediation decision is, or the privileged before
value.

There is deliberately **no public scenario view**. A "safe subset" of an answer
key is a boundary that has to be re-argued every time a field is added, and the
observed graph already carries everything an agent is entitled to.

The DataHub observed export reads `observed-graph.json` alone, so an adversarial
bundle exports exactly what an ordinary one does — the near-miss values travel
with the graph, the scenario records stay behind. `tests/bundle/
test_adversarial_bundle.py` asserts no scenario field appears in the payload.

## `scenarios.jsonl` and `scenario-transformations.jsonl`

Emitted **only** by an adversarial run. An ordinary run emits neither file, so
its byte set is exactly what it was.

`scenarios.jsonl` — one `ScenarioCase` per constructed problem:

| Field | Meaning |
| --- | --- |
| `id` | Derived from the case class and its target, never from a counter, so it is stable across runs. |
| `difficulty` | Always `adversarial`. |
| `case_type`, `polarity` | Constrained enums (`CaseType`, `ScenarioPolarity`). |
| `reasoning_scope` | The deepest scope among the case's rules. |
| `rule_ids`, `categories` | Rules applied (positive) or mimicked (near miss). |
| `target_entity_ids`, `entity_kinds` | What the case is about. |
| `evidence_entity_ids` | Records a detector must also read. Resolved against **truth**: for `SCH-CONTRACT-MISSING` the evidence record is gone from the observed graph, and that absence is the defect. |
| `decoy_entity_ids` | Clean controls placed to be mistaken for the target. |
| `finding_ids` / `control_ids` | The positive's findings, or the near miss's control record. |
| `transformation_ids` | The declared changes that built a near miss. |
| `expected_detection`, `expected_remediation` | `flag`/`no-flag`, and `remediate`/`no-remediation`/`not-applicable`. |
| `rationale` | Why this is hard, in prose. |
| `scenario_model_version`, `difficulty_model_version`, `profile`, `defect_seed`, `truth_seed` | Deterministic provenance. |

`scenario-transformations.jsonl` — one `ScenarioTransformation` per declared
near-miss field change, with `shard`, `entity_id`, `field_path`, `field`,
`before`, `after`, `mimicked_rule_id`, `validity_condition` and `validity_check`.

It is deliberately **not** a `MutationRecord`. A mutation record means "a defect
was injected here" and joins to a defect instance, a finding and a remediation; a
near miss has none of those and must never acquire them by sharing a record type.
Keeping them apart is what lets the validator apply truth equality to ordinary
controls while applying the itemised invariant here.

## Generating an adversarial benchmark

```bash
uv run dataswamp generate-truth --seed 20260717

uv run dataswamp inject-defects \
  --truth generated/truth \
  --profile demo \
  --difficulty adversarial \
  --output-dir generated/observed

uv run dataswamp validate-observed --observed-dir generated/observed
```

Maturity profile, scale and difficulty stay independent: `--profile` still sets
how many defects a *rule-filtered* run injects, and at the adversarial tier the
profile determines the reserved partition (and so which controls can become near
misses) and the per-entity cap.

A profile that cannot support a case class is an error, not a smaller benchmark:

- `gold` reserves every asset, so no positive can be constructed;
- `mostly-good` caps one defect per entity, so `overlapping-evidence` cannot be
  built.

Both fail naming the missing case class.

## Coverage

`profile-summary.json` gains a `scenarios` block for an adversarial run only:
totals (scenarios, positives, near-miss controls, transformations), counts by
case class, cross-record / cross-asset / overlapping-evidence / no-remediation /
decoy counts, the rules, categories and entity kinds represented, and —
importantly — `uncovered_required_case_types`.

Generation **fails** if that last list is non-empty. An adversarial benchmark
missing a case class silently stops measuring the failure mode it exists to
measure.

Coverage deliberately does *not* require every rule or category to appear. The
set is focused on purpose; demanding full coverage would force padding.

## Evaluation

No second scoring engine. The existing evaluator scores the same pairs the same
way, and the adversarial report is a **regrouping** of them — the case-class
counts sum to the tier's confusion matrix.

Two things are specific to the tier:

**A scenario pair is tiered `adversarial`** whatever its rule's own tier, because
the construction is what makes it hard. The rule keeps its honest tier
everywhere else. Every scored pair still lands in exactly one tier, so
`by_difficulty` remains a partition of the matrix.

**The universe is the constructed neighbourhood.** Each rule's population is
restricted to the entities the scenarios name. Pairing the tier's rules with the
whole estate would manufacture thousands of free true negatives and drive
specificity to ~1.0 for any agent — making the hardest tier the one that
discriminates least, which is the exact failure this benchmark exists to avoid.

`evaluation-summary.json` gains an `adversarial` block (always present, empty but
shaped for an ordinary benchmark) reporting the confusion matrix; precision,
recall, specificity and F1; positive support and near-miss negative support;
metrics by case class; the near-miss false-positive rate and unsafe remediations
against near misses; wrong-entity and wrong-rule attributions; correct
abstentions; and correct explicit no-remediation decisions. Per-case-class rows
are also emitted to `scenario-metrics.jsonl`.

Two reporting honesty notes:

- **Wrong-entity and wrong-rule are two lenses, not a partition.** A single false
  positive can be both, and they are never summed.
- **Some near misses cannot be in-matrix negatives.** A control dressed to look
  `restricted` was not restricted in truth, so `USE-EXTERNAL-VS-RESTRICTED` could
  never have drawn it and it is outside that rule's truth-derived population.
  Flagging one is still counted — strictly, as an out-of-scope false positive —
  but folding it into a specificity denominator would mean inventing a
  population. The report says how many near misses were declared, how many were
  scored in the matrix, and the difference.

## Measured baseline results

The three reference agents from [`docs/baselines.md`](baselines.md), run
unmodified against the canonical adversarial benchmark (demo profile, canonical
seeds). **Nothing was tuned for these numbers.**

Universe: 19 scored pairs — 13 positive, 6 near-miss negatives.

| Agent | TP | FP | FN | TN | precision | recall | specificity | F1 | near-miss FPs | wrong-entity |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | ---: | ---: |
| null | 0 | 0 | 13 | 6 | n/a | 0.000 | 1.000 | 0.000 | 0 | 0 |
| naive-metadata | 2 | 2 | 11 | 4 | 0.500 | 0.154 | 0.667 | 0.235 | **2** | 4 |
| rule-based | 7 | 0 | 6 | 6 | 1.000 | 0.538 | 1.000 | 0.700 | 0 | 0 |

By case class, true positives:

| Case class | null | naive-metadata | rule-based |
| --- | ---: | ---: | ---: |
| `cross-record-ambiguity` (3) | 0 | 0 | 3 |
| `overlapping-evidence` (4) | 0 | 0 | 4 |
| `cross-asset-inconsistency` (2) | 0 | 0 | 0 |
| `no-remediation` (2) | 0 | 0 | 0 |
| `decoy-candidate` (2) | 0 | 2 | 0 |
| `near-miss-control` (6 negatives) | 0 FP | **2 FP** | 0 FP |

### Reading these results

The tier is doing what it was built to do, and the results are not flattering to
anyone.

- **The naive agent is fooled by exactly the lookalikes it was meant to be fooled
  by.** It flags a third of the near misses it can see. It "solves" the decoy
  class only because it flags every irregular-looking version — including the
  decoy, which is why its wrong-entity count is 4.
- **The rule-based agent resists every near miss and still fails half the tier.**
  Its precision is 1.000 and its recall 0.538: precise rules do not get fooled,
  but they also never reach a defect that only exists in the relationship between
  two assets.
- **Two case classes defeat all three agents.** `cross-asset-inconsistency` and
  `no-remediation` have zero true positives across the board. That is recorded
  rather than hidden — a benchmark everything passes discriminates nothing — and
  pinned in `tests/baselines/test_adversarial_scores.py` so a future agent that
  *does* solve one is a visible, reviewed event.
- **No agent produces a correct no-remediation decision**, because none of the
  three reasons about remediation at all. The zero unsafe-remediation count is a
  floor, not a win.

Do not read these as a ranking that generalises. The adversarial tier is not
assumed to order agents the same way the ordinary tiers do, and the numbers above
are 19 pairs — small enough that a single case moves them visibly.

## Schema migration

| Contract | Before | After |
| --- | --- | --- |
| Observed schema | 3 | **4** |
| Observed generator | 1.2.0 | **1.3.0** |
| Evaluation schema | 2 | 2 (unchanged) |
| Prediction schema | 1 | 1 (unchanged) |
| Bundle layout | — | unchanged |

Schema 4 is **additive**: two optional ledgers, and a `scenarios` block in
`profile-summary.json` present only for an adversarial run. No record that
existed at schema 3 changed shape or meaning.

A schema-3 observed directory remains readable — it declares no scenarios, and
every scenario-aware path collapses to its previous behaviour.
`SUPPORTED_OBSERVED_SCHEMA_VERSIONS` is `{3, 4}`. Only *adversarial* output
genuinely requires schema 4, because schema 3 has nowhere to put the ledgers.

The canonical benchmark's content did not move. The only canonical bytes that
changed are the two version fields in observed `meta`; every ledger and the whole
truth and estate output are byte-identical, and every measured baseline score is
unchanged. See the compatibility table in
[`docs/difficulty-tiers.md`](difficulty-tiers.md#compatibility).

## Limitations

Stated plainly, because an adversarial benchmark that oversells itself is worse
than none.

- **This is a focused initial set, not a model of real-world ambiguity.** Six
  constructed failure modes, a handful of cases each. Real governance ambiguity
  is far wider — conflicting stakeholders, partial ingestion, genuinely
  underdetermined ownership, defects that are only defects under a policy that is
  itself contested. None of that is here.
- **The universe is small.** 19 scored pairs at the demo profile. Enough to
  discriminate between the reference agents; not enough for confident ranking.
- **Near misses are single-field.** Each dresses one field of one reserved
  control. Multi-field and multi-entity near misses are not constructed.
- **Only datasets and data products carry cases.** No file-level or lineage-level
  adversarial construction exists yet.
- **Two of the eight near misses are outside their mimicked rule's population**
  and so cannot be in-matrix negatives. Reported, not hidden.
- **Abstention is scored, but no case is genuinely underdetermined.** The
  `no-remediation` class tests the remediation contract, not evidential
  underdetermination — the finding itself is decidable. A case where the observed
  graph truly underdetermines the *finding* is not yet constructed.

## See also

- [`docs/difficulty-tiers.md`](difficulty-tiers.md) — the three rule-filtered tiers
- [`docs/observed-state.md`](observed-state.md) — the imperfection engine, control
  partition and maturity profiles
- [`docs/evaluation.md`](evaluation.md) — the scoring model the adversarial block
  sits in
- [`docs/baselines.md`](baselines.md) — the agents measured above
