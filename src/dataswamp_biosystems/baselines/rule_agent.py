"""The deterministic rule-based baseline: a small set of transparent checks.

Twenty of the benchmark's forty-one rules are re-implemented here, directly
against the observed graph. Each one is a short, readable function whose whole
argument is visible on the page — the intent is that a reader can decide for
themselves whether a check is fair, not take a score on trust.

The subset is chosen by what the observed graph can actually support, and the
omissions are as informative as the inclusions:

*Included* are the rules whose violation is a structural fact of the observed
metadata — an absent required field, a reference that resolves to nothing, two
records that disagree with each other, a reference the graph itself contradicts.

*Excluded* are four kinds of rule this approach cannot honestly reach:

* rules needing the bytes on disk (``FILE-CHECKSUM-MISMATCH`` cannot be decided
  without recomputing a checksum; ``MOD-H5AD-NO-COUNTS-LAYER`` needs the file);
* rules needing the *correct* value to compare against — ``SEM-DOMAIN-MISLABELLED``,
  ``OWN-OWNER-WRONG-TEAM``, ``GOV-RESTRICTED-AS-INTERNAL``. A wrong-but-plausible
  value is indistinguishable from a right one without the truth graph, and
  reaching for the truth graph is exactly what a participant may not do;
* rules resting on a vocabulary or convention the observed graph does not carry
  (``NAM-PATH-CONVENTION``, ``NAM-VERSION-NONCANONICAL``);
* rules needing a policy threshold the benchmark does not publish —
  ``GOV-STALE-REVIEW`` and ``LIF-STALE-ASSET``. Staleness is a judgement about
  how old is too old, and this estate legitimately contains records older than
  any defensible cut-off. ``docs/baselines.md`` records what a threshold
  actually costs here, measured rather than asserted.

So this agent establishes the practical ceiling for a non-learning, metadata-only
approach, and its per-rule breakdown is a map of which rules are trivially
detectable and which are not. It is not, and is not offered as, a
production-quality governance agent: it has no notion of context, priority or
cost, and its remediation proposals are copied verbatim from the published rule
contract rather than reasoned about.
"""

from __future__ import annotations

from collections.abc import Iterator
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

RULE_BASELINE_VERSION = "1.0.0"

# Every check this agent makes is structural — the fact is either in the graph or
# it is not — so they all report one confidence. A spread across checks would
# imply a calibration this agent has no way to have earned.
STRUCTURAL_CONFIDENCE = 0.9

# Vocabulary terms from ``config/vocabularies/``, which ships with the benchmark
# and is visible to any participant. Spelled out here rather than loaded, so this
# agent stays a single-input reader; a term that left the vocabulary would show up
# as the check silently never firing, which the per-rule breakdown makes visible.
RESTRICTED_CLASSIFICATIONS = frozenset({"restricted", "highly-restricted"})
EXTERNAL_USES = frozenset({"external-sharing"})
TRAINING_USES = frozenset({"model-training"})
TRAINING_APPROVED_STATUS = "model-training-approved"

# Quality statuses that assert the asset's data is sound. An asset holding one of
# these while its own quality evidence records a failure contradicts itself.
ASSERTED_GOOD_QUALITY = frozenset({"pass", "certified"})
QUALITY_CHECK_FAILED = "fail"


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | dict):
        return not value
    return False


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


class RuleBasedBaseline:
    """Re-implements a documented subset of the defect rules over observed metadata."""

    #: The rules this agent attempts, in rule-id order. Every rule it emits is in
    #: this tuple, and a test asserts the converse.
    IMPLEMENTED_RULES: tuple[str, ...] = (
        "AIR-TRAINING-APPROVAL-ABSENT",
        "AIR-TRAINING-STATUS-MISMATCH",
        "GOV-CLASS-MISSING",
        "GOV-RETENTION-MISSING",
        "LIN-DATASET-NO-UPSTREAM",
        "LIN-PROVENANCE-DANGLING",
        "META-DESC-MISSING",
        "META-MODALITY-META-EMPTY",
        "META-TITLE-MISSING",
        "META-VERSION-MISSING",
        "OWN-DENORM-MISMATCH",
        "OWN-OWNER-MISSING",
        "OWN-STEWARD-MISSING",
        "QC-CERTIFIED-CONTRADICTED",
        "SCH-CONTRACT-MISSING",
        "SCH-RECORD-COUNT-ZERO",
        "SCH-SIZE-INVERSION",
        "USE-EXTERNAL-VS-RESTRICTED",
        "USE-INTENDED-USE-MISSING",
        "USE-TRAINING-WITHOUT-APPROVAL",
    )

    info = BaselineInfo(
        name="rule-based",
        version=RULE_BASELINE_VERSION,
        summary=(
            "Re-implements a transparent subset of the defect rules against observed "
            "metadata, with remediations copied from the published rule contract."
        ),
        reads=(
            "data_products.access_classification",
            "data_products.contract_ref",
            "data_products.description",
            "data_products.intended_uses",
            "data_products.model_training_status",
            "data_products.owner_ref",
            "data_products.quality_status",
            "data_products.retention_class",
            "data_products.steward_refs",
            "data_products.title",
            "data_products.version",
            "datasets.access_classification",
            "datasets.contract_ref",
            "datasets.description",
            "datasets.id",
            "datasets.intended_uses",
            "datasets.logical_bytes",
            "datasets.modality",
            "datasets.modality_metadata",
            "datasets.model_training_status",
            "datasets.owner_ref",
            "datasets.physical_bytes",
            "datasets.provenance_run_id",
            "datasets.quality_status",
            "datasets.record_count",
            "datasets.retention_class",
            "datasets.steward_refs",
            "datasets.title",
            "datasets.version",
            "governance_records.asset_id",
            "governance_records.owner_ref",
            "instrument_runs.id",
            "lineage.downstream_id",
            "pipeline_runs.id",
            "quality_checks.asset_id",
            "quality_checks.check_type",
            "quality_checks.status",
            "training_approvals.asset_id",
            "training_approvals.status",
        ),
    )

    def predict(self, observed: ObservedInput) -> Iterator[Prediction]:
        found: list[Prediction] = []
        governance = observed.governance_by_asset
        checks = observed.quality_checks_by_asset
        approvals = observed.training_approvals_by_asset
        contract_ids = observed.contract_ids
        run_ids = observed.run_ids
        downstream = observed.lineage_downstream_ids

        for entity in observed.assets:
            if not entity.entity_id:
                continue
            for rule_id, evidence, confidence in self._asset_claims(
                entity,
                governance=governance.get(entity.entity_id, []),
                quality_checks=checks.get(entity.entity_id, []),
                approvals=approvals.get(entity.entity_id, []),
                contract_ids=contract_ids,
                run_ids=run_ids,
                downstream=downstream,
            ):
                fact = RULE_FACTS[rule_id]
                if not fact.applies_to(entity.kind, modality_of(entity)):
                    continue
                found.append(
                    make_prediction(
                        info=self.info,
                        entity_id=entity.entity_id,
                        fact=fact,
                        evidence=evidence,
                        confidence=confidence,
                        with_remediation=True,
                    )
                )
        yield from in_order(found)

    # -- the checks -----------------------------------------------------------

    def _asset_claims(
        self,
        entity: ObservedEntity,
        *,
        governance: list[dict[str, Any]],
        quality_checks: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
        contract_ids: frozenset[str],
        run_ids: frozenset[str],
        downstream: frozenset[str],
    ) -> Iterator[tuple[str, str, float]]:
        """Yield ``(rule_id, evidence, confidence)`` for every check that fires."""
        yield from self._required_fields(entity)
        yield from self._contract(entity, contract_ids)
        yield from self._sizes_and_counts(entity)
        yield from self._ownership(entity, governance)
        yield from self._certification(entity, quality_checks)
        yield from self._lineage(entity, run_ids, downstream)
        yield from self._intended_use(entity)
        yield from self._training(entity, approvals)

    def _required_fields(self, entity: ObservedEntity) -> Iterator[tuple[str, str, float]]:
        """Fields the estate requires on every catalogue asset."""
        required = (
            ("META-TITLE-MISSING", "title", "the asset carries no title"),
            ("META-DESC-MISSING", "description", "the asset carries no description"),
            ("META-VERSION-MISSING", "version", "the asset carries no version"),
            ("OWN-OWNER-MISSING", "owner_ref", "the asset names no owner"),
            ("OWN-STEWARD-MISSING", "steward_refs", "the asset names no steward"),
            (
                "GOV-CLASS-MISSING",
                "access_classification",
                "the asset carries no access classification",
            ),
            ("GOV-RETENTION-MISSING", "retention_class", "the asset carries no retention class"),
            (
                "META-MODALITY-META-EMPTY",
                "modality_metadata",
                "the dataset declares a modality but carries no modality metadata",
            ),
        )
        for rule_id, field, evidence in required:
            if _blank(entity.get(field)):
                yield rule_id, evidence, STRUCTURAL_CONFIDENCE

    def _contract(
        self, entity: ObservedEntity, contract_ids: frozenset[str]
    ) -> Iterator[tuple[str, str, float]]:
        """A contract must be referenced, and the reference must resolve."""
        reference = _text(entity.get("contract_ref"))
        if not reference:
            yield (
                "SCH-CONTRACT-MISSING",
                "the asset references no data contract",
                STRUCTURAL_CONFIDENCE,
            )
        elif reference not in contract_ids:
            yield (
                "SCH-CONTRACT-MISSING",
                f"contract reference {reference} resolves to no contract record",
                STRUCTURAL_CONFIDENCE,
            )

    def _sizes_and_counts(self, entity: ObservedEntity) -> Iterator[tuple[str, str, float]]:
        """Internal arithmetic that the record itself contradicts."""
        count = entity.get("record_count")
        if isinstance(count, int) and count == 0:
            yield "SCH-RECORD-COUNT-ZERO", "record count is zero", STRUCTURAL_CONFIDENCE

        logical = entity.get("logical_bytes")
        physical = entity.get("physical_bytes")
        if isinstance(logical, int) and isinstance(physical, int) and logical < physical:
            yield (
                "SCH-SIZE-INVERSION",
                f"logical size {logical} is smaller than physical size {physical}",
                STRUCTURAL_CONFIDENCE,
            )

    def _ownership(
        self, entity: ObservedEntity, governance: list[dict[str, Any]]
    ) -> Iterator[tuple[str, str, float]]:
        """The asset and its governance record must agree about who owns it."""
        owner = _text(entity.get("owner_ref"))
        if not owner:
            return
        # Sorted, not first-seen: an asset with several governance records would
        # otherwise have its evidence decided by the order they appear in the file.
        disagreeing = sorted(
            {
                recorded
                for record in governance
                if (recorded := _text(record.get("owner_ref"))) and recorded != owner
            }
        )
        if disagreeing:
            yield (
                "OWN-DENORM-MISMATCH",
                f"asset owner {owner} disagrees with governance record owner "
                f"{', '.join(disagreeing)}",
                STRUCTURAL_CONFIDENCE,
            )

    def _certification(
        self, entity: ObservedEntity, quality_checks: list[dict[str, Any]]
    ) -> Iterator[tuple[str, str, float]]:
        """An asset asserting good quality while its own evidence records a failure."""
        if _text(entity.get("quality_status")) not in ASSERTED_GOOD_QUALITY:
            return
        failed = [
            check for check in quality_checks if _text(check.get("status")) == QUALITY_CHECK_FAILED
        ]
        if failed:
            types = sorted({_text(check.get("check_type")) for check in failed} - {""})
            yield (
                "QC-CERTIFIED-CONTRADICTED",
                f"asset asserts quality status {_text(entity.get('quality_status'))} while "
                f"{len(failed)} quality check(s) report 'fail'"
                + (f" ({', '.join(types)})" if types else ""),
                STRUCTURAL_CONFIDENCE,
            )

    def _lineage(
        self,
        entity: ObservedEntity,
        run_ids: frozenset[str],
        downstream: frozenset[str],
    ) -> Iterator[tuple[str, str, float]]:
        """Provenance and upstream lineage must both resolve."""
        run = _text(entity.get("provenance_run_id"))
        if run and run not in run_ids:
            yield (
                "LIN-PROVENANCE-DANGLING",
                f"provenance run {run} resolves to no instrument or pipeline run",
                STRUCTURAL_CONFIDENCE,
            )
        if entity.kind == "dataset" and entity.entity_id not in downstream:
            yield (
                "LIN-DATASET-NO-UPSTREAM",
                "no lineage edge names this dataset as a downstream node",
                STRUCTURAL_CONFIDENCE,
            )

    def _intended_use(self, entity: ObservedEntity) -> Iterator[tuple[str, str, float]]:
        """Intended use must be declared, and must not contradict the classification."""
        uses = entity.get("intended_uses")
        declared = [use for use in uses if isinstance(use, str)] if isinstance(uses, list) else []
        if not declared:
            yield (
                "USE-INTENDED-USE-MISSING",
                "the asset declares no intended use",
                STRUCTURAL_CONFIDENCE,
            )
            return

        classification = _text(entity.get("access_classification"))
        external = sorted(set(declared) & EXTERNAL_USES)
        if classification in RESTRICTED_CLASSIFICATIONS and external:
            yield (
                "USE-EXTERNAL-VS-RESTRICTED",
                f"{classification} asset declares external use(s): {', '.join(external)}",
                STRUCTURAL_CONFIDENCE,
            )

    def _training(
        self, entity: ObservedEntity, approvals: list[dict[str, Any]]
    ) -> Iterator[tuple[str, str, float]]:
        """Training claims must be backed by a matching approval record."""
        status = _text(entity.get("model_training_status"))
        uses = entity.get("intended_uses")
        declared = (
            {use for use in uses if isinstance(use, str)} if isinstance(uses, list) else set()
        )

        if status and not approvals:
            yield (
                "AIR-TRAINING-APPROVAL-ABSENT",
                f"asset declares training status {status} but carries no "
                "model-training approval record",
                STRUCTURAL_CONFIDENCE,
            )

        # Sorted for the same reason as the ownership check: evidence must not
        # depend on which approval record happened to be read first.
        mismatched = sorted(
            {
                recorded
                for approval in approvals
                if status and (recorded := _text(approval.get("status"))) and recorded != status
            }
        )
        if mismatched:
            yield (
                "AIR-TRAINING-STATUS-MISMATCH",
                f"asset training status {status} disagrees with approval record "
                f"{', '.join(mismatched)}",
                STRUCTURAL_CONFIDENCE,
            )

        if declared & TRAINING_USES and status != TRAINING_APPROVED_STATUS:
            yield (
                "USE-TRAINING-WITHOUT-APPROVAL",
                f"asset declares a training use while its training status is {status or 'unset'}",
                STRUCTURAL_CONFIDENCE,
            )


__all__ = [
    "RULE_BASELINE_VERSION",
    "STRUCTURAL_CONFIDENCE",
    "RuleBasedBaseline",
]
