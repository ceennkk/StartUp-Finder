from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.database.repositories import IngestionRepository
from app.discovery.catalog import (
    DISCOVERY_RULE_IDS,
    OBSERVATION_CLASSIFICATIONS,
    SOURCE_SIGNAL_CLASSIFICATIONS,
    TEXT_RULES,
    SignalStrength,
    find_text_rule_match,
)
from app.discovery.types import (
    DiscoveryInput,
    DiscoveryResult,
    DiscoveryScope,
    DiscoverySignalDraft,
    ObservationInput,
    ObservationClassification,
    SourceSignalClassification,
)
from app.domain import SignalType
from app.utils.dates import utcnow


def discover(
    inputs: list[DiscoveryInput], observations: list[ObservationInput] | None = None
) -> DiscoveryResult:
    result = DiscoveryResult()
    derived_by_key: dict[tuple[str, UUID, UUID], DiscoverySignalDraft] = {}

    for item in inputs:
        try:
            source_type = SignalType(item.source_signal_type)
        except ValueError:
            continue

        classification_rule = SOURCE_SIGNAL_CLASSIFICATIONS.get(source_type)
        if classification_rule is not None:
            result.classifications.append(
                SourceSignalClassification(
                    source_signal_id=item.source_signal_id,
                    source_record_id=item.source_record_id,
                    entity_id=item.entity_id,
                    source_name=item.source_name,
                    source_signal_type=source_type.value,
                    category=classification_rule.category.value,
                    strength=classification_rule.strength.value,
                    interpretation=classification_rule.interpretation,
                )
            )

        for rule in TEXT_RULES:
            match = find_text_rule_match(
                rule,
                item.source_name,
                item.record_type,
                item.raw_payload,
                source_type.value,
            )
            context_key = (rule.rule_id, item.source_record_id, item.entity_id)
            if (
                item.source_name,
                item.record_type,
                source_type.value,
            ) in {
                (context.source_name, context.record_type, context.anchor_signal_type)
                for context in rule.contexts
            }:
                result.scopes.add(DiscoveryScope(item.source_record_id, item.entity_id))
            if match is None or context_key in derived_by_key:
                continue
            field_path, term = match
            properties: dict[str, Any] = {
                "discovery_rule_id": rule.rule_id,
                "discovery_rule_version": rule.rule_version,
                "discovery_category": rule.category,
                "signal_strength": SignalStrength.WEAK.value,
                "matched_field": field_path,
                "matched_term": term,
                "source_signal_id": str(item.source_signal_id),
                "source_signal_type": source_type.value,
                "interpretation": "Text mention only; not independently verified.",
            }
            derived_by_key[context_key] = DiscoverySignalDraft(
                signal_type=rule.signal_type,
                source_record_id=item.source_record_id,
                entity_id=item.entity_id,
                published_at=item.published_at,
                properties=properties,
                description=f"{rule.category.replace('_', ' ').capitalize()} mention detected.",
            )

    for observation in observations or []:
        classification_rule = OBSERVATION_CLASSIFICATIONS.get(
            (observation.source_name, observation.metric_name)
        )
        if classification_rule is None:
            continue
        result.observation_classifications.append(
            ObservationClassification(
                observation_id=observation.observation_id,
                source_record_id=observation.source_record_id,
                entity_id=observation.entity_id,
                source_name=observation.source_name,
                metric_name=observation.metric_name,
                metric_value=observation.metric_value,
                metric_unit=observation.metric_unit,
                observed_at=observation.observed_at,
                category=classification_rule.category.value,
                strength=classification_rule.strength.value,
                interpretation=classification_rule.interpretation,
            )
        )

    result.derived_signals.extend(
        sorted(
            derived_by_key.values(),
            key=lambda draft: (
                str(draft.source_record_id),
                draft.signal_type.value,
                draft.properties["discovery_rule_id"],
            ),
        )
    )
    return result


def load_discovery(session: Session, *, source_name: str | None = None, limit: int = 500) -> DiscoveryResult:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    repository = IngestionRepository(session)
    inputs = repository.list_discovery_inputs(source_name=source_name, limit=limit)
    observations = repository.list_discovery_observations(source_name=source_name, limit=limit)
    return discover(inputs, observations)


def persist_discovery(
    session: Session, result: DiscoveryResult, *, now: datetime | None = None
) -> int:
    repository = IngestionRepository(session)
    derived_by_scope: dict[DiscoveryScope, list[DiscoverySignalDraft]] = {}
    for draft in result.derived_signals:
        scope = DiscoveryScope(draft.source_record_id, draft.entity_id)
        derived_by_scope.setdefault(scope, []).append(draft)

    persisted = 0
    observed_at = now or utcnow()
    for scope in sorted(result.scopes, key=lambda value: (str(value.source_record_id), str(value.entity_id))):
        persisted += repository.reconcile_discovery_signals(
            entity_id=scope.entity_id,
            source_record_id=scope.source_record_id,
            derived_signals=derived_by_scope.get(scope, []),
            rule_ids=DISCOVERY_RULE_IDS,
            now=observed_at,
        )
    return persisted
