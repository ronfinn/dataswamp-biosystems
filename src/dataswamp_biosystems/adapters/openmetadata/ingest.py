"""Replay an emitted OpenMetadata export against a live catalogue.

The live path is strictly downstream of the offline one::

    bundle -> export-openmetadata -> emitted export -> ingest-openmetadata -> verify-om-ingestion

This module's input is an **emitted export directory**, never a bundle. It does
not regenerate metadata, reopen the generator, reinterpret a bundle or consult
the benchmark answer key. The emitted export is treated as the authoritative
statement of what the catalogue should hold, which is what makes the round-trip
claim meaningful: if ingestion could re-derive the payload, "the server matches
what we sent" would be comparing a computation against itself.

Seven things are checked before a byte leaves the process:

1. every file the manifest declares is present and its digest recomputes;
2. the manifest's mode is a known mode and agrees with its privilege flag;
3. the plan re-parses into the same record shape the exporter emitted;
4. the plan passes the *offline* validator again — FQN shape and uniqueness,
   entity-type coherence, containment, reference closure, privilege markers;
5. record ``order`` is strictly increasing across the whole export and the
   phases appear in contract sequence;
6. every reference resolves to a target emitted *earlier*, or to the closed
   built-in allow-list;
7. every operation this module would perform maps back to exactly one emitted
   record.

Only then is a socket opened, and even then only by :mod:`.client`.

**Order is load-bearing here in a way it is not for DataHub.** OpenMetadata
models an entity as a whole document with a hierarchical FQN, so a container
cannot be written before its parent, an ``extension`` key cannot be used before
its custom property is registered, and a lineage edge cannot be written before
both endpoints exist. Nothing in this module sorts, groups, batches or otherwise
reorders the plan: it is replayed exactly as emitted. Batching is deliberately
absent rather than merely unimplemented — a batch that crossed a dependency
boundary would be a correctness bug bought for throughput nobody needs at this
size.

**The deferred quality-check results are not transmitted.** They are emitted with
``status: blocked`` and no endpoint, because OpenMetadata's ``TestDefinition``
admits only ``TABLE`` and ``COLUMN`` scope while DataSwamp datasets are
Containers. Ingestion honours that: it neither invents a Table to unlock them nor
quietly drops them, but classifies them as blocked operations and reports the
count.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataswamp_biosystems.adapters.openmetadata.client import OpenMetadataClient
from dataswamp_biosystems.adapters.openmetadata.errors import OpenMetadataConfigError
from dataswamp_biosystems.adapters.openmetadata.export import (
    CUSTOM_PROPERTIES_NAME,
    ENTITIES_NAME,
    EXPORT_MANIFEST_NAME,
    LINEAGE_NAME,
    MAPPING_COVERAGE_NAME,
    TEST_RESULTS_NAME,
)
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    ExportMode,
    ExportPlan,
    PlanRecord,
    Reference,
)
from dataswamp_biosystems.adapters.openmetadata.validate import validate_plan
from dataswamp_biosystems.truth import serialize

# What this module does with one plan record. The kind is derived from the
# record's own phase and shape, never from its emitted ``endpoint`` annotation:
# a transport path is a live fact and belongs to :mod:`.client`.
KIND_CUSTOM_PROPERTY = "register-custom-property"
KIND_CREATE_ENTITY = "create-entity"
KIND_ADD_ASSETS = "add-data-product-assets"
KIND_ADD_LINEAGE = "add-lineage"
KIND_BLOCKED = "blocked"

# Phases whose records are transmitted, and how.
_PHASE_KINDS: dict[str, str] = {
    "custom-property": KIND_CUSTOM_PROPERTY,
    "classification": KIND_CREATE_ENTITY,
    "tag": KIND_CREATE_ENTITY,
    "glossary": KIND_CREATE_ENTITY,
    "glossary-term": KIND_CREATE_ENTITY,
    "team": KIND_CREATE_ENTITY,
    "domain": KIND_CREATE_ENTITY,
    "storage-service": KIND_CREATE_ENTITY,
    "study-container": KIND_CREATE_ENTITY,
    "dataset-container": KIND_CREATE_ENTITY,
    "file-container": KIND_CREATE_ENTITY,
    "data-product": KIND_CREATE_ENTITY,
    "data-product-assets": KIND_ADD_ASSETS,
    "lineage": KIND_ADD_LINEAGE,
    "test-result": KIND_BLOCKED,
}

# Reference fields that OpenMetadata's create bodies express as an
# ``EntityReference`` (or a list of them) and that therefore need a UUID the
# export cannot know. Anything not listed here is emitted inline as an FQN by the
# mapping and is transmitted untouched.
_MANY_REFERENCE_FIELDS: frozenset[str] = frozenset({"owners", "experts", "reviewers"})


@dataclass(frozen=True)
class Operation:
    """One emitted plan record, paired with what it will do on the wire.

    An operation is derived from exactly one record and carries it, so proving
    "the transmitted set equals the emitted set" is a matter of comparing
    identities rather than trusting a log this module wrote about itself.
    """

    record: PlanRecord
    kind: str

    @property
    def identity(self) -> tuple[int, str, str, str]:
        """The record's position and identity, as a comparable tuple."""
        return (self.record.order, self.record.phase, self.record.entity_type, self.record.fqn)

    @property
    def transmitted(self) -> bool:
        return self.kind != KIND_BLOCKED


@dataclass(frozen=True)
class LoadedExport:
    """A verified emitted OpenMetadata export, ready to replay or compare against."""

    root: Path
    mode: ExportMode
    plan: ExportPlan
    manifest: dict[str, Any]

    @property
    def privileged(self) -> bool:
        return bool(self.manifest.get("privileged", False))

    @property
    def records(self) -> tuple[PlanRecord, ...]:
        return self.plan.records

    def payload_digests(self) -> dict[str, str]:
        """The manifest's per-file digests — the identity of this plan."""
        declared = self.manifest.get("files", {})
        return {str(k): str(v) for k, v in sorted(declared.items())} if declared else {}

    def identity(self) -> dict[str, Any]:
        """Non-secret provenance identifying which benchmark this export came from.

        Enough to tell two round-trip reports apart and to tie one back to the
        export it judged. No path, no host, no clock.
        """
        bundle = self.manifest.get("bundle", {})
        return {
            "mode": self.mode.value,
            "privileged": self.privileged,
            "adapter_version": self.manifest.get("adapter_version", ""),
            "openmetadata_schema_target": self.manifest.get("openmetadata_schema_target", ""),
            "openmetadata_model_target_range": self.manifest.get(
                "openmetadata_model_target_range", ""
            ),
            "verified_openmetadata_version": self.manifest.get("verified_openmetadata_version"),
            "bundle_fingerprint": bundle.get("bundle_fingerprint", ""),
            "benchmark_release": bundle.get("benchmark_release", ""),
            "ground_truth_fingerprint": bundle.get("ground_truth_fingerprint", ""),
            "files": self.payload_digests(),
        }


@dataclass(frozen=True)
class IngestPlan:
    """What would be replayed, computed with no network activity whatsoever.

    ``--dry-run`` produces one of these and reports it. Building a plan opens no
    socket and performs no connectivity or health check: a dry run that contacts
    a server is not a dry run, and a health probe is not part of this contract.
    """

    export: LoadedExport
    operations: tuple[Operation, ...]

    @property
    def transmitted_count(self) -> int:
        return sum(1 for operation in self.operations if operation.transmitted)

    @property
    def blocked_count(self) -> int:
        return sum(1 for operation in self.operations if not operation.transmitted)

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for operation in self.operations:
            counts[operation.kind] = counts.get(operation.kind, 0) + 1
        return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Reading an emitted export back into plan records
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OpenMetadataConfigError(f"{path.name} is missing from the export directory") from exc
    except json.JSONDecodeError as exc:
        raise OpenMetadataConfigError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OpenMetadataConfigError(f"{path.name} is not a JSON object")
    return payload


def _reference_from_json(payload: Any, where: str) -> Reference:
    if not isinstance(payload, dict):
        raise OpenMetadataConfigError(f"{where}: a reference entry is not a JSON object")
    return Reference(
        field=str(payload.get("field", "")),
        entity_type=str(payload.get("entityType", "")),
        target=str(payload.get("target", "")),
        many=bool(payload.get("many", False)),
        builtin=bool(payload.get("builtin", False)),
    )


def _record_from_json(payload: Any, where: str) -> PlanRecord:
    """Rebuild one :class:`PlanRecord` from its emitted JSON form.

    The inverse of :meth:`PlanRecord.as_json`. Rebuilding rather than working on
    raw dictionaries is what lets the *offline* validator run again over an
    export read from disk: the same function that proved the plan sound when it
    was written re-proves it before anything is transmitted, so a plan edited in
    place cannot be replayed.
    """
    if not isinstance(payload, dict):
        raise OpenMetadataConfigError(f"{where} is not a JSON object")
    order = payload.get("order")
    if not isinstance(order, int):
        raise OpenMetadataConfigError(f"{where} has no integer 'order'")
    create = payload.get("create")
    if create is not None and not isinstance(create, dict):
        raise OpenMetadataConfigError(f"{where} has a non-object 'create'")
    plan = payload.get("plan")
    if plan is not None and not isinstance(plan, dict):
        raise OpenMetadataConfigError(f"{where} has a non-object 'plan'")
    references = payload.get("references", [])
    if not isinstance(references, list):
        raise OpenMetadataConfigError(f"{where} has a non-list 'references'")
    dataswamp_id = payload.get("dataswampId")
    return PlanRecord(
        order=order,
        phase=str(payload.get("phase", "")),
        concept=str(payload.get("concept", "")),
        entity_type=str(payload.get("entityType", "")),
        endpoint=str(payload.get("endpoint", "")),
        fqn=str(payload.get("fullyQualifiedName", "")),
        create=create,
        references=tuple(_reference_from_json(item, where) for item in references),
        dataswamp_id=str(dataswamp_id) if isinstance(dataswamp_id, str) else None,
        plan=plan,
    )


def _read_records(root: Path, name: str) -> tuple[PlanRecord, ...]:
    path = root / name
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise OpenMetadataConfigError(f"{name} is missing from the export directory") from exc
    records: list[PlanRecord] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OpenMetadataConfigError(f"{name} line {number} is not valid JSON") from exc
        records.append(_record_from_json(payload, f"{name} line {number}"))
    return tuple(records)


def load_export(export_dir: Path | str) -> LoadedExport:
    """Read, digest-verify and re-validate an emitted OpenMetadata export.

    Raises :class:`OpenMetadataConfigError` on anything wrong with the export. A
    tampered plan is refused here, before any network activity: replaying
    metadata that no longer matches the manifest it was published with would put
    unattributable content into somebody's catalogue.
    """
    root = Path(export_dir)
    if not root.is_dir():
        raise OpenMetadataConfigError(f"{root} is not a directory")

    manifest = _read_json(root / EXPORT_MANIFEST_NAME)

    declared = manifest.get("files", {})
    if not isinstance(declared, dict) or not declared:
        raise OpenMetadataConfigError(f"{EXPORT_MANIFEST_NAME} declares no files")
    for name in sorted(declared):
        path = root / name
        if not path.is_file():
            raise OpenMetadataConfigError(f"{name} is declared in the manifest but missing")
        actual = serialize.digest(path.read_bytes())
        if actual != declared[name]:
            raise OpenMetadataConfigError(
                f"{name} does not match its manifest digest — the export has been modified "
                f"since it was written (expected {declared[name]}, got {actual})"
            )

    mode_value = str(manifest.get("mode", ""))
    try:
        mode = ExportMode(mode_value)
    except ValueError as exc:
        raise OpenMetadataConfigError(
            f"{EXPORT_MANIFEST_NAME} declares an unknown mode {mode_value!r}"
        ) from exc
    if bool(manifest.get("privileged", False)) is not (mode is ExportMode.TRUTH):
        raise OpenMetadataConfigError(
            f"{EXPORT_MANIFEST_NAME} declares mode {mode_value!r} with "
            f"privileged={manifest.get('privileged')!r}, which contradict each other"
        )

    coverage = _read_json(root / MAPPING_COVERAGE_NAME)
    plan = ExportPlan(
        mode=mode,
        custom_properties=_read_records(root, CUSTOM_PROPERTIES_NAME),
        entities=_read_records(root, ENTITIES_NAME),
        lineage=_read_records(root, LINEAGE_NAME),
        test_results=_read_records(root, TEST_RESULTS_NAME),
        coverage=coverage,
    )
    if not plan.records:
        raise OpenMetadataConfigError("the export contains no plan records")

    problems = validate_plan(plan)
    if problems:
        joined = "; ".join(problems[:5])
        raise OpenMetadataConfigError(
            f"the emitted plan is invalid — {len(problems)} problem(s): {joined}"
        )

    return LoadedExport(root=root, mode=mode, plan=plan, manifest=manifest)


# ---------------------------------------------------------------------------
# Planning and replay
# ---------------------------------------------------------------------------


def plan_ingestion(export: LoadedExport) -> IngestPlan:
    """Return the replay plan for a verified export. Opens no socket.

    The plan is the emitted record sequence, in emitted order, one operation per
    record. It is not sorted, grouped or batched — see this module's docstring.
    """
    operations: list[Operation] = []
    for record in export.records:
        kind = _PHASE_KINDS.get(record.phase)
        if kind is None:
            raise OpenMetadataConfigError(
                f"{record.phase} record {record.fqn!r}: this transport knows no operation "
                f"for phase {record.phase!r} and refuses to guess one"
            )
        if kind == KIND_CREATE_ENTITY and record.create is None:
            raise OpenMetadataConfigError(
                f"{record.phase} record {record.fqn!r}: an entity phase with no create payload"
            )
        operations.append(Operation(record=record, kind=kind))

    orders = [operation.record.order for operation in operations]
    if orders != sorted(orders) or len(set(orders)) != len(orders):
        raise OpenMetadataConfigError(
            "the emitted plan is not in strictly increasing order; replaying it would "
            "violate the dependency order the export contract guarantees"
        )
    return IngestPlan(export=export, operations=tuple(operations))


def _resolve_create(record: PlanRecord, client: OpenMetadataClient) -> dict[str, Any]:
    """Return the create body with declared references resolved to ``EntityReference``.

    This is the one place an emitted body changes shape, and it changes only its
    shape. The export declares each unresolvable reference as a
    :class:`~dataswamp_biosystems.adapters.openmetadata.mapping.Reference` block
    precisely because OpenMetadata keys an ``EntityReference`` by a UUID the
    server has not issued yet; resolving it by FQN is the encoding that
    declaration asks for. Every other field is copied through untouched, and no
    field is added, removed or coerced.
    """
    body = dict(record.create or {})
    for reference in record.references:
        if reference.builtin:
            continue
        resolved = client.entity_reference(reference.entity_type, reference.target)
        if reference.field in _MANY_REFERENCE_FIELDS or reference.many:
            existing = body.get(reference.field)
            items = list(existing) if isinstance(existing, list) else []
            items.append(resolved)
            body[reference.field] = items
        else:
            body[reference.field] = resolved
    return body


def execute_operation(operation: Operation, client: OpenMetadataClient) -> bool:
    """Perform one operation. Returns ``True`` if anything was transmitted."""
    record = operation.record
    if operation.kind == KIND_BLOCKED:
        return False
    if operation.kind == KIND_CUSTOM_PROPERTY:
        target = next(
            (ref.target for ref in record.references if ref.field == "entityType"),
            None,
        )
        property_type = next(
            (ref.target for ref in record.references if ref.field == "propertyType"),
            None,
        )
        if target is None or property_type is None:
            raise OpenMetadataConfigError(
                f"custom property {record.fqn!r} does not declare both an entityType and a "
                "propertyType reference; this transport will not choose one for it"
            )
        body = dict(record.create or {})
        body["propertyType"] = property_type
        client.register_custom_property(target, body)
        return True
    if operation.kind == KIND_CREATE_ENTITY:
        client.create_or_update(record.entity_type, _resolve_create(record, client))
        return True
    if operation.kind == KIND_ADD_ASSETS:
        assets = [
            client.entity_reference(
                str(asset.get("entityType")), str(asset.get("fullyQualifiedName"))
            )
            for asset in (record.plan or {}).get("assets", [])
            if isinstance(asset, dict)
        ]
        client.add_data_product_assets(record.fqn, assets)
        return True
    if operation.kind == KIND_ADD_LINEAGE:
        plan = record.plan or {}
        endpoints = []
        for side in ("fromEntity", "toEntity"):
            value = plan.get(side)
            if not isinstance(value, dict):
                raise OpenMetadataConfigError(f"lineage edge {record.fqn!r} has no {side} endpoint")
            endpoints.append(
                client.entity_reference(
                    str(value.get("entityType")), str(value.get("fullyQualifiedName"))
                )
            )
        client.add_lineage(endpoints[0], endpoints[1])
        return True
    raise OpenMetadataConfigError(  # pragma: no cover - _PHASE_KINDS is closed
        f"unknown operation kind {operation.kind!r}"
    )


def execute_ingestion(plan: IngestPlan, client: OpenMetadataClient) -> int:
    """Replay every operation in emitted order and return how many were transmitted.

    Strictly sequential. Concurrency would be the same mistake as batching, one
    level down: two operations that look independent may not be, and the plan
    already encodes which is which by putting them in order.
    """
    sent = 0
    for operation in plan.operations:
        if execute_operation(operation, client):
            sent += 1
    return sent


__all__ = [
    "KIND_CUSTOM_PROPERTY",
    "KIND_CREATE_ENTITY",
    "KIND_ADD_ASSETS",
    "KIND_ADD_LINEAGE",
    "KIND_BLOCKED",
    "Operation",
    "LoadedExport",
    "IngestPlan",
    "load_export",
    "plan_ingestion",
    "execute_operation",
    "execute_ingestion",
]
