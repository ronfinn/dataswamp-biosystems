"""The only OpenMetadata module in this project that opens a socket.

Every concrete OpenMetadata endpoint path, HTTP verb, request envelope and
response shape lives here. Nothing in :mod:`ingest`, :mod:`readback`,
:mod:`normalize`, :mod:`roundtrip` or :mod:`report` knows a URL exists — they
speak in plan records, fully-qualified names and entity payloads. When a real
OpenMetadata release moves an endpoint, exactly one file changes.

**Standard library only.** No ``openmetadata-ingestion``, no ``requests``, no
``httpx``. See ``docs/adr/0007-no-catalogue-client-dependency.md``.

**Credentials come from the environment and nowhere else.** The JWT is never a
CLI argument, never rendered by :meth:`OpenMetadataClient.__repr__`, never
interpolated into an exception and never written to a file.

**No compatibility is claimed.** :data:`LIVE_SUPPORT` says so, and it is written
into every round-trip report, so a stored report cannot outlive its evidence.
Everything below was read from OpenMetadata's own JAX-RS resource classes at the
revision pinned by
:data:`~dataswamp_biosystems.adapters.openmetadata.mapping.OPENMETADATA_SCHEMA_COMMIT`
(the ``1.13.3-release`` tree). *Reading a resource class is not running against a
server*: this module has never exchanged a byte with a real OpenMetadata, and
:data:`~dataswamp_biosystems.adapters.openmetadata.mapping.VERIFIED_OPENMETADATA_VERSION`
stays ``None`` until it has.

Verified upstream contract
--------------------------
Every path below is a class-level ``@Path`` plus a method ``@Path`` taken
verbatim from that tree. OpenMetadata serves its JAX-RS application under the
``/api`` root, so the wire path is ``/api`` + the resource path.

===============================  =========================================================
Operation                        Upstream contract
===============================  =========================================================
create-or-update an entity       ``PUT /api/v1/<collection>`` with a ``Create<Entity>``
                                 body. Every entity resource DataSwamp emits has this
                                 method (``ContainerResource``, ``DomainResource``,
                                 ``DataProductResource``, ``TeamResource``,
                                 ``GlossaryResource``, ``GlossaryTermResource``,
                                 ``ClassificationResource``, ``TagResource``,
                                 ``StorageServiceResource``). ``POST`` is create-only and
                                 conflicts on re-run, so ``PUT`` is what makes a second
                                 ingestion idempotent.
read an entity by FQN            ``GET /api/v1/<collection>/name/{fqn}``. Present on every
                                 collection above. This is why DataSwamp's identity is the
                                 FQN and never the server's UUID.
enumerate a collection           ``GET /api/v1/<collection>`` with ``fields``, ``limit``
                                 and ``after`` (cursor). ``ContainerResource`` additionally
                                 accepts ``service`` and ``root``; ``TagResource`` accepts
                                 ``parent``. Those two filters are the reason container and
                                 tag containment can be proved rather than guessed.
register a custom property       ``GET /api/v1/metadata/types/name/{entityType}`` to learn
                                 the *type's* server-assigned UUID, then
                                 ``PUT /api/v1/metadata/types/{id}`` with a
                                 ``CustomProperty`` body (``TypeResource.addProperty``).
                                 There is no FQN-addressed form of the write, so the
                                 lookup is mandatory, not an optimisation.
read registered properties       ``GET /api/v1/metadata/types/name/{entityType}
                                 ?fields=customProperties``.
attach data-product assets       ``PUT /api/v1/dataProducts/name/{fqn}/assets/add`` with a
                                 ``BulkAssets`` body, answering ``BulkOperationResult``.
read data-product assets         ``GET /api/v1/dataProducts/name/{fqn}/assets``.
write lineage                    ``PUT /api/v1/lineage`` with an ``AddLineage`` body whose
                                 ``edge.fromEntity`` / ``edge.toEntity`` are
                                 ``EntityReference`` values — which carry a UUID, so both
                                 endpoints must be resolved by FQN first.
read lineage                     ``GET /api/v1/lineage/{entity}/name/{fqn}``.
===============================  =========================================================

Two consequences shape the rest of the live path.

**A UUID is unavoidable on exactly three writes** — custom-property registration,
data-product asset attachment and lineage — because OpenMetadata's request bodies
take an ``EntityReference`` there and an ``EntityReference`` is keyed by ``id``.
This module resolves each one by looking the FQN up first. That is transport
encoding, not remapping: the emitted plan already declares those targets as
:class:`~dataswamp_biosystems.adapters.openmetadata.mapping.Reference` blocks
precisely because an offline export cannot know a UUID. A resolved UUID is never
retained as DataSwamp identity.

**The emitted ``endpoint`` annotation is not consulted.** Plan records carry an
``endpoint`` string from the offline export, but this module ignores it and uses
the table above. A path is a live-transport fact, so it belongs here and is
verified here; trusting a string carried in a data file would put the endpoint
contract outside the one module that owns it. (It also means a stale annotation
in an emitted export cannot mis-address a request — see ``docs/openmetadata.md``,
which records one such annotation.)
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

from dataswamp_biosystems.adapters.openmetadata.errors import (
    OpenMetadataConfigError,
    OpenMetadataTransportError,
)

# Environment variables, and the only accepted source of each. The names are
# OpenMetadata's own: its ingestion configuration calls the server address
# ``hostPort`` and its bearer credential a ``jwtToken``, so a user who has
# configured OpenMetadata anywhere else already knows these.
HOST_PORT_ENV = "OPENMETADATA_HOST_PORT"
JWT_TOKEN_ENV = "OPENMETADATA_JWT_TOKEN"

# OpenMetadata serves its whole JAX-RS application under this root.
API_ROOT = "/api"

# How much of OpenMetadata's live API this adapter claims to have verified:
# none of it. The contract above was read from upstream source, which is
# evidence about the *shape* of a request and nothing at all about a running
# server. Written into every round-trip report.
LIVE_SUPPORT = (
    "unverified: request shapes were read from the OpenMetadata 1.13.3-release "
    "resource classes, but this project has never exchanged a byte with a running "
    "OpenMetadata instance and claims no compatibility point"
)

# --------------------------------------------------------------------------
# Endpoints. Nothing outside this module may name one.
# --------------------------------------------------------------------------
# Entity collections, keyed by the plan's entity type. The value is the resource
# path under :data:`API_ROOT`; ``PUT`` on it is create-or-update and
# ``GET {path}/name/{fqn}`` reads one back.
COLLECTIONS: dict[str, str] = {
    "classification": "/v1/classifications",
    "tag": "/v1/tags",
    "glossary": "/v1/glossaries",
    "glossaryTerm": "/v1/glossaryTerms",
    "team": "/v1/teams",
    "domain": "/v1/domains",
    "storageService": "/v1/services/storageServices",
    "container": "/v1/containers",
    "dataProduct": "/v1/dataProducts",
}

# ``TypeResource``. Custom-property registration is a write against the *type*,
# addressed by the type's UUID, so it does not fit the collection table above.
TYPES_PATH = "/v1/metadata/types"

# ``LineageResource``.
LINEAGE_PATH = "/v1/lineage"

# The ``entityReference.type`` discriminator OpenMetadata expects for each of the
# entity types this adapter resolves references to. It is the entity's type name,
# not its collection path, and the two differ (``storageService`` lives at
# ``/v1/services/storageServices``), so it is written out rather than derived.
REFERENCE_TYPES: dict[str, str] = {
    "classification": "classification",
    "tag": "tag",
    "glossary": "glossary",
    "glossaryTerm": "glossaryTerm",
    "team": "team",
    "domain": "domain",
    "storageService": "storageService",
    "container": "container",
    "dataProduct": "dataProduct",
    # ``metadata/types`` entries, referenced by a custom property's ``propertyType``.
    "type": "type",
}

# The ``fields`` each collection must be asked for so a readback can actually see
# what DataSwamp sent. OpenMetadata returns a *lean* entity by default: ``owners``,
# ``tags``, ``extension``, ``domains`` and ``parent`` are all opt-in. Omitting one
# would make a sent value look absent, which is the failure mode most likely to be
# mistaken for a server bug — so every field the mapping can write is requested.
READ_FIELDS: dict[str, tuple[str, ...]] = {
    "classification": ("owners",),
    "tag": ("owners",),
    "glossary": ("owners", "tags", "domains"),
    "glossaryTerm": ("owners", "tags", "parent", "glossary", "domains", "synonyms"),
    "team": ("owners", "users", "domains"),
    "domain": ("owners", "tags", "parent", "experts"),
    "storageService": ("owners", "tags", "domains"),
    "container": (
        "owners",
        "tags",
        "extension",
        "domains",
        "parent",
        "dataProducts",
        "followers",
    ),
    "dataProduct": ("owners", "tags", "extension", "domains", "experts", "assets"),
}

# A page size well above the benchmark's own estate, and a hard page cap so an
# enumeration against a large third-party instance cannot run unbounded.
LIST_PAGE_SIZE = 200
MAX_LIST_PAGES = 200

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.5


def redact_url(url: str) -> str:
    """Return ``url`` with embedded credentials and the query string removed.

    A host-port value can legitimately carry userinfo
    (``https://user:secret@host/``) and a query string can carry a token. The
    round-trip report records which server it talked to, so the recorded value
    must be safe to publish, paste into an issue and commit.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:  # pragma: no cover - defensive
        return "<unparseable>"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _quote_fqn(fqn: str) -> str:
    """Percent-encode one FQN for use as a single path segment.

    ``safe=""`` is deliberate. DataSwamp FQNs are built from ``[a-z0-9~-]`` plus
    ``.`` by :mod:`~dataswamp_biosystems.adapters.openmetadata.fqn`, so nothing
    here *should* need escaping — but the encoding is applied anyway rather than
    assumed away, because the observed graph is allowed to hold values the truth
    models forbid and an identity that reached this point unescaped would address
    the wrong entity rather than fail.
    """
    return urllib.parse.quote(fqn, safe="")


class OpenMetadataClient:
    """A minimal OpenMetadata REST client over :mod:`urllib.request`.

    Constructed through :meth:`from_environment`; the direct constructor exists
    for tests, which pass a token explicitly rather than mutating the process
    environment.
    """

    def __init__(
        self,
        host_port: str,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self.base = self._normalise_base(host_port)
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        # Private, and deliberately never exposed on a public attribute, in a
        # repr, or in an exception message.
        self._token = token
        # FQN -> UUID, for the three writes whose bodies need an EntityReference.
        # A cache, never an identity: nothing outside this module ever sees it.
        self._ids: dict[tuple[str, str], str] = {}

    @staticmethod
    def _normalise_base(host_port: str) -> str:
        """Return the server root, with any trailing ``/`` or ``/api`` removed.

        OpenMetadata's own ingestion configuration writes ``hostPort`` as
        ``http://localhost:8585/api``, so users arrive with the ``/api`` suffix
        already attached — while the paths in this module include it. Accepting
        both spellings and normalising here is friendlier than rejecting one, and
        it keeps exactly one representation inside the client.
        """
        base = host_port.strip().rstrip("/")
        if base.endswith(API_ROOT):
            base = base[: -len(API_ROOT)]
        return base

    @classmethod
    def from_environment(cls, **kwargs: Any) -> OpenMetadataClient:
        """Build a client from ``OPENMETADATA_HOST_PORT`` / ``OPENMETADATA_JWT_TOKEN``.

        The host is required; the token is optional, because a locally-run
        instance with authentication disabled is a legitimate target and
        demanding a token there would push users towards inventing one.
        """
        host_port = os.environ.get(HOST_PORT_ENV, "").strip()
        if not host_port:
            raise OpenMetadataConfigError(
                f"{HOST_PORT_ENV} is not set. The OpenMetadata address and JWT are read "
                f"from the environment only — the token is never accepted as a "
                f"command-line argument."
            )
        token = os.environ.get(JWT_TOKEN_ENV, "").strip() or None
        return cls(host_port, token, **kwargs)

    @property
    def endpoint(self) -> str:
        """The server address, safe to record in a report or print to a terminal."""
        return redact_url(self.base)

    def __repr__(self) -> str:
        return (
            f"OpenMetadataClient(host_port={self.endpoint!r}, "
            f"authenticated={self._token is not None})"
        )

    # ----------------------------------------------------------------- HTTP

    def _request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        allow_404: bool = False,
    ) -> Any:
        """Issue one request, retrying transient failures a bounded number of times.

        ``allow_404`` turns a definitive "no such entity" into ``None`` rather
        than an error, because *absent* is a legitimate readback answer and is
        precisely what the completeness claim needs to see. Every other 4xx is
        final and is raised immediately: repeating a request the server has
        already judged malformed or unauthorised cannot change the answer.
        """
        url = f"{self.base}{API_ROOT}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and allow_404:
                    return None
                if exc.code < 500:
                    raise OpenMetadataTransportError(
                        f"{method} {redact_url(url)} returned HTTP {exc.code}", status=exc.code
                    ) from exc
                last = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
            except json.JSONDecodeError as exc:
                raise OpenMetadataTransportError(
                    f"{method} {redact_url(url)} returned a body that is not JSON"
                ) from exc
            if attempt < self.retries:
                time.sleep(self.backoff * (2**attempt))

        status = getattr(last, "code", None)
        raise OpenMetadataTransportError(
            f"{method} {redact_url(url)} could not be reached after {self.retries + 1} attempt(s)",
            status=status if isinstance(status, int) else None,
        )

    @staticmethod
    def _collection(entity_type: str) -> str:
        try:
            return COLLECTIONS[entity_type]
        except KeyError as exc:
            raise OpenMetadataConfigError(
                f"no OpenMetadata collection is known for entity type {entity_type!r}; "
                "this transport refuses to guess a path"
            ) from exc

    # ---------------------------------------------------------------- Writes

    def create_or_update(self, entity_type: str, create: dict[str, Any]) -> dict[str, Any]:
        """``PUT`` one ``Create<Entity>`` body to its collection.

        **The body is transmitted exactly as the export emitted it.** Nothing is
        added, removed, renamed, reordered or coerced here; the only thing this
        method contributes is the path and the verb. That is what lets the
        round-trip treat the emitted file as an authoritative statement of what
        the catalogue should hold — if the transport could adjust a payload,
        "the server matches what we sent" would be comparing a computation
        against itself.
        """
        body = self._request("PUT", self._collection(entity_type), create)
        return body if isinstance(body, dict) else {}

    def resolve_id(self, entity_type: str, fqn: str) -> str:
        """Return the server-assigned UUID for one FQN, looking it up if needed.

        Needed only where OpenMetadata's *request body* takes an
        ``EntityReference``. The result is cached for the life of the client and
        never leaves this module: DataSwamp identity is the FQN, and a UUID that
        escaped into a report or a comparison would make the benchmark's identity
        depend on which server it happened to be loaded into.
        """
        key = (entity_type, fqn)
        cached = self._ids.get(key)
        if cached is not None:
            return cached
        entity = self.get_by_name(entity_type, fqn)
        if entity is None:
            raise OpenMetadataTransportError(
                f"cannot resolve a reference to {entity_type} {fqn!r}: the catalogue does "
                "not hold it. The emitted plan orders every reference after its target, so "
                "this means an earlier operation did not materialise."
            )
        identifier = entity.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise OpenMetadataTransportError(
                f"{entity_type} {fqn!r} was returned without a server-assigned id"
            )
        self._ids[key] = identifier
        return identifier

    def entity_reference(self, entity_type: str, fqn: str) -> dict[str, Any]:
        """Return the ``EntityReference`` OpenMetadata requires for ``fqn``."""
        return {
            "id": self.resolve_id(entity_type, fqn),
            "type": REFERENCE_TYPES.get(entity_type, entity_type),
        }

    def register_custom_property(self, entity_type: str, custom_property: dict[str, Any]) -> None:
        """Register one custom property against an OpenMetadata *type*.

        Two lookups precede the write, both forced by upstream's contract rather
        than chosen: the target type's UUID (the write is ``PUT
        /v1/metadata/types/{id}``, which has no FQN-addressed form) and the
        property type's UUID (``CustomProperty.propertyType`` is an
        ``EntityReference``). Both are exactly the references the emitted plan
        declares as :data:`BUILTIN_REFERENCES`, which is why they are looked up
        rather than created.
        """
        type_id = self.resolve_type_id(entity_type)
        body = dict(custom_property)
        property_type = body.get("propertyType")
        if isinstance(property_type, str):
            body["propertyType"] = {
                "id": self.resolve_type_id(property_type),
                "type": REFERENCE_TYPES["type"],
            }
        self._request("PUT", f"{TYPES_PATH}/{urllib.parse.quote(type_id, safe='')}", body)

    def resolve_type_id(self, type_name: str) -> str:
        """Return the UUID of one entry in ``/v1/metadata/types``."""
        key = ("type", type_name)
        cached = self._ids.get(key)
        if cached is not None:
            return cached
        body = self._request("GET", f"{TYPES_PATH}/name/{_quote_fqn(type_name)}", allow_404=True)
        if not isinstance(body, dict) or not isinstance(body.get("id"), str):
            raise OpenMetadataTransportError(
                f"the catalogue does not define the metadata type {type_name!r}; "
                "custom-property registration cannot proceed"
            )
        identifier = str(body["id"])
        self._ids[key] = identifier
        return identifier

    def add_data_product_assets(self, fqn: str, assets: list[dict[str, Any]]) -> dict[str, Any]:
        """Attach assets to a data product by FQN (``BulkAssets``).

        The FQN-addressed form of the endpoint is used deliberately over the
        ``/{name}`` form: it is the one that takes the full hierarchical name,
        and it keeps this call keyed by the same identity everything else is.
        """
        path = f"{COLLECTIONS['dataProduct']}/name/{_quote_fqn(fqn)}/assets/add"
        body = self._request("PUT", path, {"assets": assets})
        return body if isinstance(body, dict) else {}

    def add_lineage(self, from_ref: dict[str, Any], to_ref: dict[str, Any]) -> None:
        """Write one lineage edge (``AddLineage``)."""
        self._request("PUT", LINEAGE_PATH, {"edge": {"fromEntity": from_ref, "toEntity": to_ref}})

    # ----------------------------------------------------------------- Reads

    def get_by_name(self, entity_type: str, fqn: str) -> dict[str, Any] | None:
        """Return one entity addressed by FQN, or ``None`` if the catalogue lacks it.

        Every field the mapping is capable of writing is requested — see
        :data:`READ_FIELDS`. A lean default response would make a value DataSwamp
        sent look absent, and "the server dropped it" and "we forgot to ask for
        it" are not the same finding.
        """
        path = f"{self._collection(entity_type)}/name/{_quote_fqn(fqn)}"
        fields = READ_FIELDS.get(entity_type, ())
        if fields:
            path += "?" + urllib.parse.urlencode({"fields": ",".join(fields)})
        body = self._request("GET", path, allow_404=True)
        return body if isinstance(body, dict) else None

    def get_custom_properties(self, entity_type: str) -> list[dict[str, Any]]:
        """Return the custom properties registered against one OpenMetadata type."""
        query = urllib.parse.urlencode({"fields": "customProperties"})
        path = f"{TYPES_PATH}/name/{_quote_fqn(entity_type)}?{query}"
        body = self._request("GET", path, allow_404=True)
        if not isinstance(body, dict):
            return []
        properties = body.get("customProperties")
        return [item for item in properties if isinstance(item, dict)] if properties else []

    def get_data_product_assets(self, fqn: str) -> list[dict[str, Any]] | None:
        """Return the assets attached to one data product, or ``None`` if it is absent."""
        path = f"{COLLECTIONS['dataProduct']}/name/{_quote_fqn(fqn)}/assets"
        body = self._request("GET", path, allow_404=True)
        if body is None:
            return None
        if not isinstance(body, dict):  # pragma: no cover - defensive
            return []
        data = body.get("data")
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def get_lineage(self, entity_type: str, fqn: str) -> dict[str, Any] | None:
        """Return the ``EntityLineage`` document for one entity, addressed by FQN."""
        kind = urllib.parse.quote(REFERENCE_TYPES.get(entity_type, entity_type), safe="")
        path = f"{LINEAGE_PATH}/{kind}/name/{_quote_fqn(fqn)}"
        body = self._request("GET", path, allow_404=True)
        return body if isinstance(body, dict) else None

    def list_entities(
        self, entity_type: str, params: dict[str, str] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield every entity in one collection, following the ``after`` cursor.

        ``params`` carries the server-side filters upstream actually offers —
        ``service`` for containers, ``parent`` for tags. They are the difference
        between *proving* DataSwamp ownership of an enumerated entity and
        guessing at it from a name prefix, which is why containment coverage is
        declared per entity family rather than claimed uniformly.
        """
        collection = self._collection(entity_type)
        after: str | None = None
        for _ in range(MAX_LIST_PAGES):
            query = dict(params or {})
            query["limit"] = str(LIST_PAGE_SIZE)
            if after:
                query["after"] = after
            body = self._request("GET", f"{collection}?{urllib.parse.urlencode(query)}")
            if not isinstance(body, dict):  # pragma: no cover - defensive
                return
            for entry in body.get("data", []) or []:
                if isinstance(entry, dict):
                    yield entry
            paging = body.get("paging")
            after = paging.get("after") if isinstance(paging, dict) else None
            if not after:
                return
        raise OpenMetadataTransportError(
            f"enumerating {entity_type} did not terminate within {MAX_LIST_PAGES} pages"
        )


__all__ = [
    "HOST_PORT_ENV",
    "JWT_TOKEN_ENV",
    "API_ROOT",
    "LIVE_SUPPORT",
    "COLLECTIONS",
    "TYPES_PATH",
    "LINEAGE_PATH",
    "REFERENCE_TYPES",
    "READ_FIELDS",
    "LIST_PAGE_SIZE",
    "MAX_LIST_PAGES",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_RETRIES",
    "DEFAULT_BACKOFF_SECONDS",
    "OpenMetadataClient",
    "redact_url",
]
