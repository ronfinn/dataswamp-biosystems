"""Deterministic maturity profiles controlling how many defects are injected.

A profile is a fixed, named point on the data-quality spectrum, from ``gold``
(pristine, no defects) to ``catastrophic`` (pervasive defects). Each carries a
per-category injection rate (the fraction of a rule's eligible population to
affect), a control fraction (assets reserved as never-eligible so a clean
population always survives), a per-entity cap, and a global instance cap as a
hard upper bound. Rates are the only knob; the engine turns them into exact,
seed-replayable selections.

The ``demo`` profile is tuned to inject roughly 100–200 defects across the
estate while leaving a healthy control population — the mixture used for
demonstrations and agent benchmarking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from dataswamp_biosystems.observed.entities import Category


class ObservedProfile(StrEnum):
    """A named maturity profile."""

    GOLD = "gold"
    MOSTLY_GOOD = "mostly-good"
    TYPICAL = "typical"
    POOR = "poor"
    CATASTROPHIC = "catastrophic"
    DEMO = "demo"


@dataclass(frozen=True)
class ProfileSpec:
    """The fixed knobs for one profile."""

    profile: ObservedProfile
    # Fraction of a rule's eligible population to affect, unless overridden.
    default_rate: float
    # Fraction of catalogue assets reserved as controls (excluded from every rule).
    control_fraction: float
    # At most this many applied defects may touch one primary entity.
    max_per_entity: int
    # Hard upper bound on total applied defects (a safety cap, like the estate budget).
    global_cap: int
    # Per-category rate overrides.
    category_rates: dict[Category, float] = field(default_factory=dict)
    # Per-rule rate overrides (win over the category rate), for showcase rules
    # whose small eligible population would otherwise round to zero.
    rule_rates: dict[str, float] = field(default_factory=dict)

    def rate_for(self, category: Category, rule_id: str) -> float:
        if rule_id in self.rule_rates:
            return self.rule_rates[rule_id]
        return self.category_rates.get(category, self.default_rate)


_DEMO_RATES: dict[Category, float] = {
    Category.METADATA_COMPLETENESS: 0.05,
    Category.SEMANTIC_QUALITY: 0.05,
    Category.OWNERSHIP: 0.04,
    Category.NAMING_VERSIONING: 0.03,
    Category.GOVERNANCE_CLASSIFICATION: 0.04,
    Category.LICENSING_INTENDED_USE: 0.05,
    Category.LINEAGE_PROVENANCE: 0.045,
    Category.SCHEMA_STRUCTURAL: 0.045,
    Category.MODALITY_SCIENTIFIC: 0.11,
    Category.AI_TRAINING_READINESS: 0.045,
    Category.LIFECYCLE_STALENESS: 0.045,
    Category.FILE_INTEGRITY: 0.02,
}


_SPECS: dict[ObservedProfile, ProfileSpec] = {
    ObservedProfile.GOLD: ProfileSpec(
        profile=ObservedProfile.GOLD,
        default_rate=0.0,
        control_fraction=1.0,
        max_per_entity=0,
        global_cap=0,
    ),
    ObservedProfile.MOSTLY_GOOD: ProfileSpec(
        profile=ObservedProfile.MOSTLY_GOOD,
        default_rate=0.02,
        control_fraction=0.6,
        max_per_entity=1,
        global_cap=60,
    ),
    ObservedProfile.TYPICAL: ProfileSpec(
        profile=ObservedProfile.TYPICAL,
        default_rate=0.08,
        control_fraction=0.35,
        max_per_entity=2,
        global_cap=300,
    ),
    ObservedProfile.POOR: ProfileSpec(
        profile=ObservedProfile.POOR,
        default_rate=0.2,
        control_fraction=0.15,
        max_per_entity=3,
        global_cap=800,
    ),
    ObservedProfile.CATASTROPHIC: ProfileSpec(
        profile=ObservedProfile.CATASTROPHIC,
        default_rate=0.45,
        control_fraction=0.05,
        max_per_entity=3,
        global_cap=2000,
    ),
    ObservedProfile.DEMO: ProfileSpec(
        profile=ObservedProfile.DEMO,
        default_rate=0.05,
        control_fraction=0.3,
        max_per_entity=2,
        global_cap=260,
        category_rates=_DEMO_RATES,
        rule_rates={"NAM-DUP-FINAL-VERSION": 0.3},
    ),
}


def profile_spec(profile: ObservedProfile) -> ProfileSpec:
    """Return the fixed :class:`ProfileSpec` for ``profile``."""
    return _SPECS[profile]


def profile_specs() -> dict[ObservedProfile, ProfileSpec]:
    """Return a copy-safe view of every profile spec (for tests/introspection)."""
    return dict(_SPECS)


__all__ = ["ObservedProfile", "ProfileSpec", "profile_spec", "profile_specs"]
