from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain import EntityType, RunStatus, VerificationStatus, values

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _in_list(column: str, allowed: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in allowed)})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(_in_list("status", values(RunStatus)), name="status_valid"),
        Index("ix_ingestion_runs_source_started", "source_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_records_source_external"),
        Index("ix_source_records_type", "source_id", "record_type"),
        Index("ix_source_records_published_at", "published_at"),
        Index("ix_source_records_raw_payload", "raw_payload", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    record_type: Mapped[str] = mapped_column(String(50), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class SourceRecordRevision(Base):
    """Previous raw payloads, kept when a record's content hash changes."""

    __tablename__ = "source_record_revisions"
    __table_args__ = (Index("ix_source_record_revisions_record", "source_record_id", "superseded_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False
    )
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    superseded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint(_in_list("entity_type", values(EntityType)), name="entity_type_valid"),
        Index("ix_entities_type", "entity_type"),
        Index("ix_entities_properties", "properties", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    aliases: Mapped[list[EntityAlias]] = relationship(back_populates="entity", cascade="all, delete-orphan")


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("entity_id", "alias_type", "alias", name="uq_entity_aliases_entity_type_alias"),
        Index(
            "uq_entity_aliases_source_identifier",
            "source_id",
            "alias_type",
            "external_identifier",
            unique=True,
            postgresql_where=text("external_identifier IS NOT NULL"),
        ),
        Index("ix_entity_aliases_alias", "alias"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    external_identifier: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    entity: Mapped[Entity] = relationship(back_populates="aliases")


class EntitySourceRecord(Base):
    __tablename__ = "entity_source_records"
    __table_args__ = (
        UniqueConstraint("entity_id", "source_record_id", name="uq_entity_source_records_entity_record"),
        Index("ix_entity_source_records_record", "source_record_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False
    )
    extraction_method: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = _created_at()


class Relationship(Base):
    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
            "source_record_id",
            name="uq_relationships_edge_record",
        ),
        CheckConstraint(_in_list("verification_status", values(VerificationStatus)), name="verification_valid"),
        Index("ix_relationships_target", "target_entity_id", "relationship_type"),
        Index("ix_relationships_source", "source_entity_id", "relationship_type"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False)
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False
    )
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("entity_id", "signal_type", "source_record_id", name="uq_signals_entity_type_record"),
        Index("ix_signals_type_event_date", "signal_type", "event_date"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    signal_description: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created_at()


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("entity_id", "metric_name", "observed_at", name="uq_observations_entity_metric_time"),
        Index("ix_observations_metric_time", "metric_name", "observed_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    metric_unit: Mapped[str | None] = mapped_column(String(30))
    observation_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class LLMAnalysis(Base):
    __tablename__ = "llm_analyses"
    __table_args__ = (
        CheckConstraint(
            "validation_status IN ('valid', 'invalid', 'failed')",
            name="validation_status_valid",
        ),
        CheckConstraint(
            "(validation_status = 'valid' AND result_json IS NOT NULL AND error_code IS NULL) "
            "OR (validation_status IN ('invalid', 'failed') "
            "AND result_json IS NULL AND error_code IS NOT NULL)",
            name="result_matches_status",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('provider_error', 'output_schema_invalid', 'evidence_invalid')",
            name="error_code_valid",
        ),
        CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) "
            "AND (output_tokens IS NULL OR output_tokens >= 0) "
            "AND (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)",
            name="usage_nonnegative",
        ),
        Index(
            "uq_llm_analyses_success_identity",
            "source_record_id",
            "input_hash",
            "analyzer_version",
            "prompt_version",
            "schema_version",
            "provider_name",
            "model_version",
            unique=True,
            postgresql_where=text("validation_status = 'valid'"),
        ),
        Index("ix_llm_analyses_source_record", "source_record_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error_code: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = _created_at()


class SyncState(Base):
    """Incremental-sync watermarks, advanced only after a successful run."""

    __tablename__ = "sync_state"
    __table_args__ = (UniqueConstraint("source_id", "scope_key", name="uq_sync_state_source_scope"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    cursor: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
