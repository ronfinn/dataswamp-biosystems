# Benchmark evaluation and scoring

The imperfection engine emits labelled ground truth: expected findings, expected
remediations, the control partition and per-rule scope. This document defines the
contract for scoring an agent against it — the prediction schema an agent
submits, the universe those predictions are scored in, how each outcome is
decided, and what the reports mean.

The evaluator computes **evidence, not opinion**. There are no scoring weights,
no readiness index and no single composite score. Weighting detection against
remediation correctness is a judgement about what matters; this layer refuses to
make it on your behalf.

## Contents

- [The prediction schema](#the-prediction-schema)
- [Prediction validation](#prediction-validation)
- [The evaluation universe](#the-evaluation-universe)
- [Matching policy](#matching-policy)
- [Outcome definitions](#outcome-definitions)
- [Metrics](#metrics)
- [Remediation scoring](#remediation-scoring)
- [Abstention and confidence](#abstention-and-confidence)
- [Outputs](#outputs)
- [Determinism](#determinism)
- [CLI usage](#cli-usage)

## The prediction schema

A submission is one **JSONL** file: one JSON object per line, each a prediction
about one `(entity_id, rule_id)` pair. The schema is versioned; the current
version is **1**, declared per record.

The contract is deliberately small. An agent is asked only for what it could
know by inspecting the observed graph — never for ground-truth-only fields such
as defect instance ids, mutation ids or truth `before` values.

| field | required | type | meaning |
| --- | --- | --- | --- |
| `schema_version` | yes | integer | must be `1` |
| `prediction_id` | yes | string | unique within the submission |
| `entity_id` | yes | string | an entity present in the benchmark |
| `rule_id` | no | string | a rule id from `rule-scope.jsonl`; omit if unknown |
| `status` | no | enum | `finding` (default), `clean` or `abstain` |
| `category` | no | enum | a defect category |
| `severity` | no | enum | `low`, `medium` or `high` |
| `confidence` | no | number | finite, in `[0.0, 1.0]` |
| `evidence` | no | string | free prose for a human reader; **never matched on** |
| `evidence_refs` | no | list of strings | pointers into the observed graph or estate |
| `remediation` | no | object | a proposed fix (see below) |
| `agent` | no | object of strings | arbitrary agent metadata |

The three statuses are distinct claims:

- **`finding`** — "this entity violates this rule". The scorable positive claim.
- **`clean`** — "I looked, and it does not". The only way to earn an *explicit*
  true negative.
- **`abstain`** — "I decline to decide". Recorded and counted as its own state,
  never silently folded into a confusion-matrix cell it did not earn.

### The remediation object

| field | required | type | meaning |
| --- | --- | --- | --- |
| `action_class` | yes | string | action family, e.g. `restore_field`, or `no-remediation` |
| `availability` | yes | enum | `automatic`, `manual` or `none` |
| `approval_policy` | yes | enum | `not-required` or `required` |
| `approver_role` | no | enum | `data-steward`, `quality-steward`, `access-steward`, `data-owner` or `none` |
| `action` | no | string | the fuller action string |
| `recommended_value` | no | any | the value the agent would write |

Availability and approval are **independent axes**, exactly as in the rule
contract (see [observed-state.md](observed-state.md#the-rule-and-remediation-contract)).
A change can be mechanically derivable yet still require sign-off, and it can
need no sign-off yet be impossible to automate.

### Example

```jsonl
{"schema_version":1,"prediction_id":"p-1","entity_id":"ds-nsclc-01-genomics-0001","rule_id":"MET-TITLE-MISSING","status":"finding","category":"metadata-completeness","severity":"high","confidence":0.93,"evidence":"title is an empty string","remediation":{"action_class":"restore_field","availability":"automatic","approval_policy":"not-required","recommended_value":"NSCLC-01 bulk RNA-seq counts"}}
{"schema_version":1,"prediction_id":"p-2","entity_id":"ds-crc-01-imaging-0002","rule_id":"MET-TITLE-MISSING","status":"clean","confidence":0.88}
{"schema_version":1,"prediction_id":"p-3","entity_id":"file-crc-01-0007","rule_id":"INT-CHECKSUM-MISMATCH","status":"finding","category":"file-integrity","severity":"high","remediation":{"action_class":"no-remediation","availability":"none","approval_policy":"not-required"}}
{"schema_version":1,"prediction_id":"p-4","entity_id":"ds-crc-01-imaging-0003","rule_id":"OWN-OWNER-MISSING","status":"abstain"}
```

Three small worked fixtures live in `tests/evaluation/fixtures/` — a perfect
submission, a partially correct one and a deliberately poor and unsafe one.

## Prediction validation

A submission is validated **in full before scoring begins**, and the whole file
is inspected before anything is raised, so one run reports every problem. A
broken submission is never partially scored and never silently reduced.

Rejected, each with the line number, field, offending value and the expected
contract:

- malformed JSON, or a line that is not a JSON object;
- an unsupported `schema_version`;
- duplicate `prediction_id`;
- duplicate `(entity_id, rule_id)`;
- an unknown `entity_id` (not present anywhere in the ground truth);
- an unknown `rule_id` (not in `rule-scope.jsonl`);
- an invalid enum value, or any unknown field;
- a non-finite confidence (`NaN`, `Infinity`) or one outside `[0.0, 1.0]`;
- a remediation attached to a `clean` or `abstain` prediction;
- an actionable `action_class` where `availability` is `none`, or
  `no-remediation` where availability is not;
- `approval_policy: required` without a concrete `approver_role`.

A *known* entity outside a rule's population is **not** a validation failure. It
is a scoring outcome — see out-of-scope below.

## The evaluation universe

Scoring is **pair-level** on `(entity_id, rule_id)`, and the pairs come from
`rule-scope.jsonl`. For each rule:

- **population** = `eligible_ids ∪ control_excluded_ids`;
- **positives** = `selected_ids` (equivalently, that rule's expected findings);
- **negatives** = the rest of the population: entities that were exposed to the
  rule and not drawn (`eligible-unselected`), plus the reserved controls the
  profile held out before selection (`control_excluded_ids`).

The evaluation universe is the union of the per-rule populations. On the
canonical `demo` profile that is 7 121 pairs across 41 rules: 177 positives and
6 944 negatives, of which 2 076 are reserved-control pairs.

**Entities outside a rule's population are not negatives for that rule.** Pairing
every rule with every entity would manufacture tens of thousands of free true
negatives and push specificity towards 1.0 for any agent at all. An entity
recorded as `never-eligible` in `controls.jsonl` is known to the benchmark but
enters no rule's denominator.

### Out-of-scope predictions

A prediction naming a known entity that is *outside* the named rule's population
is reported separately as `out_of_scope_false_positive` (or
`out_of_scope_clean` for a non-claim). It is:

- emitted as its own record in `finding-results.jsonl`, with
  `in_scope: false` and `expected_status: "out-of-scope"`;
- counted in `out_of_scope.strict_false_positives` alongside the in-matrix false
  positives;
- **excluded from every metric denominator** — it can neither add a true
  negative nor enlarge the negative class.

## Matching policy

Exact and structural. A prediction scores against the pair named by its
`entity_id` and `rule_id`. Nothing else participates:

- prose (`evidence`, any message) is **never** matched on;
- `category` and `severity` are reported as *attributes* of a matched pair
  (`category_correct`, `severity_correct`) and are never used to rescue a pair
  that did not match, nor to invalidate one that did;
- there is no fuzzy or semantic matching in this milestone.

### Credit without a rule id

A prediction that names no rule cannot occupy a pair — binding it to one would be
a guess dressed up as a match. Such predictions are instead scored in two
coarser universes, each derived from the same rule scopes:

- **entity level** — key `entity_id`; population is the union of all rule
  populations, positives are the entities carrying at least one defect;
- **category level** — key `(entity_id, category)`; population and positives are
  the union over the rules in that category.

Where several predictions collapse onto one coarse key, a single `finding` claim
dominates, then `clean`, then `abstain`. Both universes are reported in
`findings.coarse_universes`, separately from the pair-level matrix.

## Outcome definitions

For an in-scope pair:

| | predicted `finding` | predicted `clean` / `abstain` / no prediction |
| --- | --- | --- |
| **expected present** (a defect was injected) | **TP** | **FN** |
| **expected clean** (in the population, not drawn) | **FP** | **TN** |

`abstain` and "no prediction" fall on the same side of the matrix but are
distinguished on every record and counted separately: silence is not abstention.

## Metrics

All metrics are derived **from counts**, never from other metrics:

| metric | numerator / denominator |
| --- | --- |
| precision | `TP / (TP + FP)` |
| recall | `TP / (TP + FN)` |
| specificity | `TN / (TN + FP)` |
| F1 | `2·TP / (2·TP + FP + FN)` |
| false-positive rate | `FP / (TN + FP)` |
| false-negative rate | `FN / (TP + FN)` |

F1 is computed from counts directly rather than from precision and recall, so it
stays defined whenever any of those counts is non-zero.

### Undefined metrics

Every metric is emitted as `{"value": …, "numerator": n, "denominator": d}`, and
`value` is JSON `null` **exactly when `d == 0`**.

An undefined metric is never reported as `0.0`. Precision with no predicted
positives is not zero — it is a question that was never asked, and emitting a
zero would make a silent agent look maximally imprecise and drag every average
down with a number nobody measured.

### Aggregation

- **Micro** — sum the TP/FP/FN/TN across groups, then divide once. This is the
  headline figure.
- **Macro** — the unweighted mean of each *defined* per-rule value. Groups where
  a metric is undefined are excluded from that metric's mean rather than counted
  as zero, and `group_count` / `total_groups` record how many contributed, so a
  macro recall over 3 of 41 rules can never be mistaken for one over all 41.

Breakdowns are reported by rule, category, severity, entity kind, entity class
(`asset` vs `file`), and control partition (`reserved` vs `non-reserved`). Every
breakdown partitions the same pairs, so its cells sum to the overall matrix.

### Reserved controls

Reserved controls were held out *before* selection, so no rule could ever have
drawn them. They are legitimate negatives and are included in the matrix, and
they are also broken out separately (`reserved_controls`), because a false
positive there is a distinct and more serious failure than one against an
entity that merely happened not to be drawn.

### The five dimensions

`dimensions` restates, without weighting:

| dimension | metric |
| --- | --- |
| `finding_detection` | overall micro F1 |
| `control_preservation` | overall micro specificity |
| `reserved_control_preservation` | specificity on reserved controls |
| `remediation_correctness` | fully-correct rate given a true-positive finding |
| `approval_reasoning` | approval-policy correctness |
| `non_remediation_correctness` | correct explicit no-remediation decisions |

`dimensions` is a pure mapping of dimension to metric block. The summary also
carries `composite_score: null` and `dimensions_are_weighted: false`, stated
explicitly so no consumer has to infer that the dimensions are never combined.

Prefer F1 and specificity over raw accuracy: the negative class outnumbers the
positive one roughly 39:1 on the canonical profile, so accuracy is dominated by
true negatives and rewards doing nothing.

## Remediation scoring

A remediation is scored **only against the expected remediation of a correctly
detected finding**. Four states:

| state | meaning |
| --- | --- |
| `scored` | true-positive finding with a submitted remediation |
| `missing` | true-positive finding with no remediation submitted |
| `unscored-missed-finding` | the finding itself was not detected |
| `unsafe` | an actionable remediation attached to a false positive |

Field-level correctness is reported for availability, approval policy, approver
role (where approval is required), action class and recommended value (where one
is defined). `fully_correct` requires every applicable field to match.

Three distinct rates keep detection and remediation from being confounded:

- **coverage** — submitted / detected findings;
- **correctness given a true positive** — fully correct / submitted;
- **end-to-end** — fully correct / *every* expected finding.

An agent is never penalised as a remediation error for a finding it never
detected — that is a detection error, already counted as an FN — but the
distinction is reported explicitly via `unscored_missed_finding` rather than
being quietly excused.

**A correct non-remediable result is an explicit `no-remediation` decision, not
a missing record.** Omitting the decision scores `missing` with
`no_remediation_correct: false`. Non-remediation correctness is reported twice:
`non_remediation_correct` over the non-remediable findings the agent detected,
and `non_remediation_end_to_end` over all of them.

**Unsafe actions.** An actionable (non-`no-remediation`) fix proposed against an
entity that is actually clean — an in-matrix false positive, a reserved control,
or an out-of-scope entity — is flagged `unsafe_action`, with
`unsafe_on_reserved_control` set where it applies. A detection error stays on
paper; an accompanying remediation would have altered a correct record. A
`no-remediation` decision on a false positive is wrong but harmless and is not
counted as unsafe.

## Abstention and confidence

- On a **positive** pair, `abstain` is a false negative: the defect went
  unreported.
- On a **negative** pair, it is a true negative: nothing was wrongly flagged.
- In both cases the pair is flagged `abstained` and counted in
  `abstention.abstained_pairs`, split across `on_positive_pairs` and
  `on_negative_pairs`. (`submission.abstentions` is the *submission*-level count,
  which also includes any abstention on an out-of-scope pair.)

`abstention.selective` recomputes the whole matrix with abstained pairs removed
entirely, showing what the agent achieves on the pairs it was willing to decide.
`abstention_rate` is over *submitted* predictions, not over the universe — an
agent is not charged for the millions of pairs it never mentioned.

Confidence is summarised deterministically and shallowly: count with and without,
mean, min, max, and mean over finding claims. No calibration framework, no
ROC/AUC — that would be a modelling claim this milestone has no mandate to make.

## Outputs

| file | purpose |
| --- | --- |
| `evaluation-summary.json` | every count and metric, the benchmark and submission fingerprints, the five dimensions |
| `finding-results.jsonl` | one record per *informative* evaluated pair |
| `remediation-results.jsonl` | one record per expected or submitted remediation decision |
| `rule-metrics.jsonl` | per-rule counts and metrics |
| `category-metrics.jsonl` | per-category counts and metrics |
| `evaluation-report.md` | the human-readable scorecard, suitable for a PR comment or CI artefact |
| `provenance.json` | the shared environment/scenario provenance object |

`finding-results.jsonl` deliberately does **not** emit a record for every pair in
the universe: a pair that was expected clean, was not predicted, and scored a
true negative carries no information, and emitting thousands of them would
describe silence at length. Records are emitted for every positive pair, every
pair carrying a prediction, and every out-of-scope prediction. The counts in
`evaluation-summary.json` always cover the full universe.

## Determinism

Identical ground truth, prediction file, evaluator version and configuration
produce **byte-identical** reports. As with every other layer: canonical JSON
with sorted keys, records sorted by id, UTF-8 without BOM, `\n` line endings, no
wall-clock value anywhere in the output, and no reliance on dictionary insertion
or set iteration order. Verified across processes and across `PYTHONHASHSEED`
values in `tests/evaluation/test_cli.py`.

Each summary records the identity of everything it depended on: the
`ground_truth_fingerprint` (a SHA-256 over the ground-truth artefacts in fixed
file order), the `prediction_sha256` (over the submitted bytes exactly as read),
the evaluator and schema versions, and the benchmark profile and seeds. Two
evaluations quoting the same fingerprints were scored against the same benchmark
with the same submission.

The evaluator consumes ground truth and never rewrites it — the committed golden
digests in `tests/golden/canonical-digests.json` are unchanged by this layer, and
that they still match is itself the compatibility assertion.

## CLI usage

```bash
uv run dataswamp evaluate \
  --observed-dir generated/observed \
  --predictions predictions.jsonl \
  --output-dir generated/evaluation
```

Exit codes:

| code | meaning |
| --- | --- |
| 0 | evaluated; reports written |
| 1 | the submission violates the prediction contract |
| 2 | ground truth or predictions could not be read, or an unsafe/non-empty output directory was given |

Ground truth and the submission are both fully validated *before* anything is
written, so an invalid submission never replaces a previous evaluation.

`--output-dir` is replaced wholesale, so the shared containment policy applies
(see `paths.py`): it may not be, contain, or sit inside the configuration
directory, the observed ground-truth directory, or the prediction file.
`--force` overrides only the non-empty check — **never** path safety.

## Reading a report

Read the scorecard first, then the confusion matrix, then the weakest rules.

- A high specificity with a low recall is an agent that says little and is right
  about it — check `abstention` and the FN column.
- A high recall with a low precision is an agent that flags broadly; check
  `reserved_controls.false_positives`, which blanket flagging cannot avoid.
- A strong `finding_detection` with a weak `remediation_correctness` means the
  agent sees the problem but not the fix; `action_class_correct` versus
  `recommended_value_correct` says which half.
- **Any non-zero `unsafe_actions` deserves attention before any metric does.**
  Those are proposed changes to records that were already correct.
