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
def test_no_core_layer_mentions_a_catalogue_in_code(package: str) -> None:
    """Docstrings may discuss a catalogue; executable code may not name one."""
    for path in _module_paths(package):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                rendered = ast.unparse(node).lower()
                assert "datahub" not in rendered, f"{path}: {rendered}"
                assert "openmetadata" not in rendered, f"{path}: {rendered}"


@pytest.mark.parametrize("package", CORE_PACKAGES)
def test_no_core_layer_imports_openmetadata(package: str) -> None:
    for path in _module_paths(package):
        for name in _imported_names(path):
            assert "openmetadata" not in name.lower(), f"{path} imports {name}"


def test_datahub_is_not_a_declared_dependency() -> None:
    """The adapter emits schemas rather than depending on a catalogue client."""
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "acryl-datahub" not in pyproject
    assert "datahub" not in pyproject.lower().split("[tool.")[0]


def test_no_openmetadata_client_is_a_dependency() -> None:
    """The OpenMetadata adapter emits schemas rather than depending on a client.

    ``jsonschema`` is a *dev* dependency — it validates emitted payloads against
    the vendored upstream schemas in the test suite — and must never become a
    runtime one. See ADR 0007.
    """
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    runtime = pyproject.split("[dependency-groups]")[0].lower()
    for package in ("openmetadata-ingestion", "openmetadata", "requests", "httpx", "jsonschema"):
        assert package not in runtime, f"{package} became a runtime dependency"


# ---------------------------------------------------------------------------
# The OpenMetadata adapter's boundaries.
# ---------------------------------------------------------------------------
# Two adapters now exist. They must stay independent of each other as well as of
# the core: a shared helper today is a coupling to undo when their catalogues'
# rules diverge, and ``adapters/common/`` is deliberately not created until it is
# clear what is genuinely common rather than merely similar.

# The *offline* modules. ``__init__`` is deliberately absent: it is the package
# façade and now re-exports the live path's names (``JWT_TOKEN_ENV`` among them),
# so holding it to the offline rules would assert that the live path does not
# exist rather than that it is contained.
OPENMETADATA_MODULES = ("coverage", "errors", "export", "fqn", "mapping", "validate")


def _openmetadata_module_paths() -> list[Path]:
    return [SRC / "adapters" / "openmetadata" / f"{name}.py" for name in OPENMETADATA_MODULES]


def test_the_two_adapters_do_not_import_each_other() -> None:
    for path in _openmetadata_module_paths():
        for name in _imported_names(path):
            assert "datahub" not in name.lower(), f"{path.name} imports {name}"
    for path in _module_paths("adapters/datahub"):
        for name in _imported_names(path):
            assert "openmetadata" not in name.lower(), f"{path.name} imports {name}"


def test_no_adapters_common_package_exists_yet() -> None:
    """Deferred on purpose until both adapters have settled. See issue #33."""
    assert not (SRC / "adapters" / "common").exists()


def test_the_offline_openmetadata_modules_open_no_socket() -> None:
    """The mapping and export path stay offline even though a live path now exists."""
    network = {"urllib", "http", "socket", "ssl", "asyncio", "requests", "httpx"}
    for path in _openmetadata_module_paths():
        for name in _imported_names(path):
            assert name.split(".")[0] not in network, f"{path.name} imports {name}"


def test_no_offline_openmetadata_module_names_a_live_endpoint_host() -> None:
    """Endpoint *paths* are recorded in the plan; hosts, schemes and credentials are not."""
    for path in _openmetadata_module_paths():
        text = path.read_text(encoding="utf-8")
        for fragment in ("http://", "https://localhost", "getpass", "TOKEN", "Authorization"):
            assert fragment not in text, f"{path.name} names {fragment!r}"


# ---------------------------------------------------------------------------
# The OpenMetadata live path's boundaries.
# ---------------------------------------------------------------------------
# The same three claims the DataHub live path is held to, enforced separately
# rather than by sharing a helper: the two adapters must be free to diverge.

OPENMETADATA_LIVE_MODULES = ("client", "ingest", "readback", "roundtrip", "normalize", "report")


def _openmetadata_live_paths() -> list[Path]:
    return [SRC / "adapters" / "openmetadata" / f"{name}.py" for name in OPENMETADATA_LIVE_MODULES]


def test_the_openmetadata_live_path_never_reaches_for_a_privileged_artefact() -> None:
    """``ingest-openmetadata`` and ``verify-om-ingestion`` consume an emitted export.

    Verifying an observed export must need no privilege — that is the whole point
    of having an observed export — so the live modules may not so much as *name* a
    bundle reader, a defect ledger, a rule scope, a control partition, a scenario
    or an expected finding, even to strengthen a leak probe.
    """
    for path in _openmetadata_live_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name | ast.Attribute):
                continue
            rendered = ast.unparse(node)
            for surface in PRIVILEGED_SURFACES:
                assert surface not in rendered, f"{path.name} reaches for {surface}: {rendered}"


def test_the_openmetadata_live_path_imports_no_bundle_or_observed_module() -> None:
    """A bundle is the *offline* exporter's input, not the live path's."""
    for path in _openmetadata_live_paths():
        for name in _imported_names(path):
            assert ".bundle" not in name, f"{path.name} imports {name}"
            assert ".observed" not in name, f"{path.name} imports {name}"
            assert ".evaluation" not in name, f"{path.name} imports {name}"
            assert ".comparison" not in name, f"{path.name} imports {name}"


def test_only_the_openmetadata_client_opens_a_socket() -> None:
    network = {"urllib", "http", "socket", "ssl", "asyncio", "requests", "httpx"}
    for path in _openmetadata_live_paths():
        if path.name == "client.py":
            continue
        for name in _imported_names(path):
            assert name.split(".")[0] not in network, f"{path.name} imports {name}"


def test_no_openmetadata_endpoint_path_appears_outside_the_client() -> None:
    """Endpoint strings and authorization logic are the other half of the boundary.

    ``mapping.py`` is exempt and stays exempt: the emitted plan carries an
    ``endpoint`` annotation as *data*, which is part of the frozen Issue A export
    contract. ``client.py`` deliberately does not read it — it owns the live paths
    itself — so a stale annotation cannot mis-address a request.
    """
    for path in _openmetadata_live_paths():
        if path.name == "client.py":
            continue
        text = path.read_text(encoding="utf-8")
        for fragment in ("/api/v1/", "http://", "https://", "Authorization", "Bearer "):
            assert fragment not in text, f"{path.name} names {fragment!r}"


def test_the_two_live_paths_do_not_import_each_other() -> None:
    for path in _openmetadata_live_paths():
        for name in _imported_names(path):
            assert "datahub" not in name.lower(), f"{path.name} imports {name}"


def test_the_openmetadata_live_path_adds_no_dependency() -> None:
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    runtime = pyproject.split("[dependency-groups]")[0].lower()
    for package in ("openmetadata-ingestion", "requests", "httpx", "aiohttp", "urllib3"):
        assert package not in runtime, f"{package} became a runtime dependency"


def test_the_live_path_fabricates_no_table_column_or_test_entity() -> None:
    """The Issue A decision stands: quality checks have no honest OpenMetadata target.

    ``TestDefinition.entityType`` admits only ``TABLE`` and ``COLUMN`` while
    DataSwamp datasets are Containers, so unlocking native quality tests would
    mean inventing a Table. The live path must not do one level down what the
    mapping refused to do.

    Prose may discuss these — explaining *why* a thing is refused is the point of
    the refusal. Executable code and short string literals may not name one, which
    is what would be needed to build such a request.

    ``report.py`` is out of scope and deliberately so: it can send nothing, and it
    names these entities precisely to *declare them unsupported* in every emitted
    report. A test that forbade that would be forbidding the disclosure.
    """
    forbidden = (
        "createtable",
        "createdatabase",
        "createdatabaseschema",
        "testdefinition",
        "testsuite",
        "testcase",
        "createpipeline",
        "datacontract",
    )
    for path in _openmetadata_live_paths():
        if path.name == "report.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                rendered = ast.unparse(node).lower()
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # A docstring is prose; every other string literal is a value
                # that could reach a request body or a path.
                if len(node.value) > 200:
                    continue
                rendered = node.value.lower()
            else:
                continue
            for fragment in forbidden:
                assert fragment not in rendered, f"{path.name} names {fragment!r}: {rendered}"


def test_the_openmetadata_adapter_claims_no_verified_live_version() -> None:
    """No canary has run, so no compatibility point exists. See ADR 0006."""
    from dataswamp_biosystems.adapters.openmetadata import VERIFIED_OPENMETADATA_VERSION

    assert VERIFIED_OPENMETADATA_VERSION is None


def test_the_openmetadata_adapter_only_reaches_the_project_through_the_bundle_reader() -> None:
    forbidden = {"generator", "engine", "inject", "index", "scenarios", "registry"}
    for path in _openmetadata_module_paths():
        for name in _imported_names(path):
            if not name.startswith("dataswamp_biosystems"):
                continue
            assert name.rsplit(".", 1)[-1] not in forbidden, f"{path.name} imports {name}"


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
