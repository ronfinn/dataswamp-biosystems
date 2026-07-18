"""Command-line interface for Data Swamp Biosystems."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from dataswamp_biosystems import __version__
from dataswamp_biosystems.company import (
    DEFAULT_CONFIG_DIR,
    CanonicalConfig,
    ConfigLoadError,
    ConfigValidationError,
    load_config,
)
from dataswamp_biosystems.truth import (
    GenerationPlan,
    TruthConfigError,
    TruthValidationError,
    generate_truth_graph,
    load_generation_plan,
    validate_plan_against_config,
    validate_truth_graph,
    write_truth_graph,
)
from dataswamp_biosystems.truth.errors import TruthIssueCollector
from dataswamp_biosystems.truth.writer import MANIFEST_NAME, shard_bytes

app = typer.Typer(help="Data Swamp Biosystems command-line interface.")

DEFAULT_TRUTH_DIR = Path("generated") / "truth"


def _load_config_or_exit(config_dir: Path) -> CanonicalConfig:
    """Load the canonical config, mapping failures to CLI exit codes 1/2."""
    try:
        return load_config(config_dir)
    except ConfigLoadError as exc:
        typer.echo(f"Could not load configuration: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except ConfigValidationError as exc:
        typer.echo(f"Configuration is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc


def _load_plan_or_exit(config_dir: Path, config: CanonicalConfig) -> GenerationPlan:
    """Load and cross-validate the generation plan, mapping failures to exit codes."""
    try:
        plan = load_generation_plan(config_dir)
    except TruthConfigError as exc:
        typer.echo(f"Could not load generation plan: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    issues = TruthIssueCollector()
    validate_plan_against_config(plan, config, issues)
    try:
        issues.raise_if_any()
    except TruthValidationError as exc:
        typer.echo(f"Generation plan is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc
    return plan


@app.callback()
def callback() -> None:
    """Data Swamp Biosystems command-line interface."""


@app.command()
def version() -> None:
    """Print the installed package version and exit."""
    typer.echo(__version__)


@app.command(name="validate-config")
def validate_config(
    config_dir: Annotated[
        Path,
        typer.Option(
            "--config-dir",
            help="Directory containing the canonical configuration YAML files.",
        ),
    ] = DEFAULT_CONFIG_DIR,
) -> None:
    """Load and validate the canonical company configuration.

    Exit codes: 0 = valid, 1 = validation issues, 2 = configuration could not
    be loaded (missing file or malformed YAML).
    """
    config = _load_config_or_exit(config_dir)

    typer.echo(f"Configuration is valid ({config.company.display_name}).")
    typer.echo("Entity counts:")
    for name, count in config.entity_counts().items():
        typer.echo(f"  {name.replace('_', ' ')}: {count}")


@app.command(name="generate-truth")
def generate_truth(
    seed: Annotated[
        int | None,
        typer.Option("--seed", help="Generation seed; defaults to config generation.seed."),
    ] = None,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write the truth graph into."),
    ] = DEFAULT_TRUTH_DIR,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a non-empty output directory."),
    ] = False,
) -> None:
    """Generate the deterministic truth graph under ``output_dir``.

    Exit codes: 0 = written, 1 = invalid config/plan or failed invariants,
    2 = a required file could not be loaded.
    """
    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)
    resolved_seed = seed if seed is not None else config.generation.seed
    if resolved_seed < 0:
        typer.echo(f"Seed must be a non-negative integer, got {resolved_seed}.", err=True)
        raise typer.Exit(code=2)

    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        typer.echo(
            f"Output directory {output_dir} is not empty; pass --force to overwrite.", err=True
        )
        raise typer.Exit(code=1)

    graph = generate_truth_graph(config, plan, resolved_seed)
    try:
        validate_truth_graph(graph, config, plan)
    except TruthValidationError as exc:
        typer.echo(f"Generated truth graph is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    write_truth_graph(graph, output_dir)
    typer.echo(f"Truth graph written to {output_dir} (seed {resolved_seed}).")
    typer.echo("Entity counts:")
    for name, count in graph.entity_counts().items():
        typer.echo(f"  {name.replace('_', ' ')}: {count}")


@app.command(name="validate-truth")
def validate_truth(
    truth_dir: Annotated[
        Path,
        typer.Option("--truth-dir", help="Directory containing a generated truth graph."),
    ] = DEFAULT_TRUTH_DIR,
    config_dir: Annotated[
        Path,
        typer.Option("--config-dir", help="Directory containing the canonical configuration."),
    ] = DEFAULT_CONFIG_DIR,
) -> None:
    """Validate a generated truth graph against config, invariants, and its own bytes.

    Regenerates from the seed recorded in the manifest and confirms both that
    every invariant holds and that the on-disk shards are byte-identical to what
    the generator produces — an end-to-end determinism and integrity check.

    Exit codes: 0 = valid, 1 = invalid or drifted, 2 = manifest missing/unreadable.
    """
    manifest_path = truth_dir / MANIFEST_NAME
    if not manifest_path.exists():
        typer.echo(f"No manifest found at {manifest_path}.", err=True)
        raise typer.Exit(code=2)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        seed = int(manifest["meta"]["seed"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        typer.echo(f"Could not read manifest {manifest_path}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    config = _load_config_or_exit(config_dir)
    plan = _load_plan_or_exit(config_dir, config)
    graph = generate_truth_graph(config, plan, seed)
    try:
        validate_truth_graph(graph, config, plan)
    except TruthValidationError as exc:
        typer.echo(f"Truth graph is invalid — {len(exc.issues)} issue(s):", err=True)
        for issue in exc.issues:
            typer.echo(f"  - {issue.render()}", err=True)
        raise typer.Exit(code=1) from exc

    drifted: list[str] = []
    for name, data in shard_bytes(graph).items():
        on_disk = (truth_dir / name).read_bytes() if (truth_dir / name).exists() else b""
        if on_disk != data:
            drifted.append(name)
    if drifted:
        typer.echo("On-disk shards differ from the regenerated graph:", err=True)
        for name in drifted:
            typer.echo(f"  - {name}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Truth graph at {truth_dir} is valid (seed {seed}).")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
