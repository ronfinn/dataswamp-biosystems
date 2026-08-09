"""A local, in-process stand-in for an OpenMetadata server.

The whole live path has to be provable without Docker, without a network and
without credentials, so the tests need something that behaves like a catalogue.
This is it: a :mod:`http.server` thread that speaks the endpoints the adapter
uses, stores entities in dictionaries, and — crucially — can be told to
*misbehave* in specific, named ways.

**It is built to disagree with the client.** That is the whole design constraint,
and it is not hypothetical. The DataHub fake once accepted the exact wrong wire
dialect for months because it read the request body the way the client wrote it;
a real server answered HTTP 500 and 111 offline tests had missed it. A fake that
models the client cannot catch the client.

So nothing here imports from
:mod:`dataswamp_biosystems.adapters.openmetadata.client`. Not the collection
table, not the field names, not the envelope shapes. Every route below is written
out again from OpenMetadata's own JAX-RS resource classes at the ``1.13.3-release``
tree, and every request body is validated against the **vendored upstream JSON
schemas** in ``tests/adapters/openmetadata/schemas/`` — OpenMetadata's own
declarations, complete with ``additionalProperties: false``. If the client and
this file disagree about a path, a verb, a required field or an extra field, this
file wins and the test fails.

What it validates
-----------------
* exact HTTP method per route (``POST`` where ``PUT`` is required is refused);
* exact endpoint path (an unknown or misspelled route is 404, never a fallback);
* request envelope shape (a bare entity where ``{"edge": ...}`` is required, or
  a list where an object is required, is 400);
* required fields and unknown fields, from the vendored ``Create<Entity>``
  schemas;
* percent-decoded FQN addressing;
* create-or-update semantics — a second ``PUT`` updates rather than duplicating;
* reference pre-existence — a container whose parent has not been created yet,
  or a lineage edge naming an unknown UUID, is refused;
* custom-property registration before an ``extension`` key using it;
* ``fields`` opt-in on reads: ``owners``, ``tags``, ``extension``, ``domains``,
  ``parent`` and friends are withheld unless asked for, exactly as OpenMetadata
  withholds them. A client that forgets to ask sees a lean entity and its
  round-trip fails — which is the correct outcome and not something the fake
  should paper over.

**It is not an OpenMetadata emulator and it is not evidence.** It implements the
shapes this adapter depends on and nothing else, and it makes no claim about how
a real server behaves. Establishing that is a live canary's job, and no such
canary has run: ``VERIFIED_OPENMETADATA_VERSION`` stays ``None``.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCHEMAS = Path(__file__).resolve().parent / "schemas"


class RequestError(Exception):
    """The request is malformed, in the way a real server would refuse it."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------
# The API surface, written out from upstream's resource classes.
# --------------------------------------------------------------------------
# Deliberately *not* imported from client.py. See this module's docstring.
COLLECTION_ROUTES: dict[str, str] = {
    "/api/v1/classifications": "classification",
    "/api/v1/tags": "tag",
    "/api/v1/glossaries": "glossary",
    "/api/v1/glossaryTerms": "glossaryTerm",
    "/api/v1/teams": "team",
    "/api/v1/domains": "domain",
    "/api/v1/services/storageServices": "storageService",
    "/api/v1/containers": "container",
    "/api/v1/dataProducts": "dataProduct",
}

# The vendored Create<Entity> schema backing each collection. These are
# OpenMetadata's own files; the fake reads `required` and `properties` straight
# out of them, so "unknown field" and "missing required field" are upstream's
# definitions rather than this file's opinion.
CREATE_SCHEMAS: dict[str, str] = {
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

# Fields OpenMetadata withholds from a response unless the caller asks for them
# by name. A general convention of its EntityResource layer, applied here so a
# client that forgets to request a field genuinely cannot see it.
OPT_IN_FIELDS: frozenset[str] = frozenset(
    {
        "owners",
        "tags",
        "extension",
        "domains",
        "parent",
        "children",
        "dataProducts",
        "followers",
        "experts",
        "reviewers",
        "assets",
        "glossary",
        "synonyms",
        "users",
        "votes",
    }
)

# The metadata types a stock OpenMetadata ships with that this adapter touches.
BUILTIN_TYPES: tuple[str, ...] = ("container", "dataProduct", "string")

_NAME_ROUTE = re.compile(r"^(?P<collection>.+)/name/(?P<fqn>[^/]+)(?P<tail>/.*)?$")
_TYPES_BY_NAME = re.compile(r"^/api/v1/metadata/types/name/(?P<name>[^/]+)$")
_TYPES_BY_ID = re.compile(r"^/api/v1/metadata/types/(?P<id>[0-9a-f-]{36})$")
_LINEAGE_BY_NAME = re.compile(r"^/api/v1/lineage/(?P<kind>[^/]+)/name/(?P<fqn>[^/]+)$")


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


@dataclass
class FakeOpenMetadata:
    """The catalogue's state, plus the knobs that make it misbehave."""

    # {(entity_type, fqn): stored document}
    entities: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    # {om entity type: {property name: CustomProperty}}
    custom_properties: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    # {data product fqn: [asset uuid]}
    assets: dict[str, list[str]] = field(default_factory=dict)
    # {(from uuid, to uuid)}
    lineage: set[tuple[str, str]] = field(default_factory=set)
    # {name: uuid} for the stock metadata types.
    type_ids: dict[str, str] = field(default_factory=dict)
    # {uuid: (entity_type, fqn)}
    by_id: dict[str, tuple[str, str]] = field(default_factory=dict)

    # -- traffic, for assertions ------------------------------------------
    requests: list[tuple[str, str, Any]] = field(default_factory=list)
    auth_headers: list[str | None] = field(default_factory=list)

    # -- perturbation knobs -----------------------------------------------
    #: Entities to refuse to return: {(entity_type, fqn)}.
    drop: set[tuple[str, str]] = field(default_factory=set)
    #: Field overwrites applied after ingestion: {(entity_type, fqn): {field: value}}.
    mutate: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    #: Whole entities to invent: {(entity_type, fqn): document}.
    inject_entities: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    #: Asset FQNs to invent on a data product: {dp fqn: [asset fqn]}.
    inject_assets: dict[str, list[str]] = field(default_factory=dict)
    #: Asset FQNs to withhold: {dp fqn: [asset fqn]}.
    drop_assets: dict[str, list[str]] = field(default_factory=dict)
    #: Lineage edges to invent or withhold, as FQN pairs.
    inject_lineage: set[tuple[str, str]] = field(default_factory=set)
    drop_lineage: set[tuple[str, str]] = field(default_factory=set)
    #: Custom properties to invent: {om entity type: [name]}.
    inject_properties: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in BUILTIN_TYPES:
            self.type_ids.setdefault(name, str(uuid.uuid5(uuid.NAMESPACE_URL, f"type:{name}")))
            self.custom_properties.setdefault(name, {})

    # ------------------------------------------------------------- helpers

    def _identifier(self, entity_type: str, fqn: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{entity_type}:{fqn}"))

    def _existing(self, entity_type: str, fqn: str) -> dict[str, Any] | None:
        return self.entities.get((entity_type, fqn))

    def _reference(self, entity_type: str, fqn: str) -> dict[str, Any]:
        document = self._existing(entity_type, fqn)
        identifier = document["id"] if document else self._identifier(entity_type, fqn)
        return {
            "id": identifier,
            "type": entity_type,
            "name": fqn.rsplit(".", 1)[-1],
            "fullyQualifiedName": fqn,
            "deleted": False,
            "href": f"http://fake/api/v1/{entity_type}/{identifier}",
        }

    def _require_exists(self, entity_type: str, fqn: str, why: str) -> None:
        if (entity_type, fqn) not in self.entities:
            raise RequestError(
                400,
                f"{why}: {entity_type} '{fqn}' does not exist. OpenMetadata resolves "
                "references at write time, so it must be created first.",
            )

    # ------------------------------------------------------------ validation

    def _validate_create(self, entity_type: str, body: Any) -> dict[str, Any]:
        """Validate one Create<Entity> body against the vendored upstream schema."""
        if not isinstance(body, dict):
            raise RequestError(400, "request body must be a JSON object")
        schema = _load_schema(CREATE_SCHEMAS[entity_type])
        allowed = set(schema.get("properties", {}))
        required = set(schema.get("required", []))
        missing = sorted(required - set(body))
        if missing:
            raise RequestError(400, f"create{entity_type} is missing required: {missing}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(body) - allowed)
            if unknown:
                raise RequestError(
                    400,
                    f"create{entity_type} does not accept {unknown} (additionalProperties: false)",
                )
        return dict(body)

    def _fqn_for(self, entity_type: str, body: dict[str, Any]) -> str:
        """Compute the FQN the server would assign, the way OpenMetadata does."""
        name = str(body["name"])
        if entity_type == "tag":
            return f"{body.get('classification')}.{name}"
        if entity_type == "glossaryTerm":
            parent = body.get("parent")
            return f"{parent or body.get('glossary')}.{name}"
        if entity_type == "container":
            parent = body.get("parent")
            if isinstance(parent, dict):
                owner = self.by_id.get(str(parent.get("id")))
                if owner is None:
                    raise RequestError(400, "parent reference names an unknown entity")
                return f"{owner[1]}.{name}"
            return f"{body.get('service')}.{name}"
        if entity_type == "dataProduct":
            domains = body.get("domains") or []
            if not domains:
                raise RequestError(400, "createDataProduct requires a domain")
            return f"{domains[0]}.{name}"
        return name

    def _check_references(self, entity_type: str, body: dict[str, Any]) -> None:
        """Refuse a body naming something the catalogue does not yet hold."""
        for field_name, target_type in (
            ("service", "storageService"),
            ("glossary", "glossary"),
            ("classification", "classification"),
        ):
            value = body.get(field_name)
            if isinstance(value, str):
                self._require_exists(target_type, value, f"{entity_type}.{field_name}")
        for value in body.get("domains") or []:
            if isinstance(value, str):
                self._require_exists("domain", value, f"{entity_type}.domains")
        for label in body.get("tags") or []:
            if not isinstance(label, dict):
                raise RequestError(400, "each tag must be a TagLabel object")
            for key in ("tagFQN", "source", "labelType", "state"):
                if key not in label:
                    raise RequestError(400, f"TagLabel is missing required '{key}'")
            source = label.get("source")
            target = "glossaryTerm" if source == "Glossary" else "tag"
            self._require_exists(target, str(label["tagFQN"]), f"{entity_type}.tags")
        for key in ("parent", "owners", "experts", "reviewers"):
            value = body.get(key)
            items = value if isinstance(value, list) else [value] if value else []
            for item in items:
                if isinstance(item, dict):
                    if str(item.get("id")) not in self.by_id:
                        raise RequestError(400, f"{entity_type}.{key} names an unknown entity id")
                elif isinstance(item, str):
                    raise RequestError(
                        400,
                        f"{entity_type}.{key} must be an EntityReference object, not an FQN "
                        "string; OpenMetadata resolves this field by id",
                    )

    def _check_extension(self, entity_type: str, body: dict[str, Any]) -> None:
        extension = body.get("extension")
        if extension is None:
            return
        if not isinstance(extension, dict):
            raise RequestError(400, "extension must be an object")
        registered = self.custom_properties.get(entity_type, {})
        unknown = sorted(set(extension) - set(registered))
        if unknown:
            raise RequestError(
                400,
                f"extension uses unregistered custom propert(ies) {unknown} on type "
                f"'{entity_type}'. Register them against the type first.",
            )

    # --------------------------------------------------------------- writes

    def put_entity(self, entity_type: str, body: Any) -> dict[str, Any]:
        create = self._validate_create(entity_type, body)
        self._check_references(entity_type, create)
        self._check_extension(entity_type, create)
        fqn = self._fqn_for(entity_type, create)

        existing = self._existing(entity_type, fqn)
        identifier = existing["id"] if existing else self._identifier(entity_type, fqn)
        version = round((existing["version"] if existing else 0.0) + 0.1, 1)

        document: dict[str, Any] = {
            key: value for key, value in create.items() if key not in {"parent", "owners"}
        }
        # References are stored expanded, the way OpenMetadata answers them.
        for key in ("service", "glossary", "classification"):
            if isinstance(create.get(key), str):
                target = {
                    "service": "storageService",
                    "glossary": "glossary",
                    "classification": "classification",
                }[key]
                document[key] = self._reference(target, str(create[key]))
        if create.get("domains"):
            document["domains"] = [
                self._reference("domain", str(item)) for item in create["domains"]
            ]
        for key in ("parent", "owners", "experts", "reviewers"):
            value = create.get(key)
            if isinstance(value, dict):
                kind, target_fqn = self.by_id[str(value["id"])]
                document[key] = self._reference(kind, target_fqn)
            elif isinstance(value, list):
                resolved = []
                for item in value:
                    kind, target_fqn = self.by_id[str(item["id"])]
                    resolved.append(self._reference(kind, target_fqn))
                document[key] = resolved

        document.update(
            {
                "id": identifier,
                "fullyQualifiedName": fqn,
                "version": version,
                "updatedAt": 1_700_000_000_000,
                "updatedBy": "fake-openmetadata",
                "href": f"http://fake/api/v1/{entity_type}/{identifier}",
                "deleted": False,
                "changeDescription": {"fieldsAdded": [], "fieldsUpdated": []},
            }
        )
        if entity_type == "container":
            service = create.get("service")
            document["serviceType"] = "CustomStorage" if service else None
            document["children"] = []

        self.entities[(entity_type, fqn)] = document
        self.by_id[identifier] = (entity_type, fqn)

        # Maintain the server-derived children list on the parent.
        if entity_type == "container" and isinstance(create.get("parent"), dict):
            kind, parent_fqn = self.by_id[str(create["parent"]["id"])]
            parent_doc = self.entities.get((kind, parent_fqn))
            if parent_doc is not None:
                children = parent_doc.setdefault("children", [])
                if all(child.get("fullyQualifiedName") != fqn for child in children):
                    children.append(self._reference(entity_type, fqn))
        return document

    def put_custom_property(self, type_id: str, body: Any) -> None:
        name = next((n for n, i in self.type_ids.items() if i == type_id), None)
        if name is None:
            raise RequestError(404, "no such metadata type")
        if not isinstance(body, dict):
            raise RequestError(400, "request body must be a CustomProperty object")
        schema = _load_schema("api/data/createCustomProperty.json")
        missing = sorted(set(schema.get("required", [])) - set(body))
        if missing:
            raise RequestError(400, f"CustomProperty is missing required: {missing}")
        unknown = sorted(set(body) - set(schema.get("properties", {})))
        if schema.get("additionalProperties") is False and unknown:
            raise RequestError(400, f"CustomProperty does not accept {unknown}")
        property_type = body.get("propertyType")
        if not isinstance(property_type, dict) or "id" not in property_type:
            raise RequestError(
                400,
                "CustomProperty.propertyType must be an EntityReference with an id; "
                "OpenMetadata does not accept a bare type name here",
            )
        if str(property_type["id"]) not in self.type_ids.values():
            raise RequestError(400, "propertyType names an unknown metadata type")
        self.custom_properties.setdefault(name, {})[str(body["name"])] = dict(body)

    def add_assets(self, fqn: str, body: Any) -> dict[str, Any]:
        if ("dataProduct", fqn) not in self.entities:
            raise RequestError(404, f"no such data product '{fqn}'")
        if not isinstance(body, dict) or not isinstance(body.get("assets"), list):
            raise RequestError(400, "request body must be BulkAssets: {'assets': [...]}")
        added = 0
        for item in body["assets"]:
            if not isinstance(item, dict) or "id" not in item:
                raise RequestError(400, "each asset must be an EntityReference with an id")
            identifier = str(item["id"])
            if identifier not in self.by_id:
                raise RequestError(400, "asset names an unknown entity id")
            self.assets.setdefault(fqn, [])
            if identifier not in self.assets[fqn]:
                self.assets[fqn].append(identifier)
                added += 1
        return {"dryRun": False, "status": "success", "numberOfRowsPassed": added}

    def add_lineage(self, body: Any) -> None:
        if not isinstance(body, dict) or not isinstance(body.get("edge"), dict):
            raise RequestError(400, "request body must be AddLineage: {'edge': {...}}")
        edge = body["edge"]
        ends = []
        for side in ("fromEntity", "toEntity"):
            reference = edge.get(side)
            if not isinstance(reference, dict) or "id" not in reference:
                raise RequestError(400, f"edge.{side} must be an EntityReference with an id")
            identifier = str(reference["id"])
            if identifier not in self.by_id:
                raise RequestError(400, f"edge.{side} names an unknown entity id")
            ends.append(identifier)
        self.lineage.add((ends[0], ends[1]))

    # ---------------------------------------------------------------- reads

    def _project(self, document: dict[str, Any], fields: set[str]) -> dict[str, Any]:
        """Withhold opt-in fields the caller did not ask for."""
        return {
            key: value
            for key, value in document.items()
            if key not in OPT_IN_FIELDS or key in fields
        }

    def get_entity(self, entity_type: str, fqn: str, fields: set[str]) -> dict[str, Any] | None:
        if (entity_type, fqn) in self.drop:
            return None
        injected = self.inject_entities.get((entity_type, fqn))
        document = self.entities.get((entity_type, fqn), injected)
        if document is None:
            return None
        document = dict(document)
        document.update(self.mutate.get((entity_type, fqn), {}))
        return self._project(document, fields)

    def get_type(self, name: str, fields: set[str]) -> dict[str, Any] | None:
        identifier = self.type_ids.get(name)
        if identifier is None:
            return None
        document: dict[str, Any] = {"id": identifier, "name": name}
        if "customProperties" in fields:
            declared = dict(self.custom_properties.get(name, {}))
            for extra in self.inject_properties.get(name, []):
                declared[extra] = {"name": extra, "description": "injected"}
            document["customProperties"] = list(declared.values())
        return document

    def get_assets(self, fqn: str) -> dict[str, Any] | None:
        if ("dataProduct", fqn) not in self.entities:
            return None
        withheld = set(self.drop_assets.get(fqn, []))
        data = [
            self._reference(*self.by_id[identifier])
            for identifier in self.assets.get(fqn, [])
            if self.by_id[identifier][1] not in withheld
        ]
        for extra in self.inject_assets.get(fqn, []):
            data.append(self._reference("container", extra))
        return {"data": data, "paging": {"total": len(data)}}

    def get_lineage(self, fqn: str) -> dict[str, Any] | None:
        if ("container", fqn) not in self.entities:
            return None
        edges = {
            pair for pair in self.lineage if fqn in (self.by_id[pair[0]][1], self.by_id[pair[1]][1])
        }
        pairs = [
            pair
            for pair in edges
            if (self.by_id[pair[0]][1], self.by_id[pair[1]][1]) not in self.drop_lineage
        ]
        nodes: dict[str, dict[str, Any]] = {}
        rendered: list[dict[str, str]] = []
        for source, target in sorted(pairs):
            for identifier in (source, target):
                nodes[identifier] = self._reference(*self.by_id[identifier])
            rendered.append({"fromEntity": source, "toEntity": target})
        for source_fqn, target_fqn in sorted(self.inject_lineage):
            source_ref = self._reference("container", source_fqn)
            target_ref = self._reference("container", target_fqn)
            nodes[source_ref["id"]] = source_ref
            nodes[target_ref["id"]] = target_ref
            rendered.append({"fromEntity": source_ref["id"], "toEntity": target_ref["id"]})
        return {
            "entity": self._reference("container", fqn),
            "nodes": list(nodes.values()),
            "upstreamEdges": rendered,
            "downstreamEdges": [],
        }

    def list_entities(self, entity_type: str, query: dict[str, list[str]]) -> dict[str, Any]:
        data: list[dict[str, Any]] = []
        for (kind, fqn), document in sorted(self.entities.items()):
            if kind != entity_type:
                continue
            if entity_type == "container" and "service" in query:
                service = document.get("service")
                name = service.get("fullyQualifiedName") if isinstance(service, dict) else None
                if name != query["service"][0]:
                    continue
            if entity_type == "tag" and "parent" in query:
                classification = document.get("classification")
                name = (
                    classification.get("fullyQualifiedName")
                    if isinstance(classification, dict)
                    else None
                )
                if name != query["parent"][0]:
                    continue
            data.append({"id": document["id"], "fullyQualifiedName": fqn, "name": document["name"]})
        for (kind, fqn), _document in sorted(self.inject_entities.items()):
            if kind == entity_type and (kind, fqn) not in self.entities:
                data.append({"id": self._identifier(kind, fqn), "fullyQualifiedName": fqn})
        return {"data": data, "paging": {"total": len(data)}}

    def reset_traffic(self) -> None:
        self.requests.clear()
        self.auth_headers.clear()


def _handler_for(state: FakeOpenMetadata) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # noqa: A002 - silence the test log
            return

        def _respond(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> Any:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return None
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RequestError(400, "request body is not JSON") from exc

        def _dispatch(self, method: str) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            query = urllib.parse.parse_qs(parsed.query)
            body = self._body()
            state.requests.append((method, self.path, body))
            state.auth_headers.append(self.headers.get("Authorization"))

            fields = set((query.get("fields", [""])[0] or "").split(",")) - {""}

            # -- metadata types ------------------------------------------
            match = _TYPES_BY_ID.match(path)
            if match:
                if method != "PUT":
                    raise RequestError(405, f"{method} is not allowed on a metadata type")
                state.put_custom_property(match.group("id"), body)
                self._respond({"status": "ok"})
                return
            match = _TYPES_BY_NAME.match(path)
            if match:
                if method != "GET":
                    raise RequestError(405, f"{method} is not allowed here")
                document = state.get_type(match.group("name"), fields)
                if document is None:
                    raise RequestError(404, "no such metadata type")
                self._respond(document)
                return

            # -- lineage ---------------------------------------------------
            if path == "/api/v1/lineage":
                if method != "PUT":
                    raise RequestError(405, "lineage is written with PUT, not " + method)
                state.add_lineage(body)
                self._respond({"status": "ok"})
                return
            match = _LINEAGE_BY_NAME.match(path)
            if match:
                if method != "GET":
                    raise RequestError(405, f"{method} is not allowed here")
                document = state.get_lineage(match.group("fqn"))
                if document is None:
                    raise RequestError(404, "no lineage for that entity")
                self._respond(document)
                return

            # -- data-product assets --------------------------------------
            match = _NAME_ROUTE.match(path)
            if match and match.group("tail") in {"/assets/add", "/assets"}:
                collection = COLLECTION_ROUTES.get(match.group("collection"))
                if collection != "dataProduct":
                    raise RequestError(404, "asset attachment exists on data products only")
                fqn = match.group("fqn")
                if match.group("tail") == "/assets/add":
                    if method != "PUT":
                        raise RequestError(405, "assets are attached with PUT, not " + method)
                    self._respond(state.add_assets(fqn, body))
                    return
                if method != "GET":
                    raise RequestError(405, f"{method} is not allowed here")
                document = state.get_assets(fqn)
                if document is None:
                    raise RequestError(404, "no such data product")
                self._respond(document)
                return

            # -- entity by name --------------------------------------------
            if match and not match.group("tail"):
                collection = COLLECTION_ROUTES.get(match.group("collection"))
                if collection is None:
                    raise RequestError(404, f"unknown collection {match.group('collection')!r}")
                if method != "GET":
                    raise RequestError(405, f"{method} is not allowed on /name/{{fqn}}")
                document = state.get_entity(collection, match.group("fqn"), fields)
                if document is None:
                    raise RequestError(404, "no such entity")
                self._respond(document)
                return

            # -- entity collection -----------------------------------------
            collection = COLLECTION_ROUTES.get(path)
            if collection is not None:
                if method == "PUT":
                    self._respond(state.put_entity(collection, body))
                    return
                if method == "GET":
                    self._respond(state.list_entities(collection, query))
                    return
                raise RequestError(
                    405,
                    f"{method} is not how OpenMetadata performs create-or-update on {path}; PUT is",
                )

            raise RequestError(404, f"no route for {path}")

        def _guard(self, method: str) -> None:
            try:
                self._dispatch(method)
            except RequestError as exc:
                self._respond({"code": exc.status, "message": str(exc)}, status=exc.status)
            except Exception as exc:  # pragma: no cover - defensive
                self._respond({"code": 500, "message": repr(exc)}, status=500)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
            self._guard("GET")

        def do_PUT(self) -> None:  # noqa: N802
            self._guard("PUT")

        def do_POST(self) -> None:  # noqa: N802
            self._guard("POST")

        def do_PATCH(self) -> None:  # noqa: N802
            self._guard("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._guard("DELETE")

    return Handler


class FakeOpenMetadataServer:
    """A running :class:`FakeOpenMetadata` on a loopback port."""

    def __init__(self, state: FakeOpenMetadata | None = None) -> None:
        self.state = state or FakeOpenMetadata()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self.state))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def host_port(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/api"

    def __enter__(self) -> FakeOpenMetadataServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


__all__ = [
    "COLLECTION_ROUTES",
    "CREATE_SCHEMAS",
    "OPT_IN_FIELDS",
    "BUILTIN_TYPES",
    "RequestError",
    "FakeOpenMetadata",
    "FakeOpenMetadataServer",
]
