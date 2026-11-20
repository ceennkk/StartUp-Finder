from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.exist import ExistAdapter, parse_program_page, parse_sitemap, parse_story_page
from app.config.settings import Settings
from app.database.models import Entity, Relationship, Signal, SourceRecord
from tests.helpers import fast_http

STORY_HTML = (Path(__file__).parent.parent / "fixtures" / "exist_story.html").read_text(encoding="utf-8")
SITEMAP = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://exist.de/success-stories/katapult/</loc><lastmod>2026-10-13T12:33:30+02:00</lastmod></url>
<url><loc>https://exist.de/success-stories/old-one/</loc><lastmod>2020-01-01T00:00:00+00:00</lastmod></url>
</urlset>"""
PROGRAM_HTML = '<html><head><title>x</title><meta name="description" content=" Förderung für  Gründungen. "></head><body><h1>Gründungsstipendium</h1></body></html>'
CONFIG = {
    "success_story_sitemap": "https://exist.de/success-story-sitemap1.xml",
    "wp_api": "https://exist.de/wp-json/wp/v2/success-story",
    "min_interval_seconds": 0,
    "lookback_days": 7,
    "programs": [
        {"key": "gruendungsstipendium", "name": "EXIST-Gründungsstipendium", "url": "https://exist.de/programm/gruendungsstipendium/", "keywords": ["Gründungsstipendium"]},
        {"key": "forschungstransfer", "name": "EXIST-Forschungstransfer", "url": "https://exist.de/programm/forschungstransfer/", "keywords": ["Forschungstransfer"]},
    ],
}


def site(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /wp-admin/\n")
    if path == "/success-story-sitemap1.xml":
        return httpx.Response(200, content=SITEMAP)
    if path == "/wp-json/wp/v2/success-story":
        return httpx.Response(200, json=[{"id": 5916, "link": "https://exist.de/success-stories/katapult/",
                                          "date_gmt": "2026-09-10T15:51:53", "modified_gmt": "2026-10-13T10:33:30"}])
    if path.startswith("/success-stories/"):
        return httpx.Response(200, text=STORY_HTML)
    if path.startswith("/programm/"):
        return httpx.Response(200, text=PROGRAM_HTML)
    return httpx.Response(404)


def adapter(handler=site, factory=None, **kw) -> ExistAdapter:
    kw.setdefault("dry_run", factory is None)
    return ExistAdapter(factory, http=fast_http(handler), settings=Settings(_env_file=None), config=CONFIG, **kw)


def test_parse_story_page() -> None:
    page = parse_story_page(STORY_HTML)
    assert page["title"] == "KATAPULT"
    assert page["subtitle"].startswith("Wissenschaft, Daten")
    assert page["website_url"] == "https://www.katapult-magazin.de/"
    assert "Gründungsstipendium" in page["text_for_matching"]
    assert page["published_meta"].startswith("2026-09-10")


def test_parse_sitemap_and_program_page() -> None:
    entries = parse_sitemap(SITEMAP)
    assert entries[0][0].endswith("/katapult/") and entries[0][1].isoformat().startswith("2026-10-13T10:33")
    assert parse_program_page(PROGRAM_HTML) == {"title": "Gründungsstipendium", "description": "Förderung für Gründungen."}


def test_fetch_records_dates_programs_and_separates_timestamps() -> None:
    records = {r.external_id: r for r in adapter().fetch()}
    story = records["story:katapult"].payload
    assert story["published"] == "2026-09-10T15:51:53"  # publication on exist.de, not project/funding start
    assert story["programs_mentioned"] == [{"key": "gruendungsstipendium", "keyword": "Gründungsstipendium"}]
    assert "funding_start" not in story and "project_start" not in story
    assert records["story:katapult"].published_at.year == 2026
    assert "program:gruendungsstipendium" in records


def test_normalize_story_keeps_relationship_unverified_and_event_date_null() -> None:
    a = adapter()
    records = {r.external_id: r for r in a.fetch()}
    bundle = a.normalize(records["story:katapult"])
    a.validate(bundle)
    org = bundle.entities[0]
    assert org.entity_type.value == "organization" and org.properties["website"] == "https://www.katapult-magazin.de/"
    rel = bundle.relationships[0]
    assert rel.relationship_type.value == "FUNDED_BY" and rel.verification_status.value == "unverified"
    sig = bundle.signals[0]
    assert sig.signal_type.value == "NEW_FUNDING_PROJECT" and sig.event_date is None and sig.published_at is not None


def test_robots_disallow_blocks_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return site(request)

    result = adapter(handler).run()
    assert result.status == "failed" and "robots" in (result.error_message or "").lower()


@pytest.mark.db
def test_run_idempotent_and_watermark_skips_old_pages(session_factory) -> None:
    first = adapter(site, session_factory).run()
    assert (first.status, first.records_created) == ("success", 4)  # 2 programmes + 2 stories (no watermark yet)
    second = adapter(site, session_factory).run()
    # Stories whose sitemap lastmod predates the watermark are skipped; programme pages are re-read.
    assert (second.records_created, second.records_fetched, second.records_unchanged) == (0, 2, 2)
    with session_factory() as s:
        count = lambda m: s.execute(select(func.count()).select_from(m)).scalar_one()
        assert count(SourceRecord) == 4 and count(Relationship) == 2 and count(Signal) == 2
        assert s.execute(select(func.count()).select_from(Entity).where(Entity.entity_type == "funding_program")).scalar_one() == 2
