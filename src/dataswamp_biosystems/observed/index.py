"""Read-only lookups over the truth graph, plus the mutable working copy.

:class:`GraphIndex` precomputes the maps defect predicates and mutations need
(assets by kind, governance/contract/training records by asset, files by
dataset, lineage edges by node, org ids, study→programme/access), all derived
once from the immutable truth graph. It also holds two independent JSON dumps of
the graph: an immutable ``truth`` copy (the fidelity/before-value reference) and
a mutable ``working`` copy the engine edits to produce the observed graph.

Shard names are the :class:`~dataswamp_biosystems.truth.graph.TruthGraph` field
names (``datasets``, ``governance_records``, ``lineage`` …).
"""

from __future__ import annotations

import copy
from typing import Any

from dataswamp_biosystems.company.config import CanonicalConfig
from dataswamp_biosystems.truth.graph import TruthGraph

# Shard names that carry mutable records, in a fixed order for stable iteration.
SHARD_NAMES = [
    "subjects",
    "biospecimens",
    "assays",
    "instrument_runs",
    "pipeline_runs",
    "files",
    "datasets",
    "data_products",
    "contracts",
    "quality_checks",
    "governance_records",
    "intended_use_records",
    "training_approvals",
    "lineage",
]

JsonRecord = dict[str, Any]


class GraphIndex:
    """Precomputed truth-graph lookups and the mutable working copy of the shards."""

    def __init__(self, graph: TruthGraph, config: CanonicalConfig) -> None:
        dump = graph.model_dump(mode="json")
        # Two independent deep copies: one immutable reference, one to mutate.
        self.truth: dict[str, list[JsonRecord]] = {
            shard: list(dump.get(shard, [])) for shard in SHARD_NAMES
        }
        self.working: dict[str, list[JsonRecord]] = copy.deepcopy(self.truth)

        # Per-shard id -> record, for both copies.
        self._truth_by_id: dict[str, dict[str, JsonRecord]] = {
            shard: {r["id"]: r for r in records} for shard, records in self.truth.items()
        }
        self._working_by_id: dict[str, dict[str, JsonRecord]] = {
            shard: {r["id"]: r for r in records} for shard, records in self.working.items()
        }

        # Catalogue assets span two shards.
        self.asset_shard: dict[str, str] = {}
        for record in self.truth["datasets"]:
            self.asset_shard[record["id"]] = "datasets"
        for record in self.truth["data_products"]:
            self.asset_shard[record["id"]] = "data_products"

        # Governance/contract/training/quality records keyed by asset.
        self.gov_by_asset = {r["asset_id"]: r["id"] for r in self.truth["governance_records"]}
        self.contract_by_asset = {r["asset_id"]: r["id"] for r in self.truth["contracts"]}
        self.training_by_asset = {r["asset_id"]: r["id"] for r in self.truth["training_approvals"]}
        self.quality_by_asset: dict[str, list[str]] = {}
        for record in self.truth["quality_checks"]:
            self.quality_by_asset.setdefault(record["asset_id"], []).append(record["id"])

        # Files grouped by dataset.
        self.files_by_dataset: dict[str, list[JsonRecord]] = {}
        for record in self.truth["files"]:
            self.files_by_dataset.setdefault(record["dataset_id"], []).append(record)

        # Lineage edges by endpoint.
        self.edges_into: dict[str, list[JsonRecord]] = {}
        self.edges_from: dict[str, list[JsonRecord]] = {}
        for edge in self.truth["lineage"]:
            self.edges_into.setdefault(edge["downstream_id"], []).append(edge)
            self.edges_from.setdefault(edge["upstream_id"], []).append(edge)

        # Organisation ids and study attributes, from the canonical config.
        self.team_ids = {t.id for t in config.teams}
        self.person_ids = {p.id for p in config.people}
        self.org_ids = self.team_ids | self.person_ids
        self.study_access = {s.id: s.access_classification for s in config.studies}
        self.domain_ids = sorted(t.id for t in config.vocabularies.scientific_domains)
        self.run_ids = {r["id"] for r in self.truth["instrument_runs"]} | {
            r["id"] for r in self.truth["pipeline_runs"]
        }
        self.pipeline_run_ids = {r["id"] for r in self.truth["pipeline_runs"]}

    # -- accessors -------------------------------------------------------------

    def asset_ids(self) -> list[str]:
        return sorted(self.asset_shard)

    def dataset_ids(self) -> list[str]:
        return sorted(r["id"] for r in self.truth["datasets"])

    def product_ids(self) -> list[str]:
        return sorted(r["id"] for r in self.truth["data_products"])

    def file_ids(self) -> list[str]:
        return sorted(r["id"] for r in self.truth["files"])

    def truth_record(self, shard: str, entity_id: str) -> JsonRecord | None:
        return self._truth_by_id.get(shard, {}).get(entity_id)

    def working_record(self, shard: str, entity_id: str) -> JsonRecord | None:
        return self._working_by_id.get(shard, {}).get(entity_id)

    def dataset(self, dataset_id: str) -> JsonRecord | None:
        return self.truth_record("datasets", dataset_id)

    def asset(self, asset_id: str) -> JsonRecord | None:
        shard = self.asset_shard.get(asset_id)
        return self.truth_record(shard, asset_id) if shard else None

    # -- mutation primitives (operate on the working copy) ---------------------

    def set_working_field(self, shard: str, entity_id: str, field: str, value: Any) -> None:
        record = self.working_record(shard, entity_id)
        if record is not None:
            record[field] = value

    def delete_working_record(self, shard: str, entity_id: str) -> None:
        records = self.working.get(shard)
        if records is None:
            return
        self.working[shard] = [r for r in records if r["id"] != entity_id]
        self._working_by_id.get(shard, {}).pop(entity_id, None)

    def add_working_record(self, shard: str, record: JsonRecord) -> None:
        self.working.setdefault(shard, []).append(record)
        self._working_by_id.setdefault(shard, {})[record["id"]] = record


__all__ = ["SHARD_NAMES", "JsonRecord", "GraphIndex"]
