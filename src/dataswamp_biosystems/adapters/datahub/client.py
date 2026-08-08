"""The only module in this project that opens a socket.

Every concrete DataHub endpoint path, HTTP verb, request envelope and response
shape lives here. Nothing in :mod:`ingest`, :mod:`readback` or :mod:`roundtrip`
knows a URL exists — they speak in proposals, URNs and aspects. That isolation
is the point: when the live integration job pins a real DataHub release and
finds an endpoint has moved, exactly one file changes, and the ingestion,
comparison and reporting logic is untouched by it.

**Standard library only.** No ``acryl-datahub``, no ``requests``, no ``httpx``.
The two operations needed here are documented REST calls against payloads this
project already emits, and taking a catalogue client as a dependency — even an
optional one — would contradict the architectural premise of the package and
make the adapter's tests contingent on that tree resolving. See ADR 0005.

**Credentials come from the environment and nowhere else.** The token is never a
constructor argument the CLI can pass from ``argv``, never rendered by
:meth:`~DataHubClient.__repr__`, never interpolated into an exception, and never
written to any file. A token in ``argv`` leaks into shell history and process
listings; a token in an exception leaks into CI logs and issue reports.

**Compatibility is a point, not a range.** The offline
``DATAHUB_MODEL_VERSION`` range describes the emitted *payload* shape, which is
pinned by committed fixtures. It says nothing about these REST endpoints, which
are exercised against exactly one real release —
:data:`VERIFIED_DATAHUB_VERSION` — by the ``live-datahub`` workflow. Nothing is
claimed about any other release. :data:`LIVE_SUPPORT` records that status and is
written into every round-trip report, so a stored report never overstates its
evidence.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from dataswamp_biosystems.adapters.datahub.errors import (
    DataHubConfigError,
    DataHubTransportError,
)

# Environment variables, and the only accepted source of each.
GMS_URL_ENV = "DATAHUB_GMS_URL"
GMS_TOKEN_ENV = "DATAHUB_GMS_TOKEN"

# The one DataHub release these REST endpoints have actually been exercised
# against, by the `live-datahub` workflow. A *point*, not a range: nothing is
# claimed about any other release, and `tests/adapters/test_live_pin.py` fails if
# this and the workflow's pin ever disagree, so the claim cannot outlive the
# evidence for it.
VERIFIED_DATAHUB_VERSION = "v1.7.0"

# How much of DataHub's live API this adapter claims to have verified. Written
# into every round-trip report so a stored report never overstates its evidence.
LIVE_SUPPORT = (
    f"experimental: contract-level, verified against DataHub {VERIFIED_DATAHUB_VERSION} only"
)

# --------------------------------------------------------------------------
# Endpoints. Nothing outside this module may name one.
# --------------------------------------------------------------------------
# **One API family, end to end.** Reads and writes both go through OpenAPI v3.
#
# The first live run against a pinned release found this the hard way. Ingestion
# used to post to the rest.li ``/aspects?action=ingestProposalBatch``, which
# deserializes an aspect as ``GenericAspect`` — ``value`` as serialized bytes
# plus ``contentType``. The emitted payload writes aspects in the OpenAPI/JSON
# dialect (``{"aspect": {"json": ...}}``), so a real GMS answered HTTP 500 with
# ``RequiredFieldNotPresentException: Field "value" is required``, while the
# reads beside it — already OpenAPI v3 — were fine. Two dialects, mispaired.
#
# Mixing families is what made that possible, so the fix is not just a new path:
# every call below is OpenAPI v3, and none may be quietly swapped back.

# Cross-entity batched create/upsert. Chosen over the per-entity-type route
# because one batch can carry every entity type, which preserves the emitted
# order rather than forcing proposals to be regrouped by type before sending.
#
# ``async=false`` is not optional and not a tuning knob: the endpoint defaults to
# asynchronous ingestion, and reading back an asynchronously-accepted write is a
# race that would make the round-trip's completeness claim meaningless.
INGEST_PATH = "/openapi/v3/entity/generic?async=false"

# Versioned-aspect read. Returns the entity with each requested aspect wrapped in
# a ``{"value": ..., "systemMetadata": ...}`` envelope; the envelope is unwrapped
# below and the server-owned metadata is handled by the normalization contract.
ENTITY_PATH = "/openapi/v3/entity/{entity_type}/{urn}"

# Namespace enumeration, for extra-entity detection. Paged with a scroll token.
SCROLL_PATH = "/openapi/v3/entity/{entity_type}"

# Timeseries aspects have their own route, so they are fetched explicitly rather
# than assumed to appear alongside the versioned ones. The aspect segment is
# lower-cased, unlike the camel-case aspect name used everywhere else.
TIMESERIES_PATH = "/openapi/v3/entity/{entity_type}/{urn}/{aspect}"

# The change type this transport knows how to express. The emitted export is
# UPSERT throughout; anything else would need a different endpoint or verb, and
# silently posting it as an upsert would be exactly the reinterpretation this
# module promises not to perform.
SUPPORTED_CHANGE_TYPE = "UPSERT"

# Aspects this adapter emits that DataHub stores as timeseries rather than
# versioned. Handled explicitly so the round-trip covers every emitted aspect
# rather than a hand-picked subset.
TIMESERIES_ASPECTS: frozenset[str] = frozenset({"assertionRunEvent"})

DEFAULT_BATCH_SIZE = 200
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.5
SCROLL_PAGE_SIZE = 200

# A guard against an unbounded scroll on a large third-party instance: the
# benchmark's own estate is far smaller than this, so hitting it means the
# instance holds something unexpected and the caller is told so.
MAX_SCROLL_PAGES = 200


def redact_url(url: str) -> str:
    """Return ``url`` with any embedded credentials and query string removed.

    A GMS URL can legitimately carry userinfo (``https://user:secret@host/``).
    The round-trip report records which server it talked to, so the recorded
    value must be safe to publish, paste into an issue and commit.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:  # pragma: no cover - defensive
        return "<unparseable>"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))


@dataclass(frozen=True)
class IngestBatch:
    """One batch of proposals, as it will be transmitted.

    Constructed offline — ``--dry-run`` builds these and reports them without
    any network activity at all.
    """

    index: int
    proposals: tuple[dict[str, Any], ...]

    @property
    def size(self) -> int:
        return len(self.proposals)


def build_batches(
    proposals: Sequence[dict[str, Any]], batch_size: int = DEFAULT_BATCH_SIZE
) -> tuple[IngestBatch, ...]:
    """Split proposals into transmission batches, preserving emitted order.

    Order is preserved rather than optimised: the export's order is canonical
    and deterministic, and reordering it would make a transmitted batch harder
    to reconcile with the file it came from for no benefit.
    """
    if batch_size < 1:
        raise DataHubConfigError(f"batch size must be at least 1, got {batch_size}")
    return tuple(
        IngestBatch(index=number, proposals=tuple(proposals[start : start + batch_size]))
        for number, start in enumerate(range(0, len(proposals), batch_size))
    )


def encode_batch(proposals: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Encode emitted proposals into the OpenAPI v3 cross-entity request body.

    **This is the one place emitted content changes shape, and it changes only
    its shape.** The emitted export is the interchange artefact and is never
    rewritten; what happens here is the envelope translation the wire protocol
    requires, and nothing else. Entity identity, entity type, aspect identity
    and aspect content all survive unchanged:

    ``{"entityType": "dataset", "entityUrn": U, "aspectName": A, "aspect": {"json": P}}``

    becomes ``{"dataset": [{"urn": U, "A": {"value": P}}]}``, where ``P`` is the
    same object, not a copy that has been normalized, reordered or re-keyed.

    Proposals for one URN are merged into a single entity object because the
    request body is keyed by entity rather than by aspect. Merging is safe
    precisely because the export guarantees ``(entityUrn, aspectName)`` is
    unique, so no aspect can overwrite another; the guarantee is re-checked here
    rather than assumed, since a silent overwrite would be an invisible data
    loss. Emitted order is preserved by first appearance, within each entity
    type and within each entity.

    Anything this envelope cannot express is refused rather than approximated —
    a non-UPSERT change type, or an aspect that is not in the ``json`` dialect.
    Sending an approximation would be the reinterpretation this module exists
    not to perform.
    """
    by_type: dict[str, dict[str, dict[str, Any]]] = {}
    for proposal in proposals:
        change_type = proposal.get("changeType")
        if change_type != SUPPORTED_CHANGE_TYPE:
            raise DataHubConfigError(
                f"cannot transmit changeType {change_type!r} for "
                f"{proposal.get('entityUrn')!r}: this transport expresses "
                f"{SUPPORTED_CHANGE_TYPE} only"
            )
        aspect = proposal.get("aspect")
        if not isinstance(aspect, dict) or "json" not in aspect:
            raise DataHubConfigError(
                f"proposal for {proposal.get('entityUrn')!r} carries no 'aspect.json' payload; "
                "the OpenAPI transport cannot encode it without reinterpreting it"
            )

        entity_type = str(proposal["entityType"])
        urn = str(proposal["entityUrn"])
        aspect_name = str(proposal["aspectName"])

        entities = by_type.setdefault(entity_type, {})
        entity = entities.setdefault(urn, {"urn": urn})
        if aspect_name in entity:
            raise DataHubConfigError(
                f"duplicate aspect {aspect_name!r} for {urn!r} in one batch; "
                "encoding it would silently discard one of the two"
            )
        entity[aspect_name] = {"value": aspect["json"]}

    return {entity_type: list(entities.values()) for entity_type, entities in by_type.items()}


class DataHubClient:
    """A minimal GMS client over :mod:`urllib.request`.

    Constructed through :meth:`from_environment`; the direct constructor is
    available for tests, which pass a token explicitly rather than mutating the
    process environment.
    """

    def __init__(
        self,
        server: str,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self.server = server.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        # Private, and deliberately never exposed on a public attribute, in a
        # repr, or in an exception message.
        self._token = token

    @classmethod
    def from_environment(cls, **kwargs: Any) -> DataHubClient:
        """Build a client from ``DATAHUB_GMS_URL`` / ``DATAHUB_GMS_TOKEN``.

        The URL is required; the token is optional, because a locally-run
        instance without authentication is a legitimate target and demanding a
        token there would push users towards inventing one.
        """
        server = os.environ.get(GMS_URL_ENV, "").strip()
        if not server:
            raise DataHubConfigError(
                f"{GMS_URL_ENV} is not set. The GMS endpoint and token are read from the "
                f"environment only — the token is never accepted as a command-line argument."
            )
        token = os.environ.get(GMS_TOKEN_ENV, "").strip() or None
        return cls(server, token, **kwargs)

    @property
    def endpoint(self) -> str:
        """The server address, safe to record in a report or print to a terminal."""
        return redact_url(self.server)

    def __repr__(self) -> str:
        return f"DataHubClient(server={self.endpoint!r}, authenticated={self._token is not None})"

    # ----------------------------------------------------------------- HTTP

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        """Issue one request, retrying transient failures a bounded number of times."""
        url = f"{self.server}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
            except urllib.error.HTTPError as exc:
                # 4xx is a definitive answer — the payload or the credentials are
                # wrong, and repeating the request cannot change that.
                if exc.code < 500:
                    raise DataHubTransportError(
                        f"{redact_url(url)} returned HTTP {exc.code}", status=exc.code
                    ) from exc
                last = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
            except json.JSONDecodeError as exc:
                raise DataHubTransportError(
                    f"{redact_url(url)} returned a body that is not JSON"
                ) from exc
            if attempt < self.retries:
                time.sleep(self.backoff * (2**attempt))

        status = getattr(last, "code", None)
        raise DataHubTransportError(
            f"{redact_url(url)} could not be reached after {self.retries + 1} attempt(s)",
            status=status if isinstance(status, int) else None,
        )

    # -------------------------------------------------------------- Ingest

    def ingest_batch(self, batch: IngestBatch) -> None:
        """Transmit one batch, encoded for the OpenAPI v3 write API.

        The encoding is a change of envelope and nothing else — see
        :func:`encode_batch`. Nothing here synthesizes, enriches, rewrites or
        remaps a proposal, which is what lets the round-trip treat the emitted
        file as an authoritative statement of what the catalogue should hold.
        """
        self._request(INGEST_PATH, encode_batch(batch.proposals))

    # ------------------------------------------------------------- Readback

    def fetch_aspects(self, entity_type: str, urn: str) -> dict[str, Any]:
        """Return every versioned aspect the catalogue holds for one URN.

        All aspects are requested rather than only the ones we sent, so an
        aspect the catalogue holds and the export never contained is visible as
        an extra rather than silently skipped.
        """
        path = ENTITY_PATH.format(
            entity_type=urllib.parse.quote(entity_type, safe=""),
            urn=urllib.parse.quote(urn, safe=""),
        )
        try:
            body = self._request(path)
        except DataHubTransportError as exc:
            if exc.status == 404:
                return {}
            raise
        return _unwrap_aspects(body)

    def fetch_timeseries_aspect(self, entity_type: str, urn: str, aspect_name: str) -> Any | None:
        """Return the latest value of one timeseries aspect, or ``None``.

        Timeseries aspects are read through their own route rather than assumed
        to appear beside the versioned ones, and only the most recent value is
        compared: the adapter emits exactly one run event per quality check, so a
        series is not something it can produce. That limitation is documented
        rather than papered over.

        This route is OpenAPI v3, like every other call in this module. It used
        to be the rest.li ``getTimeseriesAspectValues``, which made reads a
        two-dialect mixture even before the write path was corrected.
        """
        path = TIMESERIES_PATH.format(
            entity_type=urllib.parse.quote(entity_type, safe=""),
            urn=urllib.parse.quote(urn, safe=""),
            # The aspect segment is lower-cased in the route, unlike the
            # camel-case aspect name used in every payload.
            aspect=urllib.parse.quote(aspect_name.lower(), safe=""),
        )
        try:
            body = self._request(path)
        except DataHubTransportError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(body, dict) or "value" not in body:
            return None
        return body["value"]

    def scroll_urns(self, entity_type: str) -> Iterator[str]:
        """Yield every URN the catalogue holds for one entity type.

        Enumeration is unfiltered because GMS offers no server-side namespace
        filter on this endpoint; the caller narrows the result by URN prefix.
        That is why extra-entity detection is restricted to families whose URN
        prefix is unambiguous — see
        :data:`~dataswamp_biosystems.adapters.datahub.roundtrip.ENTITY_FAMILIES`.
        """
        scroll_id: str | None = None
        for _ in range(MAX_SCROLL_PAGES):
            query = {"count": str(SCROLL_PAGE_SIZE)}
            if scroll_id:
                query["scrollId"] = scroll_id
            path = (
                SCROLL_PATH.format(entity_type=urllib.parse.quote(entity_type, safe=""))
                + "?"
                + urllib.parse.urlencode(query)
            )
            body = self._request(path)
            if not isinstance(body, dict):  # pragma: no cover - defensive
                return
            for entry in body.get("entities", []) or []:
                if isinstance(entry, dict) and isinstance(entry.get("urn"), str):
                    yield entry["urn"]
            scroll_id = body.get("scrollId")
            if not scroll_id:
                return
        raise DataHubTransportError(
            f"enumerating {entity_type} did not terminate within {MAX_SCROLL_PAGES} pages"
        )


def _unwrap_aspects(body: Any) -> dict[str, Any]:
    """Unwrap an entity response into ``{aspect_name: payload}``.

    The response carries each aspect as ``{"value": ..., "systemMetadata": ...}``
    beside the entity's ``urn``. The value is taken and the envelope discarded;
    a server that inlines ``systemMetadata`` into the value instead is handled by
    the normalization contract, which owns that field explicitly.
    """
    if not isinstance(body, dict):
        return {}
    aspects: dict[str, Any] = {}
    for key, value in body.items():
        if key in {"urn", "entityType"}:
            continue
        if isinstance(value, dict) and "value" in value:
            aspects[key] = value["value"]
        else:
            aspects[key] = value
    return aspects


__all__ = [
    "GMS_URL_ENV",
    "GMS_TOKEN_ENV",
    "LIVE_SUPPORT",
    "VERIFIED_DATAHUB_VERSION",
    "SUPPORTED_CHANGE_TYPE",
    "encode_batch",
    "INGEST_PATH",
    "ENTITY_PATH",
    "SCROLL_PATH",
    "TIMESERIES_PATH",
    "TIMESERIES_ASPECTS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_RETRIES",
    "DEFAULT_BACKOFF_SECONDS",
    "MAX_SCROLL_PAGES",
    "IngestBatch",
    "DataHubClient",
    "build_batches",
    "redact_url",
]
