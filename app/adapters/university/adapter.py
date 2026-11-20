from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from app.adapters.base import AdapterConfigError, BaseAdapter
from app.adapters.university.connectors import CONNECTORS
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
KINDS = {
    "press_release": (EntityType.PUBLICATION, SignalType.NEW_PRESS_RELEASE),
    "news": (EntityType.PUBLICATION, SignalType.NEW_PRESS_RELEASE),
    "research_project": (EntityType.RESEARCH_PROJECT, SignalType.NEW_RESEARCH_PROJECT),
}


class UniversityAdapter(BaseAdapter):
    """Configurable collectors for selected German universities (see `universities` in sources.yaml)."""

    name = "university"
    source = SourceSpec(
        source_name="university",
        source_type=SourceType.RSS,
        base_url=None,
        description="Selected public news/project pages of German universities (RSS, sitemap+JSON-LD, JSON-LD or HTML selectors).",
        terms_url=None,
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, only: str | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else load_source_config("universities")
        self.sources: list[dict[str, Any]] = [
            s for s in (self.config.get("sources") or []) if s.get("enabled", True) and (only is None or s["key"] == only)
        ]
        if not self.sources:
            raise AdapterConfigError("no enabled university sources configured (sources.yaml -> universities.sources)")
        for src in self.sources:
            if src["connector"] not in CONNECTORS:
                raise AdapterConfigError(f"unknown connector {src['connector']!r} for {src['key']}")
            if src.get("kind", "press_release") not in KINDS:
                raise AdapterConfigError(f"unknown kind {src.get('kind')!r} for {src['key']}")

    def fetch(self) -> Iterator[RawRecord]:
        errors: dict[str, str] = {}
        for src in self.sources:
            try:
                yield from self._collect(src)
            except HttpFetchError as exc:
                # A blocked or broken source must not stop the other universities.
                log.warning("university source failed", extra={"source": src["key"], "error": str(exc)})
                errors[src["key"]] = str(exc)
        if errors:
            raise RuntimeError(f"university sources failed: {errors}")

    def _collect(self, src: dict[str, Any]) -> Iterator[RawRecord]:
        self.http.set_min_interval(urlparse(src["url"]).netloc, float(src.get("min_interval_seconds", 2)))
        scope = src["key"]
        cursor = self.get_cursor(scope)
        since = parse_datetime(cursor["from"]) if cursor and cursor.get("from") else None
        started = utcnow()
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
        entity_type, signal_type = KINDS[src.get("kind", "press_release")]
        published = parse_datetime(p.get("published"))
        uni = organization_draft(
            key="uni",
            identifier=f"university:{src['key']}",
            name=src["name"],
            is_university=True,
            aliases=[AliasDraft(alias=a, alias_type=AliasType.NAME) for a in src.get("aliases", [])],
            properties={"country": src.get("country"), "website": src.get("website")},
        )
        assert uni is not None
        item = EntityDraft(
            key="item",
            identifier=f"item:{raw.external_id}",
            entity_type=entity_type,
            canonical_name=p["title"],
            description=p.get("summary"),
            properties=compact(
                {
                    "url": p["url"],
                    "kind": src.get("kind", "press_release"),
                    "published": p.get("published"),
                    "tags": p.get("tags"),
                    "university": src["name"],
                    **(p.get("extra") or {}),
                }
            ),
            aliases=[AliasDraft(alias=p["url"], alias_type=AliasType.URL)],
            is_primary=True,
            extraction_method=f"university_{src['connector']}",
        )
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
