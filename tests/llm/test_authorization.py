from __future__ import annotations

from dataclasses import replace

import pytest

from app.llm.allowlist import (
    CuratedLLMInput,
    LLMAllowlistConfig,
    LLMInputBlocked,
    SourceFieldApproval,
    build_curated_input,
)
from app.llm.analyzer import EarlySignalLLMAnalyzer
from app.llm.fake_provider import FakeLLMProvider
from app.llm.provider import LLMRequest
from app.utils.hashing import content_hash


@pytest.fixture
def policy(monkeypatch):
    config = LLMAllowlistConfig(
        version=1, default_policy="deny",
        sources={"synthetic_test": SourceFieldApproval(
            fields=("title",), approved=True, purpose="synthetic unit test",
            reviewed_at="2026-11-20", reviewed_by="test", terms_reference="test",
            review_summary="synthetic only", allowed_purposes=("early_signal", "claim_extraction"),
            allowed_providers=("fake",),
        )},
    )
    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", lambda: config)
    return config


def _input():
    return build_curated_input(
        source_name="synthetic_test", record_type="fixture",
        raw_payload={"title": "Synthetic record", "email": "not transmitted"},
    )


def test_direct_constructed_input_never_calls_analyzer_provider(policy) -> None:
    provider = FakeLLMProvider({})
    item = _input()
    forged = CuratedLLMInput(item.source_name, item.source_scope, item.record_type, item.fields, item.input_hash)
    with pytest.raises(LLMInputBlocked):
        EarlySignalLLMAnalyzer(provider).analyze(forged)
    assert provider.requests == []


@pytest.mark.parametrize("attack", ["fields", "hash", "source", "scope", "record_type", "seal"])
def test_tampering_is_rejected_even_with_recomputed_hash(policy, attack) -> None:
    item = _input()
    if attack == "fields":
        item.fields["title"] = "modified"
        item = replace(item, input_hash=content_hash({
            "source_name": item.source_name, "source_scope": item.source_scope,
            "record_type": item.record_type, "fields": item.fields,
        }))
    elif attack == "hash":
        item = replace(item, input_hash="x" * 64)
    elif attack == "source":
        item = replace(item, source_name="synthetic_other")
    elif attack == "scope":
        item = replace(item, source_scope="synthetic_other")
    elif attack == "record_type":
        item = replace(item, record_type="modified")
    else:
        item = replace(item, _authorization_seal="a" * 64)
    provider = FakeLLMProvider({})
    with pytest.raises(LLMInputBlocked):
        EarlySignalLLMAnalyzer(provider).analyze(item)
    assert provider.requests == []


def test_policy_revocation_and_default_deny_are_rechecked(policy, monkeypatch) -> None:
    item = _input()
    monkeypatch.setattr(
        "app.llm.allowlist.load_llm_allowlist",
        lambda: LLMAllowlistConfig(version=1, default_policy="deny", sources={}),
    )
    with pytest.raises(LLMInputBlocked):
        EarlySignalLLMAnalyzer(FakeLLMProvider({})).analyze(item)


def test_policy_change_invalidates_previously_authorized_input(policy, monkeypatch) -> None:
    item = _input()
    changed = policy.sources["synthetic_test"].model_copy(update={"fields": ("other",)})
    monkeypatch.setattr(
        "app.llm.allowlist.load_llm_allowlist",
        lambda: policy.model_copy(update={"sources": {"synthetic_test": changed}}),
    )
    with pytest.raises(LLMInputBlocked):
        EarlySignalLLMAnalyzer(FakeLLMProvider({})).analyze(item)


def test_provider_boundary_rejects_direct_fake_calls_and_unapproved_purpose(policy) -> None:
    item = _input()
    provider = FakeLLMProvider({})
    request = LLMRequest(item, dict, "v1", "v1", "synthetic", purpose="funding")
    with pytest.raises(LLMInputBlocked):
        provider.complete(request)
    forged = replace(item, _authorization_seal=None)
    with pytest.raises(LLMInputBlocked):
        provider.complete(replace(request, curated_input=forged, purpose="early_signal"))
    assert provider.requests == []


def test_unapproved_provider_and_subclass_never_receive_input(policy) -> None:
    class PretendFake(FakeLLMProvider):
        pass

    provider = PretendFake({})
    with pytest.raises(LLMInputBlocked):
        EarlySignalLLMAnalyzer(provider).analyze(_input())
    assert provider.requests == []


def test_selected_fields_are_minimized_and_detached_from_source(policy) -> None:
    raw = {"title": "Synthetic record", "email": "secret", "extra": {"secret": "credential"}}
    item = build_curated_input(source_name="synthetic_test", record_type="fixture", raw_payload=raw)
    raw["title"] = "changed"
    provider = FakeLLMProvider({})
    EarlySignalLLMAnalyzer(provider).analyze(item)
    assert provider.requests[0].curated_input.fields == {"title": "Synthetic record"}
    assert "secret" not in repr(provider.requests[0])


def test_blocks_raw_objects_and_sensitive_paths(monkeypatch, policy) -> None:
    approval = policy.sources["synthetic_test"].model_copy(update={"fields": ("owner", "email")})
    monkeypatch.setattr(
        "app.llm.allowlist.load_llm_allowlist",
        lambda: policy.model_copy(update={"sources": {"synthetic_test": approval}}),
    )
    with pytest.raises(LLMInputBlocked):
        build_curated_input(
            source_name="synthetic_test", record_type="fixture",
            raw_payload={"owner": {"name": "synthetic"}, "email": "synthetic@example.test"},
        )


def test_credential_like_text_and_oversized_text_are_blocked(policy) -> None:
    for text in ("password=synthetic-secret", "x" * 20_001):
        with pytest.raises(LLMInputBlocked) as error:
            build_curated_input(
                source_name="synthetic_test", record_type="fixture",
                raw_payload={"title": text},
            )
        assert text not in str(error.value)
