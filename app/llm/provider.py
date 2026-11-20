from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from app.llm.allowlist import CuratedLLMInput


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass(frozen=True)
class LLMProviderResponse:
    structured_output: dict[str, Any]
    provider_name: str
    model_version: str
    usage: LLMUsage


@dataclass(frozen=True)
class LLMRequest:
    curated_input: CuratedLLMInput
    output_schema: type[BaseModel]
    prompt_version: str
    schema_version: str
    instructions: str
    purpose: str = "early_signal"


class LLMProvider(Protocol):
    """Provider-neutral structured completion interface."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    def complete(self, request: LLMRequest) -> LLMProviderResponse: ...


class LLMProviderError(RuntimeError):
    """Safe, provider-neutral error category without request or credential data."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
