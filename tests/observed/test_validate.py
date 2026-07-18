"""Validation tests: a fresh estate is valid; drift and tampering are caught."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.engine import generate_observed
from dataswamp_biosystems.observed.errors import ObservedConfigError, ObservedValidationError
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.validate import validate_observed
from dataswamp_biosystems.observed.writer import (
    INJECTED_DEFECTS_NAME,
    OBSERVED_GRAPH_NAME,
    write_observed,
)
from dataswamp_biosystems.truth.graph import TruthGraph
from tests.observed.conftest import TEST_SEED


def _write(graph: TruthGraph, config: CanonicalConfig, out: Path) -> None:
    result = generate_observed(graph, config, ObservedProfile.DEMO, TEST_SEED)
    write_observed(result, out)


def test_fresh_estate_validates(graph: TruthGraph, config: CanonicalConfig, tmp_path: Path) -> None:
    out = tmp_path / "observed"
    _write(graph, config, out)
    validate_observed(out, graph, config)  # must not raise


def test_missing_summary_raises_config_error(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    with pytest.raises(ObservedConfigError):
        validate_observed(tmp_path / "nowhere", graph, config)


def test_graph_tampering_is_detected(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = tmp_path / "observed"
    _write(graph, config, out)
    target = out / OBSERVED_GRAPH_NAME
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ObservedValidationError):
        validate_observed(out, graph, config)


def test_ledger_tampering_is_detected(
    graph: TruthGraph, config: CanonicalConfig, tmp_path: Path
) -> None:
    out = tmp_path / "observed"
    _write(graph, config, out)
    target = out / INJECTED_DEFECTS_NAME
    lines = target.read_text(encoding="utf-8").splitlines()
    target.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ObservedValidationError):
        validate_observed(out, graph, config)
