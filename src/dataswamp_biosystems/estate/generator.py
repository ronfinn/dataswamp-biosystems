"""Derive a physical file estate from the truth graph, deterministically.

The estate is a *consumer* of the truth graph: it never invents assets, it
materializes files for the assets the truth graph already declares. For each
selected catalogue asset (dataset or data product) it emits a small, genuine
file *set* whose shape depends on the asset's modality group, plus explicitly
declared placeholders for heavy binaries. Every file links back to its truth
asset id.

Determinism is structural: assets are iterated in sorted order, file content is
drawn from ``sub_rng(seed, "content", file_id)`` (so it depends only on the
file's stable id), sizes are integer bytes, and no wall-clock is read. The same
truth graph, profile, generator version, and seed produce byte-identical files
and manifest.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from dataswamp_biosystems.estate.entities import (
    CHECKSUM_ALGORITHM,
    EstateMeta,
    FileManifestRecord,
    PlaceholderSidecar,
)
from dataswamp_biosystems.estate.formats import (
    GenContext,
    format_spec,
    placeholder_spec,
    placeholder_stub_bytes,
)
from dataswamp_biosystems.estate.profiles import BuildMode, Profile, profile_spec
from dataswamp_biosystems.truth import ids, serialize
from dataswamp_biosystems.truth.entities import CatalogueAsset, DataProduct, Dataset
from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.rng import sub_rng

ESTATE_SCHEMA_VERSION = 1
ESTATE_GENERATOR_VERSION = "1.0.0"

# Placeholder MIME recorded on the stub's manifest row (the *intended* MIME lives
# in the sidecar).
_PLACEHOLDER_STUB_MIME = "application/octet-stream"


@dataclass(frozen=True)
class FileSlot:
    """One file in a modality group's file set."""

    role: str
    fmt: str  # genuine format name, or placeholder intended-format name
    is_placeholder: bool
    # True when this file stands in for the asset's large scientific payload, so
    # its represented logical size is taken from the truth dataset rather than
    # from the tiny bytes actually written.
    represents_payload: bool = False


# Per modality group, the deterministic file set. Every group's set is written in
# full for the tiny and demo profiles. Roles are unique within a set.
_FILE_SETS: dict[str, list[FileSlot]] = {
    "scrna-seq": [
        FileSlot("primary", "h5ad", False, represents_payload=True),
        FileSlot("counts-matrix", "matrix-market", False),
        FileSlot("barcodes", "tsv", False),
        FileSlot("features", "tsv", False),
        FileSlot("metrics", "csv", False),
        FileSlot("thumbnail", "png", False),
        FileSlot("metadata", "yaml", False),
        FileSlot("reads-compressed", "gzip-text", False),
    ],
    "visium-hd": [
        FileSlot("primary-bins", "parquet", False, represents_payload=True),
        FileSlot("spot-geometry", "geojson", False),
        FileSlot("thumbnail", "png", False),
        FileSlot("metrics", "csv", False),
        FileSlot("spatial-metadata", "json", False),
        FileSlot("metadata", "yaml", False),
        FileSlot("spatial-store", "zarr", True, represents_payload=True),
    ],
    "wgs-wes": [
        FileSlot("primary-variants", "vcf", False, represents_payload=True),
        FileSlot("target-regions", "bed", False),
        FileSlot("qc-metrics", "tsv", False),
        FileSlot("reads", "fastq", False),
        FileSlot("variants-compressed", "gzip-text", False),
        FileSlot("metadata", "yaml", False),
        FileSlot("alignment", "bam", True, represents_payload=True),
        FileSlot("alignment-archive", "cram", True, represents_payload=True),
    ],
    "digital-pathology": [
        FileSlot("thumbnail", "ome-tiff", False),
        FileSlot("preview", "png", False),
        FileSlot("annotations", "geojson", False),
        FileSlot("slide-metadata", "json", False),
        FileSlot("metadata", "yaml", False),
        FileSlot("whole-slide", "svs", True, represents_payload=True),
    ],
    "radiology": [
        FileSlot("preview", "png", False),
        FileSlot("series-index", "csv", False),
        FileSlot("metadata", "json", False),
        FileSlot("acquisition", "yaml", False),
        FileSlot("primary-series", "dicom", True, represents_payload=True),
    ],
    "functional-genomics": [
        FileSlot("primary", "h5ad", False, represents_payload=True),
        FileSlot("guide-counts", "matrix-market", False),
        FileSlot("guides", "csv", False),
        FileSlot("screen-metrics", "tsv", False),
        FileSlot("thumbnail", "png", False),
        FileSlot("metadata", "yaml", False),
        FileSlot("screen-metadata", "json", False),
    ],
    "reference": [
        FileSlot("primary", "parquet", False, represents_payload=True),
        FileSlot("index", "csv", False),
        FileSlot("metadata", "json", False),
        FileSlot("provenance", "yaml", False),
    ],
    "multimodal": [
        FileSlot("component-manifest", "jsonl", False),
        FileSlot("components", "csv", False),
        FileSlot("product", "json", False),
        FileSlot("metadata", "yaml", False),
    ],
}

# Stress mode emits many tiny catalogue shards per asset instead of a file set.
_STRESS_SLOT_FORMAT = "jsonl"


@dataclass(frozen=True)
class FilePlan:
    """A planned file: everything needed to materialize and describe it."""

    file_id: str
    asset_id: str
    modality: str
    modality_group: str
    role: str
    fmt: str
    is_placeholder: bool
    represents_payload: bool
    relative_path: str
    # The truth dataset's represented physical size, when the asset is a dataset
    # (data products have no physical size). Used only for payload files.
    dataset_physical_bytes: int | None


def gen_context(graph: TruthGraph, seed: int) -> GenContext:
    """Build the content-writer context from the truth graph and seed."""
    return GenContext(
        seed=seed,
        generator_version=ESTATE_GENERATOR_VERSION,
        epoch_anchor=graph.meta.epoch_anchor,
    )


def build_meta(graph: TruthGraph, profile: Profile, seed: int) -> EstateMeta:
    """Build the estate provenance metadata."""
    spec = profile_spec(profile)
    return EstateMeta(
        generator_version=ESTATE_GENERATOR_VERSION,
        schema_version=ESTATE_SCHEMA_VERSION,
        seed=seed,
        profile=profile.value,
        epoch_anchor=graph.meta.epoch_anchor,
        truth_generator_version=graph.meta.generator_version,
        truth_seed=graph.meta.seed,
        budget_bytes=spec.budget_bytes,
    )


def _asset_code(asset_id: str) -> str:
    for prefix in ("ds-", "dp-"):
        if asset_id.startswith(prefix):
            return asset_id[len(prefix) :]
    return asset_id


def _select_datasets(graph: TruthGraph, profile: Profile) -> list[Dataset]:
    spec = profile_spec(profile)
    by_group: dict[str, list[Dataset]] = {}
    for dataset in graph.datasets:
        by_group.setdefault(dataset.modality_group, []).append(dataset)
    selected: list[Dataset] = []
    for group in sorted(by_group):
        items = sorted(by_group[group], key=lambda d: d.id)
        if spec.select_all:
            selected.extend(items)
        else:
            cap = spec.reference_assets if group == "reference" else spec.assets_per_group
            selected.extend(items[:cap])
    return selected


def _select_products(graph: TruthGraph, profile: Profile) -> list[DataProduct]:
    spec = profile_spec(profile)
    items = sorted(graph.data_products, key=lambda p: p.id)
    return list(items) if spec.select_all else items[: spec.product_assets]


def _full_set_plans(asset: CatalogueAsset, physical_bytes: int | None) -> list[FilePlan]:
    slots = _FILE_SETS.get(asset.modality_group)
    if slots is None:  # pragma: no cover - every modality group is mapped
        raise KeyError(f"no file set defined for modality group {asset.modality_group!r}")
    code = _asset_code(asset.id)
    plans: list[FilePlan] = []
    for index, slot in enumerate(slots, start=1):
        file_id = ids.join("gf", code, slot.role, ids.ordinal(index))
        filename = _filename(slot)
        relative_path = f"files/{asset.modality_group}/{code}/{filename}"
        plans.append(
            FilePlan(
                file_id=file_id,
                asset_id=asset.id,
                modality=asset.modality,
                modality_group=asset.modality_group,
                role=slot.role,
                fmt=slot.fmt,
                is_placeholder=slot.is_placeholder,
                represents_payload=slot.represents_payload,
                relative_path=relative_path,
                dataset_physical_bytes=physical_bytes,
            )
        )
    return plans


def _stress_plans(asset: CatalogueAsset) -> list[FilePlan]:
    spec = profile_spec(Profile.STRESS)
    code = _asset_code(asset.id)
    plans: list[FilePlan] = []
    for index in range(1, spec.shards_per_asset + 1):
        file_id = ids.join("gf", code, "shard", ids.ordinal(index))
        filename = f"shard-{ids.ordinal(index)}.jsonl"
        relative_path = f"files/{asset.modality_group}/{code}/{filename}"
        plans.append(
            FilePlan(
                file_id=file_id,
                asset_id=asset.id,
                modality=asset.modality,
                modality_group=asset.modality_group,
                role="shard",
                fmt=_STRESS_SLOT_FORMAT,
                is_placeholder=False,
                represents_payload=False,
                relative_path=relative_path,
                dataset_physical_bytes=None,
            )
        )
    return plans


def _filename(slot: FileSlot) -> str:
    if slot.is_placeholder:
        marker = placeholder_spec(slot.fmt).marker_extension
        return f"{slot.role}{marker}"
    return f"{slot.role}{format_spec(slot.fmt).extension}"


def iter_file_plans(graph: TruthGraph, profile: Profile, seed: int) -> list[FilePlan]:
    """Return every planned file for ``profile``, sorted by file id.

    Sorting makes the write order deterministic (so budget accounting and any
    partial-write behaviour are reproducible), independent of asset iteration.
    """
    spec = profile_spec(profile)
    plans: list[FilePlan] = []
    datasets = _select_datasets(graph, profile)
    products = _select_products(graph, profile)
    if spec.mode is BuildMode.STRESS:
        for asset in [*datasets, *products]:
            plans.extend(_stress_plans(asset))
    else:
        for dataset in datasets:
            plans.extend(_full_set_plans(dataset, dataset.physical_bytes))
        for product in products:
            plans.extend(_full_set_plans(product, None))
    plans.sort(key=lambda p: p.file_id)
    return plans


def materialize(plan: FilePlan, ctx: GenContext) -> tuple[bytes, PlaceholderSidecar | None]:
    """Produce a file's bytes (and sidecar, if a placeholder), deterministically."""
    if plan.is_placeholder:
        spec = placeholder_spec(plan.fmt)
        content = placeholder_stub_bytes(plan.fmt)
        represented = plan.dataset_physical_bytes if plan.dataset_physical_bytes else len(content)
        sidecar = PlaceholderSidecar(
            file_id=plan.file_id,
            intended_format=spec.intended_format,
            intended_mime_type=spec.intended_mime_type,
            reason=spec.reason,
            represented_logical_bytes=represented,
            limitations=spec.limitations,
            source_truth_asset_id=plan.asset_id,
            modality=plan.modality,
            generation_seed=ctx.seed,
            generator_version=ctx.generator_version,
        )
        return content, sidecar
    writer = format_spec(plan.fmt).writer
    content = writer(sub_rng(ctx.seed, "content", plan.file_id), ctx)
    return content, None


def logical_bytes_for(plan: FilePlan, physical_bytes: int) -> int:
    """Represented logical size: the truth payload size for payload files, else actual."""
    if plan.represents_payload and plan.dataset_physical_bytes:
        return plan.dataset_physical_bytes
    return physical_bytes


def build_record(plan: FilePlan, content: bytes, seed: int) -> FileManifestRecord:
    """Build the manifest record for one file from its plan and materialized bytes."""
    physical = len(content)
    mime = _PLACEHOLDER_STUB_MIME if plan.is_placeholder else format_spec(plan.fmt).mime_type
    return FileManifestRecord(
        id=plan.file_id,
        asset_id=plan.asset_id,
        relative_path=plan.relative_path,
        modality=plan.modality,
        modality_group=plan.modality_group,
        file_format=plan.fmt,
        file_role=plan.role,
        mime_type=mime,
        physical_bytes=physical,
        logical_bytes=logical_bytes_for(plan, physical),
        checksum_algorithm=CHECKSUM_ALGORITHM,
        checksum=serialize.digest(content),
        is_placeholder=plan.is_placeholder,
        generator_version=ESTATE_GENERATOR_VERSION,
        generation_seed=seed,
    )


def iter_records(
    graph: TruthGraph, profile: Profile, seed: int
) -> Iterator[tuple[FilePlan, bytes, FileManifestRecord, PlaceholderSidecar | None]]:
    """Yield ``(plan, content, record, sidecar)`` for every planned file, in id order.

    This is the single materialization path shared by the writer (which persists
    the bytes) and the validator (which recomputes and compares), so an on-disk
    estate and a freshly regenerated one can never diverge in how a file is built.
    """
    ctx = gen_context(graph, seed)
    for plan in iter_file_plans(graph, profile, seed):
        content, sidecar = materialize(plan, ctx)
        yield plan, content, build_record(plan, content, seed), sidecar


def stub_mime() -> str:
    """MIME recorded on a placeholder stub's manifest row."""
    return _PLACEHOLDER_STUB_MIME


def checksum_algorithm() -> str:
    return CHECKSUM_ALGORITHM


__all__ = [
    "ESTATE_SCHEMA_VERSION",
    "ESTATE_GENERATOR_VERSION",
    "FileSlot",
    "FilePlan",
    "gen_context",
    "build_meta",
    "iter_file_plans",
    "materialize",
    "logical_bytes_for",
    "build_record",
    "iter_records",
    "stub_mime",
    "checksum_algorithm",
]
