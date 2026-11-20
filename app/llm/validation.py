from __future__ import annotations

from collections.abc import Iterator

from app.llm.allowlist import CuratedLLMInput
from app.llm.analyzer import EarlySignalAnalysis, Evidence


class EvidenceValidationError(ValueError):
    """Raised when an analysis cites text absent from its curated provider input."""


def _text_values(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)


def _evidence_items(analysis: EarlySignalAnalysis) -> Iterator[Evidence]:
    for signal in analysis.signals:
        yield from signal.evidence
    for extraction_group in (
        analysis.technology_fields,
        analysis.application_areas,
        analysis.product_hints,
        analysis.founding_hints,
        analysis.commercialization_hints,
    ):
        for extraction in extraction_group:
            yield from extraction.evidence


def validate_analysis_evidence(
    analysis: EarlySignalAnalysis,
    curated_input: CuratedLLMInput,
) -> EarlySignalAnalysis:
    """Require every cited path and verbatim quote to exist in provider input."""
    for evidence in _evidence_items(analysis):
        value = curated_input.fields.get(evidence.field_path)
        if evidence.field_path not in curated_input.fields:
            raise EvidenceValidationError(
                f"evidence refers to a field not sent to the provider: {evidence.field_path}"
            )
        if not any(evidence.quote in text for text in _text_values(value)):
            raise EvidenceValidationError(
                f"evidence quote is not present in the cited curated field: {evidence.field_path}"
            )
    return analysis
