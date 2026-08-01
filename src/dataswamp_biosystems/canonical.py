"""The canonical benchmark scenario: one small, fixed, fully reproducible run.

This is the scenario the committed golden digests describe. It is deliberately
small (the ``tiny`` estate profile) so the contract stays a handful of kilobytes
of checksums rather than a committed benchmark tree, while still covering every
layer: the truth graph, the materialized scientific-file estate, and the
observed state with its defect ledgers and control partition.

The scenario is defined here, in the package rather than in the tests, so the
golden test, the regeneration script, and any user reproducing a canonical
release all drive generation through exactly one code path.

Digest scopes
-------------

Not every artefact is stable across every supported dependency version, and the
contract says so explicitly rather than over-claiming:

``PORTABLE_PREFIXES``
    Artefacts proven byte-identical across the whole supported dependency range
    (locked *and* lowest-direct, Python 3.12 and 3.13): the truth graph and the
    observed-state ledgers. These are pure-Python canonical JSON/JSONL.

Everything else — the materialized estate, whose binary payloads are written by
pyarrow, Pillow, tifffile and anndata — is byte-identical only within a single
*environment fingerprint*, because those writers change their output between
releases. See ``docs/reproducibility.md``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from dataswamp_biosystems.company import CanonicalConfig, load_config
from dataswamp_biosystems.estate import Profile, write_estate
from dataswamp_biosystems.observed.engine import generate_observed
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.writer import write_observed
from dataswamp_biosystems.provenance import PROVENANCE_NAME
from dataswamp_biosystems.truth import GenerationPlan, generate_truth_graph, load_generation_plan
from dataswamp_biosystems.truth.writer import write_truth_graph

# -- the fixed scenario -------------------------------------------------------

CANONICAL_TRUTH_SEED = 20260717
CANONICAL_ESTATE_SEED = 20260717
CANONICAL_DEFECT_SEED = 20260717
CANONICAL_ESTATE_PROFILE = Profile.TINY
CANONICAL_OBSERVED_PROFILE = ObservedProfile.DEMO

TRUTH_DIRNAME = "truth"
ESTATE_DIRNAME = "estate"
OBSERVED_DIRNAME = "observed"

# Artefacts whose bytes are guaranteed across the whole supported dependency
# range, not merely within one environment fingerprint.
PORTABLE_PREFIXES: tuple[str, ...] = (f"{TRUTH_DIRNAME}/", f"{OBSERVED_DIRNAME}/")

# Provenance records the environment, so it is *expected* to differ between a
# locked and a lowest-direct run. It is never part of the digest contract.
EXCLUDED_NAMES: frozenset[str] = frozenset({PROVENANCE_NAME})

# Individual materialized files are *not* hashed directly: the estate manifest
# records a SHA-256 per file, so hashing the manifest pins every payload byte
# transitively. This keeps the committed contract a few dozen checksums instead
# of one per generated file, while still failing on any binary drift.
EXCLUDED_PREFIXES: tuple[str, ...] = (f"{ESTATE_DIRNAME}/files/",)

DIGEST_ALGORITHM = "sha256"


def scenario_identity() -> dict[str, object]:
    """Return the machine-readable identity of the canonical scenario."""
    return {
        "truth_seed": CANONICAL_TRUTH_SEED,
        "estate_seed": CANONICAL_ESTATE_SEED,
        "estate_profile": CANONICAL_ESTATE_PROFILE.value,
        "defect_seed": CANONICAL_DEFECT_SEED,
        "observed_profile": CANONICAL_OBSERVED_PROFILE.value,
    }


CONFIG_SUFFIXES: frozenset[str] = frozenset({".yaml", ".yml"})


def config_input_paths(config_dir: Path) -> list[Path]:
    """Return the configuration files that feed generation, path-sorted.

    Only the YAML inputs the loader actually reads are considered. Editor and
    operating-system artefacts (``.DS_Store``, ``.swp``, ``__pycache__`` …) are
    untracked, machine-specific and must never perturb the fingerprint — a
    contract that failed on a developer machine but passed in CI would be worse
    than no contract at all.
    """
    return sorted(
        path
        for path in Path(config_dir).rglob("*")
        if path.is_file()
        and path.suffix.lower() in CONFIG_SUFFIXES
        and not path.name.startswith(".")
    )


def config_fingerprint(config_dir: Path) -> str:
    """Return a SHA-256 over the canonical configuration inputs.

    Pins the *generation configuration identity*: a config edit changes this
    fingerprint, so a golden mismatch can be attributed to configuration rather
    than to code or dependencies.
    """
    config_dir = Path(config_dir)
    digest = hashlib.sha256()
    for path in config_input_paths(config_dir):
        digest.update(path.relative_to(config_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def generate_canonical(
    output_dir: Path,
    config: CanonicalConfig,
    plan: GenerationPlan,
) -> None:
    """Generate the full canonical scenario (truth, estate, observed) into ``output_dir``."""
    output_dir = Path(output_dir)
    graph = generate_truth_graph(config, plan, CANONICAL_TRUTH_SEED)
    write_truth_graph(graph, output_dir / TRUTH_DIRNAME)
    write_estate(
        graph, CANONICAL_ESTATE_PROFILE, CANONICAL_ESTATE_SEED, output_dir / ESTATE_DIRNAME
    )
    result = generate_observed(graph, config, CANONICAL_OBSERVED_PROFILE, CANONICAL_DEFECT_SEED)
    write_observed(result, output_dir / OBSERVED_DIRNAME)


def generate_canonical_from_config_dir(output_dir: Path, config_dir: Path) -> None:
    """Load the configuration from ``config_dir`` and generate the canonical scenario."""
    config = load_config(config_dir)
    plan = load_generation_plan(config_dir)
    generate_canonical(output_dir, config, plan)


def digest_tree(root: Path, exclude: Iterable[str] = ()) -> dict[str, str]:
    """Return ``{posix_relative_path: sha256}`` for every file under ``root``.

    Paths use forward slashes so the contract is identical on every platform.
    """
    excluded = set(exclude) | EXCLUDED_NAMES
    digests: dict[str, str] = {}
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or path.name in excluded:
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(EXCLUDED_PREFIXES):
            continue
        digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(digests.items()))


def is_portable(relative_path: str) -> bool:
    """Return whether ``relative_path`` is guaranteed across the dependency range."""
    return relative_path.startswith(PORTABLE_PREFIXES)


def split_digests(digests: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Split a digest map into ``(portable, environment_scoped)``."""
    portable = {k: v for k, v in digests.items() if is_portable(k)}
    scoped = {k: v for k, v in digests.items() if not is_portable(k)}
    return portable, scoped


__all__ = [
    "CANONICAL_TRUTH_SEED",
    "CANONICAL_ESTATE_SEED",
    "CANONICAL_DEFECT_SEED",
    "CANONICAL_ESTATE_PROFILE",
    "CANONICAL_OBSERVED_PROFILE",
    "TRUTH_DIRNAME",
    "ESTATE_DIRNAME",
    "OBSERVED_DIRNAME",
    "PORTABLE_PREFIXES",
    "EXCLUDED_NAMES",
    "EXCLUDED_PREFIXES",
    "DIGEST_ALGORITHM",
    "scenario_identity",
    "config_input_paths",
    "config_fingerprint",
    "CONFIG_SUFFIXES",
    "generate_canonical",
    "generate_canonical_from_config_dir",
    "digest_tree",
    "is_portable",
    "split_digests",
]
