from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.llm.allowlist import CuratedLLMInput
from app.llm.provider import LLMProvider, LLMRequest, LLMUsage

ANALYZER_VERSION = "early-signal-analyzer-v1"
PROMPT_VERSION = "early-signal-prompt-v1"
SCHEMA_VERSION = "early-signal-schema-v1"
AnalysisValidationCode = Literal["output_schema_invalid", "evidence_invalid"]

ANALYSIS_INSTRUCTIONS = """\
Analyze only the supplied curated record. Do not infer that an organization is a
startup, that a company has been founded, or that it is unfunded. Distinguish
technical or research evidence from explicit founding, spin-out, and
commercialization mentions. Return only claims supported by short evidence
quotes from supplied fields, with the exact field path for each quote. Exclude
personal identities. Represent ambiguity in uncertainties and use low signal
strength when evidence is indirect.
"""


class SignalCategory(StrEnum):
    RESEARCH = "research"
    TECHNOLOGY = "technology"
    DEVELOPER_ACTIVITY = "developer_activity"
    FOUNDING = "founding"
    SPIN_OUT = "spin_out"
    COMMERCIALIZATION = "commercialization"
    STARTUP_ACTIVITY = "startup_activity"


class DiscoveryMentionType(StrEnum):
    FOUNDING_ACTIVITY_MENTION = "FOUNDING_ACTIVITY_MENTION"
    SPINOUT_MENTION = "SPINOUT_MENTION"
    COMMERCIALIZATION_MENTION = "COMMERCIALIZATION_MENTION"


class SignalStrength(StrEnum):
    WEAK = "weak"
    INDIRECT = "indirect"
    EXPLICIT = "explicit"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    field_path: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)


class SignalFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    category: SignalCategory
    mention_type: DiscoveryMentionType | None = None
    strength: SignalStrength
    description: str = Field(min_length=1, max_length=500)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def mention_matches_category(self) -> SignalFinding:
        expected = {
            SignalCategory.FOUNDING: DiscoveryMentionType.FOUNDING_ACTIVITY_MENTION,
            SignalCategory.SPIN_OUT: DiscoveryMentionType.SPINOUT_MENTION,
            SignalCategory.COMMERCIALIZATION: DiscoveryMentionType.COMMERCIALIZATION_MENTION,
        }.get(self.category)
        if self.mention_type is not None and self.mention_type is not expected:
            raise ValueError("mention_type must match its discovery signal category")
        return self


class EvidenceBackedExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    value: str = Field(min_length=1, max_length=200)
    evidence: list[Evidence] = Field(min_length=1, max_length=5)


class EarlySignalAnalysis(BaseModel):
    """Structured, source-grounded result; deliberately contains no entity resolution or score."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    signals: list[SignalFinding] = Field(default_factory=list, max_length=20)
    technology_fields: list[EvidenceBackedExtraction] = Field(default_factory=list, max_length=20)
    application_areas: list[EvidenceBackedExtraction] = Field(default_factory=list, max_length=20)
    product_hints: list[EvidenceBackedExtraction] = Field(default_factory=list, max_length=20)
    founding_hints: list[EvidenceBackedExtraction] = Field(default_factory=list, max_length=20)
    commercialization_hints: list[EvidenceBackedExtraction] = Field(
        default_factory=list, max_length=20
    )
    uncertainties: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class EarlySignalAnalysisRun:
    analysis: EarlySignalAnalysis
    analyzer_version: str
    prompt_version: str
    schema_version: str
    provider_name: str
    model_version: str
    usage: LLMUsage


class LLMAnalysisValidationError(ValueError):
    """Safe validation failure carrying provider usage without exposing response text."""

    def __init__(
        self,
        error_code: AnalysisValidationCode,
        *,
        provider_name: str,
        model_version: str,
        usage: LLMUsage,
    ) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.provider_name = provider_name
        self.model_version = model_version
        self.usage = usage


class EarlySignalLLMAnalyzer:
    """Run the early-signal schema through an injected, provider-neutral implementation."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        analyzer_version: str = ANALYZER_VERSION,
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.provider = provider
        self.analyzer_version = analyzer_version
        self.prompt_version = prompt_version
        self.schema_version = schema_version

    def analyze(self, curated_input: CuratedLLMInput) -> EarlySignalAnalysis:
        return self.analyze_with_metadata(curated_input).analysis

    def analyze_with_metadata(self, curated_input: CuratedLLMInput) -> EarlySignalAnalysisRun:
        request = LLMRequest(
            curated_input=curated_input,
            output_schema=EarlySignalAnalysis,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            instructions=ANALYSIS_INSTRUCTIONS,
        )
        response = self.provider.complete(request)
        try:
            result = EarlySignalAnalysis.model_validate(response.structured_output)
        except ValidationError as exc:
            raise LLMAnalysisValidationError(
                "output_schema_invalid",
                provider_name=response.provider_name,
                model_version=response.model_version,
                usage=response.usage,
            ) from exc
        from app.llm.validation import EvidenceValidationError, validate_analysis_evidence

        try:
            validate_analysis_evidence(result, curated_input)
        except EvidenceValidationError as exc:
            raise LLMAnalysisValidationError(
                "evidence_invalid",
                provider_name=response.provider_name,
                model_version=response.model_version,
                usage=response.usage,
            ) from exc
        return EarlySignalAnalysisRun(
            analysis=result,
            analyzer_version=self.analyzer_version,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            provider_name=response.provider_name,
            model_version=response.model_version,
            usage=response.usage,
        )
