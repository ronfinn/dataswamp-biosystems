"""The licence split, and the invariants that keep it from being blurred.

Two licences apply to two different things — MIT for the software, CC BY-NC 4.0
for the official generated benchmark data the project distributes. The failure
modes worth testing are all forms of the two bleeding into each other: a stale
"same MIT terms" sentence, a resurrected custom licence, a paraphrase of the
data licence that drifts from the canonical one, or a claim over output a third
party generated themselves.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dataswamp_biosystems import licensing

REPO_ROOT = Path(__file__).resolve().parents[1]

# Operative wording from positions the project no longer holds. Historical
# mentions are allowed only where they are unmistakably marked as such, which is
# why the CHANGELOG's dated release entries are exempted below.
STALE_PHRASES = (
    "not-separately-defined",
    "not separately defined",
    "same MIT terms",
    "DataSwamp Community Research",
    "LicenseRef-DataSwamp",
)

# Files that legitimately name a superseded position, because naming it *is*
# their job: the changelog and the ADR record what the position used to be, and
# the tests name the phrases in order to assert they never come back.
HISTORICAL_FILES = frozenset({"CHANGELOG.md", "docs/adr/0004-generated-data-licensing.md"})
EXEMPT_PREFIXES = ("tests/",)

SEARCHED_SUFFIXES = (".md", ".py", ".toml", ".yaml", ".yml")
SKIPPED_DIRS = frozenset({".git", ".venv", "generated", "dist", "build", "__pycache__"})


def _tracked_text_files() -> list[Path]:
    found: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SEARCHED_SUFFIXES:
            continue
        if any(
            part in SKIPPED_DIRS or part.startswith(".")
            for part in path.relative_to(REPO_ROOT).parts[:-1]
        ):
            continue
        found.append(path)
    return found


def test_the_constants_are_the_decided_ones() -> None:
    assert licensing.SOFTWARE_LICENSE == "MIT"
    assert licensing.GENERATED_DATA_LICENSE == "CC-BY-NC-4.0"
    assert licensing.GENERATED_DATA_LICENSE_SINCE == "v0.1.0"
    assert licensing.GENERATED_DATA_LICENSE_URL.startswith("https://creativecommons.org/")


def test_the_canonical_data_licence_resolves_and_states_the_scope() -> None:
    text = licensing.data_license_text()
    assert "CC-BY-NC-4.0" in text
    assert "MIT" in text, "it must say the software is *not* covered by this licence"
    assert "v0.1.0" in text, "the designation is prospective and must say from when"
    assert "noncommercial" in text.lower()
    # Attribution is what makes a published benchmark citable; it is a term of
    # the licence, not an optional courtesy.
    assert "ttribution" in text


def test_the_data_licence_does_not_reach_independently_generated_output() -> None:
    """v0.1 makes no claim over what a third party generates from the MIT software."""
    text = licensing.data_license_text().lower()
    assert "output you generate yourself" in text or "generate yourself" in text
    assert "makes no claim" in text


def test_the_project_does_not_call_the_generated_data_open_source() -> None:
    for name in ("README.md", "DATA-LICENSE.md", "COMMERCIAL-LICENSING.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for match in re.finditer(r"open source", text, flags=re.IGNORECASE):
            window = text[max(0, match.start() - 200) : match.end() + 200].lower()
            assert "not" in window, f"{name} appears to call the generated data open source"


def test_no_operative_stale_licensing_language_remains() -> None:
    offenders: list[str] = []
    for path in _tracked_text_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in HISTORICAL_FILES or relative.startswith(EXEMPT_PREFIXES):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders.extend(f"{relative}: {phrase}" for phrase in STALE_PHRASES if phrase in text)
    assert not offenders, f"stale licensing language remains: {sorted(offenders)}"


def test_the_superseded_decision_document_is_gone() -> None:
    """One authoritative record, not two that can disagree."""
    assert not (REPO_ROOT / "docs" / "generated-data-licensing-decision.md").exists()
    adr = REPO_ROOT / "docs" / "adr" / "0004-generated-data-licensing.md"
    assert adr.is_file()
    text = adr.read_text(encoding="utf-8")
    assert "**Status:** Accepted" in text
    assert "CC-BY-NC-4.0" in text


@pytest.mark.parametrize("name", ["DATA-LICENSE.md", "COMMERCIAL-LICENSING.md"])
def test_the_root_licensing_files_exist(name: str) -> None:
    assert (REPO_ROOT / name).is_file()


def test_the_readme_states_the_three_way_split() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "CC BY-NC 4.0" in text
    assert "MIT" in text
    assert "COMMERCIAL-LICENSING.md" in text
