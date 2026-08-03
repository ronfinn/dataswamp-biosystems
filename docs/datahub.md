# DataHub adapter

The adapter translates a verified [benchmark bundle](bundles.md) into DataHub
entities and aspects, and emits them as Metadata Change Proposals — the payload
DataHub's own `file` ingestion source reads.

The dependency direction is fixed and one-way, per
[ADR 0002](adr/0002-truth-vs-observed-state.md): the adapter consumes this
project's emitted artefacts, and no core layer imports anything from it. That is
enforced by a test, not merely documented.

- [Why no DataHub SDK dependency](#why-no-datahub-sdk-dependency)
- [Exporting](#exporting)
- [Observed versus truth mode](#observed-versus-truth-mode)
- [Deterministic URNs](#deterministic-urns)
- [The mapping](#the-mapping)
- [What has no representation](#what-has-no-representation)
- [Output format](#output-format)
- [Ingesting into DataHub](#ingesting-into-datahub)
- [Validation](#validation)
- [Limitations](#limitations)

## Why no DataHub SDK dependency

The adapter emits schemas directly rather than depending on `acryl-datahub`.

That is a deliberate choice, not an omission. The SDK's only role here would be
to serialise a few dozen well-documented aspect payloads. Taking it as a
dependency — even an optional one — would pull a large transitive tree into a
package whose entire architectural premise is catalogue independence, and would
make the adapter's tests contingent on that tree resolving. Emitting the payload
directly keeps the core package free of any catalogue dependency, makes the whole
adapter testable with no server, no network and no credentials, and leaves users
free to install whichever DataHub client their instance requires.

The targeted metadata model is recorded in every export manifest as
`datahub_model_version` (currently `>=0.13,<2`). The aspect names and payload
shapes used here are the file-source representation of those aspects, which has
been stable across that range. Drift is caught by committed fixtures rather than
by a version pin: `tests/adapters/fixtures/*.jsonl` pin the complete emitted
payload for a small hand-written source graph, so any mapping change appears as a
reviewable diff. Regenerate them deliberately:

```bash
uv run --frozen python scripts/update_datahub_fixtures.py --confirm \
  --reason "why the mapping changed"
```

## Exporting

```bash
dataswamp export-datahub \
  --bundle dist/dataswamp-benchmark-v0.1.0 \
  --mode observed \
  --output-dir export/datahub
```

The bundle is opened read-only and fully verified first; the emitted payload is
validated *before* anything is written, so a mapping fault never replaces a
previous, sound export. `--output-dir` goes through the shared containment policy
and may not be, contain, or sit inside the bundle it reads.

Exit codes: `0` written, `1` the payload failed validation, `2` the bundle could
not be read or an unsafe/non-empty output directory was given.

No DataHub server, token or network connection is involved at any point.

## Observed versus truth mode

The two modes differ in **what they are allowed to read**, not merely in what
they choose to emit.

### `observed` (the default)

Built from `observed/observed-graph.json` **alone**. The expected findings,
expected remediations, control partition, rule scope, defect instances and
mutation log are never opened — a test asserts that the exporter touches exactly
one file. This is the export you can hand to an agent under test: the defects are
present in the metadata (that is the benchmark), but which entities carry them is
not.

### `truth`

Built from the `truth/` shards — the correct, defect-free state — and, when the
bundle also carries an observed layer, annotated with the expected finding rule
ids per entity. This is a **privileged** export for benchmark administration and
is marked as such three times over:

- every catalogue asset carries the `dataswamp-privileged-truth-export` tag;
- every ground-truth property is prefixed `dataswamp_truth_`;
- `export-manifest.json` sets `"privileged": true`, and the generated recipe says
  so in a comment.

The validator enforces the boundary in both directions: it fails an `observed`
payload containing any `dataswamp_truth_*` property or the privileged tag, and
fails a `truth` payload whose assets are not tagged privileged.

## Deterministic URNs

Identity is the expensive thing to get wrong: if a URN moves, re-ingesting the
same benchmark produces a second copy of the estate instead of updating the
first. So every URN is a pure function of a **stable DataSwamp id** — never of a
title, description, owner or any other field a defect could plausibly mutate.
Two exports of the same entity produce the same URN in any process, on any
machine, in any order.

| DataSwamp entity | DataHub URN |
| --- | --- |
| dataset `ds-x` | `urn:li:dataset:(urn:li:dataPlatform:dataswamp,dataswamp_biosystems.ds-x,PROD)` |
| physical file `file-x` | the same shape, with `subTypes: ["File"]` |
| data product `dp-x` | `urn:li:dataProduct:dataswamp.dp-x` |
| team `team-x` | `urn:li:corpGroup:team-x` |
| vocabulary `v` | `urn:li:glossaryNode:dataswamp.v` |
| term `t` in `v` | `urn:li:glossaryTerm:dataswamp.v.t` |
| programme `prog-x` | `urn:li:domain:dataswamp.prog-x` |
| facet `f` | `urn:li:tag:f` |
| study `study-x` | `urn:li:container:<32 hex>` |
| quality check `qc-x` | `urn:li:assertion:<32 hex>` |

**Transparent URNs** embed the id directly, and `urns.dataset_id_from_urn()`
recovers it exactly.

**Key-hashed URNs** are used where DataHub itself models identity as a GUID over
a key aspect (containers, assertions). The GUID is
`sha256("dataswamp:<family>:<id>")[:32]` — deterministic and namespaced by entity
family so two families sharing an id cannot collide, but not invertible. Every
such entity therefore carries its DataSwamp id in `customProperties.dataswamp_id`:
traceability, without pretending a hash is reversible.

**Escaping.** Ids in this project are lowercase kebab-case slugs, already safe in
every URN position. `encode_id` nevertheless escapes anything outside
`[a-z0-9-]` as `~` plus two hex digits per UTF-8 byte (escaping `~` itself), so a
defect that corrupts an id cannot inject a comma or a parenthesis into a URN.
The encoding is injective and `decode_id` inverts it exactly.

Collision resistance, cross-process stability and delimiter safety are all
covered by tests.

## The mapping

| Aspect | Emitted for | Carries |
| --- | --- | --- |
| `datasetProperties` | datasets, files | name, qualified name, description, and `dataswamp_*` custom properties (id, entity type, programme, study, modality, version, lifecycle, classification, retention, training status, intended uses, quality status, sizes, contract id/version/schema ref/SLA) |
| `subTypes` | datasets, files, containers | `Dataset`, `File`, `Study` |
| `status` | datasets, files | `removed: false` |
| `ownership` | assets, data products | owner → `DATAOWNER`, stewards → `DATA_STEWARD`, kept as distinct types because that distinction is what the governance benchmark tests |
| `globalTags` | assets, data products | coarse facets (`dataswamp-synthetic`, modality group, quality status, reference flag) |
| `glossaryTerms` | assets, data products | every controlled-vocabulary value: scientific domain, modality, lifecycle stage, access classification, retention class, model-training status, intended uses |
| `domains` | assets, data products, containers | the owning programme |
| `container` | datasets, files | the owning study |
| `upstreamLineage` | datasets | files → dataset as `COPY`; dataset → dataset as `TRANSFORMED`, from the truth lineage edges |
| `dataProductProperties` | data products | description, custom properties, and the component datasets as `assets` |
| `corpGroupInfo` | teams | display name and description |
| `glossaryNodeInfo`, `glossaryTermInfo` | vocabularies and terms | terms are parented to their vocabulary node |
| `domainProperties`, `containerProperties` | programmes, studies | name, description, `dataswamp_id` |
| `tagProperties` | tags | name and description |
| `assertionInfo`, `assertionRunEvent` | quality checks | the check as a dataset assertion, with the pass/fail result and evidence |

Audit stamps that DataHub's model requires but the benchmark has no meaning for
are fixed at `{"time": 0, "actor": "urn:li:corpuser:dataswamp"}` — mandatory in
the schema, and a wall clock there would destroy determinism. The one timestamp
that *is* meaningful, an assertion's run time, is derived from the quality
check's own `evaluated_at`.

Observed-mode records are rendered faithfully, nulls and all: a missing owner or
an empty description is exported as a missing owner or an empty description,
because showing a catalogue what it would really have seen is the entire point.

## What has no representation

Documented rather than distorted:

- **Subjects, biospecimens, assays, instrument runs and pipeline runs** have no
  catalogue analogue in DataHub's model. Runs could be forced into `dataJob`, but
  a sequencing run is not a scheduled job and modelling it as one would misinform
  every downstream consumer. They are not emitted; the truth layer in the bundle
  remains the place to read them.
- **Field-level schema.** The truth graph carries no column-level schema for its
  assets, so no `schemaMetadata` is invented for them. Emitting fabricated fields
  would be worse than emitting none. Consumers who want real schema can read the
  estate's Parquet and H5AD files directly, via `BundleReader.parquet_schema()`.
- **Defect identity.** Nothing in DataHub represents "this asset carries injected
  defect X of rule Y", and nothing should in an observed export — that is the
  answer key. It appears only in truth mode, as `dataswamp_truth_*` properties.
- **Expected remediations and the control partition** have no catalogue analogue
  and are deliberately not mapped in either mode. Read them from the bundle.
- **Data-quality assertions are one-shot.** Each quality check emits one
  `assertionRunEvent` at its recorded evaluation time, not a time series.

## Output format

```text
export/datahub/
├── mcps.jsonl            # one proposal per line, canonical JSON — the machine-readable form
├── mcps.json             # the same proposals as an array — what DataHub's file source reads
├── export-manifest.json  # mode, privilege, counts by entity type and aspect, source bundle, per-file digests
├── datahub-recipe.yml    # a ready-to-run ingestion recipe
└── provenance.json       # the same environment provenance every generated directory carries
```

Both payload forms are byte-identical for identical input and carry exactly the
same proposals (asserted by a test). Each proposal has the shape:

```json
{
  "entityType": "dataset",
  "entityUrn": "urn:li:dataset:(urn:li:dataPlatform:dataswamp,dataswamp_biosystems.ds-x,PROD)",
  "changeType": "UPSERT",
  "aspectName": "datasetProperties",
  "aspect": {"json": {"...": "..."}}
}
```

Every change type is `UPSERT`, which is what makes ingestion **idempotent**:
ingesting the same export twice yields one estate, because each `(URN, aspect)`
pair appears exactly once and addresses the same entity every time.

## Ingesting into DataHub

The generated `datahub-recipe.yml`:

```yaml
source:
  type: file
  config:
    path: ./mcps.json

sink:
  type: datahub-rest
  config:
    server: "${DATAHUB_GMS_URL}"
    token: "${DATAHUB_GMS_TOKEN}"
```

```bash
pip install 'acryl-datahub[datahub-rest]'      # your choice, not this package's dependency
cd export/datahub

datahub ingest -c datahub-recipe.yml --dry-run   # no server needed
export DATAHUB_GMS_URL=https://datahub.example.com/api/gms
export DATAHUB_GMS_TOKEN=...                     # from your environment; never committed
datahub ingest -c datahub-recipe.yml
```

Credentials are referenced only through environment variables. The recipe
contains none, and a test asserts that no credential line is ever a literal.

## Validation

`validate_export()` checks the payload itself, so the adapter is provable
offline:

- every proposal is structurally complete and wraps its aspect in a `json`
  envelope;
- every URN matches the documented pattern for its entity type — a URN built from
  something other than a stable id, or with an unescaped character in it, fails;
- no `(URN, aspect)` pair is emitted twice, and no URN is emitted under two
  entity types;
- required aspects are present per entity type, and catalogue assets additionally
  carry ownership, tags and glossary terms;
- every referenced URN — owner, tag, term, domain, container, parent node,
  lineage upstream, data-product asset, assertion subject — is itself emitted, so
  ingestion creates no dangling stubs;
- an `observed` payload contains no truth-only property and no privileged tag;
- a `truth` payload's assets are all tagged privileged.

Repeat exports are asserted byte-identical, and the committed fixtures pin the
whole payload against mapping drift.

## Limitations

- **Emitter only.** There is no live-instance ingestion, no authenticated remote
  push and no round-trip read-back from a server in this milestone; the recipe
  hands that step to DataHub's own tooling, where it belongs.
- **No SDK model validation.** Payloads are validated against this adapter's own
  documented contract and committed fixtures, not against DataHub's PDL schemas.
  A DataHub release that changes an aspect's shape would be caught at ingestion,
  not here.
- **One fabric.** A synthetic benchmark has a single environment; everything is
  emitted under `PROD`.
- **Container GUIDs are ours, not DataHub's.** They are deterministic and
  namespaced, but they are not computed by DataHub's own GUID algorithm, so a
  study container created by this adapter will not merge with one created by
  another source for the same study.
- **The estate's materialized files are not ingested** — only the truth graph's
  file records are. Pointing a catalogue at real bytes is a separate concern.
