"""The offline plan validator, exercised by breaking things on purpose.

A validator nobody has watched reject anything is not evidence. Every check here
perturbs a *sound* plan in exactly one way and asserts that the specific problem
is reported — so a future refactor that quietly stops checking something fails
rather than passing more easily.
"""

from __future__ import annotations

import dataclasses

import pytest

from dataswamp_biosystems.adapters.openmetadata import (
    ExportMode,
    ExportPlan,
    PlanRecord,
    Reference,
    validate_plan,
)
from dataswamp_biosystems.adapters.openmetadata import fqn as om_fqn


def _replace(plan: ExportPlan, index: int, **changes: object) -> ExportPlan:
    """Return ``plan`` with one entity record altered."""
    entities = list(plan.entities)
    entities[index] = dataclasses.replace(entities[index], **changes)
    return dataclasses.replace(plan, entities=tuple(entities))


def _index_of(plan: ExportPlan, phase: str) -> int:
    return next(i for i, record in enumerate(plan.entities) if record.phase == phase)


def _problems_matching(plan: ExportPlan, fragment: str) -> list[str]:
    return [problem for problem in validate_plan(plan) if fragment in problem]


def test_a_sound_plan_has_no_problems(mini_observed: ExportPlan, mini_truth: ExportPlan) -> None:
    assert validate_plan(mini_observed) == []
    assert validate_plan(mini_truth) == []


# -- identity -----------------------------------------------------------------


def test_an_unnamespaced_root_identity_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "domain")
    broken = _replace(mini_observed, index, fqn="genomics")
    assert _problems_matching(broken, "not a well-formed domain")


def test_an_unescaped_character_in_an_fqn_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "team")
    broken = _replace(mini_observed, index, fqn="dataswamp-team genomics")
    assert _problems_matching(broken, "not a well-formed team")


def test_a_duplicate_fqn_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    duplicate = dataclasses.replace(
        mini_observed.entities[index + 1], fqn=mini_observed.entities[index].fqn
    )
    entities = list(mini_observed.entities)
    entities[index + 1] = duplicate
    broken = dataclasses.replace(mini_observed, entities=tuple(entities))
    assert _problems_matching(broken, "duplicate fully-qualified name")


def test_the_same_fqn_under_two_entity_types_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "team")
    clash = dataclasses.replace(
        mini_observed.entities[index],
        entity_type="domain",
        phase="domain",
        order=mini_observed.entities[index].order,
    )
    glossary = _index_of(mini_observed, "glossary")
    broken = _replace(mini_observed, glossary, fqn=clash.fqn, entity_type="glossary")
    assert _problems_matching(broken, "emitted as both")


def test_a_bad_custom_property_name_is_rejected(mini_observed: ExportPlan) -> None:
    properties = list(mini_observed.custom_properties)
    properties[0] = dataclasses.replace(
        properties[0], create={"name": "my property!", "description": "x"}
    )
    broken = dataclasses.replace(mini_observed, custom_properties=tuple(properties))
    assert _problems_matching(broken, "custom-property name")


# -- ordering -----------------------------------------------------------------


def test_a_phase_out_of_contract_order_is_rejected(mini_observed: ExportPlan) -> None:
    entities = list(mini_observed.entities)
    dataset = _index_of(mini_observed, "dataset-container")
    entities.insert(
        0,
        dataclasses.replace(entities[dataset], order=0, fqn="dataswamp-biosystems.study-late"),
    )
    broken = dataclasses.replace(mini_observed, entities=tuple(entities))
    assert validate_plan(broken)


def test_a_non_increasing_order_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    broken = _replace(mini_observed, index, order=1)
    assert _problems_matching(broken, "does not increase")


def test_an_unknown_phase_is_rejected(mini_observed: ExportPlan) -> None:
    broken = _replace(mini_observed, 0, phase="whenever")
    assert _problems_matching(broken, "unknown load phase")


# -- reference closure --------------------------------------------------------


def test_a_dangling_reference_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    broken = _replace(
        mini_observed,
        index,
        references=(
            Reference(field="owners", entity_type="team", target="dataswamp-team-ghost", many=True),
        ),
    )
    assert _problems_matching(broken, "which this export never emits")


def test_a_forward_reference_is_rejected(mini_observed: ExportPlan) -> None:
    """Existing somewhere in the file is not the same as existing yet."""
    index = _index_of(mini_observed, "dataset-container")
    last = max(record.order for record in mini_observed.records)
    broken = _replace(
        mini_observed,
        index,
        references=(
            Reference(
                field="parent",
                entity_type="container",
                target=om_fqn.study_fqn("study-nsclc-01"),
            ),
        ),
        order=1,
    )
    assert validate_plan(broken)
    assert last > 0


def test_a_dangling_inline_domain_reference_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    record = mini_observed.entities[index]
    broken = _replace(
        mini_observed, index, create={**record.create, "domains": ["dataswamp-nowhere"]}
    )
    assert _problems_matching(broken, "domain 'dataswamp-nowhere' is never emitted")


def test_a_dangling_tag_reference_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    record = mini_observed.entities[index]
    broken = _replace(
        mini_observed,
        index,
        create={
            **record.create,
            "tags": [
                {
                    "tagFQN": "dataswamp.invented",
                    "source": "Classification",
                    "labelType": "Manual",
                    "state": "Confirmed",
                }
            ],
        },
    )
    assert _problems_matching(broken, "tag 'dataswamp.invented' is never emitted")


def test_an_off_allow_list_builtin_reference_is_rejected(mini_observed: ExportPlan) -> None:
    """There is no general 'this one is external' flag, deliberately."""
    properties = list(mini_observed.custom_properties)
    properties[0] = dataclasses.replace(
        properties[0],
        references=(
            Reference(field="propertyType", entity_type="type", target="table", builtin=True),
        ),
    )
    broken = dataclasses.replace(mini_observed, custom_properties=tuple(properties))
    assert _problems_matching(broken, "built-in allow-list")


# -- containment and cycles ---------------------------------------------------


def test_a_container_that_is_its_own_parent_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    record = mini_observed.entities[index]
    broken = _replace(
        mini_observed,
        index,
        references=(Reference(field="parent", entity_type="container", target=record.fqn),),
    )
    assert validate_plan(broken)


def test_a_parent_that_is_not_the_containing_fqn_is_rejected(
    mini_observed: ExportPlan,
) -> None:
    """A parent cycle cannot be built, because parenthood is checked against the FQN."""
    index = _index_of(mini_observed, "file-container")
    broken = _replace(
        mini_observed,
        index,
        references=(
            Reference(
                field="parent",
                entity_type="container",
                target=om_fqn.study_fqn("study-nsclc-01"),
            ),
        ),
    )
    assert _problems_matching(broken, "is not the containing FQN")


def test_a_nested_container_without_a_parent_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    broken = _replace(mini_observed, index, references=())
    assert _problems_matching(broken, "declares no parent reference")


def test_self_lineage_is_rejected_if_it_ever_reaches_the_plan(
    mini_observed: ExportPlan,
) -> None:
    edge = mini_observed.lineage[0]
    target = edge.references[0].target
    broken = dataclasses.replace(
        mini_observed,
        lineage=(
            dataclasses.replace(
                edge,
                references=(
                    Reference(field="fromEntity", entity_type="container", target=target),
                    Reference(field="toEntity", entity_type="container", target=target),
                ),
            ),
        ),
    )
    assert _problems_matching(broken, "self-lineage")


# -- the privilege boundary ---------------------------------------------------


def test_a_truth_property_in_an_observed_plan_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    record = mini_observed.entities[index]
    broken = _replace(
        mini_observed,
        index,
        create={
            **record.create,
            "extension": {**record.create["extension"], "dataswampTruthExport": "true"},
        },
    )
    assert _problems_matching(broken, "truth-only propert")


def test_a_privileged_tag_in_an_observed_plan_is_rejected(mini_observed: ExportPlan) -> None:
    index = _index_of(mini_observed, "dataset-container")
    record = mini_observed.entities[index]
    broken = _replace(
        mini_observed,
        index,
        create={
            **record.create,
            "tags": [
                *record.create["tags"],
                {
                    "tagFQN": om_fqn.tag_fqn("privileged-truth-export"),
                    "source": "Classification",
                    "labelType": "Manual",
                    "state": "Confirmed",
                },
            ],
        },
    )
    assert _problems_matching(broken, "privileged truth-export tag")


def test_a_truth_asset_missing_its_privilege_marker_is_rejected(
    mini_truth: ExportPlan,
) -> None:
    index = _index_of(mini_truth, "dataset-container")
    record = mini_truth.entities[index]
    stripped = {
        key: value
        for key, value in record.create["extension"].items()
        if key != "dataswampTruthExport"
    }
    broken = _replace(mini_truth, index, create={**record.create, "extension": stripped})
    assert _problems_matching(broken, "lacks the dataswampTruthExport marker")


def test_a_truth_asset_missing_its_privileged_tag_is_rejected(mini_truth: ExportPlan) -> None:
    index = _index_of(mini_truth, "data-product")
    record = mini_truth.entities[index]
    kept = [
        tag
        for tag in record.create["tags"]
        if tag["tagFQN"] != om_fqn.tag_fqn("privileged-truth-export")
    ]
    broken = _replace(mini_truth, index, create={**record.create, "tags": kept})
    assert _problems_matching(broken, "not tagged privileged")


@pytest.mark.parametrize("mode", list(ExportMode))
def test_plan_records_are_frozen(mode: ExportMode) -> None:
    """Plan records are values, so a validator can never alter what it checked."""
    record = PlanRecord(
        order=1,
        phase="tag",
        concept="facet_tag",
        entity_type="tag",
        endpoint="/x",
        fqn="dataswamp.x",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.order = 2  # type: ignore[misc]
    assert mode in ExportMode
