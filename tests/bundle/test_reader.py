"""The public reader API: what a bundle consumer can rely on."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from dataswamp_biosystems.bundle import (
    BundleConfigError,
    BundleReader,
    BundleValidationError,
    Layer,
)
from dataswamp_biosystems.estate.entities import FileManifestRecord
from dataswamp_biosystems.observed.entities import (
    ControlRecord,
    ExpectedFinding,
    ExpectedRemediation,
)


def test_open_verifies_by_default(mutable_bundle: Path) -> None:
    target = mutable_bundle / "truth" / "assets.jsonl"
    target.write_bytes(b"tampered\n")
    with pytest.raises(BundleValidationError):
        BundleReader.open(mutable_bundle)
    # ...but an operator inspecting a known-broken bundle can still get in.
    with BundleReader.open(mutable_bundle, verify=False) as reader:
        assert reader.manifest.layers


def test_context_manager_exposes_the_manifest(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        assert reader.manifest.benchmark_release == "v-test"
        assert reader.layers == (Layer.TRUTH, Layer.ESTATE, Layer.OBSERVED, Layer.EVALUATION)
        assert reader.has_layer(Layer.OBSERVED)
        assert reader.root == full_bundle_dir


def test_iterators_are_lazy_generators(full_bundle_dir: Path) -> None:
    """Nothing is read until a consumer asks for the first record."""
    with BundleReader.open(full_bundle_dir) as reader:
        for stream in (
            reader.iter_assets(),
            reader.iter_files(),
            reader.iter_findings(),
            reader.iter_remediations(),
            reader.iter_controls(),
            reader.iter_lineage(),
        ):
            assert isinstance(stream, Iterator)
            next(iter(stream))


def test_each_record_class_parses_into_its_emitting_model(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        assert isinstance(next(iter(reader.iter_files())), FileManifestRecord)
        assert isinstance(next(iter(reader.iter_findings())), ExpectedFinding)
        assert isinstance(next(iter(reader.iter_remediations())), ExpectedRemediation)
        assert isinstance(next(iter(reader.iter_controls())), ControlRecord)


def test_counts_match_the_manifest(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        assert sum(1 for _ in reader.iter_findings()) == reader.manifest.counts["findings"]
        assert sum(1 for _ in reader.iter_files()) == reader.manifest.counts["files"]
        assert sum(1 for _ in reader.iter_controls()) == reader.manifest.counts["controls"]
        assert sum(1 for _ in reader.iter_assets()) == reader.manifest.counts["assets"]


def test_rule_scope_covers_every_rule(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        scopes = reader.rule_scope()
        assert scopes
        assert len({scope.id for scope in scopes}) == len(scopes)
        fired = {scope.id for scope in scopes if scope.selected_count}
        assert fired <= {scope.id for scope in scopes}


def test_observed_graph_and_summary_are_readable(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        graph = reader.observed_graph()
        assert graph["datasets"]
        assert reader.observed_summary()["meta"]["profile"] == "demo"


def test_evaluation_summary_is_present_when_the_layer_is(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        summary = reader.evaluation_summary()
        assert summary is not None
        assert summary["universe"]["evaluated_pairs"] > 0


def test_missing_optional_section_returns_none_rather_than_raising(
    truth_only_bundle_dir: Path,
) -> None:
    with BundleReader.open(truth_only_bundle_dir) as reader:
        assert reader.evaluation_summary() is None


def test_missing_required_layer_raises_clearly(truth_only_bundle_dir: Path) -> None:
    reader = BundleReader.open(truth_only_bundle_dir)
    with pytest.raises(BundleConfigError, match="does not include the observed layer"):
        next(iter(reader.iter_findings()))
    with pytest.raises(BundleConfigError, match="does not include the estate layer"):
        next(iter(reader.iter_files()))


def test_resolve_returns_records_for_stable_ids(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        asset = next(iter(reader.iter_assets()))
        resolved = reader.resolve(asset["id"])
        assert resolved == asset

        file_record = next(iter(reader.iter_files()))
        assert reader.resolve(file_record.asset_id) is not None

        assert reader.resolve("no-such-entity") is None


def test_resolve_covers_every_indexed_id(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        ids = reader.entity_ids()
        assert len(ids) > 100
        assert ids == tuple(sorted(ids))
        for entity_id in (ids[0], ids[len(ids) // 2], ids[-1]):
            record = reader.resolve(entity_id)
            assert record is not None and record["id"] == entity_id


def test_resolve_does_not_hold_records_in_memory(full_bundle_dir: Path) -> None:
    """The index stores locations, not records."""
    with BundleReader.open(full_bundle_dir) as reader:
        reader.entity_ids()
        index = reader._offsets  # noqa: SLF001 - asserting an implementation guarantee
        assert index is not None
        assert all(
            isinstance(value, tuple) and isinstance(value[1], int) for value in index.values()
        )


def test_parquet_schema_is_inspectable(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        parquet = [
            record
            for record in reader.iter_files()
            if record.file_format == "parquet" and not record.is_placeholder
        ]
        assert parquet, "the tiny estate materialises at least one Parquet file"
        schema = reader.parquet_schema(parquet[0].relative_path)
        assert len(schema.names) > 0


def test_parquet_schema_rejects_a_missing_file(full_bundle_dir: Path) -> None:
    reader = BundleReader.open(full_bundle_dir)
    with pytest.raises(BundleConfigError, match="no estate file"):
        reader.parquet_schema("nope.parquet")


def test_paths_escaping_the_bundle_are_refused(full_bundle_dir: Path) -> None:
    with BundleReader.open(full_bundle_dir) as reader:
        for bad in ("../secrets", "/etc/passwd", "truth/../../x"):
            with pytest.raises(BundleConfigError, match="not a safe path"):
                reader.path(bad)


def test_malformed_jsonl_names_the_offending_line(full_bundle_dir: Path, tmp_path: Path) -> None:
    broken = tmp_path / "bundle"
    shutil.copytree(full_bundle_dir, broken)
    path = broken / "observed" / "expected-findings.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[1] = "{not json\n"
    path.write_text("".join(lines), encoding="utf-8")
    reader = BundleReader.open(broken, verify=False)
    with pytest.raises(BundleConfigError, match="line 2 is not valid JSON"):
        list(reader.iter_findings())


def test_schema_violating_record_names_the_offending_record(
    full_bundle_dir: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "bundle"
    shutil.copytree(full_bundle_dir, broken)
    path = broken / "observed" / "controls.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    row = json.loads(lines[0])
    row["reason"] = "not-a-real-reason"
    lines[0] = json.dumps(row, sort_keys=True) + "\n"
    path.write_text("".join(lines), encoding="utf-8")
    reader = BundleReader.open(broken, verify=False)
    with pytest.raises(BundleConfigError, match="record 1 is invalid"):
        list(reader.iter_controls())


def test_unknown_truth_shard_is_refused(full_bundle_dir: Path) -> None:
    reader = BundleReader.open(full_bundle_dir)
    with pytest.raises(BundleConfigError, match="unknown truth shard"):
        next(iter(reader.iter_truth_records("nope.jsonl")))
