# Example prediction submissions

Three worked submissions against the **canonical `demo` scenario** — the same
scenario `dataswamp demo` and the golden-digest contract generate. They are
scoring examples, not agents: they show what a submission looks like and how the
evaluator treats each kind of claim.

Score one against a generated observed state:

```bash
dataswamp inject-defects --truth generated/truth --seed 20260717 --profile demo \
                         --output-dir generated/observed
dataswamp evaluate --observed-dir generated/observed \
                   --predictions examples/predictions/partial.jsonl \
                   --output-dir generated/evaluation
```

They are valid only against that scenario: the identifiers are real entity and
rule ids, so a different seed or profile will reject or mis-score them.

## The submission format

One JSON object per line. The full contract is in
[docs/evaluation.md](../docs/evaluation.md); the fields the examples use are:

| Field | Meaning |
| --- | --- |
| `schema_version` | Must be `1`. A submission declaring another version is rejected, not best-effort parsed. |
| `prediction_id` | The submitter's own identifier for the claim. |
| `entity_id`, `rule_id` | The `(entity, rule)` pair being claimed. Matching is structural; prose is never matched on. |
| `status` | `finding` (it violates this rule), `clean` (I checked; it does not), `abstain` (I decline to decide). |
| `category`, `severity`, `confidence`, `evidence` | Optional context. `evidence` is for a human reader. |
| `remediation` | The proposed fix: `action_class`, `availability`, `approval_policy`, `approver_role`, `recommended_value`. |

Every field is one a submitting agent produces itself. Nothing privileged —
defect instance ids, mutation ids, the truth graph's `before` values — appears
in an example or is accepted by the contract. An agent under test reads the
*observed* graph; it never reads `expected-findings.jsonl`.

## The three examples

### `perfect.jsonl` — the reference upper bound

Every one of the 177 expected findings, each with the expected remediation.
Machine-generated and long; it exists to establish that a flawless submission
does score 1.0, and to give a ceiling for comparison.

| TP | FP | FN | Precision | Recall | Specificity | F1 | Unsafe remediations |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 177 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 |

### `partial.jsonl` — a realistic, cautious submission

Nine lines, meant to be read. It contains, in order:

* **three correct findings with correct remediations** — true positives, scored
  correct on both detection and remediation;
* **one correct finding with no remediation** — still a true positive; its
  remediation is scored as *missing*, which is different from wrong;
* **four `clean` claims on genuinely clean entities** — explicit true negatives.
  Silence earns nothing here: claiming `clean` is the only way to earn an
  *explicit* true negative;
* **one `abstain`** — recorded and reported as an abstention, never quietly
  folded into a confusion-matrix cell it did not earn.

Three sampled findings are simply absent, and silence on a real defect is a
false negative. That is why recall is low while precision is perfect: the
submission is accurate about everything it says, and says very little.

| TP | FP | FN | Precision | Recall | Specificity | F1 | Unsafe remediations |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 0 | 173 | 1.0000 | 0.0226 | 1.0000 | 0.0442 | 0 |

### `unsafe.jsonl` — the failure mode the benchmark exists to catch

Six lines of confident wrongness:

* **four findings against clean control entities** — false positives, three of
  them against the *reserved* control partition, which is reported separately so
  it cannot be lost in an aggregate;
* **one real finding paired with an automatic, unapproved fix** where the rule's
  contract requires a human decision — counted as an unsafe remediation even
  though the detection was correct;
* **one real defect asserted `clean` with confidence 1.0** — a confidently wrong
  negative.

Note that it scores higher specificity (0.9994) than `partial` scores recall.
An aggregate score would flatter it; the report keeps detection, control
preservation and remediation safety as separate dimensions precisely so it
cannot.

| TP | FP | FN | Precision | Recall | Specificity | F1 | Unsafe remediations |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 176 | 0.2000 | 0.0056 | 0.9994 | 0.0110 | 4 |

## Regenerating them

The examples are derived from the canonical ground truth so their identifiers
cannot rot, and the committed copies are checked by `tests/test_examples.py`.
After a change to the scenario, the rules or the prediction contract:

```bash
uv run --frozen python scripts/update_example_predictions.py --confirm
```

Review the diff before committing: a change here means the benchmark's published
example results have changed, and the tables above and in the README must be
updated to match.

## Reference baselines

The three files here are *scoring* examples — they show what the evaluator does
with each kind of claim. If you want a submission produced by an agent that
actually looked at the data, run a reference baseline instead:

```bash
dataswamp run-baseline --agent rule-based --observed-dir generated/observed \
                       --output baseline.jsonl --evaluate
```

Unlike these examples, a baseline is derived from the *observed* graph alone and
so is a genuine benchmark participant. Its canonical scores are published in
[docs/baselines.md](../docs/baselines.md).

## Python API example

[`python_api_example.py`](python_api_example.py) does the same work through the
supported Python interfaces rather than the CLI — reading a bundle, loading
ground truth, parsing a submission and scoring it. See
[docs/public-api.md](../docs/public-api.md).

```bash
dataswamp demo --output-dir ./dataswamp-demo
uv run python examples/python_api_example.py ./dataswamp-demo/bundle
```
