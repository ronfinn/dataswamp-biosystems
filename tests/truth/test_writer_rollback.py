"""Rollback behaviour of the truth writer's atomic directory replacement.

The writer stages output in a temporary sibling, renames any existing output
aside as a backup, then swaps the staged directory into place. These tests cover
the failure path — that a mid-swap error restores the previous output rather
than leaving the caller with nothing — which the happy-path replacement tests do
not reach. All paths are under ``tmp_path``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.writer import MANIFEST_NAME, write_truth_graph


def _staging_leftovers(parent: Path) -> list[str]:
    return sorted(
        p.name
        for p in parent.iterdir()
        if p.name.startswith(".") and (".tmp-" in p.name or ".bak-" in p.name)
    )


def _fail_on_staged_swap(out: Path) -> Callable[..., None]:
    """An ``os.replace`` stand-in that fails only on the staged→final swap.

    The existing-output→backup rename and the backup→output restore must both be
    allowed through, or the test would be exercising its own stub rather than the
    writer's rollback path.
    """
    real_replace = os.replace

    def _replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst) == out and ".tmp-" in Path(src).name:
            raise OSError("simulated failure swapping staged output into place")
        real_replace(src, dst)

    return _replace


def test_failed_swap_restores_previous_output(
    graph: TruthGraph, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "truth"
    write_truth_graph(graph, out)
    before = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
    assert before  # sanity: there is something to lose

    monkeypatch.setattr(
        "dataswamp_biosystems.truth.writer.os.replace",
        _fail_on_staged_swap(out),
    )
    with pytest.raises(OSError, match="simulated failure"):
        write_truth_graph(graph, out)

    # The previous output survived intact — no loss of existing data.
    assert out.exists()
    assert {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()} == before


def test_failed_swap_leaves_no_staging_directories(
    graph: TruthGraph, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "truth"
    write_truth_graph(graph, out)

    monkeypatch.setattr(
        "dataswamp_biosystems.truth.writer.os.replace",
        _fail_on_staged_swap(out),
    )
    with pytest.raises(OSError, match="simulated failure"):
        write_truth_graph(graph, out)

    assert _staging_leftovers(tmp_path) == []


def test_successful_write_leaves_no_staging_directories(graph: TruthGraph, tmp_path: Path) -> None:
    out = tmp_path / "truth"
    write_truth_graph(graph, out)
    write_truth_graph(graph, out)
    assert _staging_leftovers(tmp_path) == []
    assert (out / MANIFEST_NAME).exists()
