"""Per-rule tests: every defect applies cleanly and the marquee examples behave.

Each rule's population is exercised against the real truth graph, and the
mandated example defects have targeted assertions on their observed effect.
"""

from __future__ import annotations

import pytest

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.observed.defects import DEFECTS, FieldChange, MutationContext
from dataswamp_biosystems.observed.entities import ChangeOp
from dataswamp_biosystems.observed.index import GraphIndex
from dataswamp_biosystems.truth.graph import TruthGraph


@pytest.fixture(scope="module")
def index(graph: TruthGraph, config: CanonicalConfig) -> GraphIndex:
    return GraphIndex(graph, config)


def _first_changes(rule_id: str, index: GraphIndex) -> tuple[str, list[FieldChange]]:
    definition = DEFECTS[rule_id]
    for entity_id in definition.population(index):
        changes = definition.mutate(MutationContext(index=index, entity_id=entity_id))
        if changes:
            return entity_id, changes
    raise AssertionError(f"rule {rule_id} produced no changes on any eligible entity")


@pytest.mark.parametrize("rule_id", sorted(DEFECTS))
def test_every_rule_has_a_population_and_applies(rule_id: str, index: GraphIndex) -> None:
    assert DEFECTS[rule_id].population(index), f"{rule_id} has an empty eligible population"
    entity_id, changes = _first_changes(rule_id, index)
    assert entity_id
    assert changes


@pytest.mark.parametrize("rule_id", sorted(DEFECTS))
def test_every_set_change_before_matches_truth(rule_id: str, index: GraphIndex) -> None:
    _entity, changes = _first_changes(rule_id, index)
    for change in changes:
        if change.op in (ChangeOp.SET, ChangeOp.SET_LIST):
            record = index.truth_record(change.shard, change.entity_id)
            assert record is not None
            assert change.before == record.get(change.field)


def test_owner_missing_clears_owner_everywhere(index: GraphIndex) -> None:
    _entity, changes = _first_changes("OWN-OWNER-MISSING", index)
    owner_changes = [c for c in changes if c.field == "owner_ref"]
    assert owner_changes
    assert all(c.after == "" for c in owner_changes)
    assert any(c.shard == "governance_records" for c in owner_changes)
    assert any(c.shard in {"datasets", "data_products"} for c in owner_changes)


def test_owner_wrong_team_uses_a_real_other_team(index: GraphIndex) -> None:
    entity, changes = _first_changes("OWN-OWNER-WRONG-TEAM", index)
    truth = index.asset(entity)
    assert truth is not None
    owner_change = next(
        c for c in changes if c.field == "owner_ref" and c.shard != "governance_records"
    )
    assert owner_change.after in index.team_ids
    assert owner_change.after != truth["owner_ref"]


def test_genome_build_dropped(index: GraphIndex) -> None:
    _entity, changes = _first_changes("MOD-GENOME-BUILD-MISSING", index)
    change = changes[0]
    assert "reference_build" in change.before
    assert "reference_build" not in change.after


def test_mixed_gene_ids_added(index: GraphIndex) -> None:
    _entity, changes = _first_changes("MOD-MIXED-GENE-IDS", index)
    assert changes[0].after["gene_id_system"] == "mixed:ensembl+symbol"


def test_spatial_coords_out_of_bounds(index: GraphIndex) -> None:
    _entity, changes = _first_changes("MOD-SPATIAL-COORDS-OOB", index)
    assert changes[0].after["max_coord_um"] == 999999


def test_restricted_marked_internal(index: GraphIndex) -> None:
    entity, changes = _first_changes("GOV-RESTRICTED-AS-INTERNAL", index)
    assert changes[0].after == "internal"
    assert changes[0].before in {"restricted", "highly-restricted"}


def test_cross_study_edge_links_a_different_study(index: GraphIndex) -> None:
    entity, changes = _first_changes("LIN-CROSS-STUDY-EDGE", index)
    change = changes[0]
    assert change.op is ChangeOp.ADD_RECORD
    downstream = index.dataset(entity)
    upstream = index.dataset(change.after["upstream_id"])
    assert downstream is not None and upstream is not None
    assert downstream["study_id"] != upstream["study_id"]


def test_duplicate_final_versions(index: GraphIndex) -> None:
    _entity, changes = _first_changes("NAM-DUP-FINAL-VERSION", index)
    assert len(changes) == 2
    assert changes[0].after == changes[1].after == "final"


def test_vcf_index_missing_drops_a_file(index: GraphIndex) -> None:
    _entity, changes = _first_changes("LIN-VCF-INDEX-MISSING", index)
    ops = {c.op for c in changes}
    assert ChangeOp.DELETE_RECORD in ops
    assert ChangeOp.SET_LIST in ops


def test_training_approval_absent_deletes_record(index: GraphIndex) -> None:
    _entity, changes = _first_changes("AIR-TRAINING-APPROVAL-ABSENT", index)
    assert changes[0].op is ChangeOp.DELETE_RECORD
    assert changes[0].shard == "training_approvals"


def test_certified_contradicted_fails_a_check(index: GraphIndex) -> None:
    _entity, changes = _first_changes("QC-CERTIFIED-CONTRADICTED", index)
    statuses = {c.field: c.after for c in changes}
    assert statuses["status"] == "fail"


def test_checksum_mismatch_changes_digest(index: GraphIndex) -> None:
    _entity, changes = _first_changes("FILE-CHECKSUM-MISMATCH", index)
    assert changes[0].after != changes[0].before
    assert changes[0].field == "checksum"


def test_file_missing_tombstones(index: GraphIndex) -> None:
    _entity, changes = _first_changes("FILE-MISSING", index)
    assert changes[0].field == "present"
    assert changes[0].after is False


def _dataset_in_group(index: GraphIndex, group: str) -> str:
    return next(r["id"] for r in index.truth["datasets"] if r.get("modality_group") == group)


def test_inapplicable_mutation_is_rejected(index: GraphIndex) -> None:
    # A genome-build defect must not apply to a non-WGS dataset (impossible/inapplicable).
    scrna = _dataset_in_group(index, "scrna-seq")
    assert DEFECTS["MOD-GENOME-BUILD-MISSING"].mutate(MutationContext(index, scrna)) is None
    # A VCF-index defect must not apply outside wgs-wes either.
    assert DEFECTS["LIN-VCF-INDEX-MISSING"].mutate(MutationContext(index, scrna)) is None
    # A domain-mislabel defect is a no-op (rejected) when the domain is already the target.
    genome = _dataset_in_group(index, "wgs-wes")
    assert DEFECTS["MOD-GENOME-BUILD-MISSING"].mutate(MutationContext(index, genome)) is not None
