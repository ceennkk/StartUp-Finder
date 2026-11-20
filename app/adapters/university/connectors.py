from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup

from app.http.client import PoliteHttpClient
from app.normalization.text import clean_text, strip_html
from app.utils.dates import parse_datetime

Item = dict[str, Any]
Connector = Callable[[PoliteHttpClient, dict[str, Any], datetime | None], Iterator[Item]]

_SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_JSONLD_ITEM_TYPES = {"Article", "NewsArticle", "BlogPosting", "Event", "ResearchProject", "Project", "Dataset", "WebPage"}
# Only metadata and a short teaser are stored; complete article texts are never reproduced.
SUMMARY_MAX_CHARS = 500
SITEMAP_MAX_URLS = 50_000  # limit from the sitemaps.org protocol


class SitemapError(ValueError):
    """The sitemap is not valid enough to be used for URL discovery."""


def short_text(value: str | None, limit: int = SUMMARY_MAX_CHARS) -> str | None:
    text = clean_text(value)
    if text and len(text) > limit:
        text = text[: limit - 1].rstrip() + "\u2026"
    return text


def _same_site(a: str, b: str) -> bool:
    return a.lower().removeprefix("www.") == b.lower().removeprefix("www.")


def validate_sitemap(xml: bytes, sitemap_url: str) -> list[tuple[str, datetime | None]]:
    """Parse a <urlset> sitemap and return (url, lastmod). Raises SitemapError unless the document is well-formed,
    uses the sitemap namespace, stays within the protocol limits and only lists URLs of the sitemap's own site."""
    if b"<!DOCTYPE" in xml[:2048].upper() or b"<!ENTITY" in xml.upper():
        raise SitemapError("sitemap must not contain a DOCTYPE or entity declarations")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise SitemapError(f"sitemap is not well-formed XML: {exc}") from exc
    if root.tag != f"{{{_SITEMAP_NS['s']}}}urlset":
        raise SitemapError(f"unexpected sitemap root element {root.tag!r} (expected a urlset in the sitemap namespace)")
    nodes = root.findall("s:url", _SITEMAP_NS)
    if not nodes:
        raise SitemapError("sitemap contains no <url> entries")
    if len(nodes) > SITEMAP_MAX_URLS:
        raise SitemapError(f"sitemap lists {len(nodes)} URLs, more than the allowed {SITEMAP_MAX_URLS}")
    host = urlparse(sitemap_url).hostname or ""
    entries: dict[str, datetime | None] = {}
    for node in nodes:
        loc = node.find("s:loc", _SITEMAP_NS)
        url = (loc.text or "").strip() if loc is not None else ""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise SitemapError(f"invalid <loc> value {url!r}")
        if not _same_site(parsed.hostname, host):
            raise SitemapError(f"sitemap lists a URL of another site: {url!r}")
        lastmod = node.find("s:lastmod", _SITEMAP_NS)
        entries[urldefrag(url)[0]] = parse_datetime(lastmod.text) if lastmod is not None and lastmod.text else None
    return list(entries.items())


def _item(url: str, title: str | None, summary: str | None, published: Any, tags: list[str] | None = None) -> Item | None:
    url = urldefrag(url)[0].strip()
    title = clean_text(title)
    if not url or not title:
        return None
    return {
        "url": url,
        "title": title,
        "summary": short_text(summary),
        "published": published.isoformat() if isinstance(published, datetime) else published,
        "tags": [t for t in (tags or []) if t],
    }


def rss_connector(http: PoliteHttpClient, src: dict[str, Any], since: datetime | None) -> Iterator[Item]:
    """Extraction method: RSS/Atom feed parsed with feedparser; the item link is the identity (feed GUIDs may embed timestamps)."""
    feed = feedparser.parse(http.get(src["url"], respect_robots=True).content)
    emitted = 0
    for entry in feed.entries:
        published = parse_datetime(entry.get("published") or entry.get("updated"))
        if since and published and published < since:
            continue
        # Enclosures (images) and full content are deliberately ignored.
        item = _item(
            entry.get("link", ""),
            entry.get("title"),
            strip_html(entry.get("summary")),
            published,
            [t.get("term") for t in entry.get("tags", [])],
        )
        if item:
            yield item
            emitted += 1
            if emitted >= int(src.get("max_items", 500)):
                return


def parse_jsonld(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for script in BeautifulSoup(html, "html.parser").find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        out.extend(n for n in nodes if isinstance(n, dict))
    return out


def jsonld_item(url: str, html: str) -> Item | None:
    """Extraction method: schema.org JSON-LD on the page. Authors/persons are deliberately not read."""
    for node in parse_jsonld(html):
        kind = node.get("@type")
        kinds = set(kind) if isinstance(kind, list) else {kind}
        if kinds & _JSONLD_ITEM_TYPES:
            return _item(
                node.get("url") or url,
                node.get("headline") or node.get("name"),
                node.get("description"),
                node.get("datePublished") or node.get("startDate"),
                [node["keywords"]] if isinstance(node.get("keywords"), str) else list(node.get("keywords") or []),
            )
    return None


def jsonld_connector(http: PoliteHttpClient, src: dict[str, Any], since: datetime | None) -> Iterator[Item]:
    for url in src.get("urls") or [src["url"]]:
        item = jsonld_item(url, http.get(url, respect_robots=True).text)
        if item:
            yield item


def discover_sitemap_urls(
    http: PoliteHttpClient,
    sitemap_url: str,
    since: datetime | None,
    *,
    pattern: str | None = None,
    prefix: str | None = None,
) -> list[tuple[str, datetime | None]]:
    """Validated sitemap URLs filtered by regex and/or path prefix; entries unchanged since `since` are skipped."""
    entries = validate_sitemap(http.get(sitemap_url, respect_robots=True).content, sitemap_url)
    regex = re.compile(pattern) if pattern else None
    found = []
    for url, modified in entries:
        if regex and not regex.search(url):
            continue
        if prefix and not urlparse(url).path.startswith(prefix):
            continue
        if since and modified and modified < since:
            continue
        found.append((url, modified))
    return found


def sitemap_connector(http: PoliteHttpClient, src: dict[str, Any], since: datetime | None) -> Iterator[Item]:
    """Extraction method: validated sitemap URLs filtered by `url_pattern`, then JSON-LD of each page (no blind crawling)."""
    limit = int(src.get("max_pages", 50))
    for url, modified in discover_sitemap_urls(http, src["url"], since, pattern=src.get("url_pattern"))[:limit]:
        item = jsonld_item(url, http.get(url, respect_robots=True).text)
        if item:
            item["published"] = item["published"] or (modified.isoformat() if modified else None)
            yield item


def parse_page_metadata(html: str, url: str) -> Item | None:
    """Title and meta description only; page body text is never read. The requested URL stays the identity."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    og_title = soup.find("meta", attrs={"property": "og:title"})
    title = (h1.get_text(" ") if h1 else None) or (og_title.get("content") if og_title else None) or (
        soup.title.get_text(" ") if soup.title else None
    )
    description = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    return _item(url, title, description.get("content") if description else None, None)


def page_metadata_connector(http: PoliteHttpClient, src: dict[str, Any], since: datetime | None) -> Iterator[Item]:
    """Extraction method: an explicit URL allowlist (`url` + `urls`), optionally extended with URLs from a validated
    sitemap restricted to a path prefix (`sitemap: {url, prefix, max_pages}`). No links are followed."""
    targets: dict[str, datetime | None] = {src["url"]: None}
    targets.update({u: None for u in src.get("urls") or []})
    sitemap = src.get("sitemap")
    if sitemap:
        found = discover_sitemap_urls(http, sitemap["url"], since, prefix=sitemap.get("prefix"))
        for url, modified in found[: int(sitemap.get("max_pages", 10))]:
            targets.setdefault(url, modified)
        for url, modified in found:
            if url in targets:
                targets[url] = modified
    for url, modified in targets.items():
        item = parse_page_metadata(http.get(url, respect_robots=True).text, url)
        if item:
            item["extra"] = {"sitemap_lastmod": modified.isoformat()} if modified else {}
            yield item


def html_connector(http: PoliteHttpClient, src: dict[str, Any], since: datetime | None) -> Iterator[Item]:
    """Extraction method: CSS selectors from the source config applied to one listing page."""
    sel = src["selectors"]
    soup = BeautifulSoup(http.get(src["url"], respect_robots=True).text, "html.parser")
    for node in soup.select(sel["item"]):
        link = node.select_one(sel["link"]) if sel.get("link") else node
        title = node.select_one(sel["title"]) if sel.get("title") else link
        summary = node.select_one(sel["summary"]) if sel.get("summary") else None
        date = node.select_one(sel["date"]) if sel.get("date") else None
        if not link or not link.get("href") or not title:
            continue
        published = parse_datetime(date.get("datetime") or date.get_text(" ")) if date else None
        if since and published and published < since:
            continue
        item = _item(
            urljoin(src["url"], link["href"]),
            title.get_text(" "),
            summary.get_text(" ") if summary else None,
            published,
        )
        if item:
            yield item


CONNECTORS: dict[str, Connector] = {
    "rss": rss_connector,
    "sitemap": sitemap_connector,
    "jsonld": jsonld_connector,
    "html": html_connector,
    "page_metadata": page_metadata_connector,
}
