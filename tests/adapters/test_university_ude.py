"""University of Duisburg-Essen (UDE): fixture-based tests for the first university example."""
from __future__ import annotations

import copy
import json
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.base import AdapterConfigError
from app.adapters.university import UniversityAdapter
from app.adapters.university.adapter import request_interval
from app.adapters.university.connectors import SitemapError, parse_page_metadata, validate_sitemap
from app.config.settings import Settings, load_source_config
from app.database.models import Entity, Relationship, Signal, SourceRecord, SyncState
from app.http.client import PoliteHttpClient
from app.utils.dates import utcnow
from tests.helpers import fast_http

FIXTURES = Path(__file__).parent.parent / "fixtures"
RSS = (FIXTURES / "ude_forschung.rss").read_text(encoding="utf-8").replace("LONGTEXT_PLACEHOLDER", "Lorem ipsum " * 300)
SITEMAP = (FIXTURES / "ude_sitemap.xml").read_bytes()
GUIDE_HTML = (FIXTURES / "ude_guide.html").read_text(encoding="utf-8")
SETTINGS = Settings(_env_file=None, contact_email="research@example.org")
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def ude_config(*, enable: tuple[str, ...] = (), **overrides: object) -> dict:
    """The shipped UDE configuration (sources.yaml); `enable` switches disabled sources on for a test."""
    sources = [copy.deepcopy(s) for s in load_source_config("universities")["sources"] if s["key"].startswith("ude_")]
    for src in sources:
        if src["key"] in enable:
            src["enabled"] = True
        src.update(overrides)
    return {"sources": sources}


class Site:
    """Mock of www.uni-due.de with a virtual clock so that request spacing can be asserted."""

    def __init__(self, robots: str | None = None, sitemap: bytes = SITEMAP, rss: str = RSS):
        self.now = 0.0
        self.requests: list[tuple[float, str, str]] = []
        self.robots, self.sitemap, self.rss = robots, sitemap, rss

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((self.now, request.url.path, request.headers.get("user-agent", "")))
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=self.robots) if self.robots is not None else httpx.Response(404)
        if path == "/rss/forschung.rss":
            return httpx.Response(200, content=self.rss.encode(), headers={"content-type": "application/rss+xml"})
        if path == "/sitemap.xml":
            return httpx.Response(200, content=self.sitemap)
        if path.startswith("/guide/"):
            return httpx.Response(200, text=GUIDE_HTML)
        return httpx.Response(404)

    def client(self) -> PoliteHttpClient:
        def sleep(seconds: float) -> None:
            self.now += seconds

        return PoliteHttpClient(
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            sleep=sleep,
            monotonic=lambda: self.now,
            max_retries=0,
        )

    def paths(self) -> list[str]:
        return [path for _, path, _ in self.requests]


def make(config: dict, site: Site | None = None, factory=None, only: str | None = None, settings: Settings = SETTINGS):
    site = site or Site()
    return site, UniversityAdapter(
        factory, http=site.client(), settings=settings, config=config, only=only, dry_run=factory is None
    )


# --- configuration ---------------------------------------------------------------------------------


def test_shipped_config_enables_only_the_research_feed() -> None:
    sources = {s["key"]: s for s in load_source_config("universities")["sources"] if s["key"].startswith("ude_")}
    assert {k for k, s in sources.items() if s.get("enabled", True)} == {"ude_forschung"}
    assert sources["ude_forschung"]["url"] == "https://www.uni-due.de/rss/forschung.rss"
    assert sources["ude_aktuell"]["url"] == "https://www.uni-due.de/rss/aktuell.rss"
    assert sources["ude_guide"]["url"] == "https://www.uni-due.de/guide/"
    assert sources["ude_guide"]["sitemap"]["url"] == "https://www.uni-due.de/sitemap.xml"
    assert all(s["min_interval_seconds"] >= 10 and s["require_contact_email"] for s in sources.values())


def test_disabled_sources_cannot_be_selected_or_collected_by_accident() -> None:
    config = ude_config()
    with pytest.raises(AdapterConfigError, match="disabled"):
        make(config, only="ude_aktuell")
    with pytest.raises(AdapterConfigError, match="disabled"):
        make(config, only="ude")  # group selection includes the disabled sources
    with pytest.raises(AdapterConfigError, match="unknown university source"):
        make(config, only="nope")
    _, adapter = make(config, only="ude_forschung")
    assert [s["key"] for s in adapter.sources] == ["ude_forschung"]
    _, everything = make(config)
    assert [s["key"] for s in everything.sources] == ["ude_forschung"]


def test_contact_email_is_required_and_part_of_the_user_agent() -> None:
    with pytest.raises(AdapterConfigError, match="CONTACT_EMAIL"):
        make(ude_config(), settings=Settings(_env_file=None, contact_email=None))
    assert "research@example.org" in SETTINGS.user_agent and "VentureRadar" in SETTINGS.user_agent
    assert "contact" not in Settings(_env_file=None, contact_email=None).user_agent


def test_html_connectors_have_a_ten_second_floor_but_feeds_keep_their_setting() -> None:
    assert request_interval({"connector": "page_metadata", "min_interval_seconds": 0}) == 10.0
    assert request_interval({"connector": "html"}) == 10.0
    assert request_interval({"connector": "rss", "min_interval_seconds": 2}) == 2.0
    assert request_interval({"connector": "rss", "min_interval_seconds": 15}) == 15.0


# --- research feed (end to end) ---------------------------------------------------------------------


def test_research_feed_end_to_end_stores_metadata_but_no_full_text_or_images() -> None:
    site, adapter = make(ude_config(initial_days=36500), only="ude_forschung")
    records = list(adapter.fetch())
    assert [r.canonical_url for r in records] == [
        "https://www.uni-due.de/2026-11-10-quantensensoren",
        "https://www.uni-due.de/2026-11-05-langer-artikel",
        "https://www.uni-due.de/2025-01-15-aelterer-beitrag",
    ]
    assert all(r.published_at is not None for r in records)
    stored = json.dumps([r.payload for r in records])
    assert "FULL_ARTICLE_BODY_MUST_NOT_BE_STORED" not in stored  # content:encoded ignored
    assert "quanten.jpg" not in stored and "enclosure" not in stored  # no images
    long_item = records[1].payload
    assert 0 < len(long_item["summary"]) <= 500 and long_item["summary"].endswith("\u2026")
    assert records[0].payload["summary"] == "Ein Forschungsteam zeigt ein neues Verfahren. Kurzer Teaser."

    bundle = adapter.normalize(records[0])
    adapter.validate(bundle)
    assert {e.key: e.entity_type.value for e in bundle.entities} == {"item": "publication", "uni": "university"}
    item, uni = bundle.entities
    assert item.properties["topic"] == "research" and item.properties["url"] == records[0].canonical_url
    assert uni.identifier == "university:ude" and "UDE" in {a.alias for a in uni.aliases}
    assert bundle.relationships[0].relationship_type.value == "PUBLISHED_BY"
    assert bundle.signals[0].published_at is not None and bundle.signals[0].event_date is None


def test_uses_the_configured_url_and_checks_robots_first() -> None:
    config = ude_config(initial_days=36500)
    config["sources"][0]["url"] = "https://feeds.example.test/other.rss"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.url.host}{request.url.path}")
        return httpx.Response(200, content=RSS.encode()) if request.url.path == "/other.rss" else httpx.Response(404)

    adapter = UniversityAdapter(
        None, http=fast_http(handler), settings=SETTINGS, config=config, only="ude_forschung", dry_run=True
    )
    assert len(list(adapter.fetch())) == 3
    assert seen == ["feeds.example.test/robots.txt", "feeds.example.test/other.rss"]


def test_first_run_window_and_max_items() -> None:
    def feed(days_ago: int, slug: str) -> str:
        date = format_datetime(utcnow() - timedelta(days=days_ago))
        return f"<item><title>T {slug}</title><link>https://www.uni-due.de/{slug}</link><pubDate>{date}</pubDate></item>"

    rss = f'<?xml version="1.0"?><rss version="2.0"><channel>{feed(2, "neu")}{feed(10, "mittel")}{feed(200, "alt")}</channel></rss>'
    _, adapter = make(ude_config(initial_days=30), Site(rss=rss), only="ude_forschung")
    assert [r.canonical_url.rsplit("/", 1)[1] for r in adapter.fetch()] == ["neu", "mittel"]
    _, capped = make(ude_config(initial_days=30, max_items=1), Site(rss=rss), only="ude_forschung")
    assert len(list(capped.fetch())) == 1


def test_robots_disallow_stops_collection_without_fetching_the_feed() -> None:
    site, adapter = make(ude_config(), Site(robots="User-agent: *\nDisallow: /rss/\n"), only="ude_forschung")
    result = adapter.run()
    assert result.status == "failed" and "robots" in (result.error_message or "").lower()
    assert result.records_fetched == 0
    assert "/rss/forschung.rss" not in site.paths()


def test_requests_are_spaced_at_least_ten_seconds_and_use_the_contact_user_agent() -> None:
    site, adapter = make(ude_config(initial_days=36500), only="ude_forschung")
    list(adapter.fetch())
    assert site.paths() == ["/robots.txt", "/rss/forschung.rss"]
    assert site.requests[1][0] - site.requests[0][0] >= 10


# --- GUIDE (page metadata + validated sitemap discovery) ----------------------------------------------


GUIDE_ENABLED = {"enable": ("ude_guide",), "initial_days": 36500}


def guide_only_config(**kw: object) -> dict:
    config = ude_config(**GUIDE_ENABLED, **kw)
    config["sources"] = [s for s in config["sources"] if s["key"] == "ude_guide"]
    return config


def test_guide_reads_only_metadata_and_respects_the_sitemap_prefix_and_spacing() -> None:
    site, adapter = make(guide_only_config(), only="ude_guide")
    records = list(adapter.fetch())
    urls = [r.canonical_url for r in records]
    assert urls == [
        "https://www.uni-due.de/guide/",
        "https://www.uni-due.de/guide/index.php",
        "https://www.uni-due.de/guide/start-ups.php",
        "https://www.uni-due.de/guide/team.php",
    ]  # nothing outside /guide/ is requested, no links are followed
    assert "/biologie/index.php" not in site.paths()
    stored = json.dumps([r.payload for r in records])
    assert "BODY_TEXT_MUST_NOT_BE_STORED" not in stored and ".jpg" not in stored
    assert records[0].payload["title"] == "GUIDE Gruendungszentrum"
    assert records[0].payload["summary"].startswith("Gruendungsberatung")
    assert records[0].payload["published"] is None  # unknown stays unknown
    assert records[2].payload["extra"]["sitemap_lastmod"].startswith("2026-10-02")
    times = [t for t, _, _ in site.requests]
    assert site.paths()[:2] == ["/robots.txt", "/sitemap.xml"] and len(times) == 6
    assert all(b - a >= 10 for a, b in zip(times, times[1:]))


def test_guide_models_one_organization_unit_without_signals() -> None:
    _, adapter = make(guide_only_config(), only="ude_guide")
    records = list(adapter.fetch())
    home, other = adapter.normalize(records[0]), adapter.normalize(records[3])
    for bundle in (home, other):
        adapter.validate(bundle)
        assert bundle.signals == []
        assert {e.identifier for e in bundle.entities} == {"unit:ude_guide", "university:ude"}
        rel = bundle.relationships[0]
        assert (rel.source_key, rel.target_key, rel.relationship_type.value) == ("unit", "uni", "MEMBER_OF")
    assert home.entities[0].is_primary and home.entities[0].description
    assert not other.entities[0].is_primary  # sub pages are provenance only; they do not overwrite the unit
    assert adapter.normalize(records[1]).entities[0].is_primary  # /guide/index.php is the same home page


def test_guide_extra_pages_are_configurable_and_sitemap_is_optional() -> None:
    config = guide_only_config(urls=["https://www.uni-due.de/guide/team.php"], sitemap=None)
    site, adapter = make(config, only="ude_guide")
    assert [r.canonical_url for r in adapter.fetch()] == [
        "https://www.uni-due.de/guide/",
        "https://www.uni-due.de/guide/team.php",
    ]
    assert "/sitemap.xml" not in site.paths()


def test_invalid_sitemap_fails_the_source_before_any_page_is_requested() -> None:
    site, adapter = make(guide_only_config(), Site(sitemap=b"<html>not a sitemap</html>"), only="ude_guide")
    result = adapter.run()
    assert result.status == "failed" and "sitemap" in (result.error_message or "")
    assert result.records_fetched == 0
    assert not any(p.startswith("/guide/") for p in site.paths())


def test_page_metadata_parser_ignores_body_and_falls_back() -> None:
    item = parse_page_metadata(GUIDE_HTML, "https://www.uni-due.de/guide/")
    assert item["title"] == "GUIDE Gruendungszentrum" and "BODY_TEXT" not in json.dumps(item)
    only_title = parse_page_metadata("<html><head><title> Nur Titel </title></head></html>", "https://x.test/a")
    assert only_title["title"] == "Nur Titel" and only_title["summary"] is None
    assert parse_page_metadata("<html><body>no title</body></html>", "https://x.test/a") is None


# --- sitemap validation --------------------------------------------------------------------------------

SITEMAP_URL = "https://www.uni-due.de/sitemap.xml"


def test_validate_sitemap_accepts_the_fixture_and_parses_lastmod() -> None:
    entries = dict(validate_sitemap(SITEMAP, SITEMAP_URL))
    assert len(entries) == 5
    assert entries["https://www.uni-due.de/guide/start-ups.php"].isoformat().startswith("2026-10-02")
    assert entries["https://www.uni-due.de/"] is None


@pytest.mark.parametrize(
    ("xml", "reason"),
    [
        (b"<urlset", "well-formed"),
        (b"", "well-formed"),
        (f"<sitemapindex {NS}><sitemap><loc>https://www.uni-due.de/a.xml</loc></sitemap></sitemapindex>".encode(), "root element"),
        (b"<urlset><url><loc>https://www.uni-due.de/a</loc></url></urlset>", "root element"),  # missing namespace
        (f"<urlset {NS}></urlset>".encode(), "no <url>"),
        (f"<urlset {NS}><url><lastmod>2026-01-01</lastmod></url></urlset>".encode(), "invalid <loc>"),
        (f"<urlset {NS}><url><loc>ftp://www.uni-due.de/a</loc></url></urlset>".encode(), "invalid <loc>"),
        (f"<urlset {NS}><url><loc>https://evil.example/a</loc></url></urlset>".encode(), "another site"),
        (f'<!DOCTYPE urlset [<!ENTITY x "y">]><urlset {NS}><url><loc>https://www.uni-due.de/&x;</loc></url></urlset>'.encode(), "DOCTYPE"),
    ],
)
def test_validate_sitemap_rejects_unusable_documents(xml: bytes, reason: str) -> None:
    with pytest.raises(SitemapError, match=reason):
        validate_sitemap(xml, SITEMAP_URL)


def test_validate_sitemap_enforces_the_url_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.university.connectors.SITEMAP_MAX_URLS", 2)
    xml = f"<urlset {NS}>" + "".join(f"<url><loc>https://www.uni-due.de/{i}</loc></url>" for i in range(3)) + "</urlset>"
    with pytest.raises(SitemapError, match="more than"):
        validate_sitemap(xml.encode(), SITEMAP_URL)


# --- persistence -----------------------------------------------------------------------------------------


@pytest.mark.db
def test_ude_run_is_idempotent_and_keeps_provenance(session_factory) -> None:
    config = ude_config(enable=("ude_guide",), initial_days=36500)
    config["sources"] = [s for s in config["sources"] if s["key"] != "ude_aktuell"]
    _, first = make(config, factory=session_factory, only="ude")
    result = first.run()
    assert result.status == "success" and result.records_created == 7  # 3 feed items + 4 GUIDE pages
    _, second = make(config, factory=session_factory, only="ude")
    again = second.run()
    assert (again.status, again.records_created, again.records_updated) == ("success", 0, 0)

    with session_factory() as s:
        count = lambda model, *where: s.execute(select(func.count()).select_from(model).where(*where)).scalar_one()
        assert count(SourceRecord) == 7
        assert count(Entity, Entity.entity_type == "university") == 1  # one UDE entity shared by all UDE sources
        assert count(Entity, Entity.entity_type == "publication") == 3
        assert count(Entity, Entity.entity_type == "organization") == 1  # GUIDE unit
        assert count(Signal) == 3  # feed items only; the unit has no signal
        assert count(Relationship) == 7 and count(Relationship, Relationship.source_record_id.is_(None)) == 0
        scopes = {row.scope_key for row in s.execute(select(SyncState)).scalars()}
        assert scopes == {"ude_forschung", "ude_guide"}
        raw = json.dumps([r.raw_payload for r in s.execute(select(SourceRecord)).scalars()])
        assert "FULL_ARTICLE_BODY_MUST_NOT_BE_STORED" not in raw and "BODY_TEXT_MUST_NOT_BE_STORED" not in raw
