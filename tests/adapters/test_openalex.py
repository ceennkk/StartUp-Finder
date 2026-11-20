from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.openalex import OpenAlexAdapter
from app.config.settings import Settings
from app.database.models import Entity, Observation, Relationship, Signal, SourceRecord
from app.utils.dates import utcnow
from tests.helpers import fast_http

WORK = json.loads((Path(__file__).parent.parent / "fixtures" / "openalex_work.json").read_text(encoding="utf-8"))
CONFIG = {
    "countries": ["DE"],
    "per_page": 2,
    "default_start_days_back": 30,
    "lookback_days": 7,
    "topics": {"quantum": ["quantum computing", "quantum sensing"]},
}


def adapter(handler, factory=None, *, key: str | None = "test-key", config=None, **kw) -> OpenAlexAdapter:
    kw.setdefault("dry_run", factory is None)
    return OpenAlexAdapter(
        factory,
        http=fast_http(handler),
        settings=Settings(_env_file=None, openalex_api_key=key),
        config=config or CONFIG,
        **kw,
    )


def other_work(n: int) -> dict:
    return {**WORK, "id": f"https://openalex.org/W{n}", "doi": None}


def test_normalize_maps_work_authors_and_institutions() -> None:
    a = adapter(lambda r: httpx.Response(200, json={}), dry_run=True)
    raw = a._to_record(WORK)
    bundle = a.normalize(raw)
    a.validate(bundle)

    by_type: dict[str, list] = {}
    for e in bundle.entities:
        by_type.setdefault(e.entity_type.value, []).append(e)
    pub = by_type["publication"][0]
    assert pub.canonical_name == "Fraxonium: Fractional fluxon states for qudit encoding"
    assert pub.description == "We encode qudits in qudits fluxonium."
    assert pub.properties["doi"] == "10.1088/2058-9565/aec477"
    assert pub.properties["reference_count"] == 2
    assert {x.canonical_name for x in by_type["person"]} == {"Luca Chirolli", "Uri Vool"}  # id-less author skipped
    assert {x.entity_type.value for x in bundle.entities if x.key.startswith("inst:")} == {"university", "organization"}
    orcids = [al for p in by_type["person"] for al in p.aliases if al.alias_type.value == "orcid"]
    assert [o.external_identifier for o in orcids] == ["https://orcid.org/0000-0002-8439-9949"]
    kinds = sorted(r.relationship_type.value for r in bundle.relationships)
    assert kinds == ["AUTHORED", "AUTHORED", "MEMBER_OF", "MEMBER_OF"]
    assert bundle.signals[0].signal_type.value == "NEW_PUBLICATION"
    assert bundle.signals[0].published_at.isoformat().startswith("2026-11-19")
    assert [(o.metric_name, int(o.value)) for o in bundle.observations] == [("citation_count", 3)]


def test_fetch_uses_cursor_paging_with_key_and_bearer_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params["cursor"] == "*":
            return httpx.Response(200, json={"meta": {"next_cursor": "c2"}, "results": [other_work(1), other_work(2)]})
        return httpx.Response(200, json={"meta": {"next_cursor": None}, "results": [other_work(3)]})

    records = list(adapter(handler).fetch())
    assert [r.external_id for r in records] == ["W1", "W2", "W3"]
    assert all(r.headers["Authorization"] == "Bearer test-key" for r in seen)
    flt = seen[0].url.params["filter"]
    assert 'title_and_abstract.search:("quantum computing" OR "quantum sensing")' in flt
    assert "institutions.country_code:DE" in flt
    assert f"from_publication_date:{(utcnow().date() - timedelta(days=30)).isoformat()}" in flt
    assert "api_key" not in str(seen[0].url)


def test_fetch_without_key_uses_basic_paging_and_stops_on_short_page() -> None:
    pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pages.append(request.url.params["page"])
        results = [other_work(1), other_work(2)] if request.url.params["page"] == "1" else [other_work(3)]
        return httpx.Response(200, json={"meta": {}, "results": results})

    records = list(adapter(handler, key=None).fetch())
    assert pages == ["1", "2"] and len(records) == 3


def test_works_matching_several_topics_are_fetched_once() -> None:
    config = {**CONFIG, "topics": {"a": ["x"], "b": ["y"]}}
    handler = lambda r: httpx.Response(200, json={"meta": {"next_cursor": None}, "results": [other_work(1)]})
    assert len(list(adapter(handler, config=config).fetch())) == 1


@pytest.mark.db
def test_run_is_idempotent_and_advances_watermark(session_factory) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"meta": {"next_cursor": None}, "results": [WORK]})

    first = adapter(handler, session_factory).run()
    assert (first.status, first.records_created) == ("success", 1)
    second = adapter(handler, session_factory).run()
    assert (second.status, second.records_created, second.records_unchanged) == ("success", 0, 1)

    expected_from = (utcnow().date() - timedelta(days=7)).isoformat()
    assert f"from_publication_date:{expected_from}" in requests[1].url.params["filter"]

    with session_factory() as s:
        counts = {
            m.__name__: s.execute(select(func.count()).select_from(m)).scalar_one()
            for m in (SourceRecord, Entity, Relationship, Signal, Observation)
        }
    assert counts == {"SourceRecord": 1, "Entity": 5, "Relationship": 4, "Signal": 1, "Observation": 1}


@pytest.mark.db
def test_citation_change_is_not_a_new_raw_revision(session_factory) -> None:
    payloads = [WORK, {**WORK, "cited_by_count": 40, "updated_date": "2026-11-21T00:00:00"}]
    calls = iter(payloads)
    handler = lambda r: httpx.Response(200, json={"meta": {"next_cursor": None}, "results": [next(calls)]})
    adapter(handler, session_factory).run()
    second = adapter(handler, session_factory).run()
    assert second.records_updated == 0
    with session_factory() as s:
        assert int(s.execute(select(Observation.metric_value)).scalar_one()) == 40


def test_exhausted_daily_budget_fails_fast_without_retries() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "40000"}, json={"reason": "daily_budget"})

    result = adapter(handler, dry_run=True).run()
    assert result.status == "failed" and len(calls) == 1
    assert "429" in (result.error_message or "")
