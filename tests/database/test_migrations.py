from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect

from app.database.models import Base

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "sources", "ingestion_runs", "source_records", "source_record_revisions", "entities",
    "entity_aliases", "entity_source_records", "relationships", "signals", "observations", "sync_state",
}


def test_all_tables_exist(engine: Engine) -> None:
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_models_match_migrations(engine: Engine) -> None:
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []


def test_downgrade_and_upgrade_roundtrip(engine: Engine, alembic_cfg) -> None:
    command.downgrade(alembic_cfg, "base")
    assert "entities" not in inspect(engine).get_table_names()
    command.upgrade(alembic_cfg, "head")
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
