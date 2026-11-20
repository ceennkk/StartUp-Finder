from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup

from app.adapters.base import BaseAdapter
from app.config.settings import load_source_config
from app.domain import AliasType, EntityType, RelationshipType, SignalType, SourceType, VerificationStatus
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
from app.normalization.text import clean_text, name_key
from app.utils.dates import parse_datetime, utcnow

log = logging.getLogger(__name__)

SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SUMMARY_CHARS = 1500


def parse_sitemap(xml: bytes) -> list[tuple[str, datetime | None]]:
    root = ET.fromstring(xml)
    entries = []
    for url in root.findall("s:url", SITEMAP_NS):
        loc = url.find("s:loc", SITEMAP_NS)
        if loc is not None and loc.text:
            lastmod = url.find("s:lastmod", SITEMAP_NS)
            entries.append((loc.text.strip(), parse_datetime(lastmod.text) if lastmod is not None else None))
    return entries


def parse_story_page(html: str) -> dict[str, Any]:
    """Extraction method: server-rendered HTML of exist.de success stories (h1 title, first h2, body paragraphs, 'ZUR WEBSITE' link)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    h1 = main.find("h1")
    h2 = main.find("h2")
    paragraphs = [clean_text(p.get_text(" ")) for p in main.find_all("p")]
    text = " ".join(p for p in paragraphs if p)
    website = None
    for a in main.find_all("a", href=True):
        if "website" in a.get_text(" ").casefold() and not a["href"].startswith("mailto:"):
            website = a["href"]
            break
    published_meta = soup.find("meta", attrs={"property": "article:published_time"})
    return {
        "title": clean_text(h1.get_text(" ")) if h1 else None,
        "subtitle": clean_text(h2.get_text(" ")) if h2 else None,
        "summary": text[:SUMMARY_CHARS] or None,
        "text_for_matching": text,
        "website_url": website,
        "published_meta": published_meta["content"] if published_meta and published_meta.get("content") else None,
    }


def parse_program_page(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ")) if h1 else (clean_text(soup.title.get_text(" ")) if soup.title else None)
    return {"title": title, "description": clean_text(meta["content"]) if meta and meta.get("content") else None}


class ExistAdapter(BaseAdapter):
    """EXIST success stories and programme pages from exist.de.

    Access: official sitemap + public WordPress REST API (publication dates) + HTML parser.
    Not covered: foerderdatenbank.de (robots.txt disallows its search paths and sets Crawl-delay 30).
    Not extracted: person names from interview text (unstructured; no NER in Phase 1).
    """

    name = "exist"
    source = SourceSpec(
        source_name="exist",
        source_type=SourceType.HTML,
        base_url="https://exist.de",
        description="EXIST success stories and programme pages (public pages, sitemap and WordPress REST API).",
        terms_url="https://exist.de/datenschutz/",
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else load_source_config("exist")
        self.http.set_min_interval("exist.de", float(self.config.get("min_interval_seconds", 2)))

    # --- fetching ---------------------------------------------------------

    def fetch(self) -> Iterator[RawRecord]:
        yield from self._programs()
        yield from self._stories()

    def _programs(self) -> Iterator[RawRecord]:
        for program in self.config.get("programs") or []:
            html = self.http.get(program["url"], respect_robots=True).text
            parsed = parse_program_page(html)
            yield RawRecord(
                external_id=f"program:{program['key']}",
                record_type="program_page",
                payload={"key": program["key"], "configured_name": program["name"], "url": program["url"], **parsed},
                canonical_url=program["url"],
            )

    def _stories(self) -> Iterator[RawRecord]:
        sitemap_url = self.config["success_story_sitemap"]
        scope = "success-stories"
        cursor = self.get_cursor(scope)
        since = parse_datetime(cursor["from"]) if cursor and cursor.get("from") else None
        entries = parse_sitemap(self.http.get(sitemap_url, respect_robots=True).content)
        dates = self._wp_dates()
        started = utcnow()
        for url, lastmod in entries:
            if since and lastmod and lastmod < since:
                continue
            try:
                html = self.http.get(url, respect_robots=True).text
            except HttpFetchError as exc:
                log.warning("exist page failed", extra={"url": url, "error": str(exc)})
                continue
            page = parse_story_page(html)
            wp = dates.get(url.rstrip("/"), {})
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            matched = self._match_programs(page.pop("text_for_matching"))
            published = wp.get("date_gmt") or page.pop("published_meta", None)
            page.pop("published_meta", None)
            yield RawRecord(
                external_id=f"story:{slug}",
                record_type="success_story",
                payload={
                    "slug": slug,
                    "url": url,
                    "wp_id": wp.get("id"),
                    "published": published,
                    "modified": wp.get("modified_gmt"),
                    "sitemap_lastmod": lastmod.isoformat() if lastmod else None,
                    "programs_mentioned": matched,
                    **page,
                },
                canonical_url=url,
                published_at=parse_datetime(published),
            )
        lookback = int(self.config.get("lookback_days", 7))
        self.set_cursor(scope, {"from": (started - timedelta(days=lookback)).isoformat()})

    def _wp_dates(self) -> dict[str, dict[str, Any]]:
        api = self.config.get("wp_api")
        if not api:
            return {}
        try:
            items = self.http.get(
                api, params={"per_page": 100, "_fields": "id,link,date_gmt,modified_gmt"}, respect_robots=True
            ).json()
        except (HttpFetchError, ValueError) as exc:
            log.warning("exist wp api unavailable; publication dates may be NULL", extra={"error": str(exc)})
            return {}
        return {i["link"].rstrip("/"): i for i in items if i.get("link")}

    def _match_programs(self, text: str) -> list[dict[str, str]]:
        haystack = name_key(text)
        found = []
        for program in self.config.get("programs") or []:
            for keyword in program.get("keywords") or []:
                if name_key(keyword) in haystack:
                    found.append({"key": program["key"], "keyword": keyword})
                    break
        return found

    # --- normalization ----------------------------------------------------

    def _program_names(self) -> dict[str, str]:
        return {p["key"]: p["name"] for p in self.config.get("programs") or []}

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        if raw.record_type == "program_page":
            return self._normalize_program(raw)
        p = raw.payload
        published = parse_datetime(p.get("published"))
        org = organization_draft(
            key="org",
            identifier=f"exist-story:{p['slug']}",
            name=p.get("title"),
            description=p.get("subtitle"),
            aliases=[AliasDraft(alias=p["url"], alias_type=AliasType.URL)],
            properties=compact(
                {
                    "exist_story_url": p["url"],
                    "website": p.get("website_url"),
                    "summary": p.get("summary"),
                    "listed_by": "EXIST success story",
                }
            ),
            is_primary=True,
        )
        if org is None:
            raise ValueError("success story without title")
        org.extraction_method = "exist_success_story_html"
        entities = [org]
        relationships: list[RelationshipDraft] = []
        names = self._program_names()
        for hit in p.get("programs_mentioned") or []:
            key = f"program:{hit['key']}"
            entities.append(
                EntityDraft(
                    key=key,
                    identifier=key,
                    entity_type=EntityType.FUNDING_PROGRAM,
                    canonical_name=names.get(hit["key"], hit["key"]),
                    extraction_method="exist_program_keyword",
                )
            )
            relationships.append(
                RelationshipDraft(
                    source_key="org",
                    target_key=key,
                    relationship_type=RelationshipType.FUNDED_BY,
                    verification_status=VerificationStatus.UNVERIFIED,
                    properties={"evidence": "programme name mentioned in the EXIST story text", "keyword": hit["keyword"]},
                )
            )
        signals = [
            SignalDraft(
                entity_key="org",
                signal_type=SignalType.NEW_FUNDING_PROJECT,
                description=p.get("title"),
                event_date=None,  # funding start is not stated in structured form
                published_at=published,
                properties={"source_page_published_at": p.get("published")},
            )
        ]
        return NormalizedBundle(entities=entities, relationships=relationships, signals=signals)

    def _normalize_program(self, raw: RawRecord) -> NormalizedBundle:
        p = raw.payload
        key = f"program:{p['key']}"
        entity = EntityDraft(
            key="program",
            identifier=key,
            entity_type=EntityType.FUNDING_PROGRAM,
            canonical_name=p.get("configured_name") or p.get("title") or p["key"],
            description=p.get("description"),
            properties=compact({"url": p["url"], "page_title": p.get("title")}),
            aliases=[AliasDraft(alias=p["url"], alias_type=AliasType.URL)],
            is_primary=True,
            extraction_method="exist_program_page_html",
        )
        return NormalizedBundle(entities=[entity])
