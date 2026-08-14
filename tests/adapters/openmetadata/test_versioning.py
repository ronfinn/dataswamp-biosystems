"""The versioning discipline ADR 0006 imposes, applied before there is a temptation.

DataHub earned a compatibility point the hard way — a canary that went red twice
for opposite reasons. OpenMetadata has earned nothing yet, and the whole value of
that ADR is that the absence is stated rather than papered over with a range.

These tests are cheap and slightly pedantic on purpose. They exist so that
"someone will remember not to claim compatibility" becomes "someone has to delete
a test to claim compatibility".
"""

from __future__ import annotations

import re
from pathlib import Path

from dataswamp_biosystems.adapters.openmetadata import (
    OM_ADAPTER_VERSION,
    OPENMETADATA_MODEL_TARGET_RANGE,
    OPENMETADATA_SCHEMA_COMMIT,
    OPENMETADATA_SCHEMA_TARGET,
    VERIFIED_OPENMETADATA_VERSION,
)
from dataswamp_biosystems.adapters.openmetadata import mapping as om_mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "openmetadata.md"


def test_the_verified_live_version_names_the_release_a_canary_ran() -> None:
    """The single most important assertion in this file.

    It was ``None`` until a real 1.13.3 canary went completely green. It names one
    release because one release was run — never a range, and never a release whose
    schemas were merely read.
    """
    assert VERIFIED_OPENMETADATA_VERSION == "1.13.3"


def test_no_normalization_version_exists_yet() -> None:
    """Normalization is a round-trip concern; versioning one now would be fiction."""
    assert not hasattr(om_mapping, "OM_NORMALIZATION_VERSION")
    assert not hasattr(om_mapping, "NORMALIZATION_VERSION")


def test_the_schema_target_is_a_named_revision_not_a_range() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+-release", OPENMETADATA_SCHEMA_TARGET)
    assert re.fullmatch(r"[0-9a-f]{40}", OPENMETADATA_SCHEMA_COMMIT)


def test_the_declared_range_is_labelled_a_target_in_code() -> None:
    """A range with no tested point inside it must not read as evidence."""
    source = Path(om_mapping.__file__).read_text(encoding="utf-8")
    declaration = source.split("OPENMETADATA_MODEL_TARGET_RANGE")[0]
    assert "declared target" in declaration
    assert "not tested evidence" in declaration
    assert OPENMETADATA_MODEL_TARGET_RANGE == ">=1.9,<2"


def test_the_schema_target_lies_inside_the_declared_range() -> None:
    """The two must never become incoherent, as ADR 0006 requires of DataHub."""
    lower = OPENMETADATA_MODEL_TARGET_RANGE.split(",")[0].removeprefix(">=")
    upper = OPENMETADATA_MODEL_TARGET_RANGE.split(",")[1].removeprefix("<")

    def parts(version: str) -> tuple[int, ...]:
        return tuple(int(piece) for piece in version.split("-")[0].split("."))

    target = parts(OPENMETADATA_SCHEMA_TARGET)
    assert parts(lower) <= target[: len(parts(lower))]
    assert target[: len(parts(upper))] < parts(upper) or target[0] < parts(upper)[0]


def test_the_adapter_version_is_semantic() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", OM_ADAPTER_VERSION)


def test_the_documentation_states_the_remaining_absences_plainly() -> None:
    """A reader should not have to infer what has *not* been tested.

    One release has been run against in one mode. The doc has to keep saying what
    that leaves unproven, or the point quietly reads as broader than it is.
    """
    text = DOC.read_text(encoding="utf-8")
    assert "VERIFIED_OPENMETADATA_VERSION" in text
    assert "What this milestone does *not* prove" in text
    for claim in (
        "truth mode has never been loaded",
        "schema validity is not load success",
        "no release other than",
    ):
        assert claim.lower() in text.lower(), claim


def test_the_documentation_pins_the_same_schema_revision() -> None:
    """Constant and prose move together, or a reader is misled by one of them."""
    text = DOC.read_text(encoding="utf-8")
    assert OPENMETADATA_SCHEMA_TARGET in text
    assert OPENMETADATA_SCHEMA_COMMIT in text


def test_no_datahub_constant_was_disturbed() -> None:
    """This milestone touches the DataHub adapter's versioning not at all.

    ``ADAPTER_VERSION`` since moved `1.0.0` → `1.1.0` under its own issue, when
    the DataHub export gained ``mapping-coverage.json`` — an additive change to
    that adapter's own export contract, not a change made here. The constants
    this milestone actually cared about are the three below, and they are pinned.
    """
    from dataswamp_biosystems.adapters.datahub import (
        ADAPTER_VERSION,
        DATAHUB_MODEL_VERSION,
        NORMALIZATION_VERSION,
        VERIFIED_DATAHUB_VERSION,
    )

    assert ADAPTER_VERSION == "1.1.0"
    assert DATAHUB_MODEL_VERSION == ">=0.13,<2"
    assert VERIFIED_DATAHUB_VERSION == "v1.7.0"
    assert NORMALIZATION_VERSION >= 1
