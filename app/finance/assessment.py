from __future__ import annotations

from datetime import date
from typing import Sequence

from app.domain import VerificationStatus
from app.evidence.models import ClaimKind
from app.finance.models import (
    EquityAssessment,
    EquityFinding,
    EquityStage,
    EquityStatus,
    FinancialSupportEvent,
    SearchCoverage,
    SearchFamily,
    SearchOutcome,
)


def assess_equity(
    candidate_id: str,
    as_of: date,
    findings: Sequence[EquityFinding],
    events: Sequence[FinancialSupportEvent] = (),
    coverage: SearchCoverage | None = None,
) -> EquityAssessment:
    """Assess explicit equity findings, never infer an investment from support."""
    findings = [EquityFinding.model_validate(item.model_dump()) for item in findings]
    events = [FinancialSupportEvent.model_validate(item.model_dump()) for item in events]
    if coverage is not None:
        coverage = SearchCoverage.model_validate(coverage.model_dump())
    if not candidate_id.strip():
        raise ValueError("candidate_id is required")
    if any(item.candidate_id != candidate_id for item in (*findings, *events)):
        raise ValueError("findings and events must belong to the assessed candidate")
    if coverage is not None and coverage.candidate_id != candidate_id:
        raise ValueError("coverage must belong to the assessed candidate")
    if len({item.event_id for item in events}) != len(events):
        raise ValueError("duplicate event ID")
    if len({item.finding_id for item in findings}) != len(findings):
        raise ValueError("duplicate finding ID")
    for item in (*findings, *events):
        for doc in item.provenance.documents:
            if (doc.published_on and doc.published_on > as_of) or (doc.retrieved_on and doc.retrieved_on > as_of):
                raise ValueError("source document postdates assessment")
    if any(event.event_date and event.event_date > as_of for event in events):
        raise ValueError("event date postdates assessment")
    if any(item.review and item.review.reviewed_on > as_of for item in findings):
        raise ValueError("equity review postdates assessment")
    for finding in findings:
        if finding.review and any(
            (doc.published_on and doc.published_on > finding.review.reviewed_on)
            or (doc.retrieved_on and doc.retrieved_on > finding.review.reviewed_on)
            for doc in finding.provenance.documents
        ):
            raise ValueError("equity review predates a source document")
    if coverage is not None:
        if coverage.as_of != as_of or coverage.review.reviewed_on != as_of:
            raise ValueError("coverage and review must match the assessment date")
        if any(record.searched_on > as_of for record in coverage.records):
            raise ValueError("search postdates assessment")

    confirmed = []
    for finding in findings:
        relevant_claims = [
            claim for claim in finding.provenance.extraction.claims
            if claim.claim_type == "external_equity" and claim.kind == ClaimKind.FACT_CANDIDATE
        ]
        if (
            finding.stage != EquityStage.UNCLEAR
            and finding.verification_status == VerificationStatus.MANUALLY_VERIFIED
            and finding.review is not None
            and relevant_claims
            and not finding.provenance.extraction.conflicts
            and all(not claim.uncertainties for claim in finding.provenance.extraction.claims)
        ):
            confirmed.append(finding)
    if confirmed:
        return EquityAssessment(
            candidate_id=candidate_id, as_of=as_of, status=EquityStatus.EQUITY_CONFIRMED,
            finding_ids=tuple(item.finding_id for item in confirmed),
            stages=tuple(sorted({item.stage for item in confirmed}, key=lambda stage: stage.value)),
            reasons=("Manually reviewed external equity finding; agreement and completion remain distinct.",),
        )

    if coverage is not None:
        families = {record.family for record in coverage.records}
        reviewed = set(coverage.reviewed_event_ids)
        complete = (
            families == set(SearchFamily)
            and len({record.source.source_id for record in coverage.records}) >= len(SearchFamily)
            and all(record.outcome == SearchOutcome.NO_PUBLIC_EQUITY_FOUND for record in coverage.records)
            and not coverage.unresolved_questions
            and not findings
            and reviewed == {event.event_id for event in events}
            and all(record.searched_on == as_of for record in coverage.records)
        )
        if complete:
            return EquityAssessment(
                candidate_id=candidate_id, as_of=as_of, status=EquityStatus.NO_PUBLIC_EQUITY_ROUND_FOUND,
                reasons=("Documented source-family searches and human review found no public equity round; private financing may exist.",),
            )
    return EquityAssessment(
        candidate_id=candidate_id, as_of=as_of, status=EquityStatus.EQUITY_STATUS_UNCLEAR,
        reasons=("No verified equity finding or sufficiently reviewed search coverage.",),
    )
