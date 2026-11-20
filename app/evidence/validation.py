from __future__ import annotations

from collections.abc import Iterator, Sequence

from app.evidence.models import ClaimExtraction, Document
from app.evidence.identifiers import stable_id


class ClaimEvidenceError(ValueError):
    """Safe error category without source content or provider output."""


def _text_values(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)


def validate_claim_extraction(
    result: ClaimExtraction, documents: Sequence[Document]
) -> ClaimExtraction:
    docs = {doc.document_id: doc for doc in documents}
    evidence = {item.evidence_id: item for item in result.evidence}
    claims = {item.claim_id: item for item in result.claims}
    conflicts = {item.conflict_id: item for item in result.conflicts}
    if (
        len(docs) != len(documents)
        or len(evidence) != len(result.evidence)
        or len(claims) != len(result.claims)
        or len(conflicts) != len(result.conflicts)
    ):
        raise ClaimEvidenceError("duplicate_reference")
    for item in result.evidence:
        doc = docs.get(item.document_id)
        if doc is None or item.field_path not in doc.fields:
            raise ClaimEvidenceError("unknown_document_or_field")
        if not any(item.quote in value for value in _text_values(doc.fields[item.field_path])):
            raise ClaimEvidenceError("quote_not_present")
    for claim in result.claims:
        if any(ref not in evidence for ref in claim.evidence_ids):
            raise ClaimEvidenceError("unknown_evidence")
        if any(ref not in conflicts for ref in claim.conflict_ids):
            raise ClaimEvidenceError("unknown_conflict")
        if any(claim.claim_id not in conflicts[ref].claim_ids for ref in claim.conflict_ids):
            raise ClaimEvidenceError("inconsistent_conflict")
    for conflict in result.conflicts:
        if len(set(conflict.claim_ids)) < 2 or any(ref not in claims for ref in conflict.claim_ids):
            raise ClaimEvidenceError("unknown_or_duplicate_conflict_claim")
        if any(conflict.conflict_id not in claims[ref].conflict_ids for ref in conflict.claim_ids):
            raise ClaimEvidenceError("inconsistent_conflict")
    return result


def stabilize_extraction_ids(result: ClaimExtraction) -> ClaimExtraction:
    """Replace model-proposed reference IDs with content-based identifiers."""
    evidence_ids = {
        item.evidence_id: stable_id("evidence", {
            "document_id": item.document_id, "field_path": item.field_path, "quote": item.quote,
        })
        for item in result.evidence
    }
    claim_ids = {
        item.claim_id: stable_id("claim", {
            "candidate_id": item.candidate_id,
            "claim_type": item.claim_type,
            "kind": item.kind.value,
            "statement": item.statement,
            "evidence_ids": sorted(evidence_ids[ref] for ref in item.evidence_ids),
        })
        for item in result.claims
    }
    conflict_ids = {
        item.conflict_id: stable_id("conflict", {
            "claim_ids": sorted(claim_ids[ref] for ref in item.claim_ids),
            "description": item.description,
        })
        for item in result.conflicts
    }
    if any(len(set(mapping.values())) != len(mapping) for mapping in (evidence_ids, claim_ids, conflict_ids)):
        raise ClaimEvidenceError("duplicate_content_identity")
    return ClaimExtraction(
        schema_version=result.schema_version,
        evidence=[
            item.model_copy(update={"evidence_id": evidence_ids[item.evidence_id]})
            for item in result.evidence
        ],
        claims=[
            item.model_copy(update={
                "claim_id": claim_ids[item.claim_id],
                "evidence_ids": [evidence_ids[ref] for ref in item.evidence_ids],
                "conflict_ids": [conflict_ids[ref] for ref in item.conflict_ids],
            })
            for item in result.claims
        ],
        conflicts=[
            item.model_copy(update={
                "conflict_id": conflict_ids[item.conflict_id],
                "claim_ids": [claim_ids[ref] for ref in item.claim_ids],
            })
            for item in result.conflicts
        ],
    )
