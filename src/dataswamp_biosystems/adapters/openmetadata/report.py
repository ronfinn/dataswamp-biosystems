"""Write the OpenMetadata round-trip report directory atomically and deterministically.

Four files, mirroring the four claims and the evidence for each::

    roundtrip-report.json   the four claims, their counts, and the contracts in force
    discrepancies.jsonl     one record per disagreement, canonically ordered
    leak-findings.jsonl     one record per ground-truth marker found (empty on success)
    provenance.json         the environment provenance every generated directory carries

``leak-findings.jsonl`` is always written, even when empty. "The probes ran and
found nothing" and "the probes never ran" are different statements, and a missing
file cannot distinguish them.

**Nothing identifying the machine or the moment is written.** No wall clock, no
hostname, no username, no filesystem path — not even a redacted server address.
That is a deliberate difference from the DataHub round-trip report, which records
its endpoint: a host name is the one field that cannot be made deterministic (a
throwaway instance answers on a different port every run), it is the field most
likely to carry a credential by accident, and it says nothing a reader needs.
What identifies a run is the export it judged, which is recorded by digest. The
report is meant to be committed, pasted into an issue and attached to a CI run,
and two identical round-trips write identical bytes on any machine.

**The report cannot overstate its evidence.** It carries
:data:`~dataswamp_biosystems.adapters.openmetadata.client.LIVE_SUPPORT` and the
adapter's ``verified_openmetadata_version`` — which is ``None`` and stays ``None``
until a real-server canary earns otherwise. A green report produced against the
offline fake says exactly that, and says it in the file rather than in a commit
message somebody has to go and find.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from dataswamp_biosystems.adapters.openmetadata.client import LIVE_SUPPORT
from dataswamp_biosystems.adapters.openmetadata.ingest import LoadedExport
from dataswamp_biosystems.adapters.openmetadata.mapping import (
    OM_ADAPTER_VERSION,
    OPENMETADATA_MODEL_TARGET_RANGE,
    OPENMETADATA_SCHEMA_TARGET,
    VERIFIED_OPENMETADATA_VERSION,
)
from dataswamp_biosystems.adapters.openmetadata.normalize import (
    OM_NORMALIZATION_VERSION,
    normalization_contract,
)
from dataswamp_biosystems.adapters.openmetadata.roundtrip import (
    CONTAINMENT_FAMILIES,
    LEAK_PROBES,
    OM_ROUNDTRIP_SCHEMA_VERSION,
    Claim,
    Coverage,
    DiscrepancyKind,
    RoundTripResult,
)
from dataswamp_biosystems.provenance import PROVENANCE_NAME, provenance_bytes
from dataswamp_biosystems.truth import serialize

ROUNDTRIP_REPORT_NAME = "roundtrip-report.json"
DISCREPANCIES_NAME = "discrepancies.jsonl"
LEAK_FINDINGS_NAME = "leak-findings.jsonl"

PASS = "pass"
FAIL = "fail"

# Surfaces the emitted plan deliberately does not materialise, restated in every
# report so a reader never mistakes "no discrepancies" for "everything mapped".
UNSUPPORTED_SURFACES: tuple[dict[str, str], ...] = (
    {
        "surface": "quality-check results",
        "state": "preserved as custom metadata; not natively represented",
        "reason": (
            "OpenMetadata's TestDefinition.entityType admits only TABLE and COLUMN, "
            "while DataSwamp datasets are Containers. Emitting a TestCase would require "
            "inventing a Table, so quality facts stay DataSwamp custom properties and "
            "the deferred result plan is transmitted nowhere. See mapping-coverage.json."
        ),
    },
    {
        "surface": "relational schema (Table, Column, Database, DatabaseSchema)",
        "state": "not emitted",
        "reason": "DataSwamp holds no honest relational column metadata to describe.",
    },
    {
        "surface": "orchestration (Pipeline, PipelineService)",
        "state": "not emitted",
        "reason": "An instrument run is not an orchestrated pipeline.",
    },
    {
        "surface": "DataContract",
        "state": "preserved as custom metadata; not natively represented",
        "reason": "DataSwamp contract facts do not constitute a governed data contract.",
    },
)


def _status(failed: bool) -> str:
    return FAIL if failed else PASS


def build_report(result: RoundTripResult, export: LoadedExport) -> dict[str, Any]:
    """Build the round-trip report payload.

    The four claims are reported separately and each carries its own counts.
    Collapsing them into a single verdict would hide the distinction that matters
    most in practice.
    """
    by_kind: dict[str, int] = {}
    by_entity_type: dict[str, int] = {}
    for item in result.discrepancies:
        by_kind[item.kind.value] = by_kind.get(item.kind.value, 0) + 1
        by_entity_type[item.entity_type] = by_entity_type.get(item.entity_type, 0) + 1

    counts = result.counts
    missing_entities = len(result.of_kind(DiscrepancyKind.MISSING_ENTITY))
    missing_properties = len(result.of_kind(DiscrepancyKind.MISSING_PROPERTY))
    missing_relationships = len(result.of_kind(DiscrepancyKind.MISSING_RELATIONSHIP))
    mutated = len(result.of_kind(DiscrepancyKind.MUTATED))
    extra_fields = len(result.of_kind(DiscrepancyKind.EXTRA_FIELD))
    extra_relationships = len(result.of_kind(DiscrepancyKind.EXTRA_RELATIONSHIP))
    extra_entities = len(result.of_kind(DiscrepancyKind.EXTRA_ENTITY))

    unavailable = {
        family.entity_type: family.reason
        for family in CONTAINMENT_FAMILIES
        if result.coverage.get(family.entity_type) == Coverage.UNAVAILABLE.value
    }

    return {
        "roundtrip_schema_version": OM_ROUNDTRIP_SCHEMA_VERSION,
        "normalization_version": OM_NORMALIZATION_VERSION,
        "adapter_version": OM_ADAPTER_VERSION,
        "catalogue": {
            "platform": "openmetadata",
            # No address is recorded, by design. See this module's docstring.
            "schema_target": OPENMETADATA_SCHEMA_TARGET,
            "model_target_range": OPENMETADATA_MODEL_TARGET_RANGE,
            "verified_openmetadata_version": VERIFIED_OPENMETADATA_VERSION,
            "live_support": LIVE_SUPPORT,
        },
        "export": export.identity(),
        "claims": {
            Claim.COMPLETENESS.value: {
                "status": _status(
                    bool(missing_entities or missing_properties or missing_relationships)
                ),
                "sent_entities": counts["sent_entities"],
                "retrieved_entities": counts["retrieved_entities"],
                "missing_entities": missing_entities,
                "sent_custom_properties": counts["sent_custom_properties"],
                "missing_custom_properties": missing_properties,
                "sent_asset_attachments": counts["sent_asset_attachments"],
                "sent_lineage_edges": counts["sent_lineage_edges"],
                "missing_relationships": missing_relationships,
            },
            Claim.FIDELITY.value: {
                "status": _status(bool(mutated)),
                "compared": counts["retrieved_entities"],
                "matched": counts["matched_entities"],
                "mutated": mutated,
            },
            Claim.CONTAINMENT.value: {
                "status": _status(bool(extra_fields or extra_relationships or extra_entities)),
                "extra_fields": extra_fields,
                "extra_relationships": extra_relationships,
                "extra_entities": extra_entities,
                "entity_family_coverage": dict(sorted(result.coverage.items())),
                "coverage_meanings": {
                    Coverage.PROVABLE.value: (
                        "a server-side scope filter proves DataSwamp ownership structurally"
                    ),
                    Coverage.NAMESPACE.value: (
                        "enumerated globally; ownership evidenced by DataSwamp's reserved "
                        "FQN prefix, which a third party could in principle imitate"
                    ),
                    Coverage.UNAVAILABLE.value: (
                        "not enumerated; no extra-entity claim is made for this family"
                    ),
                },
                "unavailable_reasons": dict(sorted(unavailable.items())),
                "foreign_entities": (
                    "entities outside every ownership rule are ignored entirely and are "
                    "never reported as DataSwamp extras"
                ),
            },
            Claim.NON_LEAKAGE.value: {
                "status": _status(bool(result.leak_findings)),
                "applicable": result.mode.value == "observed",
                "probes": [
                    {"name": probe.name, "description": probe.description} for probe in LEAK_PROBES
                ],
                "probe_scope": (
                    "markers defined by the OpenMetadata export contract only; no bundle, "
                    "ledger, rule scope, scenario or expected-finding set is consulted"
                ),
                "findings": len(result.leak_findings),
            },
        },
        "discrepancies": {
            "total": len(result.discrepancies),
            "by_kind": dict(sorted(by_kind.items())),
            "by_entity_type": dict(sorted(by_entity_type.items())),
        },
        "normalization": normalization_contract(),
        "unsupported_surfaces": list(UNSUPPORTED_SURFACES),
        "clean": result.clean,
        "synthetic": True,
    }


def _jsonl(records: list[dict[str, Any]]) -> bytes:
    return "".join(f"{serialize.canonical_json(record)}\n" for record in records).encode("utf-8")


def write_roundtrip(
    output_dir: Path | str,
    result: RoundTripResult,
    export: LoadedExport,
) -> dict[str, Any]:
    """Write the round-trip report directory atomically, and return the report.

    Staged in a temporary sibling and swapped into place, like every other
    generated directory in this project, so an interrupted run never leaves a
    half-written report that reads as a verdict.
    """
    output_dir = Path(output_dir)
    report = build_report(result, export)
    files = {
        ROUNDTRIP_REPORT_NAME: serialize.manifest_bytes(report),
        DISCREPANCIES_NAME: _jsonl([item.as_record() for item in result.discrepancies]),
        LEAK_FINDINGS_NAME: _jsonl([item.as_record() for item in result.leak_findings]),
        PROVENANCE_NAME: provenance_bytes(
            layer="adapter-openmetadata-roundtrip",
            generator_version=OM_ADAPTER_VERSION,
            schema_version=OM_ROUNDTRIP_SCHEMA_VERSION,
            scenario={
                "mode": result.mode.value,
                "normalization_version": OM_NORMALIZATION_VERSION,
            },
        ),
    }

    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{output_dir.name}.tmp-{os.getpid()}"
    backup = parent / f".{output_dir.name}.bak-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        tmp.mkdir(parents=True)
        for name in sorted(files):
            serialize.write_bytes(tmp / name, files[name])
        had_existing = output_dir.exists()
        if had_existing:
            os.replace(output_dir, backup)
        try:
            os.replace(tmp, output_dir)
        except OSError:
            if had_existing:  # pragma: no cover - best-effort restore
                os.replace(backup, output_dir)
            raise
        if had_existing:
            shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return report


__all__ = [
    "ROUNDTRIP_REPORT_NAME",
    "DISCREPANCIES_NAME",
    "LEAK_FINDINGS_NAME",
    "PASS",
    "FAIL",
    "UNSUPPORTED_SURFACES",
    "build_report",
    "write_roundtrip",
]
