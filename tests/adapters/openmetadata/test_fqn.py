"""Identity is the expensive thing to get wrong, so it is tested hardest.

If an FQN moves, re-loading the same benchmark produces a second estate beside
the first instead of updating it. Every test here is a defence of one property:
identity is a pure, injective, reversible function of stable DataSwamp ids and
nothing else.
"""

from __future__ import annotations

import pytest

from dataswamp_biosystems.adapters.openmetadata import ExportMode, SourceGraph, build_plan
from dataswamp_biosystems.adapters.openmetadata import fqn as om_fqn
from dataswamp_biosystems.adapters.openmetadata.validate import FQN_PATTERNS

# Ordinary slugs, then values a *defect* could plausibly inject. An observed
# graph is deliberately allowed to hold things the strict truth models forbid, so
# the codec has to survive all of them.
HOSTILE_IDS = [
    "ds-alpha",
    "a",
    "1",
    "ds.alpha",  # the FQN separator itself
    'ds"alpha',  # OpenMetadata's FQN quoting character
    "ds::alpha",  # forbidden by OpenMetadata's entityName pattern
    "ds alpha",
    "DS-ALPHA",
    "ds~alpha",  # the escape marker
    "ds/alpha",
    "ds\\alpha",
    "ds\talpha",
    "ds\nalpha",
    "ds<script>",
    "études-thérapeutiques",
    "数据集",
    "ds-α",
    "../../etc/passwd",
    "-",
    "~",
    ".",
    "..",
]


@pytest.mark.parametrize("value", HOSTILE_IDS)
def test_encode_round_trips_exactly(value: str) -> None:
    assert om_fqn.decode_id(om_fqn.encode_id(value)) == value


@pytest.mark.parametrize("value", HOSTILE_IDS)
def test_encoded_names_stay_in_the_safe_alphabet(value: str) -> None:
    encoded = om_fqn.encode_id(value)
    assert om_fqn.SAFE_SEGMENT.fullmatch(encoded)
    # The three characters OpenMetadata gives structural meaning to.
    assert "." not in encoded
    assert '"' not in encoded
    assert "::" not in encoded


def test_encoding_is_injective_across_every_hostile_value() -> None:
    encoded = [om_fqn.encode_id(value) for value in HOSTILE_IDS]
    assert len(set(encoded)) == len(HOSTILE_IDS)


def test_an_empty_identifier_is_refused_rather_than_collapsing_two_fqns() -> None:
    with pytest.raises(ValueError, match="empty identifier"):
        om_fqn.encode_id("")


def test_an_over_long_identifier_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="entityName limit"):
        om_fqn.encode_id("é" * 200)


def test_a_dot_in_an_id_cannot_re_parent_a_container() -> None:
    """The specific attack the codec exists to stop."""
    honest = om_fqn.dataset_fqn("study-a", "ds-b")
    smuggled = om_fqn.study_fqn("study-a.ds-b")
    assert honest != smuggled
    assert om_fqn.parent_fqn(honest) == om_fqn.study_fqn("study-a")
    assert om_fqn.parent_fqn(smuggled) == om_fqn.service_fqn()


# -- namespace policy ---------------------------------------------------------


def test_every_root_level_identity_is_namespaced() -> None:
    """A bare name would collide in OpenMetadata's global namespaces."""
    for built in (
        om_fqn.domain_fqn("prog-x"),
        om_fqn.team_fqn("team-x"),
        om_fqn.glossary_fqn("modality"),
        om_fqn.data_product_fqn("prog-x", "dp-x"),
    ):
        assert built.startswith(f"{om_fqn.NAMESPACE}-")
    assert om_fqn.classification_fqn() == om_fqn.NAMESPACE
    assert om_fqn.service_fqn() == om_fqn.SERVICE_NAME
    assert om_fqn.tag_fqn("x").startswith(f"{om_fqn.CLASSIFICATION_NAME}.")


def test_the_container_hierarchy_nests_by_string() -> None:
    service = om_fqn.service_fqn()
    study = om_fqn.study_fqn("study-a")
    dataset = om_fqn.dataset_fqn("study-a", "ds-b")
    file_ = om_fqn.file_fqn("study-a", "ds-b", "f-c")
    assert om_fqn.parent_fqn(file_) == dataset
    assert om_fqn.parent_fqn(dataset) == study
    assert om_fqn.parent_fqn(study) == service
    assert om_fqn.parent_fqn(service) is None


def test_names_are_the_last_segment() -> None:
    assert om_fqn.name_of(om_fqn.dataset_fqn("study-a", "ds-b")) == "ds-b"
    assert om_fqn.name_of(om_fqn.domain_fqn("prog-x")) == "dataswamp-prog-x"


def test_ids_are_recoverable_for_traceability() -> None:
    assert om_fqn.id_from_fqn(om_fqn.dataset_fqn("study-a", "ds.b")) == "ds.b"
    assert om_fqn.id_from_fqn(om_fqn.glossary_term_fqn("modality", "bulk-rna-seq")) == (
        "bulk-rna-seq"
    )


def test_entity_link_shape() -> None:
    link = om_fqn.entity_link("container", "dataswamp-biosystems.study-a")
    assert link == "<#E::container::dataswamp-biosystems.study-a>"


# -- identity does not depend on mutable metadata -----------------------------

MUTABLE_FIELDS = {
    "title": "a completely different title",
    "description": "a completely different description",
    "owner_ref": "team-someone-else",
    "steward_refs": ["team-someone-else"],
    "quality_status": "fail",
    "version": "99.0.0",
    "lifecycle_stage": "deprecated",
    "access_classification": "restricted",
}


def test_identity_survives_every_mutable_field_changing(
    mini_observed_source: SourceGraph,
) -> None:
    """The defining property: a defect that rewrites metadata must not move an FQN.

    Every field below is one the imperfection engine is allowed to corrupt. If
    any of them fed identity, re-loading a defect-bearing estate would duplicate
    it rather than update it.

    The comparison is over *asset* identities. Pointing an asset at a different
    owning team legitimately brings a different team into the export — that is a
    new entity appearing, not an existing identity moving.
    """

    def asset_fqns(plan: object) -> set[str]:
        return {
            record.fqn
            for record in plan.records  # type: ignore[attr-defined]
            if record.entity_type in {"container", "dataProduct"} and record.create is not None
        }

    baseline = asset_fqns(build_plan(mini_observed_source))

    mutated_shards = {
        shard: [
            {**record, **{key: value for key, value in MUTABLE_FIELDS.items() if key in record}}
            for record in records
        ]
        for shard, records in mini_observed_source.shards.items()
    }
    mutated = build_plan(SourceGraph(mode=ExportMode.OBSERVED, shards=mutated_shards))

    assert asset_fqns(mutated) == baseline


def test_a_checksum_change_does_not_move_a_file_identity(
    mini_observed_source: SourceGraph,
) -> None:
    baseline = {record.fqn for record in build_plan(mini_observed_source).records}
    shards = dict(mini_observed_source.shards)
    shards["files"] = [{**record, "checksum": "f" * 64} for record in shards["files"]]
    mutated = build_plan(SourceGraph(mode=ExportMode.OBSERVED, shards=shards))
    assert {record.fqn for record in mutated.records} == baseline


def test_no_emitted_identity_looks_like_a_uuid(mini_truth: object) -> None:
    """Server-assigned UUIDs are never DataSwamp identity."""
    import re

    uuid_like = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)
    for record in mini_truth.records:  # type: ignore[attr-defined]
        for segment in record.fqn.split("."):
            assert not uuid_like.match(segment)


def test_every_entity_type_has_a_declared_fqn_pattern(mini_truth: object) -> None:
    for record in mini_truth.records:  # type: ignore[attr-defined]
        assert record.entity_type in FQN_PATTERNS


def test_the_adapter_does_not_import_datahub_identity_helpers() -> None:
    """Two adapters, two codecs. Sharing one today is a coupling to undo later."""
    import ast
    from pathlib import Path

    source = Path(om_fqn.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "datahub" not in node.module
        elif isinstance(node, ast.Import):
            assert all("datahub" not in alias.name for alias in node.names)
