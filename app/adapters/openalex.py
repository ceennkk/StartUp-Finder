from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

from app.adapters.base import BaseAdapter
from app.config.settings import load_search_terms
from app.domain import AliasType, EntityType, RelationshipType, SignalType, SourceType
from app.ingestion.types import (
    AliasDraft,
    EntityDraft,
    NormalizedBundle,
    ObservationDraft,
    RawRecord,
    RelationshipDraft,
    SignalDraft,
    SourceSpec,
)
from app.normalization.organizations import organization_draft
from app.normalization.persons import external_alias, person_draft
from app.normalization.publications import abstract_from_inverted_index, compact
from app.normalization.text import clean_text, normalize_doi
from app.utils.dates import parse_datetime, utcnow

log = logging.getLogger(__name__)

API_URL = "https://api.openalex.org/works"
SELECT = (
    "id,doi,title,display_name,publication_date,publication_year,type,language,authorships,"
    "primary_topic,topics,keywords,abstract_inverted_index,referenced_works,cited_by_count,updated_date,ids"
)
VOLATILE = frozenset({"cited_by_count", "updated_date"})
BASIC_PAGING_LIMIT = 10_000


def short_id(url: str | None) -> str | None:
    return url.rsplit("/", 1)[-1] if url else None


class OpenAlexAdapter(BaseAdapter):
    name = "openalex"
    source = SourceSpec(
        source_name="openalex",
        source_type=SourceType.API,
        base_url="https://api.openalex.org",
        description="OpenAlex scholarly works (CC0 data), filtered by configurable topics and countries.",
        terms_url="https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication",
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else load_search_terms("openalex")
        self.api_key = self.settings.openalex_api_key
        self.http.set_min_interval("api.openalex.org", 0.2)

    # --- fetching ---------------------------------------------------------

    def fetch(self) -> Iterator[RawRecord]:
        seen: set[str] = set()
        today = utcnow().date()
        for topic, terms in (self.config.get("topics") or {}).items():
            scope = f"works:{topic}"
            cursor = self.get_cursor(scope)
            if cursor and cursor.get("from"):
                start = cursor["from"]
            else:
                start = (today - timedelta(days=int(self.config.get("default_start_days_back", 30)))).isoformat()
            log.info("openalex topic", extra={"topic": topic, "from": start})
            for work in self._pages(self._params(terms, start)):
                record = self._to_record(work)
                if record is None or record.external_id in seen:
                    continue
                seen.add(record.external_id)
                yield record
            lookback = int(self.config.get("lookback_days", 7))
            self.set_cursor(scope, {"from": (today - timedelta(days=lookback)).isoformat()})

    @staticmethod
    def _to_record(work: dict[str, Any]) -> RawRecord | None:
        work_id = short_id(work.get("id"))
        if not work_id:
            return None
        return RawRecord(
            external_id=work_id,
            record_type="work",
            payload=work,
            canonical_url=work.get("id"),
            published_at=parse_datetime(work.get("publication_date")),
            volatile_keys=VOLATILE,
        )

    def _params(self, terms: list[str], start: str) -> dict[str, str]:
        query = " OR ".join(f'"{t}"' for t in terms)
        filters = [f"title_and_abstract.search:({query})", f"from_publication_date:{start}"]
        countries = self.config.get("countries")
        if countries:
            filters.append("institutions.country_code:" + "|".join(countries))
        return {
            "filter": ",".join(filters),
            "select": SELECT,
            "sort": "publication_date:desc",
            "per_page": str(int(self.config.get("per_page", 100))),
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _pages(self, params: dict[str, str]) -> Iterator[dict[str, Any]]:
        per_page = int(params["per_page"])
        if self.api_key:
            cursor: str | None = "*"
            while cursor:
                data = self.http.get_json(API_URL, params={**params, "cursor": cursor}, headers=self._headers())
                results = data.get("results") or []
                yield from results
                cursor = (data.get("meta") or {}).get("next_cursor") if results else None
            return
        # Without a key OpenAlex only serves the first page of cursor paging, so use basic paging.
        log.warning("OPENALEX_API_KEY not set: limited to the shared keyless budget and 10,000 results per query")
        for page in range(1, BASIC_PAGING_LIMIT // per_page + 1):
            data = self.http.get_json(API_URL, params={**params, "page": str(page)})
            results = data.get("results") or []
            yield from results
            if len(results) < per_page:
                return

    # --- normalization ----------------------------------------------------

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        work = raw.payload
        work_id = raw.external_id
        title = clean_text(work.get("title") or work.get("display_name"))
        doi = normalize_doi(work.get("doi"))
        topics = [t.get("display_name") for t in work.get("topics") or [] if t.get("display_name")]
        keywords = [k.get("display_name") for k in work.get("keywords") or [] if k.get("display_name")]
        primary_topic = work.get("primary_topic") or {}
        published = parse_datetime(work.get("publication_date"))

        aliases = [AliasDraft(alias=work["id"], alias_type=AliasType.URL, external_identifier=None)]
        if doi:
            aliases.append(AliasDraft(alias=doi, alias_type=AliasType.DOI, external_identifier=doi))

        entities: list[EntityDraft] = []
        publication = EntityDraft(
            key="work",
            identifier=f"work:{work_id}",
            entity_type=EntityType.PUBLICATION,
            canonical_name=title or f"OpenAlex work {work_id}",
            description=abstract_from_inverted_index(work.get("abstract_inverted_index")),
            properties=compact(
                {
                    "openalex_id": work.get("id"),
                    "doi": doi,
                    "publication_date": work.get("publication_date"),
                    "work_type": work.get("type"),
                    "language": work.get("language"),
                    "primary_topic": primary_topic.get("display_name"),
                    "field": (primary_topic.get("field") or {}).get("display_name"),
                    "topics": topics,
                    "keywords": keywords,
                    "reference_count": len(work.get("referenced_works") or []),
                    "author_count": len(work.get("authorships") or []),
                }
            ),
            aliases=aliases,
            is_primary=True,
            extraction_method="openalex_work",
        )
        entities.append(publication)

        relationships: list[RelationshipDraft] = []
        known_keys = {"work"}
        limit = int(self.config.get("max_authors_per_work", 100))
        for position, authorship in enumerate((work.get("authorships") or [])[:limit]):
            author = authorship.get("author") or {}
            author_id = short_id(author.get("id"))
            if not author_id:
                continue  # no stable identifier: kept in the raw payload only
            author_key = f"author:{author_id}"
            orcid = author.get("orcid")
            draft = person_draft(
                key=author_key,
                identifier=f"author:{author_id}",
                name=author.get("display_name"),
                aliases=[a for a in [external_alias(AliasType.ORCID, orcid)] if a],
                properties={"openalex_id": author.get("id"), "orcid": orcid},
            )
            if draft is None:
                continue
            if author_key not in known_keys:
                entities.append(draft)
                known_keys.add(author_key)
            relationships.append(
                RelationshipDraft(
                    source_key=author_key,
                    target_key="work",
                    relationship_type=RelationshipType.AUTHORED,
                    properties=compact(
                        {
                            "author_position": authorship.get("author_position"),
                            "author_index": position,
                            "is_corresponding": authorship.get("is_corresponding"),
                        }
                    ),
                )
            )
            for inst in authorship.get("institutions") or []:
                inst_id = short_id(inst.get("id"))
                if not inst_id:
                    continue
                inst_key = f"inst:{inst_id}"
                ror = inst.get("ror")
                inst_draft = organization_draft(
                    key=inst_key,
                    identifier=f"institution:{inst_id}",
                    name=inst.get("display_name"),
                    is_university=inst.get("type") == "education",
                    aliases=[a for a in [external_alias(AliasType.ROR, ror)] if a],
                    properties={
                        "openalex_id": inst.get("id"),
                        "ror": ror,
                        "country_code": inst.get("country_code"),
                        "institution_type": inst.get("type"),
                    },
                )
                if inst_draft is None:
                    continue
                if inst_key not in known_keys:
                    entities.append(inst_draft)
                    known_keys.add(inst_key)
                relationships.append(
                    RelationshipDraft(
                        source_key=author_key,
                        target_key=inst_key,
                        relationship_type=RelationshipType.MEMBER_OF,
                        properties={"context": "publication_affiliation", "publication_date": work.get("publication_date")},
                    )
                )

        signals = [
            SignalDraft(
                entity_key="work",
                signal_type=SignalType.NEW_PUBLICATION,
                description=title,
                event_date=published,
                published_at=published,
            )
        ]
        observations = []
        if work.get("cited_by_count") is not None:
            observations.append(
                ObservationDraft(
                    entity_key="work",
                    metric_name="citation_count",
                    value=Decimal(int(work["cited_by_count"])),
                    unit="citations",
                )
            )
        return NormalizedBundle(
            entities=entities, relationships=relationships, signals=signals, observations=observations
        )
