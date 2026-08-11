"""Render a throwaway CI copy of the *pinned* OpenMetadata quickstart compose.

The ``live-openmetadata`` canary must run the deployment upstream actually
publishes, not a hand-written approximation of it — an approximation drifts, and
a canary that drifts from the real thing stops testing the real thing. So this
script takes upstream's own file, at the pinned commit, and applies the smallest
set of edits that make it safe to run on a shared machine. Every edit is listed
in :data:`SANITIZATIONS` and reported on stdout, so what was changed is evidence
rather than folklore.

Why each edit is necessary, from the pinned source
--------------------------------------------------

``docker/docker-compose-quickstart/docker-compose.yml`` at
``255f6694913b84797064a42859cda3f2a3425dc6`` declares:

* a fixed ``container_name`` on every service (``openmetadata_server``, …), which
  collides with any other instance on the same daemon regardless of
  ``COMPOSE_PROJECT_NAME`` — project naming does **not** isolate this file;
* ``./docker-volume/db-data:/var/lib/mysql`` as a host bind mount, so MySQL state
  outlives ``down -v`` and lands in whatever directory the file sits in;
* a hardcoded network subnet ``172.16.240.0/24``, which collides with anything
  already using it;
* host port publications for MySQL, Elasticsearch and Airflow that this canary
  never speaks to.

It also declares an ``ingestion`` (Airflow) service. The server does not depend
on it — ``openmetadata-server.depends_on`` names ``elasticsearch``, ``mysql`` and
``execute-migrate-all`` and nothing else — and DataSwamp speaks to the server's
REST API directly, so it is dropped. That is a real saving, not a cosmetic one:
it is the largest image in the stack and upstream's own validation action waits
up to 180s for it to initialise.

Authentication is switched to OpenMetadata's own ``NoopAuthorizer`` /
``NoopFilter``, which exist at the pinned commit and are selected by the
``AUTHORIZER_CLASS_NAME`` / ``AUTHORIZER_REQUEST_FILTER`` variables the pinned
``conf/openmetadata.yaml`` already interpolates. Nothing is invented: the
throwaway instance needs no credential, and so the canary needs no secret and
``OPENMETADATA_JWT_TOKEN`` stays unset.

Usage::

    uv run --frozen python scripts/render_live_openmetadata_compose.py \\
        --source upstream-docker-compose.yml --output docker-compose.yml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

#: The pinned upstream deployment this script is written against. Kept here as
#: well as in the workflow so a mismatch is a test failure rather than a
#: surprise: :mod:`tests.adapters.openmetadata.test_live_om_pin` asserts the two
#: agree with the adapter's own ``OPENMETADATA_SCHEMA_COMMIT``.
UPSTREAM_COMMIT = "255f6694913b84797064a42859cda3f2a3425dc6"
UPSTREAM_RELEASE = "1.13.3"
UPSTREAM_PATH = "docker/docker-compose-quickstart/docker-compose.yml"

#: Dropped entirely. Nothing in the canary's path uses Airflow, and the server
#: does not depend on it.
DROPPED_SERVICES = ("ingestion",)

#: Host ports the canary genuinely needs: the API and the admin/health port.
#: Everything else stays on the compose network where it cannot collide.
PUBLISHED_PORTS = ("8585:8585", "8586:8586")

#: The one MySQL bind mount, replaced by a named volume so ``down -v`` really
#: destroys the database rather than leaving it in the working directory.
MYSQL_BIND_MOUNT = "./docker-volume/db-data:/var/lib/mysql"
MYSQL_VOLUME = "om-db-data"

#: Auth off, using classes that exist at the pinned commit. Applied to both the
#: migration container and the server, which read the same configuration.
NOOP_AUTH = {
    "AUTHORIZER_CLASS_NAME": "org.openmetadata.service.security.NoopAuthorizer",
    "AUTHORIZER_REQUEST_FILTER": "org.openmetadata.service.security.NoopFilter",
}

SANITIZATIONS: tuple[str, ...] = (
    "dropped the ingestion (Airflow) service; the server does not depend on it",
    "removed every fixed container_name so two stacks cannot collide",
    f"replaced the {MYSQL_BIND_MOUNT} bind mount with the named volume {MYSQL_VOLUME}",
    "removed the hardcoded 172.16.240.0/24 subnet so Docker allocates a free one",
    f"published only {', '.join(PUBLISHED_PORTS)} to the host",
    "selected NoopAuthorizer/NoopFilter so the throwaway instance needs no credential",
)


def sanitize(document: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply every sanitization, returning the new document and what was done.

    Deliberately total: each edit asserts that the thing it removes was actually
    present. If upstream drops the bind mount or renames the ingestion service,
    this fails loudly at render time rather than silently rendering a file that
    no longer needs sanitizing — which would be the moment to re-read the diff.
    """
    applied: list[str] = []
    services: dict[str, Any] = dict(document.get("services") or {})
    if not services:
        raise SystemExit("the source compose file declares no services")

    for name in DROPPED_SERVICES:
        if name not in services:
            raise SystemExit(f"expected to drop service {name!r}, but it is not present")
        del services[name]
        applied.append(f"dropped service {name}")

    volumes: dict[str, Any] = dict(document.get("volumes") or {})

    for name, service in services.items():
        service = dict(service)

        if service.pop("container_name", None) is not None:
            applied.append(f"{name}: removed container_name")

        # `restart: always` on a throwaway job turns a crash-looping container
        # into a job that hangs until the timeout instead of failing fast.
        if service.pop("restart", None) is not None:
            applied.append(f"{name}: removed restart policy")

        mounts = list(service.get("volumes") or [])
        if MYSQL_BIND_MOUNT in mounts:
            mounts[mounts.index(MYSQL_BIND_MOUNT)] = f"{MYSQL_VOLUME}:/var/lib/mysql"
            service["volumes"] = mounts
            volumes[MYSQL_VOLUME] = None
            applied.append(f"{name}: bind mount replaced by the named volume {MYSQL_VOLUME}")
        if any(str(mount).startswith(("./", "../", "/")) for mount in mounts):
            raise SystemExit(f"{name}: a host path mount survived sanitization: {mounts}")

        published = [port for port in (service.get("ports") or []) if port in PUBLISHED_PORTS]
        if service.get("ports") is not None:
            if published:
                service["ports"] = published
            else:
                del service["ports"]
            applied.append(f"{name}: publishes {published or 'nothing'}")

        environment = service.get("environment")
        if isinstance(environment, dict) and "AUTHORIZER_CLASS_NAME" in environment:
            service["environment"] = {**environment, **NOOP_AUTH}
            applied.append(f"{name}: authorization set to Noop*")

        services[name] = service

    # Volumes that only the dropped ingestion service used.
    for orphan in [key for key in volumes if str(key).startswith("ingestion-volume")]:
        del volumes[orphan]
        applied.append(f"dropped orphaned volume {orphan}")

    networks: dict[str, Any] = {}
    for name, network in (document.get("networks") or {}).items():
        network = dict(network or {})
        if network.pop("ipam", None) is not None:
            applied.append(f"network {name}: removed the hardcoded subnet")
        networks[name] = network or None

    rendered = {key: value for key, value in document.items() if key != "version"}
    rendered["services"] = services
    rendered["volumes"] = volumes
    rendered["networks"] = networks
    return rendered, applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="the pinned upstream compose")
    parser.add_argument("--output", type=Path, required=True, help="where to write the CI copy")
    args = parser.parse_args(argv)

    document = yaml.safe_load(args.source.read_text(encoding="utf-8"))
    rendered, applied = sanitize(document)
    args.output.write_text(
        yaml.safe_dump(rendered, sort_keys=False, default_flow_style=False), encoding="utf-8"
    )

    print(f"rendered {args.output} from {UPSTREAM_PATH}@{UPSTREAM_COMMIT}")
    for line in applied:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
