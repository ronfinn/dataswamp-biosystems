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
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from dataswamp_biosystems.adapters.datahub.client import DataHubClient


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

    def ingest(self, proposal: dict[str, Any]) -> None:
        """Apply one UPSERT, exactly as a catalogue would."""
        urn = str(proposal["entityUrn"])
        aspect_name = str(proposal["aspectName"])
        self.received.append(proposal)
        self.store.setdefault(urn, {})[aspect_name] = proposal["aspect"]["json"]

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

            if "ingestProposalBatch" in (path.query or ""):
                proposals = body.get("proposals", [])
                state.batch_sizes.append(len(proposals))
                for proposal in proposals:
                    state.ingest(proposal)
                return self._respond({"value": len(proposals)})

            if "getTimeseriesAspectValues" in (path.query or ""):
                urn = str(body.get("urn", ""))
                aspect_name = str(body.get("aspect", ""))
                payload = state.entity(urn).get(aspect_name)
                if payload is None:
                    return self._respond({"value": {"values": []}})
                return self._respond(
                    {"value": {"values": [{"aspect": {"value": json.dumps(payload)}}]}}
                )

            return self._respond({"error": "unknown action"}, status=400)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
            state.auth_headers.append(self.headers.get("Authorization"))
            path = urllib.parse.urlsplit(self.path)
            parts = [segment for segment in path.path.split("/") if segment]

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


__all__ = ["FakeGMS", "FakeGMSServer"]
