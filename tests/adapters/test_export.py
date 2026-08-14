"""Exporting DataHub metadata from a real benchmark bundle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.datahub import (
    COVERAGE_NAME,
    EXPORT_MANIFEST_NAME,
    MCPS_JSON_NAME,
    MCPS_JSONL_NAME,
    RECIPE_NAME,
    TAG_PRIVILEGED,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
    build_mcps,
    build_source,
    export_datahub,
    validate_export,
)
from dataswamp_biosystems.bundle import BundleConfigError, BundleReader
from dataswamp_biosystems.provenance import PROVENANCE_NAME
from dataswamp_biosystems.truth import serialize


@pytest.fixture(scope="module")
def observed_export(full_bundle_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("dh-observed") / "export"
    export_datahub(full_bundle_dir, target, mode=ExportMode.OBSERVED)
    return target


@pytest.fixture(scope="module")
def truth_export(full_bundle_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("dh-truth") / "export"
    export_datahub(full_bundle_dir, target, mode=ExportMode.TRUTH)
    return target


def _mcps(export_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (export_dir / MCPS_JSONL_NAME).read_text(encoding="utf-8").splitlines()
    ]


def test_export_writes_the_documented_files(observed_export: Path) -> None:
    for name in (
        MCPS_JSONL_NAME,
        MCPS_JSON_NAME,
        EXPORT_MANIFEST_NAME,
        RECIPE_NAME,
        COVERAGE_NAME,
        PROVENANCE_NAME,
    ):
        assert (observed_export / name).is_file(), name


def test_both_payload_forms_carry_the_same_proposals(observed_export: Path) -> None:
    array = json.loads((observed_export / MCPS_JSON_NAME).read_text(encoding="utf-8"))
    assert array == _mcps(observed_export)


def test_export_manifest_describes_the_payload(
    observed_export: Path, full_bundle_dir: Path
) -> None:
    manifest = json.loads((observed_export / EXPORT_MANIFEST_NAME).read_text(encoding="utf-8"))
    mcps = _mcps(observed_export)
    assert manifest["mode"] == "observed"
    assert manifest["privileged"] is False
    assert manifest["counts"]["aspects"] == len(mcps)
    assert manifest["counts"]["entities"] == len({mcp["entityUrn"] for mcp in mcps})
    assert (
        manifest["bundle"]["bundle_fingerprint"]
        == BundleReader.open(full_bundle_dir).manifest.bundle_fingerprint
    )
    for name, digest in manifest["files"].items():
        assert serialize.digest((observed_export / name).read_bytes()) == digest


def test_both_modes_carry_a_declared_mapping_coverage_report(
    observed_export: Path, truth_export: Path
) -> None:
    for export in (observed_export, truth_export):
        manifest = json.loads((export / EXPORT_MANIFEST_NAME).read_text(encoding="utf-8"))
        assert COVERAGE_NAME in manifest["files"]
        payload = (export / COVERAGE_NAME).read_bytes()
        assert serialize.digest(payload) == manifest["files"][COVERAGE_NAME]
        coverage = json.loads(payload.decode("utf-8"))
        assert coverage["coverage_schema_version"] == 1
        assert coverage["totals"]["concepts"] == 24
        assert coverage["totals"]["by_classification"] == {
            "exact": 4,
            "reasonable": 9,
            "lossy": 4,
            "unsupported": 7,
        }
        for row in coverage["concepts"]:
            assert (
                row["source_record_count"]
                == row["emitted_record_count"] + row["deliberately_dropped_count"]
            ), row["source_concept"]


def test_the_coverage_report_names_no_entity(observed_export: Path, full_bundle_dir: Path) -> None:
    """Aggregate counts are a privilege property, not merely a design preference.

    Per-entity coverage would let a reader infer which entities were mutated by
    differencing two exports.
    """
    rendered = (observed_export / COVERAGE_NAME).read_text(encoding="utf-8")
    with BundleReader.open(full_bundle_dir) as reader:
        ids = {str(record.get("id")) for record in reader.iter_assets()}
    assert ids
    for identifier in ids:
        assert identifier not in rendered


def test_the_real_export_validates(observed_export: Path, truth_export: Path) -> None:
    assert validate_export(_mcps(observed_export), ExportMode.OBSERVED) == []
    assert validate_export(_mcps(truth_export), ExportMode.TRUTH) == []


def test_observed_export_reveals_no_ground_truth(observed_export: Path) -> None:
    """The strongest check available: the labels simply are not in the bytes."""
    rendered = (observed_export / MCPS_JSONL_NAME).read_text(encoding="utf-8")
    assert TRUTH_ONLY_PROPERTY_PREFIX not in rendered
    assert TAG_PRIVILEGED not in rendered
    assert "expected_finding" not in rendered
    assert "rule_id" not in rendered
    assert "remediation" not in rendered


def test_observed_source_reads_only_the_observed_graph(full_bundle_dir: Path) -> None:
    """Containment, asserted structurally rather than by inspecting output."""
    opened: list[str] = []
    with BundleReader.open(full_bundle_dir) as reader:
        original = reader.path

        def spy(relative: str) -> Path:
            opened.append(relative)
            return original(relative)

        reader.path = spy  # type: ignore[method-assign]
        build_source(reader, ExportMode.OBSERVED)
    assert opened == ["observed/observed-graph.json"]


def test_truth_export_is_marked_privileged_everywhere(truth_export: Path) -> None:
    manifest = json.loads((truth_export / EXPORT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["privileged"] is True
    assert TAG_PRIVILEGED in (truth_export / MCPS_JSONL_NAME).read_text(encoding="utf-8")
    assert "PRIVILEGED" in (truth_export / RECIPE_NAME).read_text(encoding="utf-8")


def test_the_recipe_contains_no_credentials(observed_export: Path) -> None:
    recipe = (observed_export / RECIPE_NAME).read_text(encoding="utf-8")
    assert "${DATAHUB_GMS_TOKEN}" in recipe
    assert "token: " in recipe
    for line in recipe.splitlines():
        if line.strip().startswith(("token:", "password:", "api_key:")):
            assert "${" in line, "a credential must only ever be an environment reference"


def test_repeat_export_is_byte_identical(full_bundle_dir: Path, tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    export_datahub(full_bundle_dir, first, mode=ExportMode.OBSERVED)
    export_datahub(full_bundle_dir, second, mode=ExportMode.OBSERVED)
    for path in sorted(first.rglob("*")):
        if path.is_file():
            assert (second / path.relative_to(first)).read_bytes() == path.read_bytes(), path


def test_export_never_writes_into_the_bundle(full_bundle_dir: Path, tmp_path: Path) -> None:
    before = {
        path.relative_to(full_bundle_dir).as_posix(): path.read_bytes()
        for path in full_bundle_dir.rglob("*")
        if path.is_file()
    }
    export_datahub(full_bundle_dir, tmp_path / "export", mode=ExportMode.OBSERVED)
    after = {
        path.relative_to(full_bundle_dir).as_posix(): path.read_bytes()
        for path in full_bundle_dir.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_observed_export_needs_the_observed_layer(
    truth_only_bundle_dir: Path, tmp_path: Path
) -> None:
    with pytest.raises(BundleConfigError, match="needs the observed layer"):
        export_datahub(truth_only_bundle_dir, tmp_path / "export", mode=ExportMode.OBSERVED)


def test_truth_export_works_without_an_observed_layer(
    truth_only_bundle_dir: Path, tmp_path: Path
) -> None:
    """Labels are an optional enrichment, not a prerequisite."""
    manifest = export_datahub(truth_only_bundle_dir, tmp_path / "export", mode=ExportMode.TRUTH)
    assert manifest["counts"]["entities"] > 0


def test_observed_and_truth_exports_differ_where_defects_bite(
    full_bundle_dir: Path, tmp_path: Path
) -> None:
    """If they were identical, the observed layer would not be observable."""
    with BundleReader.open(full_bundle_dir) as reader:
        observed = build_mcps(build_source(reader, ExportMode.OBSERVED))
        truth = build_mcps(build_source(reader, ExportMode.TRUTH))
    assert observed != truth
