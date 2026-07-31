"""Deterministic identifier construction for truth-graph entities.

All ids are structured, human-readable, and slug-valid (``SLUG_PATTERN`` from
the company model). They are built from stable parts — never ``uuid4``, never a
digest of file *contents*, never wall-clock — so the same seed and generator
version always produce the same ids.

Ordinals are zero-padded to a fixed width so lexical and numeric ordering agree,
which keeps record ordering stable when we sort by id before writing.
"""

from __future__ import annotations

import re
from hashlib import blake2b

from dataswamp_biosystems.company.identifiers import SLUG_PATTERN

_SLUG_RE = re.compile(SLUG_PATTERN)

# Fixed zero-padding width for ordinals embedded in ids.
ORDINAL_WIDTH = 4


def ordinal(n: int) -> str:
    """Return ``n`` as a fixed-width zero-padded string (e.g. ``0007``)."""
    if n < 0:
        raise ValueError(f"ordinal must be non-negative, got {n}")
    return str(n).zfill(ORDINAL_WIDTH)


def is_slug(value: str) -> bool:
    """Return whether ``value`` is a valid canonical slug."""
    return bool(_SLUG_RE.fullmatch(value))


def join(*parts: str) -> str:
    """Join id parts with single hyphens, producing a canonical slug.

    Each part is expected to already be slug-safe; the joined result is
    validated so malformed parts fail loudly at construction time rather than
    silently producing an invalid id.
    """
    slug = "-".join(part for part in parts if part != "")
    if not is_slug(slug):
        raise ValueError(f"constructed id is not a valid slug: {slug!r}")
    return slug


def stable_suffix(*key_parts: str, digest_size: int = 4) -> str:
    """A short, deterministic hex suffix derived from a stable string key.

    Used only where a compact opaque token is unavoidable. The digest is taken
    over the joined key parts, never over RNG state or file contents.
    """
    key = "\x1f".join(key_parts).encode("utf-8")
    return blake2b(key, digest_size=digest_size).hexdigest()


__all__ = ["ORDINAL_WIDTH", "ordinal", "is_slug", "join", "stable_suffix"]
