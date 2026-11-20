from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain import (
    AliasType,
    EntityType,
    RelationshipType,
    SignalType,
    SourceType,
    VerificationStatus,
)


class SourceSpec(BaseModel):
    """Static description of a data source (row in `sources`)."""

    model_config = ConfigDict(frozen=True)

    source_name: str
    source_type: SourceType
    base_url: str | None = None
    description: str | None = None
    terms_url: str | None = None


class RawRecord(BaseModel):
    """One unit of original source data, exactly as received (JSON-serializable)."""

    external_id: str
    record_type: str
    payload: dict[str, Any]
    canonical_url: str | None = None
    published_at: datetime | None = None
    # Top-level payload keys excluded from the content hash because their changes are tracked as observations.
    volatile_keys: frozenset[str] = frozenset()
    # When set, the content hash is computed from this stable view instead of the whole payload.
    hash_basis: dict[str, Any] | None = None

    @field_validator("external_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("external_id must not be blank")
        return value


class AliasDraft(BaseModel):
    alias: str
    alias_type: AliasType = AliasType.NAME
    external_identifier: str | None = None


class EntityDraft(BaseModel):
    """Normalized entity. `identifier` is the source-scoped key; entities are never merged across sources."""

    key: str  # reference inside this bundle
    identifier: str  # unique within the source, e.g. "repo:123"
    entity_type: EntityType
    canonical_name: str
    description: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    aliases: list[AliasDraft] = Field(default_factory=list)
    # Primary entities are described by the record itself and may overwrite their normalized fields;
    # referenced entities (e.g. an author listed on a paper) are only created or have gaps filled.
    is_primary: bool = False
    extraction_method: str = "source_field"

    @field_validator("canonical_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("canonical_name must not be blank")
        return value


class RelationshipDraft(BaseModel):
    source_key: str
    target_key: str
    relationship_type: RelationshipType
    verification_status: VerificationStatus = VerificationStatus.SOURCE_ASSERTED
    confidence: Decimal | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class SignalDraft(BaseModel):
    entity_key: str
    signal_type: SignalType
    description: str | None = None
    event_date: datetime | None = None
    published_at: datetime | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ObservationDraft(BaseModel):
    entity_key: str
    metric_name: str
    value: Decimal
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedBundle(BaseModel):
    entities: list[EntityDraft] = Field(default_factory=list)
    relationships: list[RelationshipDraft] = Field(default_factory=list)
    signals: list[SignalDraft] = Field(default_factory=list)
    observations: list[ObservationDraft] = Field(default_factory=list)


class ValidationProblem(ValueError):
    pass


class RunResult(BaseModel):
    source_name: str
    status: str
    dry_run: bool = False
    run_id: str | None = None
    records_fetched: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_unchanged: int = 0
    records_failed: int = 0
    error_message: str | None = None

    @property
    def exit_code(self) -> int:
        return {"success": 0, "partial": 10, "failed": 1}.get(self.status, 1)
