"""Regenerate the committed DataHub mapping fixtures.

The fixtures pin the adapter's emitted payload for a tiny, hand-written source
graph, so any change to the mapping shows up as a reviewable diff. They are
never rewritten by ``pytest`` — mirroring ``scripts/update_golden_digests.py``,
regeneration is a deliberate act that must be justified in the pull request that
carries it.

    uv run --frozen python scripts/update_datahub_fixtures.py --confirm \\
        --reason "map retention class onto a glossary term"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from dataswamp_biosystems.adapters.datahub import build_mcps  # noqa: E402
from dataswamp_biosystems.truth import serialize  # noqa: E402
from tests.adapters.conftest import (  # noqa: E402
    MINI_OBSERVED_FIXTURE,
    MINI_SHARDS,
    MINI_TRUTH_FIXTURE,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", required=True)
    parser.add_argument("--reason", required=True, help="Why the mapping changed.")
    args = parser.parse_args()

    from dataswamp_biosystems.adapters.datahub import ExportMode, SourceGraph

    targets = {
        MINI_OBSERVED_FIXTURE: SourceGraph(mode=ExportMode.OBSERVED, shards=MINI_SHARDS),
        MINI_TRUTH_FIXTURE: SourceGraph(
            mode=ExportMode.TRUTH,
            shards=MINI_SHARDS,
            expected_finding_rules={"ds-alpha": ["RULE-ONE", "RULE-TWO"]},
        ),
    }
    for path, source in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = "".join(f"{serialize.canonical_json(mcp)}\n" for mcp in build_mcps(source))
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    print(f"reason: {args.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
