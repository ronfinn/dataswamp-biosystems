"""The naive metadata baseline: shallow, single-record field checks.

Every check here looks at *one field of one record* and asks only whether it is
absent, empty, short, or oddly shaped. Nothing is cross-referenced, no second
record is consulted, and no rule's semantics are modelled beyond "this field
looks thin".

It is meant to score badly on precision, and the reason is the point of the
exercise. A short title is not a *wrong* title; a non-``X.Y.Z`` version string is
not a *non-canonical* version in this estate's vocabulary; a null optional field
is usually just an optional field. Shallow signals correlate with defects
without identifying them, so this agent flags a large number of perfectly clean
entities — including entities in the reserved control partition, which is
precisely the measurement the control partition exists to make possible.

Read it as a demonstration of what the benchmark refuses to reward, not as an
attempt at a good score. It proposes no remediations at all: an agent with no
model of *why* a field is thin has no basis for saying how to fix it, and the
benchmark scores a missing remediation differently from a wrong one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from dataswamp_biosystems.baselines.base import (
    BaselineInfo,
    in_order,
    make_prediction,
    modality_of,
)
from dataswamp_biosystems.baselines.catalogue import RULE_FACTS
from dataswamp_biosystems.baselines.observed_input import ObservedEntity, ObservedInput
from dataswamp_biosystems.evaluation.predictions import Prediction

NAIVE_BASELINE_VERSION = "1.0.0"

# The single confidence this agent reports on everything it says. A flat value is
# honest: it has no evidence with which to prefer one shallow signal over
# another, and a fabricated spread would imply a calibration it does not have.
NAIVE_CONFIDENCE = 0.5

# What "short" means for the two prose fields. Arbitrary, and deliberately so —
# an arbitrary threshold is exactly the kind of heuristic this baseline exists to
# characterise.
SHORT_DESCRIPTION_CHARS = 60
SHORT_TITLE_CHARS = 20

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _is_blank(value: Any) -> bool:
    """Whether a field is absent, null, or an empty string/list/mapping."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | dict):
        return not value
    return False


@dataclass(frozen=True)
class NaiveCheck:
    """One shallow signal: a rule id, the field it looks at, and the test."""

    rule_id: str
    field: str
    evidence: str
    test: Callable[[Any], bool]


def _blank(rule_id: str, field: str, evidence: str) -> NaiveCheck:
    return NaiveCheck(rule_id=rule_id, field=field, evidence=evidence, test=_is_blank)


def _present_and(
    rule_id: str, field: str, evidence: str, test: Callable[[Any], bool]
) -> NaiveCheck:
    """A check that fires only when the field is present.

    Absence and thinness are different claims, and firing both on one empty field
    would be an obvious double-count rather than an interesting one.
    """
    return NaiveCheck(
        rule_id=rule_id,
        field=field,
        evidence=evidence,
        test=lambda value: not _is_blank(value) and test(value),
    )


def _shorter_than(limit: int) -> Callable[[Any], bool]:
    return lambda value: isinstance(value, str) and len(value.strip()) < limit


def _not_semver(value: Any) -> bool:
    return isinstance(value, str) and _SEMVER.match(value.strip()) is None


# Checks are declared in rule-id order and applied in that order. Applicability
# to a given entity is decided by the published catalogue, so a dataset-only rule
# is never filed against a data product.
NAIVE_CHECKS: tuple[NaiveCheck, ...] = (
    _blank("GOV-CLASS-MISSING", "access_classification", "no access classification recorded"),
    _blank("GOV-RETENTION-MISSING", "retention_class", "no retention class recorded"),
    _blank("META-DESC-MISSING", "description", "description field is absent or empty"),
    _blank("META-MODALITY-META-EMPTY", "modality_metadata", "modality metadata is empty"),
    _blank("META-TITLE-MISSING", "title", "title field is absent or empty"),
    _blank("META-VERSION-MISSING", "version", "version field is absent or empty"),
    _present_and(
        "NAM-VERSION-NONCANONICAL",
        "version",
        "version does not look like MAJOR.MINOR.PATCH",
        _not_semver,
    ),
    _blank("OWN-OWNER-MISSING", "owner_ref", "no owner reference recorded"),
    _blank("OWN-STEWARD-MISSING", "steward_refs", "no steward references recorded"),
    _blank("SCH-CONTRACT-MISSING", "contract_ref", "no data contract referenced"),
    _blank("SCH-RECORD-COUNT-ZERO", "record_count", "record count is absent or zero"),
    _present_and(
        "SEM-DESC-GENERIC",
        "description",
        f"description is shorter than {SHORT_DESCRIPTION_CHARS} characters",
        _shorter_than(SHORT_DESCRIPTION_CHARS),
    ),
    _present_and(
        "SEM-TITLE-UNINFORMATIVE",
        "title",
        f"title is shorter than {SHORT_TITLE_CHARS} characters",
        _shorter_than(SHORT_TITLE_CHARS),
    ),
    _blank("USE-INTENDED-USE-MISSING", "intended_uses", "no intended uses recorded"),
    _blank("FILE-CHECKSUM-MISMATCH", "checksum", "file record carries no checksum"),
)

# ``record_count`` of zero is falsy but not blank, so the check above needs the
# extra arm. Declared separately to keep ``_is_blank`` honest about its name.
_ZERO_IS_BLANK_FIELDS = frozenset({"record_count"})


# Entity kinds are named by rule applicability; the read list is published in
# terms of the observed graph's shards, which is what a reader actually opens.
_SHARD_BY_KIND: dict[str, str] = {
    "dataset": "datasets",
    "data_product": "data_products",
    "file": "files",
}


def _declared_reads() -> tuple[str, ...]:
    """Derive the documented read list from the checks themselves.

    Generated rather than hand-maintained, so the published "what may this agent
    read" table cannot drift away from what the code actually inspects.
    """
    return tuple(
        sorted(
            {
                f"{_SHARD_BY_KIND[kind]}.{check.field}"
                for check in NAIVE_CHECKS
                for kind in RULE_FACTS[check.rule_id].applies_to_kinds
                if kind in _SHARD_BY_KIND
            }
        )
    )


def _fires(check: NaiveCheck, entity: ObservedEntity) -> bool:
    value = entity.get(check.field)
    if check.field in _ZERO_IS_BLANK_FIELDS and value == 0:
        return True
    return check.test(value)


class NaiveMetadataBaseline:
    """Flags entities on shallow single-field signals."""

    info = BaselineInfo(
        name="naive-metadata",
        version=NAIVE_BASELINE_VERSION,
        summary=(
            "Flags absent, empty, short or oddly-shaped metadata fields, one record at a "
            "time. Low precision by construction; proposes no remediations."
        ),
        reads=_declared_reads(),
    )

    def predict(self, observed: ObservedInput) -> Iterator[Prediction]:
        found: list[Prediction] = []
        for entity in observed.entities:
            if not entity.entity_id:
                continue
            modality = modality_of(entity)
            for check in NAIVE_CHECKS:
                fact = RULE_FACTS[check.rule_id]
                if not fact.applies_to(entity.kind, modality):
                    continue
                if _fires(check, entity):
                    found.append(
                        make_prediction(
                            info=self.info,
                            entity_id=entity.entity_id,
                            fact=fact,
                            evidence=check.evidence,
                            confidence=NAIVE_CONFIDENCE,
                            with_remediation=False,
                        )
                    )
        yield from in_order(found)


__all__ = [
    "NAIVE_BASELINE_VERSION",
    "NAIVE_CHECKS",
    "NAIVE_CONFIDENCE",
    "NaiveCheck",
    "NaiveMetadataBaseline",
]
