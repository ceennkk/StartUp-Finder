from __future__ import annotations

from dataclasses import replace

from app.llm.allowlist import CuratedLLMInput, LLMInputBlocked, authorize_curated_input
from app.llm.provider import LLMProvider, LLMProviderResponse, LLMRequest


def authorize_provider_input(
    provider: LLMProvider, curated_input: CuratedLLMInput, *, purpose: str
) -> CuratedLLMInput:
    from app.llm.fake_provider import FakeLLMProvider

    if type(provider) is not FakeLLMProvider:
        raise LLMInputBlocked("LLM provider is not authorized")
    return authorize_curated_input(
        curated_input, provider_name=provider.provider_name, purpose=purpose
    )


def authorized_complete(provider: LLMProvider, request: LLMRequest) -> LLMProviderResponse:
    """Only the built-in, local fake is permitted until an external provider is approved."""
    curated = authorize_provider_input(provider, request.curated_input, purpose=request.purpose)
    return provider.complete(replace(request, curated_input=curated))
