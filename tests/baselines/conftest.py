"""Fixtures for the baseline tests.

Everything here builds on ``real_observed_dir`` from the top-level conftest —
the canonical scenario's observed state — so the baselines are exercised against
exactly the benchmark they publish scores for, never a hand-rolled stand-in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.baselines import ObservedInput
from dataswamp_biosystems.evaluation import GroundTruth, load_ground_truth
from dataswamp_biosystems.observed.writer import OBSERVED_GRAPH_NAME


@pytest.fixture(scope="session")
def observed_input(real_observed_dir: Path) -> ObservedInput:
    return ObservedInput.load(real_observed_dir)


@pytest.fixture(scope="session")
def ground_truth(real_observed_dir: Path) -> GroundTruth:
    return load_ground_truth(real_observed_dir)


@pytest.fixture(scope="session")
def observed_graph_only(real_observed_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An observed directory containing *only* the observed graph.

    An agent that reached for the expected findings, the controls or the rule
    scope would fail outright here rather than quietly scoring well, so this is
    the strongest anti-leakage fixture available: it removes the answers from the
    filesystem instead of asking the agent not to look.
    """
    target = tmp_path_factory.mktemp("observed-graph-only") / "observed"
    target.mkdir(parents=True)
    (target / OBSERVED_GRAPH_NAME).write_bytes(
        (real_observed_dir / OBSERVED_GRAPH_NAME).read_bytes()
    )
    return target


@pytest.fixture
def reordered_observed_dir(real_observed_dir: Path, tmp_path: Path) -> Path:
    """The same observed graph with every shard's records reversed.

    Record order inside a shard carries no meaning — the same entities with the
    same fields are still present — so a baseline whose output changed here would
    be reporting an artefact of file layout rather than a property of the estate.
    """
    graph = json.loads((real_observed_dir / OBSERVED_GRAPH_NAME).read_text(encoding="utf-8"))
    reordered = {
        key: list(reversed(value)) if isinstance(value, list) else value
        for key, value in graph.items()
    }
    target = tmp_path / "observed"
    target.mkdir(parents=True)
    (target / OBSERVED_GRAPH_NAME).write_text(json.dumps(reordered), encoding="utf-8")
    return target


@pytest.fixture(scope="session")
def gold_observed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The canonical estate under the defect-free ``gold`` profile.

    A scenario with (almost) nothing wrong in it is the sharpest test of a
    detector's false-positive behaviour: anything a baseline says here it is
    saying about clean data.
    """
    from dataswamp_biosystems.canonical import CANONICAL_DEFECT_SEED, CANONICAL_TRUTH_SEED
    from dataswamp_biosystems.company import load_config
    from dataswamp_biosystems.observed.engine import generate_observed
    from dataswamp_biosystems.observed.profiles import ObservedProfile
    from dataswamp_biosystems.observed.writer import write_observed
    from dataswamp_biosystems.truth import generate_truth_graph, load_generation_plan

    config_dir = Path(__file__).resolve().parents[2] / "config"
    config = load_config(config_dir)
    plan = load_generation_plan(config_dir)
    graph = generate_truth_graph(config, plan, CANONICAL_TRUTH_SEED)
    result = generate_observed(graph, config, ObservedProfile.GOLD, CANONICAL_DEFECT_SEED)
    target = tmp_path_factory.mktemp("gold-observed") / "observed"
    write_observed(result, target)
    return target
