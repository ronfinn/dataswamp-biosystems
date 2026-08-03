# Reproducibility and the determinism contract

DataSwamp Biosystems is a benchmark, so its central engineering guarantee is
that generation is deterministic. This document states exactly **where** that
guarantee holds, what is tested to prove it, and how an intentional change to
generated output is reviewed.

The short version: byte identity is guaranteed for the committed `uv.lock` on
every supported Python version. Across the wider dependency range the package
permits, the metadata layers are still byte-identical, but the binary scientific
files are not — and the contract says so rather than over-claiming.

## The tiers

| Scope | Guarantee | Proven by |
| --- | --- | --- |
| **Canonical environment** — committed `uv.lock`, Python 3.12 or 3.13 | **Byte-identical** output for every artefact, including the binary estate | `canonical` CI jobs: complete suite + full golden contract |
| **Supported dependency range** — declared minimums up to current, Python 3.12 or 3.13 | Functional correctness, schema validity, and **byte-identical truth-graph and observed-state artefacts** | `lowest-direct` CI jobs: portable golden digests, determinism and CLI suites, wheel install |
| **Across operating systems** | Not claimed | Only Linux (CI) and macOS (development) are exercised |

### Why the estate is different

The truth graph and the observed state are pure-Python canonical JSON and JSONL
written by this project's own serializer, so their bytes depend only on this
project's code. They are stable across the whole supported dependency range.

The materialized estate contains Parquet, TIFF, PNG and H5AD payloads written by
`pyarrow`, `Pillow`, `tifffile` and `anndata`. Those libraries legitimately
change their encodings between releases — compression defaults, metadata
ordering, dictionary encoding — so identical logical content can serialize to
different bytes. Measured example: `pyarrow` 18 and 25 write different Parquet
bytes for the same table, which changes four payload files and therefore the
estate manifest and summary that record their checksums.

This is a property of the ecosystem, not a defect. It is why the estate is
scoped to an **environment fingerprint** rather than claimed range-wide.

### Environment fingerprint

The fingerprint is a SHA-256 over the resolved versions of the eight direct
dependencies. Two environments sharing a fingerprint produce byte-identical
output — *including* the estate.

Python is deliberately **not** part of the fingerprint: Python 3.12 and 3.13 were
verified to produce byte-identical output across all 132 generated files for the
same dependency set, so the dependency set is what determines the bytes.

## Supported Python versions

3.12 and 3.13. Both are tested in CI in all four matrix cells, and both appear in
the package classifiers. Nothing is advertised that CI does not exercise.

## Dependency lower bounds

The declared minimums in `pyproject.toml` are the oldest versions that actually
pass the compatibility suite on **both** supported Python versions. They are not
aspirational: the `lowest-direct` CI jobs install exactly those minimums.

Two bounds were corrected when this contract was introduced, because the
previously declared minimums did not work:

- `pyyaml>=6` → `>=6.0.2`. PyYAML 6.0 has no wheel for Python 3.12 or 3.13 and
  fails to build from source against modern Cython.
- `anndata>=0.11` → `>=0.13`. anndata below 0.13 cannot write the Arrow-backed
  string arrays that current pandas produces, raising `IORegistryError` on every
  H5AD write.
- `typer>=0.15` → `>=0.16`. Typer 0.15 mis-handles a `StrEnum` option default,
  so `inject-defects --profile` rejects its own default value.

`numpy`, `pyarrow`, `pillow` and `pydantic` minimums were raised to the oldest
releases providing Python 3.13 wheels, so a single bound is honest on both
supported versions.

## Environment provenance

Every generated output directory contains one shared `provenance.json`:

```json
{
  "provenance_schema_version": 1,
  "dataswamp_version": "0.1.0",
  "layer": "observed",
  "generator_version": "1.2.0",
  "schema_version": 3,
  "python": { "version": "3.12", "implementation": "CPython" },
  "platform": { "system": "Linux", "machine": "x86_64" },
  "direct_dependencies": { "anndata": "0.13.2", "numpy": "2.5.1", "…": "…" },
  "environment_fingerprint": "19c08c76…",
  "scenario": { "defect_seed": 20260717, "profile": "demo", "truth_seed": 20260717 },
  "synthetic": true
}
```

One object per directory, referenced implicitly by everything beside it, so no
dependency list is copied into individual records.

Provenance carries **no wall-clock value** — it is a pure function of the
environment and the scenario, so repeated runs in one environment write identical
bytes. It is nevertheless excluded from the golden digests, because it is
precisely the artefact expected to differ between a locked and a lowest-direct
run. Determinism is claimed for the benchmark data; provenance is the evidence
needed to interpret that claim.

## The golden contract

`tests/golden/canonical-digests.json` pins a small canonical scenario —
`tiny` estate profile, `demo` observed profile, all three seeds fixed at
`20260717` — defined in `src/dataswamp_biosystems/canonical.py`.

It holds 24 SHA-256 digests in two scopes:

- **`portable_digests`** (21) — truth graph and observed-state ledgers, asserted
  in *every* environment, including lowest-direct.
- **`environment_scoped_digests`** (3) — the estate manifest, generation summary
  and summary, asserted only when the environment fingerprint matches the one
  recorded in the fixture.

Individual materialized files are not hashed directly: the estate manifest
records a SHA-256 per file, so hashing the manifest pins every payload byte
transitively. That keeps the committed contract at two dozen checksums instead of
one per generated file, while still failing on any binary drift. A test verifies
that binding by recomputing every payload checksum against the manifest.

The fixture also records the **config fingerprint**, so a configuration edit is
reported as a configuration change rather than an unexplained digest failure.

### Why this catches what regenerate-and-compare cannot

`validate-truth`, `validate-files` and `validate-observed` regenerate output and
compare it to disk. That proves internal consistency *within the current code*:
if generation and validation change together, they stay consistent and the check
still passes. A committed digest does not move when the code moves, so it fails.

## Updating the golden digests intentionally

Ordinary test runs never rewrite the fixture — `pytest` only compares. Updating
is a separate, deliberate act:

```bash
uv sync --frozen --all-groups     # the canonical environment
uv run --frozen python scripts/update_golden_digests.py \
    --confirm \
    --reason "pyarrow 25 changed parquet dictionary encoding" \
    --cause dependency
```

`--confirm`, `--reason` and `--cause` (`dependency`, `code`, `config` or
`schema`) are all required; without them the script exits non-zero and writes
nothing. Run it only in the canonical locked environment — from any other
environment it refuses to redefine the environment-scoped digests.

### Reviewer checklist

A pull request touching `tests/golden/canonical-digests.json` must answer:

1. **Why did the output change?** The `last_update.reason` recorded in the
   fixture must match the change actually made.
2. **What caused it** — a dependency bump, a generator change, a configuration
   edit, or a schema change?
3. **Which benchmark contracts are affected?** Published checksums, expected
   findings, control partitions and any cached ingestion fixtures derived from
   them all become stale.
4. **Does a schema or generator version need bumping?** A change to the *shape*
   of an artefact must raise `schema_version`; a change to its *content* must
   raise the generator version.
5. **Was it regenerated in the canonical environment?** Check the recorded
   `environment_fingerprint` and `direct_dependencies`.
6. **Is the digest change isolated?** Prefer a dedicated commit so the checksum
   diff is reviewable on its own.

A dependency or lockfile change that moves generated output is never accepted
without an explanation of its determinism impact.

### Why the canonical golden output changed

The observed-state digests were updated once, for the rule and remediation
contract (observed `schema_version` 2 → 3, generator `1.1.0` → `1.2.0`). The
change was verified by generating the canonical scenario from both the previous
`main` and the new code and diffing them field by field. Recording the evidence
here so a future reviewer need not re-derive it:

**Unchanged — no selection, control or truth drift.** The truth graph and the
whole file estate are byte-identical. So are `controls.jsonl` and
`rule-scope.jsonl`: the control partition and every rule's scope are untouched.
`observed-graph.json` differs *only* in its `generator_version` and
`schema_version` fields — the mutated graph payload itself is identical. Record
counts, record ids and record order are identical in all four ledgers (177
defects, 177 findings, 177 remediations, 215 mutations), so no rule selected a
different population.

**Changed — attributable to the contract, one item at a time.**

| Artefact | Difference |
|---|---|
| `injected-defects.jsonl` | new `remediation_availability`, `approval_policy`, `approver_role` fields; no existing field changed |
| `expected-findings.jsonl` | new `remediation_available`, `non_remediable_reason` fields; `match_fields` gains the same two keys so an evaluator can match on them |
| `expected-remediations.jsonl` | new `availability`, `approval_policy`, `approver_role`, `approval_evidence`, `non_remediable_reason`, `action_class` fields; 12 records became `no-remediation` (8 `FILE-MISSING`, 4 `MOD-MIXED-GENE-IDS`) with a null `recommended_value`; 23 `auto_fixable` and 45 `requires_human_approval` values were reclassified |
| `mutation-log.jsonl` | no new fields; the same 23 `auto_fixable` and 49 `requires_human_approval` reclassifications |
| `profile-summary.json` | new `by_contract_state`, `by_action_class`, `by_mutation_op`, `contract_state_coverage` and `uncovered_contract_states` blocks |

The reclassifications are the point of the change, not a side effect: previously
the two dimensions were perfectly coupled, leaving two of the four quadrants
unreachable. Five rules moved to `automatic/required` (the fix is derivable but
alters access, retention or training posture — `GOV-CLASS-MISSING`,
`GOV-RESTRICTED-AS-INTERNAL`, `GOV-RETENTION-MISSING`,
`AIR-TRAINING-STATUS-MISMATCH`, `LIN-CROSS-STUDY-EDGE`) and eight to
`manual/not-required` (judgement is needed but no sign-off — including
`META-TITLE-MISSING`, `META-DESC-MISSING`, `SEM-DESC-GENERIC`,
`GOV-STALE-REVIEW`). `FILE-MISSING` and `MOD-MIXED-GENE-IDS` became
non-remediable.

Provenance remains deterministic: no wall-clock values were introduced, and
`provenance.json` differs only in the two version fields it is supposed to
report.

## Reproducing a canonical benchmark

```bash
git clone https://github.com/ronfinn/dataswamp-biosystems
cd dataswamp-biosystems
uv sync --frozen                                     # the canonical environment

uv run --frozen dataswamp generate-truth  --seed 20260717
uv run --frozen dataswamp generate-files  --seed 20260717 --profile tiny
uv run --frozen dataswamp inject-defects  --truth generated/truth/truth-graph.json \
    --seed 20260717 --profile demo
```

Compare `provenance.json` in each output directory against the
`canonical_environment` block of the golden fixture. Matching fingerprints mean
byte-identical output; differing fingerprints mean the truth and observed layers
still match, while the estate payloads may not.

## The CI matrix

| Job | Resolution | Python | Runs |
| --- | --- | --- | --- |
| `canonical` | `uv sync --locked` | 3.12 | Complete suite, full golden contract, `uv lock --check`, ruff, format, mypy |
| `canonical` | `uv sync --locked` | 3.13 | Complete suite, full golden contract, `uv lock --check` |
| `lowest-direct` | `uv sync --resolution lowest-direct` | 3.12 | Portable golden digests, determinism and CLI suites, wheel build and install, CLI smoke |
| `lowest-direct` | `uv sync --resolution lowest-direct` | 3.13 | As above |

Lint, formatting and typing run once, in the canonical 3.12 job — they are
environment-independent, so repeating them adds cost without evidence. The
complete suite is not repeated in the lowest-direct jobs: those exist to prove
the declared bounds install and function, which a curated compatibility suite
demonstrates.

## Known limits

- Byte identity is claimed for Linux and macOS on x86-64 and arm64 as exercised
  by CI and development. Windows is untested.
- The lowest-direct jobs pin only *direct* dependencies; transitive dependencies
  resolve to their newest compatible versions, which is what surfaced the
  anndata/pandas incompatibility above.
- The golden scenario is deliberately small. It is a contract tripwire, not a
  published benchmark release; versioned release bundles are future work.
