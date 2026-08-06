"""Packaging an adversarial benchmark, and keeping its answer key out of the export.

The bundle layer is a packager: it copies emitted bytes verbatim, so the scenario
ledgers travel without the packager needing to know what they are. What must be
proved is that they are *covered* (checksummed and tamper-detectable, like every
other file) and that the one thing which reads a bundle outwards — the DataHub
observed export — still cannot see them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.adapters.datahub import ExportMode, build_source, export_datahub
from dataswamp_biosystems.bundle import BundleReader, Layer, build_bundle, verify_bundle
from dataswamp_biosystems.bundle.errors import BundleValidationError
from dataswamp_biosystems.bundle.layout import CHECKSUMS_NAME, MANIFEST_NAME
from dataswamp_biosystems.observed.writer import SCENARIO_TRANSFORMATIONS_NAME, SCENARIOS_NAME
from dataswamp_biosystems.truth import serialize

OBSERVED_SCENARIOS = f"{Layer.OBSERVED.value}/{SCENARIOS_NAME}"
OBSERVED_TRANSFORMATIONS = f"{Layer.OBSERVED.value}/{SCENARIO_TRANSFORMATIONS_NAME}"


@pytest.fixture(scope="module")
def adversarial_bundle(
    adversarial_observed_dir: Path,
    generated_layers: dict[Layer, Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    target = tmp_path_factory.mktemp("adversarial-bundle") / "bundle"
    build_bundle(
        target,
        sources={
            Layer.TRUTH: generated_layers[Layer.TRUTH],
            Layer.OBSERVED: adversarial_observed_dir,
        },
        release="v-adversarial-test",
    )
    return target


def test_the_scenario_ledgers_are_packaged_and_declared(adversarial_bundle: Path) -> None:
    manifest = json.loads((adversarial_bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
    declared = {entry["path"] for entry in manifest["files"]}
    assert OBSERVED_SCENARIOS in declared
    assert OBSERVED_TRANSFORMATIONS in declared
    assert (adversarial_bundle / OBSERVED_SCENARIOS).is_file()


def test_the_bundle_records_the_migrated_observed_schema(adversarial_bundle: Path) -> None:
    manifest = json.loads((adversarial_bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
    observed = manifest["schemas"][Layer.OBSERVED.value]
    assert observed["schema_version"] == 4
    assert observed["generator_version"] == "1.3.0"


def test_the_bundle_records_the_tier_it_was_generated_at(adversarial_bundle: Path) -> None:
    """A result must be able to cite the tier it was measured at."""
    manifest = json.loads((adversarial_bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["scenario"][Layer.OBSERVED.value]["difficulty"] == "adversarial"


def test_an_adversarial_bundle_verifies_end_to_end(adversarial_bundle: Path) -> None:
    verify_bundle(adversarial_bundle)


def test_tampering_with_the_scenario_ledger_is_detected(
    adversarial_bundle: Path, tmp_path: Path
) -> None:
    """The answer key is covered by the same integrity record as everything else."""
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(adversarial_bundle, copy)
    path = copy / OBSERVED_SCENARIOS
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    rows[0]["rationale"] = "quietly rewritten"
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )

    with pytest.raises(BundleValidationError):
        verify_bundle(copy)


def test_the_checksum_record_covers_the_scenario_ledger(adversarial_bundle: Path) -> None:
    text = (adversarial_bundle / CHECKSUMS_NAME).read_text(encoding="utf-8")
    recorded = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in text.splitlines()}
    assert OBSERVED_SCENARIOS in recorded
    assert recorded[OBSERVED_SCENARIOS] == serialize.digest(
        (adversarial_bundle / OBSERVED_SCENARIOS).read_bytes()
    )


def test_the_reader_exposes_the_observed_graph_without_the_answer_key(
    adversarial_bundle: Path,
) -> None:
    reader = BundleReader.open(adversarial_bundle)
    graph = reader.observed_graph()
    assert graph["meta"]["schema_version"] == 4


# ---------------------------------------------------------------------------
# The DataHub privilege boundary
# ---------------------------------------------------------------------------


def test_an_observed_export_never_opens_a_scenario_ledger(
    adversarial_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Opened *before* the patch: ``BundleReader.open`` verifies the whole bundle
    # and therefore reads every file in it, scenario ledgers included. That is the
    # integrity check doing its job, and it is not the boundary under test — the
    # claim is that building the observed *source graph* reads only the observed
    # graph.
    reader = BundleReader.open(adversarial_bundle)

    opened: list[Path] = []
    real_read_text = Path.read_text
    real_read_bytes = Path.read_bytes

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        opened.append(self)
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    def read_bytes(self: Path) -> bytes:
        opened.append(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    build_source(reader, ExportMode.OBSERVED)

    names = {path.name for path in opened}
    assert SCENARIOS_NAME not in names
    assert SCENARIO_TRANSFORMATIONS_NAME not in names


def test_an_observed_export_carries_no_scenario_field(
    adversarial_bundle: Path, tmp_path: Path
) -> None:
    """A near-miss *value* travels with the graph; the record saying so does not."""
    target = tmp_path / "export"
    export_datahub(adversarial_bundle, mode=ExportMode.OBSERVED, output_dir=target)
    payload = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(target.rglob("*")) if path.is_file()
    )
    for forbidden in (
        "near-miss",
        "near_miss",
        "scenario_id",
        "mimicked_rule_id",
        "validity_check",
        "expected_detection",
        "decoy",
    ):
        assert forbidden not in payload, f"observed export leaks {forbidden!r}"
