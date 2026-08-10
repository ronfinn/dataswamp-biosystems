"""The transport boundary: credentials, redaction, and a fake that can say no.

Two things are proved here. First, that the client handles credentials the way
the contract requires — environment only, never in a repr, an exception or a
recorded URL. Second, and more importantly, that the **fake server is stricter
than the client**: every negative test below sends something the client would
never send and asserts the fake refuses it.

That second half is the point. A fake that only ever sees well-formed requests
from the module it was written alongside proves nothing at all — it is a mirror.
The DataHub adapter learned this the expensive way, so these tests deliberately
bypass ``client.py`` and hand-build wrong requests with :mod:`urllib` directly.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from dataswamp_biosystems.adapters.openmetadata import (
    HOST_PORT_ENV,
    JWT_TOKEN_ENV,
    OpenMetadataClient,
    redact_url,
)
from dataswamp_biosystems.adapters.openmetadata.errors import (
    OpenMetadataConfigError,
    OpenMetadataTransportError,
)

from .fake_om import FakeOpenMetadataServer

SECRET = "super-secret-jwt-value"


def _raw(host_port: str, method: str, path: str, body: Any = None) -> tuple[int, str]:
    """Issue a request without going anywhere near ``client.py``."""
    url = f"{host_port.removesuffix('/api')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_the_host_is_read_from_the_environment_and_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HOST_PORT_ENV, raising=False)
    with pytest.raises(OpenMetadataConfigError) as caught:
        OpenMetadataClient.from_environment()
    assert HOST_PORT_ENV in str(caught.value)


def test_the_token_comes_from_the_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOST_PORT_ENV, "http://catalogue.invalid:8585/api")
    monkeypatch.setenv(JWT_TOKEN_ENV, SECRET)
    client = OpenMetadataClient.from_environment()
    assert "authenticated=True" in repr(client)
    assert SECRET not in repr(client)


def test_a_token_is_never_rendered_in_a_repr_or_an_endpoint() -> None:
    client = OpenMetadataClient("https://user:pw@host:8585/api?token=abc", SECRET)
    assert SECRET not in repr(client)
    assert "pw" not in repr(client)
    assert "token=abc" not in client.endpoint
    assert client.endpoint == "https://host:8585/api"


def test_a_transport_error_carries_no_credential() -> None:
    """An exception is one of the easiest ways for a token to reach a CI log."""
    client = OpenMetadataClient("http://127.0.0.1:1/api", SECRET, retries=0, timeout=0.5)
    with pytest.raises(OpenMetadataTransportError) as caught:
        client.get_by_name("container", "dataswamp-biosystems.anything")
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "given",
    ["http://host:8585", "http://host:8585/", "http://host:8585/api", "http://host:8585/api/"],
)
def test_the_host_port_is_accepted_with_or_without_the_api_suffix(given: str) -> None:
    """OpenMetadata's own config writes hostPort with ``/api``; users arrive with it."""
    assert OpenMetadataClient(given).base == "http://host:8585"


def test_the_token_is_sent_as_a_bearer_header() -> None:
    with FakeOpenMetadataServer() as server:
        client = OpenMetadataClient(server.host_port, SECRET, retries=0)
        client.resolve_type_id("string")
        assert server.state.auth_headers == [f"Bearer {SECRET}"]


def test_no_authorization_header_is_sent_without_a_token() -> None:
    with FakeOpenMetadataServer() as server:
        OpenMetadataClient(server.host_port, None, retries=0).resolve_type_id("string")
        assert server.state.auth_headers == [None]


def test_redact_url_strips_userinfo_and_query() -> None:
    assert redact_url("https://u:p@h:8585/api?token=t") == "https://h:8585/api"


# ---------------------------------------------------------------------------
# The fake is stricter than the client
# ---------------------------------------------------------------------------


def test_the_fake_refuses_the_wrong_http_method() -> None:
    """POST is create-only in OpenMetadata; create-or-update is PUT."""
    with FakeOpenMetadataServer() as server:
        status, body = _raw(
            server.host_port,
            "POST",
            "/api/v1/classifications",
            {"name": "dataswamp", "description": "x"},
        )
    assert status == 405
    assert "PUT" in body


def test_the_fake_refuses_an_unknown_endpoint() -> None:
    with FakeOpenMetadataServer() as server:
        status, body = _raw(server.host_port, "PUT", "/api/v1/tables", {"name": "x"})
    assert status == 404
    assert "no route" in body


def test_the_fake_refuses_the_wrong_request_envelope_for_lineage() -> None:
    """``AddLineage`` wraps the edge; a bare edge is not the same document."""
    with FakeOpenMetadataServer() as server:
        status, body = _raw(
            server.host_port,
            "PUT",
            "/api/v1/lineage",
            {"fromEntity": {"id": "a", "type": "container"}},
        )
    assert status == 400
    assert "AddLineage" in body


def test_the_fake_refuses_the_wrong_request_envelope_for_assets() -> None:
    with FakeOpenMetadataServer() as server:
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/domains",
            {"name": "dataswamp-x", "description": "d", "domainType": "Source-aligned"},
        )
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/dataProducts",
            {"name": "p", "description": "d", "domains": ["dataswamp-x"]},
        )
        status, body = _raw(
            server.host_port,
            "PUT",
            "/api/v1/dataProducts/p/assets/add",
            [{"id": "x", "type": "container"}],
        )
    assert status == 400
    assert "BulkAssets" in body


def test_the_fake_rejects_the_asset_write_route_upstream_does_not_declare() -> None:
    """``/name/{fqn}/assets/add`` is not a spelling of the write — it is a 404.

    ``DataProductResource`` declares the asset *read* at ``/name/{fqn}/assets``
    and the *write* at ``/{name}/assets/add``; there is no ``/name`` form of the
    write at all. The client sent the phantom route for the whole of #35 and the
    fake accepted it, because the fake matched ``/name/{fqn}`` plus any tail. See
    #37 — a fake that generalises a route the server enumerates cannot catch the
    client.
    """
    with FakeOpenMetadataServer() as server:
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/domains",
            {"name": "dataswamp-x", "description": "d", "domainType": "Source-aligned"},
        )
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/dataProducts",
            {"name": "p", "description": "d", "domains": ["dataswamp-x"]},
        )
        phantom, body = _raw(
            server.host_port,
            "PUT",
            "/api/v1/dataProducts/name/p/assets/add",
            {"assets": []},
        )
        real, _ = _raw(
            server.host_port,
            "PUT",
            "/api/v1/dataProducts/p/assets/add",
            {"assets": []},
        )
        read, _ = _raw(server.host_port, "GET", "/api/v1/dataProducts/name/p/assets", None)

    assert phantom == 404
    assert "/{fqn}/assets/add" in body
    assert real == 200
    # The read keeps its ``/name`` form. The asymmetry is upstream's, not ours.
    assert read == 200


def test_the_fake_derives_a_data_product_fqn_from_its_name_alone() -> None:
    """Not from its Domain. ``DataProductRepository`` does not override the default.

    The fake used to compute ``domain.name``, which is the prefix DataSwamp's own
    identity assumed and no server adds. That agreement between fake and export is
    what hid the identity bug through #33 and #35.
    """
    with FakeOpenMetadataServer() as server:
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/domains",
            {"name": "dataswamp-x", "description": "d", "domainType": "Source-aligned"},
        )
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/dataProducts",
            {"name": "p", "description": "d", "domains": ["dataswamp-x"]},
        )
        by_name, _ = _raw(server.host_port, "GET", "/api/v1/dataProducts/name/p", None)
        domain_scoped, _ = _raw(
            server.host_port, "GET", "/api/v1/dataProducts/name/dataswamp-x.p", None
        )

    assert by_name == 200
    assert domain_scoped == 404


def test_the_fake_refuses_an_unknown_field_because_upstream_forbids_it() -> None:
    """``additionalProperties: false`` is upstream's rule, read from its own schema."""
    with FakeOpenMetadataServer() as server:
        status, body = _raw(
            server.host_port,
            "PUT",
            "/api/v1/classifications",
            {"name": "dataswamp", "description": "x", "notAField": 1},
        )
    assert status == 400
    assert "notAField" in body


def test_the_fake_refuses_a_missing_required_field() -> None:
    with FakeOpenMetadataServer() as server:
        status, body = _raw(server.host_port, "PUT", "/api/v1/containers", {"name": "x"})
    assert status == 400
    assert "service" in body


def test_the_fake_refuses_an_extension_key_with_no_registered_custom_property() -> None:
    """Registration order is load-bearing, so the fake enforces it."""
    with FakeOpenMetadataServer() as server:
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/services/storageServices",
            {"name": "dataswamp-biosystems", "serviceType": "CustomStorage"},
        )
        status, body = _raw(
            server.host_port,
            "PUT",
            "/api/v1/containers",
            {
                "name": "s",
                "service": "dataswamp-biosystems",
                "extension": {"dataswampId": "s"},
            },
        )
    assert status == 400
    assert "unregistered custom propert" in body


def test_the_fake_refuses_a_reference_to_something_that_does_not_exist_yet() -> None:
    with FakeOpenMetadataServer() as server:
        status, body = _raw(
            server.host_port,
            "PUT",
            "/api/v1/containers",
            {"name": "s", "service": "dataswamp-biosystems"},
        )
    assert status == 400
    assert "does not exist" in body


def test_the_fake_refuses_an_fqn_string_where_an_entity_reference_is_required() -> None:
    """``owners`` is resolved by id upstream; an FQN there would silently do nothing."""
    with FakeOpenMetadataServer() as server:
        status, body = _raw(
            server.host_port,
            "PUT",
            "/api/v1/teams",
            {"name": "dataswamp-t", "teamType": "Group", "owners": ["dataswamp-other"]},
        )
    assert status == 400
    assert "EntityReference" in body


def test_the_fake_refuses_a_bare_property_type_name() -> None:
    """``CustomProperty.propertyType`` is an EntityReference, not a string."""
    with FakeOpenMetadataServer() as server:
        type_id = server.state.type_ids["container"]
        status, body = _raw(
            server.host_port,
            "PUT",
            f"/api/v1/metadata/types/{type_id}",
            {"name": "dataswampId", "description": "d", "propertyType": "string"},
        )
    assert status == 400
    assert "EntityReference" in body


def test_the_fake_withholds_opt_in_fields_that_were_not_requested() -> None:
    """A client that forgets ``?fields=`` must see a lean entity, not a full one."""
    label = {
        "tagFQN": "dataswamp.synthetic",
        "source": "Classification",
        "labelType": "Manual",
        "state": "Confirmed",
    }
    with FakeOpenMetadataServer() as server:
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/classifications",
            {"name": "dataswamp", "description": "d"},
        )
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/tags",
            {"name": "synthetic", "classification": "dataswamp", "description": "d"},
        )
        _raw(
            server.host_port,
            "PUT",
            "/api/v1/services/storageServices",
            {"name": "dataswamp-biosystems", "serviceType": "CustomStorage", "tags": [label]},
        )
        base = "/api/v1/services/storageServices/name/dataswamp-biosystems"
        _, lean = _raw(server.host_port, "GET", base)
        _, asked = _raw(server.host_port, "GET", f"{base}?fields=tags,owners")
    assert "tags" not in json.loads(lean)
    assert "id" in json.loads(lean)
    assert json.loads(asked)["tags"] == [label]


def test_create_or_update_is_idempotent_and_bumps_only_the_server_version() -> None:
    with FakeOpenMetadataServer() as server:
        payload = {"name": "dataswamp", "description": "d"}
        _raw(server.host_port, "PUT", "/api/v1/classifications", payload)
        _, second = _raw(server.host_port, "PUT", "/api/v1/classifications", payload)
        assert json.loads(second)["version"] == 0.2
        listing = json.loads(_raw(server.host_port, "GET", "/api/v1/classifications")[1])
    assert len(listing["data"]) == 1


def test_the_emitted_annotation_and_the_client_route_agree() -> None:
    """Two independent statements of one contract, checked against each other.

    ``mapping.ENDPOINTS`` is frozen export *data* and ``client.py`` owns the live
    path; neither imports the other, and the transport deliberately never reads
    the annotation. That independence is what kept the #37 mismatch from becoming
    a live bug — and it is also what let the two drift apart unnoticed, so the
    agreement is asserted here rather than left to attentiveness.
    """
    from urllib.parse import quote

    from dataswamp_biosystems.adapters.openmetadata.mapping import ENDPOINTS

    fqn = "dataswamp-prog~~dp-omics"
    seen: list[str] = []

    client = OpenMetadataClient("http://127.0.0.1:1", token=None)
    client._request = lambda method, path, payload=None, **kw: seen.append(path) or {}  # type: ignore[method-assign]
    client.add_data_product_assets(fqn, [])

    annotated = ENDPOINTS["dataProductAssets"].format(fqn=quote(fqn, safe=""))
    assert seen == [annotated.removeprefix("/api")]


def test_the_fake_server_does_not_model_the_client() -> None:
    """The one structural guarantee that lets the fake disagree with the client.

    A fake that imports the client's collection table, field names or route
    helpers can only ever confirm what the client already believes. That is
    precisely how the DataHub dialect mismatch survived 111 offline tests, and how
    the #37 route and FQN defects survived this suite.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).with_name("fake_om.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "client" not in node.module.split(".")
        elif isinstance(node, ast.Import):
            assert all("client" not in alias.name.split(".") for alias in node.names)
