"""Versioned, checksummed benchmark bundles: the project's portable artefact.

Everything upstream of this package generates output into a working directory
that only makes sense next to this repository. A *bundle* is the same output
made portable: one directory carrying the layers that were generated, a
versioned manifest describing them, SHA-256 checksums for every file, the
environment provenance that produced them, and the licensing and schema notices
a third party needs — verifiable and readable without any knowledge of how the
generators work.

The layer is a packager and a reader, never a generator. It copies emitted bytes
and never regenerates, rewrites or reinterprets them, so bundling can add no
drift of its own. Like every other layer it is catalogue-independent: the DataHub
adapter consumes bundles, and nothing here knows the adapter exists.

See ``docs/bundles.md``.
"""

from __future__ import annotations

from dataswamp_biosystems.bundle.builder import (
    SECTION_ADAPTERS,
    SECTION_BUNDLE,
    build_bundle,
    checksums_text,
)
from dataswamp_biosystems.bundle.entities import (
    BUNDLE_BUILDER_VERSION,
    BUNDLE_SCHEMA_VERSION,
    SUPPORTED_BUNDLE_SCHEMA_VERSIONS,
    BundleFileEntry,
    BundleManifest,
)
from dataswamp_biosystems.bundle.errors import (
    BundleConfigError,
    BundleError,
    BundleIssue,
    BundleIssueKind,
    BundleValidationError,
)
from dataswamp_biosystems.bundle.layout import (
    ADAPTER_MANIFEST_NAME,
    ADAPTERS_DIRNAME,
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
    resolve_inside,
)
from dataswamp_biosystems.bundle.reader import TRUTH_SHARDS, BundleReader
from dataswamp_biosystems.bundle.verify import read_manifest, verify_bundle

__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "BUNDLE_BUILDER_VERSION",
    "SUPPORTED_BUNDLE_SCHEMA_VERSIONS",
    "BundleFileEntry",
    "BundleManifest",
    "BundleError",
    "BundleConfigError",
    "BundleValidationError",
    "BundleIssue",
    "BundleIssueKind",
    "Layer",
    "LAYER_ORDER",
    "LAYER_REQUIRES",
    "LAYER_REQUIRED_FILES",
    "MANIFEST_NAME",
    "CHECKSUMS_NAME",
    "README_NAME",
    "LICENSES_NAME",
    "SCHEMA_INDEX_NAME",
    "ADAPTERS_DIRNAME",
    "ADAPTER_MANIFEST_NAME",
    "CHECKSUM_ALGORITHM",
    "SECTION_BUNDLE",
    "SECTION_ADAPTERS",
    "adapter_path",
    "is_safe_relative_path",
    "resolve_inside",
    "build_bundle",
    "checksums_text",
    "read_manifest",
    "verify_bundle",
    "BundleReader",
    "TRUTH_SHARDS",
]
