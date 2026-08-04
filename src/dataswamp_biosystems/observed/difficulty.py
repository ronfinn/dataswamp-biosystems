"""Benchmark difficulty tiers, derived from the reasoning a defect actually requires.

Difficulty here means one thing only: **how much evidence a detector must relate
before it can decide.** It is deliberately not any of the things it is commonly
confused with, and the separation is enforced rather than asserted:

============== =============================================================
Concept        What it controls
============== =============================================================
maturity       *How many* defects are injected (``ObservedProfile``).
scale          *How large* the estate is (the truth generation plan).
category        *What kind* of governance concern a rule belongs to.
severity       *How much it matters* once found.
remediation    *How hard it is to fix*, and who must approve.
**difficulty** *How hard it is to find*, and nothing else.
============== =============================================================

A high-severity defect can be trivial to spot (a missing owner), and a low-severity
one can need multi-hop reasoning. A rule that is automatically remediable can be
very hard to detect. Deriving difficulty from severity or from remediation
availability would therefore be wrong, and
``tests/observed/test_difficulty.py`` asserts that no such correspondence exists.

Deriving difficulty from a scope, not declaring it
--------------------------------------------------

Difficulty is not hand-assigned per rule. Each rule declares a
:class:`ReasoningScope` — an objective, checkable statement of *what evidence a
detector must consult* — and the tier follows from it by
:data:`DIFFICULTY_BY_SCOPE`. That keeps the tiering auditable: a reviewer can
disagree with "this rule needs two records", which is a factual claim about the
rule, far more usefully than with "this rule is silver", which is a judgement.

``adversarial`` is never a rule's default. It is a property of a *scenario*, not
of a rule: the same rule can appear in a bronze positive case and in an
adversarial near-miss control. See :mod:`dataswamp_biosystems.observed.scenarios`.
"""

from __future__ import annotations

from enum import StrEnum

# Bumped when the tier semantics or the scope assignment changes in a way that
# makes a previously published tier result non-comparable. Recorded alongside
# any emitted tier metadata so an old result stays interpretable.
DIFFICULTY_MODEL_VERSION = 1


class Difficulty(StrEnum):
    """The four benchmark difficulty tiers."""

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    ADVERSARIAL = "adversarial"


# Tier order, weakest first — for deterministic reporting and for ``mixed``
# coverage, never for arithmetic. The tiers are nominal, not a numeric scale, and
# nothing in this project averages them into a single "difficulty score".
DIFFICULTY_ORDER: tuple[Difficulty, ...] = (
    Difficulty.BRONZE,
    Difficulty.SILVER,
    Difficulty.GOLD,
    Difficulty.ADVERSARIAL,
)

# Tiers a *rule* may declare. Adversarial is scenario-level only.
RULE_DIFFICULTIES: frozenset[Difficulty] = frozenset(
    {Difficulty.BRONZE, Difficulty.SILVER, Difficulty.GOLD}
)


class ReasoningScope(StrEnum):
    """What a detector must relate before it can decide a rule has fired."""

    #: One record, its own fields. No other record is needed, and no knowledge of
    #: what the value *should* have been.
    SINGLE_RECORD = "single-record"
    #: The entity plus a record directly attached to it — its governance record,
    #: its contract, its quality checks, its training approval, its own files.
    #: One join, and the join key is present on the record.
    CROSS_RECORD = "cross-record"
    #: Two or more catalogue assets, or a lineage path of more than one edge.
    #: The defect is invisible from either end alone.
    CROSS_ASSET = "cross-asset"
    #: Correctness is only decidable by comparison against comparable peers — the
    #: other datasets in the study, the estate's prevailing conventions. Nothing
    #: in the entity itself is malformed; it is *wrong*, which is harder.
    PEER_RELATIVE = "peer-relative"


SCOPE_ORDER: tuple[ReasoningScope, ...] = (
    ReasoningScope.SINGLE_RECORD,
    ReasoningScope.CROSS_RECORD,
    ReasoningScope.CROSS_ASSET,
    ReasoningScope.PEER_RELATIVE,
)

#: The whole tiering rule. Peer-relative joins cross-asset at gold: both demand
#: that the detector hold several entities in view at once, and neither is
#: decidable from a single join.
DIFFICULTY_BY_SCOPE: dict[ReasoningScope, Difficulty] = {
    ReasoningScope.SINGLE_RECORD: Difficulty.BRONZE,
    ReasoningScope.CROSS_RECORD: Difficulty.SILVER,
    ReasoningScope.CROSS_ASSET: Difficulty.GOLD,
    ReasoningScope.PEER_RELATIVE: Difficulty.GOLD,
}


# ---------------------------------------------------------------------------
# The per-rule scope assignment.
#
# Kept in one table rather than spread across forty-one constructor calls so the
# whole tiering can be reviewed on one screen — the assignment *is* the product
# claim, and a claim that cannot be read in one place cannot be audited.
#
# Every rule in the registry must appear here; ``validate_registry`` fails
# otherwise, so a new rule cannot be added without stating what it takes to find.
# ---------------------------------------------------------------------------

RULE_REASONING_SCOPES: dict[str, ReasoningScope] = {
    # -- single-record: the record contradicts itself, or a required field is
    # simply absent. One `if` over one dict decides it.
    "GOV-CLASS-MISSING": ReasoningScope.SINGLE_RECORD,
    "GOV-RETENTION-MISSING": ReasoningScope.SINGLE_RECORD,
    "META-DESC-MISSING": ReasoningScope.SINGLE_RECORD,
    "META-MODALITY-META-EMPTY": ReasoningScope.SINGLE_RECORD,
    "META-TITLE-MISSING": ReasoningScope.SINGLE_RECORD,
    "META-VERSION-MISSING": ReasoningScope.SINGLE_RECORD,
    "OWN-OWNER-MISSING": ReasoningScope.SINGLE_RECORD,
    "OWN-STEWARD-MISSING": ReasoningScope.SINGLE_RECORD,
    "SCH-RECORD-COUNT-ZERO": ReasoningScope.SINGLE_RECORD,
    "SCH-SIZE-INVERSION": ReasoningScope.SINGLE_RECORD,
    "USE-INTENDED-USE-MISSING": ReasoningScope.SINGLE_RECORD,
    # Two fields of the same record disagreeing is still one record.
    "USE-EXTERNAL-VS-RESTRICTED": ReasoningScope.SINGLE_RECORD,
    "MOD-GENOME-BUILD-MISSING": ReasoningScope.SINGLE_RECORD,
    # -- cross-record: one join, from a key the entity already carries.
    "AIR-TRAINING-APPROVAL-ABSENT": ReasoningScope.CROSS_RECORD,
    "AIR-TRAINING-STATUS-MISMATCH": ReasoningScope.CROSS_RECORD,
    "OWN-DENORM-MISMATCH": ReasoningScope.CROSS_RECORD,
    "OWN-OWNER-DANGLING": ReasoningScope.CROSS_RECORD,
    "QC-CERTIFIED-CONTRADICTED": ReasoningScope.CROSS_RECORD,
    "SCH-CONTRACT-MISSING": ReasoningScope.CROSS_RECORD,
    "LIN-DATASET-NO-UPSTREAM": ReasoningScope.CROSS_RECORD,
    "LIN-PROVENANCE-DANGLING": ReasoningScope.CROSS_RECORD,
    "LIN-VCF-INDEX-MISSING": ReasoningScope.CROSS_RECORD,
    "USE-TRAINING-WITHOUT-APPROVAL": ReasoningScope.CROSS_RECORD,
    "FILE-MISSING": ReasoningScope.CROSS_RECORD,
    "FILE-CHECKSUM-MISMATCH": ReasoningScope.CROSS_RECORD,
    "MOD-H5AD-NO-COUNTS-LAYER": ReasoningScope.CROSS_RECORD,
    "MOD-SPATIAL-COORDS-OOB": ReasoningScope.CROSS_RECORD,
    "MOD-MIXED-GENE-IDS": ReasoningScope.CROSS_RECORD,
    # -- cross-asset: more than one catalogue asset, or a multi-edge path.
    "LIN-CROSS-STUDY-EDGE": ReasoningScope.CROSS_ASSET,
    "LIN-PATH-NO-SLIDE-SOURCE": ReasoningScope.CROSS_ASSET,
    "NAM-DUP-FINAL-VERSION": ReasoningScope.CROSS_ASSET,
    # -- peer-relative: the value is well-formed and wrong. Deciding needs the
    # estate's conventions or the entity's siblings, never the entity alone.
    "GOV-RESTRICTED-AS-INTERNAL": ReasoningScope.PEER_RELATIVE,
    "GOV-STALE-REVIEW": ReasoningScope.PEER_RELATIVE,
    "LIF-STAGE-REGRESSION": ReasoningScope.PEER_RELATIVE,
    "LIF-STALE-ASSET": ReasoningScope.PEER_RELATIVE,
    "NAM-PATH-CONVENTION": ReasoningScope.PEER_RELATIVE,
    "NAM-VERSION-NONCANONICAL": ReasoningScope.PEER_RELATIVE,
    "OWN-OWNER-WRONG-TEAM": ReasoningScope.PEER_RELATIVE,
    "SEM-DESC-GENERIC": ReasoningScope.PEER_RELATIVE,
    "SEM-DOMAIN-MISLABELLED": ReasoningScope.PEER_RELATIVE,
    "SEM-TITLE-UNINFORMATIVE": ReasoningScope.PEER_RELATIVE,
}


class UnknownRuleDifficultyError(KeyError):
    """A rule has no declared reasoning scope, so its tier cannot be derived."""

    def __init__(self, rule_id: str) -> None:
        self.rule_id = rule_id
        super().__init__(
            f"rule {rule_id!r} declares no reasoning scope; add it to "
            f"RULE_REASONING_SCOPES in observed/difficulty.py — a rule whose "
            f"detection difficulty is unstated cannot be tiered"
        )


def reasoning_scope_for(rule_id: str) -> ReasoningScope:
    """Return the declared reasoning scope of ``rule_id``."""
    try:
        return RULE_REASONING_SCOPES[rule_id]
    except KeyError:
        raise UnknownRuleDifficultyError(rule_id) from None


def difficulty_for(rule_id: str) -> Difficulty:
    """Return the tier ``rule_id`` sits at, derived from its reasoning scope."""
    return DIFFICULTY_BY_SCOPE[reasoning_scope_for(rule_id)]


def rules_at(difficulty: Difficulty) -> tuple[str, ...]:
    """Return the rule ids at ``difficulty``, sorted.

    Empty for :attr:`Difficulty.ADVERSARIAL`: no rule is adversarial by default,
    because adversarial is a property of a scenario rather than of a rule.
    """
    return tuple(
        sorted(
            rule_id
            for rule_id, scope in RULE_REASONING_SCOPES.items()
            if DIFFICULTY_BY_SCOPE[scope] is difficulty
        )
    )


def rules_by_difficulty() -> dict[Difficulty, tuple[str, ...]]:
    """Return every tier's rule ids, in tier order."""
    return {tier: rules_at(tier) for tier in DIFFICULTY_ORDER}


__all__ = [
    "DIFFICULTY_BY_SCOPE",
    "DIFFICULTY_MODEL_VERSION",
    "DIFFICULTY_ORDER",
    "RULE_DIFFICULTIES",
    "RULE_REASONING_SCOPES",
    "SCOPE_ORDER",
    "Difficulty",
    "ReasoningScope",
    "UnknownRuleDifficultyError",
    "difficulty_for",
    "reasoning_scope_for",
    "rules_at",
    "rules_by_difficulty",
]
