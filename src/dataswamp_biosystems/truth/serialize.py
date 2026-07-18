"""The single canonical serializer and file writer for truth-graph output.

Every byte written goes through here so determinism rules are enforced in one
place: sorted keys, UTF-8 without BOM, ``\\n`` line endings, no wall-clock, and
records sorted by id. JSONL shards use compact separators; the manifest is
pretty-printed. Both are deterministic.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Compact, canonical separators for one-object-per-line JSONL.
_COMPACT_SEPARATORS = (",", ":")


def canonical_json(payload: Any) -> str:
    """Serialize a JSON-able payload canonically (sorted keys, compact, UTF-8)."""
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=_COMPACT_SEPARATORS,
    )


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def jsonl_bytes(models: Iterable[BaseModel]) -> bytes:
    """Render models as canonical JSONL bytes, one object per line.

    Records are sorted by their ``id`` field so output order never depends on
    generation or iteration order. A trailing newline terminates the final line.
    """
    rows = sorted((_dump(m) for m in models), key=lambda row: str(row["id"]))
    if not rows:
        return b""
    text = "\n".join(canonical_json(row) for row in rows) + "\n"
    return text.encode("utf-8")


def manifest_bytes(payload: dict[str, Any]) -> bytes:
    """Render the top-level manifest as pretty, deterministic JSON bytes."""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    return text.encode("utf-8")


def digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data`` (used for the manifest tripwire)."""
    return sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes) -> None:
    """Write bytes verbatim, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with ``\\n`` newlines and no BOM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


__all__ = [
    "canonical_json",
    "jsonl_bytes",
    "manifest_bytes",
    "digest",
    "write_bytes",
    "write_text",
]
