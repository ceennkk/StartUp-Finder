from __future__ import annotations

import base64
import logging
import re
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select

from app.adapters.base import AdapterConfigError, BaseAdapter
from app.config.settings import load_search_terms
from app.database.connection import session_scope
from app.database.models import SourceRecord
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
from app.utils.dates import iter_windows, parse_datetime, utcnow

log = logging.getLogger(__name__)

API = "https://api.github.com"
SEARCH_LIMIT = 1000  # GitHub returns at most 1000 results per search query
README_MAX_CHARS = 100_000
EMPTY_OK = {204, 304, 404, 409, 451}
_LAST_PAGE = re.compile(r'[?&]page=(\d+)[^>]*>;\s*rel="last"')


def _login(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {"id": user.get("id"), "login": user.get("login"), "type": user.get("type")}


class GitHubRateLimitError(HttpFetchError):
    """Rate limit exhausted for longer than we are willing to wait; aborts the run."""


def _is_fatal(exc: HttpFetchError) -> bool:
    return isinstance(exc, GitHubRateLimitError) or exc.status_code in (401, 429) or exc.status_code is None


def _hash_basis(payload: dict[str, Any]) -> dict[str, Any]:
    """Slow-changing fields only: counters, pushes and activity are tracked as observations instead."""
    repo = payload["repository"]
    return {
        "full_name": repo.get("full_name"),
        "description": repo.get("description"),
        "topics": repo.get("topics"),
        "language": repo.get("language"),
        "license": (repo.get("license") or {}).get("spdx_id"),
        "default_branch": repo.get("default_branch"),
        "archived": repo.get("archived"),
        "visibility": repo.get("visibility"),
        "homepage": repo.get("homepage"),
        "owner_id": (repo.get("owner") or {}).get("id"),
        "readme_sha": (payload.get("readme") or {}).get("sha"),
    }


class GitHubAdapter(BaseAdapter):
    name = "github"
    source = SourceSpec(
        source_name="github",
        source_type=SourceType.API,
        base_url="https://api.github.com",
        description="GitHub public repositories, contributors and activity via the REST API.",
        terms_url="https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms",
    )

    def __init__(self, *args: Any, config: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        if not self.settings.github_token:
            raise AdapterConfigError("GITHUB_TOKEN is not set")
        self.config = config if config is not None else load_search_terms("github")
        self._headers = {
            "Authorization": f"Bearer {self.settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.http.set_min_interval("api.github.com", 0.1)

    # --- low-level --------------------------------------------------------

    @staticmethod
    def _secondary_wait(response: httpx.Response) -> float | None:
        """Seconds to wait when GitHub answers 403 because of a rate limit; None for real permission errors."""
        if response.status_code != 403:
            return None
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        if response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset")
            if reset and reset.isdigit():
                return max(1.0, float(reset) - utcnow().timestamp() + 1)
        return None

    def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        search: bool = False,
        etag: str | None = None,
    ) -> httpx.Response:
        headers = dict(self._headers)
        if etag:
            headers["If-None-Match"] = etag
        if search:
            self.http.pace("github-search", 2.1)  # search allows 30 requests per minute
        response = self.http.get(
            url,
            params=params,
            headers=headers,
            raise_for_status=False,
            should_retry=self._secondary_wait,
        )
        if response.status_code >= 400 and response.status_code not in EMPTY_OK:
            if response.status_code == 429 or self._secondary_wait(response) is not None:
                raise GitHubRateLimitError(
                    f"GitHub rate limit exhausted (resets at {response.headers.get('X-RateLimit-Reset')})",
                    response.status_code,
                )
            raise HttpFetchError(f"GET {url} returned {response.status_code}", response.status_code)
        return response

    def _json_or_none(self, url: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self._get(url, params)
        except HttpFetchError as exc:
            if _is_fatal(exc):
                raise
            return None
        return None if response.status_code in EMPTY_OK else response.json()

    def _count(self, url: str, params: dict[str, Any] | None = None) -> int | None:
        """Total item count via per_page=1 and the Link header's last page."""
        response = self._get(url, {**(params or {}), "per_page": 1})
        if response.status_code in EMPTY_OK:
            return 0
        match = _LAST_PAGE.search(response.headers.get("Link", ""))
        return int(match.group(1)) if match else len(response.json())

    # --- fetching ---------------------------------------------------------

    def fetch(self) -> Iterator[RawRecord]:
        seen: set[int] = set()
        for repo in self._discover():
            if repo["id"] in seen:
                continue
            seen.add(repo["id"])
            record = self._collect(repo)
            if record is not None:
                yield record
        yield from self._refresh_known(seen)

    def _discover(self) -> Iterator[dict[str, Any]]:
        today = utcnow().date()
        window_days = int(self.config.get("window_days", 7))
        per_query_cap = int(self.config.get("max_repositories_per_query", 100))
        min_stars = int(self.config.get("min_stars", 0))
        for query in self.config.get("queries") or []:
            scope = f"search:{query['name']}"
            cursor = self.get_cursor(scope)
            if cursor and cursor.get("from"):
                start = date.fromisoformat(cursor["from"])
            else:
                start = today - timedelta(days=int(self.config.get("default_start_days_back", 14)))
            emitted = 0
            capped = False
            for first, last in iter_windows(start, today, window_days):
                for repo in self._search_window(query["q"], first, last, min_stars):
                    yield repo
                    emitted += 1
                    if emitted >= per_query_cap:
                        capped = True
                        break
                if capped:
                    break
            if capped:
                log.warning("github query capped", extra={"query": query["name"], "cap": per_query_cap})
            else:
                lookback = int(self.config.get("lookback_days", 1))
                self.set_cursor(scope, {"from": (today - timedelta(days=lookback)).isoformat()})

    def _search_window(self, q: str, first: date, last: date, min_stars: int) -> Iterator[dict[str, Any]]:
        parts = [q, f"created:{first.isoformat()}..{last.isoformat()}"]
        if min_stars:
            parts.append(f"stars:>={min_stars}")
        params = {"q": " ".join(parts), "sort": "updated", "order": "desc", "per_page": 100}
        page = 1
        while True:
            data = self._get(f"{API}/search/repositories", {**params, "page": page}, search=True).json()
            total = data.get("total_count", 0)
            if page == 1 and total > SEARCH_LIMIT and first < last:
                mid = first + (last - first) // 2
                log.info("splitting github search window", extra={"first": str(first), "last": str(last), "total": total})
                yield from self._search_window(q, first, mid, min_stars)
                yield from self._search_window(q, mid + timedelta(days=1), last, min_stars)
                return
            items = data.get("items") or []
            yield from items
            if len(items) < 100 or page * 100 >= SEARCH_LIMIT:
                if total > SEARCH_LIMIT:
                    log.warning("github search truncated at 1000 results", extra={"q": params["q"]})
                return
            page += 1

    def _refresh_known(self, seen: set[int]) -> Iterator[RawRecord]:
        limit = int(self.config.get("refresh_known_limit", 25))
        if self.dry_run or not limit or self.session_factory is None or self._source_id is None:
            return
        with session_scope(self.session_factory) as session:
            ids = session.execute(
                select(SourceRecord.external_id)
                .where(SourceRecord.source_id == self._source_id, SourceRecord.record_type == "repository")
                .order_by(SourceRecord.last_seen_at.asc())
                .limit(limit + len(seen))
            ).scalars().all()
        for external_id in [i for i in ids if int(i) not in seen][:limit]:
            record = self._collect({"id": int(external_id)})
            if record is not None:
                yield record

    def _collect(self, stub: dict[str, Any]) -> RawRecord | None:
        """Fetch the repository (conditional on ETag) and its README, contributors and recent activity."""
        repo_id = int(stub["id"])
        etag_scope = f"etag:repo:{repo_id}"
        previous = self.get_cursor(etag_scope) or {}
        response = self._get(f"{API}/repositories/{repo_id}", etag=previous.get("etag"))
        if response.status_code == 304:
            return self._stored_record(repo_id)  # confirmed unchanged: keeps last_seen_at and the observation series current
        if response.status_code in EMPTY_OK:
            return None  # repository gone or blocked
        repo = response.json()
        if response.headers.get("ETag"):
            self.set_cursor(etag_scope, {"etag": response.headers["ETag"]})

        full_name = repo["full_name"]
        base = f"{API}/repos/{full_name}"
        n = int(self.config.get("activity_items", 30))
        errors: list[str] = []

        def safe(label: str, fn: Any) -> Any:
            try:
                return fn()
            except HttpFetchError as exc:
                if _is_fatal(exc):
                    raise
                errors.append(f"{label}: {exc}")
                return None

        readme = safe("readme", lambda: self._json_or_none(f"{base}/readme"))
        contributors = safe("contributors", lambda: self._json_or_none(f"{base}/contributors", {"per_page": 100, "anon": "false"})) or []
        commits = safe("commits", lambda: self._json_or_none(f"{base}/commits", {"per_page": n})) or []
        issues = safe("issues", lambda: self._json_or_none(f"{base}/issues", {"state": "all", "per_page": n, "sort": "created"})) or []
        pulls = safe("pulls", lambda: self._json_or_none(f"{base}/pulls", {"state": "all", "per_page": n, "sort": "created"})) or []
        totals = {
            "contributors": safe("contributor_total", lambda: self._count(f"{base}/contributors", {"anon": "false"})),
            "commits": safe("commit_total", lambda: self._count(f"{base}/commits")),
            "pull_requests": safe("pr_total", lambda: self._count(f"{base}/pulls", {"state": "all"})),
        }

        readme_text = None
        if isinstance(readme, dict) and readme.get("content"):
            try:
                readme_text = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")[:README_MAX_CHARS]
            except ValueError:
                errors.append("readme: undecodable content")

        # Data minimization: only identifiers and activity metadata are kept; git author names and emails are dropped.
        payload = {
            "repository": repo,
            "readme": {"sha": readme.get("sha"), "path": readme.get("path"), "text": readme_text} if readme_text else None,
            "contributors": [
                {
                    "id": c.get("id"),
                    "login": c.get("login"),
                    "type": c.get("type"),
                    "html_url": c.get("html_url"),
                    "avatar_url": c.get("avatar_url"),
                    "contributions": c.get("contributions"),
                }
                for c in contributors
            ],
            "totals": totals,
            "recent_commits": [
                {
                    "sha": c.get("sha"),
                    "author": _login(c.get("author")),
                    "committer": _login(c.get("committer")),
                    "authored_at": ((c.get("commit") or {}).get("author") or {}).get("date"),
                    "committed_at": ((c.get("commit") or {}).get("committer") or {}).get("date"),
                    "message_headline": ((c.get("commit") or {}).get("message") or "").split("\n", 1)[0][:200],
                }
                for c in commits
            ],
            "recent_issues": [
                {k: i.get(k) for k in ("number", "title", "state", "created_at", "closed_at")} | {"user": _login(i.get("user"))}
                for i in issues
                if "pull_request" not in i
            ],
            "recent_pull_requests": [
                {k: p.get(k) for k in ("number", "title", "state", "created_at", "closed_at", "merged_at")}
                | {"user": _login(p.get("user"))}
                for p in pulls
            ],
            "collected_at": utcnow().isoformat(),
            "fetch_errors": errors,
        }
        return RawRecord(
            external_id=str(repo["id"]),
            record_type="repository",
            payload=payload,
            canonical_url=repo.get("html_url"),
            published_at=parse_datetime(repo.get("created_at")),
            hash_basis=_hash_basis(payload),
        )

    def _stored_record(self, repo_id: int) -> RawRecord | None:
        if self.session_factory is None or self._source_id is None:
            return None
        with session_scope(self.session_factory) as session:
            stored = session.execute(
                select(SourceRecord).where(
                    SourceRecord.source_id == self._source_id, SourceRecord.external_id == str(repo_id)
                )
            ).scalar_one_or_none()
            if stored is None:
                return None
            payload = stored.raw_payload
            return RawRecord(
                external_id=stored.external_id,
                record_type=stored.record_type,
                payload=payload,
                canonical_url=stored.canonical_url,
                published_at=stored.published_at,
                hash_basis=_hash_basis(payload),
            )

    # --- normalization ----------------------------------------------------

    def normalize(self, raw: RawRecord) -> NormalizedBundle:
        payload = raw.payload
        repo = payload["repository"]
        created = parse_datetime(repo.get("created_at"))
        license_info = repo.get("license") or {}
        readme_text = (payload.get("readme") or {}).get("text")
        owner = repo.get("owner") or {}
        owner_is_org = owner.get("type") == "Organization"

        repo_draft = EntityDraft(
            key="repo",
            identifier=f"repo:{repo['id']}",
            entity_type=EntityType.REPOSITORY,
            canonical_name=repo["full_name"],
            description=clean_text(repo.get("description")),
            properties=compact(
                {
                    "github_id": repo["id"],
                    "name": repo.get("name"),
                    "html_url": repo.get("html_url"),
                    "homepage": repo.get("homepage") or None,
                    "language": repo.get("language"),
                    "topics": repo.get("topics"),
                    "license": license_info.get("spdx_id"),
                    "default_branch": repo.get("default_branch"),
                    "visibility": repo.get("visibility"),
                    "archived": repo.get("archived"),
                    "is_fork": repo.get("fork"),
                    "created_at": repo.get("created_at"),
                    "pushed_at": repo.get("pushed_at"),
                    "updated_at": repo.get("updated_at"),
                    "owner_type": owner.get("type"),
                    "readme_excerpt": readme_text[:2000] if readme_text else None,
                }
            ),
            aliases=[AliasDraft(alias=repo["html_url"], alias_type=AliasType.URL)] if repo.get("html_url") else [],
            is_primary=True,
            extraction_method="github_repository",
        )
        entities = [repo_draft]
        relationships: list[RelationshipDraft] = []
        signals = [
            SignalDraft(
                entity_key="repo",
                signal_type=SignalType.NEW_REPOSITORY,
                description=repo["full_name"],
                event_date=created,
                published_at=created,
            )
        ]
        known = {"repo"}

        def add_user(user: dict[str, Any]) -> str | None:
            if not user.get("id") or user.get("type") == "Bot":
                return None
            key = f"user:{user['id']}"
            if key in known:
                return key
            props = {"github_id": user["id"], "login": user.get("login"),
                     "profile_url": user.get("html_url"), "avatar_url": user.get("avatar_url")}
            draft = person_draft(
                key=key,
                identifier=key,
                name=user.get("login"),
                aliases=[AliasDraft(alias=user["login"], alias_type=AliasType.LOGIN)] if user.get("login") else [],
                properties=props,
            )
            if draft is None:
                return None
            entities.append(draft)
            known.add(key)
            return key

        if owner.get("id"):
            if owner_is_org:
                org = organization_draft(
                    key=f"org:{owner['id']}",
                    identifier=f"org:{owner['id']}",
                    name=owner.get("login"),
                    aliases=[AliasDraft(alias=owner["login"], alias_type=AliasType.LOGIN)],
                    properties={"github_id": owner["id"], "profile_url": owner.get("html_url"),
                                "avatar_url": owner.get("avatar_url")},
                )
                owner_key = org.key if org else None
                if org:
                    entities.append(org)
                    known.add(org.key)
            else:
                owner_key = add_user(owner)
            if owner_key:
                relationships.append(
                    RelationshipDraft(source_key="repo", target_key=owner_key, relationship_type=RelationshipType.OWNED_BY)
                )

        for contributor in payload.get("contributors") or []:
            key = add_user(contributor)
            if key is None:
                continue
            relationships.append(
                RelationshipDraft(
                    source_key=key,
                    target_key="repo",
                    relationship_type=RelationshipType.CONTRIBUTED_TO,
                    properties=compact({"contributions": contributor.get("contributions")}),
                )
            )
            signals.append(
                SignalDraft(
                    entity_key=key,
                    signal_type=SignalType.NEW_CONTRIBUTOR,
                    description=f"{contributor.get('login')} contributes to {repo['full_name']}",
                    properties=compact({"repository": repo["full_name"], "contributions": contributor.get("contributions")}),
                )
            )

        totals = payload.get("totals") or {}
        metrics = {
            "stars": (repo.get("stargazers_count"), "count"),
            "forks": (repo.get("forks_count"), "count"),
            "open_issues_and_prs": (repo.get("open_issues_count"), "count"),
            "subscribers": (repo.get("subscribers_count"), "count"),
            "contributors": (totals.get("contributors"), "count"),
            "commits": (totals.get("commits"), "count"),
            "pull_requests": (totals.get("pull_requests"), "count"),
        }
        observations = [
            ObservationDraft(entity_key="repo", metric_name=name, value=Decimal(int(value)), unit=unit)
            for name, (value, unit) in metrics.items()
            if value is not None
        ]
        return NormalizedBundle(
            entities=entities, relationships=relationships, signals=signals, observations=observations
        )
