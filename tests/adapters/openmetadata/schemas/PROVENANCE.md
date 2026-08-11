# Vendored OpenMetadata JSON schemas

These files are copied **verbatim** from the OpenMetadata project so the adapter's
emitted `Create<Entity>` payloads can be validated offline — no server, no
network, no `openmetadata-ingestion` dependency. They are test fixtures. Nothing
under `src/` reads them.

## Upstream

| | |
| --- | --- |
| Repository | <https://github.com/open-metadata/OpenMetadata> |
| Release / tag | `1.13.3-release` |
| Commit | `255f6694913b84797064a42859cda3f2a3425dc6` |
| Source root | `openmetadata-spec/src/main/resources/json/schema/` |
| Licence | Apache-2.0 (see the upstream `LICENSE`) |

Paths below are relative to that source root, and the local layout mirrors it
exactly so the schemas' own relative `$ref`s resolve unchanged.

## What is vendored, and why only this

Only the closure actually reachable from a payload this adapter emits. The full
OpenMetadata schema tree is thousands of files; vendoring it would make the
subset unreviewable and would quietly hide the fact that the adapter touches a
small, stable corner of the model.

Ten request schemas, one per entity kind the adapter creates:

```
api/classification/createClassification.json
api/classification/createTag.json
api/data/createContainer.json
api/data/createCustomProperty.json
api/data/createGlossary.json
api/data/createGlossaryTerm.json
api/domains/createDataProduct.json
api/domains/createDomain.json
api/services/createStorageService.json
api/teams/createTeam.json
```

Plus the shared types and enum-bearing entity schemas those `$ref` into, and the
entity schemas the normalization contract's evidence test reads — a forgiveness
rule is only checkable where both halves of the create/entity pair are present,
so the pair is vendored rather than the rule asserted:

```
entity/classification/classification.json  disabled, entityStatus (normalization evidence)
entity/classification/tag.json      deprecated, disabled, entityStatus (normalization evidence)
entity/data/container.json          fileFormat enum
entity/data/glossary.json           entityStatus (normalization evidence)
entity/data/glossaryTerm.json       entityStatus (normalization evidence)
entity/domains/dataProduct.json     dataProductType, visibility, portfolioPriority
entity/domains/domain.json          domainType enum
entity/services/storageService.json storageServiceType enum
entity/teams/team.json              teamType enum
type/basic.json                     entityName, fullyQualifiedEntityName, markdown, …
type/customProperty.json            propertyType, customPropertyConfig
type/entityReference.json
type/entityReferenceList.json
type/lifeCycle.json
type/tagLabel.json
```

Some of these files carry `$ref`s to schemas that are **not** vendored — storage
connection configs, `containerDataModel`'s column types, custom-property config
variants. That is deliberate and load-bearing: every one of them sits under a
field this adapter never emits, so validation never has to resolve it. If a
future mapping change starts emitting such a field, the validator raises an
unresolvable-reference error rather than silently skipping the check. An
unresolvable `$ref` is a signal to review the new field and vendor what it needs,
never a reason to relax validation.

## Refreshing

`pytest` never rewrites these files, exactly as it never rewrites the golden
digests or the DataHub fixtures. Refresh them deliberately:

```bash
uv run --frozen python scripts/update_openmetadata_fixtures.py \
    --schemas --release <tag> --commit <sha> \
    --confirm --reason "why this refresh is happening"
```

The script downloads each vendored path from the named commit and rewrites this
file's Upstream table. Bumping the vendored schemas is a **reviewable change**:

1. Read the diff. A changed `required` list, a changed enum member or a new
   `additionalProperties: false` is a compatibility event, not noise.
2. Re-run the suite. The committed export fixtures pin the emitted bytes, so a
   mapping that no longer validates fails loudly.
3. Update `OPENMETADATA_SCHEMA_TARGET` and `OPENMETADATA_SCHEMA_COMMIT` in
   `src/dataswamp_biosystems/adapters/openmetadata/mapping.py` together with the
   files — `tests/adapters/openmetadata/test_schema_pin.py` enforces that they
   move together.

Refreshing the schemas establishes **no live compatibility claim whatsoever**.
Reading a schema is not running against a server. `VERIFIED_OPENMETADATA_VERSION`
stays `None` until a real-server canary earns a point, per
[ADR 0006](../../../../docs/adr/0006-compatibility-points-not-ranges.md).
