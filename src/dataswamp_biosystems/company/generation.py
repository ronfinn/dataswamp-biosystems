"""Generation configuration.

This milestone implements no generator. The model exists so that the seed and
output settings future deterministic generators will consume are validated and
version-controlled from the start. ``output_dir`` names the git-ignored
``generated/`` location; nothing is written this milestone.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from dataswamp_biosystems.company.vocabularies import STRICT_MODEL_CONFIG


class GenerationConfig(BaseModel):
    """Deterministic-generation settings (placeholder, not yet acted upon)."""

    model_config = STRICT_MODEL_CONFIG

    seed: int = Field(ge=0)
    output_dir: str = "generated"
    deterministic: bool = True


__all__ = ["GenerationConfig"]
