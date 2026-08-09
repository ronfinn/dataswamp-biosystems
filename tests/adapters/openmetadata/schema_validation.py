"""Validate emitted OpenMetadata payloads against the vendored upstream schemas.

This is the offline stand-in for a running OpenMetadata: it is the only thing in
the repository that can catch "the adapter emits a field OpenMetadata does not
have" or "an enum member that does not exist". The adapter's own
:func:`~dataswamp_biosystems.adapters.openmetadata.validate.validate_plan` checks
*plan* properties — identity, ordering, closure, privilege. This module checks
*payload* properties, against OpenMetadata's own definition of them.

Three details make it stricter than it looks.

**``additionalProperties: false`` is honoured, not relaxed.** Every upstream
``Create<Entity>`` schema sets it, so an unknown field fails validation rather
than being quietly dropped at load time — which is the failure mode this whole
exercise exists to prevent.

**Declared references are resolved before validating, not skipped.** OpenMetadata
models a parent container, an owning team and a custom property's type as
``EntityReference``, which requires a server-assigned UUID the export cannot know.
The adapter therefore emits those as a declared reference beside the payload. If
this module validated the payload as-emitted, it would be validating something
that is deliberately incomplete and would never notice a *required* reference
going missing. Instead it substitutes a schema-shaped stand-in, so what gets
validated is the payload as it will actually be sent. The stand-in UUIDs are
derived deterministically from the FQN and exist only here — nothing under
``src/`` ever produces or consumes one.

**Unresolvable ``$ref``s are errors, not skips.** The vendored subset covers only
what the adapter emits. If a mapping change starts emitting a field whose schema
was never vendored, validation raises instead of passing vacuously.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from dataswamp_biosystems.adapters.openmetadata import PlanRecord

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

# The base every vendored schema is registered under. Upstream files carry an
# ``$id`` pointing at open-metadata.org, which would make their relative ``$ref``s
# resolve to the network; it is replaced by the file's own path so resolution
# stays entirely local.
_BASE = "https://dataswamp.example/openmetadata-vendored/"

# One upstream request schema per OpenMetadata entity type this adapter creates.
CREATE_SCHEMAS: dict[str, str] = {
    "customProperty": "api/data/createCustomProperty.json",
    "classification": "api/classification/createClassification.json",
    "tag": "api/classification/createTag.json",
    "glossary": "api/data/createGlossary.json",
    "glossaryTerm": "api/data/createGlossaryTerm.json",
    "team": "api/teams/createTeam.json",
    "domain": "api/domains/createDomain.json",
    "storageService": "api/services/createStorageService.json",
    "container": "api/data/createContainer.json",
    "dataProduct": "api/domains/createDataProduct.json",
}

# How each declared reference field is shaped once resolved. ``None`` marks a
# reference that is *not* a payload field at all — the entity type a custom
# property is registered against is a path parameter, not part of the body.
_REFERENCE_SHAPES: dict[str, str | None] = {
    "parent": "single",
    "propertyType": "single",
    "owners": "list",
    "entityType": None,
}


def _stand_in_uuid(target: str) -> str:
    """Return a deterministic, test-only UUID for a not-yet-created entity."""
    return str(uuid5(NAMESPACE_URL, f"dataswamp-openmetadata-test:{target}"))


@lru_cache(maxsize=1)
def _registry() -> Registry[Any]:
    registry: Registry[Any] = Registry()
    for path in sorted(SCHEMA_DIR.rglob("*.json")):
        relative = path.relative_to(SCHEMA_DIR).as_posix()
        document = json.loads(path.read_text(encoding="utf-8"))
        # Drop the upstream ``$id`` so the file's own location is its base URI and
        # every relative ``$ref`` stays inside the vendored tree.
        document.pop("$id", None)
        resource = Resource.from_contents(document, default_specification=DRAFT7)
        registry = registry.with_resource(f"{_BASE}{relative}", resource)
    return registry


def vendored_schema_paths() -> tuple[str, ...]:
    """Return every vendored schema path, relative and sorted."""
    return tuple(
        sorted(path.relative_to(SCHEMA_DIR).as_posix() for path in SCHEMA_DIR.rglob("*.json"))
    )


def validator_for(entity_type: str) -> Draft7Validator:
    """Return a validator for one OpenMetadata create request."""
    relative = CREATE_SCHEMAS[entity_type]
    schema = json.loads((SCHEMA_DIR / relative).read_text(encoding="utf-8"))
    schema.pop("$id", None)
    schema["$id"] = f"{_BASE}{relative}"
    return Draft7Validator(schema, registry=_registry())


def resolved_payload(record: PlanRecord) -> dict[str, Any]:
    """Return ``record``'s create payload with its declared references filled in.

    The result is what a loader would actually send once it had looked each
    reference up. Nothing here is emitted: the stand-in UUIDs never leave this
    module.
    """
    if record.create is None:
        raise ValueError(f"{record.fqn} is a plan record and has no create payload")
    payload = json.loads(json.dumps(record.create))
    for reference in record.references:
        shape = _REFERENCE_SHAPES.get(reference.field, "single")
        if shape is None:
            continue
        resolved = {
            "id": _stand_in_uuid(reference.target),
            "type": reference.entity_type,
            "fullyQualifiedName": reference.target,
        }
        if shape == "list":
            payload.setdefault(reference.field, []).append(resolved)
        else:
            payload[reference.field] = resolved
    return payload


def schema_problems(record: PlanRecord) -> list[str]:
    """Return every schema violation in ``record``'s payload, sorted and readable."""
    validator = validator_for(record.entity_type)
    return sorted(
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(resolved_payload(record))
    )


__all__ = [
    "SCHEMA_DIR",
    "CREATE_SCHEMAS",
    "vendored_schema_paths",
    "validator_for",
    "resolved_payload",
    "schema_problems",
]
