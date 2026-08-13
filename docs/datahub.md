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
- [Live ingestion](#live-ingestion)
- [Round-trip validation](#round-trip-validation)
- [What normalization forgives, and why](#what-normalization-forgives-and-why)
- [Containment scope](#containment-scope)
- [The leak probes](#the-leak-probes)
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
`datahub_model_version` (currently `>=0.13,<2`). This is a **declared target for
the emitted payload shape, not a tested range** — exactly one release inside it
has ever been run against, and the rules for moving it are in the
[`DATAHUB_MODEL_VERSION` policy](#datahub_model_version-policy). Drift is caught
by committed fixtures rather than by a version pin: `tests/adapters/fixtures/*.jsonl` pin the complete emitted
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

The table above is a reader's summary. The **authoritative, machine-readable
statement of how faithfully each DataSwamp semantic family survives is
`mapping-coverage.json`**, described below; when the two disagree, the emitted
file is right and this table is stale.

## Mapping coverage

Every export carries `mapping-coverage.json`: a first-class artefact declaring
all **24** DataSwamp semantic families — including the ones this adapter emits
nothing for — with, for each, a target, a semantic classification, an
operational state, a mandatory reason for anything non-exact, and measured
source, emitted and deliberately-dropped counts. It is regenerated with the
export and describes the adapter *as it currently behaves*, never as it ought to.

**Semantic classification** answers *how faithful is this mapping?* —
`exact` (no meaningful compromise), `reasonable` (transformed into a
catalogue-native model; the source concept stays recoverable), `lossy` (material
information does not survive into native DataHub fields), `unsupported` (no
honest target representation exists **in this adapter**). The current contract is
**4 exact, 9 reasonable, 4 lossy, 7 unsupported**.

**Operational state** answers *where does it show up?* —
`materialized_in_entity_export`, `deferred_live_write`,
`deliberately_not_mapped`. The two axes are independent, and fidelity is never a
function of operational timing. DataHub declares `deferred_live_write` but uses
it for nothing, and that zero is itself a finding: the file-source MCP model has
no server-assigned-UUID problem, so lineage and data-product assets are
materialized inline where the OpenMetadata adapter must defer.

`unsupported` is **not a defect and not a DataHub limitation** — it records that
this adapter has no honest home for a family, so an omission is counted rather
than silently absent. Reporting `0 / 0 / 0` for subjects or biospecimens would
claim nothing existed; the contract instead reports the real source count with
zero emitted, which is why the exporter reads those shards for measurement while
the mapping continues to ignore them.

Counts use each family's natural semantic grain: entity occurrences for entity
families, individual reference occurrences for ownership, stewardship and
data-product components, edge occurrences for lineage, and one containment
relationship per physical file. `source == emitted + dropped` holds for every
row, and `build_coverage` refuses a report that misses a family, counts an
undeclared one, fails to reconcile, or claims emitted records for an
`unsupported` family. Nothing is silently repaired.

The report carries **counts only, never an entity identifier** — per-entity
coverage would let a reader infer which entities were mutated by differencing two
exports.

The OpenMetadata adapter declares the same 24 families with its own, deliberately
different classifications; a test proves the two vocabularies match without
either adapter importing the other. Future cross-catalogue tooling *may* consume
these contracts. No such comparator exists.

## What has no representation

Documented rather than distorted. The semantic families below are declared
`unsupported` and counted in `mapping-coverage.json`; the answer-key artefacts
are not DataSwamp semantic families at all and appear in no contract:

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
├── mapping-coverage.json # how each of the 24 semantic families maps, how faithfully, and what is dropped
├── datahub-recipe.yml    # a ready-to-run ingestion recipe
└── provenance.json       # the same environment provenance every generated directory carries
```

Because `ingest-datahub` digest-verifies **every** file the manifest declares
before a byte leaves the process, `mapping-coverage.json` is a required,
tamper-checked companion of the export: an export with it deleted or edited is
invalid. Nothing in it is transmitted to a catalogue — it is an adapter contract
artefact, not a Metadata Change Proposal.

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

## Live ingestion

The live path sits strictly downstream of the emitted export:

```text
bundle → export-datahub → emitted export → ingest-datahub → verify-ingestion
```

`ingest-datahub` consumes an **emitted export directory**, never a bundle. It
does not regenerate metadata, reopen a generator, reinterpret a bundle or
consult the benchmark answer key. That matters for more than tidiness: if
ingestion could re-derive the payload, "the catalogue matches what we sent"
would be comparing a computation against itself.

```bash
export DATAHUB_GMS_URL=https://datahub.example.com/api/gms
export DATAHUB_GMS_TOKEN=...          # only if your instance needs one

dataswamp ingest-datahub --export-dir export/datahub --dry-run
dataswamp ingest-datahub --export-dir export/datahub --yes
```

### What "does not reinterpret" means, precisely

> Live ingestion does not remap, synthesize, enrich or reinterpret emitted
> metadata. Entity identity, entity type, aspect identity and semantic aspect
> content are preserved. `client.py` alone encodes the emitted content into the
> wire representation required by the DataHub API.

This replaces an earlier, stronger claim that ingestion transmitted the export
*verbatim*. That claim was wrong, and the live canary is how we found out: the
DataHub write API does not accept the emitted interchange shape as-is, so a
transport that changed nothing at all could not have worked against a real
server. See [the dialect mismatch](#the-restli-openapi-dialect-mismatch).

The distinction is between the interchange artefact and the wire format.
`mcps.jsonl` and `mcps.json` remain the deterministic emitted artefacts and are
never rewritten — the export on disk is byte-identical to what it always was,
and its fixtures and digests are unchanged. `encode_batch()` in `client.py`
translates the envelope at the moment of transmission and nothing else:

```text
{"entityType": "dataset", "entityUrn": U, "aspectName": A, "aspect": {"json": P}}
  →  {"dataset": [{"urn": U, "A": {"value": P}}]}
```

`P` is the same object, not a normalized or re-keyed copy. Proposals for one URN
merge into one entity object because the request body is keyed by entity;
merging is safe because the export guarantees `(entityUrn, aspectName)` is
unique, and the encoder re-checks that rather than trusting it. `changeType` is
the only emitted key with no wire representation — the endpoint *is* the change
type — so a non-`UPSERT` proposal is refused rather than posted as an upsert.

Semantic preservation is tested rather than asserted: the fake GMS reconstructs
each proposal from the bytes it actually received, and the reconstruction must
match the emitted record field for field.

Four things are checked before a byte leaves the process: the payload passes the
offline validator, every digest in `export-manifest.json` recomputes, no
`(URN, aspect)` pair appears twice, and the manifest's privilege flag agrees with
its declared mode. A modified export is refused — transmitting metadata that no
longer matches the manifest it was published with would put unattributable
content into somebody's catalogue.

Transmission is **pure transport**: nothing synthesizes, enriches, rewrites or
remaps a proposal. Every proposal is an `UPSERT`, so a second ingestion converges
on one estate rather than producing a second copy, and that idempotence is tested.

**`--dry-run` performs zero network activity.** It reads and verifies the export,
resolves non-secret configuration, builds the transmission batches and reports
them. It opens no socket and makes no health or connectivity check — a dry run
that contacts a server is not a dry run — and a test poisons every socket entry
point to prove it.

**Credentials come from the environment and nowhere else.** `DATAHUB_GMS_URL` and
`DATAHUB_GMS_TOKEN`. The token is never a command-line option (that would leak it
into shell history and process listings), never in a `repr`, never interpolated
into an exception, and never written to a file. Tests assert each of those.

**A truth-mode export is hard to transmit by accident.** It carries the benchmark
answer key, so `--yes` alone is not enough: `--i-understand-this-is-ground-truth`
is required as well, and the command prints a privileged warning either way.

No receipt file is written. It would be redundant — the emitted export *is* the
record of what was transmitted, by the contract above, and `verify-ingestion`
reads it directly rather than trusting a log this command wrote about itself.

Exit codes: `0` transmitted (or planned), `1` the export is valid but
transmission was refused for want of confirmation, `2` the export could not be
read or the catalogue could not be reached.

## Round-trip validation

```bash
dataswamp verify-ingestion \
  --export-dir export/datahub \
  --output-dir generated/roundtrip
```

Four claims are judged and reported **separately**, never collapsed into one
opaque pass/fail — a catalogue that is missing aspects has a different problem
from one that mutated them, and both differ from one holding entities nobody
sent it:

| Claim | What it proves |
| --- | --- |
| **completeness** | every `(URN, aspect)` in the export is retrievable from the catalogue |
| **fidelity** | each retrieved aspect is semantically equal to the emitted one, under the versioned normalization contract, with precise recursive field paths on any difference |
| **containment** | the catalogue holds no DataSwamp aspect or entity the export did not contain, within the scope below |
| **non-leakage** | an `observed` export left no ground-truth marker in the catalogue |

All supported emitted aspects are round-tripped, not a hand-selected subset.
Versioned and timeseries aspects are read through their separate endpoints;
timeseries aspects are compared on their latest value only, because the adapter
emits exactly one run event per quality check and cannot produce a series.

Output:

```text
generated/roundtrip/
├── roundtrip-report.json   the four claims, their counts, and the contracts in force
├── discrepancies.jsonl     one record per disagreement, canonically ordered
├── leak-findings.jsonl     one record per ground-truth marker found — empty on success
└── provenance.json         the usual environment provenance
```

`leak-findings.jsonl` is written even when empty: "the probes ran and found
nothing" and "the probes never ran" are different statements, and a missing file
cannot distinguish them. No wall-clock value appears anywhere, so two identical
round-trips write identical bytes. The recorded endpoint is passed through a
redactor, so a token embedded in a GMS URL never reaches the file.

Exit codes: `0` clean, `1` discrepancies or leak findings were reported, `2` the
export could not be read, the catalogue could not be reached, or an unsafe or
non-empty output directory was given.

### Live compatibility is experimental

The `datahub_model_version` range describes the emitted **payload** shape, which
committed fixtures pin. It says nothing about the REST endpoints the live path
uses, and must not be read as though it did. Every round-trip report therefore
records `live_support` separately, and it names the one release the endpoints
have actually been exercised against rather than a supported range.

## The live integration job

`.github/workflows/live-datahub.yml` stands up a real DataHub Quickstart, runs
the whole live path against it, and asserts zero discrepancies and zero leak
findings. It is what turns "the contract is right" into "the contract is right
*against DataHub `v1.7.0`*".

### The pin

| | |
| --- | --- |
| DataHub release | **`v1.7.0`** (published 2026-08-04) |
| Compose file | `docker/quickstart/docker-compose.quickstart-profile.yml`, fetched at that tag |
| Profile | `quickstart-backend` — GMS, MySQL, Kafka, OpenSearch. No frontend; this path speaks REST. |
| Everything else | Pinned inside that generated compose file (`mysql:8.2`, `confluentinc/cp-kafka:8.2.2`, `opensearchproject/opensearch:2.19.3`) |

Fetching the compose file *at the release tag* is what makes the pin total: the
non-DataHub images carry their own fixed tags inside it, so one version string
pins the entire stack. The resolved image list is written into the job's uploaded
artifact, so a past run's exact stack is recoverable from the run itself.

A named release is the entire point. "Whatever is latest" would make a green run
unfalsifiable — it could not distinguish a contract that still holds from one
that was quietly rewritten to match. Bumping the pin is a deliberate commit with
a diff, and [#29](https://github.com/ronfinn/dataswamp-biosystems/issues/29)
owns the policy for when and how.

### Why it is not a required check

Quickstart is fourteen images and several minutes of startup. As a merge gate it
would be red often enough — upstream image pushes, registry hiccups, runner
memory — to train reviewers to click past it, and a check everyone ignores
detects nothing. As a scheduled canary a red run is informative: DataHub drifted.

It runs weekly, on `workflow_dispatch`, and on a pull request **labelled**
`live-datahub` for when an adapter change deserves a real server before it
merges. It never runs on an unlabelled PR and never runs in a fork.

### What it actually does

```
dataswamp demo                          # bundle + observed export, offline
dataswamp ingest-datahub --dry-run      # verify the export; opens no socket
docker compose up -d --wait             # bounded: --wait-timeout 780
curl $DATAHUB_GMS_URL/health            # bounded: 60 × 5s on the *mapped* port
dataswamp ingest-datahub --yes
dataswamp verify-ingestion              # exits 1 on any discrepancy or leak
pytest -m live                          # the same claims, plus a negative control
docker compose down -v                  # if: always()
```

Both waits are bounded and they check different things. `--wait` asks the
containers whether they consider themselves healthy on the compose network, and
fails immediately if a dependency exits non-zero, so a broken upstream image
costs seconds instead of the full timeout. The `curl` loop then proves GMS
answers on the *mapped* port from the runner, which is what the adapter actually
talks to. The job's own timeout is 25 minutes.

"Zero discrepancies and zero leak findings" is `verify-ingestion`'s exit status,
not a grep over its output. The report directory uploads on success **and** on
failure — a red canary is worth much more with its evidence attached — alongside
`docker compose ps`, container logs and the resolved image pins. Teardown is
`if: always()` and takes the volumes with it, so one run's state can never reach
the next.

### Credentials

None, and this is structural rather than a promise. The pinned compose sets
`METADATA_SERVICE_AUTH_ENABLED: 'false'` on GMS, so `DATAHUB_GMS_TOKEN` is never
set. The instance is throwaway and local to the runner. No repository secret and
no third-party catalogue is involved.

Two values *are* generated. The published compose file cannot be run bare: it
interpolates `DATAHUB_TOKEN_SERVICE_SIGNING_KEY` and `DATAHUB_TOKEN_SERVICE_SALT`
into both GMS and `system-update` with no defaults, and `system-update` exits 1
with `authentication.tokenService.signingKey must be set and not be empty` when
they are missing. The `datahub` CLI normally supplies them from a local secrets
file it generates on first run. The job generates random per-run values, masks
them, and destroys the instance holding them — so no value in this repository is
ever a live signing key.

### The live test suite

`tests/adapters/test_live_datahub.py`, marked `live` and deselected by default
(`addopts = ["-m", "not live"]`); it also skips outright when `DATAHUB_GMS_URL`
is unset, so an explicit `-m live` with no server says why rather than erroring.
Point `DATAHUB_GMS_URL` at your own throwaway instance to run it locally.

It re-asserts only the claims whose truth depends on the *server*:
retrievability of every emitted aspect including the timeseries one — which the
fake GMS cannot really test, since it serves both storage paths from one store —
fidelity under normalization, idempotent upsert, extra-entity scanning and
observed non-leakage. Perturbation coverage stays offline, where faults can be
planted precisely.

One test is live-specific and load-bearing. A comparison of nothing against
nothing is also "clean", so a suite of green assertions against an empty
catalogue would look exactly like success. `test_a_withheld_proposal_is_reported
_as_an_extra_aspect` withholds one proposal from the *sent* side of an otherwise
identical comparison and requires the real readback to report that exact aspect
as extra — which it can only do if the server genuinely returned it.

### The rest.li / OpenAPI dialect mismatch

The first live run against a pinned release failed, and it is worth recording
what it caught, because no offline test could have.

Ingestion posted to the rest.li endpoint `/aspects?action=ingestProposalBatch`,
which deserializes an aspect as
[`GenericAspect`](https://github.com/datahub-project/datahub/blob/v1.7.0/metadata-models/src/main/pegasus/com/linkedin/mxe/GenericAspect.pdl)
— `value` as serialized bytes plus `contentType`. The emitted payload writes
aspects in the OpenAPI/JSON dialect, `{"aspect": {"json": {...}}}`. DataHub
v1.7.0 answered:

```
HTTP 500  RequiredFieldNotPresentException: Field "value" is required but it is not present
```

Two DataHub API families, mispaired. The reads beside it were already OpenAPI
v3 and were fine, so the *write* was the odd one out — and the timeseries read
was quietly a third case, still on rest.li `getTimeseriesAspectValues`.

**111 offline tests passed throughout.** They passed because the fake GMS read
`proposal["aspect"]["json"]` out of whatever body arrived, so any envelope the
client chose was self-consistently correct. A fake that cannot disagree with the
client cannot catch the client being wrong. Two things changed as a result:

- **One API family, end to end.** Write, entity read, timeseries read and
  namespace enumeration are all OpenAPI v3. Mixing families is what made the
  mismatch possible, so the fix is not merely a new path.
- **The fake validates the envelope.** It enforces the cross-entity request
  shape and rejects a rest.li `GenericAspect` body the way a real server does.
  `test_client.py` carries that as an explicit regression test.

Every emitted aspect was checked against the v1.7.0 OpenAPI schema before the
change, `assertionRunEvent` included: all 24 emitted `(entityType, aspectName)`
pairs are representable, so no hybrid transport was needed and none exists.

One detail is load-bearing rather than incidental: the write endpoint defaults
to **asynchronous** ingestion, and the adapter pins `async=false`. Reading back
an asynchronously-accepted write is a race, and a round-trip built on one would
report completeness failures that come and go.

## When the canary goes red

Diagnose before touching anything. A live failure is *evidence*, and the cheapest
response to it — adding the offending field to the normalization ignore list — is
the one that destroys the check's value. The architectural rule behind this
section is [ADR 0006](adr/0006-compatibility-points-not-ranges.md): **the verdict
is chosen from evidence before the fix is chosen.**

This is not hypothetical caution. The first two live runs both went red and had
*opposite* correct responses:

| Run | Symptom | Verdict | Correct response |
| --- | --- | --- | --- |
| 1 | `HTTP 500 RequiredFieldNotPresentException: Field "value" is required` | **A — DataSwamp bug** | Fix the transport. Normalization untouched. |
| 2 | 4,398 discrepancies | **B — server-derived metadata** | `NORMALIZATION_VERSION` 1 → 2, with justifications and paired tests. |

Run 1 was a rest.li/OpenAPI dialect mismatch in our own client. **It was not
normalization drift and must never be recorded as such** — no aspect shape
changed, no server behaviour changed, and no emitted byte was wrong. Widening
the ignore list would have papered over a bug in our code. Run 2 changed no
DataSwamp behaviour at all; the server was adding derived metadata it computes
from what we sent.

### The decision tree

Work top to bottom. The first branch whose evidence test passes is the verdict.

```
Did the job fail before `verify-ingestion` produced a report?
├─ yes → is the failure in image pull, container health, timeout, or the runner?
│         ├─ yes → D. Infrastructure / transient
│         └─ no  → A. DataSwamp bug (the CLI itself failed)
└─ no  → inspect discrepancies.jsonl

    Are there MISSING aspects, or a non-2xx from ingestion?
    ├─ yes → A. DataSwamp bug, unless the aspect/endpoint no longer exists
    │         upstream → C. Upstream DataHub change
    └─ no  → for each discrepancy, ask: did DataSwamp send a value here?

        MUTATED with sent ≠ ABSENT  (a value we sent came back different)
          → A if our encoding altered it; otherwise C. NEVER B.
        MUTATED with sent = ABSENT  (a field we never sent appeared)
          → B if the server can derive it from what we sent; else C.
        EXTRA-ASPECT on a URN we sent
          → B if server-derived; else C.
        EXTRA-ENTITY
          → never B. Someone else wrote to our namespace, or our URN
            construction changed → A.
```

### A — DataSwamp bug

**Marker:** the emitted payload, the transport, or the URN construction is wrong.
The server behaved correctly.

Fix it as a bug. **Normalization is not touched, `NORMALIZATION_VERSION` does not
move, and no ignore-list entry is added.** If an offline test passed while the
bug was live, that test is also defective and is fixed in the same change — as
happened in run 1, where the fake GMS accepted any request envelope and now
validates it.

### B — Genuine server-derived or server-owned metadata

**Marker:** the server produced something DataSwamp never sent, and it can be
*derived from what DataSwamp did send*.

This is the only branch that may widen normalization, and it requires **all six**:

1. **Evidence from a real compatibility run.** A green-except-this-difference
   run against a pinned release, with the report artifact retained. A difference
   observed only against the fake GMS is not evidence of server behaviour.
2. **A justification of derivability or server ownership.** Name the fields the
   server computed it from, or why it is server-owned provenance. "The server
   happened to add it" is *not* sufficient — that is indistinguishable from a
   third party writing to our URNs, which is what containment exists to detect.
3. **A focused forgiveness test** proving the difference is normalized away.
4. **A paired test** proving an adjacent, non-declared change is *still* caught —
   and for a `SERVER_ADDED_FIELD`, specifically that a mutation to a value
   DataSwamp *did* send remains visible.
5. **A `NORMALIZATION_VERSION` bump.** Every rule change moves it, so a stored
   report stays interpretable.
6. **A documentation and `CHANGELOG.md` entry**, with the rule table updated.

The bar is deliberately higher than the fix. See
[what normalization forgives](#what-normalization-forgives-and-why).

### C — Upstream DataHub API or aspect-model change

**Marker:** DataHub changed an endpoint, an aspect's shape, or a field's
semantics. Our payload and transport were correct against the previous release.

| What changed | What moves |
| --- | --- |
| An endpoint path, verb or envelope | `client.py` only — the isolation rule exists for exactly this, so a moved endpoint changes one file |
| An aspect's *emitted* shape | `mapping.py`, then regenerate fixtures deliberately with `scripts/update_datahub_fixtures.py --confirm --reason ...` |
| The aspect model such that the old shape is no longer accepted | `DATAHUB_MODEL_VERSION`, but only per the rules below |

**Committed fixtures move only when the emitted payload must change** — never to
make a live run green. A fixture regeneration is a reviewable diff of the
project's own output; if that diff is not explainable by the upstream change, the
verdict was wrong.

#### `DATAHUB_MODEL_VERSION` policy

The range (currently `>=0.13,<2`) is a **declared target for the emitted payload
shape**. It is not a tested range, and it says nothing whatever about the live
REST endpoints.

- It may be **narrowed** on evidence that a release inside it rejects the payload.
- Its **upper bound may be raised only when a tested compatibility point exists
  above the current bound** — a green live run against that named release. A
  changelog, a schema reading, or "the shape has been stable" is not sufficient.
- **Never claim a version range on assumption.** If compatibility with a release
  is believed but untested, say so in those words, or run the canary against it.
- A `DATAHUB_MODEL_VERSION` move changes what every export manifest asserts, so
  it needs a `CHANGELOG.md` entry naming the evidence.

A test asserts `VERIFIED_DATAHUB_VERSION` lies *inside* the declared range, so
the declared target and the tested point can never become incoherent.

### D — Infrastructure or transient canary failure

**Marker:** image pull failure, registry outage, a container that never became
healthy, the 25-minute timeout, or runner exhaustion. No `roundtrip-report.json`
was produced, or it was produced but the run never reached `verify-ingestion`.

- **This never justifies a normalization change.** Not one entry, not "while
  we're here".
- **Retain the diagnostic artifacts.** The run uploads `compose ps`, container
  logs and the resolved image pins on failure precisely so a transient failure
  can be told apart from a real one after the fact.
- **Re-run before changing any product semantics.** `workflow_dispatch` on the
  same pin is the cheapest disambiguation available; two independent failures on
  the same pin are evidence, one is noise.
- If a specific flake recurs, harden the *job* — a bound, a retry, a health
  check — not the contract it is testing.

### Recording a red weekly run

1. **Open an issue** titled with the pinned version and the date, e.g.
   `live-datahub red: v1.7.0, 2026-08-08`.
2. **Attach the run artifact.** `roundtrip-report.json` and
   `discrepancies.jsonl` are the evidence; the report embeds the normalization
   rules in force, so it stays interpretable later.
3. **State the verdict (A/B/C/D) and the evidence for it** before proposing a
   fix. A triage comment that begins with the fix has skipped the step this
   policy exists to enforce.
4. **Do not disable, skip or unpin the job to go green.** A canary that is
   silenced has been converted into no canary at all. If the pin must move, that
   is a C-branch decision with its own evidence.
5. **Track an accepted upstream difference as a declared rule**, never as a
   suppression: it becomes a `SERVER_DERIVED_ASPECT` or `SERVER_ADDED_FIELD` with
   a justification and paired tests, and it appears in the rule tables here. An
   accepted difference that is not written down is indistinguishable from a
   defect nobody noticed.

### The four compatibility claims, and which is which

Conflating these is the failure this policy exists to prevent — see
[ADR 0006](adr/0006-compatibility-points-not-ranges.md).

| Claim | Means | Backed by | Does **not** mean |
| --- | --- | --- | --- |
| **Emitted-payload compatibility** | `mcps.jsonl` matches DataHub's aspect shapes | Offline validator + committed fixtures | that any server accepted it |
| **`DATAHUB_MODEL_VERSION`** (`>=0.13,<2`) | the model the payload is *written for* — a declared target | fixtures pinning emitted bytes | that every release in the range was tested |
| **Live REST compatibility** | the transport works against a running GMS | the live canary | anything about the emitted payload's portability |
| **`VERIFIED_DATAHUB_VERSION`** (`v1.7.0`) | the one release the live path actually ran against | one green canary run | a range, or any adjacent release |

A **pinned compatibility point** is a named release with a green run behind it. A
**claimed version range** is a statement of intent. The project publishes both
and never lets the second borrow credibility from the first.

## What normalization forgives, and why

This is the highest-risk part of the live path, and the risk is not a bug — it is
**erosion**. When a live round-trip fails, the cheapest possible fix is to add
the offending field to the ignore list and watch the check go green. Do that a
few times and fidelity validation becomes a function that always returns
"identical", which is worse than having no check at all, because it looks like
evidence.

Three rules hold the line.

**The ignore list is narrow, versioned and justified.** Every entry names the
field, states why the *server* rather than DataSwamp owns it, and carries two
tests: one showing the field is normalized away, and a **paired** one showing
that an adjacent field which is not on the list still surfaces as a difference.
`normalization_version` is recorded in every report, so a stored report stays
interpretable — and the report embeds the rules themselves, not merely a number.

The list holds exactly one entry:

| Field | Justification |
| --- | --- |
| `systemMetadata` | Server-owned ingestion provenance (run id, observation time, registry name and version). DataSwamp never sends it — the export fixtures pin that — so its presence in a readback is definitionally the server's own annotation. It also changes on every ingestion by design, so comparing it would make the idempotence claim untestable. |

Version 1 shipped with that entry alone, and deliberately so: it had no evidence
from a real DataHub server, and inventing forgiveness rules for behaviour nobody
has observed is exactly the erosion described above.

### Version 2: what the live canary earned

The first live round-trip against DataHub `v1.7.0` produced 4,398 discrepancies.
Every single one was **the server adding something, not changing something** —
zero of the 861 field-level differences altered a value DataSwamp sent. Version 2
encodes that distinction rather than merely trusting it.

**Server-derived aspects** are exempt from *containment* only. They are never
exempt from fidelity: none is on the sent key set, so none is ever compared as a
value.

| Aspect | Justification |
| --- | --- |
| `<entityType>Key` | The entity's key aspect, a parse of the URN DataSwamp sent. Handled as a **rule**, not a suffix match: `datasetKey` is derived on a dataset, but the same aspect on a tag was not derived from that tag's URN and stays a containment finding. |
| `browsePathsV2` | Navigation path computed from the container and platform we sent; regenerated by the server on ingestion. |
| `aliases` | Alternate identifiers the server maintains, derived from the URN. |
| `dataPlatformInstance` | The platform association extracted from a dataset URN whose platform segment we sent. |

The bar is **derivability**: the server must be able to compute the aspect from
what DataSwamp already sent. "The server happened to add it" is not sufficient,
because that is indistinguishable from a third party writing to our URNs — the
very thing containment exists to detect. The exemption also reaches aspects
only: a derived aspect on an entity we never sent is still an extra *entity*.

**Server-added fields** are forgiven **only where DataSwamp sent no value**:

| Aspect | Field | Justification |
| --- | --- | --- |
| `assertionInfo` | `entityUrn` | A denormalised copy of the asserted entity, already sent inside `datasetAssertion.dataset`. Same URN, second location. |
| `domains` | `domainAssociations` | A richer rendering of the same membership sent in `domains` — one association object per domain URN, same order. |
| `ownership` | `ownerTypes` | An index of the owners we sent, grouped by ownership-type URN. Derived wholly from `owners`, which remains present and is still compared. |

That condition is what separates these from the `systemMetadata` rule. Stripping
a field from both sides would hide a genuine change to a field we *do* send;
conditional forgiveness cannot. If one of these paths ever appears in an emitted
payload and the server returns something different, it is a mutation and is
reported as one — and there is a paired test for each proving exactly that.

**Unknown additions are differences.** A field the server adds that is not on the
list is reported as a mutation, not silently dropped. The default is suspicion;
forgiveness is opt-in and reviewed.

**Order-insensitivity is per-field, not global.** A list is compared as a
multiset only where DataHub's model genuinely has no ordering semantics:

| Aspect | Unordered field | Why |
| --- | --- | --- |
| `ownership` | `owners` | a set of (owner, type) associations; no owner is "first" |
| `globalTags` | `tags` | an asset carries tags, not a tag list |
| `glossaryTerms` | `terms` | likewise a set of term associations |
| `domains` | `domains` | set membership |
| `upstreamLineage` | `upstreams` | lineage is an edge set |
| `dataProductProperties` | `assets` | a product's membership set |

Notably **absent**: `subTypes.typeNames`, where the first element is
conventionally the primary subtype, so a reordering is a real semantic change and
is reported as one.

## Containment scope

A DataSwamp benchmark gets ingested into somebody's DataHub, alongside their real
estate. Reporting one of their datasets as a "DataSwamp extra" would be a false
accusation about their data, so namespace-wide enumeration is permitted **only**
where a URN unambiguously identifies DataSwamp ownership. Where it does not,
coverage is reported as *unavailable* rather than guessed at.

| Entity family | Extra-entity coverage | Why |
| --- | --- | --- |
| `dataset` | **scanned** | the platform *and* the dataset-name namespace are both ours |
| `dataProduct` | **scanned** | namespaced by the DataSwamp platform id |
| `domain` | **scanned** | namespaced by the DataSwamp platform id |
| `glossaryNode` | **scanned** | namespaced by the DataSwamp platform id |
| `glossaryTerm` | **scanned** | namespaced by the DataSwamp platform id |
| `corpGroup` | unavailable | a bare team id with no namespace; a group of the same name in the user's own directory is indistinguishable from ours |
| `tag` | unavailable | a bare tag name with no namespace |
| `container` | unavailable | identity is an opaque GUID, which carries no evidence of who created it |
| `assertion` | unavailable | identity is an opaque GUID, likewise |

Extra **aspects** are detected for every family, because that check is scoped to
URNs the export itself contained and needs no enumeration. Moving a family from
*unavailable* to *scanned* is a claim about URN uniqueness and deserves the same
scrutiny as widening the normalization ignore list.

## The leak probes

For an `observed` export, non-leakage is proven **structurally** rather than by
consulting the answer key:

1. the emitted export already passed `validate_export(..., OBSERVED)`, which
   fails on any truth-only property or the privileged tag;
2. ingestion verifies the export's digests and transmits **exactly** the emitted
   proposal set — a test reconstructs the transmitted bodies and asserts they
   equal `mcps.jsonl`;
3. readback proves semantic equivalence to that transmitted set;
4. server-side probes check universal forbidden markers, drawn from the emitted
   **export contract itself**: any custom property beginning
   `dataswamp_truth_`, and the `dataswamp-privileged-truth-export` tag URN.

The probes never open the bundle, the defect ledgers, the rule scope, the
scenarios, the expected findings or remediations, or the control partition.
Strengthening a probe by consulting the answer key would make the live commands
privileged, and the entire point of an observed export is that verifying it needs
no privilege. An isolation test enforces that boundary against the source.

A detector never observed to fire is not evidence of anything, so a test ingests
a **privileged truth export**, judges it as though it were observed, and asserts
that both probes fire — using only the emitted export contract, not the benchmark
answer key.

## Limitations

- **Live GMS support is verified against exactly one release.** The REST
  endpoints have been exercised against DataHub `v1.7.0` and nothing else. That
  is a compatibility *point*, not a range: no claim is made about older or newer
  releases, and none should be inferred. See
  [the live integration job](#the-live-integration-job),
  [ADR 0005](adr/0005-direct-rest-datahub-client.md) and
  [ADR 0006](adr/0006-compatibility-points-not-ranges.md).
- **The declared model range is broader than the evidence.**
  `DATAHUB_MODEL_VERSION` is `>=0.13,<2`; one release inside it has been tested.
  The gap is deliberate and documented rather than closed — see the
  [`DATAHUB_MODEL_VERSION` policy](#datahub_model_version-policy) — because
  narrowing the declaration to a single version would misrepresent the payload's
  portability in the other direction.
- **No SDK model validation.** Payloads are validated against this adapter's own
  documented contract and committed fixtures, not against DataHub's PDL schemas.
  A DataHub release that changes an aspect's shape would be caught at ingestion,
  not here — which is what the [canary triage
  policy](#when-the-canary-goes-red) exists to handle.
- **Timeseries aspects are compared on their latest value.** The adapter emits
  one run event per quality check, so there is no series to verify.
- **Extra-entity enumeration is client-side.** GMS offers no server-side
  namespace filter on the enumeration endpoint, so the whole entity type is
  listed and narrowed by URN prefix. On a very large instance that is the
  expensive part of a verification.
- **One fabric.** A synthetic benchmark has a single environment; everything is
  emitted under `PROD`.
- **Container GUIDs are ours, not DataHub's.** They are deterministic and
  namespaced, but they are not computed by DataHub's own GUID algorithm, so a
  study container created by this adapter will not merge with one created by
  another source for the same study.
- **The estate's materialized files are not ingested** — only the truth graph's
  file records are. Pointing a catalogue at real bytes is a separate concern.
