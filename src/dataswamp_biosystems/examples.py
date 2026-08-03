"""Locating the example prediction submissions that ship with the package.

The examples under ``examples/predictions/`` are part of the release surface,
not test data: the quick start scores one of them, and a new user reads them to
learn the prediction contract. They are therefore shipped *inside* the
distribution as well as tracked in the repository, so ``pip install`` alone is
enough to run the worked example.

Resolution mirrors :func:`dataswamp_biosystems.company.loader.resolve_config_dir`:
a source checkout's ``examples/predictions/`` wins when it is present, and the
packaged copy is the fallback. The two are byte-identical copies of the same
tracked files.
"""

from __future__ import annotations

from pathlib import Path

# The example a checkout carries, relative to the working directory.
CHECKOUT_EXAMPLES_DIR = Path("examples") / "predictions"

# The same files, copied into the distribution at build time (see
# ``[tool.hatch.build.targets.wheel.force-include]`` in ``pyproject.toml``).
PACKAGED_EXAMPLES_DIR = Path(__file__).resolve().parent / "_examples" / "predictions"

# An *editable* install has neither: it imports from ``src/`` in a checkout that
# was never built, so nothing was force-included. Resolve back to that checkout's
# tracked copy, which is the same file the wheel would have carried.
SOURCE_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples" / "predictions"

# The committed example submissions, and what each one demonstrates. Ordered
# from best to worst so a reader meets the reference upper bound first.
EXAMPLE_SUBMISSIONS: tuple[str, ...] = ("perfect", "partial", "unsafe")

DEFAULT_EXAMPLE = "partial"


def examples_dir() -> Path:
    """Return the directory holding the example submissions.

    Prefers a source checkout's copy so an edited example is what runs, and
    falls back to the packaged copy for an installed-only user.
    """
    for candidate in (CHECKOUT_EXAMPLES_DIR, PACKAGED_EXAMPLES_DIR, SOURCE_EXAMPLES_DIR):
        if (candidate / f"{DEFAULT_EXAMPLE}.jsonl").is_file():
            return candidate
    return PACKAGED_EXAMPLES_DIR


def example_path(name: str = DEFAULT_EXAMPLE) -> Path:
    """Return the path to one example submission by name (without ``.jsonl``)."""
    return examples_dir() / f"{name}.jsonl"


__all__ = [
    "CHECKOUT_EXAMPLES_DIR",
    "PACKAGED_EXAMPLES_DIR",
    "SOURCE_EXAMPLES_DIR",
    "EXAMPLE_SUBMISSIONS",
    "DEFAULT_EXAMPLE",
    "examples_dir",
    "example_path",
]
