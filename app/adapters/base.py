from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator
from itertools import islice
from typing import Any, ClassVar

from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, get_settings
from app.database.connection import session_scope
from app.database.models import IngestionRun, SourceRecord
from app.database.repositories import IngestionRepository
from app.domain import RunStatus
from app.http.client import PoliteHttpClient
from app.ingestion.types import (
    NormalizedBundle,
    RawRecord,
    RunResult,
    SourceSpec,
    ValidationProblem,
)
from app.utils.dates import utcnow

log = logging.getLogger(__name__)

COMMIT_EVERY = 50


class AdapterConfigError(RuntimeError):
    """Missing credentials or invalid collector configuration (CLI exit code 2)."""


class BaseAdapter(ABC):
    """Collect original source records; entity and relation extraction runs downstream."""

    name: ClassVar[str]
    source: ClassVar[SourceSpec]

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None,
        *,
        http: PoliteHttpClient | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        settings: Settings | None = None,
    ):
        if session_factory is None and not dry_run:
            raise ValueError("a database session factory is required unless dry_run=True")
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.http = http or PoliteHttpClient()
        self.limit = limit
        self.dry_run = dry_run
        self._source_id: uuid.UUID | None = None
        self._pending_cursors: dict[str, dict[str, Any]] = {}

    # --- interface to implement ------------------------------------------

    @abstractmethod
    def fetch(self) -> Iterator[RawRecord]:
        """Yield raw records, handling pagination and incremental windows."""

    # Adapter normalize() methods are retained for offline inspection only.
    # The production ingestion path never calls or persists their graph drafts.

    # --- default hooks ----------------------------------------------------

    def validate(self, bundle: NormalizedBundle) -> None:
        keys = [e.key for e in bundle.entities]
        if not keys:
            raise ValidationProblem("bundle contains no entities")
        if len(set(keys)) != len(keys):
            raise ValidationProblem("duplicate entity keys in bundle")
        known = set(keys)
        for rel in bundle.relationships:
            if rel.source_key not in known or rel.target_key not in known:
                raise ValidationProblem(f"relationship references unknown entity: {rel}")
        for item in (*bundle.signals, *bundle.observations):
            if item.entity_key not in known:
                raise ValidationProblem(f"item references unknown entity key {item.entity_key!r}")

    def store(
        self,
        repo: IngestionRepository,
        source_id: uuid.UUID,
        record: SourceRecord,
        bundle: NormalizedBundle,
    ) -> None:
        repo.store_bundle(source_id, record, bundle, utcnow(), self.settings.observation_bucket)

    # --- incremental sync -------------------------------------------------

    def get_cursor(self, scope_key: str) -> dict[str, Any] | None:
        """Last committed watermark for a scope; None in dry-run or on first run."""
        if self.dry_run or self._source_id is None or self.session_factory is None:
            return None
        with session_scope(self.session_factory) as session:
            return IngestionRepository(session).get_cursor(self._source_id, scope_key)

    def set_cursor(self, scope_key: str, cursor: dict[str, Any]) -> None:
        """Stage a watermark; it is persisted only if the whole run succeeds."""
        self._pending_cursors[scope_key] = cursor

    # --- orchestration ----------------------------------------------------

    def run(self) -> RunResult:
        result = RunResult(source_name=self.source.source_name, status="success", dry_run=self.dry_run)
        try:
            if self.dry_run:
                self._run_dry(result)
            else:
                self._run_stored(result)
        except Exception as exc:
            log.exception("collector failed", extra={"source": self.source.source_name})
            result.status = RunStatus.FAILED.value
            result.error_message = f"{type(exc).__name__}: {exc}"
        finally:
            self.http.close()
        return result

    def _limited(self) -> Iterator[RawRecord]:
        stream = self.fetch()
        return islice(stream, self.limit) if self.limit else stream

    def _run_dry(self, result: RunResult) -> None:
        for raw in self._limited():
            result.records_fetched += 1
        result.status = (RunStatus.PARTIAL if result.records_failed else RunStatus.SUCCESS).value

    def _run_stored(self, result: RunResult) -> None:
        assert self.session_factory is not None
        with session_scope(self.session_factory) as session:
            repo = IngestionRepository(session)
            source = repo.ensure_source(self.source)
            run = repo.start_run(source.id, utcnow(), {"limit": self.limit, "adapter": self.name})
            self._source_id, run_id = source.id, run.id
        source_id = self._source_id
        result.run_id = str(run_id)

        fatal: Exception | None = None
        session = self.session_factory()
        repo = IngestionRepository(session)
        since_commit = 0
        try:
            for raw in self._limited():
                result.records_fetched += 1
                try:
                    self._process(repo, session, run_id, raw, result)
                except Exception as exc:
                    result.records_failed += 1
                    log.warning(
                        "record failed",
                        extra={"external_id": raw.external_id, "error": f"{type(exc).__name__}: {exc}"},
                    )
                since_commit += 1
                if since_commit >= COMMIT_EVERY:
                    session.commit()
                    since_commit = 0
            session.commit()
        except Exception as exc:
            fatal = exc
            log.exception("fetch aborted", extra={"source": self.source.source_name})
            try:
                session.commit()  # keep everything already processed
            except Exception:
                session.rollback()
        finally:
            session.close()

        if fatal is not None:
            status = RunStatus.FAILED
            result.error_message = f"{type(fatal).__name__}: {fatal}"
        elif result.records_failed:
            status = RunStatus.PARTIAL if result.records_failed < result.records_fetched else RunStatus.FAILED
            result.error_message = f"{result.records_failed} record(s) failed"
        else:
            status = RunStatus.SUCCESS
        result.status = status.value

        with session_scope(self.session_factory) as session:
            repo = IngestionRepository(session)
            if status is RunStatus.SUCCESS:
                for scope_key, cursor in self._pending_cursors.items():
                    repo.set_cursor(source_id, scope_key, cursor)
            run_row = session.get_one(IngestionRun, run_id)
            repo.finish_run(
                run_row,
                status=status,
                completed_at=utcnow(),
                fetched=result.records_fetched,
                created=result.records_created,
                updated=result.records_updated,
                failed=result.records_failed,
                error_message=result.error_message,
                metadata={"unchanged": result.records_unchanged, "cursors": sorted(self._pending_cursors)},
            )

    def _process(
        self,
        repo: IngestionRepository,
        session: Session,
        run_id: uuid.UUID,
        raw: RawRecord,
        result: RunResult,
    ) -> None:
        assert self._source_id is not None
        # The adapter writes only the original record. A worker later sends it
        # to Graphiti for LLM-based entity extraction and identity resolution.
        with session.begin_nested():
            stored = repo.upsert_source_record(self._source_id, run_id, raw, utcnow())
        if stored.status == "created":
            result.records_created += 1
        elif stored.status == "updated":
            result.records_updated += 1
        else:
            result.records_unchanged += 1

