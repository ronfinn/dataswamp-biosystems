"""Validate a generated observed estate against its bytes and its bookkeeping.

``validate-observed`` regenerates the observed state from the recorded profile
and defect seed and confirms it is byte-identical to what is on disk (a
determinism/integrity tripwire), then checks the ledgers hold together:
structural completeness and referential integrity across the four streams,
fidelity of every mutation's ``before`` to the truth graph, and the absence of
contradictory mutations — two mutations writing the same
``(shard, entity, field)`` path, or one entity carrying two mutually
incompatible rules.

It deliberately does **not** enforce the truth-graph invariants on the observed
graph — the observed graph is *supposed* to be broken. It validates the
bookkeeping, not the correctness of the estate.

It also independently re-checks the **control partition** — the benchmark's
negative class. The expected partition is reconstructed from the recorded
profile and defect seed and compared against the emitted ``controls.jsonl`` and
``rule-scope.jsonl``; the emitted defect and mutation ledgers are then read back
*from disk* and checked to target no control entity, and every control's record
in the observed graph is compared field-for-field against the truth graph. So a
control that is deliberately mutated, dropped, duplicated, invented, or pointed
at an unknown entity is reported as a specific, actionable control-partition
issue rather than only as an opaque byte drift.

An adversarial run adds a second, stricter partition check. Ordinary controls
keep the field-for-field truth equality above, unchanged. A **near-miss** control
— a clean entity deliberately dressed to resemble a defect — is instead held to
an itemised invariant: it must be a *reserved* control, absent from every rule's
``selected_ids``, absent from the defect and mutation ledgers, and every field
that differs from truth must be declared by a scenario transformation whose
before/after match the two graphs and whose emitted value still satisfies the
named validity predicate of the rule it mimics. A near miss that drifted into
being a real defect is therefore reported by name rather than shipping quietly in
the negative class.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from dataswamp_biosystems.company.config import CanonicalConfig
from dataswamp_biosystems.observed.defects import DEFECTS
from dataswamp_biosystems.observed.difficulty import Difficulty
from dataswamp_biosystems.observed.engine import (
    ADVERSARIAL_MIN_SCHEMA_VERSION,
    SUPPORTED_OBSERVED_SCHEMA_VERSIONS,
    ObservedResult,
    generate_observed,
    modality_group_of,
)
from dataswamp_biosystems.observed.entities import (
    NO_REMEDIATION_ACTION,
    ChangeOp,
    MutationRecord,
)
from dataswamp_biosystems.observed.errors import (
    ObservedConfigError,
    ObservedIssueCollector,
    ObservedIssueKind,
)
from dataswamp_biosystems.observed.index import GraphIndex
from dataswamp_biosystems.observed.profiles import ObservedProfile
from dataswamp_biosystems.observed.scenarios import (
    NEAR_MISS_VALIDITY_CHECKS,
    ScenarioCase,
    ScenarioTransformation,
    coverage_problems,
)
from dataswamp_biosystems.observed.writer import (
    CONTROLS_NAME,
    INJECTED_DEFECTS_NAME,
    MUTATION_LOG_NAME,
    OBSERVED_GRAPH_NAME,
    PROFILE_SUMMARY_NAME,
    RULE_SCOPE_NAME,
    SCENARIO_TRANSFORMATIONS_NAME,
    SCENARIOS_NAME,
    SUMMARY_MD_NAME,
    observed_bytes,
)
from dataswamp_biosystems.provenance import PROVENANCE_NAME
from dataswamp_biosystems.truth.graph import TruthGraph


def read_observed_meta(observed_dir: Path) -> dict[str, Any]:
    """Read the ``meta`` block from ``profile-summary.json``."""
    path = observed_dir / PROFILE_SUMMARY_NAME
    if not path.exists():
        raise ObservedConfigError(f"no profile summary at {path}")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
        meta = summary["meta"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ObservedConfigError(f"could not read observed summary {path}: {exc}") from exc
    if not isinstance(meta, dict):
        raise ObservedConfigError(f"malformed meta block in {path}")
    return meta


def read_observed_difficulty(observed_dir: Path) -> Difficulty | None:
    """Return the difficulty tier a written observed state was generated at.

    Recovered from ``provenance.json``, which is where the tier is recorded: the
    ground-truth artefacts deliberately carry no difficulty field, so that a
    mixed run's canonical bytes are exactly what they were before tiers existed.
    ``None`` — including for output written before this field existed — means the
    full rule catalogue, which is what re-generation must then use.
    """
    path = Path(observed_dir) / PROVENANCE_NAME
    if not path.exists():
        return None
    try:
        provenance = json.loads(path.read_text(encoding="utf-8"))
        recorded = provenance.get("scenario", {}).get("difficulty")
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise ObservedConfigError(f"could not read observed provenance {path}: {exc}") from exc
    if recorded is None:
        return None
    try:
        return Difficulty(str(recorded))
    except ValueError as exc:
        raise ObservedConfigError(
            f"{path} records an unknown difficulty {recorded!r}; "
            f"expected one of {', '.join(t.value for t in Difficulty)}"
        ) from exc


def _check_schema_compatibility(
    observed_dir: Path, meta: dict[str, Any], difficulty: Difficulty | None
) -> None:
    """Refuse an observed state this build cannot interpret, with a reason.

    Two separate questions, kept separate on purpose:

    * **Can this build read the directory at all?** A schema outside
      :data:`SUPPORTED_OBSERVED_SCHEMA_VERSIONS` is refused rather than guessed
      at — regenerating it against a mismatched generator would produce a
      confident, wrong drift report.
    * **Is the directory internally coherent?** Schema 3 has nowhere to put the
      scenario ledgers, so a schema-3 directory claiming ``adversarial`` is
      malformed rather than merely old. A schema-3 directory claiming nothing is
      perfectly fine and stays readable.
    """
    raw = meta.get("schema_version")
    try:
        schema_version = int(str(raw))
    except (TypeError, ValueError) as exc:
        raise ObservedConfigError(
            f"{observed_dir / PROFILE_SUMMARY_NAME} records a non-numeric schema_version {raw!r}"
        ) from exc

    if schema_version not in SUPPORTED_OBSERVED_SCHEMA_VERSIONS:
        raise ObservedConfigError(
            f"observed state at {observed_dir} declares schema version "
            f"{schema_version}, which this build cannot read; supported versions "
            f"are {sorted(SUPPORTED_OBSERVED_SCHEMA_VERSIONS)}. Regenerate the "
            "benchmark, or use a DataSwamp release that supports it"
        )
    if difficulty is Difficulty.ADVERSARIAL and schema_version < ADVERSARIAL_MIN_SCHEMA_VERSION:
        raise ObservedConfigError(
            f"observed state at {observed_dir} records difficulty 'adversarial' at "
            f"schema version {schema_version}, but adversarial output requires "
            f"schema {ADVERSARIAL_MIN_SCHEMA_VERSION}: schema {schema_version} has "
            "no scenario ledgers to carry the constructed cases, so the directory "
            "cannot be what it claims to be"
        )


def validate_observed(observed_dir: Path, graph: TruthGraph, config: CanonicalConfig) -> None:
    """Validate the observed estate under ``observed_dir`` against ``graph`` and disk.

    ``graph`` must be the truth graph the estate was derived from (same seed).
    Raises :class:`ObservedValidationError` on any problem.
    """
    observed_dir = Path(observed_dir)
    issues = ObservedIssueCollector()

    meta = read_observed_meta(observed_dir)
    profile = ObservedProfile(str(meta["profile"]))
    defect_seed = int(str(meta["defect_seed"]))
    truth_seed = int(str(meta["truth_seed"]))
    difficulty = read_observed_difficulty(observed_dir)
    _check_schema_compatibility(observed_dir, meta, difficulty)
    if graph.meta.seed != truth_seed:
        issues.add(
            ObservedIssueKind.CONSISTENCY,
            f"truth graph seed {graph.meta.seed} does not match observed truth_seed {truth_seed}",
        )

    result = generate_observed(graph, config, profile, defect_seed, difficulty)

    # Determinism/integrity tripwire: regenerated bytes must match disk.
    for name, data in observed_bytes(result).items():
        on_disk = (observed_dir / name).read_bytes() if (observed_dir / name).exists() else b""
        if on_disk != data:
            issues.add(
                ObservedIssueKind.CONSISTENCY,
                f"on-disk {name} differs from a freshly regenerated file (drift)",
                entity_kind=name,
            )
    md_path = observed_dir / SUMMARY_MD_NAME
    if not md_path.exists():
        issues.add(ObservedIssueKind.CONSISTENCY, f"missing {SUMMARY_MD_NAME}")

    index = GraphIndex(graph, config)
    _check_structural(result, issues)
    _check_fidelity(result, index, issues)
    _check_contamination(result, issues)
    _check_controls(observed_dir, result, index, issues)
    _check_rule_contracts(result, index, issues)

    issues.raise_if_any()


def _contract_issue(
    issues: ObservedIssueCollector,
    *,
    kind: str,
    entity_id: str,
    rule_id: str,
    field: str,
    declared: object,
    generated: object,
) -> None:
    """Report generated evidence that contradicts its rule's declaration."""
    issues.add(
        ObservedIssueKind.RULE_CONTRACT,
        f"rule {rule_id!r} declares {field}={declared!r} "
        f"but the generated record has {generated!r}",
        entity_kind=kind,
        entity_id=entity_id,
        field=field,
    )


def _check_rule_contracts(
    result: ObservedResult, index: GraphIndex, issues: ObservedIssueCollector
) -> None:
    """Prove every generated record agrees with its rule's declared contract.

    Rule metadata is only a contract if the evidence is checked against it. This
    verifies the two dimensions independently — remediation availability and
    approval policy — so neither can be silently inferred from the other, and
    that a non-remediable finding carries an explicit no-action decision rather
    than a hollow fix.

    It also enforces *applicability* against the population each rule actually
    selected: a modality-specific rule that reaches an unrelated modality is a
    silently mis-scoped benchmark, not a harmless extra defect.
    """
    for instance in result.instances:
        definition = DEFECTS.get(instance.rule_id)
        if definition is None:
            continue  # already reported as an unknown rule
        if instance.remediation_availability is not definition.remediation_availability:
            _contract_issue(
                issues,
                kind="instance",
                entity_id=instance.id,
                rule_id=instance.rule_id,
                field="remediation_availability",
                declared=definition.remediation_availability.value,
                generated=instance.remediation_availability.value,
            )
        if instance.approval_policy is not definition.approval_policy:
            _contract_issue(
                issues,
                kind="instance",
                entity_id=instance.id,
                rule_id=instance.rule_id,
                field="approval_policy",
                declared=definition.approval_policy.value,
                generated=instance.approval_policy.value,
            )
        if instance.approver_role is not definition.approver_role:
            _contract_issue(
                issues,
                kind="instance",
                entity_id=instance.id,
                rule_id=instance.rule_id,
                field="approver_role",
                declared=definition.approver_role.value,
                generated=instance.approver_role.value,
            )
        if instance.category is not definition.category:
            _contract_issue(
                issues,
                kind="instance",
                entity_id=instance.id,
                rule_id=instance.rule_id,
                field="category",
                declared=definition.category.value,
                generated=instance.category.value,
            )
        if instance.severity is not definition.default_severity:
            _contract_issue(
                issues,
                kind="instance",
                entity_id=instance.id,
                rule_id=instance.rule_id,
                field="severity",
                declared=definition.default_severity.value,
                generated=instance.severity.value,
            )
        if instance.entity_kind not in definition.applies_to_kinds:
            issues.add(
                ObservedIssueKind.RULE_CONTRACT,
                f"rule {instance.rule_id!r} applies to "
                f"{sorted(definition.applies_to_kinds)} but was applied to a "
                f"{instance.entity_kind!r}",
                entity_kind="instance",
                entity_id=instance.id,
                field="entity_kind",
            )
        declared_modalities = set(definition.applies_to_modalities)
        if "*" not in declared_modalities:
            group = modality_group_of(index, instance.entity_id)
            if group not in declared_modalities:
                issues.add(
                    ObservedIssueKind.RULE_CONTRACT,
                    f"rule {instance.rule_id!r} applies to modality group(s) "
                    f"{sorted(declared_modalities)} but was applied to entity "
                    f"{instance.entity_id!r} in group {group!r}",
                    entity_kind="instance",
                    entity_id=instance.id,
                    field="applies_to_modalities",
                )

    for mutation in result.mutations:
        definition = DEFECTS.get(mutation.rule_id)
        if definition is None:
            continue
        if mutation.operation not in definition.mutation_ops:
            _contract_issue(
                issues,
                kind="mutation",
                entity_id=mutation.id,
                rule_id=mutation.rule_id,
                field="mutation_ops",
                declared=[op.value for op in definition.mutation_ops],
                generated=mutation.operation.value,
            )
        if mutation.auto_fixable != definition.auto_fixable:
            _contract_issue(
                issues,
                kind="mutation",
                entity_id=mutation.id,
                rule_id=mutation.rule_id,
                field="auto_fixable",
                declared=definition.auto_fixable,
                generated=mutation.auto_fixable,
            )
        if mutation.requires_human_approval != definition.requires_human_approval:
            _contract_issue(
                issues,
                kind="mutation",
                entity_id=mutation.id,
                rule_id=mutation.rule_id,
                field="requires_human_approval",
                declared=definition.requires_human_approval,
                generated=mutation.requires_human_approval,
            )

    for finding in result.findings:
        definition = DEFECTS.get(finding.rule_id)
        if definition is None:
            continue
        if finding.remediation_available is not definition.remediation_availability:
            _contract_issue(
                issues,
                kind="finding",
                entity_id=finding.id,
                rule_id=finding.rule_id,
                field="remediation_available",
                declared=definition.remediation_availability.value,
                generated=finding.remediation_available.value,
            )
        if finding.non_remediable_reason is not definition.non_remediable_reason:
            _contract_issue(
                issues,
                kind="finding",
                entity_id=finding.id,
                rule_id=finding.rule_id,
                field="non_remediable_reason",
                declared=definition.non_remediable_reason.value,
                generated=finding.non_remediable_reason.value,
            )
        if finding.category is not definition.category:
            _contract_issue(
                issues,
                kind="finding",
                entity_id=finding.id,
                rule_id=finding.rule_id,
                field="category",
                declared=definition.category.value,
                generated=finding.category.value,
            )
        if finding.severity is not definition.default_severity:
            _contract_issue(
                issues,
                kind="finding",
                entity_id=finding.id,
                rule_id=finding.rule_id,
                field="severity",
                declared=definition.default_severity.value,
                generated=finding.severity.value,
            )

    _check_remediation_contracts(result, issues)


def _check_remediation_contracts(result: ObservedResult, issues: ObservedIssueCollector) -> None:
    """Check remediation records, including the explicit no-action decisions."""
    per_finding: dict[str, int] = {}
    for remediation in result.remediations:
        per_finding[remediation.finding_id] = per_finding.get(remediation.finding_id, 0) + 1
        definition = DEFECTS.get(remediation.rule_id)
        if definition is None:
            continue

        for field_name, declared, generated in (
            ("availability", definition.remediation_availability, remediation.availability),
            ("approval_policy", definition.approval_policy, remediation.approval_policy),
            ("approver_role", definition.approver_role, remediation.approver_role),
            ("approval_evidence", definition.approval_evidence, remediation.approval_evidence),
            (
                "non_remediable_reason",
                definition.non_remediable_reason,
                remediation.non_remediable_reason,
            ),
        ):
            if declared is not generated:
                _contract_issue(
                    issues,
                    kind="remediation",
                    entity_id=remediation.id,
                    rule_id=remediation.rule_id,
                    field=field_name,
                    declared=declared.value,
                    generated=generated.value,
                )

        if remediation.auto_fixable != definition.auto_fixable:
            _contract_issue(
                issues,
                kind="remediation",
                entity_id=remediation.id,
                rule_id=remediation.rule_id,
                field="auto_fixable",
                declared=definition.auto_fixable,
                generated=remediation.auto_fixable,
            )
        if remediation.requires_human_approval != definition.requires_human_approval:
            _contract_issue(
                issues,
                kind="remediation",
                entity_id=remediation.id,
                rule_id=remediation.rule_id,
                field="requires_human_approval",
                declared=definition.requires_human_approval,
                generated=remediation.requires_human_approval,
            )

        # A non-remediable finding must carry an explicit no-action decision, and
        # must never carry an actionable repair instruction.
        if definition.is_remediable:
            if remediation.action == NO_REMEDIATION_ACTION:
                issues.add(
                    ObservedIssueKind.RULE_CONTRACT,
                    f"rule {remediation.rule_id!r} is remediable but the record "
                    "declares no remediation",
                    entity_kind="remediation",
                    entity_id=remediation.id,
                    field="action",
                )
            if remediation.action != definition.remediation_action:
                _contract_issue(
                    issues,
                    kind="remediation",
                    entity_id=remediation.id,
                    rule_id=remediation.rule_id,
                    field="action",
                    declared=definition.remediation_action,
                    generated=remediation.action,
                )
        else:
            if remediation.action != NO_REMEDIATION_ACTION:
                _contract_issue(
                    issues,
                    kind="remediation",
                    entity_id=remediation.id,
                    rule_id=remediation.rule_id,
                    field="action",
                    declared=NO_REMEDIATION_ACTION,
                    generated=remediation.action,
                )
            if remediation.recommended_value is not None:
                issues.add(
                    ObservedIssueKind.RULE_CONTRACT,
                    f"rule {remediation.rule_id!r} is non-remediable but the record "
                    f"recommends {remediation.recommended_value!r}",
                    entity_kind="remediation",
                    entity_id=remediation.id,
                    field="recommended_value",
                )
        if remediation.action_class != definition.action_class:
            _contract_issue(
                issues,
                kind="remediation",
                entity_id=remediation.id,
                rule_id=remediation.rule_id,
                field="action_class",
                declared=definition.action_class,
                generated=remediation.action_class,
            )

    # Contradictory evidence: a finding must resolve to exactly one decision.
    for finding in result.findings:
        count = per_finding.get(finding.id, 0)
        if count != 1:
            issues.add(
                ObservedIssueKind.RULE_CONTRACT,
                f"finding has {count} remediation record(s); exactly one is required "
                "(a non-remediable finding carries an explicit no-action decision)",
                entity_kind="finding",
                entity_id=finding.id,
                field="remediation_id",
            )


def _read_jsonl(
    observed_dir: Path, name: str, issues: ObservedIssueCollector
) -> list[dict[str, Any]] | None:
    """Read one emitted JSONL ledger from disk, or report why it is unusable."""
    path = observed_dir / name
    if not path.exists():
        issues.add(ObservedIssueKind.CONSISTENCY, f"missing {name}", entity_kind=name)
        return None
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.add(
                ObservedIssueKind.CONSISTENCY,
                f"{name} line {number} is not valid JSON: {exc}",
                entity_kind=name,
            )
            return None
        if not isinstance(row, dict):
            issues.add(
                ObservedIssueKind.CONSISTENCY,
                f"{name} line {number} is not a JSON object",
                entity_kind=name,
            )
            return None
        rows.append(row)
    return rows


def _check_controls(
    observed_dir: Path,
    result: ObservedResult,
    index: GraphIndex,
    issues: ObservedIssueCollector,
) -> None:
    """Re-derive the control partition and prove the emitted ledgers respect it."""
    control_rows = _read_jsonl(observed_dir, CONTROLS_NAME, issues)
    if control_rows is None:
        return

    known_entities = set(index.asset_ids()) | set(index.file_ids())
    expected = {control.id: control.model_dump(mode="json") for control in result.controls}

    on_disk: dict[str, dict[str, Any]] = {}
    for row in control_rows:
        control_id = str(row.get("id", ""))
        if control_id in on_disk:
            issues.add(
                ObservedIssueKind.DUPLICATE_ID,
                f"duplicate control id {control_id!r}",
                entity_kind="control",
                entity_id=control_id,
            )
            continue
        on_disk[control_id] = row
        if control_id not in known_entities:
            issues.add(
                ObservedIssueKind.UNRESOLVED_REFERENCE,
                f"control {control_id!r} does not resolve to any truth asset or file",
                entity_kind="control",
                entity_id=control_id,
            )

    for control_id in sorted(set(expected) - set(on_disk)):
        issues.add(
            ObservedIssueKind.CONTROL_PARTITION,
            "entity belongs to the expected control partition but is not emitted",
            entity_kind="control",
            entity_id=control_id,
        )
    for control_id in sorted(set(on_disk) - set(expected)):
        issues.add(
            ObservedIssueKind.CONTROL_PARTITION,
            "emitted control is not in the expected control partition",
            entity_kind="control",
            entity_id=control_id,
        )
    for control_id in sorted(set(on_disk) & set(expected)):
        # Compare every field, not a chosen subset, so no attribute of a control
        # record can drift without being named in the report.
        for key in sorted(set(expected[control_id]) | set(on_disk[control_id])):
            if on_disk[control_id].get(key) != expected[control_id].get(key):
                issues.add(
                    ObservedIssueKind.CONTROL_PARTITION,
                    f"control {key} is {on_disk[control_id].get(key)!r}, "
                    f"expected {expected[control_id].get(key)!r}",
                    entity_kind="control",
                    entity_id=control_id,
                    field=key,
                )

    reserved_ids = {
        control_id for control_id, row in on_disk.items() if row.get("reserved") is True
    }
    # Read back from disk, exactly as the control partition is: a validator that
    # only inspected the regenerated result would prove the generator consistent
    # with itself and say nothing about the bytes anyone will actually consume.
    emitted_cases = _read_models(
        observed_dir, SCENARIOS_NAME, ScenarioCase, result.scenarios, issues
    )
    emitted_transformations = _read_models(
        observed_dir,
        SCENARIO_TRANSFORMATIONS_NAME,
        ScenarioTransformation,
        result.transformations,
        issues,
    )

    by_entity: dict[str, list[ScenarioTransformation]] = {}
    for record in emitted_transformations:
        by_entity.setdefault(record.entity_id, []).append(record)
    _check_controls_untargeted(observed_dir, set(on_disk), issues)
    _check_controls_unchanged(observed_dir, set(on_disk), index, issues, by_entity)
    _check_rule_scope(observed_dir, result, set(on_disk), reserved_ids, issues)
    _check_scenarios(
        result, emitted_cases, emitted_transformations, index, set(on_disk), reserved_ids, issues
    )


def _read_models[T: BaseModel](
    observed_dir: Path,
    name: str,
    model: type[T],
    expected: Sequence[T],
    issues: ObservedIssueCollector,
) -> list[T]:
    """Parse one emitted scenario ledger from disk, or report why it is unusable.

    An absent file is only an error when the run was supposed to produce one:
    an ordinary benchmark emits no scenario ledgers at all, and demanding an empty
    file from it would be demanding a byte change nothing needs.
    """
    path = observed_dir / name
    if not path.exists():
        if expected:
            issues.add(
                ObservedIssueKind.SCENARIO,
                f"missing {name}, but this run constructed {len(expected)} scenario record(s)",
                entity_kind=name,
            )
        return []
    rows = _read_jsonl(observed_dir, name, issues)
    if rows is None:
        return []
    parsed: list[T] = []
    for number, row in enumerate(rows, start=1):
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as exc:
            issues.add(
                ObservedIssueKind.SCENARIO,
                f"{name} record {number} is invalid: {exc}",
                entity_kind=name,
            )
    return parsed


def _check_scenarios(
    result: ObservedResult,
    cases: Sequence[ScenarioCase],
    transformations: Sequence[ScenarioTransformation],
    index: GraphIndex,
    control_ids: set[str],
    reserved_ids: set[str],
    issues: ObservedIssueCollector,
) -> None:
    """Check the scenario ledger against the partitions it claims to sit in.

    Two failure modes matter and are checked separately. A **near-miss** case
    whose entity is not a reserved control, or which has leaked into a rule's
    selection or into the defect ledger, is a positive masquerading as a negative
    — the single worst thing that can happen to this benchmark, because it makes
    a correct agent look wrong. A **positive** case that names no finding, or
    names one that does not exist, is an answer key describing a construction the
    observed graph does not contain.
    """
    if not cases and not transformations and not result.scenarios:
        return

    # The emitted ledger must be the one the generator produced. Checked as a set
    # comparison rather than only through the byte tripwire so a specific record
    # is named, not just "this file drifted".
    expected_cases = {case.id: case.model_dump(mode="json") for case in result.scenarios}
    emitted = {case.id: case.model_dump(mode="json") for case in cases}
    for case_id in sorted(set(expected_cases) - set(emitted)):
        issues.add(
            ObservedIssueKind.SCENARIO,
            "scenario was constructed but is not emitted",
            entity_kind="scenario",
            entity_id=case_id,
        )
    for case_id in sorted(set(emitted) - set(expected_cases)):
        issues.add(
            ObservedIssueKind.SCENARIO,
            "emitted scenario was not constructed by this run",
            entity_kind="scenario",
            entity_id=case_id,
        )

    finding_ids = {finding.id for finding in result.findings}
    instance_entities = {instance.entity_id for instance in result.instances}
    mutation_entities = {mutation.entity_id for mutation in result.mutations}
    selected: set[str] = set()
    for scope in result.rule_scopes:
        selected.update(scope.selected_ids)

    _check_unique([case.id for case in cases], "scenario", issues)
    _check_unique([record.id for record in transformations], "transformation", issues)

    scenario_ids = {case.id for case in cases}
    for record in transformations:
        if record.scenario_id not in scenario_ids:
            issues.add(
                ObservedIssueKind.UNRESOLVED_REFERENCE,
                f"transformation references unknown scenario {record.scenario_id!r}",
                entity_kind="transformation",
                entity_id=record.id,
            )

    # Evidence is resolved against *truth*, not the observed graph: for some rules
    # the defect is precisely that the evidence record is gone.
    truth_ids = {
        str(row["id"])
        for records in index.truth.values()
        for row in records
        if isinstance(row, dict) and "id" in row
    }

    known_transformations = {record.id for record in transformations}
    for case in cases:
        for evidence_id in sorted(case.evidence_entity_ids):
            if evidence_id not in truth_ids:
                issues.add(
                    ObservedIssueKind.UNRESOLVED_REFERENCE,
                    f"scenario names evidence {evidence_id!r} that resolves to no truth record",
                    entity_kind="scenario",
                    entity_id=case.id,
                )
        for transformation_ref in case.transformation_ids:
            if transformation_ref not in known_transformations:
                issues.add(
                    ObservedIssueKind.UNRESOLVED_REFERENCE,
                    f"scenario references unknown transformation {transformation_ref!r}",
                    entity_kind="scenario",
                    entity_id=case.id,
                )
        if case.is_near_miss:
            _check_near_miss_case(
                case,
                control_ids,
                reserved_ids,
                selected,
                instance_entities,
                mutation_entities,
                issues,
            )
            continue
        if not case.finding_ids:
            issues.add(
                ObservedIssueKind.SCENARIO,
                "positive scenario names no expected finding, so nothing it claims can be scored",
                entity_kind="scenario",
                entity_id=case.id,
            )
        for finding_ref in sorted(case.finding_ids):
            if finding_ref not in finding_ids:
                issues.add(
                    ObservedIssueKind.UNRESOLVED_REFERENCE,
                    f"scenario references unknown finding {finding_ref!r}",
                    entity_kind="scenario",
                    entity_id=case.id,
                )
        for entity_id in sorted(case.target_entity_ids):
            if entity_id in control_ids:
                issues.add(
                    ObservedIssueKind.CONTAMINATION,
                    f"positive scenario targets control entity {entity_id!r}; a case "
                    "cannot be both the positive class and the negative class",
                    entity_kind="scenario",
                    entity_id=case.id,
                )
        for entity_id in sorted(case.decoy_entity_ids):
            if entity_id not in reserved_ids:
                issues.add(
                    ObservedIssueKind.SCENARIO,
                    f"decoy {entity_id!r} is not a reserved control; a decoy must be an "
                    "entity no rule could have drawn, or naming it in the answer key "
                    "is a hint about a genuine candidate",
                    entity_kind="scenario",
                    entity_id=case.id,
                )

    coverage = result.summary.get("scenarios")
    if coverage is not None:
        for problem in coverage_problems(coverage):
            issues.add(ObservedIssueKind.SCENARIO, problem, entity_kind="coverage")


def _check_near_miss_case(
    case: ScenarioCase,
    control_ids: set[str],
    reserved_ids: set[str],
    selected: set[str],
    instance_entities: set[str],
    mutation_entities: set[str],
    issues: ObservedIssueCollector,
) -> None:
    """Prove a near-miss case sits wholly outside every positive partition."""
    for entity_id in sorted(case.target_entity_ids):
        if entity_id not in control_ids:
            issues.add(
                ObservedIssueKind.NEAR_MISS,
                f"near-miss entity {entity_id!r} is not in the control partition",
                entity_kind="scenario",
                entity_id=case.id,
            )
        if entity_id not in reserved_ids:
            issues.add(
                ObservedIssueKind.NEAR_MISS,
                f"near-miss entity {entity_id!r} is not a *reserved* control; a near "
                "miss must be held out of every rule's eligible population before "
                "selection, so that no rule could have drawn it even in principle",
                entity_kind="scenario",
                entity_id=case.id,
            )
        if entity_id in selected:
            issues.add(
                ObservedIssueKind.CONTAMINATION,
                f"near-miss entity {entity_id!r} appears in a rule's selected_ids",
                entity_kind="scenario",
                entity_id=case.id,
            )
        if entity_id in instance_entities:
            issues.add(
                ObservedIssueKind.CONTAMINATION,
                f"near-miss entity {entity_id!r} is the target of a defect instance",
                entity_kind="scenario",
                entity_id=case.id,
            )
        if entity_id in mutation_entities:
            issues.add(
                ObservedIssueKind.CONTAMINATION,
                f"near-miss entity {entity_id!r} is the target of a defect mutation; a "
                "near miss must be recorded as a scenario transformation, never as an "
                "entry in the defect mutation ledger",
                entity_kind="scenario",
                entity_id=case.id,
            )
    if case.finding_ids:
        issues.add(
            ObservedIssueKind.NEAR_MISS,
            "near-miss case names an expected finding; a near miss carries no finding "
            "and every flag against it is a false positive",
            entity_kind="scenario",
            entity_id=case.id,
        )
    if not case.transformation_ids:
        issues.add(
            ObservedIssueKind.NEAR_MISS,
            "near-miss case declares no transformation, so nothing distinguishes it "
            "from an ordinary control",
            entity_kind="scenario",
            entity_id=case.id,
        )


def _check_controls_untargeted(
    observed_dir: Path, control_ids: set[str], issues: ObservedIssueCollector
) -> None:
    """No emitted defect instance or mutation may target a control entity."""
    for name, kind in ((INJECTED_DEFECTS_NAME, "instance"), (MUTATION_LOG_NAME, "mutation")):
        rows = _read_jsonl(observed_dir, name, issues)
        if rows is None:
            continue
        for row in rows:
            entity_id = str(row.get("entity_id", ""))
            if entity_id in control_ids:
                issues.add(
                    ObservedIssueKind.CONTAMINATION,
                    f"{kind} {str(row.get('id', ''))!r} targets control entity {entity_id!r}",
                    entity_kind=kind,
                    entity_id=entity_id,
                )


def _check_controls_unchanged(
    observed_dir: Path,
    control_ids: set[str],
    index: GraphIndex,
    issues: ObservedIssueCollector,
    transformations: dict[str, list[ScenarioTransformation]] | None = None,
) -> None:
    """Every control's observed record must equal its truth record, field for field.

    The observed graph holds canonical JSON objects, so equality here is the
    strongest available evidence that a control survived injection untouched: it
    is the record-level equivalent of byte identity, and unlike a whole-file
    digest it names the individual control that drifted.

    A **near-miss** control is the one deliberate exception, and it is not a
    weakening of the rule above: the equality check is replaced, for that entity
    only, by a stricter itemised one. Every differing field must be declared by a
    scenario transformation, that transformation's ``before`` must be the truth
    value and its ``after`` the observed value, and the observed record must still
    satisfy the named validity predicate of the rule it mimics. Any field that
    differs without a declaration is reported exactly as an undeclared mutation of
    a control would be. Ordinary controls — every control not named by a
    transformation — keep field-for-field truth equality untouched.
    """
    path = observed_dir / OBSERVED_GRAPH_NAME
    if not path.exists():
        issues.add(ObservedIssueKind.CONSISTENCY, f"missing {OBSERVED_GRAPH_NAME}")
        return
    try:
        observed_graph = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.add(
            ObservedIssueKind.CONSISTENCY,
            f"{OBSERVED_GRAPH_NAME} is not valid JSON: {exc}",
            entity_kind=OBSERVED_GRAPH_NAME,
        )
        return

    by_id: dict[str, dict[str, Any]] = {}
    for shard, records in observed_graph.items():
        if shard == "meta" or not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and "id" in record:
                by_id[str(record["id"])] = record

    declared = transformations or {}
    for control_id in sorted(control_ids):
        truth_record = index.truth_record("files", control_id) or index.asset(control_id)
        if truth_record is None:
            continue  # already reported as an unresolved control reference
        observed_record = by_id.get(control_id)
        if observed_record is None:
            issues.add(
                ObservedIssueKind.CONTROL_PARTITION,
                "control entity is missing from the observed graph",
                entity_kind="control",
                entity_id=control_id,
            )
            continue
        changed = sorted(
            key
            for key in set(observed_record) | set(truth_record)
            if observed_record.get(key) != truth_record.get(key)
        )
        if control_id in declared:
            _check_near_miss(
                control_id, truth_record, observed_record, changed, declared[control_id], issues
            )
        elif changed:
            issues.add(
                ObservedIssueKind.CONTROL_PARTITION,
                f"control entity differs from truth in the observed graph: {changed}",
                entity_kind="control",
                entity_id=control_id,
                field=changed[0],
            )


def _check_near_miss(
    control_id: str,
    truth_record: dict[str, Any],
    observed_record: dict[str, Any],
    changed: list[str],
    records: list[ScenarioTransformation],
    issues: ObservedIssueCollector,
) -> None:
    """Prove one near-miss control is still clean, field by declared field."""
    by_field = {record.field: record for record in records}
    scenario_ids = sorted({record.scenario_id for record in records})
    scenario_label = ", ".join(scenario_ids)

    for field_name in changed:
        record = by_field.get(field_name)
        if record is None:
            issues.add(
                ObservedIssueKind.NEAR_MISS,
                f"near-miss control (scenario {scenario_label}) changed undeclared field "
                f"{field_name!r}; every field a near miss touches must be declared as a "
                "scenario transformation",
                entity_kind="near-miss-control",
                entity_id=control_id,
                field=field_name,
            )
            continue
        if record.before != truth_record.get(field_name):
            issues.add(
                ObservedIssueKind.NEAR_MISS,
                f"scenario {record.scenario_id} declares before={record.before!r} for "
                f"{field_name!r} but the truth graph holds "
                f"{truth_record.get(field_name)!r}",
                entity_kind="near-miss-control",
                entity_id=control_id,
                field=field_name,
            )
        if record.after != observed_record.get(field_name):
            issues.add(
                ObservedIssueKind.NEAR_MISS,
                f"scenario {record.scenario_id} declares after={record.after!r} for "
                f"{field_name!r} but the observed graph holds "
                f"{observed_record.get(field_name)!r}",
                entity_kind="near-miss-control",
                entity_id=control_id,
                field=field_name,
            )

    for field_name, record in sorted(by_field.items()):
        if field_name not in changed:
            issues.add(
                ObservedIssueKind.NEAR_MISS,
                f"scenario {record.scenario_id} declares a transformation of "
                f"{field_name!r} that the observed graph does not contain; a declared "
                "near miss that changed nothing is an empty claim in the answer key",
                entity_kind="near-miss-control",
                entity_id=control_id,
                field=field_name,
            )
        # The claim that makes this a near miss rather than a defect: the emitted
        # record must still be on the valid side of the rule it resembles. Checked
        # by re-running the named predicate against the *observed* record, so the
        # proof comes from the emitted bytes and not from the generator's word.
        check = NEAR_MISS_VALIDITY_CHECKS.get(record.validity_check)
        if check is None:
            issues.add(
                ObservedIssueKind.NEAR_MISS,
                f"scenario {record.scenario_id} names unknown validity check "
                f"{record.validity_check!r}, so its claim to be a near miss rather "
                "than a defect cannot be verified",
                entity_kind="near-miss-control",
                entity_id=control_id,
                field=field_name,
            )
        elif not check(observed_record):
            issues.add(
                ObservedIssueKind.NEAR_MISS,
                f"near-miss control (scenario {record.scenario_id}) no longer satisfies "
                f"{record.validity_condition!r}, so it would genuinely trigger "
                f"{record.mimicked_rule_id!r}: this is an undeclared defect sitting in "
                "the control partition, not a near miss",
                entity_kind="near-miss-control",
                entity_id=control_id,
                field=field_name,
            )


def _check_rule_scope(
    observed_dir: Path,
    result: ObservedResult,
    control_ids: set[str],
    reserved_ids: set[str],
    issues: ObservedIssueCollector,
) -> None:
    """Check the per-rule selection scope against the rules and the control partition.

    Note the asymmetry: a *reserved* control may never appear in a rule's
    eligible population, but a non-reserved control legitimately may — that is
    precisely an entity that was exposed to selection and not drawn.
    """
    rows = _read_jsonl(observed_dir, RULE_SCOPE_NAME, issues)
    if rows is None:
        return

    expected = {scope.id: scope for scope in result.rule_scopes}
    seen: set[str] = set()
    for row in rows:
        rule_id = str(row.get("id", ""))
        if rule_id in seen:
            issues.add(
                ObservedIssueKind.DUPLICATE_ID,
                f"duplicate rule-scope record for {rule_id!r}",
                entity_kind="rule-scope",
                entity_id=rule_id,
            )
            continue
        seen.add(rule_id)
        if rule_id not in DEFECTS:
            issues.add(
                ObservedIssueKind.UNKNOWN_RULE,
                f"rule-scope references unknown rule {rule_id!r}",
                entity_kind="rule-scope",
                entity_id=rule_id,
            )
            continue

        eligible = [str(value) for value in row.get("eligible_ids", [])]
        excluded = [str(value) for value in row.get("control_excluded_ids", [])]
        selected = [str(value) for value in row.get("selected_ids", [])]

        for label, ids, count_key in (
            ("eligible", eligible, "eligible_count"),
            ("control_excluded", excluded, "control_excluded_count"),
            ("selected", selected, "selected_count"),
        ):
            if row.get(count_key) != len(ids):
                issues.add(
                    ObservedIssueKind.CONTROL_PARTITION,
                    f"rule-scope {count_key} is {row.get(count_key)!r} "
                    f"but {len(ids)} {label} ids are listed",
                    entity_kind="rule-scope",
                    entity_id=rule_id,
                    field=count_key,
                )

        if set(eligible) & set(excluded):
            issues.add(
                ObservedIssueKind.CONTROL_PARTITION,
                f"rule-scope lists {sorted(set(eligible) & set(excluded))} as both "
                "eligible and control-excluded",
                entity_kind="rule-scope",
                entity_id=rule_id,
            )
        reserved_eligible = sorted(set(eligible) & reserved_ids)
        if reserved_eligible:
            issues.add(
                ObservedIssueKind.CONTROL_PARTITION,
                f"rule-scope lists reserved control entities {reserved_eligible} as eligible",
                entity_kind="rule-scope",
                entity_id=rule_id,
            )
        if not set(selected) <= set(eligible):
            issues.add(
                ObservedIssueKind.CONTROL_PARTITION,
                f"rule-scope selected entities {sorted(set(selected) - set(eligible))} "
                "that are not in its eligible population",
                entity_kind="rule-scope",
                entity_id=rule_id,
            )
        if set(selected) & control_ids:
            issues.add(
                ObservedIssueKind.CONTAMINATION,
                f"rule-scope selected control entities {sorted(set(selected) & control_ids)}",
                entity_kind="rule-scope",
                entity_id=rule_id,
            )

        scope = expected.get(rule_id)
        if scope is not None and sorted(selected) != scope.selected_ids:
            issues.add(
                ObservedIssueKind.CONTROL_PARTITION,
                "rule-scope selected ids differ from the expected selection",
                entity_kind="rule-scope",
                entity_id=rule_id,
                field="selected_ids",
            )

    for rule_id in sorted(set(expected) - seen):
        issues.add(
            ObservedIssueKind.CONTROL_PARTITION,
            "rule has no emitted rule-scope record",
            entity_kind="rule-scope",
            entity_id=rule_id,
        )


def _check_structural(result: ObservedResult, issues: ObservedIssueCollector) -> None:
    instance_ids = {i.id for i in result.instances}
    finding_ids = {f.id for f in result.findings}
    mutation_ids = {m.id for m in result.mutations}
    remediation_ids = {r.id for r in result.remediations}

    _check_unique([i.id for i in result.instances], "instance", issues)
    _check_unique([m.id for m in result.mutations], "mutation", issues)
    _check_unique([f.id for f in result.findings], "finding", issues)
    _check_unique([r.id for r in result.remediations], "remediation", issues)

    muts_by_instance: dict[str, int] = {}
    for mutation in result.mutations:
        muts_by_instance[mutation.instance_id] = muts_by_instance.get(mutation.instance_id, 0) + 1
        if mutation.instance_id not in instance_ids:
            issues.add(
                ObservedIssueKind.UNRESOLVED_REFERENCE,
                f"mutation references unknown instance {mutation.instance_id!r}",
                entity_kind="mutation",
                entity_id=mutation.id,
            )
        if mutation.rule_id not in DEFECTS:
            issues.add(
                ObservedIssueKind.UNKNOWN_RULE,
                f"mutation references unknown rule {mutation.rule_id!r}",
                entity_kind="mutation",
                entity_id=mutation.id,
            )

    findings_by_instance: dict[str, int] = {}
    for finding in result.findings:
        findings_by_instance[finding.instance_id] = (
            findings_by_instance.get(finding.instance_id, 0) + 1
        )
        if finding.instance_id not in instance_ids:
            issues.add(
                ObservedIssueKind.UNRESOLVED_REFERENCE,
                f"finding references unknown instance {finding.instance_id!r}",
                entity_kind="finding",
                entity_id=finding.id,
            )
        if finding.remediation_id not in remediation_ids:
            issues.add(
                ObservedIssueKind.UNRESOLVED_REFERENCE,
                f"finding references unknown remediation {finding.remediation_id!r}",
                entity_kind="finding",
                entity_id=finding.id,
            )

    for remediation in result.remediations:
        if remediation.instance_id not in instance_ids:
            issues.add(
                ObservedIssueKind.UNRESOLVED_REFERENCE,
                f"remediation references unknown instance {remediation.instance_id!r}",
                entity_kind="remediation",
                entity_id=remediation.id,
            )
        if remediation.finding_id not in finding_ids:
            issues.add(
                ObservedIssueKind.UNRESOLVED_REFERENCE,
                f"remediation references unknown finding {remediation.finding_id!r}",
                entity_kind="remediation",
                entity_id=remediation.id,
            )

    remediations_by_instance: dict[str, int] = {}
    for remediation in result.remediations:
        remediations_by_instance[remediation.instance_id] = (
            remediations_by_instance.get(remediation.instance_id, 0) + 1
        )

    for instance in result.instances:
        if muts_by_instance.get(instance.id, 0) < 1:
            issues.add(
                ObservedIssueKind.LEDGER,
                "instance has no mutation records",
                entity_kind="instance",
                entity_id=instance.id,
            )
        if findings_by_instance.get(instance.id, 0) != 1:
            issues.add(
                ObservedIssueKind.LEDGER,
                "instance must have exactly one finding",
                entity_kind="instance",
                entity_id=instance.id,
            )
        if remediations_by_instance.get(instance.id, 0) < 1:
            issues.add(
                ObservedIssueKind.LEDGER,
                "instance has no remediation records",
                entity_kind="instance",
                entity_id=instance.id,
            )
        if instance.rule_id not in DEFECTS:
            issues.add(
                ObservedIssueKind.UNKNOWN_RULE,
                f"instance references unknown rule {instance.rule_id!r}",
                entity_kind="instance",
                entity_id=instance.id,
            )
        for mutation_id in instance.mutation_ids:
            if mutation_id not in mutation_ids:
                issues.add(
                    ObservedIssueKind.UNRESOLVED_REFERENCE,
                    f"instance references unknown mutation {mutation_id!r}",
                    entity_kind="instance",
                    entity_id=instance.id,
                )
        if instance.finding_id not in finding_ids:
            issues.add(
                ObservedIssueKind.UNRESOLVED_REFERENCE,
                f"instance references unknown finding {instance.finding_id!r}",
                entity_kind="instance",
                entity_id=instance.id,
            )
        for remediation_id in instance.remediation_ids:
            if remediation_id not in remediation_ids:
                issues.add(
                    ObservedIssueKind.UNRESOLVED_REFERENCE,
                    f"instance references unknown remediation {remediation_id!r}",
                    entity_kind="instance",
                    entity_id=instance.id,
                )


def _check_unique(values: list[str], kind: str, issues: ObservedIssueCollector) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            issues.add(
                ObservedIssueKind.DUPLICATE_ID,
                f"duplicate {kind} id {value!r}",
                entity_kind=kind,
                entity_id=value,
            )
        seen.add(value)


def _truth_value(index: GraphIndex, mutation: MutationRecord) -> Any:
    record = index.truth_record(mutation.shard, mutation.entity_id)
    if record is None:
        return None
    if mutation.operation is ChangeOp.DELETE_RECORD:
        return record
    return record.get(mutation.field)


def _check_fidelity(
    result: ObservedResult, index: GraphIndex, issues: ObservedIssueCollector
) -> None:
    observed = {
        shard: {r["id"]: r for r in records}
        for shard, records in result.observed_graph.items()
        if shard != "meta"
    }
    for mutation in result.mutations:
        if mutation.operation is ChangeOp.ADD_RECORD:
            continue
        truth_value = _truth_value(index, mutation)
        if mutation.before != truth_value:
            issues.add(
                ObservedIssueKind.FIDELITY,
                "mutation before-value does not match the truth graph",
                entity_kind="mutation",
                entity_id=mutation.id,
                field=mutation.field,
            )
        if mutation.operation in (ChangeOp.SET, ChangeOp.SET_LIST):
            record = observed.get(mutation.shard, {}).get(mutation.entity_id)
            if record is None or record.get(mutation.field) != mutation.after:
                issues.add(
                    ObservedIssueKind.FIDELITY,
                    "mutation after-value is not present in the observed graph",
                    entity_kind="mutation",
                    entity_id=mutation.id,
                    field=mutation.field,
                )


def _check_contamination(result: ObservedResult, issues: ObservedIssueCollector) -> None:
    # No two SET mutations may share a (shard, entity, field) path.
    set_paths: set[tuple[str, str, str]] = set()
    for mutation in result.mutations:
        if mutation.operation in (ChangeOp.SET, ChangeOp.SET_LIST):
            key = (mutation.shard, mutation.entity_id, mutation.field)
            if key in set_paths:
                issues.add(
                    ObservedIssueKind.CONTAMINATION,
                    f"two mutations write the same path {key}",
                    entity_kind="mutation",
                    entity_id=mutation.id,
                    field=mutation.field,
                )
            set_paths.add(key)

    # No entity may carry two mutually incompatible rules.
    rules_by_entity: dict[str, set[str]] = {}
    for instance in result.instances:
        rules_by_entity.setdefault(instance.entity_id, set()).add(instance.rule_id)
    for entity_id, rules in rules_by_entity.items():
        for rule_id in rules:
            incompatible = set(DEFECTS[rule_id].incompatibilities) & rules
            if incompatible:
                issues.add(
                    ObservedIssueKind.INCOMPATIBILITY,
                    f"entity carries incompatible rules {rule_id!r} and {sorted(incompatible)}",
                    entity_kind="instance",
                    entity_id=entity_id,
                )


__all__ = ["read_observed_difficulty", "read_observed_meta", "validate_observed"]
