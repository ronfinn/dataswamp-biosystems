"""Tests for the defect-definition registry and its validation."""

from __future__ import annotations

import dataclasses

from dataswamp_biosystems.observed.defects import DEFECTS, registry_rows, validate_registry


def test_shipped_registry_is_valid() -> None:
    assert validate_registry(DEFECTS) == []


def test_registry_rows_cover_every_rule() -> None:
    rows = registry_rows()
    assert len(rows) == len(DEFECTS)
    assert {row["rule_id"] for row in rows} == set(DEFECTS)


def test_unknown_incompatibility_is_rejected() -> None:
    broken = dataclasses.replace(DEFECTS["FILE-MISSING"], incompatibilities=["NO-SUCH-RULE"])
    problems = validate_registry({**DEFECTS, "FILE-MISSING": broken})
    assert any("unknown rule" in p for p in problems)


def test_mismatched_key_is_rejected() -> None:
    definition = DEFECTS["FILE-MISSING"]
    problems = validate_registry({"WRONG-KEY": definition})
    assert any("does not match rule_id" in p for p in problems)


def test_self_incompatibility_is_rejected() -> None:
    broken = dataclasses.replace(DEFECTS["FILE-MISSING"], incompatibilities=["FILE-MISSING"])
    problems = validate_registry({**DEFECTS, "FILE-MISSING": broken})
    assert any("incompatible with itself" in p for p in problems)


def test_empty_title_is_rejected() -> None:
    broken = dataclasses.replace(DEFECTS["FILE-MISSING"], title="")
    problems = validate_registry({**DEFECTS, "FILE-MISSING": broken})
    assert any("empty title" in p for p in problems)
