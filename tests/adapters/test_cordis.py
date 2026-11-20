"""CORDIS adapter: SPARQL requests, pagination, politeness, error handling, persistence and provenance."""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters import registry
from app.adapters.base import AdapterConfigError
from app.adapters.cordis import (
    DEFAULT_ENDPOINT,
    LICENSE,
    CordisAdapter,
    merge_project_rows,
    projects_page_query,
    teaser,
)
from app.config.settings import Settings, load_source_config
from app.database.models import Entity, IngestionRun, Relationship, Signal, Source, SourceRecord, SyncState
from app.domain import EntityType, SignalType, VerificationStatus
from app.http.client import PoliteHttpClient

FIXTURES = Path(__file__).parent.parent / "fixtures"
PAGE_ROWS = json.loads((FIXTURES / "cordis_projects.json").read_text(encoding="utf-8"))["results"]["bindings"]
DETAIL_ROWS = json.loads((FIXTURES / "cordis_details.json").read_text(encoding="utf-8"))["results"]["bindings"]
TODAY = datetime(2026, 11, 20, tzinfo=UTC)
SETTINGS = Settings(_env_file=None, contact_email="research@example.org")
PROJECT_1 = "http://data.europa.eu/s66/resource/projects/11111111-1111-4111-8111-111111111111"


def sparql_json(rows: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"head": {"vars": []}, "results": {"bindings": rows}},
                          headers={"content-type": "application/sparql-results+json"})


class Cordis:
    """Mock of cordis.europa.eu with a virtual clock; serves the fixtures with real LIMIT/OFFSET behavior."""

    def __init__(self, robots: str | None = "User-agent: *\nDisallow: /search\nDisallow: /data/\n",
                 fail: Exception | None = None, fail_robots: bool = False, status: int = 200, body: str | None = None):
        self.now = 0.0
        self.requests: list[tuple[float, str, dict]] = []
        self.queries: list[str] = []
        self.robots, self.fail, self.fail_robots, self.status, self.body = robots, fail, fail_robots, status, body

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((self.now, request.url.path, dict(request.headers)))
        if request.url.path == "/robots.txt":
            if self.fail_robots and self.fail is not None:
                raise self.fail
            return httpx.Response(200, text=self.robots) if self.robots is not None else httpx.Response(404)
        if self.fail is not None:
            raise self.fail
        if self.status != 200:
            return httpx.Response(self.status, text="error")
        if self.body is not None:
            return httpx.Response(200, text=self.body, headers={"content-type": "text/html"})
        query = parse_qs(request.url.query.decode())["query"][0]
        self.queries.append(query)
        if "VALUES ?p" in query:
            uris = set(re.findall(r"<(http://data\.europa\.eu/s66/resource/projects/[^>]+)>", query))
            return sparql_json([r for r in DETAIL_ROWS if r["p"]["value"] in uris])
        limit, offset = (int(x) for x in re.search(r"LIMIT (\d+) OFFSET (\d+)", query).groups())
        return sparql_json(PAGE_ROWS[offset: offset + limit])

    def client(self) -> PoliteHttpClient:
        def sleep(seconds: float) -> None:
            self.now += seconds

        return PoliteHttpClient(client=httpx.Client(transport=httpx.MockTransport(self.handler)), sleep=sleep,
                                monotonic=lambda: self.now, max_retries=0)

    def sparql_requests(self) -> list[tuple[float, str, dict]]:
        return [r for r in self.requests if r[1] != "/robots.txt"]


def make(site: Cordis | None = None, factory=None, dry_run: bool | None = None, limit: int | None = None, **overrides):
    site = site or Cordis()
    adapter = CordisAdapter(factory, http=site.client(), settings=SETTINGS, limit=limit,
                            config={**load_source_config("cordis"), **overrides},
                            dry_run=factory is None if dry_run is None else dry_run)
    return site, adapter


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.cordis.utcnow", lambda: TODAY)


# --- configuration and wiring ------------------------------------------------------------------------


def test_shipped_config_and_registry() -> None:
    cfg = load_source_config("cordis")
    assert cfg["endpoint"] == DEFAULT_ENDPOINT == "https://cordis.europa.eu/datalab/sparql-api"
    assert cfg["countries"] == ["DE"] and cfg["min_interval_seconds"] >= 10 and cfg["page_size"] <= 50
    assert registry.get_adapter_class("cordis") is CordisAdapter


@pytest.mark.parametrize("bad", [[], ["DEU"], ['DE"))} #'], ["d e"]])
def test_countries_must_be_iso_codes(bad: list[str]) -> None:
    with pytest.raises(AdapterConfigError, match="countries"):
        make(countries=bad)


def test_query_is_a_read_only_select_without_federation() -> None:
    query = projects_page_query(["DE"], date(2026, 1, 1), date(2026, 2, 1), 25, 50)
    assert query.count("SELECT") == 1 and "LIMIT 25 OFFSET 50" in query and 'IN ("DE")' in query
    for forbidden in ("SERVICE", "INSERT", "DELETE", "LOAD", "DROP"):
        assert forbidden not in query


def test_helpers() -> None:
    assert teaser(" a   b\n c ") == "a b c"
    assert len(teaser("x" * 5000)) == 1000 and teaser("x" * 5000).endswith("…")
    merged = merge_project_rows(DETAIL_ROWS)
    assert len(merged) == 3
    assert len(merged[PROJECT_1]["orgs"]) == 2  # duplicate rows of one organisation are folded


# --- fetch / normalize ---------------------------------------------------------------------------------


def test_fetch_and_normalize_with_provenance_and_licence() -> None:
    _, adapter = make()
    records = list(adapter.fetch())
    assert [r.external_id for r in records] == ["900000001", "900000002", "900000003"]
    first = records[0]
    assert first.canonical_url == "https://cordis.europa.eu/project/id/900000001"
    assert first.published_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert first.payload["license"] == LICENSE and first.payload["license"]["name"] == "CC BY 4.0"
    assert first.payload["license"]["attribution"] == "© European Union, CORDIS"
    assert first.payload["retrieved_from"] == DEFAULT_ENDPOINT
    assert first.payload["abstract"] == "Synthetic abstract for project one."
    assert [p["name"] for p in first.payload["participants"]] == ["BEISPIEL GMBH", "TESTUNIVERSITAET MUSTERSTADT"]

    bundle = adapter.normalize(first)
    adapter.validate(bundle)
    project = bundle.entities[0]
    assert project.entity_type is EntityType.RESEARCH_PROJECT and project.identifier == "project:900000001"
    assert project.properties["license"] == "CC BY 4.0" and project.properties["attribution"] == "© European Union, CORDIS"
    orgs = bundle.entities[1:]
    assert {o.entity_type for o in orgs} == {EntityType.ORGANIZATION}
    assert all(o.properties["organization_type"] == "organization" for o in orgs)
    by_name = {o.canonical_name: o for o in orgs}
    assert by_name["TESTUNIVERSITAET MUSTERSTADT"].properties["countries"] == ["DE"]
    assert by_name["TESTUNIVERSITAET MUSTERSTADT"].properties["website"] == "https://uni.example.org"
    assert "website" not in by_name["BEISPIEL GMBH"].properties
    assert {r.verification_status for r in bundle.relationships} == {VerificationStatus.SOURCE_ASSERTED}
    assert [s.signal_type for s in bundle.signals] == [SignalType.NEW_FUNDING_PROJECT]
    assert bundle.signals[0].event_date == datetime(2026, 9, 1, tzinfo=UTC)


def test_requests_are_polite_sparql_gets_without_credentials() -> None:
    site, adapter = make()
    list(adapter.fetch())
    assert site.sparql_requests() and all(path == "/datalab/sparql-api" for _, path, _ in site.sparql_requests())
    for _, _, headers in site.requests:
        assert "authorization" not in headers and "cookie" not in headers
    assert all(h["accept"] == "application/sparql-results+json" for _, _, h in site.sparql_requests())
    times = [t for t, _, _ in site.requests]
    assert all(b - a >= 10 for a, b in zip(times, times[1:]))  # robots.txt and SPARQL calls share the 10 s spacing
    assert not any("/data/" in path for _, path, _ in site.requests)


def test_pagination_requests_one_page_and_one_detail_query_each() -> None:
    site, adapter = make(page_size=2)
    assert len(list(adapter.fetch())) == 3
    page_queries = [q for q in site.queries if "VALUES" not in q]
    assert [re.search(r"OFFSET (\d+)", q).group(1) for q in page_queries] == ["0", "2"]
    assert len([q for q in site.queries if "VALUES" in q]) == 2


def test_limit_stops_the_stream() -> None:
    _, adapter = make(limit=1)
    assert adapter.run().records_fetched == 1


# --- errors -------------------------------------------------------------------------------------------


def test_robots_disallow_of_the_endpoint_fails_the_run_without_fallback() -> None:
    site, adapter = make(Cordis(robots="User-agent: *\nDisallow: /datalab/\n"))
    result = adapter.run()
    assert result.status == "failed" and "robots.txt" in (result.error_message or "")
    assert site.sparql_requests() == []


@pytest.mark.parametrize(
    "site",
    [
        Cordis(fail=httpx.ConnectError("unreachable")),
        Cordis(fail=httpx.ConnectError("unreachable"), fail_robots=True),
        Cordis(status=500),
        Cordis(status=403),
        Cordis(body="<html>maintenance</html>"),
    ],
    ids=["endpoint-unreachable", "robots-unreachable", "http-500", "http-403", "non-sparql-body"],
)
def test_unavailable_endpoint_fails_the_run_instead_of_reporting_an_empty_success(site: Cordis) -> None:
    result = make(site)[1].run()
    assert result.status == "failed" and result.exit_code == 1
    assert result.records_fetched == 0 and result.error_message


# --- persistence --------------------------------------------------------------------------------------


def counts(factory) -> dict[str, int]:
    with factory() as s:
        return {m.__name__: s.execute(select(func.count()).select_from(m)).scalar_one()
                for m in (Source, IngestionRun, SourceRecord, Entity, Relationship, Signal, SyncState)}


@pytest.mark.db
def test_runs_are_idempotent_and_keep_provenance_and_org_type(session_factory) -> None:
    first = make(factory=session_factory)[1].run()
    assert (first.status, first.records_created) == ("success", 3)
    snapshot = counts(session_factory)
    again = make(factory=session_factory)[1].run()
    assert (again.status, again.records_created, again.records_updated, again.records_unchanged) == ("success", 0, 0, 3)
    after = counts(session_factory)
    assert {k: v for k, v in after.items() if k != "IngestionRun"} == {k: v for k, v in snapshot.items() if k != "IngestionRun"}
    assert (snapshot["SourceRecord"], snapshot["Entity"], snapshot["Relationship"], snapshot["Signal"]) == (3, 6, 4, 3)

    with session_factory() as s:
        source = s.execute(select(Source)).scalar_one()
        assert source.source_name == "cordis" and source.terms_url == "https://cordis.europa.eu/about/legal"
        assert all(r.source_record_id is not None for r in s.execute(select(Relationship)).scalars())
        assert all(sig.source_record_id is not None for sig in s.execute(select(Signal)).scalars())
        record = s.execute(select(SourceRecord).where(SourceRecord.external_id == "900000001")).scalar_one()
        assert record.raw_payload["license"]["name"] == "CC BY 4.0" and record.canonical_url.endswith("/id/900000001")
        orgs = s.execute(select(Entity).where(Entity.entity_type == "organization")).scalars().all()
        assert len(orgs) == 3 and all(o.properties["organization_type"] == "organization" for o in orgs)
        projects = s.execute(select(Entity).where(Entity.entity_type == "research_project")).scalars().all()
        assert len(projects) == 3 and all(p.properties["license"] == "CC BY 4.0" for p in projects)
        cursor = s.execute(select(SyncState)).scalar_one()
        assert cursor.scope_key == "start_date" and cursor.cursor == {"from": "2026-08-02", "skip": 0}


@pytest.mark.db
def test_dry_run_changes_nothing(session_factory) -> None:
    before = counts(session_factory)
    result = make(factory=session_factory, dry_run=True)[1].run()
    assert (result.status, result.records_fetched, result.dry_run) == ("success", 3, True)
    assert counts(session_factory) == before == {k: 0 for k in before}


@pytest.mark.db
def test_failed_run_keeps_data_but_does_not_advance_the_cursor(session_factory) -> None:
    result = make(Cordis(status=500), factory=session_factory)[1].run()
    assert result.status == "failed"
    c = counts(session_factory)
    assert c["SyncState"] == 0 and c["SourceRecord"] == 0 and c["IngestionRun"] == 1
    with session_factory() as s:
        assert s.execute(select(IngestionRun.status)).scalar_one() == "failed"


@pytest.mark.db
def test_capped_run_resumes_at_the_same_start_date_with_an_offset(session_factory) -> None:
    capped = make(factory=session_factory, page_size=2, max_projects_per_run=2)[1].run()
    assert (capped.status, capped.records_fetched) == ("success", 2)
    with session_factory() as s:
        assert s.execute(select(SyncState.cursor)).scalar_one() == {"from": "2026-09-01", "skip": 2}
    site, resume = make(factory=session_factory, page_size=2, max_projects_per_run=2)
    done = resume.run()
    assert (done.status, done.records_fetched, done.records_created) == ("success", 1, 1)
    first_query = site.queries[0]
    assert "OFFSET 2" in first_query and '"2026-09-01"^^xsd:date' in first_query
    with session_factory() as s:
        assert s.execute(select(SyncState.cursor)).scalar_one() == {"from": "2026-08-02", "skip": 0}
