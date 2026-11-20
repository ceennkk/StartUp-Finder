from __future__ import annotations

from pydantic import ValidationError

from app.evidence.models import ClaimExtraction, Document
from app.evidence.validation import ClaimEvidenceError, stabilize_extraction_ids, validate_claim_extraction
from app.llm.allowlist import CuratedLLMInput
from app.llm.analyzer import LLMAnalysisValidationError
from app.llm.authorization import authorized_complete, authorize_provider_input
from app.llm.provider import LLMProvider, LLMRequest

CLAIM_PROMPT_VERSION = "claim-extraction-prompt-v1"
CLAIM_SCHEMA_VERSION = "claim-extraction-schema-v1"
CLAIM_INSTRUCTIONS = (
    "Extract only source-backed candidate claims from the supplied fields. "
    "Use the supplied document ID and verbatim short quotes. Distinguish "
    "facts, hypotheses and classification proposals. Never infer final HTGF "
    "or funding decisions."
)


def document_id(curated_input: CuratedLLMInput) -> str:
    return f"document:{curated_input.input_hash}"


class ClaimLLMAnalyzer:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def analyze(self, curated_input: CuratedLLMInput) -> ClaimExtraction:
        curated_input = authorize_provider_input(self.provider, curated_input, purpose="claim_extraction")
        doc_id = document_id(curated_input)
        response = authorized_complete(
            self.provider,
            LLMRequest(
                curated_input=curated_input,
                output_schema=ClaimExtraction,
                prompt_version=CLAIM_PROMPT_VERSION,
                schema_version=CLAIM_SCHEMA_VERSION,
                instructions=f"{CLAIM_INSTRUCTIONS} Document ID: {doc_id}",
                purpose="claim_extraction",
            ),
        )
        try:
            result = ClaimExtraction.model_validate(response.structured_output)
        except ValidationError as exc:
            raise LLMAnalysisValidationError(
                "output_schema_invalid",
                provider_name=response.provider_name,
                model_version=response.model_version,
                usage=response.usage,
            ) from None
        document = Document(
            document_id=doc_id,
            source_id=curated_input.source_scope,
            content_hash=curated_input.input_hash,
            fields=curated_input.fields,
        )
        try:
            return stabilize_extraction_ids(validate_claim_extraction(result, [document]))
        except ClaimEvidenceError as exc:
            raise LLMAnalysisValidationError(
                "evidence_invalid",
                provider_name=response.provider_name,
                model_version=response.model_version,
                usage=response.usage,
            ) from None
