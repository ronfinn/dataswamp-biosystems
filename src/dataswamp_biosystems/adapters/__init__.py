"""Adapters that publish DataSwamp benchmark output into third-party systems.

The dependency direction is fixed and one-way: an adapter consumes this
project's own emitted artefacts — in practice, a verified benchmark bundle — and
translates them outward. No core layer (``company``, ``truth``, ``estate``,
``observed``, ``evaluation``, ``bundle``) may import anything from here, and a
test enforces that. See ``docs/adr/0002-truth-vs-observed-state.md`` for the
independence rule this respects.

Adapters are optional. Nothing in the benchmark itself needs one, and no adapter
may make a third-party client a mandatory dependency of the core package.
"""

from __future__ import annotations

__all__: list[str] = []
