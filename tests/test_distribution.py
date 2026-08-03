"""What the built wheel must and must not contain.

Packaging faults are invisible until someone installs the package, at which
point they are the first thing that user meets. Two of them matter enough to
test: a *missing* resource (the canonical configuration, without which an
installed CLI cannot generate anything) and an *included* one that should never
leave a developer's machine.

The wheel is built once per session with ``uv build``. If ``uv`` is not on PATH
the module skips rather than failing — the release checklist covers the case
where the build itself is the thing under test.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Resources the distribution must carry for an installed user to be able to work.
REQUIRED_MEMBER_PREFIXES = (
    "dataswamp_biosystems/_config/",
    "dataswamp_biosystems/_examples/predictions/",
)

REQUIRED_MEMBERS = (
    "dataswamp_biosystems/_config/company.yaml",
    "dataswamp_biosystems/_config/generation.yaml",
    "dataswamp_biosystems/_config/truth/generation-plan.yaml",
    "dataswamp_biosystems/_config/vocabularies/modalities.yaml",
    "dataswamp_biosystems/_examples/predictions/perfect.jsonl",
    "dataswamp_biosystems/_examples/predictions/partial.jsonl",
    "dataswamp_biosystems/_examples/predictions/unsafe.jsonl",
    "dataswamp_biosystems/py.typed",
)

# Anything matching these must never ship. Credentials and developer scratch are
# the obvious ones; caches and OS artefacts are the ones that actually happen.
FORBIDDEN_SUBSTRINGS = (
    ".env",
    ".git/",
    ".venv/",
    "__pycache__",
    ".pyc",
    ".DS_Store",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "id_rsa",
    "credentials",
    "secrets",
    ".pem",
    ".key",
    "generated/",
)


@pytest.fixture(scope="module")
def wheel_members(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    if shutil.which("uv") is None:  # pragma: no cover - environment dependent
        pytest.skip("uv is not available to build the distribution")
    out = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:  # pragma: no cover - surfaced as a failure message
        pytest.fail(f"uv build failed:\n{result.stdout}\n{result.stderr}")
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    with zipfile.ZipFile(wheels[0]) as archive:
        return archive.namelist()


@pytest.mark.slow
@pytest.mark.parametrize("member", REQUIRED_MEMBERS)
def test_wheel_carries_required_resources(wheel_members: list[str], member: str) -> None:
    assert member in wheel_members, f"{member} is missing from the wheel"


@pytest.mark.slow
def test_wheel_carries_the_whole_config_and_example_trees(wheel_members: list[str]) -> None:
    for prefix in REQUIRED_MEMBER_PREFIXES:
        assert any(name.startswith(prefix) for name in wheel_members), f"no {prefix} in the wheel"

    # The packaged config must be complete, not a partial copy: the loader reads
    # every one of these and an installed user has no fallback.
    packaged = {
        name[len("dataswamp_biosystems/_config/") :]
        for name in wheel_members
        if name.startswith("dataswamp_biosystems/_config/") and name.endswith(".yaml")
    }
    tracked = {
        path.relative_to(REPO_ROOT / "config").as_posix()
        for path in (REPO_ROOT / "config").rglob("*.yaml")
    }
    assert packaged == tracked, f"packaged config differs from config/: {packaged ^ tracked}"


@pytest.mark.slow
def test_wheel_excludes_sensitive_and_development_files(wheel_members: list[str]) -> None:
    offenders = [
        name
        for name in wheel_members
        for needle in FORBIDDEN_SUBSTRINGS
        if needle in name
        # ``.pyc`` would also match nothing legitimate, but a dist-info RECORD
        # line never appears as a member name, so no exemption is needed here.
    ]
    assert not offenders, f"the wheel ships files it must not: {sorted(set(offenders))}"


@pytest.mark.slow
def test_wheel_declares_the_console_script(wheel_members: list[str]) -> None:
    entry_points = [name for name in wheel_members if name.endswith("entry_points.txt")]
    assert entry_points, "the wheel declares no entry points"
