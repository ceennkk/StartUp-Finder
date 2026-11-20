from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database.models import LLMAnalysis
from app.llm.analyzer import EarlySignalAnalysisRun
from app.llm.allowlist import CuratedLLMInput

FailureStatus = Literal["invalid", "failed"]
FailureCode = Literal["provider_error", "output_schema_invalid", "evidence_invalid"]


class LLMAnalysisRepository:
    """Persists immutable analysis attempts; successful identities are idempotent."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _identity(
        source_record_id: uuid.UUID,
        curated_input: CuratedLLMInput,
        run: EarlySignalAnalysisRun,
    ) -> dict[str, object]:
        return {
            "source_record_id": source_record_id,
            "input_hash": curated_input.input_hash,
            "analyzer_version": run.analyzer_version,
            "prompt_version": run.prompt_version,
            "schema_version": run.schema_version,
            "provider_name": run.provider_name,
            "model_version": run.model_version,
        }

    def has_successful_analysis(
        self,
        source_record_id: uuid.UUID,
        curated_input: CuratedLLMInput,
        *,
        analyzer_version: str,
        prompt_version: str,
        schema_version: str,
        provider_name: str,
        model_version: str,
    ) -> bool:
        identity = {
            "source_record_id": source_record_id,
            "input_hash": curated_input.input_hash,
            "analyzer_version": analyzer_version,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "provider_name": provider_name,
            "model_version": model_version,
        }
        stmt = select(LLMAnalysis.id).where(
            *(getattr(LLMAnalysis, key) == value for key, value in identity.items()),
            LLMAnalysis.validation_status == "valid",
        )
        return self.session.scalar(stmt) is not None

    def record_success(
        self,
        source_record_id: uuid.UUID,
        curated_input: CuratedLLMInput,
        run: EarlySignalAnalysisRun,
    ) -> bool:
        values = {
            **self._identity(source_record_id, curated_input, run),
            "result_json": run.analysis.model_dump(mode="json"),
            "validation_status": "valid",
            "input_tokens": run.usage.input_tokens,
            "output_tokens": run.usage.output_tokens,
            "estimated_cost_usd": run.usage.estimated_cost_usd,
        }
        stmt = (
            insert(LLMAnalysis)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    LLMAnalysis.source_record_id,
                    LLMAnalysis.input_hash,
                    LLMAnalysis.analyzer_version,
                    LLMAnalysis.prompt_version,
                    LLMAnalysis.schema_version,
                    LLMAnalysis.provider_name,
                    LLMAnalysis.model_version,
                ],
                index_where=text("validation_status = 'valid'"),
            )
            .returning(LLMAnalysis.id)
        )
        return self.session.execute(stmt).scalar_one_or_none() is not None

    def record_failure(
        self,
        source_record_id: uuid.UUID,
        curated_input: CuratedLLMInput,
        *,
        analyzer_version: str,
        prompt_version: str,
        schema_version: str,
        provider_name: str,
        model_version: str,
        status: FailureStatus,
        error_code: FailureCode,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
    ) -> None:
        self.session.add(
            LLMAnalysis(
                source_record_id=source_record_id,
                input_hash=curated_input.input_hash,
                analyzer_version=analyzer_version,
                prompt_version=prompt_version,
                schema_version=schema_version,
                provider_name=provider_name,
                model_version=model_version,
                result_json=None,
                validation_status=status,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost_usd,
                error_code=error_code,
            )
        )
        self.session.flush()
