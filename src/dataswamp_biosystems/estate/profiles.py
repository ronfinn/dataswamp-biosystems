"""Generation profiles: how much of the estate to materialize, and how large.

A profile is a fixed, named point on the size/scale trade-off. It never lets a
caller request an arbitrary size; the byte budget is a hard safety cap enforced
during generation, not a tunable knob (see the milestone plan's size
safeguards). Three profiles are provided:

- ``tiny`` — a small representative subset of assets, full genuine file sets;
  intended to stay well under 50 MB and to exercise every supported format.
- ``demo`` — every truth-graph asset with its full file set; intended for
  DataHub/agent demonstrations and to stay under 500 MB.
- ``stress`` — every asset, but each expanded into many tiny catalogue *records*
  with near-zero physical content, to exercise catalogue scale rather than
  scientific processing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Megabyte in bytes, for legible budget arithmetic.
_MB = 1_000_000


class Profile(StrEnum):
    """A named generation profile."""

    TINY = "tiny"
    DEMO = "demo"
    STRESS = "stress"


class BuildMode(StrEnum):
    """How each selected asset is expanded into files."""

    FULL = "full"  # full genuine file set per asset (tiny, demo)
    STRESS = "stress"  # many tiny catalogue-shard records per asset (stress)


@dataclass(frozen=True)
class ProfileSpec:
    """The fixed knobs for one profile."""

    profile: Profile
    mode: BuildMode
    # Hard upper bound on total physical bytes written; generation aborts if a
    # run would exceed it, so a profile can never fill the disk.
    budget_bytes: int
    # tiny selects the first ``assets_per_group`` datasets of each modality
    # group (by sorted id) plus this many reference datasets and data products;
    # demo/stress select everything (``select_all``).
    select_all: bool
    assets_per_group: int
    reference_assets: int
    product_assets: int
    # stress only: number of tiny shard records emitted per selected asset.
    shards_per_asset: int


_SPECS: dict[Profile, ProfileSpec] = {
    Profile.TINY: ProfileSpec(
        profile=Profile.TINY,
        mode=BuildMode.FULL,
        budget_bytes=50 * _MB,
        select_all=False,
        assets_per_group=2,
        reference_assets=2,
        product_assets=2,
        shards_per_asset=0,
    ),
    Profile.DEMO: ProfileSpec(
        profile=Profile.DEMO,
        mode=BuildMode.FULL,
        budget_bytes=500 * _MB,
        select_all=True,
        assets_per_group=0,
        reference_assets=0,
        product_assets=0,
        shards_per_asset=0,
    ),
    Profile.STRESS: ProfileSpec(
        profile=Profile.STRESS,
        mode=BuildMode.STRESS,
        budget_bytes=100 * _MB,
        select_all=True,
        assets_per_group=0,
        reference_assets=0,
        product_assets=0,
        shards_per_asset=60,
    ),
}


def profile_spec(profile: Profile) -> ProfileSpec:
    """Return the fixed :class:`ProfileSpec` for ``profile``."""
    return _SPECS[profile]


__all__ = ["Profile", "BuildMode", "ProfileSpec", "profile_spec", "profile_specs"]


def profile_specs() -> dict[Profile, ProfileSpec]:
    """Return a copy-safe view of every profile spec (for tests/introspection)."""
    return dict(_SPECS)
