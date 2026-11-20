from __future__ import annotations

import copy
import unittest

from app.htgf.assessment import assess


def source(kind: str = "registry") -> dict:
    return {
        "title": "Evidence", "url": "https://example.org/evidence",
        "publisher": "Example", "source_type": kind, "published_at": None,
        "accessed_on": "2026-01-01", "claim": "Curated relevant claim",
        "reliability": "high", "contradictions": [],
    }


def sample() -> dict:
    return {
        "candidate_id": "candidate-a", "name": "A", "assessment_date": "2026-11-20",
        "technology": {
            "tech_startup_status": "satisfied", "fields": ["digital_tech", "industrial"],
            "product": "Industrial analytics product", "technology": "Machine learning",
            "business_model": "Software subscription", "business_field": "Industrial analytics",
            "rationale": "Documented product and business model", "evidence": [source("official_company")],
            "uncertainties": [], "contradictions": [],
        },
        "company_age": {
            "registration_status": "registered", "legal_entity_name": "A GmbH",
            "incorporation_date": "2023-11-20", "registration_country": "DE",
            "registry_name": "Handelsregister", "registry_id": "HRB 1",
            "pre_company_candidate": False, "pre_company_description": None,
            "rationale": "Official registration", "evidence": [source()],
            "uncertainties": [], "contradictions": [],
        },
        "germany": {
            "status": "registered_seat_in_germany", "concrete_plan": False,
            "legal_entity_name": "A GmbH",
            "rationale": "Registered seat", "evidence": [source()],
            "uncertainties": [], "contradictions": [],
        },
    }


class AssessmentTests(unittest.TestCase):
    def test_all_supported_and_multiple_sectors(self) -> None:
        result = assess(sample())
        self.assertEqual(result["htgf_eligibility_status"], "htgf_eligible")
        self.assertEqual(result["technology_fields"], ["digital_tech", "industrial"])
        self.assertEqual(result["company_age_status"], "within_three_years")

    def test_technology_scope_and_missing_support(self) -> None:
        for field in ("digital_tech", "industrial", "climate_deeptech", "life_sciences", "chemistry", "adjacent_business_field"):
            item = sample()
            item["technology"]["fields"] = [field]
            self.assertEqual(assess(item)["technology_status"], "satisfied")
        item = sample()
        item["technology"]["fields"] = ["outside_scope"]
        self.assertEqual(assess(item)["htgf_eligibility_status"], "htgf_not_eligible")
        item["technology"]["tech_startup_status"] = "unclear"
        self.assertEqual(assess(item)["htgf_eligibility_status"], "htgf_not_eligible")
        item["technology"]["tech_startup_status"] = "satisfied"
        item["technology"]["fields"] = ["unclear"]
        self.assertEqual(assess(item)["htgf_eligibility_status"], "htgf_unclear")
        item["technology"]["fields"] = ["digital_tech"]
        item["technology"]["evidence"] = []
        self.assertEqual(assess(item)["tech_startup_status"], "unclear")
        item["technology"]["tech_startup_status"] = "not_satisfied"
        self.assertEqual(assess(item)["htgf_eligibility_status"], "htgf_unclear")
        item = sample()
        item["technology"]["business_model"] = None
        self.assertEqual(assess(item)["technology_status"], "unclear")
        item = sample()
        item["technology"]["uncertainties"] = ["Product not verified"]
        self.assertEqual(assess(item)["technology_status"], "unclear")

    def test_registration_boundary_and_leap_days(self) -> None:
        for registered, assessment, expected in (
            ("2023-11-19", "2026-11-20", "older_than_three_years"),
            ("2023-11-20", "2026-11-20", "within_three_years"),
            ("2023-11-21", "2026-11-20", "within_three_years"),
            ("2024-02-29", "2027-02-28", "within_three_years"),
            ("2024-02-29", "2027-03-01", "older_than_three_years"),
            ("2025-02-28", "2028-02-29", "older_than_three_years"),
        ):
            item = sample()
            item["company_age"]["incorporation_date"] = registered
            item["assessment_date"] = assessment
            if assessment < "2026-01-01":
                item["company_age"]["evidence"][0]["accessed_on"] = assessment
            self.assertEqual(assess(item)["company_age_status"], expected, (registered, assessment))

    def test_registry_evidence_and_identity_required(self) -> None:
        for change in (
            {"legal_entity_name": None},
            {"registry_name": None},
            {"registration_country": None},
            {"incorporation_date": None},
            {"evidence": []},
            {"evidence": [source("official_company")]},
            {"incorporation_date": "2026-11-21"},
        ):
            item = sample()
            item["company_age"].update(change)
            self.assertEqual(assess(item)["company_age_status"], "unclear")

    def test_contradictions_prevent_positive(self) -> None:
        for criterion in ("technology", "company_age", "germany"):
            for kind in ("section", "source"):
                item = sample()
                if kind == "section":
                    item[criterion]["contradictions"] = ["Unresolved conflict"]
                else:
                    item[criterion]["evidence"][0]["contradictions"] = ["Unresolved conflict"]
                result = assess(item)
                self.assertEqual(result["htgf_eligibility_status"], "htgf_unclear")
        item = sample()
        item["technology"]["evidence"][0]["reliability"] = "low"
        self.assertEqual(assess(item)["technology_status"], "unclear")

    def test_germany_plans_need_concrete_reliable_evidence(self) -> None:
        for plan in ("relocation_to_germany_planned", "german_permanent_establishment_planned"):
            item = sample()
            item["germany"].update({"status": plan, "evidence": [source("official_company")]})
            self.assertEqual(assess(item)["germany_presence_status"], "unclear")
            item["germany"]["concrete_plan"] = True
            self.assertEqual(assess(item)["htgf_eligibility_status"], "htgf_eligible")
            item["germany"]["evidence"] = []
            self.assertEqual(assess(item)["germany_presence_status"], "unclear")
        item = sample()
        item["germany"]["status"] = "no_germany_connection"
        self.assertEqual(assess(item)["htgf_eligibility_status"], "htgf_not_eligible")
        item = sample()
        item["germany"]["legal_entity_name"] = "Different GmbH"
        self.assertEqual(assess(item)["germany_presence_status"], "unclear")

    def test_pre_company_requires_positive_evidence(self) -> None:
        item = sample()
        item["company_age"].update({
            "registration_status": "not_registered", "pre_company_candidate": True,
            "pre_company_description": "A concrete pre-incorporation venture",
            "evidence": [],
        })
        self.assertEqual(assess(item)["htgf_eligibility_status"], "htgf_unclear")
        item["company_age"]["evidence"] = [source("official_program")]
        self.assertEqual(assess(item)["htgf_eligibility_status"], "pre_company_candidate")
        item["company_age"]["pre_company_description"] = None
        self.assertEqual(assess(item)["htgf_eligibility_status"], "htgf_unclear")

    def test_invalid_or_future_evidence_rejected(self) -> None:
        for patch in (
            {"url": "not-a-url"},
            {"source_type": "unknown"},
            {"published_at": "2027-01-01"},
            {"accessed_on": "2027-01-01"},
            {"claim": ""},
        ):
            item = copy.deepcopy(sample())
            item["technology"]["evidence"][0].update(patch)
            with self.assertRaises(ValueError):
                assess(item)


if __name__ == "__main__":
    unittest.main()
