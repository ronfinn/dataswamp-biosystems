"""The versioned bundle manifest: the contract a bundle consumer reads first.

The manifest is the only file a consumer must understand. It declares what the
bundle contains, which benchmark run produced it, which environment produced
that run, and the SHA-256 of every other file — so a bundle can be verified,
cited and reproduced without any knowledge of this repository's internals.

Nothing here carries a wall-clock value. A bundle built twice from the same
canonical inputs is byte-identical, which is what makes the manifest's
``bundle_fingerprint`` a stable citation rather than a build receipt.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG

# Bumped when the on-disk bundle layout or manifest schema changes incompatibly.
BUNDLE_SCHEMA_VERSION = 1

# Bumped when the *builder* changes in a way that alters bundle bytes for
# unchanged inputs. Independent of the schema version: a builder fix that
# reorders a list changes bytes without changing the contract's shape.
BUNDLE_BUILDER_VERSION = "1.0.0"

# Manifest schema versions this build of the reader/verifier can consume.
SUPPORTED_BUNDLE_SCHEMA_VERSIONS: frozenset[int] = frozenset({BUNDLE_SCHEMA_VERSION})


class BundleFileEntry(BaseModel):
    """One declared file: its bundle-relative path, size, digest and owning layer."""

    model_config = STRICT_MODEL_CONFIG

    path: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    bytes: int = Field(ge=0)
    # ``truth``/``estate``/``observed``/``evaluation`` for layer content,
    # ``adapters`` for an embedded adapter export, ``bundle`` for the bundle's
    # own metadata files.
    section: str = Field(min_length=1)


class BundleManifest(BaseModel):
    """The complete, machine-readable description of one benchmark bundle."""

    model_config = STRICT_MODEL_CONFIG

    bundle_schema_version: int
    bundle_builder_version: str = Field(min_length=1)
    benchmark_release: str = Field(min_length=1)
    dataswamp_version: str = Field(min_length=1)

    layers: list[str] = Field(min_length=1)
    # Per-layer ``{schema_version, generator_version}``, read from each layer's
    # own provenance rather than restated by the builder.
    schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Per-layer seeds/profiles, verbatim from each layer's provenance scenario.
    scenario: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # SHA-256 over each layer's own file tree, so a layer can be compared
    # between bundles without diffing file lists.
    source_fingerprints: dict[str, str] = Field(default_factory=dict)
    environment_fingerprint: str = Field(min_length=1)
    # SHA-256 over the observed layer's ground-truth artefacts — the same value
    # the evaluator quotes, so a score can be tied to the bundle it came from.
    ground_truth_fingerprint: str = ""

    counts: dict[str, int] = Field(default_factory=dict)

    checksum_algorithm: str = Field(min_length=1)
    checksums_file: str = Field(min_length=1)
    files: list[BundleFileEntry] = Field(default_factory=list)
    # SHA-256 over every declared ``path:sha256`` pair. One value that changes
    # if any bundled byte changes; quote it to cite a bundle.
    bundle_fingerprint: str = Field(min_length=1)

    compatibility: dict[str, Any] = Field(default_factory=dict)
    # Present only when an adapter export was embedded at build time.
    adapters: dict[str, dict[str, Any]] = Field(default_factory=dict)

    licensing: dict[str, Any] = Field(default_factory=dict)
    synthetic: Literal[True] = True


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "BUNDLE_BUILDER_VERSION",
    "SUPPORTED_BUNDLE_SCHEMA_VERSIONS",
    "BundleFileEntry",
    "BundleManifest",
]
