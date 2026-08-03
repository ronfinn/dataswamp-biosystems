"""Verify a benchmark bundle against its own manifest, checksums and provenance.

Verification is *total*: every invariant is checked and every failure recorded,
so one run tells a consumer everything wrong with a bundle rather than the first
thing. Each issue names the offending file and the invariant it broke.

The checks, in the order they are applied:

1. the manifest parses and its schema version is supported;
2. every declared path is a safe relative path inside the bundle;
3. no path in the bundle is a symlink;
4. the declared file set matches what is on disk (extras rejected under strict
   verification, which is the default);
5. every declared file's size and SHA-256 match;
6. the bundle fingerprint is the one the declared digests imply;
7. ``checksums.sha256`` is byte-identical to what the manifest implies;
8. the declared layers are structurally complete and mutually consistent;
9. provenance agrees with the manifest, layer by layer;
10. the ground-truth fingerprint recomputes from the bundled observed layer, and
    a bundled evaluation report was scored against that same ground truth;
11. an embedded adapter export, if present, is complete and matches its recorded
    fingerprint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dataswamp_biosystems.bundle.builder import checksums_text
from dataswamp_biosystems.bundle.entities import (
    SUPPORTED_BUNDLE_SCHEMA_VERSIONS,
    BundleManifest,
)
from dataswamp_biosystems.bundle.errors import (
    BundleConfigError,
    BundleIssueCollector,
    BundleIssueKind,
)
from dataswamp_biosystems.bundle.layout import (
    CHECKSUMS_NAME,
    LAYER_ORDER,
    LAYER_REQUIRED_FILES,
    LAYER_REQUIRES,
    MANIFEST_NAME,
    Layer,
    contains_symlink,
    is_safe_relative_path,
    resolve_inside,
    walk_bundle_files,
)
from dataswamp_biosystems.evaluation import writer as evaluation_writer
from dataswamp_biosystems.evaluation.ground_truth import ground_truth_fingerprint
from dataswamp_biosystems.provenance import PROVENANCE_NAME
from dataswamp_biosystems.truth import serialize

# Files that exist in every bundle but are not declared by the manifest: the
# manifest itself (it cannot contain its own digest) and the checksum record
# (verified by exact recomputation instead).
_UNDECLARED_BY_DESIGN: frozenset[str] = frozenset({MANIFEST_NAME, CHECKSUMS_NAME})


def read_manifest(bundle_dir: Path | str) -> BundleManifest:
    """Read and parse a bundle manifest, or raise :class:`BundleConfigError`.

    Structural parsing only — it proves the manifest is well-formed, not that
    the bundle it describes is intact. Use :func:`verify_bundle` for that.
    """
    bundle_dir = Path(bundle_dir)
    path = bundle_dir / MANIFEST_NAME
    if not path.is_file():
        raise BundleConfigError(f"no bundle manifest at {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleConfigError(f"could not read {path}: {exc}") from exc
    try:
        manifest = BundleManifest.model_validate(payload)
    except ValidationError as exc:
        raise BundleConfigError(f"{path} is not a valid bundle manifest: {exc}") from exc
    if manifest.bundle_schema_version not in SUPPORTED_BUNDLE_SCHEMA_VERSIONS:
        raise BundleConfigError(
            f"{path} declares bundle schema version {manifest.bundle_schema_version}; "
            f"this build supports {sorted(SUPPORTED_BUNDLE_SCHEMA_VERSIONS)}"
        )
    return manifest


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def verify_bundle(bundle_dir: Path | str, *, strict: bool = True) -> BundleManifest:
    """Verify ``bundle_dir`` completely; return its manifest or raise.

    ``strict`` (the default) rejects a file present in the bundle but absent from
    the manifest. Relaxing it is for consumers who deliberately drop extra files
    beside a bundle; it never relaxes any *declared* file's checks.

    Raises :class:`BundleConfigError` if the manifest itself cannot be read, and
    :class:`~dataswamp_biosystems.bundle.errors.BundleValidationError` carrying
    every issue otherwise.
    """
    bundle_dir = Path(bundle_dir)
    if not bundle_dir.is_dir():
        raise BundleConfigError(f"no bundle directory at {bundle_dir}")
    manifest = read_manifest(bundle_dir)
    issues = BundleIssueCollector()

    # -- 2/3: path safety and symlinks ---------------------------------------
    declared: dict[str, Any] = {}
    for entry in manifest.files:
        if entry.path in declared:
            issues.add(entry.path, BundleIssueKind.MANIFEST_SCHEMA, detail="declared twice")
            continue
        if not is_safe_relative_path(entry.path):
            issues.add(
                entry.path,
                BundleIssueKind.UNSAFE_PATH,
                detail="not a safe relative path inside the bundle",
            )
            continue
        if entry.path in _UNDECLARED_BY_DESIGN:
            issues.add(
                entry.path,
                BundleIssueKind.MANIFEST_SCHEMA,
                detail="the manifest and checksum record are never self-declared",
            )
            continue
        declared[entry.path] = entry

    on_disk = walk_bundle_files(bundle_dir)
    for relative in on_disk:
        if contains_symlink(bundle_dir, relative):
            issues.add(relative, BundleIssueKind.SYMLINK, detail="bundles contain no symlinks")

    # -- 4: declared set versus disk -----------------------------------------
    present = set(on_disk)
    for name in _UNDECLARED_BY_DESIGN:
        if name not in present:
            issues.add(name, BundleIssueKind.MISSING_FILE, detail="required bundle metadata")
    for path in sorted(declared):
        if path not in present:
            issues.add(path, BundleIssueKind.MISSING_FILE, detail="declared but absent")
    if strict:
        for path in sorted(present - set(declared) - _UNDECLARED_BY_DESIGN):
            issues.add(path, BundleIssueKind.UNDECLARED_FILE, detail="present but not declared")

    # -- 5: per-file checksums ------------------------------------------------
    for path in sorted(declared):
        entry = declared[path]
        resolved = resolve_inside(bundle_dir, path)
        if resolved is None:
            issues.add(path, BundleIssueKind.UNSAFE_PATH, detail="resolves outside the bundle")
            continue
        if not resolved.is_file() or contains_symlink(bundle_dir, path):
            continue
        data = resolved.read_bytes()
        if len(data) != entry.bytes:
            issues.add(
                path,
                BundleIssueKind.CHECKSUM_MISMATCH,
                detail="size",
                expected=str(entry.bytes),
                actual=str(len(data)),
            )
        actual = serialize.digest(data)
        if actual != entry.sha256:
            issues.add(
                path,
                BundleIssueKind.CHECKSUM_MISMATCH,
                detail="sha256",
                expected=entry.sha256,
                actual=actual,
            )

    # -- 6: bundle fingerprint ------------------------------------------------
    lines = sorted(f"{entry.path}:{entry.sha256}" for entry in manifest.files)
    recomputed = serialize.digest("\n".join(lines).encode("utf-8"))
    if recomputed != manifest.bundle_fingerprint:
        issues.add(
            MANIFEST_NAME,
            BundleIssueKind.FINGERPRINT,
            detail="bundle_fingerprint does not match the declared digests",
            expected=manifest.bundle_fingerprint,
            actual=recomputed,
        )

    # -- 7: the checksum record must be exactly reproducible ------------------
    manifest_bytes = (bundle_dir / MANIFEST_NAME).read_bytes()
    expected_checksums = checksums_text(manifest, manifest_bytes)
    checksums_path = bundle_dir / CHECKSUMS_NAME
    if checksums_path.is_file():
        actual_checksums = checksums_path.read_text(encoding="utf-8")
        if actual_checksums != expected_checksums:
            issues.add(
                CHECKSUMS_NAME,
                BundleIssueKind.CHECKSUM_MISMATCH,
                detail="record does not match the manifest it must be derived from",
            )

    # -- 8: structural completeness ------------------------------------------
    known = {layer.value for layer in LAYER_ORDER}
    unknown = [name for name in manifest.layers if name not in known]
    for name in unknown:
        issues.add(MANIFEST_NAME, BundleIssueKind.STRUCTURE, detail=f"unknown layer {name!r}")
    included = [layer for layer in LAYER_ORDER if layer.value in manifest.layers]
    if Layer.TRUTH not in included:
        issues.add(MANIFEST_NAME, BundleIssueKind.STRUCTURE, detail="no truth layer declared")
    for layer in included:
        for required in LAYER_REQUIRES[layer]:
            if required not in included:
                issues.add(
                    layer.value,
                    BundleIssueKind.STRUCTURE,
                    detail=f"requires the {required.value} layer, which is not declared",
                )
        for name in LAYER_REQUIRED_FILES[layer]:
            path = f"{layer.value}/{name}"
            if path not in declared:
                issues.add(path, BundleIssueKind.STRUCTURE, detail="required layer file")

    # -- 9: provenance consistency -------------------------------------------
    bundle_provenance = _read_json_file(bundle_dir / PROVENANCE_NAME)
    if bundle_provenance is None:
        issues.add(PROVENANCE_NAME, BundleIssueKind.PROVENANCE, detail="missing or unreadable")
    else:
        actual = str(bundle_provenance.get("environment_fingerprint", ""))
        if actual != manifest.environment_fingerprint:
            issues.add(
                PROVENANCE_NAME,
                BundleIssueKind.PROVENANCE,
                detail="environment_fingerprint disagrees with the manifest",
                expected=manifest.environment_fingerprint,
                actual=actual,
            )
    for layer in included:
        path = f"{layer.value}/{PROVENANCE_NAME}"
        provenance = _read_json_file(bundle_dir / layer.value / PROVENANCE_NAME)
        if provenance is None:
            issues.add(path, BundleIssueKind.PROVENANCE, detail="missing or unreadable")
            continue
        if provenance.get("layer") != layer.value:
            issues.add(
                path,
                BundleIssueKind.PROVENANCE,
                detail="records a different layer",
                expected=layer.value,
                actual=str(provenance.get("layer", "")),
            )
        actual = str(provenance.get("environment_fingerprint", ""))
        if actual != manifest.environment_fingerprint:
            issues.add(
                path,
                BundleIssueKind.PROVENANCE,
                detail="environment_fingerprint disagrees with the manifest",
                expected=manifest.environment_fingerprint,
                actual=actual,
            )
        recorded = manifest.schemas.get(layer.value, {})
        for field in ("schema_version", "generator_version"):
            if recorded.get(field) != provenance.get(field):
                issues.add(
                    path,
                    BundleIssueKind.PROVENANCE,
                    detail=f"{field} disagrees with the manifest",
                    expected=str(recorded.get(field, "")),
                    actual=str(provenance.get(field, "")),
                )

    # -- 10: ground-truth fingerprint ----------------------------------------
    if Layer.OBSERVED in included:
        recomputed_gt = ground_truth_fingerprint(bundle_dir / Layer.OBSERVED.value)
        if recomputed_gt != manifest.ground_truth_fingerprint:
            issues.add(
                Layer.OBSERVED.value,
                BundleIssueKind.FINGERPRINT,
                detail="ground_truth_fingerprint does not match the bundled observed layer",
                expected=manifest.ground_truth_fingerprint,
                actual=recomputed_gt,
            )
        if Layer.EVALUATION in included:
            # The report must be about the ground truth shipped beside it.
            summary = _read_json_file(
                bundle_dir / Layer.EVALUATION.value / evaluation_writer.EVALUATION_SUMMARY_NAME
            )
            scored = str((summary or {}).get("benchmark", {}).get("ground_truth_fingerprint", ""))
            if scored != recomputed_gt:
                issues.add(
                    f"{Layer.EVALUATION.value}/{evaluation_writer.EVALUATION_SUMMARY_NAME}",
                    BundleIssueKind.REFERENCE,
                    detail="scored against ground truth that is not the bundled observed layer",
                    expected=recomputed_gt,
                    actual=scored,
                )
    elif manifest.ground_truth_fingerprint:
        issues.add(
            MANIFEST_NAME,
            BundleIssueKind.REFERENCE,
            detail="ground_truth_fingerprint declared without an observed layer",
        )

    # -- 11: embedded adapter export -----------------------------------------
    for name, record in sorted(manifest.adapters.items()):
        prefix = str(record.get("path", ""))
        members = sorted(path for path in declared if path.startswith(f"{prefix}/"))
        if not members:
            issues.add(
                prefix or name,
                BundleIssueKind.REFERENCE,
                detail=f"adapter {name!r} declares a path with no bundled files",
            )
            continue
        lines = sorted(f"{path[len(prefix) + 1 :]}:{declared[path].sha256}" for path in members)
        fingerprint = serialize.digest("\n".join(lines).encode("utf-8"))
        if fingerprint != record.get("fingerprint"):
            issues.add(
                prefix,
                BundleIssueKind.FINGERPRINT,
                detail=f"adapter {name!r} fingerprint does not match its bundled files",
                expected=str(record.get("fingerprint", "")),
                actual=fingerprint,
            )

    issues.raise_if_any()
    return manifest


__all__ = ["read_manifest", "verify_bundle"]
