"""A stable, streaming reader API for benchmark bundles.

This is the supported way to consume a bundle. It exists so a third party can
use the benchmark without importing the generators, understanding the shard
layout, or reimplementing checksum verification — and so this project can change
its internals without breaking them.

Two properties are deliberate:

*Nothing is loaded eagerly.* Every ``iter_*`` method is a generator that reads
one JSONL line at a time, so a bundle far larger than memory can be walked. The
two exceptions are single-document JSON files — the manifests, the observed graph
and the evaluation summary — which are objects, not streams, and are documented
as such at their call sites.

*Reading validates.* Records are parsed into the same typed models the emitting
layer used, so a malformed bundle fails at the record that is wrong instead of
producing plausible-looking rubbish. The models are imported, never redefined:
a bundle reader that carried its own copy of the schema would drift.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Any

from pydantic import BaseModel, ValidationError

from dataswamp_biosystems.bundle.entities import BundleManifest
from dataswamp_biosystems.bundle.errors import BundleConfigError
from dataswamp_biosystems.bundle.layout import Layer, resolve_inside
from dataswamp_biosystems.bundle.verify import read_manifest, verify_bundle
from dataswamp_biosystems.estate import writer as estate_writer
from dataswamp_biosystems.estate.entities import FileManifestRecord
from dataswamp_biosystems.evaluation import writer as evaluation_writer
from dataswamp_biosystems.observed import writer as observed_writer
from dataswamp_biosystems.observed.entities import (
    ControlRecord,
    ExpectedFinding,
    ExpectedRemediation,
    RuleScopeRecord,
)
from dataswamp_biosystems.truth import writer as truth_writer

# The truth-graph shards, by the name a caller would ask for.
TRUTH_SHARDS: tuple[str, ...] = (
    "subjects.jsonl",
    "biospecimens.jsonl",
    "assays.jsonl",
    "runs.jsonl",
    "files.jsonl",
    "assets.jsonl",
    "contracts.jsonl",
    "quality.jsonl",
    "governance.jsonl",
    "lineage.jsonl",
)

# Shards consulted when resolving a stable entity id to its record. Ordered so
# the catalogue-level entities a consumer usually means come first.
_RESOLVE_ORDER: tuple[tuple[Layer, str], ...] = (
    (Layer.TRUTH, "assets.jsonl"),
    (Layer.TRUTH, "files.jsonl"),
    (Layer.TRUTH, "subjects.jsonl"),
    (Layer.TRUTH, "biospecimens.jsonl"),
    (Layer.TRUTH, "assays.jsonl"),
    (Layer.TRUTH, "runs.jsonl"),
    (Layer.TRUTH, "contracts.jsonl"),
    (Layer.TRUTH, "quality.jsonl"),
    (Layer.TRUTH, "governance.jsonl"),
    (Layer.TRUTH, "lineage.jsonl"),
    (Layer.ESTATE, estate_writer.MANIFEST_NAME),
)


class BundleReader:
    """Read one benchmark bundle. Construct with :meth:`open`."""

    def __init__(self, root: Path, manifest: BundleManifest) -> None:
        self._root = root
        self._manifest = manifest
        self._offsets: dict[str, tuple[str, int]] | None = None

    # -- lifecycle ------------------------------------------------------------

    @classmethod
    def open(
        cls, bundle_dir: Path | str, *, verify: bool = True, strict: bool = True
    ) -> BundleReader:
        """Open a bundle, verifying it first unless ``verify`` is disabled.

        Verification is on by default: reading an unverified bundle is reading
        bytes nobody has vouched for. ``verify=False`` exists for the narrow case
        of inspecting a bundle you already know to be broken.
        """
        root = Path(bundle_dir)
        manifest = verify_bundle(root, strict=strict) if verify else read_manifest(root)
        return cls(root, manifest)

    def __enter__(self) -> BundleReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    # -- identity -------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def manifest(self) -> BundleManifest:
        """The parsed bundle manifest."""
        return self._manifest

    @property
    def layers(self) -> tuple[Layer, ...]:
        return tuple(layer for layer in Layer if layer.value in self._manifest.layers)

    def has_layer(self, layer: Layer) -> bool:
        return layer.value in self._manifest.layers

    # -- low-level access -----------------------------------------------------

    def path(self, relative: str) -> Path:
        """Resolve a bundle-relative path, refusing anything that escapes the bundle."""
        resolved = resolve_inside(self._root, relative)
        if resolved is None:
            raise BundleConfigError(f"{relative!r} is not a safe path inside the bundle")
        return resolved

    def _require(self, layer: Layer, name: str) -> Path:
        if not self.has_layer(layer):
            raise BundleConfigError(f"this bundle does not include the {layer.value} layer")
        path = self.path(f"{layer.value}/{name}")
        if not path.is_file():
            raise BundleConfigError(f"{layer.value}/{name} is missing from the bundle")
        return path

    def _iter_jsonl(self, path: Path) -> Iterator[dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            for offset, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BundleConfigError(
                        f"{path} line {offset} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(row, dict):
                    raise BundleConfigError(f"{path} line {offset} is not a JSON object")
                yield row

    def _iter_models[T: BaseModel](self, model: type[T], path: Path) -> Iterator[T]:
        for offset, row in enumerate(self._iter_jsonl(path), start=1):
            try:
                yield model.model_validate(row)
            except ValidationError as exc:
                raise BundleConfigError(f"{path} record {offset} is invalid: {exc}") from exc

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BundleConfigError(f"could not read {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise BundleConfigError(f"{path} is not a JSON object")
        return payload

    # -- truth layer ----------------------------------------------------------

    def iter_truth_records(self, shard: str) -> Iterator[dict[str, Any]]:
        """Stream raw records from one truth-graph shard, one line at a time."""
        if shard not in TRUTH_SHARDS:
            raise BundleConfigError(
                f"unknown truth shard {shard!r}; expected one of {TRUTH_SHARDS}"
            )
        return self._iter_jsonl(self._require(Layer.TRUTH, shard))

    def iter_assets(self) -> Iterator[dict[str, Any]]:
        """Stream the catalogue assets (datasets and data products) from truth."""
        return self.iter_truth_records("assets.jsonl")

    def iter_lineage(self) -> Iterator[dict[str, Any]]:
        """Stream the truth lineage edges."""
        return self.iter_truth_records("lineage.jsonl")

    def truth_manifest(self) -> dict[str, Any]:
        """Return the truth-graph manifest (a single JSON object)."""
        return self._read_json(self._require(Layer.TRUTH, truth_writer.MANIFEST_NAME))

    # -- estate layer ---------------------------------------------------------

    def iter_files(self) -> Iterator[FileManifestRecord]:
        """Stream the estate's per-file manifest records."""
        return self._iter_models(
            FileManifestRecord, self._require(Layer.ESTATE, estate_writer.MANIFEST_NAME)
        )

    def open_estate_file(self, relative_path: str) -> Path:
        """Return the on-disk path of one materialized estate file.

        ``relative_path`` is the value carried by a
        :class:`~dataswamp_biosystems.estate.entities.FileManifestRecord`, which
        is already estate-relative (it starts with ``files/``). The result is
        path-checked against the bundle root, so a manifest record — a value the
        observed layer is allowed to corrupt — can never be used to read outside
        the bundle.
        """
        return self.path(f"{Layer.ESTATE.value}/{relative_path}")

    def parquet_schema(self, relative_path: str) -> Any:
        """Return the Arrow schema of one Parquet file in the estate.

        Reads only the file's footer — the row groups are never materialized —
        so schema inspection stays cheap regardless of the estate profile.
        """
        import pyarrow.parquet as pq

        path = self.open_estate_file(relative_path)
        if not path.is_file():
            raise BundleConfigError(f"no estate file at {relative_path}")
        return pq.ParquetFile(path).schema_arrow

    # -- observed layer -------------------------------------------------------

    def iter_findings(self) -> Iterator[ExpectedFinding]:
        """Stream the expected findings — the benchmark's positive class."""
        return self._iter_models(
            ExpectedFinding, self._require(Layer.OBSERVED, observed_writer.EXPECTED_FINDINGS_NAME)
        )

    def iter_remediations(self) -> Iterator[ExpectedRemediation]:
        """Stream the expected remediations, including explicit no-action decisions."""
        return self._iter_models(
            ExpectedRemediation,
            self._require(Layer.OBSERVED, observed_writer.EXPECTED_REMEDIATIONS_NAME),
        )

    def iter_controls(self) -> Iterator[ControlRecord]:
        """Stream the control partition — the benchmark's negative class."""
        return self._iter_models(
            ControlRecord, self._require(Layer.OBSERVED, observed_writer.CONTROLS_NAME)
        )

    def rule_scope(self) -> tuple[RuleScopeRecord, ...]:
        """Return every rule's selection scope.

        Materialized rather than streamed: there is one record per *rule*, not
        per entity, and callers invariably want the whole set to scope metrics.
        """
        return tuple(
            self._iter_models(
                RuleScopeRecord, self._require(Layer.OBSERVED, observed_writer.RULE_SCOPE_NAME)
            )
        )

    def observed_graph(self) -> dict[str, Any]:
        """Return the observed catalogue graph.

        A single JSON document, so this one *is* read whole. It is the defect-bearing
        view an agent under test is allowed to see.
        """
        return self._read_json(self._require(Layer.OBSERVED, observed_writer.OBSERVED_GRAPH_NAME))

    def observed_summary(self) -> dict[str, Any]:
        """Return the observed profile summary (scenario identity and totals)."""
        return self._read_json(self._require(Layer.OBSERVED, observed_writer.PROFILE_SUMMARY_NAME))

    # -- evaluation layer -----------------------------------------------------

    def evaluation_summary(self) -> dict[str, Any] | None:
        """Return the bundled evaluation summary, or ``None`` if the layer is absent.

        An optional layer returns ``None`` rather than raising: a bundle without
        a worked example is a normal bundle, not a broken one.
        """
        if not self.has_layer(Layer.EVALUATION):
            return None
        return self._read_json(
            self._require(Layer.EVALUATION, evaluation_writer.EVALUATION_SUMMARY_NAME)
        )

    # -- stable identifiers ---------------------------------------------------

    def _build_offsets(self) -> dict[str, tuple[str, int]]:
        offsets: dict[str, tuple[str, int]] = {}
        for layer, name in _RESOLVE_ORDER:
            if not self.has_layer(layer):
                continue
            relative = f"{layer.value}/{name}"
            path = self.path(relative)
            if not path.is_file():
                continue
            with path.open("rb") as handle:
                offset = handle.tell()
                for line in handle:
                    if line.strip():
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise BundleConfigError(f"{path} contains invalid JSON: {exc}") from exc
                        entity_id = row.get("id")
                        if isinstance(entity_id, str):
                            offsets.setdefault(entity_id, (relative, offset))
                    offset += len(line)
        return offsets

    def resolve(self, entity_id: str) -> dict[str, Any] | None:
        """Return the record for a stable DataSwamp id, or ``None`` if unknown.

        The id index is built once, on first use, and holds only ``id → (file,
        byte offset)`` — the records themselves are read back one at a time by
        seeking, so resolving ids never loads the bundle into memory.
        """
        if self._offsets is None:
            self._offsets = self._build_offsets()
        located = self._offsets.get(entity_id)
        if located is None:
            return None
        relative, offset = located
        with self.path(relative).open("rb") as handle:
            handle.seek(offset)
            line = handle.readline()
        row = json.loads(line.decode("utf-8"))
        return row if isinstance(row, dict) else None

    def entity_ids(self) -> tuple[str, ...]:
        """Return every resolvable stable id, sorted."""
        if self._offsets is None:
            self._offsets = self._build_offsets()
        return tuple(sorted(self._offsets))


__all__ = ["TRUTH_SHARDS", "BundleReader"]
