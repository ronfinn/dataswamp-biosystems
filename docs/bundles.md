# Benchmark bundles

A **bundle** is the portable form of a benchmark run: one directory carrying the
layers that were generated, a versioned manifest describing them, SHA-256
checksums for every file, the environment provenance that produced them, and the
licensing and schema notices a third party needs. It can be published, cited,
verified and consumed without any knowledge of this repository's internals.

Everything else in this project generates output into a working directory that
only makes sense next to the source tree. The bundle is what you hand to someone
else.

- [Building a bundle](#building-a-bundle)
- [Bundle structure](#bundle-structure)
- [Manifest schema](#manifest-schema)
- [Checksums and integrity](#checksums-and-integrity)
- [Provenance](#provenance)
- [Verifying a bundle](#verifying-a-bundle)
- [The reader API](#the-reader-api)
- [Determinism](#determinism)
- [Licensing](#licensing)
- [Compatibility and versioning](#compatibility-and-versioning)
- [Limitations](#limitations)
- [End-to-end tutorial](#end-to-end-tutorial)

## Building a bundle

```bash
dataswamp build-bundle \
  --truth-dir generated/truth \
  --estate-dir generated/estate \
  --observed-dir generated/observed \
  --evaluation-dir generated/evaluation \
  --output-dir dist/dataswamp-benchmark-v0.1.0 \
  --release v0.1.0
```

With no `--layer` option, every layer whose directory exists is included, so the
command above works equally well before the estate or the observed state has
been generated. To be explicit, name the layers:

```bash
dataswamp build-bundle --layer truth --layer observed \
  --output-dir dist/truth-and-ground-truth
```

Four shapes are all first-class:

| Bundle | Contains | Use |
| --- | --- | --- |
| truth only | `truth/` | the correct state, for lineage or catalogue testing |
| truth + estate | `truth/`, `estate/` | plus readable scientific files |
| plus observed | `+ observed/` | a scorable benchmark with labelled ground truth |
| complete | `+ evaluation/` | the above plus one worked scoring example |

A layer may only be included alongside the layers it was derived from: the
estate and the observed state each require `truth`, and `evaluation` requires
`observed` as well. A bundle can therefore never claim scored results without the
ground truth those results were scored against — and building refuses outright if
the evaluation report quotes a `ground_truth_fingerprint` other than the bundled
observed layer's, so a score can never be published beside a benchmark it is not
about.

An **evaluation layer is optional**. A benchmark nobody has scored yet is a
normal bundle, not an incomplete one.

The builder is a *packager*, not a generator. It copies bytes the layer writers
already produced and never regenerates, rewrites or reinterprets them, so
bundling introduces no drift of its own. `--output-dir` is replaced wholesale and
goes through the shared containment policy in
[`paths.py`](../src/dataswamp_biosystems/paths.py): it may not be, contain, or sit
inside the configuration directory or any layer directory being bundled.
`--force` overrides only the non-empty check, never path safety.

### Embedding an adapter export

An already-emitted catalogue export can be embedded at build time:

```bash
dataswamp export-datahub --bundle dist/bundle --output-dir export/datahub
dataswamp build-bundle --datahub-export export/datahub --output-dir dist/bundle-with-export
```

It lands under `adapters/datahub/`, is declared in the manifest like every other
file, and gets its own fingerprint in the manifest's `adapters` block. The bundle
layer itself names no specific adapter — it stores whatever directory it is
handed under `adapters/<name>/` and copies the summary fields out of that
adapter's own `export-manifest.json`.

## Bundle structure

```text
dataswamp-benchmark-v0.1.0/
├── benchmark-manifest.json     # the versioned contract; declares every file below
├── checksums.sha256            # sha256sum-compatible; covers the manifest too
├── provenance.json             # the environment that produced the bundle
├── README.md                   # generated, human-readable orientation
├── LICENSES.md                 # licensing and content-assurance notices
├── schemas/
│   └── schema-versions.json    # each layer's schema and generator version
├── truth/                      # verbatim copy of the truth-graph output
├── estate/                     # verbatim copy of the file estate
├── observed/                   # verbatim copy of the observed state + ground truth
│                               #   (adversarial runs also carry scenarios.jsonl
│                               #    and scenario-transformations.jsonl)
├── evaluation/                 # verbatim copy of one evaluation report (optional)
└── adapters/
    └── datahub/                # an embedded catalogue export (optional)
```

Layer directories are byte-for-byte copies of what the corresponding writer
emitted, including each layer's own `provenance.json`. The schemas of those
layers are documented in [truth-graph-schema.md](truth-graph-schema.md),
[file-generation.md](file-generation.md), [observed-state.md](observed-state.md)
and [evaluation.md](evaluation.md); the bundle does not restate them.

## Manifest schema

`benchmark-manifest.json` is the only file a consumer must understand.

| Field | Meaning |
| --- | --- |
| `bundle_schema_version` | the manifest/layout contract version (currently `1`) |
| `bundle_builder_version` | bumped when the builder changes emitted bytes for unchanged input |
| `benchmark_release` | the release name given at build time |
| `dataswamp_version` | the package version that built the bundle |
| `layers` | the included layers, in dependency order |
| `schemas` | per layer: `schema_version` and `generator_version`, read from that layer's provenance |
| `scenario` | per layer: the seeds and profile, verbatim from that layer's provenance |
| `source_fingerprints` | per layer: SHA-256 over that layer's own file tree |
| `environment_fingerprint` | the direct-dependency fingerprint shared by every layer |
| `ground_truth_fingerprint` | the value the evaluator quotes, so a score ties to this bundle |
| `counts` | entities, assets, files, findings, controls, rules fired, evaluated pairs |
| `checksum_algorithm`, `checksums_file` | `sha256` and `checksums.sha256` |
| `files` | every bundled file: path, SHA-256, size, owning section |
| `bundle_fingerprint` | SHA-256 over every declared `path:sha256` pair — quote this to cite a bundle |
| `compatibility` | supported schema versions, minimum package version, Python requirement, reader entry point, which layers are byte-portable |
| `adapters` | per embedded adapter: path, mode, privilege, version, counts, fingerprint |
| `licensing` | software licence, generated-data position, notices file, `contains_real_data: false` |
| `synthetic` | always `true` |

Nothing in the manifest carries a wall-clock value, which is what makes
`bundle_fingerprint` a stable citation rather than a build receipt.

Building refuses outright if the layers disagree on `environment_fingerprint`:
a bundle mixing layers generated in different environments would carry a
provenance claim no single environment supports.

## Checksums and integrity

Two records cover each other:

- **`benchmark-manifest.json`** declares every content file. It cannot declare
  itself — a digest of a document containing that digest is circular.
- **`checksums.sha256`** records every content file *and the manifest*, in the
  standard `sha256sum` format, path-sorted.

So altering the manifest is caught by the checksum record, and altering any
content file is caught by both. `checksums.sha256` is covered in turn by being
exactly **recomputable** from the manifest, which `verify-bundle` does
byte-for-byte — a stronger check than a stored digest would have been.

Without installing anything:

```bash
cd dist/dataswamp-benchmark-v0.1.0
sha256sum --check checksums.sha256      # or: shasum -a 256 -c checksums.sha256
```

The estate's own `file-manifest.jsonl` additionally carries a checksum per
materialized scientific file, so payload bytes are pinned twice over.

## Provenance

Every bundle carries the same
[`provenance.json`](reproducibility.md) object every generated directory carries:
the DataSwamp version, the Python and platform identity, the resolved direct
dependency versions, their fingerprint, and the scenario. The bundle's own
provenance records `layer: "bundle"` and folds in each included layer's scenario.

Verification checks that the bundle provenance, every layer provenance and the
manifest agree on the environment fingerprint, that each layer's provenance
describes the layer it sits in, and that the schema and generator versions the
manifest quotes are the ones the layer actually recorded.

## Verifying a bundle

```bash
dataswamp verify-bundle dist/dataswamp-benchmark-v0.1.0
```

Every invariant is checked and every failure reported — one run tells you
everything wrong with a bundle rather than the first thing — and each issue names
the file and the invariant:

```text
Bundle is invalid — 2 issue(s):
  - observed/expected-findings.jsonl [checksum-mismatch] sha256: expected 9f3a…, got 41bc…
  - truth/assets.jsonl [missing-file] declared but absent
```

The checks:

1. the manifest parses and its schema version is supported (an unsupported
   version is refused, never guessed at);
2. every declared path is a safe relative path — absolute paths, `..` and `.`
   segments, doubled separators, Windows separators and embedded NULs are
   rejected rather than normalised;
3. no path in the bundle is a symlink;
4. the declared file set matches disk, extras included (`--no-strict` relaxes
   only this, and never relaxes a declared file's checks);
5. every declared file's size and SHA-256 match;
6. `bundle_fingerprint` is the value the declared digests imply;
7. `checksums.sha256` is byte-identical to what the manifest implies;
8. declared layers are structurally complete and satisfy their prerequisites;
9. provenance agrees with the manifest, layer by layer;
10. `ground_truth_fingerprint` recomputes from the bundled observed layer, and a
    bundled evaluation report was scored against that same ground truth;
11. an embedded adapter export is complete and matches its recorded fingerprint.

Exit codes: `0` valid, `1` one or more invariants failed, `2` the manifest is
missing or unreadable. Verification writes nothing and never modifies the bundle.

## The reader API

```python
from dataswamp_biosystems.bundle import BundleReader, Layer

with BundleReader.open("dist/dataswamp-benchmark-v0.1.0") as bundle:
    print(bundle.manifest.benchmark_release, bundle.manifest.counts)

    for asset in bundle.iter_assets():             # truth catalogue assets
        ...
    for record in bundle.iter_files():             # FileManifestRecord
        ...
    for finding in bundle.iter_findings():         # ExpectedFinding
        ...
    for fix in bundle.iter_remediations():         # ExpectedRemediation
        ...
    for control in bundle.iter_controls():         # ControlRecord
        ...

    scopes = bundle.rule_scope()                   # RuleScopeRecord per rule
    graph = bundle.observed_graph()                # the defect-bearing view
    summary = bundle.evaluation_summary()          # None when the layer is absent

    dataset = bundle.resolve("ds-nsclc-01-bulk-rna-seq-0001")
    schema = bundle.parquet_schema("files/.../counts.parquet")
```

Properties worth relying on:

- **Verification is on by default.** `BundleReader.open` verifies before it
  returns; `verify=False` exists only for inspecting a bundle you already know
  to be broken.
- **Nothing is loaded eagerly.** Every `iter_*` method is a generator reading one
  JSONL line at a time, so a bundle far larger than memory can be walked. The
  exceptions are genuine single-document JSON files — the manifests, the observed
  graph and the evaluation summary — which are objects, not streams.
- **`resolve()` seeks.** The stable-id index is built once on first use and holds
  only `id → (file, byte offset)`; records are read back by seeking. Resolving ids
  never loads the bundle into memory.
- **Reading validates.** Records parse into the same typed models the emitting
  layer used, so a malformed bundle fails at the record that is wrong, naming its
  line number. The models are imported, never redefined — a reader carrying its
  own copy of the schema would drift.
- **Missing optional sections return `None`**; a missing *required* layer raises
  with a message naming the layer.
- **Paths are checked.** `path()` and `open_estate_file()` refuse anything that
  escapes the bundle, so a manifest record — a value the observed layer is allowed
  to corrupt — cannot be used to read outside it.
- **Parquet is read through the existing stack** (`pyarrow`), footer only.

## Determinism

Identical canonical inputs produce a byte-identical bundle. The manifest,
checksum record, README, licences and schema index are all canonical output with
no wall-clock value; layer content is copied verbatim; every list is sorted; and
nothing depends on dict or set iteration order (asserted under two different
`PYTHONHASHSEED` values). Editor and operating-system droppings (`.DS_Store`,
dotfiles) are never copied, so a bundle fingerprint cannot depend on whose
machine built it.

**A bundle is a directory, not an archive.** That is deliberate: a directory of
canonical bytes is byte-reproducible without also pinning tar or zip header
semantics — member order, mtimes, permission bits, compression level, path
separators — every one of which is a determinism hazard buying nothing a
consumer of this benchmark needs. Anyone who wants an archive can make one from a
verified directory with tooling they already trust.

The determinism *scope* is inherited from the layers, and the manifest says so
in `compatibility`: the truth and observed layers are byte-identical across the
whole supported dependency range, while the estate's binary payloads are
byte-identical only within one environment fingerprint. See
[reproducibility.md](reproducibility.md).

## Licensing

`LICENSES.md` in every bundle records:

- the **software licence** — MIT, referenced (not restated) from the source
  repository's `LICENSE`;
- the **generated-data licence** — *not separately defined at this release*. The
  project has not adopted a distinct data licence and the bundle does not create
  one; the file says so plainly and points at the MIT terms in the meantime;
- a **content assurance** that every person, institution, study, subject,
  specimen, dataset and identifier is fictional and synthetic, that no real
  patient, personal, biological, confidential or proprietary data is included,
  and that email domains use the reserved `dataswamp.example` domain;
- **third-party format notices** — the files are original synthetic output; the
  format specifications belong to their authors and no specification text is
  reproduced;
- the schema and compatibility versions.

## Compatibility and versioning

Three versions move independently:

| Version | Bumped when |
| --- | --- |
| `bundle_schema_version` | the manifest or layout changes incompatibly |
| `bundle_builder_version` | the builder emits different bytes for unchanged input |
| `benchmark_release` | you decide to publish a new release |

A reader that does not support a bundle's `bundle_schema_version` **fails**
rather than guessing; `SUPPORTED_BUNDLE_SCHEMA_VERSIONS` records what this build
can read, and the same list is copied into the bundle's `schemas/` index. The
same rule applies one level down: each layer records the schema version its
writer emitted, and a consumer must refuse an unsupported one.

## Limitations

- Directory bundles only — no `.tar.gz` or `.zip` (see [Determinism](#determinism)).
- `checksums.sha256` is not itself digested anywhere; it is verified by exact
  recomputation from the manifest. Quote `bundle_fingerprint` out of band if you
  need a single value to compare.
- The bundle asserts *integrity*, not *authenticity*. There is no signing. A
  consumer who needs provenance against a hostile publisher should sign the
  manifest with tooling they trust.
- Bundles are not incremental or delta-encoded; each is a complete copy.
- Cloud hosting and a published release feed are out of scope here.

## End-to-end tutorial

Starting from a clean checkout:

```bash
# 1. generate the correct state
uv run dataswamp generate-truth --seed 20260717

# 2. materialize readable scientific files for it
uv run dataswamp generate-files --seed 20260717 --profile tiny

# 3. derive the deliberately-imperfect observed state and its ground truth
uv run dataswamp inject-defects --truth generated/truth --seed 20260717 --profile demo

# 4. score a submission (any JSONL prediction file; see docs/evaluation.md)
uv run dataswamp evaluate \
  --observed-dir generated/observed \
  --predictions predictions.jsonl

# 5. package it all
uv run dataswamp build-bundle \
  --output-dir dist/dataswamp-benchmark-v0.1.0 \
  --release v0.1.0

# 6. verify what you are about to publish
uv run dataswamp verify-bundle dist/dataswamp-benchmark-v0.1.0

# 7. translate it for a catalogue
uv run dataswamp export-datahub \
  --bundle dist/dataswamp-benchmark-v0.1.0 \
  --mode observed \
  --output-dir export/datahub
```

Step 7 is covered in [datahub.md](datahub.md). Steps 1–6 need no network access
and no credentials of any kind.
