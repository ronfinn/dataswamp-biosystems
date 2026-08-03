"""The on-disk layout of a benchmark bundle, and the rules paths inside it obey.

A bundle is a *directory*, not an archive. That is a deliberate MVP decision: a
directory of canonical bytes is byte-reproducible without also having to pin tar
or zip header semantics (member order, mtimes, permission bits, compression
level, path separators), and every one of those is a determinism hazard that
buys nothing a consumer of this benchmark actually needs. Anyone who wants an
archive can make one from a verified directory with tooling they already trust.

Two independent integrity records cover each other:

``benchmark-manifest.json``
    Declares every bundled file *except itself*, including ``checksums.sha256``.
``checksums.sha256``
    Records every bundled file *except itself*, including the manifest.

So altering either one is caught by the other, and no file in the bundle is
covered by neither. The pair is the anchor; a consumer who wants a single value
to compare out of band should quote the manifest's ``bundle_fingerprint``.
"""

from __future__ import annotations

import posixpath
from enum import StrEnum
from pathlib import Path, PurePosixPath

from dataswamp_biosystems.estate import writer as estate_writer
from dataswamp_biosystems.evaluation import writer as evaluation_writer
from dataswamp_biosystems.observed import writer as observed_writer
from dataswamp_biosystems.provenance import PROVENANCE_NAME
from dataswamp_biosystems.truth import writer as truth_writer

MANIFEST_NAME = "benchmark-manifest.json"
CHECKSUMS_NAME = "checksums.sha256"
README_NAME = "README.md"
LICENSES_NAME = "LICENSES.md"
SCHEMAS_DIRNAME = "schemas"
SCHEMA_INDEX_NAME = f"{SCHEMAS_DIRNAME}/schema-versions.json"
ADAPTERS_DIRNAME = "adapters"
# An adapter export embedded at build time supplies this manifest, which is the
# only thing the packager reads from it. The bundle layer names no specific
# adapter: it stores whatever it is handed under ``adapters/<name>/``.
ADAPTER_MANIFEST_NAME = "export-manifest.json"

CHECKSUM_ALGORITHM = "sha256"


class Layer(StrEnum):
    """The four benchmark layers a bundle may carry, in dependency order."""

    TRUTH = "truth"
    ESTATE = "estate"
    OBSERVED = "observed"
    EVALUATION = "evaluation"


# Fixed order for every list, manifest field and iteration in this package.
LAYER_ORDER: tuple[Layer, ...] = (Layer.TRUTH, Layer.ESTATE, Layer.OBSERVED, Layer.EVALUATION)

# A layer may only be bundled together with the layers it was derived from, so a
# bundle can never claim scored results without the ground truth they score.
LAYER_REQUIRES: dict[Layer, tuple[Layer, ...]] = {
    Layer.TRUTH: (),
    Layer.ESTATE: (Layer.TRUTH,),
    Layer.OBSERVED: (Layer.TRUTH,),
    Layer.EVALUATION: (Layer.TRUTH, Layer.OBSERVED),
}

# One file per layer that must exist for the layer to be structurally complete.
# Deliberately minimal: the checksum record already proves *every* file is
# present and unaltered, so this only catches a directory that is not the layer
# it claims to be.
LAYER_REQUIRED_FILES: dict[Layer, tuple[str, ...]] = {
    Layer.TRUTH: (truth_writer.MANIFEST_NAME, PROVENANCE_NAME),
    Layer.ESTATE: (estate_writer.MANIFEST_NAME, estate_writer.SUMMARY_JSON_NAME, PROVENANCE_NAME),
    Layer.OBSERVED: (
        observed_writer.OBSERVED_GRAPH_NAME,
        observed_writer.EXPECTED_FINDINGS_NAME,
        observed_writer.EXPECTED_REMEDIATIONS_NAME,
        observed_writer.CONTROLS_NAME,
        observed_writer.RULE_SCOPE_NAME,
        observed_writer.PROFILE_SUMMARY_NAME,
        PROVENANCE_NAME,
    ),
    Layer.EVALUATION: (evaluation_writer.EVALUATION_SUMMARY_NAME, PROVENANCE_NAME),
}


def adapter_path(adapter_name: str) -> str:
    """Return the bundle-relative directory an embedded adapter export lives in."""
    if not is_safe_relative_path(adapter_name) or "/" in adapter_name:
        raise ValueError(f"{adapter_name!r} is not a usable adapter name")
    return f"{ADAPTERS_DIRNAME}/{adapter_name}"


def is_safe_relative_path(path: str) -> bool:
    """Return whether ``path`` may appear in a bundle manifest.

    A bundle path is a *relative posix path inside the bundle root*. Anything
    else — an absolute path, a drive letter, a ``..`` segment, a Windows
    separator, an embedded NUL, a trailing separator — is rejected outright
    rather than normalised, because a manifest is an instruction to write or
    read a file and normalising an attacker's path is how traversal happens.
    """
    if not path or path != path.strip():
        return False
    if "\\" in path or "\0" in path:
        return False
    if path.startswith("/") or path.endswith("/") or "//" in path:
        return False
    pure = PurePosixPath(path)
    if pure.is_absolute() or pure.drive or pure.anchor:
        return False
    # Split the *raw* string rather than trusting ``PurePosixPath.parts``, which
    # silently drops ``.`` segments — so ``./x`` would otherwise normalise into
    # an innocent-looking single component instead of being rejected.
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def resolve_inside(root: Path, relative: str) -> Path | None:
    """Return the absolute path of ``relative`` inside ``root``, or ``None`` if it escapes.

    Belt and braces over :func:`is_safe_relative_path`: the string is checked
    for traversal syntax, and the *resolved* result is checked for containment,
    so a symlinked intermediate directory cannot smuggle a read or write outside
    the bundle even if the literal path looks innocent.
    """
    if not is_safe_relative_path(relative):
        return None
    candidate = root / relative
    try:
        resolved = candidate.resolve()
    except OSError:  # pragma: no cover - defensive
        return None
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def contains_symlink(root: Path, relative: str) -> bool:
    """Return whether ``relative`` traverses or ends at a symlink under ``root``."""
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def walk_bundle_files(root: Path) -> list[str]:
    """Return every regular file under ``root`` as a sorted bundle-relative path.

    Symlinks are *not* followed and *not* skipped: they are returned so the
    verifier can report them explicitly. A bundle contains only regular files.
    """
    found: list[str] = []
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_file():
            found.append(posixpath.join(*path.relative_to(root).parts))
    return sorted(found)


__all__ = [
    "MANIFEST_NAME",
    "CHECKSUMS_NAME",
    "README_NAME",
    "LICENSES_NAME",
    "SCHEMAS_DIRNAME",
    "SCHEMA_INDEX_NAME",
    "ADAPTERS_DIRNAME",
    "ADAPTER_MANIFEST_NAME",
    "CHECKSUM_ALGORITHM",
    "Layer",
    "LAYER_ORDER",
    "LAYER_REQUIRES",
    "LAYER_REQUIRED_FILES",
    "adapter_path",
    "is_safe_relative_path",
    "resolve_inside",
    "contains_symlink",
    "walk_bundle_files",
]
