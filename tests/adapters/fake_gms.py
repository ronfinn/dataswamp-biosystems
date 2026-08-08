"""A local, in-process stand-in for a DataHub GMS.

The whole live path has to be provable without Docker, without a network and
without credentials, so the tests need something that behaves like a catalogue.
This is it: a :mod:`http.server` thread that speaks the three endpoints
``client.py`` uses, stores aspects in a dictionary, and — crucially — can be told
to *misbehave* in specific, named ways.

That perturbation surface is what actually proves the round-trip works. A
differ that has only ever seen matching inputs is not evidence of anything; the
tests drop an aspect, add one nobody sent, mutate a field, add an unknown key and
plant a truth marker, and assert that each is caught with the right kind and the
right field path.

The fake is deliberately *not* a DataHub emulator. It implements the request and
response shapes this adapter depends on and nothing else, and it makes no claim
about how a real server behaves — establishing that is the live integration
job's work, not this file's.

**It validates the request envelope rather than accepting whatever arrives.**
The first version did not, and that is exactly how the rest.li/OpenAPI dialect
mismatch survived 111 offline tests: the fake read ``proposal["aspect"]["json"]``
straight out of whatever body the client sent, so any envelope the client chose
was self-consistently "correct". A real GMS answered HTTP 500. The ingest
handler below now enforces the OpenAPI v3 cross-entity shape — including
rejecting a rest.li ``GenericAspect`` body the way a real server does — so the
fake can disagree with the client, which is the only condition under which it
can catch anything.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from dataswamp_biosystems.adapters.datahub.client import DataHubClient


class EnvelopeError(ValueError):
    """The request body is not a well-formed OpenAPI v3 write envelope."""


@dataclass
class FakeGMS:
    """The catalogue's state, plus the knobs that make it misbehave."""

    # {urn: {aspect_name: payload}}
    store: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Every proposal the server was sent, in arrival order.
    received: list[dict[str, Any]] = field(default_factory=list)
    # Every Authorization header value seen, so token handling can be asserted.
    auth_headers: list[str | None] = field(default_factory=list)
    # Batch sizes, in arrival order.
    batch_sizes: list[int] = field(default_factory=list)
    # Aspects to refuse to return: {(urn, aspect_name)}.
    drop: set[tuple[str, str]] = field(default_factory=set)
    # Aspect payloads to overwrite after ingestion: {(urn, aspect): payload}.
    mutate: dict[tuple[str, str], Any] = field(default_factory=dict)
    # Aspects to invent on a URN nobody sent them for.
    inject: dict[tuple[str, str], Any] = field(default_factory=dict)
    # Entities to invent wholesale: {urn: {aspect: payload}}.
    inject_entities: dict[str, dict[str, Any]] = field(default_factory=dict)

    def ingest_v3(self, body: Any) -> int:
        """Apply one OpenAPI v3 cross-entity request, validating its envelope.

        The shape is ``{entityType: [{"urn": U, aspectName: {"value": payload}}]}``.
        Anything else is refused rather than coerced — a fake that accepts both
        dialects cannot detect that the client is speaking the wrong one.
        """
        if not isinstance(body, dict):
            raise EnvelopeError("request body must be a JSON object keyed by entity type")

        count = 0
        for entity_type, entities in body.items():
            if not isinstance(entities, list):
                raise EnvelopeError(f"{entity_type!r} must map to a list of entities")
            for entity in entities:
                if not isinstance(entity, dict) or not isinstance(entity.get("urn"), str):
                    raise EnvelopeError(f"each {entity_type} entity needs a string 'urn'")
                urn = entity["urn"]
                for aspect_name, wrapper in entity.items():
                    if aspect_name == "urn":
                        continue
                    # The rest.li dialect lands here as {"value": "<json string>",
                    # "contentType": ...} or as a bare aspect. Both are rejected,
                    # the second for the same reason a real GMS rejects it.
                    if not isinstance(wrapper, dict) or "value" not in wrapper:
                        raise EnvelopeError(
                            f'aspect {aspect_name!r} on {urn!r}: Field "value" is '
                            "required but it is not present"
                        )
                    payload = wrapper["value"]
                    if not isinstance(payload, dict | list):
                        raise EnvelopeError(
                            f"aspect {aspect_name!r} on {urn!r}: 'value' must be the "
                            f"aspect object, not {type(payload).__name__}"
                        )
                    self.received.append(
                        {
                            "entityType": entity_type,
                            "entityUrn": urn,
                            "aspectName": aspect_name,
                            "aspect": {"json": payload},
                        }
                    )
                    self.store.setdefault(urn, {})[aspect_name] = payload
                    count += 1
        return count

    def entity(self, urn: str) -> dict[str, Any]:
        """Return the aspects the server would serve for one URN."""
        aspects = dict(self.store.get(urn, {}))
        aspects.update(self.inject_entities.get(urn, {}))
        for (target, name), payload in self.inject.items():
            if target == urn:
                aspects[name] = payload
        for (target, name), payload in self.mutate.items():
            if target == urn and name in aspects:
                aspects[name] = payload
        for target, name in self.drop:
            if target == urn:
                aspects.pop(name, None)
        return aspects

    def urns_of_type(self, entity_type: str) -> list[str]:
        """Return every URN of one entity type, including injected ones."""
        prefix = f"urn:li:{entity_type}:"
        known = set(self.store) | set(self.inject_entities)
        return sorted(urn for urn in known if urn.startswith(prefix))

    def reset_traffic(self) -> None:
        """Forget what was received, keeping the stored state.

        Used by the idempotence test: the second ingestion must be observable on
        its own before its effect on the store is compared with the first's.
        """
        self.received.clear()
        self.batch_sizes.clear()
        self.auth_headers.clear()


def _handler_for(state: FakeGMS) -> type[BaseHTTPRequestHandler]:
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

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw)
            state.auth_headers.append(self.headers.get("Authorization"))
            path = urllib.parse.urlsplit(self.path)

            # POST /openapi/v3/entity/generic?async=false
            if path.path == "/openapi/v3/entity/generic":
                query = urllib.parse.parse_qs(path.query or "")
                if query.get("async", ["true"])[0] != "false":
                    # A real server would accept this and ingest asynchronously,
                    # making an immediate readback a race. Refusing it here keeps
                    # that race from being introduced by a later edit.
                    return self._respond(
                        {"error": "this fake requires async=false so readback is ordered"},
                        status=400,
                    )
                try:
                    count = state.ingest_v3(body)
                except EnvelopeError as exc:
                    # A real GMS rejects a malformed aspect envelope with a 500
                    # from its Pegasus deserializer, which is precisely what the
                    # rest.li/OpenAPI mismatch produced.
                    return self._respond({"error": str(exc)}, status=500)
                state.batch_sizes.append(count)
                return self._respond({"value": count})

            return self._respond({"error": "unknown path"}, status=404)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
            state.auth_headers.append(self.headers.get("Authorization"))
            path = urllib.parse.urlsplit(self.path)
            parts = [segment for segment in path.path.split("/") if segment]

            # /openapi/v3/entity/{type}/{urn}/{aspect} — the timeseries route.
            # The aspect segment is lower-cased in the real API, so the lookup
            # must be case-insensitive against the stored camel-case names.
            if len(parts) == 6 and parts[:3] == ["openapi", "v3", "entity"]:
                urn = urllib.parse.unquote(parts[4])
                wanted = urllib.parse.unquote(parts[5]).lower()
                for name, value in state.entity(urn).items():
                    if name.lower() == wanted:
                        return self._respond({"value": value})
                return self._respond({"error": "not found"}, status=404)

            # /openapi/v3/entity/{type}/{urn}
            if len(parts) == 5 and parts[:3] == ["openapi", "v3", "entity"]:
                urn = urllib.parse.unquote(parts[4])
                aspects = state.entity(urn)
                if not aspects:
                    return self._respond({"error": "not found"}, status=404)
                payload: dict[str, Any] = {"urn": urn}
                for name, value in sorted(aspects.items()):
                    payload[name] = {
                        "value": value,
                        # Server-owned ingestion provenance. Present on every
                        # stored aspect, which is precisely why the normalization
                        # contract owns this field explicitly.
                        "systemMetadata": {"runId": "fake-run", "lastObserved": 1},
                    }
                return self._respond(payload)

            # /openapi/v3/entity/{type}
            if len(parts) == 4 and parts[:3] == ["openapi", "v3", "entity"]:
                entity_type = urllib.parse.unquote(parts[3])
                entities = [{"urn": urn} for urn in state.urns_of_type(entity_type)]
                return self._respond({"entities": entities})

            return self._respond({"error": "unknown path"}, status=404)

    return Handler


class FakeGMSServer:
    """Context manager running a :class:`FakeGMS` on a loopback port."""

    def __init__(self, state: FakeGMS | None = None) -> None:
        self.state = state or FakeGMS()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self.state))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def client(self, token: str | None = None) -> DataHubClient:
        """Return a client pointed at this server, with retries made cheap."""
        return DataHubClient(self.url, token, timeout=5.0, retries=1, backoff=0.0)

    def __enter__(self) -> FakeGMSServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


__all__ = ["EnvelopeError", "FakeGMS", "FakeGMSServer"]
