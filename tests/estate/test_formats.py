"""Unit tests for the deterministic format writers.

Every genuine format must be byte-deterministic for a fixed seed and produce a
structurally valid, re-readable file. Placeholders must be declared, not faked.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from random import Random

import anndata as ad
import pyarrow.parquet as pq
import pytest
import tifffile
import yaml
from PIL import Image

from dataswamp_biosystems.estate.formats import (
    GenContext,
    format_spec,
    genuine_format_names,
    placeholder_format_names,
    placeholder_spec,
    placeholder_stub_bytes,
)

CTX = GenContext(seed=20260717, generator_version="1.0.0", epoch_anchor="2024-01-08")


def _bytes(name: str, seed: int = 1) -> bytes:
    return format_spec(name).writer(Random(seed), CTX)


@pytest.mark.parametrize("name", genuine_format_names())
def test_writer_is_deterministic_and_nonempty(name: str) -> None:
    first = _bytes(name)
    second = _bytes(name)
    assert first == second
    assert len(first) > 0


@pytest.mark.parametrize("name", genuine_format_names())
def test_writer_depends_on_seed(name: str) -> None:
    # Different seeds should (for these content shapes) yield different bytes.
    assert _bytes(name, seed=1) != _bytes(name, seed=2)


def test_csv_and_tsv_parse() -> None:
    rows = list(csv.reader(io.StringIO(_bytes("csv").decode())))
    assert rows[0] == ["feature", "count", "fraction"]
    trows = list(csv.reader(io.StringIO(_bytes("tsv").decode()), delimiter="\t"))
    assert trows[0] == ["barcode", "feature", "count"]


def test_json_yaml_geojson_jsonl_parse() -> None:
    assert json.loads(_bytes("json"))["synthetic"] is True
    assert yaml.safe_load(_bytes("yaml"))["synthetic"] is True
    gj = json.loads(_bytes("geojson"))
    assert gj["type"] == "FeatureCollection" and gj["features"]
    lines = _bytes("jsonl").decode().splitlines()
    assert all(json.loads(line)["synthetic"] is True for line in lines)


def test_vcf_bed_mtx_headers() -> None:
    assert _bytes("vcf").decode().startswith("##fileformat=VCFv4.2")
    assert "\t" in _bytes("bed").decode().splitlines()[1]
    assert _bytes("matrix-market").decode().startswith("%%MatrixMarket")


def test_fastq_structure() -> None:
    lines = _bytes("fastq").decode().splitlines()
    assert lines[0].startswith("@") and lines[2] == "+"
    assert len(lines[1]) == len(lines[3])


def test_gzip_text_roundtrips_and_has_zero_mtime() -> None:
    raw = _bytes("gzip-text")
    assert gzip.decompress(raw).decode().startswith("synthetic-log-line 0")
    # Bytes 4..8 of a gzip stream are the mtime; we force it to zero.
    assert raw[4:8] == b"\x00\x00\x00\x00"


def test_parquet_reads_back() -> None:
    table = pq.read_table(io.BytesIO(_bytes("parquet")))
    assert table.num_rows == 48
    assert set(table.column_names) == {"feature", "count", "fraction"}


def test_png_reads_back() -> None:
    image = Image.open(io.BytesIO(_bytes("png")))
    assert image.size == (64, 64)


def test_ome_tiff_reads_back_as_ome(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "x.ome.tif"
    path.write_bytes(_bytes("ome-tiff"))
    with tifffile.TiffFile(path) as handle:
        assert handle.is_ome
        assert handle.series[0].shape == (48, 48)


def test_h5ad_reads_back_as_anndata(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "x.h5ad"
    path.write_bytes(_bytes("h5ad"))
    adata = ad.read_h5ad(path)
    assert adata.shape == (20, 12)


def test_placeholders_are_declared_not_faked() -> None:
    for name in placeholder_format_names():
        spec = placeholder_spec(name)
        stub = placeholder_stub_bytes(name)
        assert b"PLACEHOLDER" in stub
        assert spec.intended_format == name
        assert spec.marker_extension.endswith(".placeholder")
