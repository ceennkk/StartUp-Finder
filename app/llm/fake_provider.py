from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.llm.provider import LLMProviderResponse, LLMRequest, LLMUsage

FakeOutputFactory = Callable[[LLMRequest], dict[str, Any]]


class FakeLLMProvider:
    """Local-only deterministic provider for synthetic fixtures; performs no I/O."""

    provider_name = "fake"

    def __init__(
        self,
        output: dict[str, Any] | FakeOutputFactory,
        *,
        model_version: str = "fake-v1",
        usage: LLMUsage | None = None,
    ):
        self._output = output
        self._model_version = model_version
        self._usage = usage or LLMUsage()
        self.requests: list[LLMRequest] = []

    @property
    def model_version(self) -> str:
        return self._model_version

    def complete(self, request: LLMRequest) -> LLMProviderResponse:
        from app.llm.allowlist import authorize_curated_input

        authorize_curated_input(
            request.curated_input, provider_name=self.provider_name, purpose=request.purpose
        )
        self.requests.append(request)
        output = self._output(request) if callable(self._output) else self._output
        return LLMProviderResponse(
            structured_output=output,
            provider_name=self.provider_name,
            model_version=self.model_version,
            usage=self._usage,
        )
