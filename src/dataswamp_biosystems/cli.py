"""Command-line interface for Data Swamp Biosystems."""

from __future__ import annotations

import typer

from dataswamp_biosystems import __version__

app = typer.Typer(help="Data Swamp Biosystems command-line interface.")


@app.callback()
def callback() -> None:
    """Data Swamp Biosystems command-line interface."""


@app.command()
def version() -> None:
    """Print the installed package version and exit."""
    typer.echo(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
