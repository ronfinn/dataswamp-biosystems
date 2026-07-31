"""CLI tests for output-directory containment across the generation commands.

Every path used here lives under ``tmp_path``. The repository's authored
configuration is *copied* into the temporary tree and the copy is what the
commands are pointed at, so no test can reach the real ``config/`` directory,
the repository root, or any user directory — even in the cases that deliberately
request an unsafe output path.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataswamp_biosystems.cli import app
from dataswamp_biosystems.truth.writer import MANIFEST_NAME
from tests.truth.conftest import REAL_CONFIG_DIR, TEST_SEED

runner = CliRunner()


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A synthetic repository root holding a copy of the canonical configuration."""
    shutil.copytree(REAL_CONFIG_DIR, tmp_path / "config")
    (tmp_path / "generated").mkdir()
    return tmp_path


@pytest.fixture
def truth_dir(fake_repo: Path) -> Path:
    """A generated truth graph inside the synthetic repository."""
    out = fake_repo / "generated" / "truth"
    result = runner.invoke(
        app,
        [
            "generate-truth",
            "--config-dir",
            str(fake_repo / "config"),
            "--output-dir",
            str(out),
            "--seed",
            str(TEST_SEED),
        ],
    )
    assert result.exit_code == 0, result.output
    return out


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(directory)): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def _staging_leftovers(parent: Path) -> list[str]:
    """Temporary/backup staging directories the writers create mid-replacement."""
    return sorted(
        p.name
        for p in parent.iterdir()
        if p.name.startswith(".") and (".tmp-" in p.name or ".bak-" in p.name)
    )


def _generate_truth(fake_repo: Path, out: Path, *extra: str) -> object:
    return runner.invoke(
        app,
        [
            "generate-truth",
            "--config-dir",
            str(fake_repo / "config"),
            "--output-dir",
            str(out),
            "--seed",
            str(TEST_SEED),
            *extra,
        ],
    )


# --- unsafe output paths, per command ---------------------------------------


@pytest.mark.parametrize(
    ("case", "relative_output"),
    [
        ("output is the repository root", "."),
        ("output is the config directory", "config"),
        ("output is inside the config directory", "config/vocabularies"),
        ("output contains the config directory", ".."),
    ],
)
def test_generate_truth_rejects_unsafe_output(
    fake_repo: Path, case: str, relative_output: str
) -> None:
    protected_before = _snapshot(fake_repo / "config")

    result = _generate_truth(fake_repo, fake_repo / relative_output, "--force")

    assert result.exit_code == 2, f"{case}: {result.output}"
    assert "Refusing to generate into" in result.output
    # The protected input is untouched, byte for byte.
    assert _snapshot(fake_repo / "config") == protected_before
    # Nothing was staged: the guard ran before any filesystem mutation.
    assert _staging_leftovers(fake_repo) == []


def test_generate_truth_rejects_symlink_alias_to_config(fake_repo: Path) -> None:
    alias = fake_repo / "config-alias"
    alias.symlink_to(fake_repo / "config", target_is_directory=True)
    protected_before = _snapshot(fake_repo / "config")

    result = _generate_truth(fake_repo, alias, "--force")

    assert result.exit_code == 2, result.output
    assert _snapshot(fake_repo / "config") == protected_before
    assert alias.is_symlink()


def test_generate_files_rejects_unsafe_output(fake_repo: Path) -> None:
    protected_before = _snapshot(fake_repo / "config")
    result = runner.invoke(
        app,
        [
            "generate-files",
            "--profile",
            "tiny",
            "--config-dir",
            str(fake_repo / "config"),
            "--output-dir",
            str(fake_repo / "config"),
            "--seed",
            str(TEST_SEED),
            "--force",
        ],
    )
    assert result.exit_code == 2, result.output
    assert _snapshot(fake_repo / "config") == protected_before
    assert _staging_leftovers(fake_repo) == []


@pytest.mark.parametrize("target", ["config", "generated/truth"])
def test_inject_defects_rejects_unsafe_output(
    fake_repo: Path, truth_dir: Path, target: str
) -> None:
    config_before = _snapshot(fake_repo / "config")
    truth_before = _snapshot(truth_dir)

    result = runner.invoke(
        app,
        [
            "inject-defects",
            "--truth",
            str(truth_dir / MANIFEST_NAME),
            "--config-dir",
            str(fake_repo / "config"),
            "--output-dir",
            str(fake_repo / target),
            "--seed",
            str(TEST_SEED),
            "--force",
        ],
    )

    assert result.exit_code == 2, result.output
    assert _snapshot(fake_repo / "config") == config_before
    assert _snapshot(truth_dir) == truth_before


def test_inject_defects_rejects_output_inside_truth(fake_repo: Path, truth_dir: Path) -> None:
    truth_before = _snapshot(truth_dir)
    result = runner.invoke(
        app,
        [
            "inject-defects",
            "--truth",
            str(truth_dir / MANIFEST_NAME),
            "--config-dir",
            str(fake_repo / "config"),
            "--output-dir",
            str(truth_dir / "observed"),
            "--seed",
            str(TEST_SEED),
        ],
    )
    assert result.exit_code == 2, result.output
    assert _snapshot(truth_dir) == truth_before


# --- safe output paths must keep working ------------------------------------


def test_safe_sibling_output_still_succeeds(fake_repo: Path, truth_dir: Path) -> None:
    """The canonical layout — truth, estate and observed as siblings — must work."""
    observed = fake_repo / "generated" / "observed"
    result = runner.invoke(
        app,
        [
            "inject-defects",
            "--truth",
            str(truth_dir / MANIFEST_NAME),
            "--config-dir",
            str(fake_repo / "config"),
            "--output-dir",
            str(observed),
            "--seed",
            str(TEST_SEED),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (observed / "observed-graph.json").exists()
    assert _staging_leftovers(fake_repo / "generated") == []


# --- non-empty output handling ----------------------------------------------


def test_nonempty_safe_output_without_force_exits_two(fake_repo: Path) -> None:
    out = fake_repo / "generated" / "truth"
    out.mkdir(parents=True)
    (out / "sentinel.txt").write_text("keep me", encoding="utf-8")

    result = _generate_truth(fake_repo, out)

    assert result.exit_code == 2, result.output
    assert "not empty" in result.output
    # Refusing must not have touched the existing contents.
    assert (out / "sentinel.txt").read_text(encoding="utf-8") == "keep me"


def test_nonempty_safe_output_with_force_succeeds(fake_repo: Path) -> None:
    out = fake_repo / "generated" / "truth"
    out.mkdir(parents=True)
    (out / "sentinel.txt").write_text("stale", encoding="utf-8")

    result = _generate_truth(fake_repo, out, "--force")

    assert result.exit_code == 0, result.output
    assert not (out / "sentinel.txt").exists()
    assert (out / MANIFEST_NAME).exists()


def test_force_does_not_override_the_containment_guard(fake_repo: Path) -> None:
    """``--force`` permits replacing a *safe* directory only, never a protected one."""
    protected_before = _snapshot(fake_repo / "config")
    assert _generate_truth(fake_repo, fake_repo / "config", "--force").exit_code == 2
    assert _snapshot(fake_repo / "config") == protected_before
