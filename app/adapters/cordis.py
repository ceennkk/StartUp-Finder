"""CORDIS (EU-funded research projects) via the official EURIO SPARQL endpoint.

Only the public read-only SPARQL endpoint is used (no bulk ZIPs under /data/, which robots.txt disallows, and no
registration-based APIs). Data: CC BY 4.0 / Commission Decision 2011/833/EU, attribution "© European Union, CORDIS".
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

from app.adapters.base import AdapterConfigError, BaseAdapter
from app.config.settings import load_source_config
from app.domain import AliasType, EntityType, RelationshipType, SignalType, SourceType
from app.http.client import HttpFetchError
from app.ingestion.types import (
    AliasDraft,
    EntityDraft,
    NormalizedBundle,
    RawRecord,
    RelationshipDraft,
    SignalDraft,
    SourceSpec,
)
from app.normalization.organizations import organization_draft
from app.normalization.publications import compact
from app.normalization.text import clean_text
from app.utils.dates import parse_datetime, utcnow

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://cordis.europa.eu/datalab/sparql-api"
HOST = "cordis.europa.eu"
PROJECT_URL = "https://cordis.europa.eu/project/id/{id}"
MIN_INTERVAL_SECONDS = 10.0
MAX_PAGE_SIZE = 50
ABSTRACT_LIMIT = 1000
LICENSE = {
    "name": "CC BY 4.0",
    "decision": "Commission Decision 2011/833/EU",
    "attribution": "© European Union, CORDIS",
    "terms_url": "https://cordis.europa.eu/about/legal",
}
# Verified generic value: the EURIO data exposes no organisation activity type, so none is invented.
GENERIC_ORGANIZATION_TYPE = "organization"

PREFIXES = (
    "PREFIX eurio: <http://data.europa.eu/s66#>\n"
    "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
)
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_PROJECT_URI = re.compile(r"^http://data\.europa\.eu/s66/resource/projects/[0-9a-f-]{36}$")
_ORG_URI = re.compile(r"^http://data\.europa\.eu/s66/resource/organisations/(?P<id>[0-9a-f-]{36})$")


def _country_filter(countries: list[str]) -> str:
    return "FILTER(?cc IN (" + ", ".join(f'"{c}"' for c in countries) + "))"


def projects_page_query(countries: list[str], start: date, end: date, limit: int, offset: int) -> str:
    return (
        PREFIXES
        + "SELECT DISTINCT ?p ?id ?start WHERE {\n"
        "  ?p a eurio:Project ; eurio:identifier ?id ; eurio:startDate ?start ; eurio:hasInvolvedParty ?role .\n"
        "  ?role eurio:isRoleOf ?org . ?org eurio:hasSite ?site . ?site eurio:hasAddress ?addr .\n"
        "  ?addr eurio:addressCountry ?cc .\n"
        f"  {_country_filter(countries)}\n"
        f'  FILTER(?start >= "{start.isoformat()}"^^xsd:date && ?start <= "{end.isoformat()}"^^xsd:date)\n'
        f"}} ORDER BY ?start ?id LIMIT {limit} OFFSET {offset}"
    )


def project_details_query(project_uris: list[str], countries: list[str]) -> str:
    values = " ".join(f"<{uri}>" for uri in project_uris)
    return (
        PREFIXES
        + "SELECT ?p ?title ?end ?rcn ?status ?abstract ?roleLabel ?org ?name ?url ?cc WHERE {\n"
        f"  VALUES ?p {{ {values} }}\n"
        "  ?p eurio:hasInvolvedParty ?role .\n"
        "  ?role eurio:roleLabel ?roleLabel ; eurio:isRoleOf ?org .\n"
        "  ?org eurio:legalName ?name ; eurio:hasSite ?site .\n"
        "  ?site eurio:hasAddress ?addr . ?addr eurio:addressCountry ?cc .\n"
        f"  {_country_filter(countries)}\n"
        "  OPTIONAL { ?p eurio:title ?title }\n"
        "  OPTIONAL { ?p eurio:endDate ?end }\n"
        "  OPTIONAL { ?p eurio:rcn ?rcn }\n"
        "  OPTIONAL { ?p eurio:projectStatus ?status }\n"
        "  OPTIONAL { ?p eurio:abstract ?abstract }\n"
        "  OPTIONAL { ?org eurio:url ?url }\n"
        "}"
    )


def _value(binding: dict[str, Any], name: str) -> str | None:
    item = binding.get(name)
    return item.get("value") if isinstance(item, dict) else None


def teaser(text: str | None, limit: int = ABSTRACT_LIMIT) -> str | None:
    cleaned = clean_text(text)
    if cleaned is None or len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def merge_project_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold the joined result rows (one per project x participant x site) into one dict per project URI."""
    projects: dict[str, dict[str, Any]] = {}
    for row in rows:
        uri = _value(row, "p")
        if uri is None:
            continue
        project = projects.setdefault(uri, {"title": None, "end_date": None, "rcn": None, "status": None,
                                            "abstract": None, "orgs": {}})
        for field, var in (("title", "title"), ("end_date", "end"), ("rcn", "rcn"), ("status", "status"),
                           ("abstract", "abstract")):
            if project[field] is None:
                project[field] = _value(row, var)
        org_uri, name = _value(row, "org"), _value(row, "name")
        if not org_uri or not name:
            continue
        org = project["orgs"].setdefault(org_uri, {"org_uri": org_uri, "name": name, "url": None,
                                                    "countries": set(), "roles": set()})
        org["url"] = org["url"] or _value(row, "url")
        if (cc := _value(row, "cc")):
            org["countries"].add(cc)
        if (role := _value(row, "roleLabel")):
            org["roles"].add(role)
    return projects


class CordisAdapter(BaseAdapter):
    name = "cordis"
    source = SourceSpec(
        source_name="cordis",
        source_type=SourceType.API,
        base_url="https://cordis.europa.eu",
        description="CORDIS EU research projects via the public EURIO SPARQL endpoint (CC BY 4.0, (c) European Union, CORDIS).",
        terms_url=LICENSE["terms_url"],
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else load_source_config("cordis")
        self.endpoint = self.config.get("endpoint", DEFAULT_ENDPOINT)
        self.countries = [str(c).upper() for c in self.config.get("countries", ["DE"])]
        if not self.countries or not all(_COUNTRY.match(c) for c in self.countries):
            raise AdapterConfigError("cordis.countries must be a non-empty list of ISO 3166-1 alpha-2 codes")
        self.page_size = max(1, min(int(self.config.get("page_size", 25)), MAX_PAGE_SIZE))
        self.max_projects = int(self.config.get("max_projects_per_run", 1000))
        interval = max(float(self.config.get("min_interval_seconds", MIN_INTERVAL_SECONDS)), MIN_INTERVAL_SECONDS)
        self.http.set_min_interval(HOST, interval)

    # --- SPARQL ---------------------------------------------------------------------------------------

    def _select(self, query: str) -> list[dict[str, Any]]:
        response = self.http.get(
            self.endpoint,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            respect_robots=True,
        )
        try:
            bindings = response.json()["results"]["bindings"]
        except (ValueError, KeyError, TypeError) as exc:
            raise HttpFetchError("CORDIS SPARQL endpoint returned an unexpected (non-SPARQL-JSON) response") from exc
        if not isinstance(bindings, list):
            raise HttpFetchError("CORDIS SPARQL endpoint returned an unexpected result structure")
        return bindings

    def fetch(self) -> Iterator[RawRecord]:
        today = utcnow().date()
        scope = "start_date"
        cursor = self.get_cursor(scope)
        if cursor and cursor.get("from"):
            window_start = date.fromisoformat(cursor["from"])
            skip = int(cursor.get("skip", 0))
        else:
            window_start = today - timedelta(days=int(self.config.get("initial_days", 30)))
            skip = 0
        window_end = today + timedelta(days=int(self.config.get("future_days", 0)))

        offset = skip
        fetched = 0
        last_start, count_at_last = window_start, skip
        capped = False
        while True:
            page = self._select(projects_page_query(self.countries, window_start, window_end, self.page_size, offset))
            entries: list[tuple[str, str, str]] = []
            for binding in page:
                uri, project_id, start = _value(binding, "p"), _value(binding, "id"), _value(binding, "start")
                if not (uri and _PROJECT_URI.match(uri) and project_id and start):
                    log.warning("skipping malformed CORDIS project row")
                    continue
                entries.append((uri, project_id, start))
            if not entries:
                break
            details = merge_project_rows(self._select(project_details_query([e[0] for e in entries], self.countries)))
            for uri, project_id, start in entries:
                detail = details.get(uri)
                if detail is None or not detail["title"]:
                    log.warning("CORDIS project has no usable details", extra={"project_id": project_id})
                    continue
                if start == last_start.isoformat():
                    count_at_last += 1
                else:
                    last_start, count_at_last = date.fromisoformat(start), 1
                yield self._record(uri, project_id, start, detail)
                fetched += 1
            offset += len(page)
            if len(page) < self.page_size:
                break
            if fetched >= self.max_projects:
                capped = True
                break

        if capped:
            log.warning("cordis project cap reached; the rest is fetched on the next run", extra={"cap": self.max_projects})
            self.set_cursor(scope, {"from": last_start.isoformat(), "skip": count_at_last})
        else:
            lookback = int(self.config.get("lookback_days", 60))
            newest = min(max(last_start, window_start), today)
            self.set_cursor(scope, {"from": (newest - timedelta(days=lookback)).isoformat(), "skip": 0})

    def _record(self, uri: str, project_id: str, start: str, detail: dict[str, Any]) -> RawRecord:
        participants = [
            {"org_uri": org["org_uri"], "name": org["name"], "url": org["url"],
             "countries": sorted(org["countries"]), "roles": sorted(org["roles"])}
            for org in sorted(detail["orgs"].values(), key=lambda o: (o["name"].casefold(), o["org_uri"]))
        ]
        source_url = PROJECT_URL.format(id=project_id)
        return RawRecord(
            external_id=project_id,
            record_type="project",
            payload={
                "project_id": project_id,
                "project_uri": uri,
                "title": clean_text(detail["title"]),
                "start_date": start,
                "end_date": detail["end_date"],
                "rcn": detail["rcn"],
                "status": detail["status"],
                "abstract": teaser(detail["abstract"]),
                "participants": participants,
                "participant_countries_filter": self.countries,
                "source_url": source_url,
                "retrieved_from": self.endpoint,
                "license": LICENSE,
            },
            canonical_url=source_url,
            published_at=parse_datetime(start),
        )

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        p = raw.payload
        project_id = p["project_id"]
        start = parse_datetime(p.get("start_date"))
        project = EntityDraft(
            key="project",
            identifier=f"project:{project_id}",
            entity_type=EntityType.RESEARCH_PROJECT,
            canonical_name=p["title"],
            description=p.get("abstract"),
            properties=compact(
                {
                    "project_id": project_id,
                    "rcn": p.get("rcn"),
                    "status": p.get("status"),
                    "start_date": p.get("start_date"),
                    "end_date": p.get("end_date"),
                    "source_url": p.get("source_url"),
                    "license": p["license"]["name"],
                    "attribution": p["license"]["attribution"],
                }
            ),
            aliases=[AliasDraft(alias=p["source_url"], alias_type=AliasType.URL)] if p.get("source_url") else [],
            is_primary=True,
            extraction_method="cordis_sparql_project",
        )
        entities = [project]
        relationships: list[RelationshipDraft] = []
        for participant in p.get("participants") or []:
            match = _ORG_URI.match(participant["org_uri"])
            if match is None:
                continue
            key = f"org:{match.group('id')}"
            draft = organization_draft(
                key=key,
                identifier=key,
                name=participant["name"],
                properties={
                    "organization_type": GENERIC_ORGANIZATION_TYPE,
                    "countries": participant.get("countries") or None,
                    "website": participant.get("url"),
                    "cordis_organisation_uri": participant["org_uri"],
                },
            )
            if draft is None:
                continue
            entities.append(draft)
            relationships.append(
                RelationshipDraft(
                    source_key=key,
                    target_key="project",
                    relationship_type=RelationshipType.PARTICIPATED_IN,
                    properties={"roles": participant.get("roles") or [], "context": "cordis_project_participant"},
                )
            )
        signals = [
            SignalDraft(
                entity_key="project",
                signal_type=SignalType.NEW_FUNDING_PROJECT,
                description=p["title"],
                event_date=start,
                published_at=start,
            )
        ]
        return NormalizedBundle(entities=entities, relationships=relationships, signals=signals)
