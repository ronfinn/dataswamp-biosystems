"""The two adapters must independently declare the same semantic-family set.

This is a **vocabulary** check and nothing more. The classifications are
intentionally different — DataHub holds stewardship natively and OpenMetadata
does not, and both readings are correct for their own adapter — so comparing
them here would assert a similarity that does not exist.

Equality is enforced structurally rather than by sharing a registry: the test
may import both, but neither adapter may import the other, which
``tests/adapters/test_isolation.py`` continues to prove. There is deliberately
no neutral benchmark-owned registry yet; with two examples it is not clear which
similarities are structural rather than merely coincidental.
"""

from __future__ import annotations

from dataswamp_biosystems.adapters.datahub.coverage import CONCEPT_NAMES as DATAHUB_FAMILIES
from dataswamp_biosystems.adapters.openmetadata.coverage import (
    CONCEPT_NAMES as OPENMETADATA_FAMILIES,
)


def test_the_two_adapters_declare_the_same_semantic_families() -> None:
    missing_from_datahub = sorted(OPENMETADATA_FAMILIES - DATAHUB_FAMILIES)
    missing_from_openmetadata = sorted(DATAHUB_FAMILIES - OPENMETADATA_FAMILIES)
    assert not (missing_from_datahub or missing_from_openmetadata), (
        f"missing from DataHub: {missing_from_datahub or 'none'}; "
        f"missing from OpenMetadata: {missing_from_openmetadata or 'none'}"
    )


def test_both_registries_declare_twenty_four_families() -> None:
    assert len(DATAHUB_FAMILIES) == 24
    assert len(OPENMETADATA_FAMILIES) == 24
