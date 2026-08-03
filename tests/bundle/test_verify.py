"""Bundle verification: what a tampered, truncated or hand-edited bundle looks like.

Each test breaks exactly one thing and asserts the verifier names that thing.
A verifier that reports "invalid" without saying which file and which invariant
is not usable by someone who has just downloaded a bundle over a flaky link.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataswamp_biosystems.bundle import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    BundleConfigError,
    BundleIssueKind,
    BundleValidationError,
    read_manifest,
    verify_bundle,
)
from dataswamp_biosystems.provenance import PROVENANCE_NAME


def _kinds(exc: BundleValidationError) -> set[BundleIssueKind]:
    return {issue.kind for issue in exc.issues}


def _files(exc: BundleValidationError) -> set[str]:
    return {issue.file for issue in exc.issues}


def _rewrite_manifest(bundle: Path, mutate: object) -> None:
    """Apply ``mutate`` to the manifest payload and rewrite the checksum record.

    Used by tests that must break one specific invariant without also tripping
    the "checksums.sha256 is not reproducible from the manifest" check, which
    would otherwise mask what is being tested.
    """
    from dataswamp_biosystems.bundle.builder import checksums_text
    from dataswamp_biosystems.truth import serialize

    payload = json.loads((bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
    mutate(payload)  # type: ignore[operator]
    data = serialize.manifest_bytes(payload)
    (bundle / MANIFEST_NAME).write_bytes(data)
    manifest = read_manifest(bundle)
    (bundle / CHECKSUMS_NAME).write_text(checksums_text(manifest, data), encoding="utf-8")


def test_a_freshly_built_bundle_verifies(full_bundle_dir: Path) -> None:
    manifest = verify_bundle(full_bundle_dir)
    assert manifest.layers == ["truth", "estate", "observed", "evaluation"]


def test_truth_only_bundle_verifies(truth_only_bundle_dir: Path) -> None:
    """A missing optional layer is a normal bundle, not a broken one."""
    assert verify_bundle(truth_only_bundle_dir).layers == ["truth"]


def test_missing_bundle_directory(tmp_path: Path) -> None:
    with pytest.raises(BundleConfigError, match="no bundle directory"):
        verify_bundle(tmp_path / "nope")


def test_missing_manifest(mutable_bundle: Path) -> None:
    (mutable_bundle / MANIFEST_NAME).unlink()
    with pytest.raises(BundleConfigError, match="no bundle manifest"):
        verify_bundle(mutable_bundle)


def test_invalid_manifest_json(mutable_bundle: Path) -> None:
    (mutable_bundle / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(BundleConfigError, match="could not read"):
        verify_bundle(mutable_bundle)


def test_manifest_missing_required_fields(mutable_bundle: Path) -> None:
    (mutable_bundle / MANIFEST_NAME).write_text('{"bundle_schema_version": 1}', encoding="utf-8")
    with pytest.raises(BundleConfigError, match="not a valid bundle manifest"):
        verify_bundle(mutable_bundle)


def test_unsupported_schema_version_is_refused_not_guessed(mutable_bundle: Path) -> None:
    payload = json.loads((mutable_bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["bundle_schema_version"] = 99
    (mutable_bundle / MANIFEST_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(BundleConfigError, match="supports"):
        verify_bundle(mutable_bundle)


def test_modified_file_is_detected(mutable_bundle: Path) -> None:
    target = mutable_bundle / "observed" / "expected-findings.jsonl"
    target.write_bytes(target.read_bytes() + b'{"tampered":true}\n')
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.CHECKSUM_MISMATCH in _kinds(caught.value)
    assert "observed/expected-findings.jsonl" in _files(caught.value)


def test_missing_file_is_detected(mutable_bundle: Path) -> None:
    (mutable_bundle / "truth" / "assets.jsonl").unlink()
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.MISSING_FILE in _kinds(caught.value)
    assert "truth/assets.jsonl" in _files(caught.value)


def test_missing_checksum_record_is_detected(mutable_bundle: Path) -> None:
    (mutable_bundle / CHECKSUMS_NAME).unlink()
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert CHECKSUMS_NAME in _files(caught.value)


def test_undeclared_file_is_rejected_under_strict_verification(mutable_bundle: Path) -> None:
    (mutable_bundle / "observed" / "smuggled.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.UNDECLARED_FILE in _kinds(caught.value)
    assert verify_bundle(mutable_bundle, strict=False).layers, "relaxing strict allows extras"


def test_edited_checksum_record_is_caught_by_the_manifest(mutable_bundle: Path) -> None:
    """The two integrity anchors cover each other."""
    path = mutable_bundle / CHECKSUMS_NAME
    path.write_text(path.read_text(encoding="utf-8").replace("a", "b", 1), encoding="utf-8")
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert CHECKSUMS_NAME in _files(caught.value)


def test_edited_manifest_digest_is_caught_by_the_checksum_record(mutable_bundle: Path) -> None:
    payload = json.loads((mutable_bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
    payload["benchmark_release"] = "forged"
    (mutable_bundle / MANIFEST_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert CHECKSUMS_NAME in _files(caught.value)


def test_forged_checksum_for_a_modified_file_still_fails(mutable_bundle: Path) -> None:
    """Rewriting a file *and* its manifest digest breaks the bundle fingerprint."""
    from dataswamp_biosystems.truth import serialize

    target = mutable_bundle / "truth" / "assets.jsonl"
    target.write_bytes(b'{"id":"forged"}\n')
    forged = serialize.digest(target.read_bytes())

    def mutate(payload: dict) -> None:
        for entry in payload["files"]:
            if entry["path"] == "truth/assets.jsonl":
                entry["sha256"] = forged
                entry["bytes"] = len(target.read_bytes())

    _rewrite_manifest(mutable_bundle, mutate)
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.FINGERPRINT in _kinds(caught.value)


def test_path_traversal_in_the_manifest_is_refused(mutable_bundle: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["files"].append(
            {"path": "../escape.txt", "sha256": "0" * 64, "bytes": 0, "section": "bundle"}
        )

    _rewrite_manifest(mutable_bundle, mutate)
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.UNSAFE_PATH in _kinds(caught.value)
    assert "../escape.txt" in _files(caught.value)


@pytest.mark.parametrize("bad", ["/etc/passwd", "a//b", "truth/../../x", "windows\\path", "./x"])
def test_absolute_and_dotted_manifest_paths_are_refused(mutable_bundle: Path, bad: str) -> None:
    def mutate(payload: dict) -> None:
        payload["files"].append({"path": bad, "sha256": "0" * 64, "bytes": 0, "section": "bundle"})

    _rewrite_manifest(mutable_bundle, mutate)
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.UNSAFE_PATH in _kinds(caught.value)


def test_symlink_escape_is_refused(mutable_bundle: Path, tmp_path: Path) -> None:
    secret = tmp_path / "outside.txt"
    secret.write_text("not part of the bundle", encoding="utf-8")
    (mutable_bundle / "truth" / "assets.jsonl").unlink()
    (mutable_bundle / "truth" / "assets.jsonl").symlink_to(secret)
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.SYMLINK in _kinds(caught.value)


def test_inconsistent_provenance_is_detected(mutable_bundle: Path) -> None:
    path = mutable_bundle / "truth" / PROVENANCE_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["environment_fingerprint"] = "f" * 64
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def mutate(manifest: dict) -> None:
        from dataswamp_biosystems.truth import serialize

        for entry in manifest["files"]:
            if entry["path"] == f"truth/{PROVENANCE_NAME}":
                data = path.read_bytes()
                entry["sha256"] = serialize.digest(data)
                entry["bytes"] = len(data)
        lines = sorted(f"{e['path']}:{e['sha256']}" for e in manifest["files"])
        manifest["bundle_fingerprint"] = serialize.digest("\n".join(lines).encode("utf-8"))

    _rewrite_manifest(mutable_bundle, mutate)
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.PROVENANCE in _kinds(caught.value)


def test_declaring_a_layer_without_its_prerequisite_is_structural(mutable_bundle: Path) -> None:
    _rewrite_manifest(mutable_bundle, lambda p: p.__setitem__("layers", ["truth", "evaluation"]))
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.STRUCTURE in _kinds(caught.value)


def test_ground_truth_fingerprint_drift_is_detected(mutable_bundle: Path) -> None:
    _rewrite_manifest(mutable_bundle, lambda p: p.__setitem__("ground_truth_fingerprint", "a" * 64))
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.FINGERPRINT in _kinds(caught.value)


def test_issues_render_the_file_and_the_invariant(mutable_bundle: Path) -> None:
    target = mutable_bundle / "truth" / "assets.jsonl"
    target.write_bytes(b"")
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    rendered = [issue.render() for issue in caught.value.issues]
    assert any("truth/assets.jsonl" in line and "checksum-mismatch" in line for line in rendered)


def test_verification_never_modifies_the_bundle(mutable_bundle: Path) -> None:
    before = {
        path.relative_to(mutable_bundle).as_posix(): path.read_bytes()
        for path in mutable_bundle.rglob("*")
        if path.is_file()
    }
    verify_bundle(mutable_bundle)
    after = {
        path.relative_to(mutable_bundle).as_posix(): path.read_bytes()
        for path in mutable_bundle.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_an_evaluation_scored_against_other_ground_truth_is_rejected(
    mutable_bundle: Path,
) -> None:
    """A report bundled beside a state it did not score would look authoritative."""
    from dataswamp_biosystems.truth import serialize

    path = mutable_bundle / "evaluation" / "evaluation-summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["benchmark"]["ground_truth_fingerprint"] = "c" * 64
    data = serialize.manifest_bytes(payload)
    path.write_bytes(data)

    def mutate(manifest: dict) -> None:
        for entry in manifest["files"]:
            if entry["path"] == "evaluation/evaluation-summary.json":
                entry["sha256"] = serialize.digest(data)
                entry["bytes"] = len(data)
        lines = sorted(f"{e['path']}:{e['sha256']}" for e in manifest["files"])
        manifest["bundle_fingerprint"] = serialize.digest("\n".join(lines).encode("utf-8"))

    _rewrite_manifest(mutable_bundle, mutate)
    with pytest.raises(BundleValidationError) as caught:
        verify_bundle(mutable_bundle)
    assert BundleIssueKind.REFERENCE in _kinds(caught.value)
