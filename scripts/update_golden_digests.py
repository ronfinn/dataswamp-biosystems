#!/usr/bin/env python
"""Regenerate the committed golden digest fixture — deliberately, never by accident.

The golden fixture is the project's benchmark-output contract. Updating it means
asserting that generated output *should* have changed. This script therefore
refuses to run unless the change is explained on the command line, and it is
never invoked by the test suite: ``pytest`` only ever compares.

Usage::

    uv run --frozen python scripts/update_golden_digests.py \\
        --confirm \\
        --reason "pyarrow 25 changed parquet dictionary encoding" \\
        --cause dependency

Run it only in the canonical locked environment (``uv sync --frozen``). The
script records the environment that produced the digests and refuses a
lowest-direct or otherwise non-canonical environment unless ``--allow-any-env``
is passed, which downgrades the fixture to portable digests only.

Before committing the result, the review checklist in ``docs/reproducibility.md``
must be satisfied: why the output changed, which contracts are affected, whether
a schema or generator version needs bumping, and confirmation the change is
intentional.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dataswamp_biosystems.canonical import (  # noqa: E402
    DIGEST_ALGORITHM,
    config_fingerprint,
    digest_tree,
    generate_canonical_from_config_dir,
    scenario_identity,
    split_digests,
)
from dataswamp_biosystems.provenance import (  # noqa: E402
    direct_dependency_versions,
    environment_fingerprint,
)

FIXTURE_PATH = REPO_ROOT / "tests" / "golden" / "canonical-digests.json"
FIXTURE_VERSION = 1
CAUSES = ("dependency", "code", "config", "schema")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Confirms the output change is intentional and reviewed.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Required. One line explaining why the generated output changed.",
    )
    parser.add_argument(
        "--cause",
        choices=CAUSES,
        help="Required. What changed the output.",
    )
    parser.add_argument(
        "--allow-any-env",
        action="store_true",
        help="Write portable digests only, from a non-canonical environment.",
    )
    parser.add_argument(
        "--config-dir", type=Path, default=REPO_ROOT / "config", help="Configuration directory."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.confirm or not args.reason.strip() or args.cause is None:
        print(
            "Refusing to update golden digests.\n"
            "  --confirm, --reason and --cause are all required.\n"
            "  Updating this fixture asserts that benchmark output SHOULD have changed;\n"
            "  see the review checklist in docs/reproducibility.md.",
            file=sys.stderr,
        )
        return 2

    versions = direct_dependency_versions()
    fingerprint = environment_fingerprint(versions)

    previous: dict[str, object] = {}
    if FIXTURE_PATH.exists():
        previous = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    previous_env = previous.get("canonical_environment", {})
    canonical_env = (
        isinstance(previous_env, dict)
        and previous_env.get("environment_fingerprint") == fingerprint
    )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "canonical"
        generate_canonical_from_config_dir(out, args.config_dir)
        portable, scoped = split_digests(digest_tree(out))

    if not portable:  # pragma: no cover - defensive
        print("Generated no portable digests; aborting.", file=sys.stderr)
        return 1

    fixture: dict[str, object] = {
        "fixture_version": FIXTURE_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "scenario": scenario_identity(),
        "config_fingerprint": config_fingerprint(args.config_dir),
        "portable_digests": portable,
        "last_update": {"reason": args.reason.strip(), "cause": args.cause},
    }

    if args.allow_any_env and not canonical_env and previous:
        # Keep the previously recorded canonical digests: this environment is not
        # entitled to redefine them.
        fixture["canonical_environment"] = previous_env
        fixture["environment_scoped_digests"] = previous.get("environment_scoped_digests", {})
        print("Note: non-canonical environment — canonical digests left untouched.")
    else:
        fixture["canonical_environment"] = {
            "direct_dependencies": versions,
            "environment_fingerprint": fingerprint,
        }
        fixture["environment_scoped_digests"] = scoped

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(
        json.dumps(fixture, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {FIXTURE_PATH.relative_to(REPO_ROOT)}")
    print(f"  portable digests:          {len(portable)}")
    scoped_digests = fixture["environment_scoped_digests"]
    assert isinstance(scoped_digests, dict)
    print(f"  environment-scoped digests: {len(scoped_digests)}")
    print(f"  environment fingerprint:   {fingerprint[:16]}…")
    print(f"  reason ({args.cause}): {args.reason.strip()}")
    print("\nReview before committing (docs/reproducibility.md):")
    print("  1. Why did the output change, and is that intended?")
    print("  2. Which benchmark contracts are affected?")
    print("  3. Does a schema or generator version need bumping?")
    print("  4. Were the digests produced in the canonical locked environment?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
