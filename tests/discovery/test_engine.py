from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.discovery.engine import discover
from app.discovery.types import DiscoveryInput, ObservationInput
from app.domain import SignalType


def _input(
    source_name: str,
    record_type: str,
    signal_type: SignalType,
    payload: dict,
) -> DiscoveryInput:
    return DiscoveryInput(
        source_signal_id=uuid4(),
        source_record_id=uuid4(),
        entity_id=uuid4(),
        source_name=source_name,
        record_type=record_type,
        source_signal_type=signal_type.value,
        event_date=None,
        published_at=None,
        raw_payload=payload,
    )


def test_source_signal_is_classified_without_creating_a_second_signal() -> None:
    result = discover(
        [
            _input(
                "github",
                "repository",
                SignalType.NEW_REPOSITORY,
                {"repository": {"description": "A prototype for a startup"}},
            )
        ]
    )
    assert len(result.classifications) == 1
    assert result.classifications[0].category == "technology"
    assert result.classifications[0].source_signal_type == SignalType.NEW_REPOSITORY.value
    assert result.derived_signals == []


def test_text_mention_is_derived_once_with_rule_and_provenance() -> None:
    item = _input(
        "university",
        "news",
        SignalType.NEW_PRESS_RELEASE,
        {"title": "A university spin-out was founded in 2024"},
    )
    result = discover([item, item])
    assert len(result.derived_signals) == 2
    by_type = {signal.signal_type.value: signal for signal in result.derived_signals}
    assert set(by_type) == {
        SignalType.FOUNDING_ACTIVITY_MENTION.value,
        SignalType.SPINOUT_MENTION.value,
    }
    for draft in by_type.values():
        assert draft.entity_id == item.entity_id
        assert draft.source_record_id == item.source_record_id
        assert draft.properties["source_signal_id"] == str(item.source_signal_id)
        assert draft.properties["discovery_rule_version"] == "1"
        assert draft.properties["matched_field"] == "title"


def test_funding_source_signal_is_not_reclassified_as_equity_or_startup() -> None:
    result = discover(
        [
            _input(
                "cordis",
                "project",
                SignalType.NEW_FUNDING_PROJECT,
                {"title": "A funded research project"},
            )
        ]
    )
    assert len(result.classifications) == 1
    assert result.classifications[0].category == "public_research_or_program_context"
    assert result.derived_signals == []


def test_only_single_record_anchor_signals_generate_text_rules() -> None:
    result = discover(
        [
            _input(
                "github",
                "repository",
                SignalType.NEW_CONTRIBUTOR,
                {"repository": {"description": "Commercial launch"}},
            )
        ]
    )
    assert result.classifications[0].category == "developer_activity"
    assert result.derived_signals == []
    assert result.scopes == set()


def test_single_observation_is_classified_without_a_growth_claim() -> None:
    observation = ObservationInput(
        observation_id=uuid4(),
        source_record_id=uuid4(),
        entity_id=uuid4(),
        source_name="github",
        metric_name="stars",
        metric_value=Decimal(0),
        metric_unit="count",
        observed_at=datetime(2026, 11, 20, tzinfo=UTC),
    )
    result = discover([], [observation])
    assert len(result.observation_classifications) == 1
    classified = result.observation_classifications[0]
    assert classified.observation_id == observation.observation_id
    assert classified.metric_value == Decimal(0)
    assert classified.category == "technology"
    assert classified.strength == "weak"
    assert "does not establish growth" in classified.interpretation
    assert result.derived_signals == []
