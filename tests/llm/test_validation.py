from __future__ import annotations

import pytest

from app.llm.allowlist import CuratedLLMInput
from app.llm.analyzer import EarlySignalAnalysis, Evidence, SignalCategory, SignalFinding, SignalStrength
from app.llm.validation import EvidenceValidationError, validate_analysis_evidence


def _input() -> CuratedLLMInput:
    return CuratedLLMInput(
        source_name="synthetic",
        source_scope="synthetic",
        record_type="fixture",
        fields={"abstract": "A synthetic project describes a prototype."},
        input_hash="c" * 64,
    )


def _analysis(field_path: str, quote: str) -> EarlySignalAnalysis:
    return EarlySignalAnalysis(
        signals=[
            SignalFinding(
                category=SignalCategory.TECHNOLOGY,
                strength=SignalStrength.INDIRECT,
                description="A technical prototype is described.",
                evidence=[Evidence(field_path=field_path, quote=quote)],
            )
        ]
    )


def test_evidence_must_match_exact_cited_curated_field() -> None:
    analysis = _analysis("abstract", "describes a prototype")
    assert validate_analysis_evidence(analysis, _input()) is analysis


def test_evidence_cannot_reference_untransmitted_field() -> None:
    with pytest.raises(EvidenceValidationError, match="not sent to the provider"):
        validate_analysis_evidence(_analysis("authors", "A. Example"), _input())


def test_evidence_quote_must_be_present_verbatim() -> None:
    with pytest.raises(EvidenceValidationError, match="not present"):
        validate_analysis_evidence(_analysis("abstract", "a company was founded"), _input())
