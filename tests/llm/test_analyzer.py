from __future__ import annotations

import pytest

from app.llm.allowlist import CuratedLLMInput
from app.llm.analyzer import (
    ANALYZER_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    DiscoveryMentionType,
    EarlySignalLLMAnalyzer,
    LLMAnalysisValidationError,
    SignalCategory,
    SignalStrength,
)
from app.llm.fake_provider import FakeLLMProvider
from app.llm.provider import LLMUsage


def _curated_input() -> CuratedLLMInput:
    return CuratedLLMInput(
        source_name="synthetic",
        source_scope="synthetic",
        record_type="fixture",
        fields={
            "title": "Synthetic research prototype",
            "abstract": "The project has plans to found a company.",
        },
        input_hash="b" * 64,
    )


def test_analyzer_validates_structured_output_and_passes_versions() -> None:
    provider = FakeLLMProvider(
        {
            "signals": [
                {
                    "category": "technology",
                    "mention_type": None,
                    "strength": "indirect",
                    "description": "A prototype is described.",
                    "evidence": [
                        {"field_path": "title", "quote": "Synthetic research prototype"}
                    ],
                },
                {
                    "category": "founding",
                    "mention_type": "FOUNDING_ACTIVITY_MENTION",
                    "strength": "explicit",
                    "description": "The text explicitly describes a founding effort.",
                    "evidence": [{"field_path": "abstract", "quote": "plans to found a company"}],
                },
            ],
            "technology_fields": [
                {
                    "value": "synthetic materials",
                    "evidence": [{"field_path": "title", "quote": "Synthetic research prototype"}],
                }
            ],
            "application_areas": [],
            "product_hints": [],
            "founding_hints": [],
            "commercialization_hints": [],
            "uncertainties": ["The source does not establish a completed legal incorporation."],
        }
    )

    analyzer = EarlySignalLLMAnalyzer(provider)
    result = analyzer.analyze(_curated_input())

    assert result.signals[0].category is SignalCategory.TECHNOLOGY
    assert result.signals[0].strength is SignalStrength.INDIRECT
    assert result.signals[1].mention_type is DiscoveryMentionType.FOUNDING_ACTIVITY_MENTION
    assert result.uncertainties
    request = provider.requests[0]
    assert request.curated_input == _curated_input()
    assert request.output_schema.__name__ == "EarlySignalAnalysis"
    assert request.prompt_version == PROMPT_VERSION
    assert request.schema_version == SCHEMA_VERSION
    assert analyzer.analyzer_version == ANALYZER_VERSION


def test_analyzer_rejects_unknown_output_fields() -> None:
    provider = FakeLLMProvider(
        {"unapproved_raw_text": "must not pass"},
        usage=LLMUsage(input_tokens=8, output_tokens=3),
    )
    with pytest.raises(LLMAnalysisValidationError, match="output_schema_invalid") as error:
        EarlySignalLLMAnalyzer(provider).analyze_with_metadata(_curated_input())
    assert error.value.provider_name == "fake"
    assert error.value.usage.input_tokens == 8
    assert error.value.usage.output_tokens == 3


def test_analyzer_rejects_finding_without_evidence() -> None:
    provider = FakeLLMProvider(
        {
            "signals": [
                {
                    "category": "startup_activity",
                    "strength": "weak",
                    "description": "Unsupported claim",
                    "evidence": [],
                }
            ]
        }
    )
    with pytest.raises(LLMAnalysisValidationError, match="output_schema_invalid"):
        EarlySignalLLMAnalyzer(provider).analyze(_curated_input())


def test_analyzer_rejects_mismatched_discovery_mention_type() -> None:
    provider = FakeLLMProvider(
        {
            "signals": [
                {
                    "category": "founding",
                    "mention_type": "SPINOUT_MENTION",
                    "strength": "explicit",
                    "description": "A spin-out is mentioned.",
                    "evidence": [
                        {"field_path": "abstract", "quote": "plans to found a company"}
                    ],
                }
            ]
        }
    )
    with pytest.raises(LLMAnalysisValidationError, match="output_schema_invalid"):
        EarlySignalLLMAnalyzer(provider).analyze(_curated_input())


def test_analyzer_rejects_evidence_not_in_curated_input_without_leaking_it() -> None:
    provider = FakeLLMProvider(
        {
            "signals": [
                {
                    "category": "founding",
                    "mention_type": "FOUNDING_ACTIVITY_MENTION",
                    "strength": "explicit",
                    "description": "A founding event is claimed.",
                    "evidence": [{"field_path": "abstract", "quote": "not actually supplied"}],
                }
            ]
        }
    )
    with pytest.raises(LLMAnalysisValidationError, match="evidence_invalid") as error:
        EarlySignalLLMAnalyzer(provider).analyze(_curated_input())
    assert "not actually supplied" not in str(error.value)
