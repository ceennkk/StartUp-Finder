from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.llm.allowlist import LLMAllowlistConfig, SourceFieldApproval, build_curated_input
from app.llm.fake_provider import FakeLLMProvider
from app.llm.provider import LLMRequest, LLMUsage


class _Schema(BaseModel):
    value: str


def _request() -> LLMRequest:
    return LLMRequest(
        curated_input=build_curated_input(
            source_name="synthetic_test",
            record_type="fixture",
            raw_payload={"title": "Synthetic record"},
        ),
        output_schema=_Schema,
        prompt_version="test-prompt-v1",
        schema_version="test-schema-v1",
        instructions="Synthetic test instructions.",
    )


@pytest.fixture(autouse=True)
def _approved_synthetic_data(monkeypatch) -> None:
    config = LLMAllowlistConfig(
        version=1, default_policy="deny",
        sources={"synthetic_test": SourceFieldApproval(
            fields=("title",), approved=True, purpose="synthetic test",
            reviewed_at="2026-11-20", reviewed_by="test", terms_reference="test",
            review_summary="synthetic fixture only",
        )},
    )
    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", lambda: config)


def test_fake_provider_returns_structured_response_without_io() -> None:
    provider = FakeLLMProvider(
        {"value": "synthetic result"},
        model_version="fake-model-v2",
        usage=LLMUsage(input_tokens=12, output_tokens=4, estimated_cost_usd=0.0),
    )
    response = provider.complete(_request())
    assert response.structured_output == {"value": "synthetic result"}
    assert response.provider_name == "fake"
    assert response.model_version == "fake-model-v2"
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 4
    assert response.usage.estimated_cost_usd == 0
    assert provider.requests == [_request()]


def test_fake_provider_can_return_deterministic_output_per_request() -> None:
    provider = FakeLLMProvider(lambda request: {"value": request.curated_input.fields["title"]})
    response = provider.complete(_request())
    assert response.structured_output == {"value": "Synthetic record"}
