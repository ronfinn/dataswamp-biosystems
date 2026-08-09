# The OpenMetadata adapter

DataSwamp Biosystems is a **vendor-neutral** benchmark. OpenMetadata is an
adapter: it consumes the benchmark's own emitted artefacts — a verified bundle —
and translates them outward. Nothing in the benchmark's generation, evaluation,
comparison or bundling layers knows OpenMetadata exists, and
`tests/adapters/test_isolation.py` enforces that rather than documenting it.

```bash
uv run dataswamp export-openmetadata --bundle dist/benchmark \
    --mode observed --output-dir export/openmetadata
```

> **What this does not prove.** There is no live path, no ingestion command and
> no canary. This project has never loaded the emitted plan into a running
> OpenMetadata instance. `VERIFIED_OPENMETADATA_VERSION` is `None` and stays
> `None` until a real-server run earns it. The schemas were *read*, which is not
> the same as having been *tested against* — see
> [ADR 0006](adr/0006-compatibility-points-not-ranges.md) and
> [What Issue A does not prove](#what-this-milestone-does-not-prove).

---

## Not a copy of the DataHub adapter

The two adapters look different because the two catalogues are different, and
imitating one in the other would have produced something that ingests well into
neither.

| | DataHub | OpenMetadata |
| --- | --- | --- |
| Unit of change | An **aspect** — one independently addressed facet of an entity | A whole **entity** create/update request |
| Identity | A URN; sometimes a GUID hashed over a key aspect | A hierarchical `fullyQualifiedName` |
| Emitted artefact | `mcps.jsonl` — one proposal per aspect | `entities.jsonl` — one `Create<Entity>` per entity, in load order |
| References | Embedded URNs, resolvable by string | `EntityReference` values needing a **server-assigned UUID** |

There is deliberately **no `adapters/common/`**. The two adapters duplicate an
id-escaping codec and an atomic-directory writer, and that is on purpose: with
exactly two examples it is not clear which similarities are structural and which
are coincidental. A shared helper extracted now would have to be undone the first
time the two catalogues' rules genuinely diverge. Revisit when there is a third.

---

## Why Container rather than Table

This is the single most consequential mapping decision, so it is the one stated
first.

**DataSwamp does not contain honest relational column metadata.** It models
datasets, physical files, contracts, ownership and lineage. It does not model
columns, data types, primary keys or partitioning — because the fictional estate
is a *file* estate, and inventing a column list to populate a `Table` would put a
fact in a catalogue that nothing in the benchmark supports.

So the estate maps onto a storage hierarchy instead:

```
storageService  dataswamp-biosystems          (serviceType: CustomStorage)
└── container   dataswamp-biosystems.<study-id>            a study
    └── container   dataswamp-biosystems.<study-id>.<dataset-id>       a dataset
        └── container   …<study-id>.<dataset-id>.<file-id>            a physical file
```

`CustomStorage` is a real member of OpenMetadata's `storageServiceType` enum and
is the honest choice: the estate is not in S3, ADLS or GCS. **No storage
connection is fabricated** — `connection` is optional in
`createStorageService.json`, and leaving it unset says "this is not a real object
store", which is true.

A **study** becomes an intermediate Container. OpenMetadata has no entity for a
scientific study, and a Container keeps the hierarchy navigable; that the node was
a study rather than a folder survives in the `dataswampEntityType` custom
property and is classified `reasonable` in the coverage report.

### What this costs

OpenMetadata's data-quality, profiling and column-lineage features are
table-scoped. Choosing Container gives them up. That is the intended trade: a
feature that works because we lied about the data model is worse than a feature
that is honestly unavailable. **The upgrade path is real** — if a future
scientific domain pack gives datasets genuine column-level schema, they can become
Tables, and because identity is derived from stable DataSwamp ids rather than from
entity kind, that change does not have to move an FQN.

---

## Identity: FQNs derived from stable ids

`src/dataswamp_biosystems/adapters/openmetadata/fqn.py`.

OpenMetadata identifies an entity two ways at once: a server-assigned `id`
(a UUID) and a `fullyQualifiedName` built by joining name segments with `.`. Only
the second is knowable offline, so **the FQN is this adapter's identity and the
UUID is never used as one**. An export that depended on a UUID could not be
written before the server had already seen it, which defeats the point.

```text
storage service   dataswamp-biosystems
study             dataswamp-biosystems.<study-id>
dataset           dataswamp-biosystems.<study-id>.<dataset-id>
file              dataswamp-biosystems.<study-id>.<dataset-id>.<file-id>
domain            dataswamp-<programme-id>
data product      dataswamp-<programme-id>.<product-id>
team              dataswamp-<team-id>
glossary          dataswamp-<vocabulary-id>
term              dataswamp-<vocabulary-id>.<term-id>
classification    dataswamp
tag               dataswamp.<facet-id>
```

Three properties are enforced by tests rather than hoped for.

**Identity is a pure function of stable DataSwamp ids.** Never a display title, a
description, an owner, a checksum, a quality status, a version or a lifecycle
stage — every one of which the imperfection engine is allowed to corrupt. If any
of them fed identity, re-loading a defect-bearing estate would produce a second
copy beside the first instead of updating it.

**Root-level identities are namespaced.** OpenMetadata's Domain, DataProduct,
Team, Glossary and Classification namespaces are *global* — unlike a Container,
there is no service to scope them under. A bare `genomics` domain would collide
with any other producer's, so every root-level identity carries the `dataswamp`
prefix.

**The safe-id codec is injective.** Anything outside `[a-z0-9-]` becomes `~`
followed by two hex digits per UTF-8 byte, and `~` escapes itself, so
`decode(encode(id)) == id` exactly. This is not cosmetic: an *observed* graph is
deliberately allowed to hold values the strict truth models forbid, and without
the codec a defect could smuggle a `.` into a dataset id and silently re-parent
the entity. `test_a_dot_in_an_id_cannot_re_parent_a_container` is that attack,
written down.

The codec intentionally duplicates DataHub's escaping scheme today. It is
reimplemented, not imported — see the `adapters/common/` note above.

`dataswampId` is stamped on containers and data products for traceability, but
**identity never depends on parsing it back out**.

---

## Ownership versus stewardship: the visible loss

DataSwamp draws a distinction OpenMetadata does not: an asset has one **owner**
and one or more **stewards**, and the difference is precisely what a governance
benchmark is testing for.

* **Owner** → OpenMetadata's native `owners`, as a team reference.
* **Stewards** → the `dataswampStewardRefs` custom property, and nothing else.

Flattening stewards into `owners` would have been easy and would have destroyed
the distinction. Putting them in `experts` would have been *nearly* right and is
still wrong: `experts` takes **user login names**, and DataSwamp stewards are
teams. So the mapping is classified **lossy**, and the reason says exactly what a
consumer loses:

> A consumer reading only native OpenMetadata fields will not see stewardship at
> all.

The stewarding teams are still emitted as real Team entities — the loss is in the
*relationship*, not in the entities.

---

## Why DataContract is deferred

OpenMetadata has a `DataContract` entity. It is not used.

DataSwamp's contract record carries an id, a version, a schema reference, an SLA
string and a list of quality expectations. OpenMetadata's DataContract is built
around schema definitions, semantics rules and linked test suites — none of which
DataSwamp contains. Populating one would have meant fabricating exactly the
schema and test-suite semantics that decision "no invented Tables" exists to
avoid, and the result would have looked like a governed agreement while being a
generated shell.

The contract facts are preserved verbatim as `dataswampContract*` custom
properties. Classification: **lossy** — the values survive, the concept's status
as a governed agreement does not.

---

## Unsupported scientific provenance

Subjects, biospecimens, assays, instrument runs and pipeline runs are **not
mapped**, and each is a counted row in the coverage report rather than a silent
omission.

*Subjects, biospecimens and assays* are scientific provenance with no catalogue
analogue. Synthesizing an entity for them would put fictional trial participants
into a data catalogue, which is not what a data catalogue is for.

*Instrument and pipeline runs* are closer — OpenMetadata has a `Pipeline` entity —
but a Pipeline lives under a `PipelineService`, and creating one would mean
inventing a platform connection that does not exist. An instrument acquisition is
not an orchestrated data pipeline in any case. The producing run id is preserved
on each file container so the link is not lost.

**Upgrade path** for all five: an OpenLineage run-event export, where a run is a
first-class concept, or the Neo4j graph export. Both are on the
[roadmap](roadmap.md#v02--metadata-and-lineage-integrations).

Lineage edges whose endpoints are any of these entities are counted separately as
`non_dataset_lineage`, so the gap between DataSwamp's lineage graph and the
catalogue's is a number rather than an impression.

---

## Quality checks are unsupported, and why

This one was decided against the grain of the original design, on the evidence of
the schema.

OpenMetadata's data-quality model is `TestDefinition` → `TestSuite` →
`TestCase`, and `TestDefinition.entityType` is an enum of **exactly** `TABLE` and
`COLUMN`
(`openmetadata-spec/.../tests/testDefinition.json`). Since this adapter
deliberately invents no Table, every TestDefinition it emitted would have to
assert table scope for an entity that is a Container — fabricating applicability
to satisfy a schema, which is the same mistake as inventing the Table in the
first place, one level removed.

So:

* Quality checks are classified **unsupported**, with the enum named as the
  reason.
* The facts survive in the `dataswampQualityChecks` custom property on the
  dataset container, as `check-id:check-type:status` entries.
* `test-results.jsonl` still ships, as an explicitly **blocked** plan — each
  record carries the check's type, status, evidence and evaluation time, plus a
  `blockedBy` field naming the reason. The facts and the blocker travel together
  rather than the results quietly disappearing.
* **Upgrade path:** if datasets ever acquire honest column-level schema and become
  Tables, the data-quality mapping becomes available without changing identity.

---

## The observed / truth boundary

Same structural discipline as the DataHub adapter, because the property being
protected is the same: an **observed** export is handed to the agent under test,
and if it leaked which entities carry defects the benchmark would be measuring
nothing.

The defence is not "the mapping is careful". It is that `_observed_source()` in
`export.py` **reads `observed/observed-graph.json` and nothing else**. The
expected findings, expected remediations, control partition, rule scope, injected
defects, mutation log and — for an adversarial bundle — `scenarios.jsonl` and
`scenario-transformations.jsonl` are never opened, so no future change to the
mapping can surface them by accident.

Three tests hold that line:

* a read-tracking `BundleReader` subclass asserting the observed build opens
  exactly one file;
* an AST check that `_observed_source`'s executable statements name no privileged
  reader method;
* the strongest one — **every privileged artefact in the bundle is made unreadable
  at the filesystem level and the observed export still succeeds.** That is a
  claim about file handles, not about intent.

An adversarial bundle therefore exports exactly what an ordinary one does: the
near-miss *values* are in the observed graph and travel with it; the records
saying they were planted stay behind.

### Truth mode is privileged, three independent ways

`--mode truth` is for benchmark administration and carries ground truth. It is
marked by three signals, because one could be stripped by accident and three is a
deliberate act:

1. every asset tagged `dataswamp.privileged-truth-export`;
2. reserved `dataswampTruthExport` and `dataswampTruthExpectedFindingRules`
   custom properties;
3. `"privileged": true` in `export-manifest.json`.

The offline validator **rejects** any of these appearing in an observed plan, and
rejects a truth asset missing them. Both directions are tested — a detector never
observed to fire is not evidence of anything.

---

## The export

```text
export/openmetadata/
├── custom-properties.jsonl   registrations, before anything uses them
├── entities.jsonl            one Create<Entity> per entity, in load order
├── lineage.jsonl             dataset→dataset edges, as a plan
├── test-results.jsonl        deferred, explicitly blocked result plan
├── mapping-coverage.json     what was mapped, how faithfully, what was dropped
├── export-manifest.json      mode, privilege, counts, schema target, digests
└── provenance.json           the standard environment provenance
```

Canonical JSON throughout — sorted keys, UTF-8, deterministic record order, final
newline — and **byte-identical for identical input**. There is deliberately **no
recipe or YAML wrapper**: the emitted JSONL *is* the interchange contract, and a
file that only restates it is one more thing to keep in step and one more place
for a claim to drift.

### Load order is part of the contract

```text
 1 custom-property registrations   8 storage service         12 data products
 2 classification                  9 study containers        13 data-product assets
 3 tags                           10 dataset containers      14 lineage
 4 glossaries                     11 file containers         15 deferred test results
 5 glossary terms
 6 teams
 7 domains
```

Test definitions, suites and cases are absent for the reason above.

`order` is a single monotonically increasing integer across **all four files**, so
a loader walking the plan in order never meets a reference to something it has not
created yet. The validator checks both the phase sequence and the ordering, and
`test_custom_properties_are_registered_before_any_entity_uses_them` pins the one
dependency that is easy to get wrong.

### Deferred references

OpenMetadata's `EntityReference` requires a **server-assigned UUID**. A parent
container, an owning team, a custom property's type and both endpoints of a
lineage edge are all `EntityReference` fields, and an offline export cannot know a
UUID the server has not issued. Fabricating one would be worse than useless: it
would produce a payload that looks complete and loads wrong.

So those are emitted as a declared `references` block beside the payload:

```json
{"field": "parent", "entityType": "container",
 "target": "dataswamp-biosystems.study-nsclc-01", "many": false, "builtin": false}
```

Fields OpenMetadata already expresses *as* FQNs — `domains`, `glossary`,
`classification`, a glossary term's `parent` — are emitted inline, because they
need no resolution. Both kinds are held to the same closure rule.

Offline schema validation resolves the declared references into schema-shaped
stand-ins before validating, so what gets checked is the payload as it will
actually be sent, not a deliberately incomplete one.

### Reference closure

Every DataSwamp-owned reference must resolve to something emitted **earlier** in
the same plan. Existing somewhere in the file is not the same as existing yet.

Exactly three references may resolve outside the export — OpenMetadata's built-in
`string` property type and the `container` and `dataProduct` entity types, which
every server ships with and which DataSwamp must not try to create. That is a
closed allow-list (`BUILTIN_REFERENCES`), not a general "this one is external"
flag; an escape hatch would turn closure into a suggestion.

The validator rejects dangling references, forward references, parent cycles,
self-lineage, duplicate FQNs, the same FQN under incompatible entity types, and
names outside the safe alphabet.

---

## Mapping coverage

`mapping-coverage.json` ships in **every** export and is a first-class part of it,
not documentation that happens to be machine-readable. The interesting property of
a catalogue adapter is not what it emits — it is what it quietly loses, and an
adapter that drops stewardship and says nothing looks identical, from its output,
to one that had no stewardship to drop.

Two orthogonal axes, and neither substitutes for the other.

**Semantic classification** — *how faithful is this mapping?*

| | |
| --- | --- |
| `exact` | OpenMetadata has the same concept with the same meaning. |
| `reasonable` | No identical concept; a defensible one is used and the source concept stays recoverable. A reader is not misled. |
| `lossy` | A distinction DataSwamp draws does not survive into native fields. Values carried, meaning flattened. |
| `unsupported` | Deliberately not mapped — no honest home, or the only home would require asserting something false. |

**Operational state** — *where does this show up?*

| | |
| --- | --- |
| `materialized_in_entity_export` | Emitted as entity payloads in this export. |
| `deferred_live_write` | Emitted as a plan for a later live write. |
| `deliberately_not_mapped` | Emitted nowhere; recorded so the omission is counted. |

They are genuinely independent — dataset lineage is `reasonable` **and**
`deferred_live_write`; quality-check results are `unsupported` **and**
`deferred_live_write`. Collapsing them into one field would make "we chose not to"
indistinguishable from "we could not", which is the exact distinction a governance
benchmark should not blur.

Each row carries a source count, an emitted count, a deliberately-dropped count,
and — mandatory for anything not `exact` — a reason. `build_coverage` **refuses**
to build a report that misses a declared concept or counts an undeclared one, so a
mapping change that starts emitting something new fails rather than shipping a
report that under-describes the export.

Summary of the current mapping:

| Source concept | OpenMetadata target | Classification |
| --- | --- | --- |
| company | `storageService` | reasonable |
| programme | `domain` | reasonable |
| study | `container` | reasonable |
| dataset | `container` | reasonable |
| physical file | `container` | reasonable |
| file containment | `container.parent` | **exact** |
| data product | `dataProduct` | reasonable |
| data-product components | `dataProduct.assets` | reasonable (deferred) |
| team | `team` | reasonable |
| ownership | `owners` | reasonable |
| **stewardship** | custom property only | **lossy** |
| controlled vocabulary | `glossary` | reasonable |
| vocabulary term | `glossaryTerm` | reasonable |
| facet tag | `tag` | reasonable |
| **data contract** | custom properties only | **lossy** |
| dataset lineage | lineage edge | reasonable (deferred) |
| quality check | — | unsupported |
| quality-check result | — | unsupported (deferred) |
| subject, biospecimen, assay | — | unsupported |
| instrument run, pipeline run | — | unsupported |
| non-dataset lineage | — | unsupported |

---

## Custom properties

Every DataSwamp fact OpenMetadata has no native home for lands in a custom
property, registered against `container` and `dataProduct` before any entity uses
one. Names are camelCase and `dataswamp`-prefixed, well inside OpenMetadata's
`customPropertyName` pattern.

**They are all declared `string`, deliberately.** An observed record may hold a
null, an empty value or a wrong-typed one — that *is* the defect — and a typed
property would either reject it or silently coerce it. The export's job is to show
a catalogue what it would really have seen.

The one place this matters most:

| | |
| --- | --- |
| `size` (native) | OpenMetadata's Container size, **in KB**, floored |
| `dataswampPhysicalBytes` | The **exact** byte count |

Flooring is the conservative direction — a container never claims to hold more
than it does — and the byte count is the authoritative figure. A 1500-byte file
reports `size: 1.0` and `dataswampPhysicalBytes: "1500"`. If the byte count is
corrupt (a defect put a string there), `size` is **omitted** rather than guessed
at, and the corrupt value still travels in the property.

Similarly, `fileFormat`: OpenMetadata's enum is
`zip, gz, zstd, csv, tsv, json, parquet, avro, MF4`. A `parquet` file declares
`fileFormats: ["parquet"]`. An `h5ad` file declares **nothing** natively —
`h5ad` is not `json`, and saying it is would put a false fact in a catalogue to
satisfy a schema. The real format is in `dataswampFileFormat`.

---

## Offline schema validation

Emitted payloads are validated against **OpenMetadata's own JSON schemas**,
vendored verbatim from a named upstream commit under
`tests/adapters/openmetadata/schemas/` — 21 files, the minimum reachable closure,
with full provenance in `PROVENANCE.md`.

| | |
| --- | --- |
| Upstream | `open-metadata/OpenMetadata` |
| Release | `1.13.3-release` |
| Commit | `255f6694913b84797064a42859cda3f2a3425dc6` |
| Licence | Apache-2.0 |

`additionalProperties: false` is honoured, so an unknown field **fails** rather
than being silently dropped at load time. Enum members are enforced. Some vendored
files carry `$ref`s to schemas that are *not* vendored — storage connection
configs, `containerDataModel`'s column types — and that is load-bearing: each sits
under a field the adapter never emits, so validation never resolves it, and if a
future mapping change starts emitting one, the validator **raises** rather than
passing vacuously. An unresolvable `$ref` is a signal to review the new field, never
a reason to relax validation.

Refreshing is deliberate and never done by `pytest`:

```bash
uv run --frozen python scripts/update_openmetadata_fixtures.py --schemas \
    --release <tag> --commit <sha> --confirm --reason "..."
uv run --frozen python scripts/update_openmetadata_fixtures.py --fixtures \
    --confirm --reason "..."
```

`jsonschema` is a **dev** dependency only. Installing DataSwamp installs nothing
catalogue-shaped — see [ADR 0007](adr/0007-no-catalogue-client-dependency.md).

---

## Versioning: three different things

Following [ADR 0006](adr/0006-compatibility-points-not-ranges.md), which exists
precisely because these get conflated:

| | What it is | What backs it | Value |
| --- | --- | --- | --- |
| `OPENMETADATA_SCHEMA_TARGET` | The exact schema revision payloads were written against and are validated against | The vendored subset + committed fixtures | `1.13.3-release` |
| `OPENMETADATA_MODEL_TARGET_RANGE` | A **declared target** for payload shape. Not evidence, not a statement about any REST endpoint | Nothing. It is an intention | `>=1.9,<2` |
| `VERIFIED_OPENMETADATA_VERSION` | The one release the live path was actually **run** against | A green canary run, and only that | **`None`** |

`OM_ADAPTER_VERSION` is `1.0.0`, bumped when the emitted plan changes for
unchanged input.

There is **no `OM_NORMALIZATION_VERSION`**. Normalization is a round-trip concern
and belongs to the live milestone; adding one now would version a contract that
does not exist.

---

## What this milestone does *not* prove

Stated plainly, because a reader should not have to infer it:

* **Nothing has been loaded into a running OpenMetadata.** Not once. There is no
  ingestion command, no client, no canary, no credentials handling.
* **No REST endpoint has been exercised.** The paths recorded in `ENDPOINTS` are
  read from documentation, for a future live path to start from. They are
  untested.
* **The declared model range is not evidence.** `>=1.9,<2` is where the payload
  shape is *aimed*. Exactly one revision inside it has been read, and zero have
  been run against.
* **Schema validity is not load success.** A payload can satisfy every JSON
  schema and still be rejected by server-side business rules, authorization, or
  reference resolution. Only a real run settles that.
* **The declared references are unresolved by construction.** Whether the FQNs
  this plan names actually resolve to the right entities on a server is exactly
  the question a live path answers.

Treat OpenMetadata support as **offline-only and experimental**. When a
compatibility point is earned it will be a named release in
`VERIFIED_OPENMETADATA_VERSION`, moving together with a workflow pin and this
document — never a range, and never on the strength of a schema having been read.

---

## Related

* [ADR 0007 — catalogue adapters emit payloads rather than depend on a client](adr/0007-no-catalogue-client-dependency.md)
* [ADR 0006 — compatibility as tested points, not asserted ranges](adr/0006-compatibility-points-not-ranges.md)
* [ADR 0002 — truth versus observed state](adr/0002-truth-vs-observed-state.md)
* [The DataHub adapter](datahub.md) — the other integration, and the contrast
* [Bundles](bundles.md) — the adapter's only input
* [Public API](public-api.md) — what is stable and what is not
