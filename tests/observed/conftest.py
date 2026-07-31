"""Shared fixtures for imperfection-engine (observed-state) tests.

Tests run against the repository's authored configuration and a fixed seed so
count and determinism assertions are stable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dataswamp_biosystems.company import CanonicalConfig, load_config
from dataswamp_biosystems.truth import GenerationPlan, generate_truth_graph, load_generation_plan
from dataswamp_biosystems.truth.graph import TruthGraph

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG_DIR = REPO_ROOT / "config"

# Matches the milestone's example seed.
TEST_SEED = 20260717


@pytest.fixture(scope="session")
def config() -> CanonicalConfig:
    return load_config(REAL_CONFIG_DIR)


@pytest.fixture(scope="session")
def plan() -> GenerationPlan:
    return load_generation_plan(REAL_CONFIG_DIR)


@pytest.fixture(scope="session")
def graph(config: CanonicalConfig, plan: GenerationPlan) -> TruthGraph:
    return generate_truth_graph(config, plan, TEST_SEED)


@pytest.fixture(scope="session")
def config_dir() -> Path:
    return REAL_CONFIG_DIR
