"""The rendered CI deployment must be genuinely throwaway.

The canary runs upstream's own quickstart compose rather than a hand-written
approximation, because an approximation drifts and a drifted canary stops
testing the real thing. But upstream's file is written for a developer's laptop:
it names its containers, bind-mounts MySQL's data directory into the working
directory, and hardcodes a subnet. On a shared machine each of those is a
collision or a leak of state between runs, and ``COMPOSE_PROJECT_NAME`` isolates
none of them.

``scripts/render_live_openmetadata_compose.py`` applies the smallest set of edits
that fix that. These tests pin what those edits guarantee, against a fixture that
reproduces the pinned file's relevant shape — no Docker, no network.

The renderer is deliberately *total*: it fails loudly if something it expects to
sanitize is absent, so an upstream change that removes the bind mount surfaces as
a render failure to read rather than as a quietly weaker deployment.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from scripts.render_live_openmetadata_compose import (
    MYSQL_VOLUME,
    NOOP_AUTH,
    PUBLISHED_PORTS,
    UPSTREAM_COMMIT,
    UPSTREAM_RELEASE,
    sanitize,
)

# A faithful reduction of the pinned upstream file: every trait the renderer
# exists to remove, and nothing irrelevant to that.
UPSTREAM = yaml.safe_load(
    """
version: "3.9"
volumes:
  ingestion-volume-dag-airflow:
  ingestion-volume-dags:
  ingestion-volume-tmp:
  es-data:
services:
  mysql:
    container_name: openmetadata_mysql
    image: docker.getcollate.io/openmetadata/db:1.13.3
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: password
    ports:
      - "3306:3306"
    volumes:
      - ./docker-volume/db-data:/var/lib/mysql
    networks:
      - app_net
  elasticsearch:
    container_name: openmetadata_elasticsearch
    image: docker.elastic.co/elasticsearch/elasticsearch:9.3.0
    ports:
      - "9200:9200"
      - "9300:9300"
    volumes:
      - es-data:/usr/share/elasticsearch/data
    networks:
      - app_net
  execute-migrate-all:
    container_name: execute_migrate_all
    image: docker.getcollate.io/openmetadata/server:1.13.3
    environment:
      AUTHORIZER_CLASS_NAME: org.openmetadata.service.security.DefaultAuthorizer
      AUTHORIZER_REQUEST_FILTER: org.openmetadata.service.security.JwtFilter
      AUTHENTICATION_PROVIDER: basic
    networks:
      - app_net
  openmetadata-server:
    container_name: openmetadata_server
    image: docker.getcollate.io/openmetadata/server:1.13.3
    restart: always
    environment:
      AUTHORIZER_CLASS_NAME: org.openmetadata.service.security.DefaultAuthorizer
      AUTHORIZER_REQUEST_FILTER: org.openmetadata.service.security.JwtFilter
      AUTHENTICATION_PROVIDER: basic
    ports:
      - "8585:8585"
      - "8586:8586"
    networks:
      - app_net
  ingestion:
    container_name: openmetadata_ingestion
    image: docker.getcollate.io/openmetadata/ingestion:1.13.3
    ports:
      - "8080:8080"
    volumes:
      - ingestion-volume-dags:/opt/airflow/dags
    networks:
      - app_net
networks:
  app_net:
    ipam:
      driver: default
      config:
        - subnet: "172.16.240.0/24"
"""
)


@pytest.fixture
def rendered() -> dict[str, Any]:
    document, _ = sanitize(UPSTREAM)
    return document


def test_the_renderer_names_the_deployment_it_was_written_against() -> None:
    """The rendered stack and the vendored schemas come from one commit."""
    assert UPSTREAM_COMMIT == "255f6694913b84797064a42859cda3f2a3425dc6"
    assert UPSTREAM_RELEASE == "1.13.3"


def test_no_container_name_survives(rendered: dict[str, Any]) -> None:
    """Two stacks on one daemon must not collide over a fixed name."""
    for name, service in rendered["services"].items():
        assert "container_name" not in service, name


def test_no_host_path_is_mounted(rendered: dict[str, Any]) -> None:
    """State must live in a named volume `down -v` destroys, not in a directory."""
    for name, service in rendered["services"].items():
        for mount in service.get("volumes") or []:
            assert not str(mount).startswith(("./", "../", "/")), f"{name}: {mount}"
    assert MYSQL_VOLUME in rendered["volumes"]
    assert f"{MYSQL_VOLUME}:/var/lib/mysql" in rendered["services"]["mysql"]["volumes"]


def test_only_the_api_and_health_ports_reach_the_host(rendered: dict[str, Any]) -> None:
    """MySQL, Elasticsearch and Airflow have no business on the runner's ports."""
    published = {
        port for service in rendered["services"].values() for port in service.get("ports") or []
    }
    assert published == set(PUBLISHED_PORTS)


def test_the_airflow_service_and_its_volumes_are_gone(rendered: dict[str, Any]) -> None:
    """The server does not depend on it and the canary never speaks to it."""
    assert "ingestion" not in rendered["services"]
    assert not [name for name in rendered["volumes"] if str(name).startswith("ingestion-volume")]


def test_the_network_subnet_is_not_hardcoded(rendered: dict[str, Any]) -> None:
    """A fixed subnet collides with whatever already holds it on the runner."""
    for name, network in rendered["networks"].items():
        assert not (network or {}).get("ipam"), name


def test_authorization_is_disabled_using_openmetadatas_own_classes(
    rendered: dict[str, Any],
) -> None:
    """Not invented configuration: both classes exist at the pinned commit, and
    the pinned `conf/openmetadata.yaml` already interpolates these variables.

    This is what makes the canary secret-free: with no authorizer there is no
    credential to generate, mask, store or leak, and OPENMETADATA_JWT_TOKEN
    stays unset throughout.
    """
    assert NOOP_AUTH == {
        "AUTHORIZER_CLASS_NAME": "org.openmetadata.service.security.NoopAuthorizer",
        "AUTHORIZER_REQUEST_FILTER": "org.openmetadata.service.security.NoopFilter",
    }
    for name in ("execute-migrate-all", "openmetadata-server"):
        environment = rendered["services"][name]["environment"]
        assert environment["AUTHORIZER_CLASS_NAME"] == NOOP_AUTH["AUTHORIZER_CLASS_NAME"]
        assert environment["AUTHORIZER_REQUEST_FILTER"] == NOOP_AUTH["AUTHORIZER_REQUEST_FILTER"]


def test_the_server_image_still_carries_the_pinned_tag(rendered: dict[str, Any]) -> None:
    """Sanitizing must not touch what is under test."""
    image = rendered["services"]["openmetadata-server"]["image"]
    assert image == f"docker.getcollate.io/openmetadata/server:{UPSTREAM_RELEASE}"


def test_a_restart_policy_never_survives(rendered: dict[str, Any]) -> None:
    """`restart: always` turns a crash loop into a job that hangs to its timeout."""
    for name, service in rendered["services"].items():
        assert "restart" not in service, name


# --------------------------------------------------------------- totality
#
# The renderer must fail rather than silently render a weaker deployment when
# upstream stops matching its assumptions. That failure is the signal to re-read
# the upstream diff, which is the whole reason for not maintaining a second
# hand-written compose file.


def test_a_missing_ingestion_service_is_an_error_not_a_shrug() -> None:
    document = {
        **UPSTREAM,
        "services": {
            name: service for name, service in UPSTREAM["services"].items() if name != "ingestion"
        },
    }
    with pytest.raises(SystemExit, match="ingestion"):
        sanitize(document)


def test_a_surviving_host_mount_is_an_error() -> None:
    services = {name: dict(service) for name, service in UPSTREAM["services"].items()}
    services["elasticsearch"] = {
        **services["elasticsearch"],
        "volumes": ["/var/lib/somewhere:/data"],
    }
    with pytest.raises(SystemExit, match="host path mount"):
        sanitize({**UPSTREAM, "services": services})


def test_an_empty_compose_file_is_an_error() -> None:
    with pytest.raises(SystemExit, match="no services"):
        sanitize({"version": "3.9"})
