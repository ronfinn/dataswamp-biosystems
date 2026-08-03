"""The adapter's architectural boundary, enforced rather than merely documented.

ADR 0002 fixes the dependency direction: DataSwamp's layers know nothing about
any catalogue, and an adapter consumes their emitted artefacts. A grep-based
test is crude, but it is the only kind that fails when someone adds the wrong
import — a comment does not.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "dataswamp_biosystems"

# Every layer that must remain catalogue-independent, plus the bundle packager:
# a bundle is the adapter's *input*, so it may not depend on the adapter either.
CORE_PACKAGES = ("company", "truth", "estate", "observed", "evaluation", "bundle")


def _module_paths(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("package", CORE_PACKAGES)
def test_no_core_layer_imports_the_adapter(package: str) -> None:
    for path in _module_paths(package):
        for name in _imported_names(path):
            assert "adapters" not in name, f"{path} imports {name}"
            assert "datahub" not in name.lower(), f"{path} imports {name}"


@pytest.mark.parametrize("package", CORE_PACKAGES)
def test_no_core_layer_mentions_datahub_in_code(package: str) -> None:
    """Docstrings may discuss DataHub; executable code may not name it."""
    for path in _module_paths(package):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                rendered = ast.unparse(node).lower()
                assert "datahub" not in rendered, f"{path}: {rendered}"


def test_datahub_is_not_a_declared_dependency() -> None:
    """The adapter emits schemas rather than depending on a catalogue client."""
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "acryl-datahub" not in pyproject
    assert "datahub" not in pyproject.lower().split("[tool.")[0]


def test_the_adapter_only_reaches_the_project_through_the_bundle_reader() -> None:
    """The adapter's interface to this project is the bundle, not the generators."""
    forbidden = {"generator", "engine", "inject", "index"}
    for path in _module_paths("adapters"):
        for name in _imported_names(path):
            if not name.startswith("dataswamp_biosystems"):
                continue
            tail = name.rsplit(".", 1)[-1]
            assert tail not in forbidden, f"{path} imports {name}"
