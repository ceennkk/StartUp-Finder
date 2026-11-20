from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from app.adapters.base import AdapterConfigError, BaseAdapter
from app.adapters.university.connectors import CONNECTORS, SitemapError
from app.adapters.university.plugins import get_plugin
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
from app.utils.dates import parse_datetime, utcnow

log = logging.getLogger(__name__)

# Source "kind" decides how items are modelled; nothing is classified automatically.
# organization_unit: pages describe one university unit (e.g. a founder centre); no per-page entities and no signal.
KINDS: dict[str, tuple[EntityType, SignalType | None]] = {
    "press_release": (EntityType.PUBLICATION, SignalType.NEW_PRESS_RELEASE),
    "news": (EntityType.PUBLICATION, SignalType.NEW_PRESS_RELEASE),
    "research_project": (EntityType.RESEARCH_PROJECT, SignalType.NEW_RESEARCH_PROJECT),
    "organization_unit": (EntityType.ORGANIZATION, None),
}

MIN_HTML_INTERVAL_SECONDS = 10.0  # applies to every connector except plain RSS/Atom feeds
DEFAULT_FEED_INTERVAL_SECONDS = 2.0
DEFAULT_INITIAL_DAYS = 30  # first run without watermark: do not ingest a feed's whole history


def request_interval(src: dict[str, Any]) -> float:
    if src["connector"] == "rss":
        return float(src.get("min_interval_seconds", DEFAULT_FEED_INTERVAL_SECONDS))
    return max(float(src.get("min_interval_seconds", MIN_HTML_INTERVAL_SECONDS)), MIN_HTML_INTERVAL_SECONDS)


class UniversityAdapter(BaseAdapter):
    """Configurable collectors for selected German universities (see `universities` in sources.yaml)."""

    name = "university"
    source = SourceSpec(
        source_name="university",
        source_type=SourceType.RSS,
        base_url=None,
        description="Selected public news/project pages of German universities (RSS, validated sitemap + JSON-LD, JSON-LD, page metadata or HTML selectors).",
        terms_url=None,
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, only: str | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else load_source_config("universities")
        all_sources: list[dict[str, Any]] = self.config.get("sources") or []
        if only is not None:
            selected = [s for s in all_sources if only in (s["key"], s.get("group"))]
            if not selected:
                known = ", ".join(sorted({s["key"] for s in all_sources}))
                raise AdapterConfigError(f"unknown university source {only!r}; configured: {known}")
            disabled = [s["key"] for s in selected if not s.get("enabled", True)]
            if disabled:
                raise AdapterConfigError(
                    f"university source(s) {', '.join(disabled)} disabled in sources.yaml (usage terms not clarified, see README)"
                )
            self.sources: list[dict[str, Any]] = selected
        else:
            self.sources = [s for s in all_sources if s.get("enabled", True)]
        if not self.sources:
            raise AdapterConfigError("no enabled university sources configured (sources.yaml -> universities.sources)")
        for src in self.sources:
            if src["connector"] not in CONNECTORS:
                raise AdapterConfigError(f"unknown connector {src['connector']!r} for {src['key']}")
            if src.get("kind", "press_release") not in KINDS:
                raise AdapterConfigError(f"unknown kind {src.get('kind')!r} for {src['key']}")
            if src.get("require_contact_email") and not self.settings.contact_email:
                raise AdapterConfigError(f"CONTACT_EMAIL must be set to collect {src['key']} (sent in the User-Agent)")
        # Intervals are per host; the most conservative setting of all sources on that host wins.
        hosts: dict[str, float] = {}
        for src in self.sources:
            for url in (src["url"], (src.get("sitemap") or {}).get("url")):
                if url:
                    host = urlparse(url).netloc
                    hosts[host] = max(hosts.get(host, 0.0), request_interval(src))
        for host, seconds in hosts.items():
            self.http.set_min_interval(host, seconds)

    def fetch(self) -> Iterator[RawRecord]:
        errors: dict[str, str] = {}
        for src in self.sources:
            try:
                yield from self._collect(src)
            except (HttpFetchError, SitemapError) as exc:
                # A blocked or broken source must not stop the other universities.
                log.warning("university source failed", extra={"source": src["key"], "error": str(exc)})
                errors[src["key"]] = str(exc)
        if errors:
            raise RuntimeError(f"university sources failed: {errors}")

    def _collect(self, src: dict[str, Any]) -> Iterator[RawRecord]:
        scope = src["key"]
        started = utcnow()
        cursor = self.get_cursor(scope)
        if cursor and cursor.get("from"):
            since = parse_datetime(cursor["from"])
        else:
            since = started - timedelta(days=int(src.get("initial_days", DEFAULT_INITIAL_DAYS)))
        plugin = get_plugin(src.get("plugin"))
        connector = plugin.connector or CONNECTORS[src["connector"]]
        for item in connector(self.http, src, since):
            item = plugin.enrich(item, src)
            yield RawRecord(
                external_id=f"{src['key']}:{item['url']}",
                record_type=src.get("kind", "press_release"),
                payload={"university_key": src["key"], "source_url": src["url"], **item},
                canonical_url=item["url"],
                published_at=parse_datetime(item.get("published")),
            )
        lookback = int(src.get("lookback_days", 7))
        self.set_cursor(scope, {"from": (started - timedelta(days=lookback)).isoformat()})

    # --- normalization ----------------------------------------------------

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        p = raw.payload
        src = next(s for s in self.sources if s["key"] == p["university_key"])
        kind = src.get("kind", "press_release")
        entity_type, signal_type = KINDS[kind]
        published = parse_datetime(p.get("published"))
        uni = organization_draft(
            key="uni",
            identifier=f"university:{src.get('group', src['key'])}",
            name=src["name"],
            is_university=True,
            aliases=[AliasDraft(alias=a, alias_type=AliasType.NAME) for a in src.get("aliases", [])],
            properties={"country": src.get("country"), "website": src.get("website")},
        )
        assert uni is not None
        if kind == "organization_unit":
            return self._normalize_unit(raw, src, uni)
        item = EntityDraft(
            key="item",
            identifier=f"item:{raw.external_id}",
            entity_type=entity_type,
            canonical_name=p["title"],
            description=p.get("summary"),
            properties=compact(
                {
                    "url": p["url"],
                    "kind": kind,
                    "published": p.get("published"),
                    "tags": p.get("tags"),
                    "university": src["name"],
                    **(src.get("properties") or {}),
                    **(p.get("extra") or {}),
                }
            ),
            aliases=[AliasDraft(alias=p["url"], alias_type=AliasType.URL)],
            is_primary=True,
            extraction_method=f"university_{src['connector']}",
        )
        assert signal_type is not None
        return NormalizedBundle(
            entities=[item, uni],
            relationships=[RelationshipDraft(source_key="item", target_key="uni", relationship_type=RelationshipType.PUBLISHED_BY)],
            signals=[
                SignalDraft(
                    entity_key="item",
                    signal_type=signal_type,
                    description=p["title"],
                    event_date=None,
                    published_at=published,
                )
            ],
        )

    def _normalize_unit(self, raw: RawRecord, src: dict[str, Any], uni: EntityDraft) -> NormalizedBundle:
        """One organization entity per configured unit; every fetched page is provenance, only the home page updates it."""
        p = raw.payload
        def base(url: str) -> str:
            return re.sub(r"/index\.(php|html?)$", "", url.rstrip("/"))

        is_home = base(p["url"]) == base(src["url"])
        unit = organization_draft(
            key="unit",
            identifier=f"unit:{src['key']}",
            name=src.get("unit_name") or src["name"],
            description=p.get("summary") if is_home else None,
            aliases=[AliasDraft(alias=a, alias_type=AliasType.NAME) for a in src.get("unit_aliases", [])],
            properties={"website": src["url"], "unit_of": src["name"], **(src.get("properties") or {})},
            is_primary=is_home,
        )
        assert unit is not None
        return NormalizedBundle(
            entities=[unit, uni],
            relationships=[
                RelationshipDraft(
                    source_key="unit",
                    target_key="uni",
                    relationship_type=RelationshipType.MEMBER_OF,
                    properties={"basis": "configured organisational unit of the university"},
                )
            ],
        )
