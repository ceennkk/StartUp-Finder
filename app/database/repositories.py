from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database.models import (
    Entity,
    EntityAlias,
    EntitySourceRecord,
    IngestionRun,
    Observation,
    Relationship,
    Signal,
    Source,
    SourceRecord,
    SourceRecordRevision,
    SyncState,
)
from app.discovery.types import DiscoveryInput, DiscoverySignalDraft, ObservationInput
from app.domain import AliasType, RunStatus
from app.ingestion.types import EntityDraft, NormalizedBundle, RawRecord, SourceSpec
from app.utils.dates import bucket_time
from app.utils.hashing import content_hash


@dataclass
class StoredRecord:
    record: SourceRecord
    status: str  # created | updated | unchanged


class IngestionRepository:
    """All writes of the ingestion layer. Every write is an upsert so repeated runs stay idempotent."""

    def __init__(self, session: Session):
        self.session = session

    # --- sources and runs -------------------------------------------------

    def ensure_source(self, spec: SourceSpec) -> Source:
        stmt = (
            insert(Source)
            .values(
                source_name=spec.source_name,
                source_type=spec.source_type.value,
                base_url=spec.base_url,
                description=spec.description,
                terms_url=spec.terms_url,
            )
            .on_conflict_do_update(
                index_elements=[Source.source_name],
                set_={
                    "source_type": spec.source_type.value,
                    "base_url": spec.base_url,
                    "description": spec.description,
                    "terms_url": spec.terms_url,
                },
            )
            .returning(Source)
        )
        return self.session.execute(stmt, execution_options={"populate_existing": True}).scalar_one()

    def start_run(self, source_id: uuid.UUID, started_at: datetime, metadata: dict[str, Any]) -> IngestionRun:
        run = IngestionRun(
            source_id=source_id, started_at=started_at, status=RunStatus.RUNNING.value, run_metadata=metadata
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_run(
        self,
        run: IngestionRun,
        *,
        status: RunStatus,
        completed_at: datetime,
        fetched: int,
        created: int,
        updated: int,
        failed: int,
        error_message: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        run.status = status.value
        run.completed_at = completed_at
        run.records_fetched = fetched
        run.records_created = created
        run.records_updated = updated
        run.records_failed = failed
        run.error_message = error_message
        if metadata:
            run.run_metadata = {**run.run_metadata, **metadata}
        self.session.flush()

    # --- raw records ------------------------------------------------------

    def upsert_source_record(
        self, source_id: uuid.UUID, run_id: uuid.UUID | None, raw: RawRecord, now: datetime
    ) -> StoredRecord:
        digest = content_hash(raw.hash_basis if raw.hash_basis is not None else raw.payload, raw.volatile_keys)
        inserted = self.session.execute(
            insert(SourceRecord)
            .values(
                source_id=source_id,
                external_id=raw.external_id,
                record_type=raw.record_type,
                canonical_url=raw.canonical_url,
                raw_payload=raw.payload,
                content_hash=digest,
                published_at=raw.published_at,
                first_seen_at=now,
                last_seen_at=now,
                updated_at=now,
                last_ingestion_run_id=run_id,
            )
            .on_conflict_do_nothing(constraint="uq_source_records_source_external")
            .returning(SourceRecord.id)
        ).scalar_one_or_none()
        if inserted is not None:
            return StoredRecord(self.session.get_one(SourceRecord, inserted), "created")

        existing = self.session.execute(
            select(SourceRecord)
            .where(SourceRecord.source_id == source_id, SourceRecord.external_id == raw.external_id)
            .with_for_update()
        ).scalar_one()
        existing.last_seen_at = now
        existing.last_ingestion_run_id = run_id
        if existing.content_hash == digest:
            # Only volatile fields differ; their history lives in observations, so no revision is kept.
            if existing.raw_payload != raw.payload:
                existing.raw_payload = raw.payload
                existing.updated_at = now
            return StoredRecord(existing, "unchanged")

        self.session.add(
            SourceRecordRevision(
                source_record_id=existing.id,
                ingestion_run_id=run_id,
                content_hash=existing.content_hash,
                raw_payload=existing.raw_payload,
                superseded_at=now,
            )
        )
        existing.raw_payload = raw.payload
        existing.content_hash = digest
        existing.record_type = raw.record_type
        existing.canonical_url = raw.canonical_url or existing.canonical_url
        existing.published_at = raw.published_at or existing.published_at
        existing.updated_at = now
        return StoredRecord(existing, "updated")

    # --- normalized data --------------------------------------------------

    def store_bundle(
        self,
        source_id: uuid.UUID,
        record: SourceRecord,
        bundle: NormalizedBundle,
        now: datetime,
        observation_bucket: str,
    ) -> None:
        entity_ids: dict[str, uuid.UUID] = {}
        for draft in bundle.entities:
            entity_ids[draft.key] = self._upsert_entity(source_id, record.id, draft, now)

        for rel in bundle.relationships:
            self.session.execute(
                insert(Relationship)
                .values(
                    source_entity_id=entity_ids[rel.source_key],
                    target_entity_id=entity_ids[rel.target_key],
                    relationship_type=rel.relationship_type.value,
                    confidence=rel.confidence,
                    verification_status=rel.verification_status.value,
                    source_record_id=record.id,
                    properties=rel.properties,
                    valid_from=rel.valid_from,
                    valid_until=rel.valid_until,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_relationships_edge_record",
                    set_={"last_seen_at": now, "properties": rel.properties},
                )
            )

        for sig in bundle.signals:
            self.session.execute(
                insert(Signal)
                .values(
                    entity_id=entity_ids[sig.entity_key],
                    source_record_id=record.id,
                    signal_type=sig.signal_type.value,
                    signal_description=sig.description,
                    event_date=sig.event_date,
                    published_at=sig.published_at,
                    first_seen_at=now,
                    properties=sig.properties,
                )
                .on_conflict_do_nothing(constraint="uq_signals_entity_type_record")
            )

        observed_at = bucket_time(now, observation_bucket)
        for obs in bundle.observations:
            # Core table insert: the ORM attribute for the `metadata` column is renamed.
            stmt = insert(Observation.__table__).values(
                entity_id=entity_ids[obs.entity_key],
                source_record_id=record.id,
                observed_at=observed_at,
                metric_name=obs.metric_name,
                metric_value=obs.value,
                metric_unit=obs.unit,
                metadata=obs.metadata,
            )
            self.session.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_observations_entity_metric_time",
                    set_={
                        "metric_value": stmt.excluded["metric_value"],
                        "metadata": stmt.excluded["metadata"],
                        "source_record_id": stmt.excluded["source_record_id"],
                    },
                )
            )

    def list_discovery_inputs(
        self, *, source_name: str | None = None, limit: int = 500
    ) -> list[DiscoveryInput]:
        stmt = (
            select(
                Signal.id,
                Signal.source_record_id,
                Signal.entity_id,
                Source.source_name,
                SourceRecord.record_type,
                Signal.signal_type,
                Signal.event_date,
                Signal.published_at,
                SourceRecord.raw_payload,
            )
            .join(SourceRecord, SourceRecord.id == Signal.source_record_id)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(Signal.properties["discovery_rule_id"].as_string().is_(None))
            .order_by(Signal.first_seen_at, Signal.id)
            .limit(limit)
        )
        if source_name:
            stmt = stmt.where(Source.source_name == source_name)

        return [
            DiscoveryInput(
                source_signal_id=signal_id,
                source_record_id=source_record_id,
                entity_id=entity_id,
                source_name=name,
                record_type=record_type,
                source_signal_type=signal_type,
                event_date=event_date,
                published_at=published_at,
                raw_payload=payload,
            )
            for (
                signal_id,
                source_record_id,
                entity_id,
                name,
                record_type,
                signal_type,
                event_date,
                published_at,
                payload,
            ) in self.session.execute(stmt).all()
        ]

    def list_discovery_observations(
        self, *, source_name: str | None = None, limit: int = 500
    ) -> list[ObservationInput]:
        stmt = (
            select(
                Observation.id,
                Observation.source_record_id,
                Observation.entity_id,
                Source.source_name,
                Observation.metric_name,
                Observation.metric_value,
                Observation.metric_unit,
                Observation.observed_at,
            )
            .join(SourceRecord, SourceRecord.id == Observation.source_record_id)
            .join(Source, Source.id == SourceRecord.source_id)
            .order_by(Observation.observed_at, Observation.id)
            .limit(limit)
        )
        if source_name:
            stmt = stmt.where(Source.source_name == source_name)

        return [
            ObservationInput(
                observation_id=observation_id,
                source_record_id=source_record_id,
                entity_id=entity_id,
                source_name=name,
                metric_name=metric_name,
                metric_value=metric_value,
                metric_unit=metric_unit,
                observed_at=observed_at,
            )
            for (
                observation_id,
                source_record_id,
                entity_id,
                name,
                metric_name,
                metric_value,
                metric_unit,
                observed_at,
            ) in self.session.execute(stmt).all()
        ]

    def reconcile_discovery_signals(
        self,
        *,
        entity_id: uuid.UUID,
        source_record_id: uuid.UUID,
        derived_signals: list[DiscoverySignalDraft],
        rule_ids: tuple[str, ...],
        now: datetime,
    ) -> int:
        desired = {draft.signal_type.value: draft for draft in derived_signals}
        if len(desired) != len(derived_signals):
            raise ValueError("only one derived signal per type is allowed for a source record and entity")
        if any(
            draft.entity_id != entity_id or draft.source_record_id != source_record_id
            for draft in derived_signals
        ):
            raise ValueError("derived signals must match the reconciled entity and source record")

        existing = self.session.execute(
            select(Signal)
            .where(Signal.entity_id == entity_id, Signal.source_record_id == source_record_id)
            .with_for_update()
        ).scalars()
        for signal in existing:
            rule_id = signal.properties.get("discovery_rule_id")
            if rule_id in rule_ids and signal.signal_type not in desired:
                self.session.delete(signal)

        for draft in desired.values():
            self.session.execute(
                insert(Signal)
                .values(
                    entity_id=entity_id,
                    source_record_id=source_record_id,
                    signal_type=draft.signal_type.value,
                    signal_description=draft.description,
                    event_date=None,
                    published_at=draft.published_at,
                    first_seen_at=now,
                    properties=draft.properties,
                )
                .on_conflict_do_update(
                    constraint="uq_signals_entity_type_record",
                    set_={
                        "signal_description": draft.description,
                        "published_at": draft.published_at,
                        "properties": draft.properties,
                    },
                )
            )
        return len(desired)

    def _upsert_entity(
        self, source_id: uuid.UUID, record_id: uuid.UUID, draft: EntityDraft, now: datetime
    ) -> uuid.UUID:
        entity = self.session.execute(
            select(Entity)
            .join(EntityAlias, EntityAlias.entity_id == Entity.id)
            .where(
                EntityAlias.source_id == source_id,
                EntityAlias.alias_type == AliasType.SOURCE_IDENTIFIER.value,
                EntityAlias.external_identifier == draft.identifier,
            )
        ).scalar_one_or_none()

        if entity is None:
            entity = Entity(
                entity_type=draft.entity_type.value,
                canonical_name=draft.canonical_name,
                description=draft.description,
                properties=draft.properties,
                created_at=now,
                updated_at=now,
            )
            self.session.add(entity)
            self.session.flush()
            self._add_alias(
                entity.id, draft.identifier, AliasType.SOURCE_IDENTIFIER, source_id, draft.identifier
            )
        elif draft.is_primary:
            merged = {**entity.properties, **draft.properties}
            if (entity.canonical_name, entity.description, entity.properties) != (
                draft.canonical_name,
                draft.description,
                merged,
            ):
                entity.canonical_name = draft.canonical_name
                entity.description = draft.description
                entity.properties = merged
                entity.updated_at = now
        else:
            merged = {**draft.properties, **entity.properties}
            if entity.description is None and draft.description:
                entity.description = draft.description
                entity.updated_at = now
            if merged != entity.properties:
                entity.properties = merged
                entity.updated_at = now

        self._add_alias(entity.id, draft.canonical_name, AliasType.NAME, source_id, None)
        for alias in draft.aliases:
            self._add_alias(entity.id, alias.alias, alias.alias_type, source_id, alias.external_identifier)

        self.session.execute(
            insert(EntitySourceRecord)
            .values(
                entity_id=entity.id,
                source_record_id=record_id,
                extraction_method=draft.extraction_method,
            )
            .on_conflict_do_nothing(constraint="uq_entity_source_records_entity_record")
        )
        return entity.id

    def _add_alias(
        self,
        entity_id: uuid.UUID,
        alias: str,
        alias_type: AliasType,
        source_id: uuid.UUID,
        external_identifier: str | None,
    ) -> None:
        self.session.execute(
            insert(EntityAlias)
            .values(
                entity_id=entity_id,
                alias=alias,
                alias_type=alias_type.value,
                source_id=source_id,
                external_identifier=external_identifier,
            )
            .on_conflict_do_nothing()
        )

    # --- sync state -------------------------------------------------------

    def get_cursor(self, source_id: uuid.UUID, scope_key: str) -> dict[str, Any] | None:
        return self.session.execute(
            select(SyncState.cursor).where(SyncState.source_id == source_id, SyncState.scope_key == scope_key)
        ).scalar_one_or_none()

    def set_cursor(self, source_id: uuid.UUID, scope_key: str, cursor: dict[str, Any]) -> None:
        stmt = insert(SyncState).values(source_id=source_id, scope_key=scope_key, cursor=cursor)
        self.session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_sync_state_source_scope",
                set_={"cursor": stmt.excluded.cursor, "updated_at": func.now()},
            )
        )

    # --- reporting --------------------------------------------------------

    def recent_runs(self, limit: int = 20, source_name: str | None = None) -> list[tuple[IngestionRun, str]]:
        stmt = (
            select(IngestionRun, Source.source_name)
            .join(Source, Source.id == IngestionRun.source_id)
            .order_by(IngestionRun.started_at.desc())
            .limit(limit)
        )
        if source_name:
            stmt = stmt.where(Source.source_name == source_name)
        return [(run, name) for run, name in self.session.execute(stmt).all()]

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for model in (Source, IngestionRun, SourceRecord, Entity, EntityAlias, EntitySourceRecord,
                      Relationship, Signal, Observation):
            counts[model.__tablename__] = self.session.execute(select(func.count()).select_from(model)).scalar_one()
        return counts
