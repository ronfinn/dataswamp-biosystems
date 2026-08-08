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
CORE_PACKAGES = (
    "company",
    "truth",
    "estate",
    "observed",
    "evaluation",
    "comparison",
    "bundle",
)


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


# ---------------------------------------------------------------------------
# The live path's boundaries.
# ---------------------------------------------------------------------------
# Three separate claims, each enforced rather than documented: the live commands
# are unprivileged, only one module opens a socket, and no catalogue or HTTP
# client became a dependency.

LIVE_MODULES = ("client", "ingest", "readback", "roundtrip", "normalize", "report", "errors")

# Bundle and answer-key surfaces the live path must never reach for. Reaching
# into any of these would make ``ingest-datahub`` / ``verify-ingestion``
# privileged commands, and the entire point of an observed export is that
# verifying it needs no privilege.
PRIVILEGED_SURFACES = (
    "BundleReader",
    "iter_findings",
    "iter_remediations",
    "iter_controls",
    "rule_scope",
    "observed_graph",
    "scenarios",
    "scenario_transformations",
    "mutation",
    "defect",
    "expected_finding",
)


def _live_module_paths() -> list[Path]:
    return [SRC / "adapters" / "datahub" / f"{name}.py" for name in LIVE_MODULES]


def test_the_live_path_never_reaches_for_a_privileged_artefact() -> None:
    """The live commands consume an emitted export and nothing else."""
    for path in _live_module_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name | ast.Attribute):
                continue
            rendered = ast.unparse(node)
            for surface in PRIVILEGED_SURFACES:
                assert surface not in rendered, f"{path.name} reaches for {surface}: {rendered}"


def test_the_live_path_imports_no_bundle_or_observed_module() -> None:
    """A bundle is the *offline* exporter's input, not the live path's."""
    for path in _live_module_paths():
        for name in _imported_names(path):
            assert ".bundle" not in name, f"{path.name} imports {name}"
            assert ".observed" not in name, f"{path.name} imports {name}"
            assert ".evaluation" not in name, f"{path.name} imports {name}"


def test_only_the_client_module_opens_a_socket() -> None:
    """Every endpoint and every socket is confined to one file.

    When a real DataHub release moves an endpoint, exactly one file changes and
    the ingestion, comparison and reporting logic is untouched by it.
    """
    network = {"urllib", "http", "socket", "ssl", "asyncio", "requests", "httpx"}
    for path in _live_module_paths():
        if path.name == "client.py":
            continue
        for name in _imported_names(path):
            root = name.split(".")[0]
            assert root not in network, f"{path.name} imports the network module {name}"


def test_no_endpoint_path_appears_outside_the_client() -> None:
    """Endpoint strings are the other half of the same boundary."""
    for path in _live_module_paths():
        if path.name == "client.py":
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in ("/openapi/", "/aspects?", "ingestProposal", "http://", "https://"):
            assert fragment not in text, f"{path.name} names the endpoint fragment {fragment!r}"


def test_no_http_or_catalogue_client_is_a_dependency() -> None:
    """The live path must add no dependency at all."""
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    declared = pyproject.split("[tool.")[0].lower()
    for package in ("acryl-datahub", "requests", "httpx", "aiohttp", "urllib3"):
        assert package not in declared, f"{package} became a dependency"
