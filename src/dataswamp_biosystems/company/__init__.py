"""Canonical company model: entities, controlled vocabularies, and validation.

This package defines the fictional Data Swamp Biosystems company model and the
machinery that loads and validates it from ``config/``. It is deliberately
independent of any catalogue or governance tool (e.g. DataHub): nothing here
imports or depends on such a system, and any future integration must adapt
*from* this model, not the other way around.
"""

from __future__ import annotations

from dataswamp_biosystems.company.config import (
    SCHEMA_VERSION,
    CanonicalConfig,
    Vocabularies,
)
from dataswamp_biosystems.company.errors import (
    ConfigError,
    ConfigIssue,
    ConfigLoadError,
    ConfigValidationError,
    IssueKind,
)
from dataswamp_biosystems.company.loader import (
    DEFAULT_CONFIG_DIR,
    PACKAGED_CONFIG_DIR,
    SOURCE_CONFIG_DIR,
    is_config_dir,
    load_config,
    resolve_config_dir,
)

__all__ = [
    "SCHEMA_VERSION",
    "CanonicalConfig",
    "Vocabularies",
    "ConfigError",
    "ConfigIssue",
    "ConfigLoadError",
    "ConfigValidationError",
    "IssueKind",
    "DEFAULT_CONFIG_DIR",
    "PACKAGED_CONFIG_DIR",
    "SOURCE_CONFIG_DIR",
    "is_config_dir",
    "resolve_config_dir",
    "load_config",
]
