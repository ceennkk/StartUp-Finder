from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from app.adapters.base import BaseAdapter
from app.config.settings import load_search_terms
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
from app.normalization.persons import person_draft
from app.normalization.publications import compact
from app.normalization.text import clean_text, name_key, normalize_doi
from app.utils.dates import parse_datetime, utcnow

log = logging.getLogger(__name__)

API_URL = "https://export.arxiv.org/api/query"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
}
_ID = re.compile(r"arxiv\.org/abs/(?P<id>.+?)(?:v(?P<version>\d+))?$")
HARD_RESULT_WINDOW = 30_000  # the arXiv API cannot page beyond this offset


def _text(node: ET.Element, path: str) -> str | None:
    found = node.find(path, NS)
    return clean_text(found.text) if found is not None and found.text else None


def parse_entry(entry: ET.Element) -> dict[str, Any] | None:
    match = _ID.search(_text(entry, "a:id") or "")
    if not match:
        return None
    pdf_url = abs_url = None
    for link in entry.findall("a:link", NS):
        if link.get("title") == "pdf":
            pdf_url = link.get("href")
        elif link.get("rel") == "alternate":
            abs_url = link.get("href")
    primary = entry.find("arxiv:primary_category", NS)
    return {
        "arxiv_id": match.group("id"),
        "version": int(match.group("version")) if match.group("version") else None,
        "title": _text(entry, "a:title"),
        "summary": _text(entry, "a:summary"),
        "authors": [
            {"name": _text(a, "a:name"), "affiliations": [clean_text(x.text) for x in a.findall("arxiv:affiliation", NS) if x.text]}
            for a in entry.findall("a:author", NS)
        ],
        "published": _text(entry, "a:published"),
        "updated": _text(entry, "a:updated"),
        "categories": [c.get("term") for c in entry.findall("a:category", NS) if c.get("term")],
        "primary_category": primary.get("term") if primary is not None else None,
        "doi": _text(entry, "arxiv:doi"),
        "journal_ref": _text(entry, "arxiv:journal_ref"),
        "comment": _text(entry, "arxiv:comment"),
        "abs_url": abs_url,
        "pdf_url": pdf_url,  # link only: arXiv terms forbid storing PDFs
    }


class ArxivAdapter(BaseAdapter):
    name = "arxiv"
    source = SourceSpec(
        source_name="arxiv",
        source_type=SourceType.API,
        base_url="https://export.arxiv.org/api",
        description="arXiv e-print metadata (CC0) via the official API; one request every 3 seconds.",
        terms_url="https://info.arxiv.org/help/api/tou.html",
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else load_search_terms("arxiv")
        self.http.set_min_interval("export.arxiv.org", 3.0)  # arXiv terms: at most one request every 3 s

    def fetch(self) -> Iterator[RawRecord]:
        categories = self.config.get("categories") or []
        if not categories:
            return
        now = utcnow()
        scope = "submitted"
        cursor = self.get_cursor(scope)
        if cursor and cursor.get("from"):
            start_dt = datetime.fromisoformat(cursor["from"])
        else:
            start_dt = now - timedelta(days=int(self.config.get("default_start_days_back", 7)))

        query = "(" + " OR ".join(f"cat:{c}" for c in categories) + ")"
        for keyword in self.config.get("keywords") or []:
            query += f' AND all:"{keyword}"'
        query += f" AND submittedDate:[{start_dt:%Y%m%d%H%M} TO {now:%Y%m%d%H%M}]"

        page_size = int(self.config.get("page_size", 100))
        max_results = min(int(self.config.get("max_results_per_run", 2000)), HARD_RESULT_WINDOW)
        offset = 0
        last_published: datetime | None = None
        complete = False
        while offset < max_results:
            params = {
                "search_query": query,
                "start": offset,
                "max_results": min(page_size, max_results - offset),
                "sortBy": "submittedDate",
                "sortOrder": "ascending",  # oldest first, so a capped run still advances the watermark
            }
            root = ET.fromstring(self.http.get(API_URL, params=params).content)
            entries = root.findall("a:entry", NS)
            if entries and "api/errors" in (_text(entries[0], "a:id") or ""):
                raise HttpFetchError(f"arXiv API error: {_text(entries[0], 'a:summary')}")
            total = int(_text(root, "os:totalResults") or 0)
            for entry in entries:
                parsed = parse_entry(entry)
                if parsed is None:
                    continue
                published = parse_datetime(parsed["published"])
                last_published = published or last_published
                yield RawRecord(
                    external_id=parsed["arxiv_id"],
                    record_type="preprint",
                    payload=parsed,
                    canonical_url=parsed["abs_url"],
                    published_at=published,
                )
            offset += len(entries)
            if not entries or offset >= total:
                complete = True
                break

        if complete or last_published is None:
            lookback = int(self.config.get("lookback_days", 1))
            watermark = now - timedelta(days=lookback)
        else:
            log.warning("arxiv result cap reached; the rest is fetched on the next run", extra={"cap": max_results})
            watermark = last_published
        self.set_cursor(scope, {"from": watermark.replace(tzinfo=None).isoformat(timespec="minutes")})

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        p = raw.payload
        arxiv_id = p["arxiv_id"]
        doi = normalize_doi(p.get("doi"))
        published = parse_datetime(p.get("published"))
        aliases = [AliasDraft(alias=f"arXiv:{arxiv_id}", alias_type=AliasType.NAME, external_identifier=None)]
        if p.get("abs_url"):
            aliases.append(AliasDraft(alias=p["abs_url"], alias_type=AliasType.URL))
        if doi:
            aliases.append(AliasDraft(alias=doi, alias_type=AliasType.DOI, external_identifier=doi))

        paper = EntityDraft(
            key="paper",
            identifier=f"paper:{arxiv_id}",
            entity_type=EntityType.PUBLICATION,
            canonical_name=p.get("title") or f"arXiv:{arxiv_id}",
            description=p.get("summary"),
            properties=compact(
                {
                    "arxiv_id": arxiv_id,
                    "version": p.get("version"),
                    "published": p.get("published"),
                    "updated": p.get("updated"),
                    "categories": p.get("categories"),
                    "primary_category": p.get("primary_category"),
                    "doi": doi,
                    "journal_ref": p.get("journal_ref"),
                    "comment": p.get("comment"),
                    "abs_url": p.get("abs_url"),
                    "pdf_url": p.get("pdf_url"),
                    "author_count": len(p.get("authors") or []),
                }
            ),
            aliases=aliases,
            is_primary=True,
            extraction_method="arxiv_atom_entry",
        )
        entities = [paper]
        relationships: list[RelationshipDraft] = []
        known = {"paper"}
        for position, author in enumerate(p.get("authors") or []):
            # arXiv exposes no author IDs, so each authorship is its own person entity; same names are never merged.
            key = f"author:{arxiv_id}:{position}"
            draft = person_draft(key=key, identifier=key, name=author.get("name"),
                                 properties={"author_index": position, "arxiv_id": arxiv_id})
            if draft is None:
                continue
            entities.append(draft)
            relationships.append(
                RelationshipDraft(
                    source_key=key,
                    target_key="paper",
                    relationship_type=RelationshipType.AUTHORED,
                    properties={"author_index": position},
                )
            )
            for affiliation in author.get("affiliations") or []:
                org_key = f"org:{name_key(affiliation)}"
                if org_key not in known:
                    org = organization_draft(key=org_key, identifier=org_key, name=affiliation)
                    if org is None:
                        continue
                    entities.append(org)
                    known.add(org_key)
                relationships.append(
                    RelationshipDraft(
                        source_key=key,
                        target_key=org_key,
                        relationship_type=RelationshipType.MEMBER_OF,
                        properties={"context": "arxiv_affiliation_metadata", "arxiv_id": arxiv_id},
                    )
                )

        signals = [
            SignalDraft(
                entity_key="paper",
                signal_type=SignalType.NEW_PUBLICATION,
                description=p.get("title"),
                event_date=published,
                published_at=published,
            )
        ]
        return NormalizedBundle(entities=entities, relationships=relationships, signals=signals)
