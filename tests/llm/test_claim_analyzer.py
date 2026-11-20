from __future__ import annotations

import copy

import pytest

from app.llm.allowlist import LLMAllowlistConfig, SourceFieldApproval, build_curated_input
from app.llm.analyzer import LLMAnalysisValidationError
from app.llm.claim_analyzer import ClaimLLMAnalyzer, document_id
from app.llm.fake_provider import FakeLLMProvider


@pytest.fixture
def curated(monkeypatch):
    config = LLMAllowlistConfig(
        version=1, default_policy="deny",
        sources={"synthetic_test": SourceFieldApproval(
            fields=("title",), approved=True, purpose="synthetic only", reviewed_at="2026-11-20",
            reviewed_by="test", terms_reference="synthetic", review_summary="fixture",
            allowed_purposes=("claim_extraction",),
        )},
    )
    monkeypatch.setattr("app.llm.allowlist.load_llm_allowlist", lambda: config)
    return build_curated_input(
        source_name="synthetic_test", record_type="fixture",
        raw_payload={"title": "A synthetic project demonstrates a prototype"},
    )


def output(curated):
    return {
        "schema_version": "1.0",
        "evidence": [{
            "evidence_id": "e1", "document_id": document_id(curated), "field_path": "title",
            "quote": "synthetic project",
        }],
        "claims": [{
            "claim_id": "c1", "candidate_id": "candidate-synthetic", "claim_type": "prototype",
            "kind": "hypothesis", "statement": "A prototype may exist.", "evidence_ids": ["e1"],
            "uncertainties": ["Not independently confirmed"], "conflict_ids": [],
        }],
        "conflicts": [],
    }


def test_claims_are_schema_and_evidence_validated(curated) -> None:
    result = ClaimLLMAnalyzer(FakeLLMProvider(output(curated))).analyze(curated)
    assert result.claims[0].kind == "hypothesis"
    assert result.evidence[0].quote == "synthetic project"
    assert result.claims[0].claim_id.startswith("claim:")
    assert result.claims[0].evidence_ids == [result.evidence[0].evidence_id]
    changed = output(curated)
    changed["claims"][0]["claim_id"] = "other-ephemeral-id"
    changed["claims"][0]["evidence_ids"] = ["other-evidence-id"]
    changed["evidence"][0]["evidence_id"] = "other-evidence-id"
    repeated = ClaimLLMAnalyzer(FakeLLMProvider(changed)).analyze(curated)
    assert repeated.claims[0].claim_id == result.claims[0].claim_id
    assert repeated.evidence[0].evidence_id == result.evidence[0].evidence_id


@pytest.mark.parametrize("attack", ["document", "field", "quote", "evidence", "duplicates", "schema"])
def test_invalid_claims_are_rejected_without_leaking_provider_text(curated, attack) -> None:
    payload = copy.deepcopy(output(curated))
    if attack == "document":
        payload["evidence"][0]["document_id"] = "unknown"
    elif attack == "field":
        payload["evidence"][0]["field_path"] = "not_sent"
    elif attack == "quote":
        payload["evidence"][0]["quote"] = "secret-not-present"
    elif attack == "evidence":
        payload["claims"][0]["evidence_ids"] = ["unknown"]
    elif attack == "duplicates":
        payload["evidence"].append(payload["evidence"][0])
    else:
        payload["claims"][0]["final_htgf_status"] = "eligible"
    with pytest.raises(LLMAnalysisValidationError) as error:
        ClaimLLMAnalyzer(FakeLLMProvider(payload)).analyze(curated)
    assert "secret-not-present" not in str(error.value)
    assert error.value.__suppress_context__


def test_provider_mutation_cannot_change_validated_evidence(curated) -> None:
    payload = output(curated)
    payload["evidence"][0]["quote"] = "provider-invented"

    def mutate(request):
        request.curated_input.fields["title"] = "provider-invented"
        return payload

    with pytest.raises(LLMAnalysisValidationError, match="evidence_invalid"):
        ClaimLLMAnalyzer(FakeLLMProvider(mutate)).analyze(curated)
    assert curated.fields["title"] == "A synthetic project demonstrates a prototype"
