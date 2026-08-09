"""Regenerate the committed OpenMetadata fixtures, or refresh the vendored schemas.

Two deliberate acts, never performed by ``pytest``, mirroring
``scripts/update_datahub_fixtures.py`` and ``scripts/update_golden_digests.py``.

**Fixtures** pin the adapter's emitted load plan for a tiny, hand-written source
graph, so any change to the mapping shows up as a reviewable diff rather than as
a moved count::

    uv run --frozen python scripts/update_openmetadata_fixtures.py --fixtures \\
        --confirm --reason "carry the contract SLA as a custom property"

**Schemas** re-download the vendored OpenMetadata JSON-schema subset from a named
upstream commit. This changes what the payloads are validated *against*, which is
a compatibility event and needs reading, not rubber-stamping::

    uv run --frozen python scripts/update_openmetadata_fixtures.py --schemas \\
        --release 1.14.0-release --commit <sha> \\
        --confirm --reason "upstream added a required field to createContainer"

Refreshing the schemas establishes **no live compatibility claim**. Reading a
schema is not running against a server; ``VERIFIED_OPENMETADATA_VERSION`` stays
``None`` until a real-server canary earns a point. See
``docs/adr/0006-compatibility-points-not-ranges.md``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from dataswamp_biosystems.adapters.openmetadata import (  # noqa: E402
    ExportMode,
    SourceGraph,
    build_plan,
)
from dataswamp_biosystems.truth import serialize  # noqa: E402
from tests.adapters.openmetadata.conftest import FIXTURE_DIR, MINI_SHARDS  # noqa: E402
from tests.adapters.openmetadata.schema_validation import SCHEMA_DIR  # noqa: E402

UPSTREAM_RAW = (
    "https://raw.githubusercontent.com/open-metadata/OpenMetadata/"
    "{commit}/openmetadata-spec/src/main/resources/json/schema/{path}"
)
PROVENANCE = SCHEMA_DIR / "PROVENANCE.md"

# The plan file each fixture pins, by attribute on the emitted plan.
_PLAN_PARTS: tuple[tuple[str, str], ...] = (
    ("custom_properties", "custom-properties"),
    ("entities", "entities"),
    ("lineage", "lineage"),
    ("test_results", "test-results"),
)


def _write_fixtures(reason: str) -> None:
    sources = {
        "observed": SourceGraph(mode=ExportMode.OBSERVED, shards=MINI_SHARDS),
        "truth": SourceGraph(
            mode=ExportMode.TRUTH,
            shards=MINI_SHARDS,
            expected_finding_rules={"ds-alpha": ["RULE-ONE", "RULE-TWO"]},
        ),
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for mode, source in sources.items():
        plan = build_plan(source)
        for attribute, stem in _PLAN_PARTS:
            path = FIXTURE_DIR / f"mini-{mode}-{stem}.jsonl"
            rendered = "".join(
                f"{serialize.canonical_json(record.as_json())}\n"
                for record in getattr(plan, attribute)
            )
            path.write_text(rendered, encoding="utf-8")
            print(f"wrote {path.relative_to(REPO_ROOT)}")
        coverage = FIXTURE_DIR / f"mini-{mode}-mapping-coverage.json"
        coverage.write_bytes(serialize.manifest_bytes(plan.coverage))
        print(f"wrote {coverage.relative_to(REPO_ROOT)}")
    print(f"reason: {reason}")


def _write_schemas(release: str, commit: str, reason: str) -> None:
    paths = sorted(path.relative_to(SCHEMA_DIR).as_posix() for path in SCHEMA_DIR.rglob("*.json"))
    if not paths:
        raise SystemExit("no vendored schemas to refresh; add the first one by hand")
    for relative in paths:
        url = UPSTREAM_RAW.format(commit=commit, path=relative)
        with urllib.request.urlopen(url) as response:  # noqa: S310 - a pinned raw.githubusercontent URL
            body = response.read()
        # Parsed before writing, so a 404 page or a truncated download fails here
        # rather than becoming an unresolvable schema three test runs later.
        json.loads(body)
        (SCHEMA_DIR / relative).write_bytes(body)
        print(f"refreshed {relative}")

    text = PROVENANCE.read_text(encoding="utf-8")
    text = re.sub(r"(\| Release / tag \| `)[^`]*(` \|)", rf"\g<1>{release}\g<2>", text)
    text = re.sub(r"(\| Commit \| `)[^`]*(` \|)", rf"\g<1>{commit}\g<2>", text)
    PROVENANCE.write_text(text, encoding="utf-8")
    print(f"updated {PROVENANCE.relative_to(REPO_ROOT)}")
    print(
        "\nNow update OPENMETADATA_SCHEMA_TARGET and OPENMETADATA_SCHEMA_COMMIT in\n"
        "src/dataswamp_biosystems/adapters/openmetadata/mapping.py to match, read the\n"
        "schema diff for changed required fields and enum members, and re-run the suite.\n"
        "This establishes no live compatibility claim."
    )
    print(f"reason: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true", help="Regenerate the plan fixtures.")
    parser.add_argument("--schemas", action="store_true", help="Re-download the vendored schemas.")
    parser.add_argument("--release", help="Upstream release/tag, required with --schemas.")
    parser.add_argument("--commit", help="Upstream commit sha, required with --schemas.")
    parser.add_argument("--confirm", action="store_true", required=True)
    parser.add_argument("--reason", required=True, help="Why this refresh is happening.")
    args = parser.parse_args()

    if not (args.fixtures or args.schemas):
        parser.error("choose at least one of --fixtures / --schemas")
    if args.schemas and not (args.release and args.commit):
        parser.error("--schemas requires --release and --commit")

    if args.schemas:
        _write_schemas(args.release, args.commit, args.reason)
    if args.fixtures:
        _write_fixtures(args.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
