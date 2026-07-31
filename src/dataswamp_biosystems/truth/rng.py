"""Seeded, order-independent pseudorandom helpers.

Determinism hinges on *where* randomness comes from. Every random value is
drawn from a :class:`random.Random` derived from the root seed plus the stable
key of the entity being generated, so a value depends only on that key — never
on iteration order, generation timing, or how many values were drawn before it.

Do not use the global :mod:`random` module or an unseeded ``Random`` anywhere in
generator code; always go through :func:`sub_rng`.
"""

from __future__ import annotations

from hashlib import blake2b
from random import Random


def _derive_seed(seed: int, key_parts: tuple[str, ...]) -> int:
    """Derive a stable 64-bit integer seed from the root seed and a string key."""
    key = "\x1f".join((str(seed), *key_parts)).encode("utf-8")
    return int.from_bytes(blake2b(key, digest_size=8).digest(), "big")


def sub_rng(seed: int, *key_parts: str) -> Random:
    """Return an independent ``Random`` for the given entity key.

    The same ``(seed, *key_parts)`` always yields the same stream, independent
    of any other RNG use, so generation order cannot affect output.
    """
    return Random(_derive_seed(seed, key_parts))


__all__ = ["sub_rng"]
