from __future__ import annotations

import pytest

from app.evidence.models import ClaimExtraction, Document
from app.evidence.identifiers import stable_id
from app.evidence.validation import ClaimEvidenceError, validate_claim_extraction


def _document() -> Document:
    return Document(
        document_id="d1", source_id="s1", content_hash="hash",
        fields={"title": "Synthetic prototype"},
    )


def _extraction() -> ClaimExtraction:
    return ClaimExtraction.model_validate({
        "claims": [
            {"claim_id": "c1", "candidate_id": "candidate1", "claim_type": "technology",
             "kind": "hypothesis", "statement": "A prototype", "evidence_ids": ["e1"], "conflict_ids": ["x1"]},
            {"claim_id": "c2", "candidate_id": "candidate1", "claim_type": "technology",
             "kind": "classification_proposal", "statement": "Technology", "evidence_ids": ["e1"], "conflict_ids": ["x1"]},
        ],
        "evidence": [{"evidence_id": "e1", "document_id": "d1", "field_path": "title", "quote": "prototype"}],
        "conflicts": [{"conflict_id": "x1", "claim_ids": ["c1", "c2"], "description": "Unresolved"}],
    })


def test_valid_conflicts_and_document_references() -> None:
    extraction = _extraction()
    assert validate_claim_extraction(extraction, [_document()]) is extraction
    assert extraction.schema_version == "1.0"
    assert extraction.claims[0].schema_version == "1.0"
    assert extraction.conflicts[0].status == "open"


def test_inconsistent_conflict_and_duplicate_documents_fail() -> None:
    payload = _extraction().model_dump(mode="json")
    payload["claims"][0]["conflict_ids"] = []
    with pytest.raises(ClaimEvidenceError):
        validate_claim_extraction(ClaimExtraction.model_validate(payload), [_document()])
    with pytest.raises(ClaimEvidenceError):
        validate_claim_extraction(_extraction(), [_document(), _document()])


def test_model_cannot_resolve_conflict_or_provide_final_status() -> None:
    payload = _extraction().model_dump(mode="json")
    payload["conflicts"][0]["status"] = "resolved"
    with pytest.raises(ValueError):
        ClaimExtraction.model_validate(payload)


def test_stable_ids_use_canonical_identity() -> None:
    first = stable_id("claim", {"candidate_id": "c1", "claim_type": "prototype"})
    assert first == stable_id("claim", {"claim_type": "prototype", "candidate_id": "c1"})
    assert first != stable_id("claim", {"candidate_id": "c2", "claim_type": "prototype"})
    with pytest.raises(ValueError):
        stable_id("claim", {})
