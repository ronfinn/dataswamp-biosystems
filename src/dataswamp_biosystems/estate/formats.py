"""Deterministic content writers for every supported estate file format.

Each genuine-format writer takes a seeded :class:`random.Random` (and a small
context) and returns the file's bytes. Determinism is structural: all
randomness comes from the passed generator, no wall-clock is read, and every
library writer that would otherwise embed a timestamp or UUID is called so that
it does not (gzip ``mtime=0``, TIFF ``datetime=False`` with a fixed OME UUID,
HDF5/AnnData writers that embed no wall-clock in this environment).

Genuine formats produce structurally valid, re-readable files. Formats that are
too heavy or unjustified to fake honestly (BAM, CRAM, DICOM, SVS, large Zarr)
are *not* here; they are emitted as explicitly-declared placeholders by
:mod:`.generator`, never as arbitrary bytes behind a real extension.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from random import Random

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import tifffile
import yaml
from PIL import Image

# A short, fictional gene panel used to give tabular/matrix content plausible
# (but wholly invented) labels. No real gene symbols are used.
_GENES = [f"DSB-GENE-{i:04d}" for i in range(64)]


@dataclass(frozen=True)
class GenContext:
    """Immutable context passed to content writers."""

    seed: int
    generator_version: str
    epoch_anchor: str


@dataclass(frozen=True)
class FormatSpec:
    """A genuine, re-readable file format and how to write it."""

    name: str
    extension: str
    mime_type: str
    writer: Callable[[Random, GenContext], bytes]


@dataclass(frozen=True)
class PlaceholderSpec:
    """A declared stand-in for a format not generated genuinely."""

    intended_format: str
    marker_extension: str  # appended after the intended extension, e.g. ".bam.placeholder"
    intended_mime_type: str
    reason: str
    limitations: str


def _np(rng: Random) -> np.random.Generator:
    """Derive a numpy Generator deterministically from a seeded Random."""
    return np.random.default_rng(rng.getrandbits(63))


# --- text / tabular ---------------------------------------------------------


def _rows(rng: Random, n: int) -> list[tuple[str, int, float]]:
    npr = _np(rng)
    counts = npr.integers(0, 5000, size=n)
    fracs = npr.random(size=n).round(4)
    return [(_GENES[i % len(_GENES)], int(counts[i]), float(fracs[i])) for i in range(n)]


def write_csv(rng: Random, ctx: GenContext) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["feature", "count", "fraction"])
    for name, count, frac in _rows(rng, 24):
        writer.writerow([name, count, frac])
    return buf.getvalue().encode("utf-8")


def write_tsv(rng: Random, ctx: GenContext) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    writer.writerow(["barcode", "feature", "count"])
    npr = _np(rng)
    barcodes = [f"CELL-{i:05d}" for i in range(16)]
    for i, bc in enumerate(barcodes):
        writer.writerow([bc, _GENES[i % len(_GENES)], int(npr.integers(0, 3000))])
    return buf.getvalue().encode("utf-8")


def write_json(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    payload = {
        "schema": "dataswamp-estate/metadata",
        "epoch_anchor": ctx.epoch_anchor,
        "synthetic": True,
        "metrics": {
            "n_features": 24,
            "n_records": int(npr.integers(1000, 50000)),
            "mean_quality": round(float(npr.random()), 3),
        },
    }
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def write_yaml(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    payload = {
        "schema": "dataswamp-estate/metadata",
        "generator_version": ctx.generator_version,
        "epoch_anchor": ctx.epoch_anchor,
        "synthetic": True,
        "processing": {
            "pipeline": "swamp-standard",
            "n_records": int(npr.integers(1000, 50000)),
        },
    }
    text = yaml.safe_dump(payload, sort_keys=True, default_flow_style=False)
    return text.encode("utf-8")


def write_jsonl(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    lines = []
    for i in range(8):
        row = {"index": i, "value": int(npr.integers(0, 1000)), "synthetic": True}
        lines.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_geojson(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    features = []
    for i in range(6):
        x = float(npr.integers(0, 1000))
        y = float(npr.integers(0, 1000))
        features.append(
            {
                "type": "Feature",
                "id": f"region-{i:03d}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[x, y], [x + 10, y], [x + 10, y + 10], [x, y + 10], [x, y]]],
                },
                "properties": {"label": f"roi-{i:03d}", "synthetic": True},
            }
        )
    payload = {"type": "FeatureCollection", "features": features}
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def write_vcf(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    header = [
        "##fileformat=VCFv4.2",
        "##source=dataswamp-synthetic",
        '##INFO=<ID=SYN,Number=0,Type=Flag,Description="Synthetic record">',
        '##FILTER=<ID=PASS,Description="All filters passed">',
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
    ]
    bases = ["A", "C", "G", "T"]
    rows = []
    pos = 1000
    for i in range(12):
        pos += int(npr.integers(10, 500))
        ref = bases[int(npr.integers(0, 4))]
        alt = bases[int(npr.integers(0, 4))]
        if alt == ref:
            alt = bases[(bases.index(ref) + 1) % 4]
        qual = int(npr.integers(20, 60))
        rows.append(f"chr1\t{pos}\tsyn{i:04d}\t{ref}\t{alt}\t{qual}\tPASS\tSYN")
    return ("\n".join(header + rows) + "\n").encode("utf-8")


def write_bed(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    lines = ['track name="dataswamp-synthetic" description="synthetic regions"']
    start = 0
    for i in range(12):
        start += int(npr.integers(100, 1000))
        end = start + int(npr.integers(50, 500))
        lines.append(f"chr1\t{start}\t{end}\tregion-{i:04d}\t{int(npr.integers(0, 1000))}\t+")
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_matrix_market(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    n_rows, n_cols = 16, 8
    entries: list[tuple[int, int, int]] = []
    for r in range(1, n_rows + 1):
        for c in range(1, n_cols + 1):
            v = int(npr.integers(0, 6))
            if v > 0:
                entries.append((r, c, v))
    lines = ["%%MatrixMarket matrix coordinate integer general", "% synthetic count matrix"]
    lines.append(f"{n_rows} {n_cols} {len(entries)}")
    lines.extend(f"{r} {c} {v}" for r, c, v in entries)
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_fastq(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    bases = np.array(list("ACGT"))
    records = []
    for i in range(8):
        seq = "".join(bases[npr.integers(0, 4, size=40)])
        qual = "".join(chr(33 + int(q)) for q in npr.integers(20, 40, size=40))
        records.append(f"@SYN:{i:04d}\n{seq}\n+\n{qual}")
    return ("\n".join(records) + "\n").encode("utf-8")


def write_gzip_text(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    lines = [f"synthetic-log-line {i} value={int(npr.integers(0, 1000))}" for i in range(64)]
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    buf = io.BytesIO()
    # mtime=0 so the gzip header carries no wall-clock and bytes stay stable.
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as handle:
        handle.write(raw)
    return buf.getvalue()


# --- binary / scientific ----------------------------------------------------


def write_parquet(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    n = 48
    table = pa.table(
        {
            "feature": pa.array([_GENES[i % len(_GENES)] for i in range(n)], type=pa.string()),
            "count": pa.array(npr.integers(0, 10000, size=n), type=pa.int32()),
            "fraction": pa.array(npr.random(size=n).round(5), type=pa.float64()),
        }
    )
    buf = pa.BufferOutputStream()
    pq.write_table(table, buf, compression="snappy")
    return bytes(buf.getvalue().to_pybytes())


def write_png(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    arr = npr.integers(0, 256, size=(64, 64), dtype=np.int64).astype(np.uint8)
    image = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def write_ome_tiff(rng: Random, ctx: GenContext) -> bytes:
    npr = _np(rng)
    arr = npr.integers(0, 256, size=(48, 48), dtype=np.int64).astype(np.uint8)
    # Hand-built OME-XML with a FIXED UUID: tifffile's automatic OME writer emits
    # a random UUID that would break byte-determinism, so we supply our own.
    ome_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06" '
        'UUID="urn:uuid:00000000-0000-0000-0000-000000000001">'
        '<Image ID="Image:0" Name="synthetic">'
        '<Pixels ID="Pixels:0" DimensionOrder="XYZCT" Type="uint8" '
        'SizeX="48" SizeY="48" SizeZ="1" SizeC="1" SizeT="1">'
        '<Channel ID="Channel:0:0" SamplesPerPixel="1"/>'
        "<TiffData/></Pixels></Image></OME>"
    )
    buf = io.BytesIO()
    tifffile.imwrite(
        buf,
        arr,
        description=ome_xml,
        software="dataswamp",
        datetime=False,
        metadata=None,
    )
    return buf.getvalue()


def write_h5ad(rng: Random, ctx: GenContext) -> bytes:
    import anndata as ad  # imported lazily; heavy transitive dependency

    npr = _np(rng)
    n_obs, n_var = 20, 12
    x = npr.integers(0, 200, size=(n_obs, n_var)).astype(np.float32)
    adata = ad.AnnData(
        X=x,
        obs={"cell_type": np.array(["type-a", "type-b"] * (n_obs // 2))},
        var={"gene_symbol": np.array([_GENES[i % len(_GENES)] for i in range(n_var)])},
    )
    adata.obs_names = [f"cell-{i:05d}" for i in range(n_obs)]
    adata.var_names = [f"gene-{i:04d}" for i in range(n_var)]
    adata.uns["synthetic"] = True
    # anndata writes to a path, not a buffer; stage in a temp file and read back.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "a.h5ad"
        adata.write_h5ad(path)
        return path.read_bytes()


# --- registry ---------------------------------------------------------------

_FORMATS: dict[str, FormatSpec] = {
    spec.name: spec
    for spec in [
        FormatSpec("csv", ".csv", "text/csv", write_csv),
        FormatSpec("tsv", ".tsv", "text/tab-separated-values", write_tsv),
        FormatSpec("json", ".json", "application/json", write_json),
        FormatSpec("yaml", ".yaml", "application/yaml", write_yaml),
        FormatSpec("jsonl", ".jsonl", "application/x-ndjson", write_jsonl),
        FormatSpec("geojson", ".geojson", "application/geo+json", write_geojson),
        FormatSpec("vcf", ".vcf", "text/vcf", write_vcf),
        FormatSpec("bed", ".bed", "text/plain", write_bed),
        FormatSpec("matrix-market", ".mtx", "text/plain", write_matrix_market),
        FormatSpec("fastq", ".fastq", "text/plain", write_fastq),
        FormatSpec("gzip-text", ".txt.gz", "application/gzip", write_gzip_text),
        FormatSpec("parquet", ".parquet", "application/vnd.apache.parquet", write_parquet),
        FormatSpec("png", ".png", "image/png", write_png),
        FormatSpec("ome-tiff", ".ome.tif", "image/tiff", write_ome_tiff),
        FormatSpec("h5ad", ".h5ad", "application/x-hdf5", write_h5ad),
    ]
}

_PLACEHOLDERS: dict[str, PlaceholderSpec] = {
    spec.intended_format: spec
    for spec in [
        PlaceholderSpec(
            "bam",
            ".bam.placeholder",
            "application/x-bam",
            "Aligned-read BAM is a large binary; a genuine example is unjustified at estate scale.",
            "Not a valid BAM; carries no alignment records. Use the sidecar for represented size.",
        ),
        PlaceholderSpec(
            "cram",
            ".cram.placeholder",
            "application/x-cram",
            "Reference-compressed CRAM is heavy and needs a reference; unjustified at this scale.",
            "Not a valid CRAM; carries no alignment records.",
        ),
        PlaceholderSpec(
            "dicom",
            ".dcm.placeholder",
            "application/dicom",
            "DICOM series are large and numerous; a genuine study is unjustified at estate scale.",
            "Not a valid DICOM object; a PNG preview accompanies the asset instead.",
        ),
        PlaceholderSpec(
            "svs",
            ".svs.placeholder",
            "application/octet-stream",
            "Aperio SVS whole-slide images are gigabyte-scale pyramidal TIFFs; too heavy to fake.",
            "Not a valid SVS; an OME-TIFF thumbnail accompanies the asset instead.",
        ),
        PlaceholderSpec(
            "zarr",
            ".zarr.placeholder",
            "application/octet-stream",
            "Large Zarr stores are multi-file and heavy; a genuine store is unjustified here.",
            "Not a valid Zarr store; represents a chunked array hierarchy only.",
        ),
    ]
}


def format_spec(name: str) -> FormatSpec:
    """Return the genuine-format spec named ``name``."""
    return _FORMATS[name]


def placeholder_spec(intended_format: str) -> PlaceholderSpec:
    """Return the placeholder spec for ``intended_format``."""
    return _PLACEHOLDERS[intended_format]


def genuine_format_names() -> list[str]:
    """Return every genuine format name (sorted, for stable iteration)."""
    return sorted(_FORMATS)


def placeholder_format_names() -> list[str]:
    """Return every placeholder intended-format name (sorted)."""
    return sorted(_PLACEHOLDERS)


def placeholder_stub_bytes(intended_format: str) -> bytes:
    """Return the fixed, unambiguous marker content for a placeholder stub."""
    spec = _PLACEHOLDERS[intended_format]
    return (
        "DATASWAMP-BIOSYSTEMS PLACEHOLDER\n"
        f"intended_format={spec.intended_format}\n"
        "placeholder=true synthetic=true\n"
        "This file is NOT a valid scientific binary. See the .placeholder.json sidecar.\n"
    ).encode()


__all__ = [
    "GenContext",
    "FormatSpec",
    "PlaceholderSpec",
    "format_spec",
    "placeholder_spec",
    "genuine_format_names",
    "placeholder_format_names",
    "placeholder_stub_bytes",
]
