from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import app as app_package
from app.database.connection import make_session_factory, normalize_database_url
from pathlib import Path

DEFAULT_TEST_URL = "postgresql+psycopg://ventureradar:ventureradar@127.0.0.1:5433/ventureradar_test"


def _alembic_cfg(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(app_package.__file__).parent / "database" / "migrations"))
    cfg.attributes["engine"] = engine
    return cfg


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = normalize_database_url(os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL))
    eng = create_engine(url, pool_pre_ping=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:  # no local Postgres: skip DB tests instead of failing the suite
        pytest.skip(f"test database unavailable: {exc}")
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_cfg(eng), "head")
    yield eng
    eng.dispose()


@pytest.fixture
def alembic_cfg(engine: Engine) -> Config:
    return _alembic_cfg(engine)


@pytest.fixture
def session_factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    with engine.begin() as conn:
        tables = conn.execute(
            text("select tablename from pg_tables where schemaname='public' and tablename <> 'alembic_version'")
        ).scalars().all()
        conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    yield make_session_factory(engine)
