from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.base import BaseAdapter
from app.domain import EntityType, RelationshipType, SignalType, SourceType
from app.http.client import PoliteHttpClient
from app.ingestion.types import (
    EntityDraft,
    NormalizedBundle,
    ObservationDraft,
    RawRecord,
    RelationshipDraft,
    SignalDraft,
    SourceSpec,
)


def fast_http(handler: Any = None) -> PoliteHttpClient:
    transport = httpx.MockTransport(handler) if handler else None
    client = httpx.Client(transport=transport) if transport else None
    return PoliteHttpClient(client=client, sleep=lambda _s: None, max_retries=2)


class FakeAdapter(BaseAdapter):
    name = "fake"
    source = SourceSpec(source_name="fake", source_type=SourceType.API, base_url="https://example.test")

    def __init__(self, factory: Any, items: list[dict[str, Any]], **kwargs: Any):
        super().__init__(factory, http=fast_http(), **kwargs)
        self.items = items
        self.fail_ids: set[str] = set()
        self.explode_after: int | None = None

    def fetch(self) -> Iterator[RawRecord]:
        for index, item in enumerate(self.items):
            if self.explode_after is not None and index >= self.explode_after:
                raise RuntimeError("source went away")
            yield RawRecord(
                external_id=item["id"],
                record_type="repo",
                payload=item,
                canonical_url=f"https://example.test/{item['id']}",
                volatile_keys=frozenset({"stars"}),
            )
        self.set_cursor("main", {"last": self.items[-1]["id"] if self.items else None})

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        if raw.external_id in self.fail_ids:
            raise ValueError("cannot normalize")
        p = raw.payload
        return NormalizedBundle(
            entities=[
                EntityDraft(
                    key="repo",
                    identifier=f"repo:{p['id']}",
                    entity_type=EntityType.REPOSITORY,
                    canonical_name=p["name"],
                    is_primary=True,
                ),
                EntityDraft(
                    key="owner",
                    identifier=f"user:{p['owner']}",
                    entity_type=EntityType.PERSON,
                    canonical_name=p["owner"],
                ),
            ],
            relationships=[
                RelationshipDraft(source_key="owner", target_key="repo", relationship_type=RelationshipType.DEVELOPED)
            ],
            signals=[SignalDraft(entity_key="repo", signal_type=SignalType.NEW_REPOSITORY)],
            observations=[ObservationDraft(entity_key="repo", metric_name="stars", value=Decimal(p["stars"]))],
        )
