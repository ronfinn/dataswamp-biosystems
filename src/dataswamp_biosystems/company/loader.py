"""Load and validate the canonical configuration from a directory of YAML files.

The loader performs two stages:

1. **Read & construct** — read every expected YAML file, check each file's
   ``schema_version``, and build a :class:`CanonicalConfig`. File/parse
   problems raise :class:`ConfigLoadError` (CLI exit 2). Per-field model
   problems (bad types, unknown keys, malformed emails, empty required lists)
   are collected as ``schema`` issues.
2. **Cross-file validation** — with a constructed model in hand, resolve
   duplicates, email domains, references, and controlled-vocabulary values,
   collecting every problem before raising :class:`ConfigValidationError`
   (CLI exit 1).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from dataswamp_biosystems.company.config import SCHEMA_VERSION, CanonicalConfig
from dataswamp_biosystems.company.entities import FICTIONAL_DOMAIN, TeamType
from dataswamp_biosystems.company.errors import (
    ConfigLoadError,
    IssueCollector,
    IssueKind,
)
from dataswamp_biosystems.company.relationships import OwnerType, SubjectType

DEFAULT_CONFIG_DIR = Path("config")

# Maps a config file (relative to the config dir) to the top-level keys it is
# expected to contribute. Vocabulary files each carry a ``terms`` list.
_ENTITY_FILES = {
    "company.yaml": ("company",),
    "programmes.yaml": ("programmes",),
    "studies.yaml": ("studies",),
    "teams.yaml": ("teams",),
    "people.yaml": ("roles", "people"),
    "ownership.yaml": ("ownership",),
    "stewardship.yaml": ("stewardship",),
    "generation.yaml": ("generation",),
}

# Vocabulary file (under ``vocabularies/``) -> CanonicalConfig.vocabularies field.
_VOCABULARY_FILES = {
    "access-classifications.yaml": "access_classifications",
    "retention-classes.yaml": "retention_classes",
    "scientific-domains.yaml": "scientific_domains",
    "modalities.yaml": "modalities",
    "lifecycle-stages.yaml": "lifecycle_stages",
    "intended-uses.yaml": "intended_uses",
    "training-approval-statuses.yaml": "training_approval_statuses",
    "stewardship-types.yaml": "stewardship_types",
}


def _read_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file, requiring a top-level mapping."""
    if not path.exists():
        raise ConfigLoadError(f"missing configuration file: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - message content only
        raise ConfigLoadError(f"could not parse {path}: {exc}") from exc
    if raw is None:
        raise ConfigLoadError(f"empty configuration file: {path}")
    if not isinstance(raw, Mapping):
        raise ConfigLoadError(f"expected a top-level mapping in {path}, got {type(raw).__name__}")
    return dict(raw)


def _check_schema_version(doc: Mapping[str, Any], source: str, issues: IssueCollector) -> None:
    version = doc.get("schema_version")
    if version != SCHEMA_VERSION:
        issues.add(
            IssueKind.SCHEMA,
            f"schema_version must be {SCHEMA_VERSION}, got {version!r}",
            source=source,
            field="schema_version",
        )


def _validation_error_to_issues(exc: ValidationError, source: str, issues: IssueCollector) -> None:
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        issues.add(
            IssueKind.SCHEMA,
            error["msg"],
            source=source,
            field=location,
        )


def load_config(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> CanonicalConfig:
    """Load, assemble, and fully validate the canonical configuration.

    Raises:
        ConfigLoadError: a file is missing or cannot be parsed (CLI exit 2).
        ConfigValidationError: the config loads but fails validation (CLI exit 1).
    """
    config_dir = Path(config_dir)
    issues = IssueCollector()

    # --- Stage 1: read files and assemble raw kwargs -------------------------
    payload: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    for filename, keys in _ENTITY_FILES.items():
        doc = _read_mapping(config_dir / filename)
        _check_schema_version(doc, filename, issues)
        for key in keys:
            payload[key] = doc.get(key)

    vocab_payload: dict[str, Any] = {}
    for filename, field_name in _VOCABULARY_FILES.items():
        source = f"vocabularies/{filename}"
        doc = _read_mapping(config_dir / "vocabularies" / filename)
        _check_schema_version(doc, source, issues)
        vocab_payload[field_name] = doc.get("terms")
    payload["vocabularies"] = vocab_payload

    # --- Stage 1b: construct the typed model ---------------------------------
    try:
        config = CanonicalConfig.model_validate(payload)
    except ValidationError as exc:
        _validation_error_to_issues(exc, "config", issues)
        # Schema problems are terminal: cross-file checks need a valid model.
        issues.raise_if_any()
        raise  # pragma: no cover - raise_if_any always raises when issues exist

    # --- Stage 2: cross-file validation --------------------------------------
    _validate_identities(config, issues)
    _validate_duplicates(config, issues)
    _validate_references(config, issues)
    _validate_vocabulary_references(config, issues)
    _validate_structural(config, issues)

    issues.raise_if_any()
    return config


def _duplicate_ids(ids: Iterable[str]) -> list[str]:
    counts = Counter(ids)
    return sorted(value for value, count in counts.items() if count > 1)


def _validate_duplicates(config: CanonicalConfig, issues: IssueCollector) -> None:
    collections: dict[str, list[str]] = {
        "programmes": [p.id for p in config.programmes],
        "studies": [s.id for s in config.studies],
        "teams": [t.id for t in config.teams],
        "people": [p.id for p in config.people],
        "roles": [r.id for r in config.roles],
        "ownership": [o.id for o in config.ownership],
        "stewardship": [s.id for s in config.stewardship],
    }
    vocab = config.vocabularies
    collections.update(
        {
            "vocabularies.access_classifications": [t.id for t in vocab.access_classifications],
            "vocabularies.retention_classes": [t.id for t in vocab.retention_classes],
            "vocabularies.scientific_domains": [t.id for t in vocab.scientific_domains],
            "vocabularies.modalities": [t.id for t in vocab.modalities],
            "vocabularies.lifecycle_stages": [t.id for t in vocab.lifecycle_stages],
            "vocabularies.intended_uses": [t.id for t in vocab.intended_uses],
            "vocabularies.training_approval_statuses": [
                t.id for t in vocab.training_approval_statuses
            ],
            "vocabularies.stewardship_types": [t.id for t in vocab.stewardship_types],
        }
    )
    for source, ids in collections.items():
        for duplicate in _duplicate_ids(ids):
            issues.add(
                IssueKind.DUPLICATE_ID,
                f"duplicate id {duplicate!r} in {source}",
                source=source,
                entity_id=duplicate,
            )


def _validate_identities(config: CanonicalConfig, issues: IssueCollector) -> None:
    if config.company.domain != FICTIONAL_DOMAIN:
        issues.add(
            IssueKind.INVALID_EMAIL_DOMAIN,
            f"company domain must be {FICTIONAL_DOMAIN!r}, got {config.company.domain!r}",
            source="company",
            entity_id=config.company.id,
            field="domain",
        )

    seen_emails: dict[str, str] = {}
    for person in config.people:
        email = str(person.email)
        domain = email.rsplit("@", 1)[-1].lower()
        if domain != FICTIONAL_DOMAIN:
            issues.add(
                IssueKind.INVALID_EMAIL_DOMAIN,
                f"email domain must be {FICTIONAL_DOMAIN!r}, got {domain!r}",
                source="people",
                entity_id=person.id,
                field="email",
            )
        key = email.lower()
        if key in seen_emails:
            issues.add(
                IssueKind.DUPLICATE_EMAIL,
                f"email {email!r} is already used by {seen_emails[key]!r}",
                source="people",
                entity_id=person.id,
                field="email",
            )
        else:
            seen_emails[key] = person.id


def _validate_references(config: CanonicalConfig, issues: IssueCollector) -> None:
    programme_ids = {p.id for p in config.programmes}
    study_ids = {s.id for s in config.studies}
    team_ids = {t.id for t in config.teams}
    person_ids = {p.id for p in config.people}

    subject_universe: dict[SubjectType, set[str]] = {
        SubjectType.PROGRAMME: programme_ids,
        SubjectType.STUDY: study_ids,
        SubjectType.TEAM: team_ids,
    }

    for study in config.studies:
        if study.programme_id not in programme_ids:
            issues.add(
                IssueKind.UNRESOLVED_REFERENCE,
                f"study {study.id!r} references nonexistent programme {study.programme_id!r}",
                source="studies",
                entity_id=study.id,
                field="programme_id",
            )

    for team in config.teams:
        if team.programme_id is not None and team.programme_id not in programme_ids:
            issues.add(
                IssueKind.UNRESOLVED_REFERENCE,
                f"team {team.id!r} references nonexistent programme {team.programme_id!r}",
                source="teams",
                entity_id=team.id,
                field="programme_id",
            )

    for person in config.people:
        if person.team_id not in team_ids:
            issues.add(
                IssueKind.UNRESOLVED_REFERENCE,
                f"person {person.id!r} references nonexistent team {person.team_id!r}",
                source="people",
                entity_id=person.id,
                field="team_id",
            )

    for assignment in config.ownership:
        universe = subject_universe[assignment.subject_type]
        if assignment.subject_id not in universe:
            issues.add(
                IssueKind.UNRESOLVED_REFERENCE,
                f"ownership {assignment.id!r} references nonexistent "
                f"{assignment.subject_type.value} {assignment.subject_id!r}",
                source="ownership",
                entity_id=assignment.id,
                field="subject_id",
            )
        owner_universe = team_ids if assignment.owner_type is OwnerType.TEAM else person_ids
        if assignment.owner_id not in owner_universe:
            issues.add(
                IssueKind.UNRESOLVED_REFERENCE,
                f"ownership {assignment.id!r} references nonexistent "
                f"{assignment.owner_type.value} owner {assignment.owner_id!r}",
                source="ownership",
                entity_id=assignment.id,
                field="owner_id",
            )

    for steward_assignment in config.stewardship:
        universe = subject_universe[steward_assignment.subject_type]
        if steward_assignment.subject_id not in universe:
            issues.add(
                IssueKind.UNRESOLVED_REFERENCE,
                f"stewardship {steward_assignment.id!r} references nonexistent "
                f"{steward_assignment.subject_type.value} "
                f"{steward_assignment.subject_id!r}",
                source="stewardship",
                entity_id=steward_assignment.id,
                field="subject_id",
            )
        if steward_assignment.steward_id not in person_ids:
            issues.add(
                IssueKind.UNRESOLVED_REFERENCE,
                f"stewardship {steward_assignment.id!r} references nonexistent person "
                f"{steward_assignment.steward_id!r}",
                source="stewardship",
                entity_id=steward_assignment.id,
                field="steward_id",
            )


def _term_ids(terms: Iterable[Any]) -> set[str]:
    return {term.id for term in terms}


def _check_term(
    value: str,
    valid: set[str],
    *,
    vocabulary: str,
    source: str,
    entity_id: str,
    field: str,
    issues: IssueCollector,
) -> None:
    if value not in valid:
        issues.add(
            IssueKind.INVALID_VOCABULARY,
            f"{field} {value!r} is not a valid {vocabulary} term",
            source=source,
            entity_id=entity_id,
            field=field,
        )


def _validate_vocabulary_references(config: CanonicalConfig, issues: IssueCollector) -> None:
    vocab = config.vocabularies
    access = _term_ids(vocab.access_classifications)
    retention = _term_ids(vocab.retention_classes)
    domains = _term_ids(vocab.scientific_domains)
    modalities = _term_ids(vocab.modalities)
    lifecycle = _term_ids(vocab.lifecycle_stages)
    intended = _term_ids(vocab.intended_uses)
    training = _term_ids(vocab.training_approval_statuses)
    stewardship_types = _term_ids(vocab.stewardship_types)
    roles = _term_ids(config.roles)

    # Intra-vocabulary: each modality points at a real scientific domain.
    for modality_term in vocab.modalities:
        _check_term(
            modality_term.scientific_domain,
            domains,
            vocabulary="scientific-domain",
            source="vocabularies/modalities",
            entity_id=modality_term.id,
            field="scientific_domain",
            issues=issues,
        )

    for programme in config.programmes:
        if programme.default_access_classification is not None:
            _check_term(
                programme.default_access_classification,
                access,
                vocabulary="access-classification",
                source="programmes",
                entity_id=programme.id,
                field="default_access_classification",
                issues=issues,
            )
        if programme.default_retention_class is not None:
            _check_term(
                programme.default_retention_class,
                retention,
                vocabulary="retention-class",
                source="programmes",
                entity_id=programme.id,
                field="default_retention_class",
                issues=issues,
            )

    for study in config.studies:
        for domain in study.scientific_domains:
            _check_term(
                domain,
                domains,
                vocabulary="scientific-domain",
                source="studies",
                entity_id=study.id,
                field="scientific_domains",
                issues=issues,
            )
        for modality in study.modalities:
            _check_term(
                modality,
                modalities,
                vocabulary="modality",
                source="studies",
                entity_id=study.id,
                field="modalities",
                issues=issues,
            )
        for use in study.intended_uses:
            _check_term(
                use,
                intended,
                vocabulary="intended-use",
                source="studies",
                entity_id=study.id,
                field="intended_uses",
                issues=issues,
            )
        _check_term(
            study.access_classification,
            access,
            vocabulary="access-classification",
            source="studies",
            entity_id=study.id,
            field="access_classification",
            issues=issues,
        )
        _check_term(
            study.retention_class,
            retention,
            vocabulary="retention-class",
            source="studies",
            entity_id=study.id,
            field="retention_class",
            issues=issues,
        )
        _check_term(
            study.lifecycle_stage,
            lifecycle,
            vocabulary="lifecycle-stage",
            source="studies",
            entity_id=study.id,
            field="lifecycle_stage",
            issues=issues,
        )
        _check_term(
            study.model_training_approval,
            training,
            vocabulary="training-approval-status",
            source="studies",
            entity_id=study.id,
            field="model_training_approval",
            issues=issues,
        )

    for person in config.people:
        _check_term(
            person.role,
            roles,
            vocabulary="role",
            source="people",
            entity_id=person.id,
            field="role",
            issues=issues,
        )

    for assignment in config.stewardship:
        _check_term(
            assignment.stewardship_type,
            stewardship_types,
            vocabulary="stewardship-type",
            source="stewardship",
            entity_id=assignment.id,
            field="stewardship_type",
            issues=issues,
        )


def _validate_structural(config: CanonicalConfig, issues: IssueCollector) -> None:
    """Per-record structural rules that hold independent of dataset size.

    Scientific teams must be aligned to a programme; platform and governance
    teams must not be. (Dataset cardinality expectations — three programmes,
    six studies, two per programme — are asserted by the test suite against the
    authored configuration, not enforced here, so that compact fixtures remain
    valid.)
    """
    for team in config.teams:
        if team.team_type is TeamType.SCIENTIFIC and team.programme_id is None:
            issues.add(
                IssueKind.STRUCTURAL,
                f"scientific team {team.id!r} must set programme_id",
                source="teams",
                entity_id=team.id,
                field="programme_id",
            )
        if team.team_type is not TeamType.SCIENTIFIC and team.programme_id is not None:
            issues.add(
                IssueKind.STRUCTURAL,
                f"{team.team_type.value} team {team.id!r} must not set programme_id",
                source="teams",
                entity_id=team.id,
                field="programme_id",
            )


__all__ = ["DEFAULT_CONFIG_DIR", "load_config"]
