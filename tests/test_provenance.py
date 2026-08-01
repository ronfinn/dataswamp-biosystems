"""Environment provenance recorded alongside every generated output directory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems import __version__
from dataswamp_biosystems.canonical import (
    CANONICAL_DEFECT_SEED,
    CANONICAL_OBSERVED_PROFILE,
    CANONICAL_TRUTH_SEED,
    config_fingerprint,
    config_input_paths,
)
from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.engine import generate_observed
from dataswamp_biosystems.observed.writer import write_observed
from dataswamp_biosystems.provenance import (
    DIRECT_DEPENDENCIES,
    PROVENANCE_NAME,
    UNKNOWN_VERSION,
    build_provenance,
    direct_dependency_versions,
    environment_fingerprint,
    provenance_bytes,
)
from dataswamp_biosystems.truth import GenerationPlan, generate_truth_graph
from dataswamp_biosystems.truth.writer import write_truth_graph

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


def _payload(directory: Path) -> dict:
    return json.loads((directory / PROVENANCE_NAME).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def truth_provenance(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from dataswamp_biosystems.company import load_config
    from dataswamp_biosystems.truth import load_generation_plan

    out = tmp_path_factory.mktemp("prov") / "truth"
    config: CanonicalConfig = load_config(CONFIG_DIR)
    plan: GenerationPlan = load_generation_plan(CONFIG_DIR)
    write_truth_graph(generate_truth_graph(config, plan, CANONICAL_TRUTH_SEED), out)
    return _payload(out)


# -- required fields ----------------------------------------------------------


def test_truth_output_records_provenance(truth_provenance: dict) -> None:
    assert truth_provenance["dataswamp_version"] == __version__
    assert truth_provenance["layer"] == "truth"
    assert truth_provenance["generator_version"]
    assert truth_provenance["schema_version"] >= 1
    assert truth_provenance["python"]["version"].count(".") == 1
    assert truth_provenance["platform"]["system"]
    assert truth_provenance["synthetic"] is True


def test_provenance_records_every_direct_dependency(truth_provenance: dict) -> None:
    versions = truth_provenance["direct_dependencies"]
    assert set(versions) == set(DIRECT_DEPENDENCIES)
    assert UNKNOWN_VERSION not in versions.values()
    assert list(versions) == sorted(versions)


def test_provenance_records_the_scenario(truth_provenance: dict) -> None:
    assert truth_provenance["scenario"]["seed"] == CANONICAL_TRUTH_SEED


def test_observed_provenance_records_seeds_profile_and_truth_linkage(
    graph_and_config: tuple, tmp_path: Path
) -> None:
    graph, config = graph_and_config
    result = generate_observed(graph, config, CANONICAL_OBSERVED_PROFILE, CANONICAL_DEFECT_SEED)
    out = tmp_path / "observed"
    write_observed(result, out)

    payload = _payload(out)
    assert payload["layer"] == "observed"
    assert payload["scenario"]["defect_seed"] == CANONICAL_DEFECT_SEED
    assert payload["scenario"]["profile"] == CANONICAL_OBSERVED_PROFILE.value
    assert payload["scenario"]["truth_seed"] == graph.meta.seed
    assert payload["schema_version"] == result.meta.schema_version


@pytest.fixture(scope="module")
def graph_and_config() -> tuple:
    from dataswamp_biosystems.company import load_config
    from dataswamp_biosystems.truth import load_generation_plan

    config = load_config(CONFIG_DIR)
    plan = load_generation_plan(CONFIG_DIR)
    return generate_truth_graph(config, plan, CANONICAL_TRUTH_SEED), config


# -- determinism --------------------------------------------------------------


def test_provenance_is_byte_stable_within_an_environment() -> None:
    """No wall-clock value may destabilize the payload."""
    first = provenance_bytes(
        layer="truth", generator_version="1.0.0", schema_version=1, scenario={"seed": 1}
    )
    second = provenance_bytes(
        layer="truth", generator_version="1.0.0", schema_version=1, scenario={"seed": 1}
    )
    assert first == second


def test_provenance_contains_no_timestamp_fields() -> None:
    payload = build_provenance(
        layer="truth", generator_version="1.0.0", schema_version=1, scenario={"seed": 1}
    )
    flattened = json.dumps(payload).lower()
    for banned in ("timestamp", "generated_at", "created_at", "datetime"):
        assert banned not in flattened


def test_fingerprint_changes_with_dependency_identity() -> None:
    versions = direct_dependency_versions()
    bumped = {**versions, "numpy": "0.0.0-not-real"}
    assert environment_fingerprint(bumped) != environment_fingerprint(versions)


def test_fingerprint_is_independent_of_ordering() -> None:
    versions = direct_dependency_versions()
    reversed_order = dict(reversed(list(versions.items())))
    assert environment_fingerprint(reversed_order) == environment_fingerprint(versions)


# -- configuration identity ---------------------------------------------------


def test_config_fingerprint_is_stable_and_covers_the_yaml_inputs() -> None:
    paths = config_input_paths(CONFIG_DIR)
    assert paths
    assert all(path.suffix in {".yaml", ".yml"} for path in paths)
    assert config_fingerprint(CONFIG_DIR) == config_fingerprint(CONFIG_DIR)


def test_config_fingerprint_ignores_machine_specific_artefacts(tmp_path: Path) -> None:
    """A stray .DS_Store or editor swapfile must not change the contract.

    Regression guard: an earlier implementation hashed every file under the
    configuration directory, so an untracked macOS ``.DS_Store`` made the golden
    contract fail locally while passing in CI.
    """
    config_dir = tmp_path / "config"
    (config_dir / "vocabularies").mkdir(parents=True)
    (config_dir / "company.yaml").write_text("name: test\n", encoding="utf-8")
    (config_dir / "vocabularies" / "terms.yml").write_text("terms: []\n", encoding="utf-8")
    baseline = config_fingerprint(config_dir)

    (config_dir / ".DS_Store").write_bytes(b"\x00\x01mac junk")
    (config_dir / ".company.yaml.swp").write_bytes(b"vim swap")
    (config_dir / "notes.txt").write_text("scratch", encoding="utf-8")
    (config_dir / "__pycache__").mkdir()
    (config_dir / "__pycache__" / "x.pyc").write_bytes(b"\x00")

    assert config_fingerprint(config_dir) == baseline


def test_config_fingerprint_changes_when_configuration_changes(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "company.yaml").write_text("name: test\n", encoding="utf-8")
    before = config_fingerprint(config_dir)
    (config_dir / "company.yaml").write_text("name: changed\n", encoding="utf-8")
    assert config_fingerprint(config_dir) != before
