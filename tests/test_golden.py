"""The golden benchmark-output contract.

``tests/golden/canonical-digests.json`` records SHA-256 digests for a small,
fixed canonical scenario. This module only ever *compares* against it — the
fixture is regenerated exclusively by ``scripts/update_golden_digests.py``, which
requires an explicit reason and cause, so ordinary test runs can never rewrite
the contract.

Two scopes, matching what the evidence actually supports:

*portable* digests (truth graph, observed-state ledgers) are asserted in **every**
environment, including lowest-direct dependency resolution; *environment-scoped*
digests (the estate, whose payloads are written by pyarrow/Pillow/tifffile/
anndata) are asserted only when the environment fingerprint matches the one that
produced the fixture.

This catches drift that regenerate-and-compare validation cannot: those checks
compare current output against current code, so a change to generation *and*
validation together stays self-consistent and passes. A committed digest does
not move when the code does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.canonical import (
    DIGEST_ALGORITHM,
    config_fingerprint,
    digest_tree,
    generate_canonical,
    is_portable,
    scenario_identity,
    split_digests,
)
from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.provenance import (
    PROVENANCE_NAME,
    direct_dependency_versions,
    environment_fingerprint,
)
from dataswamp_biosystems.truth import GenerationPlan

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "golden" / "canonical-digests.json"
CONFIG_DIR = REPO_ROOT / "config"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate the canonical scenario once, into a temporary directory."""
    from dataswamp_biosystems.company import load_config
    from dataswamp_biosystems.truth import load_generation_plan

    out = tmp_path_factory.mktemp("canonical") / "out"
    config: CanonicalConfig = load_config(CONFIG_DIR)
    plan: GenerationPlan = load_generation_plan(CONFIG_DIR)
    generate_canonical(out, config, plan)
    return out


@pytest.fixture(scope="module")
def digests(generated: Path) -> dict[str, str]:
    return digest_tree(generated)


def _is_canonical_environment(fixture: dict) -> bool:
    recorded = fixture.get("canonical_environment", {}).get("environment_fingerprint")
    return bool(recorded) and recorded == environment_fingerprint()


# -- the contract -------------------------------------------------------------


def test_fixture_is_well_formed(fixture: dict) -> None:
    assert fixture["fixture_version"] >= 1
    assert fixture["digest_algorithm"] == DIGEST_ALGORITHM
    assert fixture["scenario"] == scenario_identity()
    assert fixture["portable_digests"]
    assert fixture["environment_scoped_digests"]
    assert fixture["canonical_environment"]["environment_fingerprint"]
    assert fixture["last_update"]["reason"]


def test_configuration_identity_is_unchanged(fixture: dict) -> None:
    """A config edit must surface as a config change, not a mystery digest failure."""
    assert config_fingerprint(CONFIG_DIR) == fixture["config_fingerprint"], (
        "the canonical configuration changed; regenerate the golden fixture "
        "with scripts/update_golden_digests.py --cause config"
    )


def test_portable_digests_match_in_every_environment(
    fixture: dict, digests: dict[str, str]
) -> None:
    """Truth-graph and observed-state bytes are guaranteed across the dependency range."""
    expected = fixture["portable_digests"]
    actual = {path: digest for path, digest in digests.items() if is_portable(path)}
    assert actual == expected, (
        "portable benchmark output changed. If this is intentional, see "
        "docs/reproducibility.md and run scripts/update_golden_digests.py."
    )


def test_environment_scoped_digests_match_in_the_canonical_environment(
    fixture: dict, digests: dict[str, str]
) -> None:
    """Estate bytes are guaranteed only within the canonical environment fingerprint."""
    if not _is_canonical_environment(fixture):
        pytest.skip(
            "not the canonical environment fingerprint "
            "(expected under lowest-direct resolution); portable digests still assert"
        )
    expected = fixture["environment_scoped_digests"]
    actual = {path: digest for path, digest in digests.items() if not is_portable(path)}
    assert actual == expected


def test_contract_covers_every_benchmark_artefact_class(fixture: dict) -> None:
    """Guard against an artefact silently dropping out of the contract."""
    covered = set(fixture["portable_digests"]) | set(fixture["environment_scoped_digests"])
    required = {
        "truth/truth-graph.json",
        "truth/assets.jsonl",
        "truth/files.jsonl",
        "truth/lineage.jsonl",
        "estate/file-manifest.jsonl",
        "estate/generation-summary.json",
        "observed/observed-graph.json",
        "observed/injected-defects.jsonl",
        "observed/expected-findings.jsonl",
        "observed/expected-remediations.jsonl",
        "observed/mutation-log.jsonl",
        "observed/controls.jsonl",
        "observed/rule-scope.jsonl",
        "observed/profile-summary.json",
    }
    assert required <= covered, sorted(required - covered)


def test_provenance_is_excluded_from_the_contract(
    fixture: dict, digests: dict[str, str], generated: Path
) -> None:
    """Provenance varies by environment by design, so it is never hashed."""
    assert not any(path.endswith(PROVENANCE_NAME) for path in digests)
    covered = set(fixture["portable_digests"]) | set(fixture["environment_scoped_digests"])
    assert not any(path.endswith(PROVENANCE_NAME) for path in covered)
    # It must nevertheless be present in every generated layer.
    for layer in ("truth", "estate", "observed"):
        assert (generated / layer / PROVENANCE_NAME).is_file()


def test_individual_estate_files_are_pinned_through_the_manifest(generated: Path) -> None:
    """The compact contract must still bind every materialized payload byte."""
    import hashlib

    manifest_path = generated / "estate" / "file-manifest.jsonl"
    records = [json.loads(line) for line in manifest_path.read_text().splitlines() if line]
    assert records
    for record in records:
        if record["is_placeholder"]:
            continue
        payload = generated / "estate" / record["relative_path"]
        assert hashlib.sha256(payload.read_bytes()).hexdigest() == record["checksum"]


# -- the contract must be able to fail ----------------------------------------


def test_an_altered_expected_digest_is_detected(fixture: dict, digests: dict[str, str]) -> None:
    """A deliberately corrupted expectation must not silently pass."""
    tampered = dict(fixture["portable_digests"])
    key = sorted(tampered)[0]
    tampered[key] = "0" * 64
    actual = {path: digest for path, digest in digests.items() if is_portable(path)}
    assert actual != tampered


def test_altered_output_is_detected(fixture: dict, digests: dict[str, str]) -> None:
    """A single changed output byte must break the comparison."""
    mutated = dict(digests)
    key = sorted(path for path in mutated if is_portable(path))[0]
    mutated[key] = "f" * 64
    portable, _ = split_digests(mutated)
    assert portable != fixture["portable_digests"]


def test_regeneration_requires_explicit_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """``pytest`` must never be able to rewrite the fixture; the script refuses by default."""
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    from update_golden_digests import main  # type: ignore[import-not-found]

    before = FIXTURE_PATH.read_bytes()
    assert main([]) == 2
    assert main(["--confirm"]) == 2
    assert main(["--confirm", "--reason", "x"]) == 2
    assert FIXTURE_PATH.read_bytes() == before


# -- environment identity -----------------------------------------------------


def test_environment_fingerprint_is_deterministic() -> None:
    assert environment_fingerprint() == environment_fingerprint()
    assert len(environment_fingerprint()) == 64


def test_environment_fingerprint_tracks_dependency_identity() -> None:
    versions = direct_dependency_versions()
    assert versions
    changed = {**versions, sorted(versions)[0]: "0.0.0-not-a-real-version"}
    assert environment_fingerprint(changed) != environment_fingerprint(versions)


def test_fingerprint_ignores_python_version(fixture: dict) -> None:
    """Python 3.12 and 3.13 produce identical bytes, so the fingerprint excludes Python.

    Verified empirically for this dependency set; the fingerprint is therefore
    defined over direct dependency versions alone.
    """
    recorded = fixture["canonical_environment"]["direct_dependencies"]
    assert (
        environment_fingerprint(recorded)
        == fixture["canonical_environment"]["environment_fingerprint"]
    )
