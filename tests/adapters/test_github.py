from __future__ import annotations

import base64
import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.base import AdapterConfigError
from app.adapters.github import GitHubAdapter
from app.config.settings import Settings
from app.database.models import Observation, SourceRecord, SourceRecordRevision, Signal, Relationship, Entity
from app.utils.dates import utcnow
from tests.helpers import fast_http

CONFIG = {
    "default_start_days_back": 7,
    "window_days": 7,
    "min_stars": 3,
    "max_repositories_per_query": 50,
    "refresh_known_limit": 5,
    "activity_items": 5,
    "queries": [{"name": "ai", "q": "topic:machine-learning"}],
}


def make_repo(repo_id: int = 1, *, stars: int = 10, owner_type: str = "Organization") -> dict[str, Any]:
    return {
        "id": repo_id,
        "name": f"proj{repo_id}",
        "full_name": f"acme/proj{repo_id}",
        "html_url": f"https://github.com/acme/proj{repo_id}",
        "description": "  Neural   nets for\nrobots ",
        "created_at": "2026-11-15T10:00:00Z",
        "pushed_at": "2026-11-19T10:00:00Z",
        "updated_at": "2026-11-19T10:00:00Z",
        "language": "Python",
        "topics": ["machine-learning", "robotics"],
        "stargazers_count": stars,
        "forks_count": 2,
        "open_issues_count": 4,
        "subscribers_count": 1,
        "default_branch": "main",
        "license": {"spdx_id": "MIT"},
        "visibility": "public",
        "archived": False,
        "fork": False,
        "homepage": "",
        "owner": {"id": 77, "login": "acme", "type": owner_type, "html_url": "https://github.com/acme",
                  "avatar_url": "https://avatars.test/77"},
    }


class FakeGitHub:
    def __init__(self, repos: list[dict[str, Any]]):
        self.repos = {r["id"]: r for r in repos}
        self.calls: list[httpx.Request] = []
        self.search_total: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        params = request.url.params
        if path == "/search/repositories":
            items = list(self.repos.values())
            total = self.search_total if self.search_total is not None else len(items)
            return httpx.Response(200, json={"total_count": total, "items": items if params["page"] == "1" else []})
        if path.startswith("/repositories/"):
            repo = self.repos[int(path.rsplit("/", 1)[1])]
            etag = f'W/"{repo["id"]}-{hash(json.dumps(repo, sort_keys=True)) & 0xFFFFFF}"'
            if request.headers.get("If-None-Match") == etag:
                return httpx.Response(304, headers={"ETag": etag})
            return httpx.Response(200, json=repo, headers={"ETag": etag})
        if path.endswith("/readme"):
            return httpx.Response(200, json={"sha": "r1", "path": "README.md",
                                             "content": base64.b64encode(b"# Hello\nrobots").decode()})
        if path.endswith("/contributors"):
            people = [
                {"id": 1, "login": "ann", "type": "User", "html_url": "https://github.com/ann",
                 "avatar_url": "https://avatars.test/1", "contributions": 30},
                {"id": 2, "login": "dependabot[bot]", "type": "Bot", "contributions": 5},
            ]
            if params.get("per_page") == "1":
                return httpx.Response(200, json=people[:1], headers={"Link": '<https://x/contributors?per_page=1&page=2>; rel="next", <https://x/contributors?per_page=1&page=2>; rel="last"'})
            return httpx.Response(200, json=people)
        if path.endswith("/commits"):
            commit = {"sha": "abc", "author": {"id": 1, "login": "ann", "type": "User"}, "committer": None,
                      "commit": {"author": {"name": "Ann Secret", "email": "ann@private.example", "date": "2026-11-18T09:00:00Z"},
                                 "committer": {"name": "Ann Secret", "email": "ann@private.example", "date": "2026-11-18T09:00:00Z"},
                                 "message": "Fix bug\n\nlong body"}}
            if params.get("per_page") == "1":
                return httpx.Response(200, json=[commit], headers={"Link": '<https://x/c?page=42>; rel="last"'})
            return httpx.Response(200, json=[commit])
        if path.endswith("/issues"):
            return httpx.Response(200, json=[
                {"number": 1, "title": "Bug", "state": "open", "created_at": "2026-11-16T00:00:00Z", "user": {"id": 5, "login": "bob", "type": "User"}},
                {"number": 2, "title": "A PR", "state": "open", "pull_request": {}, "user": {"id": 5, "login": "bob", "type": "User"}},
            ])
        if path.endswith("/pulls"):
            if params.get("per_page") == "1":
                return httpx.Response(200, json=[{"number": 2}], headers={"Link": '<https://x/p?page=7>; rel="last"'})
            return httpx.Response(200, json=[{"number": 2, "title": "A PR", "state": "open", "created_at": "2026-11-17T00:00:00Z", "user": {"id": 5, "login": "bob", "type": "User"}}])
        return httpx.Response(404, json={"message": "Not Found"})


def adapter(handler, factory=None, *, token: str | None = "tok", config=None, **kw) -> GitHubAdapter:
    kw.setdefault("dry_run", factory is None)
    return GitHubAdapter(
        factory,
        http=fast_http(handler),
        settings=Settings(_env_file=None, github_token=token),
        config=config or CONFIG,
        **kw,
    )


def test_missing_token_is_a_config_error() -> None:
    with pytest.raises(AdapterConfigError):
        adapter(lambda r: httpx.Response(200), token=None)


def test_fetch_builds_record_with_activity_and_no_personal_emails() -> None:
    api = FakeGitHub([make_repo()])
    records = list(adapter(api).fetch())
    assert len(records) == 1
    payload = records[0].payload
    assert records[0].external_id == "1" and records[0].record_type == "repository"
    assert payload["totals"] == {"contributors": 2, "commits": 42, "pull_requests": 7}
    assert [i["number"] for i in payload["recent_issues"]] == [1]  # PRs are excluded from issues
    assert payload["readme"]["text"].startswith("# Hello")
    blob = json.dumps(payload)
    assert "ann@private.example" not in blob and "Ann Secret" not in blob
    first = api.calls[0]
    assert first.headers["Authorization"] == "Bearer tok"
    assert first.headers["X-GitHub-Api-Version"] == "2022-11-28"
    q = first.url.params["q"]
    assert "topic:machine-learning " in q and "stars:>=3" in q and "created:" in q


def test_normalize_repository_owner_contributors_and_observations() -> None:
    api = FakeGitHub([make_repo()])
    a = adapter(api)
    bundle = a.normalize(next(iter(a.fetch())))
    a.validate(bundle)
    names = {e.key: (e.entity_type.value, e.canonical_name) for e in bundle.entities}
    assert names["repo"] == ("repository", "acme/proj1")
    assert names["org:77"] == ("organization", "acme")
    assert names["user:1"] == ("person", "ann")
    assert "user:2" not in names  # bots are not people
    rels = sorted((r.relationship_type.value, r.source_key, r.target_key) for r in bundle.relationships)
    assert rels == [("CONTRIBUTED_TO", "user:1", "repo"), ("OWNED_BY", "repo", "org:77")]
    metrics = {o.metric_name: int(o.value) for o in bundle.observations}
    assert metrics == {"stars": 10, "forks": 2, "open_issues_and_prs": 4, "subscribers": 1,
                       "contributors": 2, "commits": 42, "pull_requests": 7}
    types = sorted(s.signal_type.value for s in bundle.signals)
    assert types == ["NEW_CONTRIBUTOR", "NEW_REPOSITORY"]
    repo_signal = next(s for s in bundle.signals if s.signal_type.value == "NEW_REPOSITORY")
    assert repo_signal.event_date.isoformat().startswith("2026-11-15")
    assert bundle.entities[0].description == "Neural nets for robots"


def test_large_search_window_is_split() -> None:
    api = FakeGitHub([make_repo()])
    api.search_total = 2500
    list(adapter(api).fetch())
    searches = [c for c in api.calls if c.url.path == "/search/repositories"]
    assert len(searches) > 2  # the wide window was split into narrower ones


def test_secondary_rate_limit_is_waited_out_then_retried() -> None:
    state = {"n": 0}
    inner = FakeGitHub([make_repo()])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories" and state["n"] == 0:
            state["n"] += 1
            return httpx.Response(403, headers={"Retry-After": "3"}, json={"message": "secondary rate limit"})
        return inner(request)

    assert len(list(adapter(handler).fetch())) == 1 and state["n"] == 1


def test_exhausted_primary_limit_aborts_run_with_clear_error() -> None:
    reset = str(int(utcnow().timestamp()) + 3000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset}, json={"message": "API rate limit exceeded"})

    result = adapter(handler, dry_run=True).run()
    assert result.status == "failed" and "rate limit" in (result.error_message or "").lower()


@pytest.mark.db
def test_run_is_idempotent_and_tracks_changes_over_time(session_factory) -> None:
    api = FakeGitHub([make_repo(stars=10)])
    first = adapter(api, session_factory).run()
    assert (first.status, first.records_created, first.records_failed) == ("success", 1, 0)

    second = adapter(api, session_factory).run()
    assert (second.status, second.records_created, second.records_unchanged) == ("success", 0, 1)
    detail_calls = [c for c in api.calls if c.url.path == "/repositories/1"]
    assert detail_calls[0].headers.get("If-None-Match") is None
    assert detail_calls[-1].headers["If-None-Match"].startswith('W/"1-')  # conditional request

    api.repos[1]["stargazers_count"] = 25
    third = adapter(api, session_factory).run()
    assert third.status == "success"

    with session_factory() as s:
        count = lambda m: s.execute(select(func.count()).select_from(m)).scalar_one()
        assert count(SourceRecord) == 1 and count(SourceRecordRevision) == 0
        assert count(Entity) == 3 and count(Relationship) == 2 and count(Signal) == 2
        stars = s.execute(select(Observation.metric_value).where(Observation.metric_name == "stars")).scalar_one()
        assert int(stars) == 25  # same-day bucket is updated in place


@pytest.mark.db
def test_description_change_creates_revision(session_factory) -> None:
    api = FakeGitHub([make_repo()])
    adapter(api, session_factory).run()
    api.repos[1]["description"] = "New positioning"
    adapter(api, session_factory).run()
    with session_factory() as s:
        rev = s.execute(select(SourceRecordRevision)).scalar_one()
        assert rev.raw_payload["repository"]["description"].startswith("  Neural")
        entity = s.execute(select(Entity).where(Entity.entity_type == "repository")).scalar_one()
        assert entity.description == "New positioning"


@pytest.mark.db
def test_known_repositories_are_refreshed_even_when_not_in_search(session_factory) -> None:
    api = FakeGitHub([make_repo()])
    adapter(api, session_factory).run()
    api.repos[1]["stargazers_count"] = 40
    config = {**CONFIG, "queries": []}  # nothing discovered by search anymore
    result = adapter(api, session_factory, config=config).run()
    assert result.records_fetched == 1
    with session_factory() as s:
        stars = s.execute(select(Observation.metric_value).where(Observation.metric_name == "stars")).scalar_one()
        assert int(stars) == 40
