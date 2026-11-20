from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

from app.adapters.base import BaseAdapter
from app.config.settings import load_search_terms
from app.domain import AliasType, EntityType, RelationshipType, SignalType, SourceType
from app.http.client import HttpFetchError
from app.ingestion.types import (
    AliasDraft,
    EntityDraft,
    NormalizedBundle,
    ObservationDraft,
    RawRecord,
    RelationshipDraft,
    SignalDraft,
    SourceSpec,
)
from app.normalization.organizations import organization_draft
from app.normalization.persons import person_draft
from app.normalization.publications import compact
from app.normalization.text import clean_text
from app.utils.dates import parse_datetime, utcnow

log = logging.getLogger(__name__)

HUB = "https://huggingface.co"
KINDS = {
    # kind: (list endpoint, card URL prefix, entity type, signal, record type)
    "models": ("/api/models", "", EntityType.MODEL, SignalType.NEW_MODEL, "model"),
    "datasets": ("/api/datasets", "/datasets", EntityType.DATASET, SignalType.NEW_DATASET, "dataset"),
    "spaces": ("/api/spaces", "/spaces", EntityType.SPACE, SignalType.NEW_SPACE, "space"),
}
VOLATILE = frozenset({"downloads", "downloadsAllTime", "likes", "lastModified", "trendingScore"})
METRICS = {"downloads": "downloads", "downloadsAllTime": "downloads_all_time", "likes": "likes"}


def _num(value: Any) -> Decimal | None:
    return Decimal(int(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class HuggingFaceAdapter(BaseAdapter):
    name = "huggingface"
    source = SourceSpec(
        source_name="huggingface",
        source_type=SourceType.API,
        base_url=HUB,
        description="Hugging Face Hub models, datasets, spaces and organizations via the public Hub API.",
        terms_url="https://huggingface.co/terms-of-service",
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = config if config is not None else load_search_terms("huggingface")
        self._headers = {"Authorization": f"Bearer {self.settings.hf_token}"} if self.settings.hf_token else {}
        self.http.set_min_interval("huggingface.co", 0.25)
        # namespace -> "organization" | "user" | None (unknown), filled while fetching
        self._namespaces: dict[str, str | None] = {}
        self._lookups = 0

    # --- fetching ---------------------------------------------------------

    def fetch(self) -> Iterator[RawRecord]:
        today = utcnow()
        seen: set[tuple[str, str]] = set()
        for kind in self.config.get("kinds") or list(KINDS):
            spec = self.config.get(kind) or {}
            queries: list[dict[str, str]] = [{"filter": f} for f in spec.get("filters") or []]
            queries += [{"search": s} for s in spec.get("search") or []]
            if not queries:
                queries = [{}]
            for query in queries:
                scope = f"{kind}:" + (",".join(f"{k}={v}" for k, v in query.items()) or "all")
                cursor = self.get_cursor(scope)
                if cursor and cursor.get("from"):
                    since = parse_datetime(cursor["from"])
                else:
                    since = today - timedelta(days=int(self.config.get("default_start_days_back", 7)))
                complete = yield from self._query(kind, query, since, seen)
                if complete:
                    lookback = int(self.config.get("lookback_days", 1))
                    self.set_cursor(scope, {"from": (today - timedelta(days=lookback)).isoformat()})
        yield from self._organizations()

    def _query(self, kind: str, query: dict[str, str], since: Any, seen: set[tuple[str, str]]) -> Iterator[RawRecord]:
        endpoint, _, _, _, record_type = KINDS[kind]
        cap = int(self.config.get("max_items_per_query", 200))
        params: dict[str, Any] = {
            **query,
            "sort": "createdAt",
            "direction": -1,
            "limit": min(int(self.config.get("page_size", 100)), cap),
            "full": "true",
        }
        url: str | None = f"{HUB}{endpoint}"
        emitted = 0
        while url:
            response = self.http.get(url, params=params if url.endswith(endpoint) else None, headers=self._headers)
            items = response.json()
            for item in items:
                created = parse_datetime(item.get("createdAt"))
                if created is not None and created < since:
                    return True  # sorted newest first: everything after this is older than the watermark
                repo_id = item.get("id") or item.get("modelId")
                if not repo_id or (kind, repo_id) in seen:
                    continue
                seen.add((kind, repo_id))
                namespace = repo_id.split("/", 1)[0] if "/" in repo_id else item.get("author")
                if namespace:
                    yield from self._namespace_record(namespace)
                yield self._record(kind, record_type, item, repo_id, created)
                emitted += 1
                if emitted >= cap:
                    log.info("huggingface query capped", extra={"kind": kind, "query": query, "cap": cap})
                    return False
            nxt = response.links.get("next")
            url = nxt["url"] if nxt else None
            params = {}
        return True

    def _record(self, kind: str, record_type: str, item: dict[str, Any], repo_id: str, created: Any) -> RawRecord:
        payload = dict(item)
        if self.config.get("fetch_cards", True):
            payload["card_text"] = self._card(kind, repo_id)
        return RawRecord(
            external_id=f"{record_type}:{repo_id}",
            record_type=record_type,
            payload=payload,
            canonical_url=f"{HUB}{KINDS[kind][1]}/{repo_id}",
            published_at=created,
            volatile_keys=VOLATILE,
        )

    def _card(self, kind: str, repo_id: str) -> str | None:
        url = f"{HUB}{KINDS[kind][1]}/{repo_id}/raw/main/README.md"
        try:
            response = self.http.get(url, headers=self._headers, raise_for_status=False)
        except HttpFetchError:
            return None
        if response.status_code != 200:
            return None  # no card, gated or private
        return response.text[: int(self.config.get("card_max_chars", 20000))]

    def _namespace_record(self, namespace: str) -> Iterator[RawRecord]:
        """Resolve a namespace once per run; organizations are emitted as their own record (with public members)."""
        if namespace in self._namespaces:
            return
        if self._lookups >= int(self.config.get("max_namespace_lookups", 50)):
            self._namespaces[namespace] = None
            return
        self._lookups += 1
        try:
            response = self.http.get(f"{HUB}/api/organizations/{namespace}/overview", headers=self._headers, raise_for_status=False)
        except HttpFetchError:
            self._namespaces[namespace] = None
            return
        if response.status_code == 404:
            self._namespaces[namespace] = "user"
            return
        if response.status_code != 200:
            self._namespaces[namespace] = None
            return
        self._namespaces[namespace] = "organization"
        overview = response.json()
        members_response = self.http.get(f"{HUB}/api/organizations/{namespace}/members", headers=self._headers, raise_for_status=False)
        members: list[dict[str, Any]] = []
        if members_response.status_code == 200:
            # Data minimization: only the public handle, type and avatar are kept; real names are dropped.
            members = [
                {"name": m.get("user") or m.get("name"), "type": m.get("type"), "avatar_url": m.get("avatarUrl")}
                for m in members_response.json()
                if (m.get("user") or m.get("name"))
            ]
        yield RawRecord(
            external_id=f"organization:{namespace}",
            record_type="organization",
            payload={"name": namespace, "overview": overview, "members": members, "members_public": members_response.status_code == 200},
            canonical_url=f"{HUB}/{namespace}",
            volatile_keys=frozenset({"overview"}),
        )

    def _organizations(self) -> Iterator[RawRecord]:
        for name in self.config.get("organizations") or []:
            yield from self._namespace_record(name)

    # --- normalization ----------------------------------------------------

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        if raw.record_type == "organization":
            return self._normalize_org(raw)
        item = raw.payload
        repo_id = raw.external_id.split(":", 1)[1]
        kind = next(k for k, v in KINDS.items() if v[4] == raw.record_type)
        _, prefix, entity_type, signal_type, _ = KINDS[kind]
        card = item.get("cardData") or {}
        created = parse_datetime(item.get("createdAt"))
        entity = EntityDraft(
            key="item",
            identifier=f"{raw.record_type}:{repo_id}",
            entity_type=entity_type,
            canonical_name=repo_id,
            description=clean_text(item.get("description") or card.get("description") or (item.get("card_text") or "")[:1000]),
            properties=compact(
                {
                    "hub_id": repo_id,
                    "url": raw.canonical_url,
                    "author": item.get("author"),
                    "created_at": item.get("createdAt"),
                    "last_modified": item.get("lastModified"),
                    "tags": item.get("tags"),
                    "pipeline_tag": item.get("pipeline_tag"),
                    "library": item.get("library_name"),
                    "sdk": item.get("sdk"),
                    "license": card.get("license"),
                    "language": card.get("language"),
                    "gated": item.get("gated"),
                    "model_card_excerpt": (item.get("card_text") or "")[:2000] or None,
                }
            ),
            aliases=[AliasDraft(alias=raw.canonical_url, alias_type=AliasType.URL)] if raw.canonical_url else [],
            is_primary=True,
            extraction_method=f"huggingface_{raw.record_type}",
        )
        entities = [entity]
        relationships: list[RelationshipDraft] = []
        namespace = repo_id.split("/", 1)[0] if "/" in repo_id else None
        kind_of_ns = self._namespaces.get(namespace) if namespace else None
        if namespace and kind_of_ns == "organization":
            org = organization_draft(
                key="ns", identifier=f"org:{namespace}", name=namespace,
                aliases=[AliasDraft(alias=namespace, alias_type=AliasType.LOGIN)],
                properties={"profile_url": f"{HUB}/{namespace}"},
            )
        elif namespace and kind_of_ns == "user":
            org = person_draft(
                key="ns", identifier=f"user:{namespace}", name=namespace,
                aliases=[AliasDraft(alias=namespace, alias_type=AliasType.LOGIN)],
                properties={"profile_url": f"{HUB}/{namespace}"},
            )
        else:
            org = None
        if org is not None:
            entities.append(org)
            relationships.append(RelationshipDraft(source_key="item", target_key="ns", relationship_type=RelationshipType.OWNED_BY))

        signals = [SignalDraft(entity_key="item", signal_type=signal_type, description=repo_id, event_date=created, published_at=created)]
        observations = [
            ObservationDraft(entity_key="item", metric_name=metric, value=value, unit="count")
            for field, metric in METRICS.items()
            if (value := _num(item.get(field))) is not None
        ]
        return NormalizedBundle(entities=entities, relationships=relationships, signals=signals, observations=observations)

    def _normalize_org(self, raw: RawRecord) -> NormalizedBundle:
        payload = raw.payload
        name = payload["name"]
        overview = payload.get("overview") or {}
        org = organization_draft(
            key="org", identifier=f"org:{name}", name=overview.get("fullname") or name,
            description=overview.get("details"),
            aliases=[AliasDraft(alias=name, alias_type=AliasType.LOGIN)],
            properties={"hub_name": name, "profile_url": raw.canonical_url, "avatar_url": overview.get("avatarUrl"),
                        "is_verified": overview.get("isVerified")},
            is_primary=True,
        )
        assert org is not None
        entities = [org]
        relationships: list[RelationshipDraft] = []
        for member in payload.get("members") or []:
            handle = member.get("name")
            if not handle or member.get("type") not in (None, "user"):
                continue
            key = f"user:{handle}"
            draft = person_draft(key=key, identifier=key, name=handle,
                                 aliases=[AliasDraft(alias=handle, alias_type=AliasType.LOGIN)],
                                 properties={"profile_url": f"{HUB}/{handle}", "avatar_url": member.get("avatar_url")})
            if draft is None or any(e.key == key for e in entities):
                continue
            entities.append(draft)
            relationships.append(RelationshipDraft(source_key=key, target_key="org", relationship_type=RelationshipType.MEMBER_OF))
        observations = []
        if payload.get("members_public"):
            observations.append(ObservationDraft(entity_key="org", metric_name="public_members", value=Decimal(len(payload.get("members") or [])), unit="count"))
        for field, metric in (("numFollowers", "followers"), ("numModels", "models"), ("numDatasets", "datasets"), ("numSpaces", "spaces")):
            value = _num(overview.get(field))
            if value is not None:
                observations.append(ObservationDraft(entity_key="org", metric_name=metric, value=value, unit="count"))
        return NormalizedBundle(entities=entities, relationships=relationships, observations=observations)
