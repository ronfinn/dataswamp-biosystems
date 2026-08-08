"""The compatibility claim must not outlive the evidence for it.

``VERIFIED_DATAHUB_VERSION`` is written into every round-trip report as part of
``live_support``, and quoted in ``docs/datahub.md``. The only thing that makes it
true is the ``live-datahub`` workflow having run against that exact release. So
the constant, the workflow's pin and the documented pin have to move together —
and the failure mode worth guarding is the quiet one: someone bumps the workflow
to chase a green canary and every stored report keeps claiming the old release,
or bumps the constant and nothing is actually tested against the new one.

These tests are offline and need no Docker, no network and no catalogue. They
read the workflow as text on purpose: parsing it into a graph would let a
restructure pass while the pin silently disagreed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.datahub.client import (
    LIVE_SUPPORT,
    VERIFIED_DATAHUB_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-datahub.yml"
DOCS = REPO_ROOT / "docs" / "datahub.md"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    if not WORKFLOW.is_file():
        pytest.skip("not a checkout: the workflow is not shipped in the distribution")
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_workflow_pins_the_version_the_adapter_claims(workflow_text: str) -> None:
    pins = set(
        re.findall(
            r"DATAHUB_VERSION: \$\{\{ inputs\.datahub_version \|\| '(.+?)' \}\}", workflow_text
        )
    )
    assert pins == {VERIFIED_DATAHUB_VERSION}, (
        f"the workflow pins {pins or 'nothing recognisable'} but the adapter claims "
        f"{VERIFIED_DATAHUB_VERSION}; a compatibility point is only worth what was run"
    )


def test_the_dispatch_default_pins_the_same_version(workflow_text: str) -> None:
    """A dispatch with no input must reproduce the scheduled run, not drift from it."""
    defaults = set(re.findall(r"datahub_version:\n(?:.*\n)*?\s+default: (\S+)", workflow_text))
    assert defaults == {VERIFIED_DATAHUB_VERSION}


def test_the_claim_names_the_release_and_stays_honest_about_its_scope() -> None:
    assert LIVE_SUPPORT.startswith("experimental")
    assert VERIFIED_DATAHUB_VERSION in LIVE_SUPPORT
    # A point, not a range. Reports are stored and quoted; "supported" would be
    # read as a promise about releases nobody has run this against.
    assert "supported" not in LIVE_SUPPORT.lower()


def test_the_documented_pin_matches_the_verified_one() -> None:
    if not DOCS.is_file():
        pytest.skip("not a checkout: docs are not shipped in the distribution")
    assert f"`{VERIFIED_DATAHUB_VERSION}`" in DOCS.read_text(encoding="utf-8")


def test_the_live_job_is_never_a_merge_gate(workflow_text: str) -> None:
    """It must not run on push, and must not run on an unlabelled pull request.

    A canary that blocks merges gets clicked past, and one that boots fourteen
    containers on every pull request gets deleted. Both failure modes start with
    an innocuous trigger edit, so the triggers are asserted rather than trusted.
    """
    assert "\n  push:" not in workflow_text
    assert "workflow_dispatch:" in workflow_text
    assert "schedule:" in workflow_text
    assert "contains(github.event.pull_request.labels.*.name, 'live-datahub')" in workflow_text


def test_teardown_and_artifact_upload_survive_a_failure(workflow_text: str) -> None:
    """The two steps whose value exists only on the unhappy path."""
    for step in ("Upload the round-trip report", "Tear down DataHub Quickstart"):
        index = workflow_text.index(step)
        assert "if: always()" in workflow_text[index : index + 400], step


def test_the_job_and_its_waits_are_bounded(workflow_text: str) -> None:
    """An unbounded wait on a heavy stack is how a canary becomes a 6-hour bill."""
    assert re.search(r"timeout-minutes: \d+", workflow_text)
    assert "--wait-timeout" in workflow_text


def test_no_repository_secret_or_catalogue_token_is_used(workflow_text: str) -> None:
    """#28's premise: a throwaway instance, and nobody else's credentials.

    The token env var may be *named* in a comment explaining why it is unset;
    what must never appear is an assignment giving the job one.
    """
    assert "secrets." not in workflow_text
    assert not re.search(r"^\s*DATAHUB_GMS_TOKEN\s*:", workflow_text, re.MULTILINE)
