"""Bundle construction: layer selection, manifest contents, checksums, determinism."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dataswamp_biosystems import __version__
from dataswamp_biosystems.bundle import (
    BUNDLE_SCHEMA_VERSION,
    CHECKSUMS_NAME,
    DATA_LICENSE_NAME,
    LICENSES_NAME,
    MANIFEST_NAME,
    README_NAME,
    SCHEMA_INDEX_NAME,
    BundleConfigError,
    Layer,
    build_bundle,
    read_manifest,
)
from dataswamp_biosystems.evaluation.ground_truth import ground_truth_fingerprint
from dataswamp_biosystems.licensing import data_license_path
from dataswamp_biosystems.provenance import PROVENANCE_NAME
from dataswamp_biosystems.truth import serialize


def test_truth_only_bundle_carries_just_the_truth_layer(truth_only_bundle_dir: Path) -> None:
    manifest = read_manifest(truth_only_bundle_dir)
    assert manifest.layers == ["truth"]
    assert not (truth_only_bundle_dir / "estate").exists()
    assert not (truth_only_bundle_dir / "observed").exists()
    assert all(entry.section in {"truth", "bundle"} for entry in manifest.files), (
        "a truth-only bundle declares no other section"
    )


def test_full_bundle_declares_every_layer(full_bundle_dir: Path) -> None:
    manifest = read_manifest(full_bundle_dir)
    assert manifest.layers == ["truth", "estate", "observed", "evaluation"]
    sections = {entry.section for entry in manifest.files}
    assert sections == {"truth", "estate", "observed", "evaluation", "bundle"}


def test_evaluation_layer_is_optional(generated_layers: dict[Layer, Path], tmp_path: Path) -> None:
    """A benchmark nobody has scored yet still bundles."""
    target = tmp_path / "bundle"
    manifest = build_bundle(
        target,
        sources={
            Layer.TRUTH: generated_layers[Layer.TRUTH],
            Layer.ESTATE: generated_layers[Layer.ESTATE],
            Layer.OBSERVED: generated_layers[Layer.OBSERVED],
        },
    )
    assert "evaluation" not in manifest.layers
    assert manifest.counts["findings"] > 0
    assert "evaluated_pairs" not in manifest.counts


def test_bundle_requires_the_truth_layer(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    with pytest.raises(BundleConfigError, match="must include the truth layer"):
        build_bundle(tmp_path / "b", sources={Layer.ESTATE: generated_layers[Layer.ESTATE]})


def test_evaluation_layer_requires_its_ground_truth(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    """Scored results without the ground truth they score would be uncheckable."""
    with pytest.raises(BundleConfigError, match="requires observed"):
        build_bundle(
            tmp_path / "b",
            sources={
                Layer.TRUTH: generated_layers[Layer.TRUTH],
                Layer.EVALUATION: generated_layers[Layer.EVALUATION],
            },
        )


def test_missing_layer_directory_fails_before_writing(tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    with pytest.raises(BundleConfigError, match="no truth directory"):
        build_bundle(target, sources={Layer.TRUTH: tmp_path / "nope"})
    assert not target.exists(), "a failed build leaves no output behind"


def test_incomplete_layer_directory_is_rejected(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    broken = tmp_path / "truth"
    broken.mkdir()
    (broken / "subjects.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(BundleConfigError, match="incomplete; missing"):
        build_bundle(tmp_path / "bundle", sources={Layer.TRUTH: broken})


def test_manifest_records_the_contract_fields(full_bundle_dir: Path) -> None:
    manifest = read_manifest(full_bundle_dir)
    assert manifest.bundle_schema_version == BUNDLE_SCHEMA_VERSION
    assert manifest.dataswamp_version == __version__
    assert manifest.benchmark_release == "v-test"
    assert manifest.checksum_algorithm == "sha256"
    assert manifest.checksums_file == CHECKSUMS_NAME
    assert manifest.environment_fingerprint
    assert set(manifest.source_fingerprints) == set(manifest.layers)
    assert set(manifest.schemas) == set(manifest.layers)
    assert manifest.scenario["truth"]["seed"] == 20260717
    assert manifest.scenario["observed"]["profile"] == "demo"
    assert manifest.compatibility["python_requires"] == ">=3.12"
    # The two licences are stated independently: the software is MIT, the
    # generated data is CC BY-NC 4.0, and neither is inferable from the other.
    assert manifest.licensing["software_license"] == "MIT"
    assert manifest.licensing["generated_data_license"] == "CC-BY-NC-4.0"
    assert manifest.licensing["generated_data_license_file"] == DATA_LICENSE_NAME
    assert manifest.licensing["generated_data_license_url"] == (
        "https://creativecommons.org/licenses/by-nc/4.0/"
    )
    assert manifest.licensing["generated_data_license_since"] == "v0.1.0"
    assert "separate permission" in manifest.licensing["commercial_use"]
    assert manifest.licensing["notices_file"] == LICENSES_NAME
    assert manifest.licensing["contains_real_data"] is False


def test_manifest_counts_match_the_bundled_layers(full_bundle_dir: Path) -> None:
    manifest = read_manifest(full_bundle_dir)
    findings = (full_bundle_dir / "observed" / "expected-findings.jsonl").read_text(
        encoding="utf-8"
    )
    assert manifest.counts["findings"] == len(findings.splitlines())
    files = (full_bundle_dir / "estate" / "file-manifest.jsonl").read_text(encoding="utf-8")
    assert manifest.counts["files"] == len(files.splitlines())


def test_ground_truth_fingerprint_matches_the_bundled_observed_layer(
    full_bundle_dir: Path,
) -> None:
    manifest = read_manifest(full_bundle_dir)
    assert manifest.ground_truth_fingerprint == ground_truth_fingerprint(
        full_bundle_dir / "observed"
    )


def test_bundle_metadata_files_are_present(full_bundle_dir: Path) -> None:
    for name in (
        MANIFEST_NAME,
        CHECKSUMS_NAME,
        README_NAME,
        LICENSES_NAME,
        DATA_LICENSE_NAME,
        PROVENANCE_NAME,
    ):
        assert (full_bundle_dir / name).is_file(), name
    index = json.loads((full_bundle_dir / SCHEMA_INDEX_NAME).read_text(encoding="utf-8"))
    assert index["bundle_schema_version"] == BUNDLE_SCHEMA_VERSION
    assert set(index["layers"]) == {"truth", "estate", "observed", "evaluation"}


def test_licences_state_the_generated_data_position_without_inventing_terms(
    full_bundle_dir: Path,
) -> None:
    text = (full_bundle_dir / LICENSES_NAME).read_text(encoding="utf-8")
    assert "MIT Licence" in text
    assert "CC-BY-NC-4.0" in text
    assert "Creative Commons Attribution-NonCommercial 4.0 International" in text
    assert "separate permission from the project owner" in text
    assert DATA_LICENSE_NAME in text, "the notices point at the licence shipped beside them"
    assert "No real" in text
    assert "Permission is hereby granted" not in text, "licence text is referenced, not copied"
    assert "not separately defined" not in text
    for stale in ("DataSwamp Community Research", "LicenseRef-DataSwamp"):
        assert stale not in text, f"abandoned custom-licence wording resurfaced: {stale}"


def test_bundle_ships_the_data_licence_verbatim(full_bundle_dir: Path) -> None:
    """A consumer holding only the bundle can read the terms without the repository."""
    shipped = (full_bundle_dir / DATA_LICENSE_NAME).read_bytes()
    assert shipped == data_license_path().read_bytes(), "the bundled copy must not be a paraphrase"
    text = shipped.decode("utf-8")
    assert "CC-BY-NC-4.0" in text
    assert "MIT" in text, "the licence statement must say the software is not covered by it"


def test_the_readme_states_both_licences(full_bundle_dir: Path) -> None:
    text = (full_bundle_dir / README_NAME).read_text(encoding="utf-8")
    assert "MIT" in text
    assert "CC-BY-NC-4.0" in text
    assert DATA_LICENSE_NAME in text


def test_every_bundled_file_except_the_two_anchors_is_declared(full_bundle_dir: Path) -> None:
    manifest = read_manifest(full_bundle_dir)
    declared = {entry.path for entry in manifest.files}
    on_disk = {
        path.relative_to(full_bundle_dir).as_posix()
        for path in full_bundle_dir.rglob("*")
        if path.is_file()
    }
    assert on_disk - declared == {MANIFEST_NAME, CHECKSUMS_NAME}


def test_declared_checksums_and_sizes_match_disk(full_bundle_dir: Path) -> None:
    manifest = read_manifest(full_bundle_dir)
    for entry in manifest.files:
        data = (full_bundle_dir / entry.path).read_bytes()
        assert serialize.digest(data) == entry.sha256, entry.path
        assert len(data) == entry.bytes, entry.path


def test_checksum_record_is_sha256sum_compatible_and_covers_the_manifest(
    full_bundle_dir: Path,
) -> None:
    lines = (full_bundle_dir / CHECKSUMS_NAME).read_text(encoding="utf-8").splitlines()
    paths = []
    for line in lines:
        digest, _, path = line.partition("  ")
        assert len(digest) == 64
        paths.append(path)
        assert serialize.digest((full_bundle_dir / path).read_bytes()) == digest
    assert MANIFEST_NAME in paths
    assert CHECKSUMS_NAME not in paths
    assert paths == sorted(paths), "checksum lines are path-sorted for determinism"


def test_layer_bytes_are_copied_verbatim(
    generated_layers: dict[Layer, Path], full_bundle_dir: Path
) -> None:
    """A packager must not reinterpret what it packages."""
    source = generated_layers[Layer.OBSERVED] / "expected-findings.jsonl"
    assert (full_bundle_dir / "observed" / "expected-findings.jsonl").read_bytes() == (
        source.read_bytes()
    )


def test_repeat_build_is_byte_identical(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    build_bundle(first, sources=generated_layers, release="v-test")
    build_bundle(second, sources=generated_layers, release="v-test")
    for path in sorted(first.rglob("*")):
        if path.is_file():
            mirror = second / path.relative_to(first)
            assert mirror.read_bytes() == path.read_bytes(), path


def test_build_is_independent_of_pythonhashseed(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    """Nothing in the bundle may depend on dict/set iteration order."""
    script = (
        "from pathlib import Path;"
        "from dataswamp_biosystems.bundle import Layer, build_bundle;"
        "import sys;"
        "build_bundle(sys.argv[1], sources={Layer.TRUTH: Path(sys.argv[2])}, release='v-test')"
    )
    fingerprints = []
    for index, seed in enumerate(("0", "12345")):
        target = tmp_path / f"seeded-{index}"
        environment = {**os.environ, "PYTHONHASHSEED": seed}
        subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [sys.executable, "-c", script, str(target), str(generated_layers[Layer.TRUTH])],
            check=True,
            env=environment,
        )
        fingerprints.append(read_manifest(target).bundle_fingerprint)
    assert fingerprints[0] == fingerprints[1]


def test_embedded_datahub_export_is_declared_and_fingerprinted(
    generated_layers: dict[Layer, Path], full_bundle_dir: Path, tmp_path: Path
) -> None:
    from dataswamp_biosystems.adapters.datahub import ExportMode, export_datahub

    export_dir = tmp_path / "export"
    export_datahub(full_bundle_dir, export_dir, mode=ExportMode.OBSERVED)

    target = tmp_path / "bundle"
    manifest = build_bundle(
        target, sources=generated_layers, release="v-test", adapter_exports={"datahub": export_dir}
    )
    assert manifest.adapters["datahub"]["mode"] == "observed"
    assert manifest.adapters["datahub"]["privileged"] is False
    embedded = [e for e in manifest.files if e.path.startswith("adapters/datahub/")]
    assert embedded and all(e.section == "adapters" for e in embedded)
    assert (target / "adapters" / "datahub" / "mcps.jsonl").is_file()


def test_symlinked_input_is_refused(generated_layers: dict[Layer, Path], tmp_path: Path) -> None:
    staged = tmp_path / "truth"
    staged.mkdir()
    for path in generated_layers[Layer.TRUTH].iterdir():
        (staged / path.name).write_bytes(path.read_bytes())
    (staged / "escape.jsonl").symlink_to(tmp_path / "elsewhere.jsonl")
    with pytest.raises(BundleConfigError, match="symlink"):
        build_bundle(tmp_path / "bundle", sources={Layer.TRUTH: staged})


def test_building_refuses_an_evaluation_of_a_different_benchmark(
    generated_layers: dict[Layer, Path], tmp_path: Path
) -> None:
    """The builder catches the mismatch before it can be published."""
    other = tmp_path / "evaluation"
    other.mkdir()
    for path in generated_layers[Layer.EVALUATION].iterdir():
        (other / path.name).write_bytes(path.read_bytes())
    summary = other / "evaluation-summary.json"
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["benchmark"]["ground_truth_fingerprint"] = "d" * 64
    summary.write_bytes(serialize.manifest_bytes(payload))

    with pytest.raises(
        BundleConfigError, match="bundle an evaluation only with the state it scored"
    ):
        build_bundle(
            tmp_path / "bundle",
            sources={**generated_layers, Layer.EVALUATION: other},
        )
