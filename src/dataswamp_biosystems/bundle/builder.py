"""Assemble a versioned, checksummed benchmark bundle from emitted layer output.

The builder is a *packager*, not a generator. It copies bytes that the truth,
estate, observed and evaluation writers already produced, records what it copied,
and adds the metadata a third party needs to verify and cite the result. It never
regenerates a layer, never rewrites one, and never reaches for the canonical
configuration — a bundle is exactly the output it was pointed at.

Output is staged in a temporary sibling directory and swapped into place with
directory renames, mirroring every other writer in this package, so a failing
build never leaves a half-copied bundle and a previous bundle is restored.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from dataswamp_biosystems import __version__
from dataswamp_biosystems.bundle.entities import (
    BUNDLE_BUILDER_VERSION,
    BUNDLE_SCHEMA_VERSION,
    SUPPORTED_BUNDLE_SCHEMA_VERSIONS,
    BundleFileEntry,
    BundleManifest,
)
from dataswamp_biosystems.bundle.errors import BundleConfigError
from dataswamp_biosystems.bundle.layout import (
    ADAPTER_MANIFEST_NAME,
    CHECKSUM_ALGORITHM,
    CHECKSUMS_NAME,
    LAYER_ORDER,
    LAYER_REQUIRED_FILES,
    LAYER_REQUIRES,
    LICENSES_NAME,
    MANIFEST_NAME,
    README_NAME,
    SCHEMA_INDEX_NAME,
    Layer,
    adapter_path,
    is_safe_relative_path,
    walk_bundle_files,
)
from dataswamp_biosystems.estate import writer as estate_writer
from dataswamp_biosystems.evaluation import writer as evaluation_writer
from dataswamp_biosystems.evaluation.ground_truth import ground_truth_fingerprint
from dataswamp_biosystems.observed import writer as observed_writer
from dataswamp_biosystems.provenance import PROVENANCE_NAME, provenance_bytes
from dataswamp_biosystems.truth import serialize
from dataswamp_biosystems.truth import writer as truth_writer

SECTION_BUNDLE = "bundle"
SECTION_ADAPTERS = "adapters"

# Files that are never copied out of a layer directory. Editor and operating
# system droppings are machine-specific; letting one into a bundle would make
# the bundle fingerprint depend on whose laptop built it.
_IGNORED_NAMES: frozenset[str] = frozenset({".DS_Store", "Thumbs.db"})


def _ignored(relative: str) -> bool:
    parts = relative.split("/")
    return any(part in _IGNORED_NAMES or part.startswith(".") for part in parts)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleConfigError(f"could not read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BundleConfigError(f"{path} is not a JSON object")
    return payload


def _collect_layer_files(source: Path, layer: Layer) -> list[tuple[str, Path]]:
    """Return ``(bundle_relative_path, source_path)`` for every file in one layer."""
    if not source.is_dir():
        raise BundleConfigError(f"no {layer.value} directory at {source}")
    collected: list[tuple[str, Path]] = []
    for relative in walk_bundle_files(source):
        if _ignored(relative):
            continue
        path = source / relative
        if path.is_symlink():
            raise BundleConfigError(
                f"{layer.value} input {path} is a symlink; bundles contain only regular files"
            )
        if not is_safe_relative_path(relative):  # pragma: no cover - defensive
            raise BundleConfigError(f"{layer.value} input path {relative!r} is not bundle-safe")
        collected.append((f"{layer.value}/{relative}", path))
    for required in LAYER_REQUIRED_FILES[layer]:
        if not (source / required).is_file():
            raise BundleConfigError(
                f"{layer.value} directory {source} is incomplete; missing {required}"
            )
    return collected


def _layer_provenance(source: Path, layer: Layer) -> dict[str, Any]:
    provenance = _read_json(source / PROVENANCE_NAME)
    recorded = provenance.get("layer")
    if recorded != layer.value:
        raise BundleConfigError(
            f"{source / PROVENANCE_NAME} describes layer {recorded!r}, expected {layer.value!r}"
        )
    return provenance


def _counts(sources: Mapping[Layer, Path]) -> dict[str, int]:
    """Return the headline counts a consumer wants before unpacking anything."""
    counts: dict[str, int] = {}
    if Layer.TRUTH in sources:
        manifest = _read_json(sources[Layer.TRUTH] / truth_writer.MANIFEST_NAME)
        entity_counts = manifest.get("counts", {})
        counts["entities"] = sum(int(value) for value in entity_counts.values())
        counts["assets"] = int(entity_counts.get("datasets", 0)) + int(
            entity_counts.get("data_products", 0)
        )
    if Layer.ESTATE in sources:
        summary = _read_json(sources[Layer.ESTATE] / estate_writer.SUMMARY_JSON_NAME)
        counts["files"] = int(summary.get("counts", {}).get("files", 0))
    if Layer.OBSERVED in sources:
        summary = _read_json(sources[Layer.OBSERVED] / observed_writer.PROFILE_SUMMARY_NAME)
        totals = summary.get("totals", {})
        counts["findings"] = int(totals.get("defects", 0))
        counts["controls"] = int(totals.get("control_records", 0))
        counts["rules_fired"] = int(totals.get("rules_fired", 0))
    if Layer.EVALUATION in sources:
        summary = _read_json(sources[Layer.EVALUATION] / evaluation_writer.EVALUATION_SUMMARY_NAME)
        counts["evaluated_pairs"] = int(summary.get("universe", {}).get("evaluated_pairs", 0))
    return dict(sorted(counts.items()))


def _fingerprint_files(entries: Iterable[tuple[str, str]]) -> str:
    """Return a SHA-256 over ``path:digest`` lines, in rendered-line order.

    The *rendered lines* are sorted, not the pairs: a verifier reading the
    manifest sees only lines, so sorting anything else would make the two
    computations disagree on paths where ``:`` and ``/`` order differently.
    """
    lines = sorted(f"{path}:{digest}" for path, digest in entries)
    return serialize.digest("\n".join(lines).encode("utf-8"))


def _render_readme(manifest: BundleManifest) -> str:
    layers = ", ".join(manifest.layers)
    lines = [
        f"# Data Swamp Biosystems benchmark bundle {manifest.benchmark_release}",
        "",
        "A portable, checksummed snapshot of a fully synthetic oncology data-governance",
        "benchmark. Everything in this bundle is fictional and machine-generated. It",
        "contains no real patient, personal, biological or proprietary data.",
        "",
        "## What is here",
        "",
        f"- Bundle schema version: {manifest.bundle_schema_version}",
        f"- DataSwamp version: {manifest.dataswamp_version}",
        f"- Included layers: {layers}",
        f"- Bundle fingerprint: `{manifest.bundle_fingerprint}`",
        f"- Environment fingerprint: `{manifest.environment_fingerprint}`",
        "",
        "| count | value |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in manifest.counts.items())
    lines.extend(
        [
            "",
            "## Layers",
            "",
            "- `truth/` — the complete, correct synthetic scientific and governance state.",
            "- `estate/` — small, genuinely-readable scientific files for the truth graph's",
            "  assets, plus a per-file manifest with checksums.",
            "- `observed/` — the deliberately-imperfect catalogue view, with the expected",
            "  findings, expected remediations, control partition and per-rule scope that",
            "  make it scorable.",
            "- `evaluation/` — an example scoring report, when one was included.",
            "- `adapters/<name>/` — a catalogue metadata export, when one was embedded at",
            "  build time. The manifest's `adapters` block says which and in which mode.",
            "",
            "## Verifying",
            "",
            "```bash",
            "dataswamp verify-bundle <this directory>",
            "```",
            "",
            "Or, without installing anything:",
            "",
            "```bash",
            f"sha256sum --check {CHECKSUMS_NAME}",
            "```",
            "",
            f"`{MANIFEST_NAME}` declares every other file, and `{CHECKSUMS_NAME}` records",
            "the manifest, so tampering with either is caught by the other.",
            "",
            "## Reading",
            "",
            "```python",
            "from dataswamp_biosystems.bundle import BundleReader",
            "",
            "with BundleReader.open('<this directory>') as bundle:",
            "    for finding in bundle.iter_findings():",
            "        print(finding.rule_id, finding.entity_id)",
            "```",
            "",
            f"See `{LICENSES_NAME}` for licensing and `schemas/` for the schema versions",
            "each layer was written against.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_licenses(manifest: BundleManifest) -> str:
    return "\n".join(
        [
            "# Licensing and distribution notices",
            "",
            "## Software",
            "",
            "The Data Swamp Biosystems software that produced this bundle is distributed",
            "under the MIT Licence. The full text ships with the source repository as",
            "`LICENSE`; it is not restated here.",
            "",
            "## Generated data",
            "",
            "**Licensing for the generated benchmark data is not separately defined at this",
            "release.** The project has not adopted a distinct data licence, and this file",
            "does not create one. Treat the generated contents as covered by the same MIT",
            "terms as the software unless and until the project states otherwise.",
            "",
            "## Content assurance",
            "",
            "Every person, institution, programme, study, subject, specimen, dataset and",
            "identifier in this bundle is fictional and synthetically generated. No real",
            "patient data, no real personal data, no real biological measurements and no",
            "confidential or proprietary company data are included. Email addresses and",
            "domains use the reserved `dataswamp.example` domain.",
            "",
            "## Third-party formats",
            "",
            "The estate materialises files in third-party formats (HDF5/AnnData, Apache",
            "Parquet, OME-TIFF, PNG, VCF, BED, GeoJSON, Matrix Market, gzip, FASTQ). The",
            "*files* are original synthetic output of this project; the *format",
            "specifications* belong to their respective authors and no specification text",
            "is reproduced here. Heavy binary formats are represented by explicitly",
            "declared placeholder stubs with sidecar metadata, never by real captures.",
            "",
            "## Compatibility",
            "",
            f"- Bundle schema version: {manifest.bundle_schema_version}",
            f"- DataSwamp version: {manifest.dataswamp_version}",
            f"- Python: {manifest.compatibility.get('python_requires', '')}",
            "",
        ]
    )


def _schema_index(manifest: BundleManifest) -> dict[str, Any]:
    return {
        "bundle_schema_version": manifest.bundle_schema_version,
        "supported_bundle_schema_versions": sorted(SUPPORTED_BUNDLE_SCHEMA_VERSIONS),
        "layers": manifest.schemas,
        "notes": (
            "Each layer records the schema version its writer emitted. A reader that "
            "does not support a layer's schema version must fail rather than guess."
        ),
    }


def _checksums_text(entries: Sequence[tuple[str, str]]) -> str:
    """Render a ``sha256sum``-compatible record, path-sorted for determinism."""
    return "".join(f"{digest}  {path}\n" for path, digest in sorted(entries))


def build_bundle(
    output_dir: Path | str,
    *,
    sources: Mapping[Layer, Path],
    release: str | None = None,
    adapter_exports: Mapping[str, Path] | None = None,
) -> BundleManifest:
    """Build a bundle in ``output_dir`` from the emitted layer directories.

    ``sources`` maps each included :class:`Layer` to the directory that layer's
    writer produced. The truth layer is always required; every other layer may
    only be included alongside the layers it was derived from. ``release`` names
    the benchmark release (defaults to the DataSwamp version), and
    ``adapter_exports`` maps an adapter name to an already-emitted export
    directory to embed under ``adapters/<name>/``.

    Path safety is the caller's responsibility to *invoke* (via
    :func:`~dataswamp_biosystems.paths.ensure_safe_output_dir`) and this
    function's to *not undermine*: it writes only inside ``output_dir`` and reads
    only inside the given sources.
    """
    output_dir = Path(output_dir)
    if Layer.TRUTH not in sources:
        raise BundleConfigError("a bundle must include the truth layer")
    included = [layer for layer in LAYER_ORDER if layer in sources]
    for layer in included:
        missing = [required.value for required in LAYER_REQUIRES[layer] if required not in sources]
        if missing:
            raise BundleConfigError(
                f"the {layer.value} layer requires {', '.join(missing)} in the same bundle"
            )

    # -- gather layer bytes ---------------------------------------------------
    payload: dict[str, bytes] = {}
    sections: dict[str, str] = {}
    layer_digests: dict[Layer, list[tuple[str, str]]] = {}

    for layer in included:
        source = Path(sources[layer])
        digests: list[tuple[str, str]] = []
        for bundle_path, path in _collect_layer_files(source, layer):
            data = path.read_bytes()
            payload[bundle_path] = data
            sections[bundle_path] = layer.value
            digests.append((bundle_path.split("/", 1)[1], serialize.digest(data)))
        layer_digests[layer] = digests

    # -- optional embedded adapter exports ------------------------------------
    # The packager names no specific adapter: it stores whatever directory it is
    # handed under ``adapters/<name>/`` and copies the summary fields out of the
    # adapter's own ``export-manifest.json``. That keeps the bundle layer as
    # catalogue-independent as every layer it packages.
    adapters: dict[str, dict[str, Any]] = {}
    for name, source_dir in sorted((adapter_exports or {}).items()):
        export_dir = Path(source_dir)
        prefix = adapter_path(name)
        if not export_dir.is_dir():
            raise BundleConfigError(f"no {name} adapter export directory at {export_dir}")
        export_digests: list[tuple[str, str]] = []
        for relative in walk_bundle_files(export_dir):
            if _ignored(relative):
                continue
            path = export_dir / relative
            if path.is_symlink():
                raise BundleConfigError(f"{name} adapter export {path} is a symlink")
            bundle_path = f"{prefix}/{relative}"
            data = path.read_bytes()
            payload[bundle_path] = data
            sections[bundle_path] = SECTION_ADAPTERS
            export_digests.append((relative, serialize.digest(data)))
        if not export_digests:
            raise BundleConfigError(f"{name} adapter export directory {export_dir} is empty")
        export_manifest = _read_json(export_dir / ADAPTER_MANIFEST_NAME)
        adapters[name] = {
            "path": prefix,
            "mode": export_manifest.get("mode", ""),
            "privileged": bool(export_manifest.get("privileged", False)),
            "adapter_version": export_manifest.get("adapter_version", ""),
            "entities": export_manifest.get("counts", {}).get("entities", 0),
            "aspects": export_manifest.get("counts", {}).get("aspects", 0),
            "fingerprint": _fingerprint_files(export_digests),
        }

    # -- provenance and environment ------------------------------------------
    provenances = {layer: _layer_provenance(Path(sources[layer]), layer) for layer in included}
    fingerprints = {str(p.get("environment_fingerprint", "")) for p in provenances.values()}
    if len(fingerprints) != 1:
        raise BundleConfigError(
            "layer provenance disagrees on the environment fingerprint "
            f"({', '.join(sorted(fingerprints))}); bundle only layers generated together"
        )
    environment_fingerprint = fingerprints.pop()

    schemas = {
        layer.value: {
            "schema_version": provenances[layer].get("schema_version"),
            "generator_version": provenances[layer].get("generator_version"),
        }
        for layer in included
    }
    scenario = {layer.value: dict(provenances[layer].get("scenario", {})) for layer in included}

    bundle_provenance = provenance_bytes(
        layer="bundle",
        generator_version=BUNDLE_BUILDER_VERSION,
        schema_version=BUNDLE_SCHEMA_VERSION,
        scenario={
            "benchmark_release": release or __version__,
            "layers": [layer.value for layer in included],
            **{f"{layer.value}_scenario": scenario[layer.value] for layer in included},
        },
    )
    payload[PROVENANCE_NAME] = bundle_provenance
    sections[PROVENANCE_NAME] = SECTION_BUNDLE

    gt_fingerprint = ""
    if Layer.OBSERVED in sources:
        gt_fingerprint = ground_truth_fingerprint(Path(sources[Layer.OBSERVED]))
    if Layer.EVALUATION in sources:
        # An evaluation report quotes the ground-truth fingerprint it was scored
        # against. Bundling a report beside a *different* observed state would
        # publish a score that looks authoritative and is not about this
        # benchmark at all, so the two must agree before anything is written.
        summary = _read_json(
            Path(sources[Layer.EVALUATION]) / evaluation_writer.EVALUATION_SUMMARY_NAME
        )
        scored = str(summary.get("benchmark", {}).get("ground_truth_fingerprint", ""))
        if scored != gt_fingerprint:
            raise BundleConfigError(
                "the evaluation report was scored against ground truth "
                f"{scored or '<unrecorded>'}, but the bundled observed layer is "
                f"{gt_fingerprint}; bundle an evaluation only with the state it scored"
            )

    # -- manifest -------------------------------------------------------------
    # Built in two passes: the file list and its fingerprint are computed over
    # every file except the manifest itself, then the README, licences and
    # schema index (which quote the manifest) are rendered and folded in.
    def entries_for(names: Iterable[str]) -> list[BundleFileEntry]:
        return sorted(
            (
                BundleFileEntry(
                    path=name,
                    sha256=serialize.digest(payload[name]),
                    bytes=len(payload[name]),
                    section=sections[name],
                )
                for name in names
            ),
            key=lambda entry: entry.path,
        )

    compatibility = {
        "bundle_schema_versions_supported": sorted(SUPPORTED_BUNDLE_SCHEMA_VERSIONS),
        "min_dataswamp_version": __version__,
        "python_requires": ">=3.12",
        "reader_api": "dataswamp_biosystems.bundle.BundleReader",
        "verify_command": "dataswamp verify-bundle",
        "portable_layers": [Layer.TRUTH.value, Layer.OBSERVED.value],
        "environment_scoped_layers": [Layer.ESTATE.value],
    }
    licensing = {
        "software_license": "MIT",
        "software_license_file": "LICENSE (source repository)",
        "generated_data_license": "not-separately-defined",
        "notices_file": LICENSES_NAME,
        "contains_real_data": False,
    }

    base = BundleManifest(
        bundle_schema_version=BUNDLE_SCHEMA_VERSION,
        bundle_builder_version=BUNDLE_BUILDER_VERSION,
        benchmark_release=release or __version__,
        dataswamp_version=__version__,
        layers=[layer.value for layer in included],
        schemas=schemas,
        scenario=scenario,
        source_fingerprints={
            layer.value: _fingerprint_files(layer_digests[layer]) for layer in included
        },
        environment_fingerprint=environment_fingerprint,
        ground_truth_fingerprint=gt_fingerprint,
        counts=_counts(sources),
        checksum_algorithm=CHECKSUM_ALGORITHM,
        checksums_file=CHECKSUMS_NAME,
        files=[],
        bundle_fingerprint="0" * 64,
        compatibility=compatibility,
        adapters=adapters,
        licensing=licensing,
    )

    # The human-readable files quote only manifest fields that are already
    # fixed, so rendering them here introduces no circularity.
    payload[README_NAME] = _render_readme(base).encode("utf-8")
    sections[README_NAME] = SECTION_BUNDLE
    payload[LICENSES_NAME] = _render_licenses(base).encode("utf-8")
    sections[LICENSES_NAME] = SECTION_BUNDLE
    payload[SCHEMA_INDEX_NAME] = serialize.manifest_bytes(_schema_index(base))
    sections[SCHEMA_INDEX_NAME] = SECTION_BUNDLE

    # Coverage, without any digest defined in terms of itself:
    #   * the manifest declares every content file (not itself, not the
    #     checksum record — a digest of either would be circular);
    #   * the checksum record covers every content file *and the manifest*;
    #   * the checksum record itself is covered by being exactly *recomputable*
    #     from the manifest, which the verifier does byte-for-byte. That is
    #     stronger than a stored digest would have been.
    declared = entries_for(payload)
    fingerprint = _fingerprint_files((entry.path, entry.sha256) for entry in declared)
    manifest = base.model_copy(update={"files": declared, "bundle_fingerprint": fingerprint})
    manifest_bytes = serialize.manifest_bytes(manifest.model_dump(mode="json"))
    checksums = checksums_text(manifest, manifest_bytes)

    _write_atomically(
        output_dir,
        {**payload, MANIFEST_NAME: manifest_bytes, CHECKSUMS_NAME: checksums.encode("utf-8")},
    )
    return manifest


def checksums_text(manifest: BundleManifest, manifest_bytes: bytes) -> str:
    """Return the exact contents of ``checksums.sha256`` for ``manifest``.

    Used by the builder to write the record and by the verifier to recompute it,
    so the two can never drift apart.
    """
    return _checksums_text(
        [
            *((entry.path, entry.sha256) for entry in manifest.files),
            (MANIFEST_NAME, serialize.digest(manifest_bytes)),
        ]
    )


def _write_atomically(output_dir: Path, files: Mapping[str, bytes]) -> None:
    """Stage every file in a temporary sibling and swap it into place."""
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{output_dir.name}.tmp-{os.getpid()}"
    backup = parent / f".{output_dir.name}.bak-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        tmp.mkdir(parents=True)
        for name in sorted(files):
            serialize.write_bytes(tmp / name, files[name])
        had_existing = output_dir.exists()
        if had_existing:
            os.replace(output_dir, backup)
        try:
            os.replace(tmp, output_dir)
        except OSError:
            if had_existing:  # pragma: no cover - best-effort restore
                os.replace(backup, output_dir)
            raise
        if had_existing:
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


__all__ = ["SECTION_BUNDLE", "SECTION_ADAPTERS", "build_bundle", "checksums_text"]
