"""The anti-leakage boundary: a baseline sees the observed graph and nothing else.

A published baseline score is only meaningful if the baseline was scored as a
genuine participant. These tests attack that claim from four directions:

* run the agents in a directory where the answers *do not exist*, and check the
  output is unchanged;
* record every path the process opens while an agent runs, and check none of them
  is a privileged artefact;
* check the source of the package never names a privileged file, a privileged
  module, or a canonical entity identifier;
* check the rule catalogue the agents consume carries no injector machinery.

The first is the strongest: it does not ask an agent to behave, it removes the
opportunity.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from dataswamp_biosystems.baselines import (
    BASELINE_NAMES,
    FORBIDDEN_INPUT_FILES,
    PERMITTED_INPUT_FILES,
    ObservedInput,
    get_baseline,
    render_predictions,
    run_baseline,
)
from dataswamp_biosystems.baselines.catalogue import RULE_FACT_FIELDS, RULE_FACTS
from dataswamp_biosystems.observed.writer import OBSERVED_GRAPH_NAME

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "dataswamp_biosystems" / "baselines"
PACKAGE_SOURCES = sorted(PACKAGE_DIR.glob("*.py"))

# Modules a baseline may not import, because importing them is how it would get
# at ground truth. ``observed.defects`` is permitted for its published metadata
# and is confined to ``catalogue.py``; ``observed.writer`` is permitted for its
# filename constants, which is how the forbidden list is spelled.
FORBIDDEN_IMPORTS = (
    "dataswamp_biosystems.truth.writer",
    "dataswamp_biosystems.observed.engine",
    "dataswamp_biosystems.observed.inject",
    "dataswamp_biosystems.observed.index",
    "dataswamp_biosystems.adapters",
)

# Identifier prefixes the canonical scenario uses. A baseline that hard-coded one
# would be answering from memory rather than detecting anything, and would also
# silently break on any other seed or profile.
CANONICAL_ID_PATTERN = re.compile(
    r"\b(?:ds|dp|file|person|team|study|prog|spec|subj|assay|irun|prun|gov|qc|iu|mta|"
    r"contract|edge)-[a-z0-9]+-[a-z0-9-]+\b"
)


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_agents_produce_identical_output_without_the_answers_on_disk(
    name: str, real_observed_dir: Path, observed_graph_only: Path
) -> None:
    """Delete the ground truth from the filesystem; the submission must not move."""
    agent = get_baseline(name)
    with_answers = render_predictions(
        run_baseline(agent, ObservedInput.load(real_observed_dir)).predictions
    )
    without_answers = render_predictions(
        run_baseline(agent, ObservedInput.load(observed_graph_only)).predictions
    )
    assert with_answers == without_answers


def test_the_answer_files_really_are_absent_from_the_isolated_fixture(
    real_observed_dir: Path, observed_graph_only: Path
) -> None:
    """Guard the guard: the isolation fixture must actually be isolating something."""
    present = {path.name for path in real_observed_dir.iterdir()}
    assert present >= FORBIDDEN_INPUT_FILES
    assert {path.name for path in observed_graph_only.iterdir()} == {OBSERVED_GRAPH_NAME}


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_running_an_agent_opens_only_the_observed_graph(
    name: str, real_observed_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record every file the agent's whole run reads, and inspect the list."""
    opened: list[Path] = []
    real_read_text = Path.read_text
    real_read_bytes = Path.read_bytes
    real_open = Path.open

    def record(path: Path) -> None:
        opened.append(path)

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        record(self)
        return real_read_text(self, *args, **kwargs)

    def read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        record(self)
        return real_read_bytes(self, *args, **kwargs)

    def open_(self: Path, *args: Any, **kwargs: Any) -> Any:
        record(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "open", open_)

    run_baseline(get_baseline(name), ObservedInput.load(real_observed_dir))

    names = {path.name for path in opened}
    assert names <= PERMITTED_INPUT_FILES, f"{name} read {sorted(names - PERMITTED_INPUT_FILES)}"
    assert not names & FORBIDDEN_INPUT_FILES


def test_the_permitted_and_forbidden_lists_are_disjoint_and_complete(
    real_observed_dir: Path,
) -> None:
    assert not PERMITTED_INPUT_FILES & FORBIDDEN_INPUT_FILES
    emitted = {
        path.name
        for path in real_observed_dir.iterdir()
        if path.suffix in {".json", ".jsonl"} and path.name != "provenance.json"
    }
    unclassified = emitted - PERMITTED_INPUT_FILES - FORBIDDEN_INPUT_FILES
    assert not unclassified, (
        "an observed-state artefact is neither permitted nor forbidden; classify it "
        f"before a baseline can be trusted: {sorted(unclassified)}"
    )


@pytest.mark.parametrize("source", PACKAGE_SOURCES, ids=lambda path: path.name)
def test_no_module_names_a_forbidden_artefact(source: Path) -> None:
    """Only the module that *defines* the forbidden list may spell those filenames."""
    if source.name == "observed_input.py":
        pytest.skip("observed_input.py declares the forbidden list")
    text = source.read_text(encoding="utf-8")
    for forbidden in sorted(FORBIDDEN_INPUT_FILES):
        assert forbidden not in text, f"{source.name} names {forbidden}"


@pytest.mark.parametrize("source", PACKAGE_SOURCES, ids=lambda path: path.name)
def test_no_module_imports_a_privileged_module(source: Path) -> None:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for forbidden in FORBIDDEN_IMPORTS:
        assert not any(name.startswith(forbidden) for name in imported), (
            f"{source.name} imports {forbidden}"
        )


@pytest.mark.parametrize("source", PACKAGE_SOURCES, ids=lambda path: path.name)
def test_no_module_hard_codes_a_canonical_identifier(source: Path) -> None:
    """A heuristic coupled to a specific entity id is a memorised answer."""
    found = CANONICAL_ID_PATTERN.findall(source.read_text(encoding="utf-8"))
    assert not found, f"{source.name} hard-codes canonical identifier(s): {sorted(set(found))}"


def test_the_rule_catalogue_exposes_no_injector_machinery() -> None:
    """``RuleFact`` must carry published metadata only — never a callable.

    ``population`` and ``mutate`` are how a defect is *chosen* and *applied*. A
    baseline holding either would be reading the injector, not the estate.
    """
    fact = RULE_FACTS["META-TITLE-MISSING"]
    for field in RULE_FACT_FIELDS:
        assert not callable(getattr(fact, field)), f"RuleFact.{field} is callable"
    assert not hasattr(fact, "population")
    assert not hasattr(fact, "mutate")


def test_the_catalogue_covers_every_published_rule() -> None:
    from dataswamp_biosystems.observed import DEFECTS

    assert set(RULE_FACTS) == set(DEFECTS)
