"""The GMS client: credential handling, batching, and transport behaviour.

The credential tests matter more than the transport ones. A token that reaches
``argv``, a ``repr``, an exception or a report is a token in shell history, CI
logs and issue trackers — and unlike a transport bug, nobody notices.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from dataswamp_biosystems.adapters.datahub.client import (
    GMS_TOKEN_ENV,
    GMS_URL_ENV,
    DataHubClient,
    build_batches,
    redact_url,
)
from dataswamp_biosystems.adapters.datahub.errors import (
    DataHubConfigError,
    DataHubTransportError,
)

from .fake_gms import FakeGMSServer

TOKEN = "super-secret-token-value"


def _proposal(index: int) -> dict[str, object]:
    return {
        "entityType": "tag",
        "entityUrn": f"urn:li:tag:t{index}",
        "changeType": "UPSERT",
        "aspectName": "tagProperties",
        "aspect": {"json": {"name": f"t{index}"}},
    }


# ------------------------------------------------------------- credentials


def test_the_token_is_read_from_the_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GMS_URL_ENV, "https://gms.example.com")
    monkeypatch.setenv(GMS_TOKEN_ENV, TOKEN)
    client = DataHubClient.from_environment()
    assert client.endpoint == "https://gms.example.com"


def test_a_missing_url_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GMS_URL_ENV, raising=False)
    with pytest.raises(DataHubConfigError) as excinfo:
        DataHubClient.from_environment()
    assert GMS_URL_ENV in str(excinfo.value)


def test_an_absent_token_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local unauthenticated instance is a legitimate target."""
    monkeypatch.setenv(GMS_URL_ENV, "http://localhost:8080")
    monkeypatch.delenv(GMS_TOKEN_ENV, raising=False)
    assert DataHubClient.from_environment()._token is None


def test_the_token_never_appears_in_the_repr() -> None:
    client = DataHubClient("https://gms.example.com", TOKEN)
    assert TOKEN not in repr(client)
    assert "authenticated=True" in repr(client)


def test_the_token_never_appears_in_a_transport_exception() -> None:
    client = DataHubClient("http://127.0.0.1:1", TOKEN, timeout=0.5, retries=0, backoff=0.0)
    with pytest.raises(DataHubTransportError) as excinfo:
        client.fetch_aspects("dataset", "urn:li:dataset:(a,b,PROD)")
    assert TOKEN not in str(excinfo.value)


def test_credentials_embedded_in_a_url_are_redacted() -> None:
    assert redact_url("https://user:secret@gms.example.com/api/gms?token=abc") == (
        "https://gms.example.com/api/gms"
    )
    assert "secret" not in DataHubClient("https://user:secret@host/").endpoint


def test_the_token_is_sent_as_a_bearer_header() -> None:
    with FakeGMSServer() as server:
        client = server.client(TOKEN)
        client.ingest_batch(build_batches([_proposal(1)])[0])
    assert server.state.auth_headers == [f"Bearer {TOKEN}"]


def test_no_authorization_header_is_sent_without_a_token() -> None:
    with FakeGMSServer() as server:
        server.client().ingest_batch(build_batches([_proposal(1)])[0])
    assert server.state.auth_headers == [None]


# ---------------------------------------------------------------- batching


def test_batches_preserve_emitted_order_and_size() -> None:
    proposals = [_proposal(index) for index in range(5)]
    batches = build_batches(proposals, batch_size=2)
    assert [batch.size for batch in batches] == [2, 2, 1]
    assert [item for batch in batches for item in batch.proposals] == proposals
    assert [batch.index for batch in batches] == [0, 1, 2]


def test_a_zero_batch_size_is_refused() -> None:
    with pytest.raises(DataHubConfigError):
        build_batches([_proposal(1)], batch_size=0)


def test_batching_reaches_the_server_in_the_configured_sizes() -> None:
    proposals = [_proposal(index) for index in range(5)]
    with FakeGMSServer() as server:
        client = server.client()
        for batch in build_batches(proposals, batch_size=2):
            client.ingest_batch(batch)
    assert server.state.batch_sizes == [2, 2, 1]


# --------------------------------------------------------------- transport


def test_a_four_hundred_response_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 4xx is a definitive answer; repeating the request cannot change it."""
    attempts: list[str] = []

    def fail(request: urllib.request.Request, **kwargs: object) -> None:
        attempts.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    client = DataHubClient("https://gms.example.com", TOKEN, retries=3, backoff=0.0)
    with pytest.raises(DataHubTransportError) as excinfo:
        client.fetch_aspects("dataset", "urn:li:dataset:(a,b,PROD)")
    assert excinfo.value.status == 401
    assert len(attempts) == 1


def test_a_transient_failure_is_retried_a_bounded_number_of_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def fail(request: urllib.request.Request, **kwargs: object) -> None:
        attempts.append(request.full_url)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    client = DataHubClient("https://gms.example.com", retries=2, backoff=0.0)
    with pytest.raises(DataHubTransportError):
        client.fetch_aspects("dataset", "urn:li:dataset:(a,b,PROD)")
    assert len(attempts) == 3


def test_an_unknown_urn_reads_back_as_no_aspects() -> None:
    """A 404 on readback means "not there", which is a completeness finding."""
    with FakeGMSServer() as server:
        assert server.client().fetch_aspects("dataset", "urn:li:dataset:(a,b,PROD)") == {}


def test_readback_unwraps_the_value_envelope() -> None:
    with FakeGMSServer() as server:
        client = server.client()
        client.ingest_batch(build_batches([_proposal(1)])[0])
        aspects = client.fetch_aspects("tag", "urn:li:tag:t1")
    assert aspects == {"tagProperties": {"name": "t1"}}


def test_a_timeseries_aspect_is_read_through_its_own_endpoint() -> None:
    run_event = {
        "entityType": "assertion",
        "entityUrn": "urn:li:assertion:" + "a" * 32,
        "changeType": "UPSERT",
        "aspectName": "assertionRunEvent",
        "aspect": {"json": {"runId": "qc-1", "status": "COMPLETE"}},
    }
    with FakeGMSServer() as server:
        client = server.client()
        client.ingest_batch(build_batches([run_event])[0])
        value = client.fetch_timeseries_aspect(
            "assertion", run_event["entityUrn"], "assertionRunEvent"
        )
    assert value == {"runId": "qc-1", "status": "COMPLETE"}


def test_scrolling_yields_every_urn_of_a_type() -> None:
    proposals = [_proposal(index) for index in range(3)]
    with FakeGMSServer() as server:
        client = server.client()
        client.ingest_batch(build_batches(proposals)[0])
        assert sorted(client.scroll_urns("tag")) == [
            "urn:li:tag:t0",
            "urn:li:tag:t1",
            "urn:li:tag:t2",
        ]


def test_a_non_json_body_is_a_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def read(self) -> bytes:
            return b"<html>gateway</html>"

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response())
    client = DataHubClient("https://gms.example.com", retries=0, backoff=0.0)
    with pytest.raises(DataHubTransportError, match="not JSON"):
        client.fetch_aspects("dataset", "urn:li:dataset:(a,b,PROD)")


def test_the_transmitted_body_is_the_proposal_set_verbatim() -> None:
    """Pure transport: nothing is synthesized, enriched, rewritten or remapped."""
    proposals = [_proposal(index) for index in range(3)]
    captured: list[dict[str, object]] = []

    with FakeGMSServer() as server:
        client = server.client()
        client.ingest_batch(build_batches(proposals)[0])
        captured = server.state.received

    assert captured == proposals
    assert json.dumps(captured, sort_keys=True) == json.dumps(proposals, sort_keys=True)
