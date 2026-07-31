"""Unit tests for the shared output-directory containment policy.

These exercise the path semantics directly, independently of Typer, so a change
in CLI wiring cannot mask a change in the rule itself. Every path here is built
under ``tmp_path``: no test touches the real repository, its ``config/``
directory, or any user directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dataswamp_biosystems.paths import (
    CONFIG_INPUT_LABEL,
    TRUTH_INPUT_LABEL,
    UnsafeOutputDirectoryError,
    ensure_safe_output_dir,
    resolve_path,
)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A synthetic repository: a root holding ``config/`` and ``generated/truth``."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "company.yaml").write_text("synthetic: true\n", encoding="utf-8")
    (tmp_path / "generated" / "truth").mkdir(parents=True)
    (tmp_path / "generated" / "truth" / "truth-graph.json").write_text("{}\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def protected(fake_repo: Path) -> dict[str, Path]:
    return {
        CONFIG_INPUT_LABEL: fake_repo / "config",
        TRUTH_INPUT_LABEL: fake_repo / "generated" / "truth",
    }


def _reject(output: Path, protected: dict[str, Path]) -> UnsafeOutputDirectoryError:
    with pytest.raises(UnsafeOutputDirectoryError) as excinfo:
        ensure_safe_output_dir(output, protected_paths=protected)
    return excinfo.value


def test_output_equal_to_repository_root_is_rejected(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    # The root is rejected because it *contains* protected inputs; no explicit
    # repository-root detection is involved.
    error = _reject(fake_repo, protected)
    assert error.relation == "contains"


def test_output_equal_to_config_dir_is_rejected(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    error = _reject(fake_repo / "config", protected)
    assert error.relation == "is"
    assert error.protected_label == CONFIG_INPUT_LABEL


def test_output_equal_to_truth_dir_is_rejected(fake_repo: Path, protected: dict[str, Path]) -> None:
    error = _reject(fake_repo / "generated" / "truth", protected)
    assert error.relation == "is"
    assert error.protected_label == TRUTH_INPUT_LABEL


def test_output_containing_a_protected_path_is_rejected(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    # ``generated/`` contains the truth input directory.
    error = _reject(fake_repo / "generated", protected)
    assert error.relation == "contains"
    assert error.protected_label == TRUTH_INPUT_LABEL


def test_output_inside_a_protected_path_is_rejected(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    error = _reject(fake_repo / "generated" / "truth" / "observed", protected)
    assert error.relation == "is-inside"
    assert error.protected_label == TRUTH_INPUT_LABEL


def test_symlink_alias_to_protected_path_is_rejected(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    alias = fake_repo / "config-alias"
    alias.symlink_to(fake_repo / "config", target_is_directory=True)
    error = _reject(alias, protected)
    assert error.relation == "is"
    assert error.protected_label == CONFIG_INPUT_LABEL


def test_symlinked_protected_path_is_still_matched(fake_repo: Path) -> None:
    """Protection follows symlinks on the *protected* side too."""
    alias = fake_repo / "truth-alias"
    alias.symlink_to(fake_repo / "generated" / "truth", target_is_directory=True)
    with pytest.raises(UnsafeOutputDirectoryError):
        ensure_safe_output_dir(
            fake_repo / "generated" / "truth",
            protected_paths={TRUTH_INPUT_LABEL: alias},
        )


def test_safe_sibling_output_is_accepted(fake_repo: Path, protected: dict[str, Path]) -> None:
    """The canonical layout must keep working: estate beside truth, not inside it."""
    resolved = ensure_safe_output_dir(fake_repo / "generated" / "estate", protected_paths=protected)
    assert resolved == resolve_path(fake_repo / "generated" / "estate")


@pytest.mark.parametrize("name", ["estate", "observed", "truth-2"])
def test_all_canonical_sibling_outputs_are_accepted(
    fake_repo: Path, protected: dict[str, Path], name: str
) -> None:
    ensure_safe_output_dir(fake_repo / "generated" / name, protected_paths=protected)


def test_nonexistent_output_is_accepted_and_resolved(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    """A not-yet-created output directory is normal, and must resolve cleanly."""
    target = fake_repo / "generated" / "brand-new" / "nested"
    assert not target.exists()
    assert ensure_safe_output_dir(target, protected_paths=protected) == resolve_path(target)


def test_dot_dot_traversal_is_normalised_before_comparison(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    sneaky = fake_repo / "generated" / "truth" / ".." / ".." / "config"
    error = _reject(sneaky, protected)
    assert error.relation == "is"
    assert error.protected_label == CONFIG_INPUT_LABEL


def test_redundant_separators_and_dots_are_normalised(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    error = _reject(Path(f"{fake_repo}//config/./"), protected)
    assert error.relation == "is"


def test_error_identifies_both_output_and_protected_path(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    error = _reject(fake_repo / "config", protected)
    message = str(error)
    assert str(resolve_path(fake_repo / "config")) in message
    assert CONFIG_INPUT_LABEL in message
    assert error.output_dir == resolve_path(fake_repo / "config")
    assert error.protected_path == resolve_path(fake_repo / "config")


def test_conflicting_label_is_deterministic(fake_repo: Path) -> None:
    """A path overlapping several protected entries reports the label-sorted first.

    The root contains both protected inputs; insertion order must not decide
    which conflict is reported, so the message stays stable for assertions.
    """
    forward = {
        CONFIG_INPUT_LABEL: fake_repo / "config",
        TRUTH_INPUT_LABEL: fake_repo / "generated" / "truth",
    }
    reversed_order = dict(reversed(list(forward.items())))
    assert _reject(fake_repo, forward).protected_label == CONFIG_INPUT_LABEL
    assert _reject(fake_repo, reversed_order).protected_label == CONFIG_INPUT_LABEL


def test_empty_protected_set_accepts_anything(fake_repo: Path) -> None:
    assert ensure_safe_output_dir(fake_repo, protected_paths={}) == resolve_path(fake_repo)


def test_guard_does_not_create_or_remove_anything(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    """The check must be purely non-destructive, including on the rejected path."""
    before = sorted(p.relative_to(fake_repo) for p in fake_repo.rglob("*"))
    _reject(fake_repo / "config", protected)
    ensure_safe_output_dir(fake_repo / "generated" / "estate", protected_paths=protected)
    assert sorted(p.relative_to(fake_repo) for p in fake_repo.rglob("*")) == before


# --- case canonicalisation --------------------------------------------------
#
# On a case-insensitive filesystem (macOS/APFS by default, Windows), ``CONFIG``
# and ``config`` name one directory while ``Path.resolve()`` preserves whichever
# spelling was typed. Without canonicalisation a case variant slipped past the
# guard entirely, so ``--output-dir CONFIG --force`` destroyed the configuration
# it was supposed to protect. These tests pin that regression.


def _case_insensitive(tmp_path: Path) -> bool:
    """Whether *this* temporary filesystem treats case-varied names as one entry."""
    probe = tmp_path / "case-probe-dir"
    probe.mkdir()
    try:
        return (tmp_path / "CASE-PROBE-DIR").is_dir()
    finally:
        probe.rmdir()


def _require_case_insensitive(tmp_path: Path) -> None:
    if not _case_insensitive(tmp_path):
        pytest.skip("filesystem is case-sensitive; a case alias is a genuinely distinct path")


@pytest.mark.parametrize("alias", ["CONFIG", "Config", "cOnFiG"])
def test_case_varied_alias_of_config_is_rejected(
    fake_repo: Path, protected: dict[str, Path], alias: str
) -> None:
    _require_case_insensitive(fake_repo)
    error = _reject(fake_repo / alias, protected)
    assert error.relation == "is"
    assert error.protected_label == CONFIG_INPUT_LABEL


def test_case_varied_alias_of_truth_is_rejected(
    fake_repo: Path, protected: dict[str, Path]
) -> None:
    _require_case_insensitive(fake_repo)
    error = _reject(fake_repo / "generated" / "TRUTH", protected)
    assert error.relation == "is"
    assert error.protected_label == TRUTH_INPUT_LABEL


def test_case_varied_descendant_is_rejected(fake_repo: Path, protected: dict[str, Path]) -> None:
    (fake_repo / "config" / "vocabularies").mkdir()
    _require_case_insensitive(fake_repo)
    error = _reject(fake_repo / "CONFIG" / "vocabularies", protected)
    assert error.relation == "is-inside"
    assert error.protected_label == CONFIG_INPUT_LABEL


def test_case_varied_ancestor_is_rejected(fake_repo: Path, protected: dict[str, Path]) -> None:
    _require_case_insensitive(fake_repo)
    error = _reject(fake_repo / "GENERATED", protected)
    assert error.relation == "contains"
    assert error.protected_label == TRUTH_INPUT_LABEL


def test_case_varied_sibling_is_still_accepted(fake_repo: Path, protected: dict[str, Path]) -> None:
    """Canonicalising case must not make an unrelated sibling look protected."""
    ensure_safe_output_dir(fake_repo / "GENERATED" / "estate", protected_paths=protected)


# The following exercise the canonicalisation helper itself, so they assert
# meaningful behaviour on case-sensitive CI as well as case-insensitive laptops.


def test_resolve_path_canonicalises_existing_component_case(fake_repo: Path) -> None:
    _require_case_insensitive(fake_repo)
    assert resolve_path(fake_repo / "CONFIG") == resolve_path(fake_repo / "config")
    assert resolve_path(fake_repo / "CONFIG").name == "config"


def test_resolve_path_preserves_an_exact_match(fake_repo: Path) -> None:
    """An exactly-spelled entry always wins, so case-sensitive layouts are safe."""
    assert resolve_path(fake_repo / "config").name == "config"
    assert resolve_path(fake_repo / "generated" / "truth").name == "truth"


def test_resolve_path_keeps_nonexistent_tail_verbatim(fake_repo: Path) -> None:
    target = fake_repo / "generated" / "BrandNew" / "Nested"
    resolved = resolve_path(target)
    assert resolved.name == "Nested"
    assert resolved.parent.name == "BrandNew"


def test_resolve_path_is_idempotent(fake_repo: Path) -> None:
    once = resolve_path(fake_repo / "CONFIG")
    assert resolve_path(once) == once


def test_ambiguous_case_matches_do_not_collapse(fake_repo: Path) -> None:
    """Where case *is* significant, distinct entries must stay distinct.

    Only reachable on a case-sensitive filesystem, where ``config`` and
    ``CONFIG`` are two directories: canonicalisation must not fold one onto the
    other, which would wrongly reject a legitimate output.
    """
    if _case_insensitive(fake_repo):
        pytest.skip("filesystem is case-insensitive; both spellings cannot coexist")
    upper = fake_repo / "CONFIG"
    upper.mkdir()
    assert resolve_path(upper) != resolve_path(fake_repo / "config")
    # A distinct directory that merely case-matches a protected one is allowed.
    ensure_safe_output_dir(upper, protected_paths={CONFIG_INPUT_LABEL: fake_repo / "config"})


def test_unreadable_parent_falls_back_to_requested_spelling(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A listing failure must degrade to plain resolve, never crash the guard."""

    def _boom(_path: object) -> object:
        raise PermissionError("listing refused")

    monkeypatch.setattr("dataswamp_biosystems.paths.os.scandir", _boom)
    assert resolve_path(fake_repo / "config").name == "config"
    # The guard still functions on exactly-spelled paths.
    with pytest.raises(UnsafeOutputDirectoryError):
        ensure_safe_output_dir(
            fake_repo / "config", protected_paths={CONFIG_INPUT_LABEL: fake_repo / "config"}
        )
