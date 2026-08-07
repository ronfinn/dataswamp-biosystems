# Run comparison and regression reports

The evaluator scores one submission against one ground truth. It cannot answer
the question anyone iterating actually asks: **did my change help?**

`dataswamp compare-runs` answers it by differencing two already-emitted
evaluation directories.

```bash
dataswamp compare-runs \
  --baseline generated/evaluation-v1 \
  --candidate generated/evaluation-v2 \
  --output-dir generated/comparison
```

## Where it sits

Strictly downstream of the evaluation contract. The comparison layer:

- consumes **emitted evaluation output only** — it never re-runs the evaluator;
- reads **no prediction file** and **no observed ground truth**;
- never opens `scenarios.jsonl` or any other privileged answer key;
- **writes nothing** into either input directory.

That is what makes a comparison cheap and reproducible, and what stops it
quietly disagreeing with the evaluations it compares: every number it prints is
the evaluator's own, differenced.

Compare *evaluations*, not predictions. Two prediction files scored under
different conditions are not comparable, and the evaluator is the only thing
that knows what the conditions were.

## Compatibility: what must match

A delta only means something when both sides measured the same universe. If any
identity field differs the comparison is **refused**, exit code 1, and every
differing field is named with both values.

| group | fields |
| --- | --- |
| Universe | `ground_truth_fingerprint`, `profile`, `truth_seed`, `defect_seed`, `observed_generator_version`, `observed_schema_version` |
| Contract | `evaluator_version`, `evaluation_schema_version`, `prediction_schema_version` |
| Shape | `universe.rules`, `universe.evaluated_pairs`, `universe.positive_pairs`, `universe.negative_pairs`, `universe.reserved_control_pairs`, `universe.rules_by_difficulty`, `adversarial.scenarios`, `adversarial.scenario_pairs`, `adversarial.near_miss_controls.declared` |

`ground_truth_fingerprint` is the decisive one — it is a digest of the emitted
observed ledgers, so it already covers the config, the truth graph and the
defect selection behind them. The seeds and profile are checked alongside it
because naming the *cause* is more useful than reporting a changed hash. The
shape fields are redundant given a matching fingerprint, and are checked anyway
as the tripwire for a hand-edited summary whose fingerprint was left intact.

There is deliberately **no config-fingerprint field**: the evaluator does not
emit one, and this layer does not reach past the evaluation contract to recover
it. `ground_truth_fingerprint` is the evaluator's expression of the same fact.

The submission's own `prediction_sha256` is **not** identity — comparing a run
with itself is a legitimate (and tested) determinism check.

## Delta semantics

Two rules, both inherited from the evaluator.

**An undefined metric stays undefined.** If either side's `value` is `null`, the
delta is `null` and the direction is `undefined`. A fabricated zero on one side
becomes a fabricated delta on the other. Both sides' numerators and denominators
travel with every delta.

**Direction is a field, not a sign.** Rising recall is an improvement; a rising
false-positive rate is not. Every delta carries an explicit `direction` —
`improved`, `regressed`, `unchanged` or `undefined` — beside a
`higher_is_better` flag:

```json
{
  "metric": "false_positive_rate",
  "higher_is_better": false,
  "baseline": {"value": 0.0, "numerator": 0, "denominator": 6944},
  "candidate": {"value": 0.00058, "numerator": 4, "denominator": 6944},
  "delta": 0.00058,
  "direction": "regressed"
}
```

The raw `delta` is always `candidate - baseline`, unmodified. Signs are never
flipped to make "positive means better" true by construction — a flipped number
that disagrees with the two values printed beside it is its own trap. Error
*counts* (false positives, unsafe remediations, missing remediations) carry the
same explicit direction rather than relying on a reader to remember which way
each one points.

## Control preservation

A first-class output, reported before every other detail section. A candidate
that buys recall by flagging clean entities must be impossible to miss.

Both the *stock* and the *flow* are given, because a candidate can hold its
false-positive total steady while moving every false positive to a different
control:

- `new_control_false_positives` / `resolved_control_false_positives`
- `new_reserved_control_false_positives` /
  `resolved_reserved_control_false_positives`
- `unsafe_remediations_on_new_control_false_positives`

Every one is attributed to a named entity and rule in
`control-regressions.jsonl`.

### The implicit true negative

The evaluator emits a finding result only for pairs that carry information, so a
clean, unpredicted, in-scope pair is a true negative that was never written
down. The comparison therefore joins on the **union** of both runs' emitted
pairs and reconstructs the absent side as that implicit true negative. Joining
on the intersection would drop exactly the transition this report exists to
surface — a clean control the baseline ignored and the candidate has started
flagging appears in one file and not the other.

## Rule-level attribution

`rule-regressions.jsonl` carries one record per rule that changed, with rule ids
preserved verbatim. Ranking is by pairs that got worse — defects newly missed
plus clean entities newly flagged, with reserved-control false positives
weighted above ordinary ones — ties breaking on the rule id, so the order is
total and reproducible.

Because the shared serializer sorts JSONL by `id`, rank is an explicit `rank`
field rather than file order. The ranked reading order lives in the Markdown
report and in the summary's `ranked_regressions`.

## Difficulty and adversarial

Difficulty tiers are compared independently, taken from the tiers the runs
themselves published — a tier absent from both is never fabricated, and an
undefined metric on either side leaves the delta undefined.

Adversarial comparison is **aggregate-only**, and the payload says so
(`per_case_attribution_available: false`). The evaluator publishes adversarial
results as aggregate blocks and by case type; it does not tag individual pairs
with scenario membership. Recovering that would mean reading the privileged
scenario answer key, which this layer never opens. What is reported: net
movement of the adversarial confusion matrix, near-miss control false positives
and their rate, near-miss unsafe remediations, explicit no-remediation
decisions, and per-case-type blocks.

## Output

```
comparison/
  comparison-summary.json        the whole comparison, machine-readable
  metric-deltas.json             every delta, including breakdowns not in the report
  pair-transitions.jsonl         every (entity, rule) pair whose outcome moved
  rule-regressions.jsonl         per-rule change with an explicit rank
  control-regressions.jsonl      control false positives gained and lost
  remediation-regressions.jsonl  remediation decisions that changed
  comparison-report.md           the human-readable report
  provenance.json                environment and scenario provenance
```

Output is deterministic: identical input directories produce byte-identical
output, with no wall-clock value anywhere. The comparison layer versions its own
contract — `comparison_schema_version` — and changes no other layer's schema.

## Exit codes

| code | meaning |
| --- | --- |
| 0 | compared, whatever the result |
| 1 | the runs are not comparable; every differing identity field is named |
| 2 | an evaluation directory could not be read, or the output directory is unsafe or non-empty |

**A regression does not fail the command.** This release answers *what changed*;
thresholds and CI gating are a policy question the project has no contract for
yet, and inventing one here would bake an arbitrary threshold into every
downstream pipeline. `comparison-summary.json` carries
`verdict_is_advisory: true` to say so explicitly.

## Worked example

```bash
# score two submissions against the same ground truth
dataswamp evaluate --observed-dir generated/observed \
    --predictions v1.jsonl --output-dir generated/eval-v1
dataswamp evaluate --observed-dir generated/observed \
    --predictions v2.jsonl --output-dir generated/eval-v2

# ask what changed
dataswamp compare-runs \
    --baseline generated/eval-v1 \
    --candidate generated/eval-v2 \
    --output-dir generated/comparison
```

```
Comparison written to generated/comparison (profile demo, 180 pair(s) changed).
  findings: 0 newly solved, 176 newly broken
  control false positives: 4 new (3 on reserved controls), 0 resolved
  rules: 41 regressed, 0 improved
  remediations: 181 changed (181 regressed)
  control_preservation: -0.0006 (regressed)
  finding_detection: -0.9890 (regressed)
  non_remediation_correctness: n/a (undefined)
  ...
```

Note the last line: the baseline never had a non-remediable finding to decide
on, so that dimension was undefined on one side — and the delta stays undefined
rather than becoming a misleading zero.

## Related

- [evaluation.md](evaluation.md) — the scoring contract this consumes
- [difficulty-tiers.md](difficulty-tiers.md)
- [adversarial-scenarios.md](adversarial-scenarios.md)
- [public-api.md](public-api.md)
