from __future__ import annotations

from alembic import context

from app.database.connection import make_engine
from app.database.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # An engine passed via config.attributes lets tests target a different database.
    engine = context.config.attributes.get("engine") or make_engine(direct=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run_migrations_online()
