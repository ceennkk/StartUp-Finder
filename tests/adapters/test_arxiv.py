from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.arxiv import ArxivAdapter, parse_entry, NS
from app.config.settings import Settings
from app.database.models import Entity, Relationship, SourceRecord, SourceRecordRevision, SyncState
from tests.helpers import fast_http
import xml.etree.ElementTree as ET

FEED = (Path(__file__).parent.parent / "fixtures" / "arxiv_feed.xml").read_text(encoding="utf-8")
EMPTY = FEED.split("<entry>")[0] + "</feed>"
CONFIG = {"categories": ["cs.RO", "quant-ph"], "page_size": 2, "default_start_days_back": 3,
          "lookback_days": 1, "max_results_per_run": 1000}


def feed(total: int, with_entries: bool = True) -> httpx.Response:
    body = FEED if with_entries else EMPTY
    return httpx.Response(200, content=body.replace("{total}", str(total)).encode())


def adapter(handler, factory=None, config=None, **kw) -> ArxivAdapter:
    kw.setdefault("dry_run", factory is None)
    return ArxivAdapter(factory, http=fast_http(handler), settings=Settings(_env_file=None),
                        config=config or CONFIG, **kw)


def test_parse_entry_extracts_all_metadata() -> None:
    entry = ET.fromstring(FEED.replace("{total}", "2")).findall("a:entry", NS)[0]
    p = parse_entry(entry)
    assert p["arxiv_id"] == "2611.00001" and p["version"] == 2
    assert p["title"] == "Learning Robot Policies"
    assert p["summary"] == "We study robot learning. Results are good."
    assert p["categories"] == ["cs.RO", "cs.LG"] and p["primary_category"] == "cs.RO"
    assert p["doi"] == "10.1000/XYZ.123" and p["comment"] == "12 pages, 3 figures"
    assert p["pdf_url"] == "http://arxiv.org/pdf/2611.00001v2" and p["abs_url"].endswith("2611.00001v2")
    assert p["authors"][0] == {"name": "Ann Example", "affiliations": ["TU Munich"]}
    assert p["authors"][1]["affiliations"] == []


def test_old_style_identifiers_are_supported() -> None:
    entry = ET.fromstring(FEED.replace("{total}", "2")).findall("a:entry", NS)[1]
    assert parse_entry(entry)["arxiv_id"] == "quant-ph/0611002" 


def test_fetch_query_paging_and_spacing() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return feed(2) if request.url.params["start"] == "0" else feed(2, with_entries=False)

    a = adapter(handler)
    records = list(a.fetch())
    assert [r.external_id for r in records] == ["2611.00001", "quant-ph/0611002"]
    q = requests[0].url.params["search_query"]
    assert q.startswith("(cat:cs.RO OR cat:quant-ph) AND submittedDate:[") and " TO " in q
    assert requests[0].url.params["sortOrder"] == "ascending"
    assert len(requests) == 1  # offset reached totalResults
    assert a._pending_cursors["submitted"]["from"]


def test_multiple_pages_are_followed() -> None:
    starts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        starts.append(request.url.params["start"])
        return feed(4) if request.url.params["start"] == "0" else feed(4)

    config = {**CONFIG, "page_size": 2}
    assert len(list(adapter(handler, config=config).fetch())) == 4 and starts == ["0", "2"]


def test_capped_run_keeps_watermark_at_last_seen_entry() -> None:
    config = {**CONFIG, "max_results_per_run": 2, "page_size": 2}
    a = adapter(lambda r: feed(500), config=config)
    list(a.fetch())
    assert a._pending_cursors["submitted"]["from"] == "2026-11-18T12:00"


def test_api_error_entry_fails_the_run() -> None:
    body = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#x</id>'
            "<summary>bad query</summary></entry></feed>")
    result = adapter(lambda r: httpx.Response(200, content=body.encode()), dry_run=True).run()
    assert result.status == "failed" and "bad query" in (result.error_message or "")


def test_normalize_authors_are_not_merged_and_affiliations_only_when_given() -> None:
    a = adapter(lambda r: feed(2))
    raw = list(a.fetch())[0]
    bundle = a.normalize(raw)
    a.validate(bundle)
    persons = [e for e in bundle.entities if e.entity_type.value == "person"]
    assert [p.identifier for p in persons] == ["author:2611.00001:0", "author:2611.00001:1"]
    orgs = [e for e in bundle.entities if e.entity_type.value == "organization"]
    assert [o.canonical_name for o in orgs] == ["TU Munich"]
    assert sorted(r.relationship_type.value for r in bundle.relationships) == ["AUTHORED", "AUTHORED", "MEMBER_OF"]
    paper = bundle.entities[0]
    assert paper.properties["doi"] == "10.1000/xyz.123" and paper.properties["pdf_url"].endswith("v2")
    assert bundle.signals[0].published_at.isoformat().startswith("2026-11-18T09:30")


@pytest.mark.db
def test_run_is_idempotent_and_new_version_creates_revision(session_factory) -> None:
    handler = lambda r: feed(2) if r.url.params["start"] == "0" else feed(2, with_entries=False)
    assert adapter(handler, session_factory).run().records_created == 2
    again = adapter(handler, session_factory).run()
    assert (again.records_created, again.records_unchanged) == (0, 2)

    newer = lambda r: httpx.Response(200, content=FEED.replace("{total}", "2").replace("v2", "v3").encode())
    third = adapter(newer, session_factory).run()
    assert third.records_updated == 1
    with session_factory() as s:
        count = lambda m: s.execute(select(func.count()).select_from(m)).scalar_one()
        assert count(SourceRecord) == 2 and count(SourceRecordRevision) == 1
        # Ann appears on two papers but stays two separate person entities (no automatic merging).
        assert s.execute(select(func.count()).select_from(Entity).where(Entity.canonical_name == "Ann Example")).scalar_one() == 2
        assert count(Relationship) == 4
        assert count(SyncState) == 1
