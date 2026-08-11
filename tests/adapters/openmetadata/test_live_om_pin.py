"""The OpenMetadata compatibility claim must not outlive the evidence for it.

``VERIFIED_OPENMETADATA_VERSION`` is written into every emitted export manifest
and every round-trip report, and quoted in ``docs/openmetadata.md``. The only
thing that can make it true is the ``live-openmetadata`` workflow having run
against that exact release. So the constant, the workflow's pin and the
documented pin have to move together — and the failure mode worth guarding is
the quiet one: someone bumps the workflow to chase a green canary and every
stored report keeps claiming the old release, or bumps the constant and nothing
is actually tested against the new one.

The stronger guard here, while the constant is still ``None``, is that it cannot
become non-``None`` without a workflow pinning that exact release. Reading a
schema is not running a server; a green fake is not a green server; and neither
is a workflow file that exists.

These tests are offline and need no Docker, no network and no catalogue. They
read the workflow as text on purpose: parsing it into a graph would let a
restructure pass while the pin silently disagreed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from dataswamp_biosystems.adapters.openmetadata.client import LIVE_SUPPORT
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    OM_ADAPTER_VERSION,
    OPENMETADATA_SCHEMA_COMMIT,
    OPENMETADATA_SCHEMA_TARGET,
    VERIFIED_OPENMETADATA_VERSION,
)
from dataswamp_biosystems.adapters.openmetadata.normalize import OM_NORMALIZATION_VERSION
from dataswamp_biosystems.adapters.openmetadata.roundtrip import OM_ROUNDTRIP_SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-openmetadata.yml"
RENDERER = REPO_ROOT / "scripts" / "render_live_openmetadata_compose.py"
DOCS = REPO_ROOT / "docs" / "openmetadata.md"
LABEL = "live-openmetadata"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    if not WORKFLOW.is_file():
        pytest.skip("not a checkout: the workflow is not shipped in the distribution")
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict[str, object]:
    return yaml.safe_load(workflow_text)


def _job(workflow: dict[str, object]) -> dict[str, object]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return dict(jobs["live"])


# ------------------------------------------------------------------- the pin


def test_the_workflow_pins_the_release_and_the_source_commit(workflow: dict[str, object]) -> None:
    """The two halves of the pin: which release ran, and where it was rendered from."""
    env = _job(workflow)["env"]
    assert isinstance(env, dict)
    assert env["OPENMETADATA_VERSION"] == "1.13.3"
    assert env["OPENMETADATA_SOURCE_COMMIT"] == OPENMETADATA_SCHEMA_COMMIT


def test_the_deployment_commit_is_the_commit_the_schemas_came_from() -> None:
    """One commit, two uses: what the payloads are validated against, and what runs.

    Letting these drift apart would mean validating against one version of
    OpenMetadata's model and testing against another, and reporting the result
    as a single compatibility point.
    """
    assert RENDERER.is_file()
    text = RENDERER.read_text(encoding="utf-8")
    assert f'UPSTREAM_COMMIT = "{OPENMETADATA_SCHEMA_COMMIT}"' in text
    assert OPENMETADATA_SCHEMA_TARGET.startswith(f"{'1.13.3'}-")
    assert 'UPSTREAM_RELEASE = "1.13.3"' in text


def test_the_verified_point_is_earned_and_coherent() -> None:
    """The constant is evidence, not intent.

    Earned by run 31528890425 against a pinned OpenMetadata 1.13.3: all four
    claims green, zero discrepancies, zero leak findings. If this test is the one
    failing, the question is not how to satisfy it: it is whether a completely
    green run against that exact release actually exists.
    """
    assert VERIFIED_OPENMETADATA_VERSION == "1.13.3"
    # It must name the release the canary actually pins.
    assert WORKFLOW.is_file(), "a verified point requires a canary workflow"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert f'OPENMETADATA_VERSION: "{VERIFIED_OPENMETADATA_VERSION}"' in text
    assert VERIFIED_OPENMETADATA_VERSION in LIVE_SUPPORT
    # A point, not a range. Reports are stored and quoted; "supported" would be
    # read as a promise about releases nobody has run this against.
    assert "supported" not in LIVE_SUPPORT.lower()
    assert DOCS.is_file()
    assert f"`{VERIFIED_OPENMETADATA_VERSION}`" in DOCS.read_text(encoding="utf-8")


def test_the_verified_point_stays_distinct_from_the_schema_target() -> None:
    """Two different questions that happen to name the same release.

    ``OPENMETADATA_SCHEMA_TARGET`` is a *read artefact* — the revision the
    payloads are validated against offline. The verified point is a *run*. They
    must never be derived from one another, or "the schemas were refreshed"
    silently becomes "a server was tested".
    """
    assert OPENMETADATA_SCHEMA_TARGET == "1.13.3-release"
    assert OPENMETADATA_SCHEMA_COMMIT == "255f6694913b84797064a42859cda3f2a3425dc6"
    assert VERIFIED_OPENMETADATA_VERSION != OPENMETADATA_SCHEMA_TARGET


def test_the_verified_claim_is_scoped_to_observed_mode() -> None:
    """What actually ran was the observed path. The claim may not outgrow it.

    Truth mode is a privileged diagnostic surface resting on the deterministic
    offline contract; no canary has loaded one into a real server. Asserted on
    substance rather than on paragraph shape: the words must appear somewhere in
    the doc and in LIVE_SUPPORT, not in a particular sentence.
    """
    assert "observed" in LIVE_SUPPORT
    assert "truth" in LIVE_SUPPORT.lower()

    doc = DOCS.read_text(encoding="utf-8").lower()
    assert "observed" in doc and "truth mode" in doc
    # Nothing may claim the privileged path was live-tested.
    for forbidden in (
        "truth mode has been verified",
        "truth-mode ingestion has been verified",
        "truth mode is verified against",
        "both modes have been verified",
    ):
        assert forbidden not in doc


def test_no_range_is_claimed_anywhere_the_point_is_stated() -> None:
    """Adjacent patch releases are untested and must never be *claimed*.

    Naming ``1.13.x`` is fine — the doc does it twice, both times to deny it.
    What must not appear is a sentence asserting one, so the check is on claim
    phrasings rather than on the token, which would forbid saying the true thing.
    """
    doc = DOCS.read_text(encoding="utf-8").lower()
    for verb in ("verified against", "compatible with", "tested against", "supports"):
        for target in ("1.13.x", "1.13.*", ">=1.13.3", "1.13.3+", "1.13.3 and later"):
            assert f"{verb} {target}" not in doc, f"{verb} {target!r} claims a range, not a point"
    # And the point is stated as one, explicitly, somewhere in the document.
    assert "never a range" in doc or "not a range" in doc


def test_the_version_constants_stay_independent() -> None:
    """Five counters, five different questions. Borrowing evidence between them
    is how "the schemas were refreshed" quietly becomes "a server was tested"."""
    assert OM_ADAPTER_VERSION == "1.1.0"
    assert OM_NORMALIZATION_VERSION == 2
    assert OM_ROUNDTRIP_SCHEMA_VERSION == 1
    assert OPENMETADATA_SCHEMA_TARGET == "1.13.3-release"
    # Independent of DataHub's, which also happens to be at 2 — arrived at
    # separately, on separate evidence. Independence is structural, not a matter
    # of the numbers differing: this counter moved because a live OpenMetadata
    # returned materialized defaults and escaped descriptions, which says nothing
    # about DataHub and must never be read as saying anything about it.
    source = (
        Path(__file__).resolve().parents[3]
        / "src/dataswamp_biosystems/adapters/openmetadata/normalize.py"
    ).read_text(encoding="utf-8")
    assert "from dataswamp_biosystems.adapters.datahub" not in source


# ------------------------------------------------------------ trigger policy


def test_the_live_job_is_never_a_merge_gate(workflow: dict[str, object]) -> None:
    """It must not run on push, and must not run on an unlabelled pull request.

    A canary that blocks merges gets clicked past, and one that boots a database,
    an Elasticsearch and a Java server on every pull request gets deleted. Both
    failure modes start with an innocuous trigger edit.
    """
    triggers = workflow[True] if True in workflow else workflow["on"]  # `on:` parses as True
    assert isinstance(triggers, dict)
    assert "push" not in triggers
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers
    assert set(triggers["pull_request"]["types"]) == {"labeled", "synchronize", "reopened"}  # type: ignore[index]


def test_the_schedule_is_weekly(workflow: dict[str, object]) -> None:
    triggers = workflow[True] if True in workflow else workflow["on"]
    crons = [entry["cron"] for entry in triggers["schedule"]]  # type: ignore[index]
    assert len(crons) == 1
    # Five fields, with a specific day-of-week — not a daily or hourly alarm.
    minute, hour, day_of_month, month, day_of_week = crons[0].split()
    assert day_of_month == "*" and month == "*"
    assert day_of_week.isdigit()
    assert minute.isdigit() and hour.isdigit()


def test_the_job_is_guarded_by_repository_and_label(workflow: dict[str, object]) -> None:
    condition = str(_job(workflow)["if"])
    assert "github.repository == 'ronfinn/dataswamp-biosystems'" in condition
    assert f"contains(github.event.pull_request.labels.*.name, '{LABEL}')" in condition


def test_the_job_is_bounded_and_serialised(workflow: dict[str, object]) -> None:
    """An unbounded wait on a heavy stack is how a canary becomes a six-hour bill."""
    job = _job(workflow)
    timeout = job["timeout-minutes"]
    assert isinstance(timeout, int) and 0 < timeout <= 30
    concurrency = workflow["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency["group"] == "live-openmetadata"
    assert concurrency.get("cancel-in-progress") is False


def test_every_wait_in_the_job_is_bounded(workflow_text: str) -> None:
    """Each readiness loop must have a finite trip count, not `while true`."""
    assert "while true" not in workflow_text
    assert re.search(r"for attempt in \$\(seq 1 \d+\)", workflow_text)


# ------------------------------------------------- teardown, secrets, evidence


def test_teardown_and_artifact_upload_survive_a_failure(workflow_text: str) -> None:
    """The two steps whose value exists only on the unhappy path."""
    for step in (
        "Upload the round-trip report",
        "Tear down the OpenMetadata stack",
        "Collect diagnostics",
    ):
        index = workflow_text.index(step)
        assert "if: always()" in workflow_text[index : index + 400], step


def test_teardown_removes_volumes(workflow_text: str) -> None:
    """`down` alone leaves the database behind, and one run's state would reach
    the next — precisely the contamination this job exists to detect."""
    assert "docker compose down -v --remove-orphans" in workflow_text


def test_no_repository_secret_or_catalogue_token_is_used(workflow_text: str) -> None:
    """A throwaway instance, and nobody's credentials.

    The token env var may be *named* in a comment explaining why it is unset;
    what must never appear is an assignment giving the job one. A JWT is never a
    CLI argument and never reaches a log, report or artifact.
    """
    assert "secrets." not in workflow_text
    assert not re.search(r"^\s*OPENMETADATA_JWT_TOKEN\s*:", workflow_text, re.MULTILINE)
    assert "--token" not in workflow_text


def test_the_dry_run_precedes_any_server_contact(workflow_text: str) -> None:
    """Export validity is established before a network failure can be blamed for it."""
    dry_run = workflow_text.index("--dry-run")
    assert dry_run < workflow_text.index("docker compose up -d")
    # And the real ingestion, which is the only `ingest-openmetadata` that
    # transmits anything, comes after both.
    assert dry_run < workflow_text.index("--yes")


def test_the_canary_runs_the_real_product_path(workflow_text: str) -> None:
    """Not a bespoke script: the same commands a user would run."""
    for command in (
        "dataswamp demo",
        "dataswamp export-openmetadata",
        "dataswamp ingest-openmetadata",
        "dataswamp verify-om-ingestion",
        "pytest -q -m live_openmetadata",
    ):
        assert command in workflow_text, command


def test_the_export_the_canary_ingests_is_one_it_actually_produced(
    workflow_text: str,
) -> None:
    """`demo` emits the bundle and the *DataHub* export, not the OpenMetadata one.

    The first live run failed here: the job ingested a directory nothing had
    written. The export step and the paths that consume it have to agree, so
    both halves are asserted rather than assumed.
    """
    assert '--output-dir "$DEMO_DIR/export/openmetadata"' in workflow_text
    assert '--bundle "$DEMO_DIR/bundle"' in workflow_text
    assert workflow_text.index("dataswamp export-openmetadata") < workflow_text.index("--dry-run")


def test_the_run_directory_exists_before_the_always_steps_need_it(
    workflow_text: str, workflow: dict[str, object]
) -> None:
    """Diagnostics and teardown use RUN_DIR as their working directory.

    A job failing before RUN_DIR existed lost both — which is precisely when
    they are worth most, and is how the first live run reported nothing about
    itself beyond the failing step.
    """
    assert 'mkdir -p "$RUNNER_TEMP/live-om-run"' in workflow_text
    steps = _job(workflow)["steps"]
    assert isinstance(steps, list)
    names = [str(step.get("name", "")) for step in steps]
    creation = names.index("Choose working directories")
    for step_name in ("Collect diagnostics", "Tear down the OpenMetadata stack"):
        assert creation < names.index(step_name), step_name


def test_the_live_marker_is_deselected_by_default() -> None:
    """An ordinary `pytest` must never try to reach a catalogue."""
    import tomllib

    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    options = config["tool"]["pytest"]["ini_options"]
    assert options["addopts"] == ["-m", "not live and not live_openmetadata"]
    assert any(marker.startswith("live_openmetadata:") for marker in options["markers"])


def test_the_live_suite_carries_the_marker_and_names_no_default_server() -> None:
    """It must skip when unconfigured, never fall back to a local guess.

    A live suite with a default host is a live suite that will one day run
    against a developer's own catalogue and report a compatibility point for it.
    """
    suite = (Path(__file__).parent / "test_live_openmetadata.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.live_openmetadata" in suite
    assert 'pytest.skip(f"no live catalogue: {HOST_PORT_ENV} is unset")' in suite
    assert "localhost" not in suite
    assert "8585" not in suite
