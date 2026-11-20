from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.llm_repository import LLMAnalysisRepository
from app.database.models import Source, SourceRecord
from app.llm.allowlist import LLMInputBlocked, build_curated_input
from app.llm.analyzer import (
    EarlySignalLLMAnalyzer,
    LLMAnalysisValidationError,
)
from app.llm.fake_provider import FakeLLMProvider
from app.llm.provider import LLMProviderError

SYNTHETIC_SOURCE_PREFIX = "synthetic_"


@dataclass(frozen=True)
class LLMRecordOutcome:
    source_record_id: uuid.UUID
    source_name: str
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class LLMRunSummary:
    mode: str
    outcomes: tuple[LLMRecordOutcome, ...]

    def counts(self) -> dict[str, int]:
        return {
            "records_scanned": len(self.outcomes),
            "eligible": sum(item.status == "eligible" for item in self.outcomes),
            "blocked": sum(item.status == "blocked" for item in self.outcomes),
            "already_analyzed": sum(item.status == "already_analyzed" for item in self.outcomes),
            "persisted": sum(item.status == "persisted" for item in self.outcomes),
            "failed": sum(item.status == "failed" for item in self.outcomes),
        }


def load_llm_source_records(
    session: Session,
    *,
    source_name: str | None = None,
    limit: int = 500,
) -> list[tuple[SourceRecord, str]]:
    stmt = (
        select(SourceRecord, Source.source_name)
        .join(Source, Source.id == SourceRecord.source_id)
        .order_by(SourceRecord.first_seen_at, SourceRecord.id)
        .limit(limit)
    )
    if source_name is not None:
        stmt = stmt.where(Source.source_name == source_name)
    return [(record, name) for record, name in session.execute(stmt).all()]


def preview_llm_records(records: list[tuple[SourceRecord, str]]) -> LLMRunSummary:
    outcomes: list[LLMRecordOutcome] = []
    for record, source_name in records:
        try:
            build_curated_input(
                source_name=source_name,
                record_type=record.record_type,
                raw_payload=record.raw_payload,
            )
        except LLMInputBlocked:
            outcomes.append(LLMRecordOutcome(record.id, source_name, "blocked", "source not approved"))
            continue
        if not source_name.startswith(SYNTHETIC_SOURCE_PREFIX):
            outcomes.append(
                LLMRecordOutcome(
                    record.id,
                    source_name,
                    "blocked",
                    "the fake provider is restricted to synthetic source fixtures",
                )
            )
            continue
        outcomes.append(LLMRecordOutcome(record.id, source_name, "eligible"))
    return LLMRunSummary("preview", tuple(outcomes))


def run_llm_records(
    session: Session,
    records: list[tuple[SourceRecord, str]],
) -> LLMRunSummary:
    """Run only the built-in no-I/O fake provider; production allowlist is always loaded."""
    provider = FakeLLMProvider(lambda _request: {})
    analyzer = EarlySignalLLMAnalyzer(provider)
    repository = LLMAnalysisRepository(session)
    outcomes: list[LLMRecordOutcome] = []

    for record, source_name in records:
        try:
            curated_input = build_curated_input(
                source_name=source_name,
                record_type=record.record_type,
                raw_payload=record.raw_payload,
            )
        except LLMInputBlocked:
            outcomes.append(LLMRecordOutcome(record.id, source_name, "blocked", "source not approved"))
            continue
        if not source_name.startswith(SYNTHETIC_SOURCE_PREFIX):
            outcomes.append(
                LLMRecordOutcome(
                    record.id,
                    source_name,
                    "blocked",
                    "the fake provider is restricted to synthetic source fixtures",
                )
            )
            continue

        if repository.has_successful_analysis(
            record.id,
            curated_input,
            analyzer_version=analyzer.analyzer_version,
            prompt_version=analyzer.prompt_version,
            schema_version=analyzer.schema_version,
            provider_name=provider.provider_name,
            model_version=provider.model_version,
        ):
            outcomes.append(LLMRecordOutcome(record.id, source_name, "already_analyzed"))
            continue

        try:
            analysis_run = analyzer.analyze_with_metadata(curated_input)
        except LLMInputBlocked:
            outcomes.append(LLMRecordOutcome(record.id, source_name, "blocked", "LLM input authorization failed"))
        except LLMAnalysisValidationError as exc:
            repository.record_failure(
                record.id,
                curated_input,
                analyzer_version=analyzer.analyzer_version,
                prompt_version=analyzer.prompt_version,
                schema_version=analyzer.schema_version,
                provider_name=exc.provider_name,
                model_version=exc.model_version,
                status="invalid",
                error_code=exc.error_code,  # constrained safe category, not provider text
                input_tokens=exc.usage.input_tokens,
                output_tokens=exc.usage.output_tokens,
                estimated_cost_usd=exc.usage.estimated_cost_usd,
            )
            outcomes.append(LLMRecordOutcome(record.id, source_name, "failed", exc.error_code))
        except LLMProviderError:
            repository.record_failure(
                record.id,
                curated_input,
                analyzer_version=analyzer.analyzer_version,
                prompt_version=analyzer.prompt_version,
                schema_version=analyzer.schema_version,
                provider_name=provider.provider_name,
                model_version=provider.model_version,
                status="failed",
                error_code="provider_error",
            )
            outcomes.append(
                LLMRecordOutcome(record.id, source_name, "failed", "provider_error")
            )
        else:
            inserted = repository.record_success(record.id, curated_input, analysis_run)
            outcomes.append(
                LLMRecordOutcome(
                    record.id,
                    source_name,
                    "persisted" if inserted else "already_analyzed",
                )
            )

    return LLMRunSummary("run", tuple(outcomes))
