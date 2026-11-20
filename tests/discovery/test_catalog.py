from __future__ import annotations

from app.discovery.catalog import (
    SOURCE_SIGNAL_CLASSIFICATIONS,
    TEXT_RULES,
    find_text_rule_match,
)
from app.domain import SignalType


def _rule(signal_type: SignalType):
    return next(rule for rule in TEXT_RULES if rule.signal_type is signal_type)


def test_source_signal_classifications_keep_source_meaning() -> None:
    assert SOURCE_SIGNAL_CLASSIFICATIONS[SignalType.NEW_PUBLICATION].category == "research"
    assert SOURCE_SIGNAL_CLASSIFICATIONS[SignalType.NEW_REPOSITORY].category == "technology"
    funding = SOURCE_SIGNAL_CLASSIFICATIONS[SignalType.NEW_FUNDING_PROJECT]
    assert funding.category == "public_research_or_program_context"
    assert "not an external startup equity round" in funding.interpretation


def test_founding_mention_matches_only_supported_context_and_text() -> None:
    rule = _rule(SignalType.FOUNDING_ACTIVITY_MENTION)
    match = find_text_rule_match(
        rule,
        "exist",
        "success_story",
        {"summary": "The company was founded in 2024."},
        SignalType.NEW_FUNDING_PROJECT.value,
    )
    assert match == ("summary", "founded")
    assert find_text_rule_match(
        rule,
        "cordis",
        "project",
        {"title": "A company was founded"},
        SignalType.NEW_FUNDING_PROJECT.value,
    ) is None


def test_negated_mentions_are_excluded() -> None:
    founding = _rule(SignalType.FOUNDING_ACTIVITY_MENTION)
    assert find_text_rule_match(
        founding,
        "university",
        "news",
        {"title": "The company is not yet founded"},
        SignalType.NEW_PRESS_RELEASE.value,
    ) is None

    spinout = _rule(SignalType.SPINOUT_MENTION)
    assert find_text_rule_match(
        spinout,
        "university",
        "news",
        {"summary": "This is not a spin-out"},
        SignalType.NEW_PRESS_RELEASE.value,
    ) is None


def test_spinout_and_commercialization_rules_match_explicit_terms() -> None:
    spinout = _rule(SignalType.SPINOUT_MENTION)
    assert find_text_rule_match(
        spinout,
        "university",
        "press_release",
        {"summary": "A university spin-out launches a new technology"},
        SignalType.NEW_PRESS_RELEASE.value,
    ) == ("summary", "spin-out")

    commercial = _rule(SignalType.COMMERCIALIZATION_MENTION)
    assert find_text_rule_match(
        commercial,
        "github",
        "repository",
        {"repository": {"description": "Commercial launch of a research prototype"}},
        SignalType.NEW_REPOSITORY.value,
    ) == ("repository.description", "Commercial launch")

    german_spinout = _rule(SignalType.SPINOUT_MENTION)
    assert find_text_rule_match(
        german_spinout,
        "university",
        "news",
        {"summary": "Die Ausgründung entstand aus einem Forschungsprojekt."},
        SignalType.NEW_PRESS_RELEASE.value,
    ) == ("summary", "Ausgründung")

    german_commercial = _rule(SignalType.COMMERCIALIZATION_MENTION)
    assert find_text_rule_match(
        german_commercial,
        "exist",
        "success_story",
        {"summary": "Die Markteinführung des Produkts erfolgte im Frühjahr."},
        SignalType.NEW_FUNDING_PROJECT.value,
    ) == ("summary", "Markteinführung")


def test_rule_version_and_signal_type_are_stable() -> None:
    assert {rule.rule_id for rule in TEXT_RULES} == {
        "founding-activity-mention",
        "spinout-mention",
        "commercialization-mention",
    }
    assert {rule.rule_version for rule in TEXT_RULES} == {"1"}
    assert {rule.signal_type.value for rule in TEXT_RULES} <= {
        signal.value for signal in SignalType
    }
