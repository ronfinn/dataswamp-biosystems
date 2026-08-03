"""Deterministic URNs: stability, reversibility, safety and collision resistance."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from dataswamp_biosystems.adapters.datahub import urns


def test_urns_are_pure_functions_of_the_id() -> None:
    assert urns.dataset_urn("ds-alpha") == urns.dataset_urn("ds-alpha")
    assert urns.dataset_urn("ds-alpha") != urns.dataset_urn("ds-bravo")


def test_urn_shapes_are_documented_and_stable() -> None:
    """Pinned literally: a URN change is a breaking change for every consumer."""
    assert urns.dataset_urn("ds-alpha") == (
        "urn:li:dataset:(urn:li:dataPlatform:dataswamp,dataswamp_biosystems.ds-alpha,PROD)"
    )
    assert urns.data_product_urn("dp-omics") == "urn:li:dataProduct:dataswamp.dp-omics"
    assert urns.corp_group_urn("team-genomics") == "urn:li:corpGroup:team-genomics"
    assert urns.domain_urn("prog-nsclc") == "urn:li:domain:dataswamp.prog-nsclc"
    assert urns.glossary_term_urn("modality", "scrna-seq") == (
        "urn:li:glossaryTerm:dataswamp.modality.scrna-seq"
    )
    assert urns.tag_urn("sequencing") == "urn:li:tag:sequencing"


def test_key_hashed_urns_are_fixed_width_hex() -> None:
    for urn in (urns.container_urn("study-nsclc-01"), urns.assertion_urn("qc-1")):
        guid = urn.rsplit(":", 1)[1]
        assert len(guid) == urns.GUID_LENGTH
        assert set(guid) <= set("0123456789abcdef")


def test_key_hashed_urns_are_namespaced_by_entity_family() -> None:
    """Two families sharing an id must not share a GUID."""
    assert urns.container_urn("same-id") != urns.assertion_urn("same-id")


def test_dataset_urn_round_trips_to_the_dataswamp_id() -> None:
    for asset_id in ("ds-alpha", "dp-omics", "file-ds-alpha-1"):
        assert urns.dataset_id_from_urn(urns.dataset_urn(asset_id)) == asset_id


def test_dataset_id_from_urn_rejects_a_foreign_urn() -> None:
    with pytest.raises(ValueError, match="not a DataSwamp dataset URN"):
        urns.dataset_id_from_urn("urn:li:dataset:(urn:li:dataPlatform:hive,db.table,PROD)")


@pytest.mark.parametrize(
    "raw",
    ["ds-alpha", "ds,alpha", "ds)alpha(", "ds:alpha", "ds alpha", "ds~alpha", "DS-Alpha", "dsé"],
)
def test_encoding_is_injective_and_reversible(raw: str) -> None:
    encoded = urns.encode_id(raw)
    assert urns.decode_id(encoded) == raw
    assert set(encoded) <= set("abcdefghijklmnopqrstuvwxyz0123456789-~")


def test_encoding_never_leaks_urn_delimiters() -> None:
    """A defect must not be able to inject URN syntax through a mutated id."""
    hostile = "ds,PROD):(urn:li:dataPlatform:hive"
    urn = urns.dataset_urn(hostile)
    # The template contributes exactly two commas and one bracket pair; a
    # smuggled delimiter would add more.
    assert urn.count(",") == 2 and urn.count("(") == 1 and urn.count(")") == 1
    assert urns.dataset_id_from_urn(urn) == hostile


def test_empty_ids_are_refused_rather_than_producing_an_empty_component() -> None:
    with pytest.raises(ValueError, match="empty identifier"):
        urns.encode_id("")


def test_no_collisions_across_a_large_id_space() -> None:
    ids = [f"ds-{index:05d}" for index in range(5000)]
    for builder in (urns.dataset_urn, urns.data_product_urn, urns.container_urn):
        built = {builder(entity_id) for entity_id in ids}
        assert len(built) == len(ids)


def test_encoded_ids_do_not_collide_with_unencoded_ones() -> None:
    """``ds:alpha`` must not encode onto the same string as some literal id."""
    seen: dict[str, str] = {}
    for raw in ("ds-alpha", "ds:alpha", "ds~2dalpha", "ds~alpha", "ds.alpha"):
        encoded = urns.encode_id(raw)
        assert encoded not in seen, f"{raw!r} collides with {seen.get(encoded)!r}"
        seen[encoded] = raw


def test_urns_are_stable_across_processes() -> None:
    """No hash randomisation may reach identity."""
    script = (
        "from dataswamp_biosystems.adapters.datahub import urns;"
        "print(urns.container_urn('study-nsclc-01'), urns.assertion_urn('qc-1'))"
    )
    outputs = set()
    for seed in ("0", "424242"):
        result = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1
