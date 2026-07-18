"""Command-line interface for Data Swamp Biosystems."""

from __future__ import annotations

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

app = typer.Typer(help="Data Swamp Biosystems command-line interface.")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
