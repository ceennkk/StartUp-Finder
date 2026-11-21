from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.domain import VerificationStatus
from app.evidence.models import ClaimExtraction, ClaimKind, Document, EvidenceModel, Source
from app.evidence.validation import validate_claim_extraction

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Description = Annotated[str, Field(min_length=1, max_length=500)]


class SupportCategory(StrEnum):
    PUBLIC_GRANT = "public_grant"
    FOUNDER_STIPEND = "founder_stipend"
    RESEARCH_FUNDING = "research_funding"
    PRIZE = "prize"
    EQUITY_INVESTMENT = "equity_investment"
    BUSINESS_ANGEL_INVESTMENT = "business_angel_investment"
    VENTURE_CAPITAL = "venture_capital"
    LOAN = "loan"
    CONVERTIBLE_INSTRUMENT = "convertible_instrument"
    IN_KIND_SUPPORT = "in_kind_support"
    OTHER = "other"
    UNKNOWN = "unknown"


class EventScope(StrEnum):
    INDIVIDUAL = "individual"
    PROGRAM_OFFER = "program_offer"
    PROGRAM_PARTICIPATION = "program_participation"


class EventStatus(StrEnum):
    ANNOUNCED = "announced"
    APPLIED = "applied"
    APPROVED = "approved"
    CONTRACTED = "contracted"
    PAID = "paid"
    UNKNOWN = "unknown"


class TriState(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class AmountQualifier(StrEnum):
    EXACT = "exact"
    UP_TO = "up_to"
    APPROXIMATE = "approximate"


class Provenance(EvidenceModel):
    """Source documents and claims curated for one subject."""

    sources: list[Source] = Field(min_length=1)
    documents: list[Document] = Field(min_length=1)
    extraction: ClaimExtraction

    @model_validator(mode="after")
    def validate_references(self) -> Provenance:
        source_ids = [source.source_id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("duplicate source ID")
        if any(document.source_id not in source_ids for document in self.documents):
            raise ValueError("document source is missing")
        if not self.extraction.claims:
            raise ValueError("at least one supported claim is required")
        validate_claim_extraction(self.extraction, self.documents)
        return self


class FinancialSupportEvent(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: Identifier
    candidate_id: Identifier
    category: SupportCategory
    scope: EventScope
    beneficiary: Description | None = None
    applicant: Description | None = None
    legal_recipient: Description | None = None
    funder: Description | None = None
    amount: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    amount_qualifier: AmountQualifier | None = None
    instrument: Description | None = None
    program_or_project: Description | None = None
    event_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    statuses: tuple[EventStatus, ...] = (EventStatus.UNKNOWN,)
    repayable: TriState = TriState.UNKNOWN
    dilutive: TriState = TriState.UNKNOWN
    provenance: Provenance
    uncertainties: tuple[Description, ...] = ()

    @model_validator(mode="after")
    def validate_event(self) -> FinancialSupportEvent:
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be supplied together")
        if (self.amount is None) != (self.amount_qualifier is None):
            raise ValueError("amount qualifier must accompany an amount")
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period start must not follow period end")
        if not self.statuses or len(set(self.statuses)) != len(self.statuses):
            raise ValueError("event statuses must be nonempty and unique")
        if EventStatus.UNKNOWN in self.statuses and len(self.statuses) > 1:
            raise ValueError("unknown status cannot accompany known statuses")
        if self.scope != EventScope.INDIVIDUAL and any(
            status in self.statuses for status in (EventStatus.APPROVED, EventStatus.CONTRACTED, EventStatus.PAID)
        ):
            raise ValueError("program information cannot establish an individual award or payment")
        if any(claim.candidate_id != self.candidate_id for claim in self.provenance.extraction.claims):
            raise ValueError("event claims must identify the assessed candidate")
        return self


class EquityStage(StrEnum):
    COMPLETED = "completed"
    BINDING_AGREEMENT = "binding_agreement"
    UNCLEAR = "unclear"


class HumanReview(EvidenceModel):
    reviewer: Identifier
    reviewed_on: date
    rationale: Description


class EquityFinding(EvidenceModel):
    """A separately curated finding, not an inference from an event category."""

    finding_id: Identifier
    candidate_id: Identifier
    stage: EquityStage
    provenance: Provenance
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    review: HumanReview | None = None

    @model_validator(mode="after")
    def validate_finding(self) -> EquityFinding:
        claims = self.provenance.extraction.claims
        if any(claim.candidate_id != self.candidate_id for claim in claims):
            raise ValueError("equity claims must identify the assessed candidate")
        if self.verification_status == VerificationStatus.MANUALLY_VERIFIED:
            if self.review is None:
                raise ValueError("manual verification requires a human review")
            if not any(claim.claim_type == "external_equity" and claim.kind == ClaimKind.FACT_CANDIDATE for claim in claims):
                raise ValueError("manual finding requires an external-equity fact candidate")
        return self


class SearchFamily(StrEnum):
    COMPANY = "company"
    REGISTRY = "registry"
    INVESTOR = "investor"
    INDEPENDENT_MEDIA = "independent_media"


class SearchOutcome(StrEnum):
    NO_PUBLIC_EQUITY_FOUND = "no_public_equity_found"
    POSSIBLE_EQUITY_FOUND = "possible_equity_found"
    INACCESSIBLE = "inaccessible"


class SearchRecord(EvidenceModel):
    family: SearchFamily
    source: Source
    searched_on: date
    queries: tuple[Description, ...] = Field(min_length=1)
    outcome: SearchOutcome
    notes: Description


class SearchCoverage(EvidenceModel):
    candidate_id: Identifier
    as_of: date
    records: tuple[SearchRecord, ...] = Field(min_length=1)
    review: HumanReview
    reviewed_event_ids: tuple[Identifier, ...] = ()
    unresolved_questions: tuple[Description, ...] = ()


class EquityStatus(StrEnum):
    EQUITY_CONFIRMED = "equity_confirmed"
    EQUITY_STATUS_UNCLEAR = "equity_status_unclear"
    NO_PUBLIC_EQUITY_ROUND_FOUND = "no_public_equity_round_found"


class EquityAssessment(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    candidate_id: Identifier
    as_of: date
    status: EquityStatus
    finding_ids: tuple[Identifier, ...] = ()
    stages: tuple[EquityStage, ...] = ()
    reasons: tuple[Description, ...]
