from __future__ import annotations

import pytest

from app.llm.allowlist import (
    LLMAllowlistConfig,
    LLMInputBlocked,
    SourceFieldApproval,
    build_curated_input,
    load_llm_allowlist,
)


def _synthetic_approval(*fields: str) -> SourceFieldApproval:
    return SourceFieldApproval(
        fields=fields,
        approved=True,
        purpose="synthetic unit test only",
        reviewed_at="2026-11-20",
        reviewed_by="test fixture",
        terms_reference="synthetic fixture",
        review_summary="synthetic data; never an external processing approval",
    )


def test_checked_in_allowlist_is_empty_and_denies_by_default() -> None:
    allowlist = load_llm_allowlist()
    assert allowlist.default_policy == "deny"
    assert allowlist.sources == {}
    with pytest.raises(LLMInputBlocked):
        build_curated_input(
            source_name="github",
            record_type="repository",
            raw_payload={"description": "synthetic"},
        )


def test_only_configured_fields_are_in_curated_input(monkeypatch) -> None:
    allowlist = LLMAllowlistConfig(
        version=1,
        default_policy="deny",
        sources={"synthetic_github": _synthetic_approval("description", "topics[]")},
    )
    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", lambda: allowlist)
    result = build_curated_input(
        source_name="synthetic_github",
        record_type="repository",
        raw_payload={
            "description": "synthetic description",
            "topics": ["robotics", "synthetic"],
            "owner": {"login": "person-not-to-send"},
            "contributors": [{"name": "person-not-to-send"}],
        },
    )
    assert result.fields == {
        "description": "synthetic description",
        "topics[]": ["robotics", "synthetic"],
    }


def test_unapproved_or_incompletely_documented_fields_fail_closed(monkeypatch) -> None:
    incomplete = SourceFieldApproval(fields=("title",), approved=True, purpose="test")
    allowlist = LLMAllowlistConfig(
        version=1, default_policy="deny", sources={"synthetic_openalex": incomplete}
    )
    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", lambda: allowlist)
    with pytest.raises(LLMInputBlocked):
        build_curated_input(
            source_name="synthetic_openalex",
            record_type="work",
            raw_payload={"title": "synthetic"},
        )


def test_manual_import_is_blocked_even_if_allowlist_is_constructed(monkeypatch) -> None:
    allowlist = LLMAllowlistConfig(
        version=1,
        default_policy="deny",
        sources={"synthetic_github": _synthetic_approval("description")},
    )
    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", lambda: allowlist)
    with pytest.raises(LLMInputBlocked, match="manual_import"):
        build_curated_input(
            source_name="manual_import",
            record_type="person",
            raw_payload={"name": "synthetic"},
        )


def test_source_and_field_approvals_cannot_be_bypassed(monkeypatch) -> None:
    allowlist = LLMAllowlistConfig(
        version=1,
        default_policy="deny",
        sources={"synthetic_arxiv": _synthetic_approval("title")},
    )
    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", lambda: allowlist)
    with pytest.raises(LLMInputBlocked):
        build_curated_input(
            source_name="synthetic_github",
            record_type="repository",
            raw_payload={"title": "synthetic"},
        )
    result = build_curated_input(
        source_name="synthetic_arxiv",
        record_type="preprint",
        raw_payload={"title": "synthetic", "authors": [{"name": "private"}]},
    )
    assert result.fields == {"title": "synthetic"}


def test_university_feed_scope_is_distinct_from_parent_source() -> None:
    from app.llm.allowlist import source_scope

    assert source_scope("university", {"university_key": "ude_forschung"}) == (
        "university:ude_forschung"
    )
    assert source_scope("university", {"university_key": "ude_aktuell"}) == (
        "university:ude_aktuell"
    )


def test_hash_is_based_on_curated_provider_input(monkeypatch) -> None:
    allowlist = LLMAllowlistConfig(
        version=1,
        default_policy="deny",
        sources={"synthetic_openalex": _synthetic_approval("title")},
    )
    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", lambda: allowlist)
    first = build_curated_input(
        source_name="synthetic_openalex",
        record_type="work",
        raw_payload={"title": "same", "authors": ["excluded A"]},
    )
    same = build_curated_input(
        source_name="synthetic_openalex",
        record_type="work",
        raw_payload={"title": "same", "authors": ["excluded B"]},
    )
    changed = build_curated_input(
        source_name="synthetic_openalex",
        record_type="work",
        raw_payload={"title": "changed"},
    )
    assert first.input_hash == same.input_hash
    assert first.input_hash != changed.input_hash
