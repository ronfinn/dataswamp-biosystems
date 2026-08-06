"""The single, deliberately narrow window a baseline agent has onto the benchmark.

A baseline is scored as a genuine participant, so it must see exactly what a
submitting agent sees and nothing more. That guarantee is made *structural*
rather than promised in prose: this module is the only place in
:mod:`dataswamp_biosystems.baselines` that touches the filesystem, and it opens
exactly one file — ``observed-graph.json``.

Everything else an emitted observed state contains is ground truth or a
derivative of it, and reading any of it would make a published baseline score
meaningless:

``expected-findings.jsonl``, ``expected-remediations.jsonl``
    The answers.
``controls.jsonl``, ``rule-scope.jsonl``
    Which entities were held clean, and which population each rule drew from —
    enough to reconstruct the answers by elimination.
``injected-defects.jsonl``, ``mutation-log.jsonl``
    The injection record, including the truth ``before`` values.
``profile-summary.json``
    Per-rule injection counts.
``scenarios.jsonl``, ``scenario-transformations.jsonl``
    The adversarial answer key: which candidate is the true positive, which
    lookalike is a deliberate near miss, what the expected detection and
    remediation decisions are, and the privileged before values. An agent is
    meant to *see* a near miss and have to decide about it; reading the record
    that says it was planted would defeat the entire adversarial tier.

Those names are enumerated in :data:`FORBIDDEN_INPUT_FILES` so a test can assert
the reader never names one, and so a reviewer can see the boundary in one place.
The observed graph's own ``meta`` block is permitted: it is written into the
observed graph the agent under test is handed, and carries only scenario
identity (profile, seeds, generator versions, epoch anchor).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataswamp_biosystems.baselines.errors import ObservedInputError
from dataswamp_biosystems.observed.writer import (
    CONTROLS_NAME,
    EXPECTED_FINDINGS_NAME,
    EXPECTED_REMEDIATIONS_NAME,
    INJECTED_DEFECTS_NAME,
    MUTATION_LOG_NAME,
    OBSERVED_GRAPH_NAME,
    PROFILE_SUMMARY_NAME,
    RULE_SCOPE_NAME,
    SCENARIO_TRANSFORMATIONS_NAME,
    SCENARIOS_NAME,
)

# The only file any baseline may read.
PERMITTED_INPUT_FILES: frozenset[str] = frozenset({OBSERVED_GRAPH_NAME})

# Everything a baseline must not read, named explicitly so the prohibition is
# testable rather than aspirational.
FORBIDDEN_INPUT_FILES: frozenset[str] = frozenset(
    {
        CONTROLS_NAME,
        EXPECTED_FINDINGS_NAME,
        EXPECTED_REMEDIATIONS_NAME,
        INJECTED_DEFECTS_NAME,
        MUTATION_LOG_NAME,
        PROFILE_SUMMARY_NAME,
        RULE_SCOPE_NAME,
        SCENARIOS_NAME,
        SCENARIO_TRANSFORMATIONS_NAME,
    }
)

# The forbidden files an *ordinary* benchmark does not contain at all — they are
# emitted only by an adversarial run. Named separately so a test can still assert
# "every forbidden file is really present" against the benchmark that has them,
# instead of weakening that assertion to "present or absent, who knows".
ADVERSARIAL_ONLY_INPUT_FILES: frozenset[str] = frozenset(
    {SCENARIOS_NAME, SCENARIO_TRANSFORMATIONS_NAME}
)

# Forbidden files every emitted observed state carries, whatever its tier.
ALWAYS_PRESENT_FORBIDDEN_FILES: frozenset[str] = (
    FORBIDDEN_INPUT_FILES - ADVERSARIAL_ONLY_INPUT_FILES
)

# Shards holding a catalogue asset, and the entity kind each one denotes. These
# are the entities a baseline may make a claim about; the remaining shards
# (lineage, runs, specimens, …) are supporting evidence it reads but never
# files a finding against, because no rule's population is drawn from them.
ASSET_SHARDS: tuple[tuple[str, str], ...] = (
    ("datasets", "dataset"),
    ("data_products", "data_product"),
)
FILE_SHARD = "files"
FILE_KIND = "file"


@dataclass(frozen=True)
class ObservedEntity:
    """One record from the observed graph, with the shard and kind it came from."""

    entity_id: str
    kind: str
    shard: str
    record: dict[str, Any]

    def get(self, field: str, default: Any = None) -> Any:
        return self.record.get(field, default)


def _records(graph: dict[str, Any], shard: str) -> list[dict[str, Any]]:
    rows = graph.get(shard, [])
    if not isinstance(rows, list):
        raise ObservedInputError(f"observed graph shard {shard!r} is not a list")
    out: list[dict[str, Any]] = []
    for offset, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ObservedInputError(
                f"observed graph shard {shard!r} record {offset + 1} is not an object"
            )
        out.append(row)
    return out


@dataclass(frozen=True)
class ObservedInput:
    """The observed graph, indexed for the read patterns baselines actually use.

    Construction is the only I/O; every accessor below works from the loaded
    document. Ordering is stable everywhere — records are returned in the graph's
    own canonical order, and every derived index is built by iterating that
    order — so a baseline's output never depends on dictionary iteration or on
    how the file happened to be laid out.
    """

    graph: dict[str, Any]
    source_dir: str

    # -- loading --------------------------------------------------------------

    @classmethod
    def load(cls, observed_dir: Path | str) -> ObservedInput:
        """Read ``observed-graph.json`` from ``observed_dir``. Reads nothing else."""
        observed_dir = Path(observed_dir)
        if not observed_dir.is_dir():
            raise ObservedInputError(f"no observed state directory at {observed_dir}")
        path = observed_dir / OBSERVED_GRAPH_NAME
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ObservedInputError(f"could not read {path}: {exc}") from exc
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ObservedInputError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise ObservedInputError(
                f"{path} must contain a JSON object, got {type(document).__name__}"
            )
        return cls(graph=document, source_dir=observed_dir.as_posix())

    # -- scenario identity ----------------------------------------------------

    @property
    def meta(self) -> dict[str, Any]:
        meta = self.graph.get("meta", {})
        if not isinstance(meta, dict):
            raise ObservedInputError("observed graph 'meta' is not an object")
        return meta

    @property
    def epoch_anchor(self) -> str:
        """The scenario's 'today', as an ISO date. Empty when the graph omits it."""
        return str(self.meta.get("epoch_anchor", ""))

    @property
    def scenario(self) -> dict[str, str]:
        """Profile, seeds and generator versions — recorded alongside any score."""
        keys = (
            "profile",
            "defect_seed",
            "truth_seed",
            "generator_version",
            "truth_generator_version",
            "schema_version",
        )
        return {key: str(self.meta[key]) for key in keys if key in self.meta}

    # -- entities -------------------------------------------------------------

    def shard(self, name: str) -> list[dict[str, Any]]:
        return _records(self.graph, name)

    @property
    def assets(self) -> list[ObservedEntity]:
        """Datasets then data products, each in the graph's own order."""
        return [
            ObservedEntity(str(row.get("id", "")), kind, shard, row)
            for shard, kind in ASSET_SHARDS
            for row in _records(self.graph, shard)
        ]

    @property
    def files(self) -> list[ObservedEntity]:
        return [
            ObservedEntity(str(row.get("id", "")), FILE_KIND, FILE_SHARD, row)
            for row in _records(self.graph, FILE_SHARD)
        ]

    @property
    def entities(self) -> list[ObservedEntity]:
        """Every entity a baseline may file a claim against."""
        return [*self.assets, *self.files]

    # -- supporting indexes ---------------------------------------------------

    def _by_asset(self, shard: str) -> dict[str, list[dict[str, Any]]]:
        index: dict[str, list[dict[str, Any]]] = {}
        for row in _records(self.graph, shard):
            index.setdefault(str(row.get("asset_id", "")), []).append(row)
        return index

    @property
    def governance_by_asset(self) -> dict[str, list[dict[str, Any]]]:
        return self._by_asset("governance_records")

    @property
    def quality_checks_by_asset(self) -> dict[str, list[dict[str, Any]]]:
        return self._by_asset("quality_checks")

    @property
    def training_approvals_by_asset(self) -> dict[str, list[dict[str, Any]]]:
        return self._by_asset("training_approvals")

    @property
    def contract_ids(self) -> frozenset[str]:
        return frozenset(str(row.get("id", "")) for row in _records(self.graph, "contracts"))

    @property
    def run_ids(self) -> frozenset[str]:
        """Every id that can legitimately appear as an asset's provenance run."""
        ids: set[str] = set()
        for shard in ("instrument_runs", "pipeline_runs"):
            ids.update(str(row.get("id", "")) for row in _records(self.graph, shard))
        return frozenset(ids)

    @property
    def lineage_downstream_ids(self) -> frozenset[str]:
        """Ids that appear on the downstream end of at least one lineage edge."""
        return frozenset(
            str(row.get("downstream_id", "")) for row in _records(self.graph, "lineage")
        )


__all__ = [
    "ADVERSARIAL_ONLY_INPUT_FILES",
    "ALWAYS_PRESENT_FORBIDDEN_FILES",
    "ASSET_SHARDS",
    "FILE_KIND",
    "FILE_SHARD",
    "FORBIDDEN_INPUT_FILES",
    "PERMITTED_INPUT_FILES",
    "ObservedEntity",
    "ObservedInput",
]
