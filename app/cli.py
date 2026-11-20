from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import SQLAlchemyError

import app as app_package
from app.adapters import registry
from app.adapters.base import AdapterConfigError
from app.config.settings import get_settings
from app.database.connection import (
    DatabaseConfigError,
    check_connection,
    make_engine,
    make_session_factory,
    session_scope,
)
from app.database.repositories import IngestionRepository
from app.ingestion.types import RunResult
from app.utils.logging import configure_logging

EXIT_OK, EXIT_FAILED, EXIT_CONFIG, EXIT_DB = 0, 1, 2, 3
EXIT_PARTIAL = 10

cli = typer.Typer(help="VentureRadar data ingestion", no_args_is_help=True, add_completion=False)
database_cli = typer.Typer(help="Database management", no_args_is_help=True)
ingestion_cli = typer.Typer(help="Ingestion run information", no_args_is_help=True)
cli.add_typer(database_cli, name="database")
cli.add_typer(ingestion_cli, name="ingestion")


@cli.callback()
def _setup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)


def _alembic_config() -> Config:
    migrations = Path(app_package.__file__).parent / "database" / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations))
    return cfg


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(json.dumps({"error": message}), err=False)
    return typer.Exit(code)


@database_cli.command("init")
def database_init() -> None:
    """Apply all migrations (alembic upgrade head)."""
    try:
        command.upgrade(_alembic_config(), "head")
    except DatabaseConfigError as exc:
        raise _fail(str(exc), EXIT_CONFIG) from exc
    except SQLAlchemyError as exc:
        raise _fail(f"database error: {exc}", EXIT_DB) from exc
    typer.echo(json.dumps({"status": "ok", "message": "database is at head"}))


@database_cli.command("status")
def database_status() -> None:
    """Show connection, migration state and row counts."""
    try:
        engine = make_engine()
        version = check_connection(engine)
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
        counts: dict[str, int] = {}
        if current:
            with session_scope(make_session_factory(engine)) as session:
                counts = IngestionRepository(session).table_counts()
    except DatabaseConfigError as exc:
        raise _fail(str(exc), EXIT_CONFIG) from exc
    except SQLAlchemyError as exc:
        raise _fail(f"database unreachable: {exc}", EXIT_DB) from exc
    typer.echo(
        json.dumps(
            {
                "connected": True,
                "server": version,
                "migration_current": current,
                "migration_head": head,
                "up_to_date": current == head,
                "row_counts": counts,
            },
            indent=2,
        )
    )


@ingestion_cli.command("history")
def ingestion_history(
    limit: Annotated[int, typer.Option(help="Number of runs to show")] = 20,
    source: Annotated[str | None, typer.Option(help="Filter by source name")] = None,
) -> None:
    """List recent collector runs."""
    try:
        factory = make_session_factory(make_engine())
        with session_scope(factory) as session:
            rows = IngestionRepository(session).recent_runs(limit, source)
            runs = [
                {
                    "run_id": str(run.id),
                    "source": name,
                    "status": run.status,
                    "started_at": run.started_at.isoformat(),
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "fetched": run.records_fetched,
                    "created": run.records_created,
                    "updated": run.records_updated,
                    "failed": run.records_failed,
                    "error": run.error_message,
                }
                for run, name in rows
            ]
    except DatabaseConfigError as exc:
        raise _fail(str(exc), EXIT_CONFIG) from exc
    except SQLAlchemyError as exc:
        raise _fail(f"database error: {exc}", EXIT_DB) from exc
    typer.echo(json.dumps(runs, indent=2))


def _exit_code(results: list[RunResult]) -> int:
    codes = [r.exit_code for r in results]
    if EXIT_FAILED in codes:
        return EXIT_FAILED
    return EXIT_PARTIAL if EXIT_PARTIAL in codes else EXIT_OK


@cli.command("collect")
def collect(
    collector: Annotated[str, typer.Argument(help="Collector name or 'all'")],
    limit: Annotated[int | None, typer.Option(help="Maximum number of records to fetch")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Fetch and normalize without writing to the database")] = False,
) -> None:
    """Run one collector (or all). Exit codes: 0 ok, 10 partial, 1 failed, 2 config, 3 database."""
    names = registry.available() if collector == "all" else [collector]
    if not names:
        raise _fail("no collectors registered", EXIT_CONFIG)

    factory = None
    if not dry_run:
        try:
            engine = make_engine()
            check_connection(engine)
            factory = make_session_factory(engine)
        except DatabaseConfigError as exc:
            raise _fail(str(exc), EXIT_CONFIG) from exc
        except SQLAlchemyError as exc:
            raise _fail(f"database unreachable: {exc}", EXIT_DB) from exc

    results: list[RunResult] = []
    for name in names:
        try:
            adapter = registry.get_adapter_class(name)(factory, limit=limit, dry_run=dry_run)
        except KeyError as exc:
            raise _fail(str(exc), EXIT_CONFIG) from exc
        except AdapterConfigError as exc:
            if collector != "all":
                raise _fail(f"{name}: {exc}", EXIT_CONFIG) from exc
            results.append(RunResult(source_name=name, status="failed", dry_run=dry_run, error_message=str(exc)))
            continue
        results.append(adapter.run())

    for result in results:
        typer.echo(result.model_dump_json())
    raise typer.Exit(_exit_code(results))


def main() -> None:
    try:
        cli()
    except DatabaseConfigError as exc:
        typer.echo(json.dumps({"error": str(exc)}))
        sys.exit(EXIT_CONFIG)


if __name__ == "__main__":
    main()
