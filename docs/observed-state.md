# Observed state and the imperfection engine

The **observed state** is a deliberately-imperfect view of the
[truth graph](domain-model.md), produced by the **imperfection engine**. It is
what a catalogue or governance tool might *observe* after defects, drift, and
gaps have crept into an estate — the counterpart to the complete, correct truth
the engine derives it from. Alongside the observed graph, the engine emits a
full, machine-readable ledger of every injected defect and its expected finding
and remediation, so a future governance agent can be **scored** against known
truth, with a healthy population of untouched controls.

## Where it lives

- **Package:** `src/dataswamp_biosystems/observed/` — depends only on the
  `company/` and `truth/` packages, never on any catalogue tool.
- **CLI:** `dataswamp list-defects`, `dataswamp validate-defects`,
  `dataswamp inject-defects`, and `dataswamp validate-observed`.
- **Output (git-ignored):** `generated/observed/`.

## Consumer, never owner ([ADR 0002](adr/0002-truth-vs-observed-state.md), [ADR 0003](adr/0003-imperfection-engine.md))

The engine is a downstream *consumer* of the truth graph. `inject-defects` reads
a generated truth graph **from disk** (via its `truth-graph.json` manifest),
reconstructs the typed graph from the manifest's seed and verifies it
byte-for-byte against the on-disk shards, then applies defects to independent JSON
**copies** of the truth records. It never opens the canonical files for writing,
never invents an asset the truth graph does not contain, and refuses to write its
output inside the truth directory.

**Truth immutability is checked, not just asserted.** Before processing, every
file under the truth directory is checksummed (SHA-256); after generation and
again after writing, the checksums are re-computed and must be unchanged, or the
run aborts. The recorded checksums are written to `truth-inputs.json` alongside
the observed output.

The observed graph deliberately holds **relaxed JSON objects**, not the strict
truth models — so a defect can express a state the truth models forbid (an empty
owner, an invalid vocabulary term, an inverted size, a dangling reference, an
out-of-bounds coordinate). The observed graph carries **no** defect annotations;
it looks like what a catalogue would actually report. All defect linkage lives in
the ledgers.

## Output layout

```text
generated/observed/
├── observed-graph.json          # meta + every truth shard as post-mutation JSON objects
├── injected-defects.jsonl       # one DefectInstance per applied defect
├── expected-findings.jsonl      # one ExpectedFinding per instance
├── expected-remediations.jsonl  # one+ ExpectedRemediation per finding
├── mutation-log.jsonl           # one MutationRecord per field change (before/after)
├── controls.jsonl               # one ControlRecord per clean entity (the negative class)
├── rule-scope.jsonl             # one RuleScopeRecord per rule (eligible/selected/excluded)
├── profile-summary.json         # meta, distributions (category/severity/rule/modality), controls
├── truth-inputs.json            # SHA-256 of every truth input, verified unchanged
└── summary.md                   # human-readable summary
```

## The ledgers

- **DefectInstance** — the anchor for one applied defect: `rule_id`, `category`,
  `severity`, target entity, `profile`, seeds, and the ids of its mutations,
  finding, and remediation.
- **MutationRecord** — one field-level change. It names the defect instance and
  rule, the affected entity and its type, the JSON-pointer `path` (field or
  relationship target), the operation (`set`/`set_list`/`delete_record`/
  `add_record`), the truth `before` and observed `after` values, the severity,
  seed, profile, a human-readable **selection rationale**, auto-fix eligibility,
  human-approval requirement, reversibility, and the **manifestation**
  (`metadata` vs `physical`). No wall-clock timestamp is recorded — provenance is
  the seed and profile, so runs stay byte-identical. The `before` value is the
  ground truth scoring relies on and is preserved even for deletions and
  missing-value defects, where the observed graph no longer holds it.
- **ExpectedFinding** — the finding an agent is expected to raise. It is
  structured so a future evaluator grants credit on *semantics*, not exact prose:
  `match_fields` holds the machine-matchable keys (rule, entity, category,
  severity, target fields), `observable_evidence` states what is visible in the
  observed graph, `expected_message_semantics` states what the finding must
  communicate, `detection_locator` says where to look, and `remediation_id` links
  the expected fix.
- **ExpectedRemediation** — the fix expected to resolve the finding (metadata
  only; never applied), with `auto_fixable`, `requires_human_approval`,
  `reversible`, and a `truth_reference` back to the correct value.
- **ControlRecord** — one catalogue asset or file that carries *no* injected
  defect: the benchmark's negative class. See
  [The control partition](#the-control-partition).
- **RuleScopeRecord** — the machine-readable selection scope of one rule:
  its population, which entities were control-excluded, which were eligible,
  and which were actually selected.

### Mutation-log semantics

The mutation log is the authoritative, replayable record of *what changed*. Each
row is a single field or relationship edit with a stable id, so an evaluator (or
a debugging human) can reconstruct the exact difference between truth and
observed without diffing whole graphs. Because every row carries its truth
`before` value, the log doubles as the reversal recipe: applying each `before`
back at its `path` restores truth. Deletions store the entire removed record;
additions (e.g. a fabricated cross-study edge) carry the new record as `after`
with a null `before`.

### How expected findings support benchmarking

A future evaluator scores an agent's detections against `expected-findings.jsonl`
by matching on `match_fields` — rule id, entity id, category, severity, and the
affected fields — never on the exact wording of a message. `observable_evidence`
and `expected_message_semantics` describe what a correct finding must surface and
assert, and `remediation_id` ties each finding to the fix in
`expected-remediations.jsonl` (whose `truth_reference` gives the correct value).
This lets an agent earn credit for *finding the right problem on the right
entity* regardless of prose, and lets remediation proposals be scored against a
concrete target. Assessment agents and scoring harnesses themselves are a future
milestone; this milestone produces the labelled ground truth they will consume.

## The control partition

`controls.jsonl` names every catalogue asset and file that carries no injected
defect, so an evaluator can tell "correctly left unflagged" from "missed". The
partition is exhaustive by construction: across assets and files, an entity is
either named by a defect instance or mutation, or it appears in `controls.jsonl`
— nothing is silently omitted from the evaluation population.

Each record carries the entity `id` — the truth-graph identifier, which is also
the id under which the entity appears in the observed graph, and (for asset
controls) the estate manifest's `asset_id`. Note that the materialized estate
assigns generated files their *own* `gf-…` ids in a separate id space, so a
truth `file-…` control joins to the estate through its `parent_asset_id`, not by
file id. Each record also carries its
`entity_kind` and `shard`, the `parent_asset_id` for files, `modality` and
`modality_group`, the `profile`, `defect_seed`, `truth_seed` and
`control_fraction` that reproduce it, `eligible_rule_count`, and
`expected_status: "clean"`.

`reason` says *why* the entity is clean, and `reserved` marks the strict
held-out partition:

| `reason` | `reserved` | Meaning |
| --- | --- | --- |
| `reserved-control-asset` | `true` | The profile held this asset out before selection; no rule could ever draw it. |
| `member-of-reserved-control-asset` | `true` | A file whose dataset is a reserved control. |
| `eligible-unselected` | `false` | The entity was in at least one rule's eligible population and simply was not drawn. |
| `never-eligible` | `false` | No rule's population contained the entity. |

### How controls differ from mutated targets and excluded artefacts

*Mutated targets* are the entities named by `injected-defects.jsonl` and
`mutation-log.jsonl` — the positive class. *Controls* are everything else in the
asset/file population. *Reserved* controls are the subset deliberately excluded
from the benchmark's selection population — a rule's `control_excluded_ids` in
`rule-scope.jsonl` — as opposed to entities that were exposed to selection and
survived it. An entity mutated only indirectly (through its governance,
contract, or training record) is **not** a control: those mutations anchor to
the asset's own defect instance.

### Deriving TP, FP, FN and TN

Join an agent's findings to the emitted ground truth on `(entity_id, rule_id)`
— never on message prose:

- **TP** — an agent finding matching a row in `expected-findings.jsonl`.
- **FP** — an agent finding with no matching expected finding; a finding against
  an id in `controls.jsonl` is an unambiguous false positive.
- **FN** — an expected finding the agent did not raise.
- **TN** — a control the agent did not flag.

Precision is `TP / (TP + FP)` and recall is `TP / (TP + FN)`. Specificity is
`TN / |controls|` over whichever control population the evaluation scopes: all
controls for an estate-wide figure, or — per rule — the rule's `eligible_ids`
minus its `selected_ids`, which is why `rule-scope.jsonl` emits the eligible
population rather than only counts. The structured `eligible_count`,
`control_excluded_count`, `candidate_count` and `selected_count` fields mean no
evaluator ever has to parse the human-readable `selection_rationale` prose.

### How controls are validated

`validate-observed` reconstructs the expected partition from the recorded
profile and defect seed and checks that the emitted ledgers respect it:

- every emitted control resolves to a real truth asset or file;
- control identifiers are unique;
- the emitted set equals the reconstructed partition (missing and extra records
  are both reported, by id);
- each control's `reason`, `reserved`, `entity_kind` and `eligible_rule_count`
  match the reconstruction;
- no `DefectInstance` and no `MutationRecord` *on disk* targets a control;
- every control's record in the observed graph is field-for-field equal to its
  truth record — the record-level equivalent of byte identity, and the strongest
  available evidence a control survived injection untouched;
- every rule has a scope record, its counts match its listed ids, its eligible
  and control-excluded sets are disjoint, and its selected ids are a subset of
  its eligible ids and match the rule's defect instances.

Failures are reported as `control-partition`, `contamination`,
`duplicate-id`, `unresolved-reference` or `unknown-rule` issues naming the
offending entity and the violated invariant, under the existing exit-code
conventions (0 valid, 1 invalid, 2 unreadable).

### Identity, ordering and schema

Control records are sorted by entity id and rule-scope records by rule id, and
every id list within a record is sorted, so output is byte-identical for a fixed
config, truth seed, defect seed and profile — across processes and
`PYTHONHASHSEED` values. Both files are part of the observed-state output
contract and are covered by the regeneration tripwire. Adding them raised
`schema_version` to `2` (generator version `1.1.0`); the pre-existing four
ledgers and the observed graph's records are unchanged.

## Defect taxonomy

Defects are defined in an in-code registry (`observed/defects.py`) spanning
twelve categories: metadata completeness, semantic metadata quality, ownership
and stewardship, naming and versioning, governance and classification, licensing
and intended use, lineage and provenance, schema and structural quality,
modality-specific scientific metadata, AI/model-training readiness, lifecycle and
staleness, and physical file integrity. The initial set ships ~40 rules,
including missing/wrong owner, generic description, missing genome build, mixed
gene identifiers, H5AD without a counts layer, spatial coordinates out of bounds,
missing VCF index relationship, pathology feature table without source-slide
lineage, stale governance review, restricted-marked-internal, absent
model-training approval, cross-study lineage edge, duplicate final versions,
QC-contradicted certification, checksum mismatch, and missing file.

Each rule declares its applicability, prerequisites, mutation, expected evidence,
expected finding and remediation, severity, whether it is auto-fixable or needs
human approval, reversibility, incompatibilities, and multiplicity.

**Physical file integrity is observed-graph-only** in this milestone: checksum
and missing-file defects mutate the observed `PhysicalFileRecord` view; no bytes
under `generated/estate/` are touched.

## Profiles

A profile fixes how many defects are injected, as a per-category rate over each
rule's eligible population, plus a control fraction, a per-entity cap, and a hard
global cap.

| Profile | Character |
| --- | --- |
| `gold` | pristine — no defects |
| `mostly-good` | a few defects, mostly clean |
| `typical` | a moderate mix across every category |
| `poor` | pervasive defects |
| `catastrophic` | defects almost everywhere |
| `demo` (default) | ~100–200 defects across all twelve categories, with a healthy control population |

`profile-summary.json` reports the exact final distribution: totals, controls,
and counts by category, severity, rule, modality group, and entity kind.

## Commands

```bash
dataswamp list-defects                 # print the defect registry (add --json for JSON)
dataswamp validate-defects             # validate the registry itself
dataswamp inject-defects \
  --truth generated/truth/truth-graph.json \
  --seed 20260717 --profile demo       # derive the observed state (default output generated/observed/)
dataswamp validate-observed            # re-check a generated observed state
```

`inject-defects` defaults its output to `generated/observed/`; pass
`--output-dir` for another location and `--force` to overwrite a non-empty one.
`--seed` is the *defect* seed; the truth seed comes from the truth manifest.

The output directory is checked against the command's protected inputs before
anything is staged, renamed or removed. `inject-defects` refuses an output
directory that **is**, **contains**, or **sits inside** the configuration
directory or the truth directory it reads from — the repository root is
therefore refused too, since it contains `config/`. Comparisons use canonicalised
paths, so neither `..` segments, nor symlink aliases, nor (on a case-insensitive
filesystem) differently cased spellings such as `CONFIG` can bypass the check.
Where the filesystem distinguishes case, distinct directories stay distinct. Unsafe
usage exits with code **2**, as does a non-empty output directory without
`--force` (both are CLI usage errors, not data-validation failures). `--force`
permits replacing a non-empty *safe* directory only; it never overrides the
containment check. A sibling such as `generated/observed` alongside
`generated/truth` remains valid.

## Determinism and safety

The same config, truth seed, defect seed, and profile produce byte-identical
output. Determinism is structural: defects are applied in sorted rule-id order
over sorted, seed-shuffled eligible populations; every draw comes from
`sub_rng(defect_seed, …)`; and the shared canonical serializer writes
sorted-key, `\n`, no-BOM bytes with records sorted by id.

Contradictory, impossible, or inapplicable mutations are prevented: per-rule
prerequisites gate eligibility, each mutation asserts its precondition at apply
time, and a conflict ledger blocks incompatible rules, locked-path collisions,
and deletion of an already-mutated record. A control partition keeps a clean
population of assets untouched.

`validate-observed` regenerates the observed state from the recorded seeds and
confirms a **byte-for-byte** match against disk, then checks the ledgers hold
together: structural completeness and referential integrity across the four
streams, fidelity of every mutation's `before` to the truth graph, and the
absence of contradictory mutations — two mutations writing the same
`(shard, entity, field)` path, or one entity carrying two mutually incompatible
rules. It deliberately does **not** enforce the truth-graph invariants on the
observed graph — the observed graph is *supposed* to be broken.

The control partition is enforced by the **engine**, which excludes reserved
control assets from every rule's eligible population at selection time, and is
re-checked independently by `validate-observed`, which reconstructs the expected
partition from the recorded profile and defect seed and verifies the emitted
ledgers against it. See [The control partition](#the-control-partition).

## Limitations

- Physical file integrity is represented in the observed graph only; the
  materialized estate is not corrupted this milestone.
- The control partition covers catalogue assets and files. Non-asset records
  (governance, contract, lineage and similar) are scored through the asset their
  defect instance anchors to, and are not themselves emitted as controls.
- Scoring itself — computing the confusion matrix, weighting and reporting — is
  a downstream concern. This milestone emits the labelled ground truth and the
  validation evidence that make it computable.
- Byte-for-byte determinism is defined within a fixed environment (pinned
  dependency versions), as with the truth graph and estate.
- There are no scenario packs, no assessment agents, no automatic remediation,
  and no DataHub integration here — those are future milestones.

## Reset by regeneration

The observed state is disposable and fully reproducible. To reset, delete
`generated/observed/` and re-run `inject-defects`; the same truth graph, defect
definitions, generator version, profile, and seed reproduce it byte-for-byte.
Never hand-edit the observed graph or the ledgers — regenerate them. The truth
graph is likewise regenerable and is never modified by injection.
