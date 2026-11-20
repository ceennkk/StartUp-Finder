from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.database.models import Signal
from app.database.repositories import IngestionRepository
from app.discovery.types import DiscoverySignalDraft
from app.domain import SignalType


class _Result:
    def __init__(self, rows=()):
        self._rows = rows

    def scalars(self):
        return iter(self._rows)

    def all(self):
        return []


class _RecordingSession:
    def __init__(self, rows=()):
        self.rows = rows
        self.statements = []
        self.deleted = []

    def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return _Result(self.rows)

    def delete(self, value):
        self.deleted.append(value)


def _draft(
    entity_id,
    source_record_id,
    version: str,
) -> DiscoverySignalDraft:
    return DiscoverySignalDraft(
        signal_type=SignalType.FOUNDING_ACTIVITY_MENTION,
        source_record_id=source_record_id,
        entity_id=entity_id,
        published_at=None,
        properties={"discovery_rule_id": "founding-activity-mention", "discovery_rule_version": version},
        description="Founding activity mention detected.",
    )


def test_persistence_uses_existing_unique_constraint_and_upserts_rule_version() -> None:
    session = _RecordingSession()
    repo = IngestionRepository(session)
    entity_id, record_id = uuid4(), uuid4()
    repo.reconcile_discovery_signals(
        entity_id=entity_id,
        source_record_id=record_id,
        derived_signals=[_draft(entity_id, record_id, "1")],
        rule_ids=("founding-activity-mention",),
        now=datetime(2026, 11, 20, tzinfo=UTC),
    )
    repo.reconcile_discovery_signals(
        entity_id=entity_id,
        source_record_id=record_id,
        derived_signals=[_draft(entity_id, record_id, "2")],
        rule_ids=("founding-activity-mention",),
        now=datetime(2026, 11, 21, tzinfo=UTC),
    )

    insert_statements = session.statements[1::2]
    assert len(insert_statements) == 2
    compiled = [str(stmt.compile(dialect=postgresql.dialect())) for stmt in insert_statements]
    assert all(
        "ON CONFLICT ON CONSTRAINT uq_signals_entity_type_record DO UPDATE" in sql
        for sql in compiled
    )
    assert insert_statements[0].compile(dialect=postgresql.dialect()).params["signal_type"] == (
        SignalType.FOUNDING_ACTIVITY_MENTION.value
    )
    assert insert_statements[1].compile(dialect=postgresql.dialect()).params["properties"][
        "discovery_rule_version"
    ] == "2"


def test_reconciliation_deletes_only_stale_derived_rows() -> None:
    stale = Signal(
        entity_id=uuid4(),
        source_record_id=uuid4(),
        signal_type=SignalType.FOUNDING_ACTIVITY_MENTION.value,
        properties={"discovery_rule_id": "founding-activity-mention"},
    )
    source_signal = Signal(
        entity_id=stale.entity_id,
        source_record_id=stale.source_record_id,
        signal_type=SignalType.NEW_PRESS_RELEASE.value,
        properties={},
    )
    session = _RecordingSession([stale, source_signal])
    repo = IngestionRepository(session)
    repo.reconcile_discovery_signals(
        entity_id=stale.entity_id,
        source_record_id=stale.source_record_id,
        derived_signals=[],
        rule_ids=("founding-activity-mention",),
        now=datetime(2026, 11, 20, tzinfo=UTC),
    )
    assert session.deleted == [stale]


def test_discovery_reader_selects_source_signals_not_derived_rows() -> None:
    session = _RecordingSession()
    repo = IngestionRepository(session)
    assert repo.list_discovery_inputs(limit=2) == []
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "discovery_rule_id" in compiled.params.values()
    assert "IS NULL" in sql
    assert "LIMIT" in sql
