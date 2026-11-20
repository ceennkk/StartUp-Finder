# VentureRadar Ingestion (Phase 1: Data Foundation)

Collects public data on research, funding and developer activity, normalizes it into a common model and stores it, with full provenance and history, in PostgreSQL (Neon). 
**Scope of this repository: data collection, normalization and storage only.** There is no scoring, ranking, startup detection, entity resolution, team detection, market analysis, dashboard or API server. The schema leaves room for those later phases but none of their logic exists here.

## Contents
1. [Architecture](#architecture)
2. [Setup](#setup)
3. [Running collectors](#running-collectors-cli)
4. [Collectors](#collectors)
5. [Database schema](#database-schema)
6. [Data quality rules](#data-quality-rules)
7. [Privacy and legal notes](#privacy-and-legal-notes)
8. [Error handling](#error-handling)
9. [n8n integration](#n8n-integration)
10. [Adding a new source](#adding-a-new-source)
11. [Known limitations](#known-limitations)
12. [Tests](#tests)

## Architecture

```mermaid
flowchart LR
  CLI[CLI / n8n] --> RUN[BaseAdapter.run]
  RUN --> A[Adapters: OpenAlex, GitHub, arXiv, Hugging Face, EXIST, Universities]
  HTTP[PoliteHttpClient: spacing, retries, Retry-After, robots.txt] --> A
  A -->|RawRecord| STORE1[(source_records + revisions)]
  A -->|normalize| N[NormalizedBundle: entities, relationships, signals, observations]
  N --> STORE2[(entities, aliases, relationships, signals, observations)]
```

* `app/adapters/base.py` - template method: `fetch -> store raw -> normalize -> validate -> store normalized`. Raw data is written first, each record in its own savepoint, so one bad record never loses data or stops the run.
* `app/database/repositories.py` - all writes are upserts on unique constraints, which makes every run idempotent.
* `app/normalization/` - pure helpers (text cleaning, DOI, persons, organizations). Missing values stay `NULL`; nothing is inferred.
* Entities are scoped to **one source identifier** (for example `github user 123`, `openalex author A5...`). Entities from different sources or with the same name are **never merged** - that is entity resolution and belongs to a later phase. External IDs (ORCID, ROR, DOI) are stored as aliases only.

## Setup

Requirements: Python 3.12+, Docker (for the local test database), a Neon project for production data.

```powershell
# keep the virtualenv outside OneDrive (sync makes it slow)
python -m venv C:\Users\<you>\venvs\startup-finder
C:\Users\<you>\venvs\startup-finder\Scripts\python.exe -m pip install -r requirements.txt

Copy-Item .env.example .env        # then edit .env
docker compose up -d               # local PostgreSQL 16 on port 5433 (tests / fallback)
python -m app.cli database init    # applies Alembic migrations
python -m app.cli database status
```

### Configuration (`.env`)

| Variable | Needed for | Notes |
|---|---|---|
| `DATABASE_URL` | everything except `--dry-run` | Neon **pooled** string. `postgresql://` is rewritten to the psycopg 3 driver automatically. |
| `DATABASE_URL_DIRECT` | optional | Non-pooled Neon URL, preferred by Alembic migrations. |
| `TEST_DATABASE_URL` | tests | Defaults to the Docker database. Use `127.0.0.1`, not `localhost` (IPv6 lookups can stall for 20 s). |
| `GITHUB_TOKEN` | GitHub | Personal access token with public read access. |
| `OPENALEX_API_KEY` | recommended | Free key. Without it the shared keyless budget ($0.10/day per IP) and basic paging (10,000 results) apply. |
| `HF_TOKEN` | optional | Public endpoints work without it. |
| `CONTACT_EMAIL` | recommended | Included in the `User-Agent`. |

Secrets are only read from the environment / `.env` (which is git-ignored). No credentials are stored in code or in the database.

### Local database fallback
`docker compose up -d` starts PostgreSQL 16 (`ventureradar_test`). Point `DATABASE_URL` at it to run without Neon:
`postgresql+psycopg://ventureradar:ventureradar@127.0.0.1:5433/ventureradar_test`.

## Running collectors (CLI)

```powershell
python -m app.cli collect openalex
python -m app.cli collect github --limit 20 --dry-run
python -m app.cli collect all
python -m app.cli collect university --source ude_forschung   # --source: only for `university` (key or group)
python -m app.cli database init | status
python -m app.cli ingestion history --limit 10 --source github
```

* `--limit N` caps the number of records (test mode). `--dry-run` fetches, normalizes and validates but writes nothing and needs no database. A limited run does not advance incremental watermarks.
* stdout carries JSON (one `RunResult` per collector); logs are JSON lines on stderr (`LOG_FORMAT=text` for humans).

| Exit code | Meaning |
|---|---|
| 0 | success |
| 10 | partial: some records failed, the rest was stored |
| 1 | failed (stored data is kept) |
| 2 | configuration error (unknown collector, missing token / `DATABASE_URL`) |
| 3 | database unreachable |

## Collectors

Every collector runs standalone, is incremental (watermarks in `sync_state`, advanced only after a fully successful run), paginated, rate-limit aware and retried (tenacity, `Retry-After`). Search scope lives in `app/config/search_terms.yaml` and `app/config/sources.yaml`.

| Collector | Access | Scope config | Key behavior and fields |
|---|---|---|---|
| `openalex` | REST `/works` | topics + countries (DE) | Cursor paging (needs key), `from_publication_date` watermark with 7-day lookback. ID, title, abstract (rebuilt from the inverted index), publication date, authors + IDs, institutions + IDs (ROR), topics, keywords, DOI, reference list (raw), citation count (observation). Max 100 authors per work become entities. |
| `github` | REST + Search | topic queries | Repository search sliced by created-date windows (1000-result cap per query, auto-split). Repository fields, README, contributors, recent commits/issues/PRs (identifiers and dates only, **no emails or git author names**), counts via `Link` headers. Known repositories are re-observed every run with ETag conditional requests. Observations: stars, forks, open issues, subscribers, contributors, commits, PRs. |
| `arxiv` | Atom API | categories | 1 request / 3 s, oldest-first so capped runs resume. ID (version separate), title, abstract, authors, published/updated, categories, DOI, comment, abstract and PDF **URL** (PDFs are not stored). Affiliations only when present in the metadata. |
| `huggingface` | Hub API | language filters / search | Models, datasets, spaces (+ model card text), namespaces resolved to organization or user, public org members (handles only). Observations: downloads, likes. |
| `exist` | sitemap + WordPress REST (dates) + HTML | `sources.yaml` | Success stories (company, website, summary) and the three programme pages. Programme mentions are keyword matches and stored as **unverified** `FUNDED_BY`. |
| `university` | RSS, validated sitemap + JSON-LD, JSON-LD, page metadata, HTML selectors | `sources.yaml` | Plugin system. Working examples: KIT, TU Darmstadt and the University of Duisburg-Essen (see [below](#university-of-duisburg-essen-ude)). |

### Source facts, terms and technical limits

| Source | Limits / terms handled | Limitations |
|---|---|---|
| OpenAlex | Free key: $1/day budget, 429 + `Retry-After`; an exhausted daily budget stops the run immediately. | `from_updated_date` needs a paid plan, so incremental runs use publication date + lookback; late-indexed old works are missed. |
| GitHub | Search: 30 req/min (paced at 2.1 s), core: 5000/h; 403/429 with `Retry-After`/reset are waited out up to 5 min, otherwise the run aborts with a clear message. | No repository geography, so scope is topic-based. Discussions need GraphQL and are not collected. |
| arXiv | One request per 3 s (terms of use); metadata is CC0; PDFs are never stored. | No country or author IDs: each authorship becomes its own person entity. |
| Hugging Face | Hub API rate limits via 429 handling. | **`huggingface.co` could not be reached from the development network (TLS interception / DNS filtering), so this collector is verified with mocked responses only.** Tag formats (`de`, `language:de`) and the org endpoints (`/api/organizations/{name}/overview` and `/members`) must be confirmed on the first live run. |
| exist.de | `robots.txt` honored, 2 s spacing. | Success stories contain no structured project start / funding start; those stay `NULL`. Person names in interviews are not extracted. |
| foerderdatenbank.de | **Not collected.** `robots.txt` disallows `/FDB/SiteGlobals/` (the search paths) and sets `Crawl-delay: 30`. | Add explicit detail pages to `sources.yaml` only after checking terms. |
| Universities | `robots.txt` honored per fetch, configurable spacing (HTML connectors: at least 10 s), explicit pages only (no crawling). | Each university needs its own entry; there is no uniform API. |

### University of Duisburg-Essen (UDE)

First worked example of the university adapter. All URLs live in `app/config/sources.yaml` (`universities.sources`, keys `ude_*`, group `ude`).

| Key | Source | Connector / kind | Status |
|---|---|---|---|
| `ude_forschung` | `https://www.uni-due.de/rss/forschung.rss` (research news) | `rss` / `news` | **enabled** |
| `ude_aktuell` | `https://www.uni-due.de/rss/aktuell.rss` (general news) | `rss` / `news` | disabled |
| `ude_guide` | `https://www.uni-due.de/guide/` start-up centre GUIDE, plus validated `sitemap.xml` discovery limited to `/guide/` (max 5 pages) | `page_metadata` / `organization_unit` | disabled |

```powershell
python -m app.cli collect university --source ude_forschung --limit 5 --dry-run
python -m app.cli collect university --source ude_forschung
python -m app.cli collect university --source ude        # whole group; fails while a member is disabled
```

* **Why two sources are disabled.** The UDE pages we checked state no terms for automated reuse of feed or page content, and `robots.txt` explicitly disallows `GPTBot`. Until the university clarifies this, only the research feed (public RSS meant for syndication; only metadata and a teaser are kept) is on. Selecting a disabled source fails with exit code 2. To enable one, set `enabled: true` after clarifying usage with the university; do not use the data for AI training.
* **Stored:** title, link, publication date, a teaser of at most 500 characters (feed description, HTML stripped), raw feed item metadata as provenance (`source_records`), watermark per source in `sync_state`. **Not stored:** `content:encoded` / complete article texts, enclosures or images (not even their URLs), authors, page bodies. GUIDE pages contribute only `<h1>`/`<title>` and the meta description.
* **Model:** feed items become `publication` entities `PUBLISHED_BY` the university entity (`university:ude`, shared by all three sources) with a `NEW_PRESS_RELEASE` signal. GUIDE becomes one `organization` entity (`unit:ude_guide`) `MEMBER_OF` the university; only the home page may update it, other pages are provenance. No signal is created for it.
* **Politeness.** `CONTACT_EMAIL` is required for UDE (`require_contact_email`) and sent in the `User-Agent` (`VentureRadar-Ingestion/0.1 (...; contact: <email>)`). `robots.txt` is checked before every origin is used and is itself fetched through the host throttle. Requests to `www.uni-due.de` are at least 10 s apart (HTML connectors cannot be configured below 10 s). The first run reads at most `initial_days` of history (90 for the research feed) and at most `max_items` entries.
* **Sitemap.** Before any URL from `sitemap.xml` is used it is validated: well-formed XML without DOCTYPE/entities, `urlset` in the sitemap namespace, at least one and at most 50,000 URLs, valid `http(s)` `<loc>` values on the sitemap's own host. An invalid sitemap fails that source; there is no silent fallback. At the time of writing the sitemap lists exactly 5,000 URLs and only six under `/guide/`; this looks like a size cap, so it may be incomplete and must not be treated as a full site index.
* **Adding another German university:** add an entry with its own `key` (optional shared `group`), pick `rss`, `sitemap`, `jsonld`, `page_metadata` or `html`, check its `robots.txt` and terms, and keep `enabled: false` while anything is unclear. A plugin is only needed for source-specific enrichment.

Timestamps are never conflated: `published_at` is the date in the source, `event_date` the real-world event (often `NULL`), `first_seen_at` the first discovery by VentureRadar, `created_at`/`updated_at` database bookkeeping. All are UTC; unknown values stay `NULL`.

## Database schema

All primary keys are UUIDs, all timestamps `timestamptz` (UTC).

```mermaid
erDiagram
  sources ||--o{ ingestion_runs : has
  sources ||--o{ source_records : has
  sources ||--o{ sync_state : has
  source_records ||--o{ source_record_revisions : history
  source_records ||--o{ entity_source_records : provenance
  entities ||--o{ entity_source_records : provenance
  entities ||--o{ entity_aliases : has
  entities ||--o{ relationships : source_or_target
  source_records ||--o{ relationships : evidence
  entities ||--o{ signals : has
  entities ||--o{ observations : has
```

| Table | Purpose |
|---|---|
| `sources` | origin, type, base URL, terms URL |
| `ingestion_runs` | one row per collector run: status, counters, error, metadata |
| `source_records` | **original payloads** (JSONB), content hash, `published_at`, `first_seen_at`, `last_seen_at`; unique `(source_id, external_id)` |
| `source_record_revisions` | previous payloads when the content hash changes (changes stay traceable) |
| `entities` | normalized entities (13 types), JSONB properties |
| `entity_aliases` | names, URLs, ORCID/ROR/DOI, and the source identifier that makes an entity addressable; unique per source and identifier |
| `entity_source_records` | provenance: which source record produced which entity |
| `relationships` | typed edges with `verification_status` (`source_asserted`, `unverified`, `manually_verified`), mandatory `source_record_id` |
| `signals` | observed events (`NEW_REPOSITORY`, `NEW_PUBLICATION`, `NEW_MODEL`, `NEW_FUNDING_PROJECT`, `NEW_CONTRIBUTOR`, ...), unique per entity, type and record |
| `observations` | time series of changing metrics (stars, downloads, citations, ...), one point per entity and metric per UTC day (`OBSERVATION_BUCKET`) |
| `sync_state` | incremental watermarks and ETags per source scope |

Volatile fields (stars, downloads, citation counts) do not create raw revisions: the raw payload is refreshed in place and the history lives in `observations`. Content changes (title, description, README, ...) keep the old payload in `source_record_revisions`.

## Data quality rules
1. Raw data is never overwritten by normalized data; each normalized row links back via `entity_source_records` / `source_record_id`.
2. Unknown values are `NULL`; nothing is guessed (no inferred dates, countries or founders).
3. Same-name persons are never merged; organization spelling variants are aliases.
4. Relationships exist only when the source states them, or are marked `unverified` (keyword evidence recorded in `properties`).
5. Re-running a collector creates no duplicates (unique constraints + upserts); failures keep already stored data.

## Privacy and legal notes
* Only public, source-attributed data is collected; no private profiles and no LinkedIn scraping (not implemented in this phase).
* Data minimization: no e-mail addresses, no git author names, no real names of Hugging Face members, no author fields from JSON-LD; GitHub persons are stored by login and profile URL only.
* `robots.txt` is checked for every HTML/RSS fetch (`respect_robots=True`); API terms (rate limits, no PDF storage for arXiv) are enforced in code.
* Erasure / rectification: all dependent rows reference `entities` or `source_records` with `ON DELETE CASCADE`.

```sql
-- remove a person and everything derived from them
DELETE FROM entities WHERE id = '<person uuid>';
-- additionally remove the raw records that mention them (cascades to revisions, signals, observations, edges)
DELETE FROM source_records WHERE id IN (SELECT source_record_id FROM entity_source_records WHERE entity_id = '<person uuid>');
```
There is no CLI for this yet; it is a documented manual procedure.

## Error handling
* HTTP: retries on transport errors, 429 and 5xx with exponential backoff and `Retry-After`; waits longer than 5 minutes (quota exhausted) fail fast.
* A failing record is counted, logged and skipped (savepoint); status becomes `partial` (exit 10), or `failed` if every record failed.
* A fetch error fails the run (exit 1) but keeps everything already committed; watermarks are not advanced.
* Inspect runs with `python -m app.cli ingestion history`.

## n8n integration
n8n only schedules; processing stays here.
1. Execute Command node: `python -m app.cli collect github --limit 200` (working directory = repository, `DATABASE_URL`/tokens as environment variables of the n8n process).
2. Branch on the exit code: `0` ok, `10` warn, anything else alert. stdout is a JSON line you can parse (`records_created`, `error_message`, ...).
3. Run collectors separately and at different intervals (e.g. arXiv/OpenAlex daily, GitHub every few hours). `collect all` runs them sequentially and returns the worst code.
4. Logs are JSON lines on stderr. A FastAPI wrapper can later call the same `BaseAdapter.run()`; it is deliberately not part of Phase 1.

## Adding a new source
1. Create `app/adapters/<name>.py` with a class extending `BaseAdapter`: set `name` and `source` (`SourceSpec`), implement `fetch()` (yield `RawRecord`, use `self.http`, `self.get_cursor/set_cursor`) and `normalize()` (return a `NormalizedBundle`).
2. Register it in `app/adapters/registry.py`.
3. Put scope and URLs in `app/config/search_terms.yaml` or `sources.yaml`.
4. Add fixtures and tests (see `tests/adapters/`): normalization, pagination, idempotent re-run.
5. For another university: add an entry under `universities.sources` (connector `rss`, `sitemap`, `jsonld`, `page_metadata` or `html`; see the UDE example), optionally a plugin in `app/adapters/university/plugins.py`.

## Known limitations
* Hugging Face has not been verified against the live API from the development network (see above).
* GitHub and arXiv have no country filter; German focus is only possible for OpenAlex (institution country) and the German sources.
* OpenAlex without an API key is practically limited to a few requests per day.
* HTML sources can change; parser output is covered by fixtures but a layout change needs a parser update.
* Corporate spin-outs, Product Hunt, pitch events and the LinkedIn reference adapter are not part of this phase.

## Tests
```powershell
docker compose up -d
python -m pytest              # unit + database tests (mocked HTTP)
python -m pytest -m live      # smoke tests against the real services
```
Database tests skip automatically when `TEST_DATABASE_URL` is not reachable.
