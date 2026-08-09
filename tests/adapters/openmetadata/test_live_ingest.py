"""Replay semantics: what is sent, in what order, and what is refused.

The claims under test are the ones that make the round-trip meaningful. If
ingestion could reorder, batch, repair or enrich the emitted plan, then "the
catalogue matches what we sent" would be a statement about this module rather
than about the catalogue.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.openmetadata import (
    OpenMetadataClient,
    execute_ingestion,
    load_export,
    plan_ingestion,
)
from dataswamp_biosystems.adapters.openmetadata.errors import OpenMetadataConfigError
from dataswamp_biosystems.adapters.openmetadata.export import (
    ENTITIES_NAME,
    EXPORT_MANIFEST_NAME,
)
from dataswamp_biosystems.adapters.openmetadata.ingest import (
    KIND_ADD_ASSETS,
    KIND_ADD_LINEAGE,
    KIND_BLOCKED,
    KIND_CREATE_ENTITY,
    KIND_CUSTOM_PROPERTY,
)

from .conftest import LiveFixture
from .fake_om import FakeOpenMetadataServer

# ---------------------------------------------------------------------------
# Loading and verifying an emitted export
# ---------------------------------------------------------------------------


def test_a_clean_export_loads(om_observed_export_dir: Path) -> None:
    export = load_export(om_observed_export_dir)
    assert export.mode.value == "observed"
    assert not export.privileged
    assert export.records


def test_a_tampered_payload_is_refused_before_any_network_activity(
    copied_om_export: Path,
) -> None:
    """A digest that no longer recomputes means somebody edited the plan."""
    target = copied_om_export / ENTITIES_NAME
    original = target.read_bytes()
    target.write_bytes(original.replace(b'"description"', b'"descriptioN"', 1))
    assert target.read_bytes() != original
    with pytest.raises(OpenMetadataConfigError) as caught:
        load_export(copied_om_export)
    assert "does not match its manifest digest" in str(caught.value)


def test_a_tampered_manifest_is_refused(copied_om_export: Path) -> None:
    manifest = json.loads((copied_om_export / EXPORT_MANIFEST_NAME).read_text())
    manifest["files"][ENTITIES_NAME] = "0" * 64
    (copied_om_export / EXPORT_MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(OpenMetadataConfigError):
        load_export(copied_om_export)


def test_a_mode_that_contradicts_its_privilege_flag_is_refused(copied_om_export: Path) -> None:
    manifest = json.loads((copied_om_export / EXPORT_MANIFEST_NAME).read_text())
    manifest["privileged"] = True
    (copied_om_export / EXPORT_MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(OpenMetadataConfigError) as caught:
        load_export(copied_om_export)
    assert "contradict" in str(caught.value)


def test_a_plan_that_violates_reference_closure_is_refused(copied_om_export: Path) -> None:
    """The offline validator runs again over what was read from disk.

    The manifest is re-digested to match, so this test isolates *plan validity*
    rather than merely re-proving that digest verification works.
    """
    from dataswamp_biosystems.truth import serialize

    path = copied_om_export / ENTITIES_NAME
    lines = path.read_text(encoding="utf-8").splitlines()
    # Drop the storage service, which every container references.
    kept = [line for line in lines if json.loads(line)["phase"] != "storage-service"]
    path.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
    manifest_path = copied_om_export / EXPORT_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][ENTITIES_NAME] = serialize.digest(path.read_bytes())
    manifest_path.write_bytes(serialize.manifest_bytes(manifest))

    with pytest.raises(OpenMetadataConfigError) as caught:
        load_export(copied_om_export)
    assert "invalid" in str(caught.value)


def test_a_directory_that_is_not_an_export_is_refused(tmp_path: Path) -> None:
    with pytest.raises(OpenMetadataConfigError):
        load_export(tmp_path)


# ---------------------------------------------------------------------------
# The replay plan
# ---------------------------------------------------------------------------


def test_the_planned_operations_are_exactly_the_emitted_records(
    om_observed_export_dir: Path,
) -> None:
    """One operation per emitted record, and nothing invented in between."""
    export = load_export(om_observed_export_dir)
    plan = plan_ingestion(export)
    assert [operation.record for operation in plan.operations] == list(export.records)


def test_the_replay_order_is_the_emitted_order(om_observed_export_dir: Path) -> None:
    export = load_export(om_observed_export_dir)
    orders = [operation.record.order for operation in plan_ingestion(export).operations]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)


def test_an_out_of_order_plan_is_refused(om_observed_export_dir: Path) -> None:
    """Dependency order is a contract, so a plan that breaks it is not replayed."""
    export = load_export(om_observed_export_dir)
    reversed_plan = type(export)(
        root=export.root,
        mode=export.mode,
        plan=type(export.plan)(
            mode=export.plan.mode,
            custom_properties=export.plan.custom_properties[::-1],
            entities=export.plan.entities,
            lineage=export.plan.lineage,
            test_results=export.plan.test_results,
            coverage=export.plan.coverage,
        ),
        manifest=export.manifest,
    )
    with pytest.raises(OpenMetadataConfigError) as caught:
        plan_ingestion(reversed_plan)
    assert "increasing order" in str(caught.value)


def test_deferred_quality_results_are_classified_blocked_and_never_transmitted(
    om_observed_export_dir: Path,
) -> None:
    """OpenMetadata has no honest home for them; ingestion must not invent one."""
    export = load_export(om_observed_export_dir)
    plan = plan_ingestion(export)
    blocked = [op for op in plan.operations if op.kind == KIND_BLOCKED]
    assert blocked
    assert all(op.record.phase == "test-result" for op in blocked)
    assert plan.blocked_count == len(blocked)


def test_every_operation_kind_is_exercised(om_observed_export_dir: Path) -> None:
    kinds = set(plan_ingestion(load_export(om_observed_export_dir)).counts_by_kind())
    assert kinds == {
        KIND_CUSTOM_PROPERTY,
        KIND_CREATE_ENTITY,
        KIND_ADD_ASSETS,
        KIND_ADD_LINEAGE,
        KIND_BLOCKED,
    }


# ---------------------------------------------------------------------------
# Dry run opens no socket
# ---------------------------------------------------------------------------


def test_planning_opens_no_socket(
    om_observed_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Poisoned at the network entry points, not merely at the client.

    Mocking ``OpenMetadataClient`` would only prove that the code path nobody
    doubts was not taken. Poisoning ``socket.socket`` and ``urlopen`` proves that
    *nothing at all* reached the network, including a stray health check.
    """
    import socket
    import urllib.request

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a dry run opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    export = load_export(om_observed_export_dir)
    plan = plan_ingestion(export)
    assert plan.transmitted_count > 0


# ---------------------------------------------------------------------------
# Transmission
# ---------------------------------------------------------------------------


def test_the_transmitted_set_equals_the_emitted_set(om_live: LiveFixture) -> None:
    """Semantic preservation, checked against the fake's own arrival log.

    Every create body that arrived is matched back to the emitted record it came
    from, field for field, with the sole exception of the reference fields the
    export explicitly declares as unresolvable offline.
    """
    plan = plan_ingestion(om_live.export)
    execute_ingestion(plan, om_live.client())

    arrived: dict[str, dict[str, object]] = {}
    for method, path, body in om_live.state.requests:
        if method == "PUT" and isinstance(body, dict) and "name" in body and "/name/" not in path:
            arrived[f"{path}|{body['name']}"] = body

    checked = 0
    for operation in plan.operations:
        record = operation.record
        if operation.kind != KIND_CREATE_ENTITY or record.create is None:
            continue
        declared = {reference.field for reference in record.references}
        for path_key, body in arrived.items():
            if not path_key.endswith(f"|{record.create['name']}"):
                continue
            for key, value in record.create.items():
                assert body.get(key) == value, f"{record.fqn}: {key} was altered in transit"
            assert set(body) - set(record.create) <= declared
            checked += 1
            break
    assert checked > 0


def test_a_second_ingestion_is_idempotent(om_live: LiveFixture) -> None:
    """Create-or-update converges on one estate rather than producing a second."""
    before = dict(om_live.state.entities)
    execute_ingestion(plan_ingestion(om_live.export), om_live.client())
    assert set(om_live.state.entities) == set(before)
    assert om_live.compare().clean


def test_custom_properties_are_registered_before_any_extension_uses_them(
    om_live: LiveFixture,
) -> None:
    """Proved by the fake, which refuses an unregistered extension key.

    A successful clean ingestion of a plan whose containers carry ``extension``
    is therefore itself the proof — the fake would have answered 400 otherwise.
    """
    assert om_live.state.custom_properties["container"]
    with_extension = [
        document
        for (kind, _fqn), document in om_live.state.entities.items()
        if kind == "container" and document.get("extension")
    ]
    assert with_extension


def test_ingestion_fails_loudly_when_a_dependency_is_missing() -> None:
    """A reference that cannot resolve is an error, never a silent skip."""
    from dataswamp_biosystems.adapters.openmetadata.errors import OpenMetadataTransportError

    with FakeOpenMetadataServer() as server:
        client = OpenMetadataClient(server.host_port, retries=0)
        with pytest.raises(OpenMetadataTransportError) as caught:
            client.entity_reference("container", "dataswamp-biosystems.nothing")
    assert "does not hold it" in str(caught.value)
