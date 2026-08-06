"""The difficulty model: every rule tiered, and tiered by nothing but its scope.

The point of these tests is not that the numbers are 13/15/13. It is that the
tiering is *derived* — from a per-rule reasoning scope, deterministically — and
that it is not secretly a restatement of severity, of the maturity profile, or
of how hard a defect is to fix. Those three confusions are what makes a
difficulty axis worthless, so each one is refuted explicitly rather than
asserted in a docstring.
"""

from __future__ import annotations

import pytest

from dataswamp_biosystems.observed.defects import DEFECTS, registry_rows, validate_registry
from dataswamp_biosystems.observed.difficulty import (
    DIFFICULTY_BY_SCOPE,
    DIFFICULTY_ORDER,
    RULE_DIFFICULTIES,
    RULE_REASONING_SCOPES,
    SCOPE_ORDER,
    Difficulty,
    DifficultySelection,
    ReasoningScope,
    UnavailableDifficultyError,
    UnknownRuleDifficultyError,
    classification_problems,
    difficulty_for,
    reasoning_scope_for,
    resolve_selection,
    rules_at,
    rules_by_difficulty,
    selectable_rules,
)
from dataswamp_biosystems.observed.profiles import ObservedProfile, profile_spec

# The published distribution. Pinned so a reclassification is a deliberate,
# reviewed edit rather than a silent drift in what "gold" advertises.
EXPECTED_DISTRIBUTION = {
    Difficulty.BRONZE: 13,
    Difficulty.SILVER: 15,
    Difficulty.GOLD: 13,
    Difficulty.ADVERSARIAL: 0,
}


# ---------------------------------------------------------------------------
# Completeness and derivation
# ---------------------------------------------------------------------------


def test_every_registered_rule_declares_exactly_one_reasoning_scope() -> None:
    assert set(RULE_REASONING_SCOPES) == set(DEFECTS)
    assert len(RULE_REASONING_SCOPES) == len(DEFECTS) == 41


def test_the_classification_is_sound_and_the_registry_enforces_it() -> None:
    assert classification_problems(DEFECTS) == []
    # The registry validator is where an unclassified rule is actually caught,
    # so the two must not be able to disagree.
    assert validate_registry(DEFECTS) == []


def test_an_unclassified_rule_is_a_registry_error_naming_the_rule() -> None:
    problems = classification_problems([*DEFECTS, "NEW-RULE-NOBODY-TIERED"])
    assert len(problems) == 1
    assert "NEW-RULE-NOBODY-TIERED" in problems[0]
    assert "reasoning scope" in problems[0]


def test_a_scope_declared_for_an_unregistered_rule_is_also_an_error() -> None:
    problems = classification_problems(set(DEFECTS) - {"OWN-OWNER-MISSING"})
    assert len(problems) == 1
    assert "OWN-OWNER-MISSING" in problems[0]
    assert "not registered" in problems[0]


def test_looking_up_an_unknown_rule_fails_loudly_rather_than_defaulting() -> None:
    """No rule may silently acquire a tier — the failure names what to fix."""
    with pytest.raises(UnknownRuleDifficultyError) as excinfo:
        difficulty_for("NO-SUCH-RULE")
    assert "NO-SUCH-RULE" in str(excinfo.value)
    assert "RULE_REASONING_SCOPES" in str(excinfo.value)


def test_every_scope_is_known_and_maps_to_one_rule_holdable_tier() -> None:
    assert set(DIFFICULTY_BY_SCOPE) == set(SCOPE_ORDER) == set(ReasoningScope)
    for scope in SCOPE_ORDER:
        assert DIFFICULTY_BY_SCOPE[scope] in RULE_DIFFICULTIES


def test_difficulty_is_a_pure_function_of_the_declared_scope() -> None:
    """The tier is derived, never hand-assigned: same scope, same tier, always."""
    for rule_id, scope in RULE_REASONING_SCOPES.items():
        assert difficulty_for(rule_id) is DIFFICULTY_BY_SCOPE[scope]
        assert reasoning_scope_for(rule_id) is scope


def test_the_published_distribution_is_what_the_registry_actually_holds() -> None:
    tiers = rules_by_difficulty()
    assert {tier: len(rules) for tier, rules in tiers.items()} == EXPECTED_DISTRIBUTION
    assert sum(EXPECTED_DISTRIBUTION.values()) == len(DEFECTS)


def test_the_tiers_partition_the_registry_exactly_once() -> None:
    seen: list[str] = []
    for rules in rules_by_difficulty().values():
        seen.extend(rules)
    assert sorted(seen) == sorted(DEFECTS)
    assert len(seen) == len(set(seen))


def test_lookups_and_ordering_are_deterministic() -> None:
    """Ordering is a property of the data, not of dict iteration."""
    for tier in DIFFICULTY_ORDER:
        rules = rules_at(tier)
        assert list(rules) == sorted(rules)
        assert rules == rules_at(tier)
    assert list(rules_by_difficulty()) == list(DIFFICULTY_ORDER)


# ---------------------------------------------------------------------------
# Independence: difficulty is not severity, maturity, or remediation
# ---------------------------------------------------------------------------


def _tiers_per(attribute: str) -> dict[str, set[Difficulty]]:
    """Group tiers by some other rule attribute, to show the axes cross-cut."""
    grouped: dict[str, set[Difficulty]] = {}
    for rule_id, definition in DEFECTS.items():
        key = str(getattr(definition, attribute))
        grouped.setdefault(key, set()).add(difficulty_for(rule_id))
    return grouped


def _rules_per(attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for definition in DEFECTS.values():
        key = str(getattr(definition, attribute))
        counts[key] = counts.get(key, 0) + 1
    return counts


# Deliberately not parametrized over ``category``. Category is *what kind* of
# governance concern a rule addresses, and some kinds genuinely cluster — every
# metadata-completeness rule really is decidable from one record. Difficulty
# correlating with category is expected; difficulty *being* severity, approval
# policy or maturity is the confusion worth refuting.
@pytest.mark.parametrize(
    "attribute", ["default_severity", "remediation_availability", "approval_policy"]
)
def test_difficulty_does_not_encode_another_dimension(attribute: str) -> None:
    """No other rule attribute determines the tier.

    If a value of ``attribute`` mapped to exactly one tier, the tier would be
    that attribute wearing a new name. Values held by fewer than three rules are
    exempt: a two-rule value cannot demonstrate spread either way, so demanding
    it would be a test of the catalogue's size rather than of its tiering.
    """
    grouped = _tiers_per(attribute)
    sizes = _rules_per(attribute)
    confined = {key: tiers for key, tiers in grouped.items() if sizes[key] >= 3 and len(tiers) < 2}
    assert not confined, f"{attribute} values confined to one tier: {confined}"


def test_every_tier_spans_severities_and_remediation_availabilities() -> None:
    """And the converse: no tier is a single severity or a single fixability."""
    for tier in RULE_DIFFICULTIES:
        rules = rules_at(tier)
        severities = {DEFECTS[r].default_severity for r in rules}
        availabilities = {DEFECTS[r].remediation_availability for r in rules}
        assert len(severities) > 1, f"{tier.value} is a single severity"
        assert len(availabilities) > 1, f"{tier.value} is a single remediation availability"


def test_difficulty_is_independent_of_the_maturity_profile() -> None:
    """No profile knob is keyed by difficulty; profiles tune category rates only.

    Maturity controls *how many* defects appear, difficulty *which rules may
    produce them*. A profile that varied its rate by tier would silently couple
    the two, so the profile specs are checked for any tier-shaped key.
    """
    tier_names = {tier.value for tier in DIFFICULTY_ORDER}
    for profile in ObservedProfile:
        spec = profile_spec(profile)
        assert not tier_names & {c.value for c in spec.category_rates}
        assert not tier_names & set(spec.rule_rates)
        # The per-rule overrides that do exist must not single out a tier.
        overridden = {difficulty_for(rule_id) for rule_id in spec.rule_rates}
        assert len(overridden) <= 1 or overridden <= RULE_DIFFICULTIES


# ---------------------------------------------------------------------------
# Adversarial is a scenario property, never a rule label
# ---------------------------------------------------------------------------


def test_no_ordinary_rule_is_labelled_adversarial() -> None:
    assert rules_at(Difficulty.ADVERSARIAL) == ()
    assert Difficulty.ADVERSARIAL not in RULE_DIFFICULTIES


def test_adversarial_cannot_be_resolved_to_a_rule_set() -> None:
    """It is generated by constructing scenarios, so "which rules?" is the wrong question.

    Still an error rather than an empty tuple: returning nothing would silently
    produce a defect-free "adversarial" benchmark, which is worse than a failure
    because it looks like a result.
    """
    with pytest.raises(UnavailableDifficultyError) as excinfo:
        selectable_rules(Difficulty.ADVERSARIAL)
    assert "produced by the scenario engine" in str(excinfo.value)


def test_the_caller_facing_selection_adds_mixed_and_adversarial() -> None:
    assert {s.value for s in DifficultySelection} == {
        "bronze",
        "silver",
        "gold",
        "mixed",
        "adversarial",
    }
    assert resolve_selection(None) is None
    assert resolve_selection(DifficultySelection.MIXED) is None
    for tier in RULE_DIFFICULTIES:
        assert resolve_selection(DifficultySelection(tier.value)) is tier
    assert resolve_selection(DifficultySelection.ADVERSARIAL) is Difficulty.ADVERSARIAL


def test_mixed_never_means_all_tiers_including_adversarial() -> None:
    """``mixed`` is the ordinary rule catalogue and nothing else.

    Folding constructed scenarios into the default would move the canonical
    benchmark's bytes and every published baseline score with them, so the
    boundary is asserted rather than left to a docstring.
    """
    assert resolve_selection(DifficultySelection.MIXED) is None
    catalogue = {rule_id for tier in RULE_DIFFICULTIES for rule_id in rules_at(tier)}
    assert catalogue == set(RULE_REASONING_SCOPES)


# ---------------------------------------------------------------------------
# The public registry surface
# ---------------------------------------------------------------------------


def test_registry_rows_publish_both_the_scope_and_the_tier() -> None:
    """The scope is the checkable claim; publishing only the tier hides the why."""
    for row in registry_rows():
        rule_id = row["rule_id"]
        assert row["reasoning_scope"] == reasoning_scope_for(rule_id).value
        assert row["difficulty"] == difficulty_for(rule_id).value


def test_selectable_rules_returns_exactly_the_tier() -> None:
    for tier in RULE_DIFFICULTIES:
        rules = selectable_rules(tier)
        assert set(rules) == set(rules_at(tier))
        assert all(difficulty_for(rule_id) is tier for rule_id in rules)
