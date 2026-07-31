"""Tests for truth-graph generation: counts, allocation, and integrity."""

from __future__ import annotations

from dataswamp_biosystems.company import CanonicalConfig
from dataswamp_biosystems.truth import GenerationPlan
from dataswamp_biosystems.truth.graph import TruthGraph
from dataswamp_biosystems.truth.plan import even_split


def test_headline_counts(graph: TruthGraph, plan: GenerationPlan) -> None:
    counts = graph.entity_counts()
    assert counts["subjects"] == 60
    assert counts["datasets"] == plan.total_datasets() == 165
    assert counts["data_products"] == plan.data_product_count == 15
    # One contract, governance record, and training approval per catalogue asset.
    assets = counts["datasets"] + counts["data_products"]
    assert counts["contracts"] == assets
    assert counts["governance_records"] == assets
    assert counts["training_approvals"] == assets


def test_per_modality_counts_match_plan(graph: TruthGraph, plan: GenerationPlan) -> None:
    for group in plan.modality_groups:
        actual = sum(
            1 for d in graph.datasets if d.modality_group == group.id and not d.is_reference
        )
        assert actual == group.dataset_count, group.id


def test_reference_datasets_are_flagged(graph: TruthGraph, plan: GenerationPlan) -> None:
    reference = [d for d in graph.datasets if d.is_reference]
    assert len(reference) == plan.reference_dataset_count
    for dataset in reference:
        assert dataset.modality_group == "reference"
        # Cross-modal reference datasets still take a representative study/modality
        # (belonging to their programme) so every catalogue entry is complete.
        assert dataset.study_id
        assert dataset.modality


def test_all_entities_are_synthetic(graph: TruthGraph) -> None:
    for name, value in graph:
        if name == "meta":
            continue
        for entity in value:
            assert entity.synthetic is True


def test_subjects_split_ten_per_study(graph: TruthGraph, config: CanonicalConfig) -> None:
    per_study: dict[str, int] = {}
    for subject in graph.subjects:
        per_study[subject.study_id] = per_study.get(subject.study_id, 0) + 1
    assert set(per_study.values()) == {10}
    assert set(per_study) == {s.id for s in config.studies}


def test_experimental_models_only_in_functional_studies(
    graph: TruthGraph, plan: GenerationPlan
) -> None:
    functional_studies = {
        study
        for group in plan.modality_groups
        if group.subject_kind.value == "experimental_model"
        for study in group.studies
    }
    for subject in graph.subjects:
        if subject.kind.value == "experimental_model":
            assert subject.study_id in functional_studies


def test_even_split_is_exact_and_deterministic() -> None:
    result = even_split(25, ["c", "a", "b", "d"])
    assert sum(result.values()) == 25
    # Remainder (25 % 4 == 1) goes to the lowest-sorted key.
    assert result == {"a": 7, "b": 6, "c": 6, "d": 6}


def test_logical_size_at_least_physical(graph: TruthGraph) -> None:
    for dataset in graph.datasets:
        assert dataset.logical_bytes >= dataset.physical_bytes
        assert dataset.physical_bytes >= 0
