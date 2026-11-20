from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.huggingface import HuggingFaceAdapter
from app.config.settings import Settings
from app.database.models import Entity, Observation, Relationship, SourceRecord, SourceRecordRevision
from app.utils.dates import utcnow
from tests.helpers import fast_http

NOW = utcnow()
CONFIG = {
    "kinds": ["models"],
    "models": {"filters": ["de"], "search": []},
    "page_size": 2,
    "max_items_per_query": 10,
    "default_start_days_back": 7,
    "max_namespace_lookups": 10,
    "fetch_cards": True,
}


def iso(days_ago: float) -> str:
    return (NOW - __import__("datetime").timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def model(name: str, days_ago: float, downloads: int = 10) -> dict:
    return {"id": name, "author": name.split("/")[0], "createdAt": iso(days_ago), "lastModified": iso(days_ago),
            "downloads": downloads, "likes": 3, "tags": ["de", "text-generation"], "pipeline_tag": "text-generation",
            "library_name": "transformers", "cardData": {"license": "apache-2.0"}}


class FakeHub:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.models = [model("acme/one", 0.5), model("acme/two", 1), model("bob/three", 2), model("acme/old", 30)]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/api/models":
            page = int(request.url.params.get("cursor", "0"))
            chunk = self.models[page * 2:(page + 1) * 2]
            headers = {}
            if (page + 1) * 2 < len(self.models):
                headers["Link"] = f'<https://huggingface.co/api/models?cursor={page + 1}&limit=2>; rel="next"'
            return httpx.Response(200, json=chunk, headers=headers)
        if path == "/api/organizations/acme/overview":
            return httpx.Response(200, json={"name": "acme", "fullname": "Acme AI", "details": "We build models.",
                                             "numFollowers": 12, "isVerified": False})
        if path == "/api/organizations/acme/members":
            return httpx.Response(200, json=[{"user": "alice", "fullname": "Alice Realname", "type": "user", "avatarUrl": "https://a/1"}])
        if path.startswith("/api/organizations/"):
            return httpx.Response(404, json={"error": "Organization not found"})
        if path.endswith("/raw/main/README.md"):
            return httpx.Response(200, text="# Model card\nGerman LLM") if "acme/one" in path else httpx.Response(404)
        return httpx.Response(404)


def adapter(handler, factory=None, config=None, **kw) -> HuggingFaceAdapter:
    kw.setdefault("dry_run", factory is None)
    return HuggingFaceAdapter(factory, http=fast_http(handler), settings=Settings(_env_file=None),
                              config=config or CONFIG, **kw)


def test_fetch_follows_link_header_and_stops_at_watermark() -> None:
    hub = FakeHub()
    records = list(adapter(hub).fetch())
    kinds = [(r.record_type, r.external_id) for r in records]
    assert ("model", "model:acme/one") in kinds and ("model", "model:bob/three") in kinds
    assert ("model", "model:acme/old") not in kinds  # older than 7 days
    assert ("organization", "organization:acme") in kinds
    assert not any(k[1] == "organization:bob" for k in kinds)  # bob is a user, not an org
    first = next(c for c in hub.calls if c.url.path == "/api/models")
    assert first.url.params["filter"] == "de" and first.url.params["sort"] == "createdAt"
    assert first.url.params["direction"] == "-1" and first.url.params["full"] == "true"


def test_org_record_precedes_its_models_and_drops_real_names() -> None:
    records = list(adapter(FakeHub()).fetch())
    ids = [r.external_id for r in records]
    assert ids.index("organization:acme") < ids.index("model:acme/one")
    org = next(r for r in records if r.record_type == "organization")
    assert org.payload["members"] == [{"name": "alice", "type": "user", "avatar_url": "https://a/1"}]
    assert "Alice Realname" not in str(org.payload)


def test_normalize_model_with_org_user_and_card() -> None:
    a = adapter(FakeHub())
    by_id = {r.external_id: a.normalize(r) for r in a.fetch()}
    one = by_id["model:acme/one"]
    types = {e.key: e.entity_type.value for e in one.entities}
    assert types == {"item": "model", "ns": "organization"}
    assert one.entities[0].properties["pipeline_tag"] == "text-generation"
    assert one.entities[0].properties["license"] == "apache-2.0"
    assert "Model card" in one.entities[0].properties["model_card_excerpt"]
    assert sorted(o.metric_name for o in one.observations) == ["downloads", "likes"]
    assert one.signals[0].signal_type.value == "NEW_MODEL" and one.signals[0].event_date is not None
    three = by_id["model:bob/three"]
    assert {e.key: e.entity_type.value for e in three.entities}["ns"] == "person"
    org = by_id["organization:acme"]
    assert [r.relationship_type.value for r in org.relationships] == ["MEMBER_OF"]
    assert {o.metric_name: int(o.value) for o in org.observations} == {"public_members": 1, "followers": 12}


def test_missing_created_at_stays_null() -> None:
    item = {"id": "acme/x", "author": "acme", "downloads": 1}
    a = adapter(FakeHub())
    raw = a._record("models", "model", item, "acme/x", None)
    bundle = a.normalize(raw)
    assert bundle.signals[0].event_date is None and bundle.signals[0].published_at is None
    assert "created_at" not in bundle.entities[0].properties


@pytest.mark.db
def test_run_is_idempotent_and_download_growth_is_an_observation(session_factory) -> None:
    hub = FakeHub()
    first = adapter(hub, session_factory).run()
    assert first.status == "success" and first.records_created == 4  # 3 models + acme org
    second = adapter(hub, session_factory).run()
    assert (second.records_created, second.records_updated) == (0, 0)

    hub.models[0]["downloads"] = 500
    adapter(hub, session_factory).run()
    with session_factory() as s:
        count = lambda m: s.execute(select(func.count()).select_from(m)).scalar_one()
        assert count(SourceRecord) == 4 and count(SourceRecordRevision) == 0
        value = s.execute(select(Observation.metric_value).join(Entity, Entity.id == Observation.entity_id)
                          .where(Entity.canonical_name == "acme/one", Observation.metric_name == "downloads")).scalar_one()
        assert int(value) == 500
        assert count(Relationship) >= 4
