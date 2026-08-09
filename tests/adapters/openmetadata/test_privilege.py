"""The observed/truth privilege boundary, enforced structurally rather than by care.

An observed export is handed to the agent under test. If it leaked which entities
carry defects, the benchmark would be measuring nothing. The defence is not "the
mapping is careful not to emit findings" — it is that the observed source graph
**reads one file** and physically cannot reach the rest.

The strongest test in this module makes every privileged artefact in a bundle
unreadable and asserts the observed export still succeeds. That is a claim about
file handles, not about intent, and it is the one a future refactor cannot talk
its way around.
"""

from __future__ import annotations

import ast
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.openmetadata import (
    ENTITIES_NAME,
    TRUTH_ONLY_PROPERTY_PREFIX,
    ExportMode,
    build_plan,
    build_source,
    export_openmetadata,
)
from dataswamp_biosystems.adapters.openmetadata import export as om_export
from dataswamp_biosystems.bundle import BundleReader

# Every answer-key artefact an observed export must never open. If any of these
# were read, the export could tell an agent where the defects are.
PRIVILEGED_ARTEFACTS = (
    "expected-findings.jsonl",
    "expected-remediations.jsonl",
    "injected-defects.jsonl",
    "mutation-log.jsonl",
    "controls.jsonl",
    "rule-scope.jsonl",
    "scenarios.jsonl",
    "scenario-transformations.jsonl",
)


@contextmanager
def _unreadable(paths: list[Path]) -> Iterator[None]:
    """Strip read permission for the duration of the block, then restore it."""
    original = {path: path.stat().st_mode for path in paths}
    try:
        for path in paths:
            path.chmod(0o000)
        yield
    finally:
        for path, mode in original.items():
            path.chmod(stat.S_IMODE(mode))


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_an_observed_export_succeeds_with_every_privileged_artefact_unreadable(
    mutable_bundle: Path, tmp_path: Path
) -> None:
    """The structural claim, tested at the filesystem rather than in prose."""
    blocked = [
        path
        for name in PRIVILEGED_ARTEFACTS
        if (path := mutable_bundle / "observed" / name).is_file()
    ]
    assert blocked, "the bundle should contain answer-key artefacts to block"

    with _unreadable(blocked):
        # Verification checksums every file in the bundle, so it is skipped here:
        # the question is what the *mapping* opens, not what the verifier does.
        manifest = export_openmetadata(
            mutable_bundle, tmp_path / "export", mode=ExportMode.OBSERVED, verify=False
        )
    assert manifest["counts"]["entities"] > 0
    assert manifest["privileged"] is False


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_the_blocked_artefacts_really_are_unreadable(mutable_bundle: Path) -> None:
    """Proves the previous test's premise rather than assuming it."""
    target = mutable_bundle / "observed" / "expected-findings.jsonl"
    with _unreadable([target]), pytest.raises(PermissionError):
        target.read_bytes()


def test_the_observed_source_reads_the_observed_graph_and_nothing_else(
    full_bundle_dir: Path,
) -> None:
    """A read-tracking proxy: the containment boundary, observed directly."""
    opened: list[str] = []

    class _Tracking(BundleReader):
        def _iter_jsonl(self, path: Path):  # type: ignore[override]
            opened.append(path.name)
            return super()._iter_jsonl(path)

        def _read_json(self, path: Path):  # type: ignore[override]
            opened.append(path.name)
            return super()._read_json(path)

    with _Tracking.open(full_bundle_dir) as reader:
        build_plan(build_source(reader, ExportMode.OBSERVED))

    assert opened == ["observed-graph.json"]


def test_the_observed_source_function_names_no_privileged_reader_method() -> None:
    """The boundary as code, so a future edit has to defeat a test to cross it."""
    source = Path(om_export.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_observed_source"
    )
    # The docstring explains what is *not* read, so it names those very things.
    # It is the executable statements that must be clean.
    body = [node for node in function.body if not isinstance(node, ast.Expr)]
    rendered = "\n".join(ast.unparse(node) for node in body)
    for forbidden in (
        "iter_findings",
        "iter_remediations",
        "iter_controls",
        "rule_scope",
        "iter_truth_records",
        "iter_assets",
        "scenario",
        "mutation",
    ):
        assert forbidden not in rendered, forbidden


def test_an_adversarial_bundle_exports_exactly_what_an_ordinary_one_does() -> None:
    """The near-miss *values* travel; the records saying they were planted do not."""
    from dataswamp_biosystems.adapters.openmetadata import SourceGraph

    shards = {
        "datasets": [{"id": "ds-x", "asset_type": "dataset", "study_id": "s", "programme_id": "p"}]
    }
    plan = build_plan(SourceGraph(mode=ExportMode.OBSERVED, shards=shards))
    serialized = json.dumps([record.as_json() for record in plan.records])
    for term in (
        "scenario",
        "nearMiss",
        "near_miss",
        "ruleScope",
        "rule_scope",
        "controlRecord",
        "expectedFinding",
        "mutation",
    ):
        assert term not in serialized


def test_the_real_observed_export_carries_no_rule_id(om_observed_export_dir: Path) -> None:
    """Defect rule ids are the most direct possible leak."""
    text = (om_observed_export_dir / ENTITIES_NAME).read_text(encoding="utf-8")
    assert TRUTH_ONLY_PROPERTY_PREFIX not in text
    assert "expectedFindingRules" not in text


def test_the_truth_export_is_privileged_three_independent_ways(
    om_truth_export_dir: Path,
) -> None:
    """One marker could be stripped by accident; three is a deliberate act."""
    manifest = json.loads(
        (om_truth_export_dir / "export-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["privileged"] is True

    tagged = propertied = 0
    for line in (om_truth_export_dir / ENTITIES_NAME).read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        create = record.get("create") or {}
        if any(tag["tagFQN"].endswith("privileged-truth-export") for tag in create.get("tags", [])):
            tagged += 1
        if (create.get("extension") or {}).get("dataswampTruthExport") == "true":
            propertied += 1
    assert tagged > 0
    assert propertied > 0
    assert tagged == propertied
