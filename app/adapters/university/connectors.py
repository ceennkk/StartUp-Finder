from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from urllib.parse import urldefrag, urljoin

import feedparser
from bs4 import BeautifulSoup

from app.http.client import PoliteHttpClient
from app.normalization.text import clean_text, strip_html
from app.utils.dates import parse_datetime

Item = dict[str, Any]
Connector = Callable[[PoliteHttpClient, dict[str, Any], datetime | None], Iterator[Item]]

_SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_JSONLD_ITEM_TYPES = {"Article", "NewsArticle", "BlogPosting", "Event", "ResearchProject", "Project", "Dataset", "WebPage"}


def _item(url: str, title: str | None, summary: str | None, published: Any, tags: list[str] | None = None) -> Item | None:
    url = urldefrag(url)[0].strip()
    title = clean_text(title)
    if not url or not title:
        return None
    return {
        "url": url,
        "title": title,
        "summary": clean_text(summary),
        "published": published.isoformat() if isinstance(published, datetime) else published,
        "tags": [t for t in (tags or []) if t],
    }


def rss_connector(http: PoliteHttpClient, src: dict[str, Any], since: datetime | None) -> Iterator[Item]:
    """Extraction method: RSS/Atom feed parsed with feedparser; the item link is the identity (feed GUIDs may embed timestamps)."""
    feed = feedparser.parse(http.get(src["url"], respect_robots=True).content)
    for entry in feed.entries:
        published = parse_datetime(entry.get("published") or entry.get("updated"))
        if since and published and published < since:
            continue
        item = _item(
            entry.get("link", ""),
            entry.get("title"),
            strip_html(entry.get("summary")),
            published,
            [t.get("term") for t in entry.get("tags", [])],
        )
        if item:
            yield item


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


def sitemap_connector(http: PoliteHttpClient, src: dict[str, Any], since: datetime | None) -> Iterator[Item]:
    """Extraction method: sitemap URLs filtered by `url_pattern`, then JSON-LD of each page (no blind crawling)."""
    pattern = re.compile(src.get("url_pattern", ".*"))
    limit = int(src.get("max_pages", 50))
    root = ET.fromstring(http.get(src["url"], respect_robots=True).content)
    fetched = 0
    for node in root.findall("s:url", _SITEMAP_NS):
        loc = node.find("s:loc", _SITEMAP_NS)
        lastmod = node.find("s:lastmod", _SITEMAP_NS)
        if loc is None or not loc.text or not pattern.search(loc.text):
            continue
        modified = parse_datetime(lastmod.text) if lastmod is not None else None
        if since and modified and modified < since:
            continue
        item = jsonld_item(loc.text.strip(), http.get(loc.text.strip(), respect_robots=True).text)
        if item:
            item["published"] = item["published"] or (modified.isoformat() if modified else None)
            yield item
        fetched += 1
        if fetched >= limit:
            return


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
}
