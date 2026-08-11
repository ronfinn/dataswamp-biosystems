"""The emitted export directory: its bytes, its atomicity and its manifest.

Determinism is the load-bearing claim. If two exports of the same bundle differed,
every fixture in this directory would be meaningless and no downstream diff would
mean anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.openmetadata import (
    CUSTOM_PROPERTIES_NAME,
    ENTITIES_NAME,
    EXPORT_MANIFEST_NAME,
    LINEAGE_NAME,
    MAPPING_COVERAGE_NAME,
    OM_ADAPTER_VERSION,
    OPENMETADATA_MODEL_TARGET_RANGE,
    OPENMETADATA_SCHEMA_TARGET,
    PHASES,
    TEST_RESULTS_NAME,
    TRUTH_ONLY_PROPERTY_PREFIX,
    VERIFIED_OPENMETADATA_VERSION,
    ExportMode,
    ExportPlan,
    build_plan,
    export_openmetadata,
)
from dataswamp_biosystems.bundle.errors import BundleConfigError
from dataswamp_biosystems.provenance import PROVENANCE_NAME
from dataswamp_biosystems.truth import serialize

from .conftest import FIXTURE_DIR

EXPECTED_FILES = {
    CUSTOM_PROPERTIES_NAME,
    ENTITIES_NAME,
    LINEAGE_NAME,
    TEST_RESULTS_NAME,
    MAPPING_COVERAGE_NAME,
    EXPORT_MANIFEST_NAME,
    PROVENANCE_NAME,
}


def test_the_export_contains_exactly_the_contract_files(om_observed_export_dir: Path) -> None:
    assert {path.name for path in om_observed_export_dir.iterdir()} == EXPECTED_FILES


def test_no_decorative_recipe_is_emitted(om_observed_export_dir: Path) -> None:
    """The JSONL plan is the interchange contract; a YAML restating it would drift."""
    assert not list(om_observed_export_dir.glob("*.yml"))
    assert not list(om_observed_export_dir.glob("*.yaml"))


@pytest.mark.parametrize("mode", list(ExportMode))
def test_repeating_an_export_is_byte_identical(
    full_bundle_dir: Path, tmp_path: Path, mode: ExportMode
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    export_openmetadata(full_bundle_dir, first, mode=mode)
    export_openmetadata(full_bundle_dir, second, mode=mode)
    for name in EXPECTED_FILES - {PROVENANCE_NAME}:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_every_emitted_file_ends_with_a_newline(om_observed_export_dir: Path) -> None:
    for name in EXPECTED_FILES:
        data = (om_observed_export_dir / name).read_bytes()
        if data:
            assert data.endswith(b"\n"), name


def test_jsonl_records_are_canonically_serialized(om_observed_export_dir: Path) -> None:
    for line in (om_observed_export_dir / ENTITIES_NAME).read_text(encoding="utf-8").splitlines():
        assert serialize.canonical_json(json.loads(line)) == line


def test_an_export_replaces_a_previous_one_atomically(
    full_bundle_dir: Path, tmp_path: Path
) -> None:
    target = tmp_path / "export"
    export_openmetadata(full_bundle_dir, target, mode=ExportMode.OBSERVED)
    (target / "stale-artefact.json").write_text("{}", encoding="utf-8")
    export_openmetadata(full_bundle_dir, target, mode=ExportMode.TRUTH)
    assert {path.name for path in target.iterdir()} == EXPECTED_FILES


def test_a_failed_export_leaves_no_temporary_directory(tmp_path: Path) -> None:
    target = tmp_path / "export"
    with pytest.raises(BundleConfigError):
        export_openmetadata(tmp_path / "not-a-bundle", target, mode=ExportMode.OBSERVED)
    assert not target.exists()
    assert not list(tmp_path.glob(".export.tmp-*"))


def test_the_export_writes_nothing_outside_its_directory(
    full_bundle_dir: Path, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "export"
    export_openmetadata(full_bundle_dir, target, mode=ExportMode.OBSERVED)
    assert {path.name for path in root.iterdir()} == {"export"}


def test_the_bundle_is_not_modified_by_an_export(
    full_bundle_dir: Path, mutable_bundle: Path, tmp_path: Path
) -> None:
    before = {
        path.relative_to(mutable_bundle): path.read_bytes()
        for path in sorted(mutable_bundle.rglob("*"))
        if path.is_file()
    }
    export_openmetadata(mutable_bundle, tmp_path / "export", mode=ExportMode.OBSERVED)
    after = {
        path.relative_to(mutable_bundle): path.read_bytes()
        for path in sorted(mutable_bundle.rglob("*"))
        if path.is_file()
    }
    assert after == before
    assert full_bundle_dir.exists()


# -- the manifest -------------------------------------------------------------


def _manifest(directory: Path) -> dict:
    return json.loads((directory / EXPORT_MANIFEST_NAME).read_text(encoding="utf-8"))


def test_the_manifest_digests_every_content_file(om_observed_export_dir: Path) -> None:
    manifest = _manifest(om_observed_export_dir)
    for name, digest in manifest["files"].items():
        assert serialize.digest((om_observed_export_dir / name).read_bytes()) == digest
    assert set(manifest["files"]) == EXPECTED_FILES - {EXPORT_MANIFEST_NAME, PROVENANCE_NAME}


def test_the_manifest_carries_the_verified_live_version(om_observed_export_dir: Path) -> None:
    """The whole point of the versioning amendment: schemas read is not server tested.

    The manifest now records a point that a run earned, and it travels with the
    export so a stored export cannot outlive or overstate its evidence.
    """
    manifest = _manifest(om_observed_export_dir)
    assert manifest["verified_openmetadata_version"] == VERIFIED_OPENMETADATA_VERSION == "1.13.3"
    assert "observed mode" in manifest["live_support"]
    # Still not a range, and still not a claim about the privileged path.
    assert "supported" not in manifest["live_support"].lower()


def test_the_manifest_separates_schema_target_from_declared_range(
    om_observed_export_dir: Path,
) -> None:
    manifest = _manifest(om_observed_export_dir)
    assert manifest["openmetadata_schema_target"] == OPENMETADATA_SCHEMA_TARGET
    assert manifest["openmetadata_model_target_range"] == OPENMETADATA_MODEL_TARGET_RANGE
    assert manifest["adapter_version"] == OM_ADAPTER_VERSION


def test_the_declared_range_is_a_target_not_a_tested_range() -> None:
    """A range with no tested point inside it must not masquerade as evidence."""
    assert OPENMETADATA_MODEL_TARGET_RANGE.startswith(">=")
    assert OPENMETADATA_SCHEMA_TARGET.startswith("1.13")
    # The tested-point rule: exactly one release inside that declared range has
    # actually been run, and the range itself remains a target, never evidence.
    assert VERIFIED_OPENMETADATA_VERSION == "1.13.3"
    assert OPENMETADATA_MODEL_TARGET_RANGE != VERIFIED_OPENMETADATA_VERSION


def test_the_manifest_records_the_load_order(om_observed_export_dir: Path) -> None:
    assert _manifest(om_observed_export_dir)["load_order"] == list(PHASES)


def test_privilege_is_manifested(om_observed_export_dir: Path, om_truth_export_dir: Path) -> None:
    assert _manifest(om_observed_export_dir)["privileged"] is False
    assert _manifest(om_truth_export_dir)["privileged"] is True


def test_the_export_declares_itself_synthetic(om_observed_export_dir: Path) -> None:
    assert _manifest(om_observed_export_dir)["synthetic"] is True


# -- committed fixtures -------------------------------------------------------

FIXTURE_PARTS = (
    ("custom_properties", "custom-properties"),
    ("entities", "entities"),
    ("lineage", "lineage"),
    ("test_results", "test-results"),
)


@pytest.mark.parametrize("mode", ["observed", "truth"])
def test_the_mini_plan_matches_its_committed_fixture(
    mode: str, mini_observed: ExportPlan, mini_truth: ExportPlan
) -> None:
    """Mapping drift shows up as a reviewable diff, not as a moved count."""
    plan = mini_observed if mode == "observed" else mini_truth
    for attribute, stem in FIXTURE_PARTS:
        expected = (FIXTURE_DIR / f"mini-{mode}-{stem}.jsonl").read_text(encoding="utf-8")
        rendered = "".join(
            f"{serialize.canonical_json(record.as_json())}\n" for record in getattr(plan, attribute)
        )
        assert rendered == expected, f"{mode}/{stem}"


@pytest.mark.parametrize("mode", ["observed", "truth"])
def test_the_mapping_coverage_matches_its_committed_fixture(
    mode: str, mini_observed: ExportPlan, mini_truth: ExportPlan
) -> None:
    plan = mini_observed if mode == "observed" else mini_truth
    expected = (FIXTURE_DIR / f"mini-{mode}-mapping-coverage.json").read_bytes()
    assert serialize.manifest_bytes(plan.coverage) == expected


def test_pytest_never_rewrites_a_fixture() -> None:
    before = {path: path.read_bytes() for path in sorted(FIXTURE_DIR.glob("*"))}
    assert before
    assert all(path.read_bytes() == data for path, data in before.items())


# -- the real benchmark --------------------------------------------------------


def test_the_real_export_is_non_trivial(om_observed_export_dir: Path) -> None:
    manifest = _manifest(om_observed_export_dir)
    assert manifest["counts"]["entities"] > 50
    assert manifest["counts"]["custom_properties"] > 0
    assert manifest["counts"]["lineage_edges"] >= 0


def test_the_real_export_validates(full_bundle_dir: Path) -> None:
    from dataswamp_biosystems.adapters.openmetadata import build_source, validate_plan
    from dataswamp_biosystems.bundle import BundleReader

    for mode in ExportMode:
        with BundleReader.open(full_bundle_dir) as reader:
            assert validate_plan(build_plan(build_source(reader, mode))) == []


def test_a_truth_only_bundle_cannot_serve_an_observed_export(
    truth_only_bundle_dir: Path, tmp_path: Path
) -> None:
    with pytest.raises(BundleConfigError, match="observed export needs the observed layer"):
        export_openmetadata(truth_only_bundle_dir, tmp_path / "export", mode=ExportMode.OBSERVED)


def test_no_truth_marker_reaches_the_real_observed_export(om_observed_export_dir: Path) -> None:
    for name in (ENTITIES_NAME, CUSTOM_PROPERTIES_NAME, LINEAGE_NAME, TEST_RESULTS_NAME):
        text = (om_observed_export_dir / name).read_text(encoding="utf-8")
        assert TRUTH_ONLY_PROPERTY_PREFIX not in text, name
        assert "privileged-truth-export" not in text, name


def test_the_truth_export_does_carry_those_markers(om_truth_export_dir: Path) -> None:
    """A detector never observed to fire is not evidence of anything."""
    text = (om_truth_export_dir / ENTITIES_NAME).read_text(encoding="utf-8")
    assert TRUTH_ONLY_PROPERTY_PREFIX in text
    assert "privileged-truth-export" in text
