"""Inject defects into an on-disk truth graph, provably without mutating it.

``inject-defects`` reads a generated truth graph from disk, checksums every truth
input before and after processing, derives the observed state onto independent
JSON copies, and writes the result (plus a ``truth-inputs.json`` checksum
manifest) to a separate output directory. It refuses to write inside the truth
directory and fails loudly if any truth file changes.

The truth graph is reconstructed via the deterministic generator from the seed
recorded in the manifest and cross-checked byte-for-byte against the on-disk
shards, so the typed graph the engine consumes is provably the one on disk — and
the canonical files themselves are never opened for writing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataswamp_biosystems.company.config import CanonicalConfig
from dataswamp_biosystems.observed.engine import (
    OBSERVED_GENERATOR_VERSION,
    ObservedResult,
    generate_observed,
)
from dataswamp_biosystems.observed.errors import ObservedConfigError, ObservedError
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.writer import TRUTH_INPUTS_NAME, write_observed
from dataswamp_biosystems.truth import (
    GenerationPlan,
    generate_truth_graph,
    serialize,
    validate_truth_graph,
)
from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.writer import MANIFEST_NAME, shard_bytes

CHECKSUM_ALGORITHM = "sha256"


class TruthImmutabilityError(ObservedError):
    """A truth input changed during injection — the run is aborted."""


@dataclass(frozen=True)
class InjectionReport:
    """The result of one injection plus the recorded truth-input checksums."""

    result: ObservedResult
    truth_inputs: dict[str, Any]
    output_dir: Path
    truth_dir: Path


def resolve_truth_dir(truth_path: Path) -> Path:
    """Resolve the truth directory from a path to the manifest or the directory."""
    truth_path = Path(truth_path)
    return truth_path.parent if truth_path.is_file() or truth_path.suffix else truth_path


def compute_truth_checksums(truth_dir: Path) -> dict[str, str]:
    """Return ``{relative_path: sha256}`` for every file under ``truth_dir``, sorted."""
    truth_dir = Path(truth_dir)
    checksums: dict[str, str] = {}
    for path in sorted(truth_dir.rglob("*")):
        if path.is_file():
            checksums[str(path.relative_to(truth_dir))] = serialize.digest(path.read_bytes())
    return checksums


def ensure_output_outside_truth(output_dir: Path, truth_dir: Path) -> None:
    """Raise if ``output_dir`` resolves to or inside ``truth_dir``."""
    out = Path(output_dir).resolve()
    truth = Path(truth_dir).resolve()
    if out == truth or truth in out.parents:
        raise ObservedConfigError(
            f"output directory {out} resolves inside the truth directory {truth}; "
            "refusing to write observed state into truth"
        )


def load_truth_from_disk(
    truth_dir: Path, config: CanonicalConfig, plan: GenerationPlan
) -> TruthGraph:
    """Load the truth graph from disk (seed from manifest, verified against shards).

    The graph is regenerated from the manifest's seed and every shard is compared
    byte-for-byte to the on-disk file, so the returned typed graph is provably the
    one on disk. Raises :class:`ObservedConfigError` if the manifest is missing or
    the on-disk truth has drifted from what the generator produces.
    """
    truth_dir = Path(truth_dir)
    manifest_path = truth_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise ObservedConfigError(f"no truth manifest at {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        seed = int(manifest["meta"]["seed"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ObservedConfigError(f"could not read truth manifest {manifest_path}: {exc}") from exc

    graph = generate_truth_graph(config, plan, seed)
    validate_truth_graph(graph, config, plan)

    for name, data in shard_bytes(graph).items():
        path = truth_dir / name
        on_disk = path.read_bytes() if path.exists() else b""
        if on_disk != data:
            raise ObservedConfigError(
                f"truth shard {name} on disk differs from a regeneration from its seed; "
                "regenerate the truth graph before injecting defects"
            )
    return graph


def inject_defects(
    truth_path: Path,
    config: CanonicalConfig,
    plan: GenerationPlan,
    profile: ObservedProfile,
    defect_seed: int,
    output_dir: Path,
) -> InjectionReport:
    """Read truth from disk, inject defects, and write the observed state.

    Guarantees: the output never resolves inside the truth directory; truth
    checksums are recorded before processing and verified unchanged after
    generation and after writing; a ``truth-inputs.json`` manifest records the
    checksums. Raises :class:`TruthImmutabilityError` if any truth file changes.
    """
    truth_dir = resolve_truth_dir(Path(truth_path))
    if not truth_dir.exists():
        raise ObservedConfigError(f"truth directory {truth_dir} does not exist")
    output_dir = Path(output_dir)
    ensure_output_outside_truth(output_dir, truth_dir)

    before = compute_truth_checksums(truth_dir)
    graph = load_truth_from_disk(truth_dir, config, plan)
    result = generate_observed(graph, config, profile, defect_seed)

    if compute_truth_checksums(truth_dir) != before:
        raise TruthImmutabilityError("truth files changed during observed-state generation")

    truth_inputs: dict[str, Any] = {
        "truth_manifest": MANIFEST_NAME,
        "truth_seed": graph.meta.seed,
        "truth_generator_version": graph.meta.generator_version,
        "observed_generator_version": OBSERVED_GENERATOR_VERSION,
        "checksum_algorithm": CHECKSUM_ALGORITHM,
        "verified_unchanged": True,
        "checksums": before,
    }
    extra = {TRUTH_INPUTS_NAME: serialize.manifest_bytes(truth_inputs)}
    write_observed(result, output_dir, extra_files=extra)

    if compute_truth_checksums(truth_dir) != before:
        raise TruthImmutabilityError("truth files changed after writing the observed state")

    return InjectionReport(
        result=result,
        truth_inputs=truth_inputs,
        output_dir=output_dir,
        truth_dir=truth_dir,
    )


__all__ = [
    "CHECKSUM_ALGORITHM",
    "TruthImmutabilityError",
    "InjectionReport",
    "resolve_truth_dir",
    "compute_truth_checksums",
    "ensure_output_outside_truth",
    "load_truth_from_disk",
    "inject_defects",
]
