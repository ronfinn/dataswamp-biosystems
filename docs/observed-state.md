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
`--output-dir` for another location (it may not resolve inside the truth
directory) and `--force` to overwrite a non-empty one. `--seed` is the *defect*
seed; the truth seed comes from the truth manifest.

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
absence of contradictory or control-touching mutations. It deliberately does
**not** enforce the truth-graph invariants on the observed graph — the observed
graph is *supposed* to be broken.

## Limitations

- Physical file integrity is represented in the observed graph only; the
  materialized estate is not corrupted this milestone.
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
