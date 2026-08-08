"""Write the round-trip report directory atomically and deterministically.

Four files, mirroring the four claims and the evidence for each::

    roundtrip-report.json   the four claims, their counts, and the contracts in force
    discrepancies.jsonl     one record per disagreement, canonically ordered
    leak-findings.jsonl     one record per ground-truth marker found (empty on success)
    provenance.json         the environment provenance every generated directory carries

``leak-findings.jsonl`` is always written, even when empty. "The probes ran and
found nothing" and "the probes never ran" are different statements, and a
missing file cannot distinguish them.

No wall-clock value appears anywhere. The report is a function of the export, the
catalogue's answers and the contracts in force, so two identical round-trips
write identical bytes. The server address is recorded through
:func:`~dataswamp_biosystems.adapters.datahub.client.redact_url`, so a token
embedded in a GMS URL never reaches the file — the report is meant to be
committed, pasted into an issue and attached to CI runs.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from dataswamp_biosystems.adapters.datahub.client import LIVE_SUPPORT
from dataswamp_biosystems.adapters.datahub.ingest import LoadedExport
from dataswamp_biosystems.adapters.datahub.mapping import ADAPTER_VERSION
from dataswamp_biosystems.adapters.datahub.normalize import (
    NORMALIZATION_VERSION,
    normalization_contract,
)
from dataswamp_biosystems.adapters.datahub.roundtrip import (
    ENTITY_FAMILIES,
    LEAK_PROBES,
    ROUNDTRIP_SCHEMA_VERSION,
    Claim,
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


def _status(failed: int) -> str:
    return FAIL if failed else PASS


def build_report(result: RoundTripResult, export: LoadedExport, endpoint: str) -> dict[str, Any]:
    """Build the round-trip report payload.

    The four claims are reported separately and each carries its own numerator
    and denominator. Collapsing them into a single verdict would hide the
    distinction that matters most in practice: a catalogue that is missing
    aspects has a different problem from one that mutated them, and both differ
    from one holding entities nobody sent it.
    """
    missing = len(result.of_kind(DiscrepancyKind.MISSING))
    mutated = len(result.of_kind(DiscrepancyKind.MUTATED))
    extra_aspects = len(result.of_kind(DiscrepancyKind.EXTRA_ASPECT))
    extra_entities = len(result.of_kind(DiscrepancyKind.EXTRA_ENTITY))
    sent = result.counts["sent"]

    by_kind: dict[str, int] = {}
    by_entity_type: dict[str, int] = {}
    by_aspect: dict[str, int] = {}
    for item in result.discrepancies:
        by_kind[item.kind.value] = by_kind.get(item.kind.value, 0) + 1
        by_entity_type[item.entity_type] = by_entity_type.get(item.entity_type, 0) + 1
        if item.aspect_name:
            by_aspect[item.aspect_name] = by_aspect.get(item.aspect_name, 0) + 1

    return {
        "roundtrip_schema_version": ROUNDTRIP_SCHEMA_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "export": export.identity(),
        "catalogue": {"endpoint": endpoint, "live_support": LIVE_SUPPORT},
        "claims": {
            Claim.COMPLETENESS.value: {
                "status": _status(missing),
                "sent": sent,
                "retrieved": result.counts["retrieved"],
                "missing": missing,
            },
            Claim.FIDELITY.value: {
                "status": _status(mutated),
                "compared": sent - missing,
                "matched": result.counts["matched"],
                "mutated": mutated,
            },
            Claim.CONTAINMENT.value: {
                "status": _status(extra_aspects + extra_entities),
                "extra_aspects": extra_aspects,
                "extra_entities": extra_entities,
                "entity_family_coverage": dict(sorted(result.coverage.items())),
                "unavailable_reasons": {
                    family.entity_type: family.reason
                    for family in sorted(ENTITY_FAMILIES, key=lambda f: f.entity_type)
                    if not family.scannable
                },
            },
            Claim.NON_LEAKAGE.value: {
                "status": _status(len(result.leak_findings)),
                "applicable": result.mode.value == "observed",
                "probes": [
                    {"name": probe.name, "description": probe.description} for probe in LEAK_PROBES
                ],
                "findings": len(result.leak_findings),
            },
        },
        "discrepancies": {
            "total": len(result.discrepancies),
            "by_kind": dict(sorted(by_kind.items())),
            "by_entity_type": dict(sorted(by_entity_type.items())),
            "by_aspect": dict(sorted(by_aspect.items())),
        },
        "normalization": normalization_contract(),
        "clean": result.clean,
        "synthetic": True,
    }


def _jsonl(records: list[dict[str, Any]]) -> bytes:
    return "".join(f"{serialize.canonical_json(record)}\n" for record in records).encode("utf-8")


def write_roundtrip(
    output_dir: Path | str,
    result: RoundTripResult,
    export: LoadedExport,
    endpoint: str,
) -> dict[str, Any]:
    """Write the round-trip report directory atomically, and return the report.

    Staged in a temporary sibling and swapped into place, like every other
    generated directory in this project, so an interrupted run never leaves a
    half-written report that reads as a verdict.
    """
    output_dir = Path(output_dir)
    report = build_report(result, export, endpoint)
    files = {
        ROUNDTRIP_REPORT_NAME: serialize.manifest_bytes(report),
        DISCREPANCIES_NAME: _jsonl([item.as_record() for item in result.discrepancies]),
        LEAK_FINDINGS_NAME: _jsonl([item.as_record() for item in result.leak_findings]),
        PROVENANCE_NAME: provenance_bytes(
            layer="adapter-datahub-roundtrip",
            generator_version=ADAPTER_VERSION,
            schema_version=ROUNDTRIP_SCHEMA_VERSION,
            scenario={
                "mode": result.mode.value,
                "mcps_digest": export.payload_digest,
                "normalization_version": NORMALIZATION_VERSION,
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
    "build_report",
    "write_roundtrip",
]
