from __future__ import annotations

import calendar
from datetime import date
from typing import Any
from urllib.parse import urlparse

FIELDS = frozenset({
    "digital_tech", "industrial", "climate_deeptech", "life_sciences",
    "chemistry", "adjacent_business_field", "outside_scope", "unclear",
})
MATCHED_FIELDS = FIELDS - {"outside_scope", "unclear"}
PRESENCE = frozenset({
    "registered_seat_in_germany", "relocation_to_germany_planned",
    "german_permanent_establishment_planned", "no_germany_connection", "unclear",
})
SOURCE_TYPES = frozenset({
    "registry", "official_company", "official_program", "investor",
    "independent_media", "other",
})


def _date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return [_text(item, label) for item in value]


def _evidence(value: Any, label: str, as_of: date) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label}.evidence must be a list")
    for source in value:
        if not isinstance(source, dict):
            raise ValueError(f"{label}: evidence must be objects")
        for key in ("title", "url", "publisher", "claim", "source_type", "reliability"):
            _text(source.get(key), f"{label}.{key}")
        parsed = urlparse(source["url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{label}: evidence URL must be an HTTP(S) URL")
        if source["source_type"] not in SOURCE_TYPES:
            raise ValueError(f"{label}: invalid source_type")
        if source["reliability"] not in {"high", "medium", "low"}:
            raise ValueError(f"{label}: invalid reliability")
        if _date(source.get("accessed_on"), f"{label}.accessed_on") > as_of:
            raise ValueError(f"{label}: evidence accessed after assessment date")
        if source.get("published_at") is not None:
            if _date(source["published_at"], f"{label}.published_at") > as_of:
                raise ValueError(f"{label}: evidence published after assessment date")
        _strings(source.get("contradictions"), f"{label}.contradictions")
    return value


def _section(value: Any, label: str, as_of: date) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    _text(value.get("rationale"), f"{label}.rationale")
    _strings(value.get("uncertainties"), f"{label}.uncertainties")
    _strings(value.get("contradictions"), f"{label}.contradictions")
    _evidence(value.get("evidence"), label, as_of)
    return value


def _supported(section: dict[str, Any], types: set[str] | None = None) -> bool:
    evidence = section["evidence"]
    return (
        bool(evidence)
        and not section["uncertainties"]
        and not section["contradictions"]
        and not any(source["contradictions"] for source in evidence)
        and all(source["reliability"] in {"high", "medium"} for source in evidence)
        and (types is None or any(
            source["source_type"] in types and source["reliability"] == "high"
            for source in evidence
        ))
    )


def third_anniversary(day: date) -> date:
    year = day.year + 3
    return date(year, day.month, min(day.day, calendar.monthrange(year, day.month)[1]))


def assess(candidate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("assessment input must be an object")
    candidate_id = _text(candidate.get("candidate_id"), "candidate_id")
    _text(candidate.get("name"), "name")
    as_of = _date(candidate.get("assessment_date"), "assessment_date")
    tech = _section(candidate.get("technology"), "technology", as_of)
    age = _section(candidate.get("company_age"), "company_age", as_of)
    germany = _section(candidate.get("germany"), "germany", as_of)

    tech_claim = tech.get("tech_startup_status")
    if tech_claim not in {"satisfied", "not_satisfied", "unclear"}:
        raise ValueError("invalid tech_startup_status")
    fields = _strings(tech.get("fields"), "technology.fields")
    if not fields or len(fields) != len(set(fields)) or not set(fields) <= FIELDS:
        raise ValueError("technology.fields must be a nonempty list of distinct known fields")
    if len(fields) > 1 and ({"unclear", "outside_scope"} & set(fields)):
        raise ValueError("unclear and outside_scope cannot be combined with other fields")
    tech_facts = ("product", "technology", "business_model", "business_field")
    tech_facts_complete = all(
        isinstance(tech.get(key), str) and tech[key].strip() for key in tech_facts
    )
    tech_status = tech_claim if _supported(tech) else "unclear"
    if tech_status == "satisfied" and not tech_facts_complete:
        tech_status = "unclear"
    if _supported(tech) and "outside_scope" in fields:
        sector_status = "not_satisfied"
    elif tech_status == "not_satisfied":
        sector_status = "not_satisfied"
    elif tech_status == "satisfied" and set(fields) & MATCHED_FIELDS:
        sector_status = "satisfied"
    else:
        sector_status = "unclear"

    registration = age.get("registration_status")
    if registration not in {"registered", "not_registered", "unclear"}:
        raise ValueError("invalid registration_status")
    if not isinstance(age.get("pre_company_candidate"), bool):
        raise ValueError("pre_company_candidate must be boolean")
    incorporation = age.get("incorporation_date")
    registered_date = _date(incorporation, "incorporation_date") if incorporation else None
    age_status = "unclear"
    pre_company = False
    if (
        registration == "registered" and registered_date and registered_date <= as_of
        and all(isinstance(age.get(key), str) and age[key].strip()
                for key in ("legal_entity_name", "registration_country", "registry_name"))
        and _supported(age, {"registry"})
    ):
        age_status = "within_three_years" if as_of <= third_anniversary(registered_date) else "older_than_three_years"
    elif registration == "not_registered" and _supported(age, {"registry", "official_company", "official_program"}):
        age_status = "not_registered"
        pre_company = (
            age["pre_company_candidate"]
            and isinstance(age.get("pre_company_description"), str)
            and bool(age["pre_company_description"].strip())
        )

    presence_claim = germany.get("status")
    if presence_claim not in PRESENCE:
        raise ValueError("invalid germany.status")
    if not isinstance(germany.get("concrete_plan"), bool):
        raise ValueError("germany.concrete_plan must be boolean")
    presence = "unclear"
    germany_entity = germany.get("legal_entity_name")
    age_entity = age.get("legal_entity_name")
    identity_matches = (
        isinstance(germany_entity, str) and bool(germany_entity.strip())
        and (not age_entity or (
            isinstance(age_entity, str) and germany_entity.strip().casefold() == age_entity.strip().casefold()
        ))
    )
    if presence_claim == "registered_seat_in_germany" and identity_matches and _supported(germany, {"registry", "official_company"}):
        presence = presence_claim
    elif presence_claim in {"relocation_to_germany_planned", "german_permanent_establishment_planned"}:
        if identity_matches and germany["concrete_plan"] and _supported(germany, {"official_company", "independent_media"}):
            presence = presence_claim
    elif presence_claim == "no_germany_connection" and identity_matches and _supported(germany, {"official_company", "registry"}):
        presence = presence_claim

    if pre_company:
        overall = "pre_company_candidate"
    elif sector_status == "not_satisfied" or age_status == "older_than_three_years" or presence == "no_germany_connection":
        overall = "htgf_not_eligible"
    elif sector_status == "satisfied" and age_status == "within_three_years" and presence in {
        "registered_seat_in_germany", "relocation_to_germany_planned",
        "german_permanent_establishment_planned",
    }:
        overall = "htgf_eligible"
    else:
        overall = "htgf_unclear"
    return {
        "candidate_id": candidate_id,
        "name": candidate["name"],
        "assessment_date": as_of.isoformat(),
        "tech_startup_status": tech_status,
        "technology_fields": fields,
        "technology_status": sector_status,
        "company_age_status": age_status,
        "germany_presence_status": presence,
        "htgf_eligibility_status": overall,
        "criteria": {"technology": tech, "company_age": age, "germany": germany},
    }
