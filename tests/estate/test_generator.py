"""Tests for estate planning, record building, and determinism."""

from __future__ import annotations

from dataswamp_biosystems.estate import Profile
from dataswamp_biosystems.estate.generator import (
    ESTATE_GENERATOR_VERSION,
    iter_file_plans,
    iter_records,
)
from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.ids import is_slug
from tests.estate.conftest import TEST_SEED


def _records(graph: TruthGraph, profile: Profile) -> list:
    return [record for _p, _c, record, _s in iter_records(graph, profile, TEST_SEED)]


def test_all_asset_ids_exist_in_truth_graph(graph: TruthGraph) -> None:
    asset_ids = {a.id for a in graph.datasets} | {p.id for p in graph.data_products}
    for record in _records(graph, Profile.TINY):
        assert record.asset_id in asset_ids


def test_file_ids_are_unique_valid_slugs(graph: TruthGraph) -> None:
    records = _records(graph, Profile.DEMO)
    ids = [r.id for r in records]
    assert len(ids) == len(set(ids))
    assert all(is_slug(i) for i in ids)


def test_records_are_stamped_with_generator_and_seed(graph: TruthGraph) -> None:
    for record in _records(graph, Profile.TINY):
        assert record.generator_version == ESTATE_GENERATOR_VERSION
        assert record.generation_seed == TEST_SEED
        assert record.synthetic is True
        assert record.logical_bytes >= record.physical_bytes


def test_tiny_covers_every_required_format(graph: TruthGraph) -> None:
    formats = {r.file_format for r in _records(graph, Profile.TINY)}
    required = {
        "h5ad",
        "parquet",
        "ome-tiff",
        "png",
        "geojson",
        "vcf",
        "bed",
        "matrix-market",
        "csv",
        "tsv",
        "json",
        "yaml",
        "gzip-text",
    }
    assert required <= formats


def test_tiny_includes_every_placeholder_type(graph: TruthGraph) -> None:
    placeholders = {r.file_format for r in _records(graph, Profile.TINY) if r.is_placeholder}
    assert {"bam", "cram", "dicom", "svs", "zarr"} <= placeholders


def test_tiny_spreads_across_assets(graph: TruthGraph) -> None:
    # Defects/files must not all pile onto one asset: tiny touches many assets.
    assets = {r.asset_id for r in _records(graph, Profile.TINY)}
    assert len(assets) >= 12


def test_payload_files_represent_truth_size(graph: TruthGraph) -> None:
    ds_physical = {d.id: d.physical_bytes for d in graph.datasets}
    for _p, _c, record, _s in iter_records(graph, Profile.TINY, TEST_SEED):
        if record.file_role in {"primary", "primary-bins", "primary-variants"} and (
            record.asset_id in ds_physical
        ):
            assert record.logical_bytes == ds_physical[record.asset_id]


def test_in_process_manifest_is_deterministic(graph: TruthGraph) -> None:
    first = [r.model_dump(mode="json") for r in _records(graph, Profile.TINY)]
    second = [r.model_dump(mode="json") for r in _records(graph, Profile.TINY)]
    assert first == second


def test_content_is_deterministic(graph: TruthGraph) -> None:
    first = {p.file_id: c for p, c, _r, _s in iter_records(graph, Profile.TINY, TEST_SEED)}
    second = {p.file_id: c for p, c, _r, _s in iter_records(graph, Profile.TINY, TEST_SEED)}
    assert first == second


def test_stress_prioritizes_record_count_over_bytes(graph: TruthGraph) -> None:
    records = _records(graph, Profile.STRESS)
    assert len(records) > 5000
    total_physical = sum(r.physical_bytes for r in records)
    # Minimal physical content: far below the demo profile's data volume.
    assert total_physical < 20_000_000
    assert all(not r.is_placeholder for r in records)


def test_file_plans_sorted_by_id(graph: TruthGraph) -> None:
    plans = iter_file_plans(graph, Profile.TINY, TEST_SEED)
    assert [p.file_id for p in plans] == sorted(p.file_id for p in plans)
