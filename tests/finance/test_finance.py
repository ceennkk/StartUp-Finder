from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from app.domain import VerificationStatus
from app.evidence.models import Claim, ClaimExtraction, ClaimKind, Document, Evidence, Source
from app.finance.assessment import assess_equity
from app.finance.models import (
    AmountQualifier,
    EquityFinding,
    EquityStage,
    EquityStatus,
    EventScope,
    EventStatus,
    FinancialSupportEvent,
    HumanReview,
    Provenance,
    SearchCoverage,
    SearchFamily,
    SearchOutcome,
    SearchRecord,
    SupportCategory,
    TriState,
)

TODAY = date(2026, 11, 20)


def provenance(candidate: str, quote: str, claim_type: str = "support", url: str = "https://example.test/") -> Provenance:
    return Provenance(
        sources=[Source(source_id="s1", title="Source", url=url, publisher="Publisher", source_type="official")],
        documents=[Document(document_id="d1", source_id="s1", content_hash="hash", retrieved_on=TODAY, fields={"text": quote})],
        extraction=ClaimExtraction(
            claims=[Claim(claim_id="c1", candidate_id=candidate, claim_type=claim_type,
                          kind=ClaimKind.FACT_CANDIDATE, statement=quote, evidence_ids=["e1"])],
            evidence=[Evidence(evidence_id="e1", document_id="d1", field_path="text", quote=quote)],
        ),
    )


def event(candidate: str, category: SupportCategory = SupportCategory.PUBLIC_GRANT, **kwargs: object) -> FinancialSupportEvent:
    return FinancialSupportEvent(
        event_id="event1", candidate_id=candidate, category=category, scope=EventScope.INDIVIDUAL,
        provenance=provenance(candidate, "Project support"), **kwargs,
    )


def review() -> HumanReview:
    return HumanReview(reviewer="researcher", reviewed_on=TODAY, rationale="Reviewed the sources and identity.")


def coverage(candidate: str, events: tuple[str, ...] = ()) -> SearchCoverage:
    return SearchCoverage(
        candidate_id=candidate, as_of=TODAY, review=review(), reviewed_event_ids=events,
        records=tuple(
            SearchRecord(
                family=family,
                source=Source(source_id=family.value, title=family.value, url=f"https://example.test/{family.value}",
                              publisher="Publisher", source_type=family.value),
                searched_on=TODAY, queries=(f"{candidate} equity funding",),
                outcome=SearchOutcome.NO_PUBLIC_EQUITY_FOUND, notes="No matching public equity record.",
            ) for family in SearchFamily
        ),
    )


class FinancialSupportTests(unittest.TestCase):
    def test_nodeline_grant_is_not_equity_or_payment(self) -> None:
        kit = "Fördersumme von 798.682 Euro"
        company = "bis zu knapp 800.000 Euro durch das Bundesministerium für Forschung, Technologie und Raumfahrt"
        sources = Provenance(
            sources=[
                Source(source_id="kit", title="KIT FORGE", publisher="KIT FORGE", source_type="official",
                       url="https://de.linkedin.com/posts/kit-gruenderschmiede_startupsecure-cybersecurity-cybersecurity-activity-7511673973017956352-SWwl"),
                Source(source_id="company", title="nodeline", publisher="nodeline", source_type="company",
                       url="https://de.linkedin.com/posts/nodeline_startupsecure-datenintegration-systemintegration-activity-7498639220232704002-S-PA"),
            ],
            documents=[
                Document(document_id="kit-doc", source_id="kit", content_hash="test-kit",
                         retrieved_on=TODAY, fields={"text": kit}),
                Document(document_id="company-doc", source_id="company", content_hash="test-company",
                         retrieved_on=TODAY, fields={"text": company}),
            ],
            extraction=ClaimExtraction(
                claims=[
                    Claim(claim_id="amount", candidate_id="nodeline", claim_type="support",
                          kind=ClaimKind.FACT_CANDIDATE, statement=kit, evidence_ids=["kit-e"]),
                    Claim(claim_id="funder", candidate_id="nodeline", claim_type="support",
                          kind=ClaimKind.FACT_CANDIDATE, statement=company, evidence_ids=["company-e"]),
                ],
                evidence=[
                    Evidence(evidence_id="kit-e", document_id="kit-doc", field_path="text", quote=kit),
                    Evidence(evidence_id="company-e", document_id="company-doc", field_path="text", quote=company),
                ],
            ),
        )
        item = FinancialSupportEvent(
            event_id="shieldconnect", candidate_id="nodeline", category=SupportCategory.RESEARCH_FUNDING,
            scope=EventScope.INDIVIDUAL, funder="BMFTR", program_or_project="ShieldConnect",
            amount=Decimal("798682"), currency="EUR", amount_qualifier=AmountQualifier.EXACT,
            statuses=(EventStatus.ANNOUNCED,), legal_recipient=None,
            provenance=sources,
            uncertainties=("Formal recipient and disbursement unverified.",),
        )
        self.assertNotIn(EventStatus.PAID, item.statuses)
        self.assertEqual(item.dilutive, TriState.UNKNOWN)
        self.assertEqual(assess_equity("nodeline", TODAY, [], [item]).status, EquityStatus.EQUITY_STATUS_UNCLEAR)

    def test_onsite_stipend_does_not_infer_recipient_or_equity(self) -> None:
        item = FinancialSupportEvent(
            event_id="exist", candidate_id="onsite", category=SupportCategory.FOUNDER_STIPEND,
            scope=EventScope.INDIVIDUAL, beneficiary="Founding team",
            provenance=provenance(
                "onsite", "aktuell noch in der Förderung durch das EXIST Gründerstipendium",
                url="https://www.kit-forge.de/de/magazin/grundung-des-monats-onsite-solutions/",
            ),
        )
        self.assertIsNone(item.legal_recipient)
        self.assertIsNone(item.applicant)
        self.assertEqual(assess_equity("onsite", TODAY, [], [item]).status, EquityStatus.EQUITY_STATUS_UNCLEAR)

    def test_floronics_offer_and_participation_are_not_award(self) -> None:
        data = dict(event_id="fgi", candidate_id="floronics", category=SupportCategory.PUBLIC_GRANT,
                    scope=EventScope.PROGRAM_OFFER, amount=Decimal("300000"), currency="EUR",
                    amount_qualifier=AmountQualifier.UP_TO, provenance=provenance(
                        "floronics", "up to €300,000 non-dilutive funding",
                        url="https://www.futureforest.de/en/future-greentech-incubator"))
        item = FinancialSupportEvent(**data)
        self.assertEqual(item.statuses, (EventStatus.UNKNOWN,))
        self.assertEqual(assess_equity("floronics", TODAY, [], [item]).status, EquityStatus.EQUITY_STATUS_UNCLEAR)
        for scope in (EventScope.PROGRAM_OFFER, EventScope.PROGRAM_PARTICIPATION):
            for status in (EventStatus.APPROVED, EventStatus.CONTRACTED, EventStatus.PAID):
                with self.subTest(scope=scope, status=status), self.assertRaises(ValidationError):
                    FinancialSupportEvent(**(data | {"scope": scope, "statuses": (status,)}))

    def test_categories_do_not_infer_equity(self) -> None:
        for category in SupportCategory:
            with self.subTest(category=category):
                self.assertEqual(assess_equity("c", TODAY, [], [event("c", category)]).status,
                                 EquityStatus.EQUITY_STATUS_UNCLEAR)

    def test_investor_partner_logo_is_not_a_finding(self) -> None:
        item = event("c", SupportCategory.IN_KIND_SUPPORT)
        self.assertEqual(assess_equity("c", TODAY, [], [item]).status, EquityStatus.EQUITY_STATUS_UNCLEAR)
        with self.assertRaises(ValidationError):
            EquityFinding(finding_id="f", candidate_id="c", stage=EquityStage.COMPLETED,
                          provenance=provenance("c", "Partner investors"), review=review(),
                          verification_status=VerificationStatus.MANUALLY_VERIFIED)

    def test_provenance_and_candidate_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            Provenance(sources=[], documents=[], extraction=ClaimExtraction())
        with self.assertRaises(ValidationError):
            FinancialSupportEvent(event_id="x", candidate_id="a", category=SupportCategory.LOAN,
                scope=EventScope.INDIVIDUAL, provenance=provenance("b", "loan"))

    def test_invalid_quote_and_missing_source_are_rejected(self) -> None:
        good = provenance("c", "actual text")
        payload = good.model_dump()
        payload["extraction"]["evidence"][0]["quote"] = "invented"
        with self.assertRaises(ValueError):
            Provenance.model_validate(payload)
        payload = good.model_dump()
        payload["documents"][0]["source_id"] = "missing"
        with self.assertRaises(ValidationError):
            Provenance.model_validate(payload)

    def test_invalid_amount_dates_and_status(self) -> None:
        for kwargs in (
            {"amount": Decimal("12")}, {"amount": Decimal("0"), "currency": "EUR", "amount_qualifier": AmountQualifier.EXACT},
            {"amount": Decimal("12"), "currency": "eur", "amount_qualifier": AmountQualifier.EXACT},
            {"period_start": date(2026, 2, 1), "period_end": date(2026, 1, 1)},
            {"statuses": (EventStatus.UNKNOWN, EventStatus.PAID)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                event("c", **kwargs)


class EquityAssessmentTests(unittest.TestCase):
    def finding(self, stage: EquityStage = EquityStage.COMPLETED) -> EquityFinding:
        return EquityFinding(
            finding_id="f1", candidate_id="c", stage=stage,
            provenance=provenance("c", "External investor acquired shares.", "external_equity"),
            verification_status=VerificationStatus.MANUALLY_VERIFIED, review=review(),
        )

    def test_equity_requires_explicit_reviewed_finding(self) -> None:
        finding = self.finding()
        result = assess_equity("c", TODAY, [finding], [event("c", SupportCategory.CONVERTIBLE_INSTRUMENT)])
        self.assertEqual(result.status, EquityStatus.EQUITY_CONFIRMED)
        self.assertEqual(result.stages, (EquityStage.COMPLETED,))
        result = assess_equity("c", TODAY, [self.finding(EquityStage.BINDING_AGREEMENT)])
        self.assertEqual(result.stages, (EquityStage.BINDING_AGREEMENT,))
        unverified = EquityFinding.model_validate(finding.model_dump() | {"verification_status": "unverified", "review": None})
        self.assertEqual(assess_equity("c", TODAY, [unverified]).status, EquityStatus.EQUITY_STATUS_UNCLEAR)

    def test_hypothesis_cannot_be_manually_verified_as_equity(self) -> None:
        raw = self.finding().model_dump()
        raw["provenance"]["extraction"]["claims"][0]["kind"] = "hypothesis"
        with self.assertRaises(ValidationError):
            EquityFinding.model_validate(raw)

    def test_unresolved_claim_is_not_confirmed(self) -> None:
        raw = self.finding().model_dump()
        raw["provenance"]["extraction"]["claims"][0]["uncertainties"] = ["Identity unclear"]
        result = assess_equity("c", TODAY, [EquityFinding.model_validate(raw)])
        self.assertEqual(result.status, EquityStatus.EQUITY_STATUS_UNCLEAR)

    def test_negative_requires_coverage_human_review_and_event_review(self) -> None:
        grant = event("c")
        self.assertEqual(assess_equity("c", TODAY, [], [grant], coverage("c", ("event1",))).status,
                         EquityStatus.NO_PUBLIC_EQUITY_ROUND_FOUND)
        self.assertEqual(assess_equity("c", TODAY, [], [grant], coverage("c")).status,
                         EquityStatus.EQUITY_STATUS_UNCLEAR)
        self.assertEqual(assess_equity("c", TODAY, [], [], None).status, EquityStatus.EQUITY_STATUS_UNCLEAR)
        with self.assertRaises(ValidationError):
            SearchCoverage.model_validate(coverage("c").model_dump(exclude={"review"}))

    def test_missing_blocked_duplicate_sources_and_unresolved_search(self) -> None:
        base = coverage("c").model_dump()
        cases = []
        missing = coverage("c").model_dump(); missing["records"] = missing["records"][:-1]; cases.append(missing)
        blocked = coverage("c").model_dump(); blocked["records"][0]["outcome"] = "inaccessible"; cases.append(blocked)
        duplicate = coverage("c").model_dump(); duplicate["records"][1]["source"]["source_id"] = "company"; cases.append(duplicate)
        unresolved = coverage("c").model_dump(); unresolved["unresolved_questions"] = ["Potential investment"]; cases.append(unresolved)
        old = coverage("c").model_dump(); old["records"][0]["searched_on"] = date(2026, 1, 1); cases.append(old)
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(assess_equity("c", TODAY, [], coverage=SearchCoverage.model_validate(case)).status,
                                 EquityStatus.EQUITY_STATUS_UNCLEAR)
        self.assertEqual(assess_equity("c", TODAY, [], coverage=SearchCoverage.model_validate(base)).status,
                         EquityStatus.NO_PUBLIC_EQUITY_ROUND_FOUND)

    def test_unreviewed_finding_blocks_negative_and_confirmed_has_precedence(self) -> None:
        raw = self.finding().model_dump()
        raw["verification_status"] = "unverified"; raw["review"] = None
        finding = EquityFinding.model_validate(raw)
        self.assertEqual(assess_equity("c", TODAY, [finding], coverage=coverage("c")).status,
                         EquityStatus.EQUITY_STATUS_UNCLEAR)
        self.assertEqual(assess_equity("c", TODAY, [self.finding()], coverage=coverage("c")).status,
                         EquityStatus.EQUITY_CONFIRMED)

    def test_wrong_candidate_future_and_mutated_provenance_fail(self) -> None:
        with self.assertRaises(ValueError):
            assess_equity("other", TODAY, [self.finding()])
        with self.assertRaises(ValueError):
            assess_equity("c", date(2026, 1, 1), [self.finding()])
        item = event("c")
        item.provenance.documents[0].fields["text"] = "tampered"
        with self.assertRaises(ValueError):
            assess_equity("c", TODAY, [], [item])

    def test_review_must_not_predate_source_and_future_coverage_fails(self) -> None:
        raw = self.finding().model_dump()
        raw["review"]["reviewed_on"] = date(2026, 11, 19)
        with self.assertRaises(ValueError):
            assess_equity("c", TODAY, [EquityFinding.model_validate(raw)])
        raw_coverage = coverage("c").model_dump()
        raw_coverage["records"][0]["searched_on"] = date(2026, 11, 21)
        with self.assertRaises(ValueError):
            assess_equity("c", TODAY, [self.finding()], coverage=SearchCoverage.model_validate(raw_coverage))


if __name__ == "__main__":
    unittest.main()
