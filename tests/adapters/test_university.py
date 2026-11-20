from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.base import AdapterConfigError
from app.adapters.university import UniversityAdapter
from app.adapters.university.connectors import (
    html_connector,
    jsonld_item,
    rss_connector,
    sitemap_connector,
)
from app.adapters.university.plugins import KitPlugin, get_plugin
from app.config.settings import Settings
from app.database.models import Entity, Relationship, Signal, SourceRecord
from app.utils.dates import utcnow
from tests.helpers import fast_http

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>KIT</title>
<item><title>KI soll neue Materialien entwickeln</title>
<link>https://www.kit.edu/kit/pi_2026_093_ki-soll-neue-materialien.php#top</link>
<guid>38397-2026-11-12 12:18:06</guid><pubDate>Thu, 12 Nov 2026 12:18:06 +0100</pubDate>
<description>&lt;p&gt;ERC Synergy Grant &amp;amp; mehr&lt;/p&gt;</description></item>
<item><title>Alter Eintrag</title><link>https://www.kit.edu/kit/pi_2020_001_alt.php</link>
<pubDate>Wed, 01 Jan 2020 10:00:00 +0100</pubDate><description>alt</description></item>
</channel></rss>""".encode()

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Uni"},
{"@type":"NewsArticle","headline":"Quantenchip entwickelt","description":"Neuer Chip.",
 "datePublished":"2026-11-10T09:00:00+01:00","url":"https://uni.test/news/chip","author":{"@type":"Person","name":"Do Not Store"}}]}
</script></head></html>"""

LISTING = """<html><body>
<article class="project"><a href="/p/1"><h3>Projekt Eins</h3></a><p>Beschreibung 1</p><time datetime="2026-11-01">1. Nov</time></article>
<article class="project"><a href="/p/2"><h3>Projekt Zwei</h3></a><p>Beschreibung 2</p></article>
<article class="other"><a href="/x">ignored</a></article></body></html>"""

SITEMAP = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://uni.test/news/chip</loc><lastmod>2026-11-10T08:00:00Z</lastmod></url>
<url><loc>https://uni.test/other/page</loc></url></urlset>"""


def http_for(handler):
    return fast_http(handler)


def routes(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p == "/robots.txt":
        return httpx.Response(404)
    return {
        "/pi.rss": httpx.Response(200, content=RSS),
        "/news/chip": httpx.Response(200, text=JSONLD_PAGE),
        "/projects": httpx.Response(200, text=LISTING),
        "/sitemap.xml": httpx.Response(200, content=SITEMAP),
    }.get(p, httpx.Response(404))


def client():
    return fast_http(routes)


def test_rss_connector_uses_link_without_fragment_and_cleans_html() -> None:
    items = list(rss_connector(client(), {"url": "https://uni.test/pi.rss"}, None))
    assert items[0]["url"] == "https://www.kit.edu/kit/pi_2026_093_ki-soll-neue-materialien.php"
    assert items[0]["summary"] == "ERC Synergy Grant & mehr"
    assert items[0]["published"].startswith("2026-11-12T11:18")  # normalized to UTC
    since = utcnow().replace(year=2026, month=1, day=1)
    assert [i["title"] for i in rss_connector(client(), {"url": "https://uni.test/pi.rss"}, since)] == [
        "KI soll neue Materialien entwickeln"
    ]


def test_jsonld_item_never_reads_authors() -> None:
    item = jsonld_item("https://uni.test/x", JSONLD_PAGE)
    assert item["title"] == "Quantenchip entwickelt" and item["url"] == "https://uni.test/news/chip"
    assert "Do Not Store" not in str(item)
    assert jsonld_item("https://uni.test/x", "<html></html>") is None


def test_html_connector_with_selectors() -> None:
    src = {"url": "https://uni.test/projects",
           "selectors": {"item": "article.project", "link": "a", "title": "h3", "summary": "p", "date": "time"}}
    items = list(html_connector(client(), src, None))
    assert [i["title"] for i in items] == ["Projekt Eins", "Projekt Zwei"]
    assert items[0]["url"] == "https://uni.test/p/1" and items[0]["published"].startswith("2026-11-01")
    assert items[1]["published"] is None  # unknown date stays NULL


def test_sitemap_connector_filters_by_pattern_and_reads_jsonld() -> None:
    src = {"url": "https://uni.test/sitemap.xml", "url_pattern": "/news/"}
    items = list(sitemap_connector(client(), src, None))
    assert [i["url"] for i in items] == ["https://uni.test/news/chip"]


def test_plugin_registry_and_kit_enrichment() -> None:
    item = KitPlugin().enrich({"url": "https://www.kit.edu/kit/pi_2026_094_x.php"}, {})
    assert item["extra"]["press_release_number"] == "2026/094"
    with pytest.raises(KeyError):
        get_plugin("nope")


CONFIG = {"sources": [
    {"key": "kit", "name": "Karlsruher Institut für Technologie", "aliases": ["KIT"], "country": "DE",
     "connector": "rss", "url": "https://uni.test/pi.rss", "kind": "press_release", "plugin": "kit", "min_interval_seconds": 0, "initial_days": 36500},
    {"key": "broken", "name": "Broken Uni", "connector": "rss", "url": "https://down.test/feed.rss", "min_interval_seconds": 0, "initial_days": 36500},
]}


def adapter(config=None, factory=None, only=None, **kw) -> UniversityAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "down.test":
            return httpx.Response(503)
        return routes(request)

    kw.setdefault("dry_run", factory is None)
    return UniversityAdapter(factory, http=fast_http(handler), settings=Settings(_env_file=None),
                             config=config or CONFIG, only=only, **kw)


def test_invalid_config_is_a_config_error() -> None:
    with pytest.raises(AdapterConfigError):
        adapter({"sources": []})
    with pytest.raises(AdapterConfigError):
        adapter({"sources": [{"key": "x", "name": "X", "connector": "ftp", "url": "u"}]})


def test_normalize_models_item_and_university_without_inventing_dates() -> None:
    a = adapter(only="kit")
    raw = next(iter(a.fetch()))
    bundle = a.normalize(raw)
    a.validate(bundle)
    kinds = {e.key: e.entity_type.value for e in bundle.entities}
    assert kinds == {"item": "publication", "uni": "university"}
    item = bundle.entities[0]
    assert item.properties["press_release_number"] == "2026/093"
    assert bundle.relationships[0].relationship_type.value == "PUBLISHED_BY"
    sig = bundle.signals[0]
    assert sig.signal_type.value == "NEW_PRESS_RELEASE" and sig.event_date is None and sig.published_at is not None


def test_one_failing_source_does_not_hide_the_others() -> None:
    a = adapter()
    result = a.run()
    assert result.status == "failed" and "broken" in (result.error_message or "")
    assert result.records_fetched == 2  # kit still delivered


@pytest.mark.db
def test_run_is_idempotent(session_factory) -> None:
    cfg = {"sources": [CONFIG["sources"][0]]}
    first = adapter(cfg, session_factory).run()
    assert (first.status, first.records_created) == ("success", 2)
    second = adapter(cfg, session_factory).run()
    assert (second.records_created, second.status) == (0, "success")
    with session_factory() as s:
        count = lambda m: s.execute(select(func.count()).select_from(m)).scalar_one()
        assert count(SourceRecord) == 2 and count(Signal) == 2 and count(Relationship) == 2
        assert s.execute(select(func.count()).select_from(Entity).where(Entity.entity_type == "university")).scalar_one() == 1
