from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain import SignalType


@dataclass(frozen=True)
class DiscoveryInput:
    source_signal_id: UUID
    source_record_id: UUID
    entity_id: UUID
    source_name: str
    record_type: str
    source_signal_type: str
    event_date: datetime | None
    published_at: datetime | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class ObservationInput:
    observation_id: UUID
    source_record_id: UUID
    entity_id: UUID
    source_name: str
    metric_name: str
    metric_value: Decimal
    metric_unit: str | None
    observed_at: datetime


@dataclass(frozen=True)
class SourceSignalClassification:
    source_signal_id: UUID
    source_record_id: UUID
    entity_id: UUID
    source_name: str
    source_signal_type: str
    category: str
    strength: str
    interpretation: str


@dataclass(frozen=True)
class ObservationClassification:
    observation_id: UUID
    source_record_id: UUID
    entity_id: UUID
    source_name: str
    metric_name: str
    metric_value: Decimal
    metric_unit: str | None
    observed_at: datetime
    category: str
    strength: str
    interpretation: str


@dataclass(frozen=True)
class DiscoverySignalDraft:
    signal_type: SignalType
    source_record_id: UUID
    entity_id: UUID
    published_at: datetime | None
    properties: dict[str, Any]
    description: str


@dataclass(frozen=True)
class DiscoveryScope:
    source_record_id: UUID
    entity_id: UUID


@dataclass
class DiscoveryResult:
    classifications: list[SourceSignalClassification] = field(default_factory=list)
    observation_classifications: list[ObservationClassification] = field(default_factory=list)
    derived_signals: list[DiscoverySignalDraft] = field(default_factory=list)
    scopes: set[DiscoveryScope] = field(default_factory=set)
