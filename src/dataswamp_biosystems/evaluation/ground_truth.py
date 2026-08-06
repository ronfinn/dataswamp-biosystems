"""Read an emitted observed state as the benchmark's labelled ground truth.

The evaluator *consumes* what the imperfection engine emitted; it never
re-derives it and never writes to it. Five artefacts are read:

``rule-scope.jsonl``
    The evaluation universe. For each rule, ``eligible_ids`` and
    ``control_excluded_ids`` together are the rule's population, and
    ``selected_ids`` are the entities that actually carry the defect.
``expected-findings.jsonl``
    The positive class, one record per injected defect.
``expected-remediations.jsonl``
    The expected fix (or explicit no-action decision) for each finding.
``controls.jsonl``
    Entities carrying no defect at all, and the ``reserved`` flag marking the
    held-out partition.
``profile-summary.json``
    The scenario identity (profile, seeds, generator/schema versions).
``scenarios.jsonl``
    Present only for an adversarial benchmark: the constructed cases, which say
    which pairs belong to which reasoning problem and which lookalikes are
    deliberate near misses. Read by the *evaluator*, which is privileged; never
    by an agent, which is not.

The union of every rule population is the evaluation universe; entities that
appear in no rule population are known to the benchmark but *outside* every
rule's scope, and never enter a specificity denominator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from dataswamp_biosystems.evaluation.errors import EvaluationConfigError
from dataswamp_biosystems.observed.entities import (
    ControlRecord,
    ExpectedFinding,
    ExpectedRemediation,
    RuleScopeRecord,
)
from dataswamp_biosystems.observed.scenarios import CaseType, ScenarioCase, ScenarioPolarity
from dataswamp_biosystems.observed.writer import (
    CONTROLS_NAME,
    EXPECTED_FINDINGS_NAME,
    EXPECTED_REMEDIATIONS_NAME,
    MUTATION_LOG_NAME,
    PROFILE_SUMMARY_NAME,
    RULE_SCOPE_NAME,
    SCENARIOS_NAME,
)
from dataswamp_biosystems.truth import serialize

# The artefacts whose bytes identify this ground truth, in a fixed order so the
# fingerprint never depends on directory iteration. ``scenarios.jsonl`` is part
# of the identity even where it is absent: an adversarial benchmark and an
# ordinary one are different benchmarks, and a fingerprint that could not tell
# them apart would let two incomparable results quote the same value.
GROUND_TRUTH_FILES: tuple[str, ...] = (
    CONTROLS_NAME,
    EXPECTED_FINDINGS_NAME,
    EXPECTED_REMEDIATIONS_NAME,
    PROFILE_SUMMARY_NAME,
    RULE_SCOPE_NAME,
    SCENARIOS_NAME,
)

# Artefacts a benchmark may legitimately omit. Absence is a fact about the
# scenario (no adversarial cases), not an incomplete directory.
OPTIONAL_GROUND_TRUTH_FILES: frozenset[str] = frozenset({SCENARIOS_NAME})

# Entity kinds that denote a materialized file rather than a catalogue asset.
FILE_ENTITY_KINDS: frozenset[str] = frozenset({"file"})

ENTITY_CLASS_FILE = "file"
ENTITY_CLASS_ASSET = "asset"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvaluationConfigError(f"could not read {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for offset, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise EvaluationConfigError(
                f"{path} line {offset + 1} is not valid JSON: {exc}"
            ) from exc
    return rows


def _parse[T: BaseModel](model: type[T], rows: list[dict[str, Any]], path: Path) -> list[T]:
    parsed: list[T] = []
    for offset, row in enumerate(rows):
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as exc:
            raise EvaluationConfigError(f"{path} record {offset + 1} is invalid: {exc}") from exc
    return parsed


@dataclass(frozen=True)
class GroundTruth:
    """The labelled benchmark state one submission is scored against."""

    scopes: tuple[RuleScopeRecord, ...]
    findings: tuple[ExpectedFinding, ...]
    remediations: tuple[ExpectedRemediation, ...]
    controls: tuple[ControlRecord, ...]
    meta: dict[str, Any]
    fingerprint: str
    source_dir: str
    # Entity kinds recovered from the mutation log, for the few entities that
    # are neither a control nor the primary target of a finding.
    collateral_kinds: tuple[tuple[str, str], ...] = ()
    #: Constructed adversarial cases; empty for an ordinary benchmark.
    scenarios: tuple[ScenarioCase, ...] = ()

    # -- adversarial indexes ---------------------------------------------------

    @property
    def is_adversarial(self) -> bool:
        return bool(self.scenarios)

    @property
    def case_type_by_pair(self) -> dict[tuple[str, str], str]:
        """Return ``{(entity_id, rule_id): case type}`` for every scenario pair.

        A positive case claims the pairs formed by its target and each rule it
        fires; a near miss claims the pair formed by its control and the rule it
        *mimics* — that is precisely the pair an over-eager detector will flag,
        and scoring it anywhere else would hide the mistake the case exists to
        surface.
        """
        pairs: dict[tuple[str, str], str] = {}
        for case in self.scenarios:
            for entity_id in case.target_entity_ids:
                for rule_id in case.rule_ids:
                    pairs[(entity_id, rule_id)] = case.case_type.value
        return pairs

    @property
    def near_miss_entity_ids(self) -> frozenset[str]:
        return frozenset(
            entity_id
            for case in self.scenarios
            if case.polarity is ScenarioPolarity.NEAR_MISS_CONTROL
            for entity_id in case.target_entity_ids
        )

    @property
    def scenario_positive_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (entity_id, rule_id)
            for case in self.scenarios
            if case.polarity is ScenarioPolarity.POSITIVE
            for entity_id in case.target_entity_ids
            for rule_id in case.rule_ids
        )

    @property
    def no_remediation_pairs(self) -> frozenset[tuple[str, str]]:
        """Pairs whose case requires an explicit no-action decision."""
        return frozenset(
            (entity_id, rule_id)
            for case in self.scenarios
            if case.case_type is CaseType.NO_REMEDIATION
            for entity_id in case.target_entity_ids
            for rule_id in case.rule_ids
        )

    # -- indexes --------------------------------------------------------------

    @property
    def scope_by_rule(self) -> dict[str, RuleScopeRecord]:
        return {scope.id: scope for scope in self.scopes}

    @property
    def rule_ids(self) -> frozenset[str]:
        return frozenset(scope.id for scope in self.scopes)

    @property
    def finding_by_pair(self) -> dict[tuple[str, str], ExpectedFinding]:
        return {(f.entity_id, f.rule_id): f for f in self.findings}

    @property
    def remediation_by_finding(self) -> dict[str, ExpectedRemediation]:
        return {r.finding_id: r for r in self.remediations}

    @property
    def reserved_ids(self) -> frozenset[str]:
        return frozenset(control.id for control in self.controls if control.reserved)

    @property
    def known_entities(self) -> frozenset[str]:
        """Every entity id the benchmark knows, in or out of any rule scope.

        A prediction naming an entity outside this set is a broken submission;
        a prediction naming a known entity outside a *rule's* population is a
        scoring outcome (out-of-scope), not a validation failure. That difference
        is why the set has to be generous: rejecting a whole submission is a
        judgement about the *submitter*, and it must be reserved for a prediction
        about something the benchmark genuinely never heard of.

        Collaterally-mutated entities are included for exactly that reason. They
        are neither a control (they were touched) nor the target of a finding
        (the rule's primary subject was another entity), so on a
        scenario-restricted benchmark they would otherwise fall through every
        other source and turn a reasonable prediction — the entity really does
        look odd in the observed graph — into a rejected submission.
        """
        ids: set[str] = {control.id for control in self.controls}
        ids.update(finding.entity_id for finding in self.findings)
        ids.update(entity_id for entity_id, _ in self.collateral_kinds)
        for scope in self.scopes:
            ids.update(scope.eligible_ids)
            ids.update(scope.control_excluded_ids)
        return frozenset(ids)

    def population(self, rule_id: str) -> frozenset[str]:
        """Return the entities that rule ``rule_id`` was actually able to draw from."""
        scope = self.scope_by_rule.get(rule_id)
        if scope is None:
            return frozenset()
        return frozenset(scope.eligible_ids) | frozenset(scope.control_excluded_ids)

    @property
    def entity_kinds(self) -> dict[str, str]:
        """Return ``{entity_id: entity_kind}`` for every entity in the universe.

        Controls and expected findings between them name the kind of nearly every
        entity. A handful of entities are neither — collaterally touched by a
        rule whose *primary* target was another entity, so they are not clean
        enough to be a control yet carry no finding of their own. They remain
        legitimate negatives for every *other* rule, so their kind is recovered
        from the mutation log rather than dropping them from the universe or
        filing them under an "unknown" bucket that would distort the breakdown.
        """
        kinds: dict[str, str] = dict(self.collateral_kinds)
        for control in self.controls:
            kinds[control.id] = control.entity_kind
        for finding in self.findings:
            kinds.setdefault(finding.entity_id, finding.entity_kind)
        return kinds

    def entity_kind(self, entity_id: str) -> str:
        return self.entity_kinds.get(entity_id, "unknown")

    def entity_class(self, entity_id: str) -> str:
        """Return ``file`` or ``asset`` — the coarse split the reports break out."""
        kind = self.entity_kind(entity_id)
        return ENTITY_CLASS_FILE if kind in FILE_ENTITY_KINDS else ENTITY_CLASS_ASSET

    def is_reserved(self, entity_id: str) -> bool:
        return entity_id in self.reserved_ids


def ground_truth_fingerprint(observed_dir: Path) -> str:
    """Return a SHA-256 over the ground-truth artefacts, in fixed file order.

    Identifies *which* benchmark a score belongs to. Two evaluations quoting the
    same fingerprint were scored against byte-identical ground truth.
    """
    digest_input: list[str] = []
    for name in GROUND_TRUTH_FILES:
        path = observed_dir / name
        data = path.read_bytes() if path.exists() else b""
        digest_input.append(f"{name}:{serialize.digest(data)}")
    return serialize.digest("\n".join(digest_input).encode("utf-8"))


def load_ground_truth(observed_dir: Path | str) -> GroundTruth:
    """Load an emitted observed state as ground truth, or raise :class:`EvaluationConfigError`."""
    observed_dir = Path(observed_dir)
    if not observed_dir.is_dir():
        raise EvaluationConfigError(f"no observed state directory at {observed_dir}")
    missing = [
        name
        for name in GROUND_TRUTH_FILES
        if name not in OPTIONAL_GROUND_TRUTH_FILES and not (observed_dir / name).is_file()
    ]
    if missing:
        raise EvaluationConfigError(
            f"observed state at {observed_dir} is incomplete; missing: {', '.join(sorted(missing))}"
        )

    scope_path = observed_dir / RULE_SCOPE_NAME
    finding_path = observed_dir / EXPECTED_FINDINGS_NAME
    remediation_path = observed_dir / EXPECTED_REMEDIATIONS_NAME
    control_path = observed_dir / CONTROLS_NAME

    scopes = _parse(RuleScopeRecord, _read_jsonl(scope_path), scope_path)
    findings = _parse(ExpectedFinding, _read_jsonl(finding_path), finding_path)
    remediations = _parse(ExpectedRemediation, _read_jsonl(remediation_path), remediation_path)
    controls = _parse(ControlRecord, _read_jsonl(control_path), control_path)

    summary_path = observed_dir / PROFILE_SUMMARY_NAME
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        meta = dict(summary["meta"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise EvaluationConfigError(f"could not read {summary_path}: {exc}") from exc

    # Kind lookup only — the mutation log is not part of the scoring contract and
    # is therefore absent from the fingerprint. A missing log is not an error.
    collateral: dict[str, str] = {}
    mutation_path = observed_dir / MUTATION_LOG_NAME
    if mutation_path.is_file():
        for row in _read_jsonl(mutation_path):
            entity_id = str(row.get("entity_id", ""))
            kind = str(row.get("entity_kind", ""))
            if entity_id and kind:
                collateral.setdefault(entity_id, kind)

    scenario_path = observed_dir / SCENARIOS_NAME
    scenarios = (
        _parse(ScenarioCase, _read_jsonl(scenario_path), scenario_path)
        if scenario_path.is_file()
        else []
    )

    return GroundTruth(
        scopes=tuple(sorted(scopes, key=lambda s: s.id)),
        findings=tuple(sorted(findings, key=lambda f: (f.entity_id, f.rule_id))),
        remediations=tuple(sorted(remediations, key=lambda r: r.id)),
        controls=tuple(sorted(controls, key=lambda c: c.id)),
        meta=meta,
        fingerprint=ground_truth_fingerprint(observed_dir),
        source_dir=observed_dir.as_posix(),
        collateral_kinds=tuple(sorted(collateral.items())),
        scenarios=tuple(sorted(scenarios, key=lambda case: case.id)),
    )


__all__ = [
    "GROUND_TRUTH_FILES",
    "OPTIONAL_GROUND_TRUTH_FILES",
    "FILE_ENTITY_KINDS",
    "ENTITY_CLASS_ASSET",
    "ENTITY_CLASS_FILE",
    "GroundTruth",
    "ground_truth_fingerprint",
    "load_ground_truth",
]
