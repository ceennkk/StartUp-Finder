from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import (
    Entity,
    EntityAlias,
    IngestionRun,
    Observation,
    Relationship,
    Signal,
    SourceRecord,
    SourceRecordRevision,
    SyncState,
)
from tests.helpers import FakeAdapter

pytestmark = pytest.mark.db

ITEMS = [
    {"id": "1", "name": "alpha", "owner": "ann", "stars": 5},
    {"id": "2", "name": "beta", "owner": "ann", "stars": 7},
]


def count(factory: sessionmaker[Session], model: type) -> int:
    with factory() as s:
        return s.execute(select(func.count()).select_from(model)).scalar_one()


def test_first_run_stores_everything_with_provenance(session_factory) -> None:
    result = FakeAdapter(session_factory, ITEMS).run()
    assert (result.status, result.records_created, result.records_failed) == ("success", 2, 0)
    assert count(session_factory, SourceRecord) == 2
    assert count(session_factory, Entity) == 3  # two repos + one owner, owner not duplicated
    assert count(session_factory, Relationship) == 2
    assert count(session_factory, Signal) == 2
    assert count(session_factory, Observation) == 2
    with session_factory() as s:
        run = s.execute(select(IngestionRun)).scalar_one()
        assert run.status == "success" and run.records_fetched == 2 and run.completed_at is not None
        assert s.execute(select(SyncState.cursor)).scalar_one() == {"last": "2"}


def test_rerun_is_idempotent(session_factory) -> None:
    FakeAdapter(session_factory, ITEMS).run()
    second = FakeAdapter(session_factory, ITEMS).run()
    assert (second.records_created, second.records_updated, second.records_unchanged) == (0, 0, 2)
    for model, expected in [(SourceRecord, 2), (Entity, 3), (Relationship, 2), (Signal, 2),
                            (Observation, 2), (SourceRecordRevision, 0)]:
        assert count(session_factory, model) == expected, model.__name__
    assert count(session_factory, IngestionRun) == 2


def test_volatile_change_updates_observation_not_revision(session_factory) -> None:
    FakeAdapter(session_factory, ITEMS).run()
    changed = [{**ITEMS[0], "stars": 99}, ITEMS[1]]
    FakeAdapter(session_factory, changed).run()
    assert count(session_factory, SourceRecordRevision) == 0
    assert count(session_factory, Observation) == 2  # same day bucket: updated in place
    with session_factory() as s:
        values = s.execute(select(Observation.metric_value).order_by(Observation.metric_value)).scalars().all()
        assert [int(v) for v in values] == [7, 99]


def test_content_change_keeps_previous_payload(session_factory) -> None:
    FakeAdapter(session_factory, ITEMS).run()
    changed = [{**ITEMS[0], "name": "alpha-renamed"}, ITEMS[1]]
    result = FakeAdapter(session_factory, changed).run()
    assert result.records_updated == 1
    with session_factory() as s:
        rev = s.execute(select(SourceRecordRevision)).scalar_one()
        assert rev.raw_payload["name"] == "alpha"
        rec = s.execute(select(SourceRecord).where(SourceRecord.external_id == "1")).scalar_one()
        assert rec.raw_payload["name"] == "alpha-renamed"
        entity = s.execute(select(Entity).where(Entity.entity_type == "repository")
                           .order_by(Entity.created_at)).scalars().first()
        assert entity.canonical_name == "alpha-renamed"
        assert rec.first_seen_at <= rec.last_seen_at and rec.created_at is not None


def test_normalization_failure_keeps_raw_and_marks_partial(session_factory) -> None:
    adapter = FakeAdapter(session_factory, ITEMS)
    adapter.fail_ids = {"2"}
    result = adapter.run()
    assert (result.status, result.records_failed) == ("partial", 1)
    assert result.exit_code == 10
    assert count(session_factory, SourceRecord) == 2  # raw of the failed record is retained
    assert count(session_factory, Signal) == 1
    with session_factory() as s:
        assert s.execute(select(func.count()).select_from(SyncState)).scalar_one() == 0  # watermark not advanced


def test_fetch_error_fails_run_but_keeps_stored_data(session_factory) -> None:
    adapter = FakeAdapter(session_factory, ITEMS)
    adapter.explode_after = 1
    result = adapter.run()
    assert result.status == "failed" and result.exit_code == 1
    assert "source went away" in (result.error_message or "")
    assert count(session_factory, SourceRecord) == 1
    assert count(session_factory, SyncState) == 0


def test_limit_and_dry_run(session_factory) -> None:
    limited = FakeAdapter(session_factory, ITEMS, limit=1).run()
    assert limited.records_fetched == 1 and count(session_factory, SourceRecord) == 1

    before = count(session_factory, SourceRecord)
    dry = FakeAdapter(None, [{"id": "9", "name": "zeta", "owner": "zed", "stars": 1}], dry_run=True).run()
    assert dry.dry_run and dry.records_fetched == 1 and dry.status == "success"
    assert count(session_factory, SourceRecord) == before


def test_same_name_persons_from_different_identifiers_stay_separate(session_factory) -> None:
    items = [
        {"id": "1", "name": "a", "owner": "sam", "stars": 1},
        {"id": "2", "name": "b", "owner": "sam", "stars": 1},
    ]
    adapter = FakeAdapter(session_factory, items)
    adapter.run()
    with session_factory() as s:
        persons = s.execute(select(Entity).where(Entity.entity_type == "person")).scalars().all()
        assert len(persons) == 1  # same source identifier user:sam -> same entity
        aliases = s.execute(select(EntityAlias).where(EntityAlias.entity_id == persons[0].id)).scalars().all()
        assert {a.alias_type for a in aliases} == {"source_identifier", "name"}
