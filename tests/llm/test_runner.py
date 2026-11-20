from __future__ import annotations

import uuid

from unittest.mock import Mock

from app.database.models import SourceRecord
from app.llm.allowlist import LLMAllowlistConfig, SourceFieldApproval
from app.llm.runner import preview_llm_records, run_llm_records


def _record() -> SourceRecord:
    record = SourceRecord(
        source_id=uuid.uuid4(),
        external_id="synthetic-record",
        record_type="repository",
        raw_payload={"description": "synthetic input"},
        content_hash="e" * 64,
        first_seen_at="2026-01-01T00:00:00Z",
        last_seen_at="2026-01-01T00:00:00Z",
    )
    record.id = uuid.uuid4()
    return record


def test_preview_only_reports_denied_status_for_empty_product_allowlist() -> None:
    summary = preview_llm_records([(_record(), "github")])

    assert summary.mode == "preview"
    assert summary.counts() == {
        "records_scanned": 1,
        "eligible": 0,
        "blocked": 1,
        "already_analyzed": 0,
        "persisted": 0,
        "failed": 0,
    }
    assert summary.outcomes[0].status == "blocked"
    assert "not approved" in (summary.outcomes[0].reason or "")


def test_persistent_run_skips_unapproved_record_without_any_write_or_provider_call() -> None:
    session = Mock()

    summary = run_llm_records(session, [(_record(), "github")])

    assert summary.outcomes[0].status == "blocked"
    session.scalar.assert_not_called()
    session.execute.assert_not_called()
    session.add.assert_not_called()


def _synthetic_allowlist() -> LLMAllowlistConfig:
    return LLMAllowlistConfig(
        version=1,
        default_policy="deny",
        sources={
            "synthetic_github": SourceFieldApproval(
                fields=("description",),
                approved=True,
                purpose="synthetic test fixture",
                reviewed_at="2026-11-20",
                reviewed_by="test",
                terms_reference="synthetic",
                review_summary="synthetic input only; not a real source approval",
            )
        },
    )


def test_run_uses_fake_provider_for_synthetic_records_and_persists_validated_output(
    monkeypatch,
) -> None:
    from app.database.llm_repository import LLMAnalysisRepository

    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", _synthetic_allowlist)
    persisted: list[object] = []
    monkeypatch.setattr(LLMAnalysisRepository, "has_successful_analysis", lambda *_args, **_kw: False)
    monkeypatch.setattr(
        LLMAnalysisRepository,
        "record_success",
        lambda _self, record_id, curated, run: persisted.append((record_id, curated, run)) or True,
    )
    session = Mock()

    summary = run_llm_records(session, [(_record(), "synthetic_github")])

    assert summary.outcomes[0].status == "persisted"
    assert len(persisted) == 1
    _, curated, run = persisted[0]
    assert curated.fields == {"description": "synthetic input"}
    assert run.provider_name == "fake"
    assert run.analysis.model_dump(mode="json") == {
        "signals": [],
        "technology_fields": [],
        "application_areas": [],
        "product_hints": [],
        "founding_hints": [],
        "commercialization_hints": [],
        "uncertainties": [],
    }


def test_successful_identity_is_skipped_before_provider_call(monkeypatch) -> None:
    from app.database.llm_repository import LLMAnalysisRepository

    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", _synthetic_allowlist)
    monkeypatch.setattr(LLMAnalysisRepository, "has_successful_analysis", lambda *_args, **_kw: True)
    record_success = Mock()
    monkeypatch.setattr(LLMAnalysisRepository, "record_success", record_success)

    summary = run_llm_records(Mock(), [(_record(), "synthetic_github")])

    assert summary.outcomes[0].status == "already_analyzed"
    record_success.assert_not_called()
