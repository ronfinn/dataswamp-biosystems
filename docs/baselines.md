# Reference baseline agents

Without a published baseline there is no score to beat, and no way to tell
whether a result is good. This document describes the three reference agents
that ship with the benchmark, what each may read, what each scores, and how to
compare your own agent against them.

**They are not production-quality governance agents, and are not offered as
one.** Each is short enough to read in full, has no notion of context, priority
or cost, and reasons about nothing beyond the fields in front of it. Their
purpose is transparency and comparison: a floor, a cautionary example, and a
practical ceiling for a non-learning approach.

## The three baselines

| Agent | What it does | Remediations |
| --- | --- | --- |
| `null` | Claims nothing at all. | none |
| `naive-metadata` | Flags absent, empty, short or oddly-shaped fields, one record at a time. | none |
| `rule-based` | Re-implements 20 of the 41 defect rules against observed metadata. | from the published rule contract |

```bash
dataswamp list-baselines
dataswamp run-baseline --agent rule-based \
                       --observed-dir generated/observed \
                       --output predictions.jsonl
dataswamp run-baseline --agent rule-based --observed-dir generated/observed \
                       --output predictions.jsonl --force --evaluate
```

`--evaluate` runs the ordinary evaluator and writes the ordinary reports; there
is no second scoring path. A baseline submission is an ordinary submission.

## What a baseline may read

Every baseline reads **`observed-graph.json` and nothing else**.

It does not read the truth graph, `expected-findings.jsonl`,
`expected-remediations.jsonl`, `controls.jsonl`, `rule-scope.jsonl`,
`mutation-log.jsonl`, `injected-defects.jsonl`, `profile-summary.json`, a
truth-mode DataHub export, or any fixture derived from ground truth. Reading any
of them would make the published numbers meaningless — `rule-scope.jsonl` alone
would hand over each rule's population, which is most of the way to the answers
by elimination.

This is enforced structurally rather than promised:

* `baselines/observed_input.py` is the only module in the package that opens a
  file for reading, and it opens exactly one filename;
* the forbidden filenames are enumerated in `FORBIDDEN_INPUT_FILES`, and a test
  asserts no other module in the package so much as *names* one;
* a test runs every agent in a directory containing only `observed-graph.json`
  and asserts the output is byte-identical to a run beside the full ground
  truth — the answers are removed, not merely left unread;
* a test records every path the process opens during a run and asserts the set
  is `{observed-graph.json}`;
* a test greps the package for canonical entity-id patterns, so a heuristic
  cannot be quietly coupled to a specific dataset.

### The rule catalogue is not ground truth

Baselines *do* consume the published defect-rule catalogue — the same rule ids,
categories, severities, applicability and remediation contracts that
`dataswamp list-defects` prints. That is the question paper, not the answer key.

The rest of a `DefectDef` is off limits: `population` names the entities a rule
drew from, and `mutate` is the injection routine itself. `baselines/catalogue.py`
projects a metadata-only `RuleFact` at import time, and a test asserts no field
of it holds a callable. The agents never see anything else.

### Declared reads, per agent

`dataswamp list-baselines` prints the observed fields each agent inspects. The
lists are derived from the agents' own check tables, so they cannot drift away
from the code.

## Canonical scores

Scored against the canonical `demo` scenario — 7 121 evaluated `(entity, rule)`
pairs across 41 rules, 177 of them positive, with 2 076 reserved-control pairs.

| Agent | Predictions | TP | FP | FN | Precision | Recall | Specificity | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `null` | 0 | 0 | 0 | 177 | n/a (0 denom.) | 0.0000 | 1.0000 | 0.0000 |
| `naive-metadata` | 65 | 59 | 6 | 118 | 0.9077 | 0.3333 | 0.9991 | 0.4876 |
| `rule-based` | 92 | 92 | 0 | 85 | 1.0000 | 0.5198 | 1.0000 | 0.6840 |

| Agent | Reserved-control FPs | Reserved-control FP rate | Remediation coverage | Remediation correctness | End-to-end |
| --- | ---: | ---: | ---: | ---: | ---: |
| `null` | 0 | 0.0000 | n/a (0 denom.) | n/a (0 denom.) | 0.0000 |
| `naive-metadata` | 0 | 0.0000 | 0.0000 | n/a (0 denom.) | 0.0000 |
| `rule-based` | 0 | 0.0000 | 1.0000 | 1.0000 | 0.5198 |

Runtime for all three is well under a second on the canonical scenario — each is
a single pass over an 180-asset, 571-file graph — so runtime is reported here
rather than pinned in a fixture, where a machine-dependent number would fail on a
slow runner for no reason.

**These numbers are only comparable within one generator version, config
fingerprint, profile and seed.** All four are recorded in
`tests/baselines/fixtures/baseline-scores.json` alongside the ground-truth
fingerprint, and quoting a score without them is quoting nothing.

For reference, the committed [example submissions](../examples/README.md) score
`perfect` at recall 1.0000 and `partial` at recall 0.0226 on the same scenario.

## Reading the results

**The null baseline's precision is `null`, not `0.0`.** It predicted nothing, so
the precision denominator is empty and the quantity was never measured. A
benchmark that reported `0.0` here would be inventing a number; one that folded
specificity into a composite score would rank doing nothing above trying. This is
the first row of the table for exactly that reason.

**The naive baseline is more precise than intended, and that is a finding about
the scenario, not the heuristic.** The `demo` profile's defects skew towards
*removing* field values, and a presence check catches a removed value cleanly.
The heuristic has not become sophisticated; the question happened to suit it. On
a profile whose defects were mostly value *corruption* rather than removal, the
same agent would do much worse. Treat 0.9077 as scenario-dependent.

Its six false positives are worth looking at individually: four are on entities
that genuinely carry a defect, but under a *different* rule —
`NAM-DUP-FINAL-VERSION` sets a version to `final` as a side effect, and the naive
agent reports `NAM-VERSION-NONCANONICAL` instead. Right entity, wrong rule, and
pair-level scoring charges it as both a false positive and a false negative. An
entity-level scorer would have called it a hit.

**The rule-based baseline's perfect precision reflects the estate, not the
agent.** Its checks are structural — a required field is absent, a reference
resolves to nothing, two records disagree — and a synthetic estate that is
internally consistent except where a defect was injected gives such checks
nothing to trip on. Recall of 0.5198 is the honest half of that picture: it
detects roughly half the injected defects and is blind to the rest by
construction.

**All three are silent on the `gold` profile**, which injects nothing. That is
the sharpest false-positive test available, and it is a test, not a claim.

## What the rule-based baseline covers, and what it cannot

It implements 20 of 41 rules:

`AIR-TRAINING-APPROVAL-ABSENT`, `AIR-TRAINING-STATUS-MISMATCH`,
`GOV-CLASS-MISSING`, `GOV-RETENTION-MISSING`, `LIN-DATASET-NO-UPSTREAM`,
`LIN-PROVENANCE-DANGLING`, `META-DESC-MISSING`, `META-MODALITY-META-EMPTY`,
`META-TITLE-MISSING`, `META-VERSION-MISSING`, `OWN-DENORM-MISMATCH`,
`OWN-OWNER-MISSING`, `OWN-STEWARD-MISSING`, `QC-CERTIFIED-CONTRADICTED`,
`SCH-CONTRACT-MISSING`, `SCH-RECORD-COUNT-ZERO`, `SCH-SIZE-INVERSION`,
`USE-EXTERNAL-VS-RESTRICTED`, `USE-INTENDED-USE-MISSING`,
`USE-TRAINING-WITHOUT-APPROVAL`.

The 21 it omits fall into four groups, and the grouping is the useful output:

| Why omitted | Rules |
| --- | --- |
| Needs the bytes on disk | `FILE-CHECKSUM-MISMATCH`, `FILE-MISSING`, `MOD-H5AD-NO-COUNTS-LAYER`, `MOD-MIXED-GENE-IDS`, `MOD-SPATIAL-COORDS-OOB`, `NAM-PATH-CONVENTION` |
| Needs the *correct* value to compare against | `GOV-RESTRICTED-AS-INTERNAL`, `OWN-OWNER-WRONG-TEAM`, `OWN-OWNER-DANGLING`, `SEM-DOMAIN-MISLABELLED`, `SEM-DESC-GENERIC`, `SEM-TITLE-UNINFORMATIVE`, `LIF-STAGE-REGRESSION`, `MOD-GENOME-BUILD-MISSING`, `LIN-VCF-INDEX-MISSING`, `LIN-PATH-NO-SLIDE-SOURCE`, `LIN-CROSS-STUDY-EDGE`, `NAM-DUP-FINAL-VERSION` |
| Needs a vocabulary the observed graph does not carry | `NAM-VERSION-NONCANONICAL` |
| Needs a policy threshold the benchmark does not publish | `GOV-STALE-REVIEW`, `LIF-STALE-ASSET` |

That last group is worth recording, because it was measured rather than assumed.
An early version of this agent flagged `GOV-STALE-REVIEW` when a governance
review predated the graph's epoch anchor by more than 540 days. On the canonical
scenario that fires on **41 assets, of which 5 are genuine defects** — the estate
legitimately contains 36 governance reviews older than that. No principled
observed-only threshold separates them: the injected ones sit at a sentinel date,
and tuning the cut-off to hit it would be memorising the injector rather than
detecting staleness. So both rules are excluded, and both are flagged here as
**under-specified from observed metadata alone**. Detecting them fairly needs a
review-cadence policy the benchmark does not currently publish.

This is the kind of feedback the rule-based baseline exists to produce. It is
recorded as documentation; changing the defect registry is a separate decision.

## Comparing your own agent

1. Generate the canonical scenario, or use a bundle:

   ```bash
   dataswamp demo --output-dir ./dataswamp-demo
   ```

2. Run a baseline against the same observed state, so you have a comparable
   number from the same scenario:

   ```bash
   dataswamp run-baseline --agent rule-based \
       --observed-dir ./dataswamp-demo/generated/observed \
       --output baseline.jsonl --evaluate \
       --evaluation-dir ./dataswamp-demo/baseline-evaluation
   ```

3. Score your own submission the same way, and compare the report's five
   dimensions — detection, control preservation, remediation coverage,
   remediation correctness, and abstention — rather than one aggregate. There
   deliberately is no composite score.

4. Quote the scenario identity with any number you publish: profile, defect
   seed, truth seed, generator version, and the ground-truth fingerprint printed
   in the evaluation report.

Beating `null` on recall is trivial. Beating `rule-based` on recall *without*
losing its precision or its clean reserved-control record is the interesting
target, and the rules it cannot reach are listed above as a map of where the
remaining recall lives.

## Adding another baseline

1. Write a module in `src/dataswamp_biosystems/baselines/` with a class carrying
   a `BaselineInfo` and a `predict(self, observed: ObservedInput)` method that
   yields `Prediction` records. Use `in_order()` so output is sorted on
   `(entity_id, rule_id)`, and `make_prediction()` so the agent block and the
   remediation contract are filled in consistently.
2. Add one line to `baselines/registry.py`.
3. Read only through `ObservedInput`. Do not open files yourself — the isolation
   tests are written against that boundary, and bypassing it is how leakage gets
   in.
4. Regenerate the score fixture and update the tables here and in the README:

   ```bash
   uv run --frozen python scripts/update_baseline_scores.py --confirm \
       --reason "added the <name> baseline"
   ```

The same interface is where a model-backed agent would attach: implement
`BaselineAgent`, take a client as a constructor argument, emit the same
`Prediction` records. No provider integration ships in this milestone, and no
provider client, credential or network access appears anywhere in this package
or its tests.

## Limitations and non-goals

* **Not production agents.** No context, no prioritisation, no cost model, no
  human-in-the-loop, no incremental or streaming operation.
* **Not tuned, and deliberately not tuned.** The agents were not adjusted to
  improve their scores against the canonical answers. Where a check was removed,
  the reason and its measured cost are recorded above.
* **Scenario-bound.** Every number here belongs to one profile and one seed pair.
  A baseline's relative standing can and will change on a different profile.
* **Metadata-only.** None of them opens a materialized scientific file, so the
  whole file-integrity and modality-scientific end of the taxonomy is out of
  reach by construction.
* **No LLM adapter.** Deferred deliberately: a provider integration would bring
  credentials, network access and non-determinism into a benchmark whose value
  rests on having none of those.
