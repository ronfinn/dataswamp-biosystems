"""Ingesting an emitted export: verification first, then pure transport.

These tests use a *real* emitted export from the canonical bundle rather than a
hand-built one. The claim being tested is about the artefact the project
actually publishes, and a hand-built payload could drift from it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.datahub import (
    EXPORT_MANIFEST_NAME,
    MCPS_JSONL_NAME,
    ExportMode,
)
from dataswamp_biosystems.adapters.datahub.errors import DataHubConfigError
from dataswamp_biosystems.adapters.datahub.ingest import (
    execute_ingestion,
    load_export,
    plan_ingestion,
)

from .fake_gms import FakeGMSServer


def _emitted_proposals(export_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (export_dir / MCPS_JSONL_NAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ------------------------------------------------------------- verification


def test_a_sound_export_loads(observed_export_dir: Path) -> None:
    export = load_export(observed_export_dir)
    assert export.mode is ExportMode.OBSERVED
    assert not export.privileged
    assert export.proposals
    assert export.payload_digest


def test_the_loaded_proposals_are_the_emitted_ones(observed_export_dir: Path) -> None:
    export = load_export(observed_export_dir)
    assert list(export.proposals) == _emitted_proposals(observed_export_dir)


def test_a_tampered_payload_refuses_to_load(copied_export: Path) -> None:
    """Transmitting metadata that no longer matches its manifest would put
    unattributable content into somebody's catalogue."""
    path = copied_export / MCPS_JSONL_NAME
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["aspect"]["json"]["tampered"] = True
    lines[0] = json.dumps(record, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(DataHubConfigError, match="does not match its manifest digest"):
        load_export(copied_export)


def test_a_tampered_recipe_also_refuses_to_load(copied_export: Path) -> None:
    """Every declared file is verified, not only the payload."""
    recipe = copied_export / "datahub-recipe.yml"
    recipe.write_text(recipe.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    with pytest.raises(DataHubConfigError, match="does not match its manifest digest"):
        load_export(copied_export)


def test_a_missing_declared_file_refuses_to_load(copied_export: Path) -> None:
    (copied_export / MCPS_JSONL_NAME).unlink()
    with pytest.raises(DataHubConfigError, match="missing"):
        load_export(copied_export)


def test_a_manifest_whose_mode_and_privilege_disagree_refuses_to_load(
    copied_export: Path,
) -> None:
    """The privilege flag is checked, not merely carried."""
    path = copied_export / EXPORT_MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["privileged"] = True
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    # The manifest's own digest is not self-referential, so this reaches the check.
    with pytest.raises(DataHubConfigError, match="contradict each other"):
        load_export(copied_export)


def test_a_directory_that_is_not_an_export_refuses_to_load(tmp_path: Path) -> None:
    with pytest.raises(DataHubConfigError):
        load_export(tmp_path)


def test_a_nonexistent_directory_refuses_to_load(tmp_path: Path) -> None:
    with pytest.raises(DataHubConfigError, match="not a directory"):
        load_export(tmp_path / "absent")


def test_a_privileged_truth_export_loads_and_declares_itself(truth_export_dir: Path) -> None:
    export = load_export(truth_export_dir)
    assert export.mode is ExportMode.TRUTH
    assert export.privileged


# -------------------------------------------------------------- dry running


def test_planning_opens_no_socket(
    observed_export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dry run that contacts a server is not a dry run.

    Every socket-creating entry point is poisoned, so any network activity at
    all — a request, a health check, a DNS lookup through a connection — fails
    the test rather than passing silently.
    """
    import socket
    import urllib.request

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("planning must not perform any network activity")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    export = load_export(observed_export_dir)
    plan = plan_ingestion(export, batch_size=50)
    assert plan.proposal_count == len(export.proposals)
    assert sum(batch.size for batch in plan.batches) == plan.proposal_count


def test_batching_covers_every_proposal_exactly_once(observed_export_dir: Path) -> None:
    export = load_export(observed_export_dir)
    plan = plan_ingestion(export, batch_size=7)
    flattened = [item for batch in plan.batches for item in batch.proposals]
    assert flattened == list(export.proposals)


# ------------------------------------------------------------ transmission


def test_the_transmitted_set_equals_the_emitted_set(observed_export_dir: Path) -> None:
    """The structural containment guarantee behind the non-leakage claim.

    Ingestion cannot introduce content the export did not contain, so anything
    the catalogue holds under our URNs came from a payload that already passed
    the offline observed-mode validator.
    """
    export = load_export(observed_export_dir)
    with FakeGMSServer() as server:
        execute_ingestion(plan_ingestion(export, batch_size=25), server.client())
        received = list(server.state.received)

    assert received == _emitted_proposals(observed_export_dir)


def test_a_second_ingestion_is_idempotent(observed_export_dir: Path) -> None:
    """Every proposal is an UPSERT, so re-running converges rather than duplicating."""
    export = load_export(observed_export_dir)
    with FakeGMSServer() as server:
        client = server.client()
        execute_ingestion(plan_ingestion(export), client)
        first = json.dumps(server.state.store, sort_keys=True)
        entities_after_first = len(server.state.store)

        server.state.reset_traffic()
        execute_ingestion(plan_ingestion(export), client)
        second = json.dumps(server.state.store, sort_keys=True)

    assert second == first
    assert len(json.loads(second)) == entities_after_first
