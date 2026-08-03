"""Fixtures shared by the bundle and adapter tests.

The canonical scenario is generated once per session (truth, estate, observed)
and scored once against a perfect submission to produce an evaluation layer.
Bundle tests then package some subset of those directories and adapter tests
translate the result, so both exercise the real emitted bytes rather than a
hand-rolled imitation of them — which is the whole point of a packager.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dataswamp_biosystems.bundle import Layer, build_bundle
from dataswamp_biosystems.canonical import (
    CANONICAL_DEFECT_SEED,
    CANONICAL_TRUTH_SEED,
    ESTATE_DIRNAME,
    OBSERVED_DIRNAME,
    TRUTH_DIRNAME,
    generate_canonical_from_config_dir,
)
from dataswamp_biosystems.company import load_config
from dataswamp_biosystems.evaluation import (
    evaluate,
    load_ground_truth,
    load_predictions,
    prediction_digest,
    write_evaluation,
)
from dataswamp_biosystems.observed.engine import generate_observed
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.writer import write_observed
from dataswamp_biosystems.truth import generate_truth_graph, load_generation_plan

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"

EVALUATION_DIRNAME = "evaluation"


@pytest.fixture(scope="session")
def generated_layers(tmp_path_factory: pytest.TempPathFactory) -> dict[Layer, Path]:
    """Generate the canonical scenario plus one evaluation report, once."""
    root = tmp_path_factory.mktemp("bundle-inputs") / "generated"
    generate_canonical_from_config_dir(root, CONFIG_DIR)

    observed_dir = root / OBSERVED_DIRNAME
    truth = load_ground_truth(observed_dir)
    predictions_path = root.parent / "predictions.jsonl"
    predictions_path.write_text(
        "".join(
            json.dumps(
                {
                    "schema_version": 1,
                    "prediction_id": f"p-{index}",
                    "entity_id": finding.entity_id,
                    "rule_id": finding.rule_id,
                    "status": "finding",
                    "category": finding.category.value,
                    "severity": finding.severity.value,
                    "confidence": 0.9,
                    "evidence": finding.observable_evidence[:80],
                },
                sort_keys=True,
            )
            + "\n"
            for index, finding in enumerate(truth.findings, start=1)
        ),
        encoding="utf-8",
    )
    submitted, raw = load_predictions(
        predictions_path, known_entities=truth.known_entities, known_rules=truth.rule_ids
    )
    result = evaluate(truth, submitted, prediction_digest=prediction_digest(raw))
    write_evaluation(result, root / EVALUATION_DIRNAME)

    return {
        Layer.TRUTH: root / TRUTH_DIRNAME,
        Layer.ESTATE: root / ESTATE_DIRNAME,
        Layer.OBSERVED: observed_dir,
        Layer.EVALUATION: root / EVALUATION_DIRNAME,
    }


@pytest.fixture(scope="session")
def full_bundle_dir(
    generated_layers: dict[Layer, Path], tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """A complete four-layer bundle, built once and never modified by a test."""
    target = tmp_path_factory.mktemp("full-bundle") / "bundle"
    build_bundle(target, sources=generated_layers, release="v-test")
    return target


@pytest.fixture(scope="session")
def truth_only_bundle_dir(
    generated_layers: dict[Layer, Path], tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """A truth-only bundle: the minimum a bundle may contain."""
    target = tmp_path_factory.mktemp("truth-bundle") / "bundle"
    build_bundle(target, sources={Layer.TRUTH: generated_layers[Layer.TRUTH]})
    return target


@pytest.fixture
def mutable_bundle(full_bundle_dir: Path, tmp_path: Path) -> Path:
    """A private copy of the full bundle, for tests that tamper with it."""
    target = tmp_path / "bundle"
    shutil.copytree(full_bundle_dir, target)
    return target


CANONICAL_SEED = CANONICAL_DEFECT_SEED


@pytest.fixture(scope="session")
def real_observed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The canonical scenario's observed state, generated and written once.

    Shared by the evaluation tests and the example-submission tests: both score
    against exactly the ground truth the benchmark publishes, and generating it
    per-module would be pure waste.
    """
    config = load_config(CONFIG_DIR)
    plan = load_generation_plan(CONFIG_DIR)
    graph = generate_truth_graph(config, plan, CANONICAL_TRUTH_SEED)
    result = generate_observed(graph, config, ObservedProfile.DEMO, CANONICAL_DEFECT_SEED)
    target = tmp_path_factory.mktemp("real-observed") / "observed"
    write_observed(result, target)
    return target
