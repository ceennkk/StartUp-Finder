from __future__ import annotations

import uuid
from unittest.mock import Mock

from sqlalchemy.dialects import postgresql

from app.database.llm_repository import LLMAnalysisRepository
from app.llm.allowlist import CuratedLLMInput
from app.llm.analyzer import EarlySignalAnalysis, EarlySignalAnalysisRun
from app.llm.provider import LLMUsage


def _input() -> CuratedLLMInput:
    return CuratedLLMInput(
        source_name="synthetic",
        source_scope="synthetic",
        record_type="fixture",
        fields={"title": "Synthetic fixture"},
        input_hash="d" * 64,
    )


def _run() -> EarlySignalAnalysisRun:
    return EarlySignalAnalysisRun(
        analysis=EarlySignalAnalysis(uncertainties=["Synthetic fixture only."]),
        analyzer_version="analyzer-v1",
        prompt_version="prompt-v1",
        schema_version="schema-v1",
        provider_name="fake",
        model_version="fake-v1",
        usage=LLMUsage(input_tokens=10, output_tokens=4),
    )


def test_success_insert_is_immutable_and_idempotent_by_full_identity() -> None:
    session = Mock()
    session.execute.return_value.scalar_one_or_none.return_value = uuid.uuid4()
    repository = LLMAnalysisRepository(session)

    inserted = repository.record_success(uuid.uuid4(), _input(), _run())

    assert inserted
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "ON CONFLICT" in sql
    assert "validation_status = 'valid'" in sql
    assert "result_json" in sql
    assert "fake-v1" in compiled.params.values()


def test_duplicate_success_returns_false_on_conflict() -> None:
    session = Mock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    inserted = LLMAnalysisRepository(session).record_success(uuid.uuid4(), _input(), _run())

    assert inserted is False


def test_success_lookup_requires_all_versions_and_exact_input_hash() -> None:
    session = Mock()
    session.scalar.return_value = uuid.uuid4()
    repository = LLMAnalysisRepository(session)

    found = repository.has_successful_analysis(
        uuid.uuid4(),
        _input(),
        analyzer_version="analyzer-v1",
        prompt_version="prompt-v1",
        schema_version="schema-v1",
        provider_name="fake",
        model_version="fake-v1",
    )

    assert found
    compiled = session.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    for column in (
        "source_record_id",
        "input_hash",
        "analyzer_version",
        "prompt_version",
        "schema_version",
        "provider_name",
        "model_version",
        "validation_status",
    ):
        assert column in sql
    assert "d" * 64 in compiled.params.values()


def test_failure_attempt_stores_no_result_or_raw_error() -> None:
    session = Mock()
    repository = LLMAnalysisRepository(session)
    record_id = uuid.uuid4()

    repository.record_failure(
        record_id,
        _input(),
        analyzer_version="analyzer-v1",
        prompt_version="prompt-v1",
        schema_version="schema-v1",
        provider_name="fake",
        model_version="fake-v1",
        status="failed",
        error_code="provider_error",
    )

    attempt = session.add.call_args.args[0]
    assert attempt.source_record_id == record_id
    assert attempt.result_json is None
    assert attempt.validation_status == "failed"
    assert attempt.error_code == "provider_error"
    assert attempt.estimated_cost_usd is None
    session.flush.assert_called_once_with()
