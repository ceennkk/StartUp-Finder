from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings


class DatabaseConfigError(RuntimeError):
    pass


def normalize_database_url(url: str) -> str:
    """Neon hands out postgresql:// URLs; force the psycopg 3 driver."""
    parsed = make_url(url)
    if parsed.drivername in ("postgresql", "postgres"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed.render_as_string(hide_password=False)


def make_engine(url: str | None = None, *, direct: bool = False) -> Engine:
    settings = get_settings()
    chosen = url or (settings.database_url_direct if direct else None) or settings.database_url
    if not chosen:
        raise DatabaseConfigError("DATABASE_URL is not set (see .env.example)")
    # pre_ping + recycle cope with Neon scale-to-zero closing idle connections.
    return create_engine(
        normalize_database_url(chosen),
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"connect_timeout": 15},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("select version()")).scalar_one()
