# VentureRadar Ingestion (Phase 1 + 2A/2B)

Collects public data on research, funding and developer activity, normalizes it into a common model and stores it, with full provenance and history, in PostgreSQL (Neon).
**Scope of this repository: data collection, normalization, storage, and deterministic early-signal discovery.** Discovery classifies existing source signals and individual observations and can emit rule-based text-mention signals with source-record provenance. It does not identify startups or founding teams. There is no entity resolution, funding verification, scoring, ranking, market analysis, dashboard or API server.

## Product goal and funding requirement

> Build a sourcing engine that spots upcoming startups from the traces they leave long before their funding round.

StartUp-Finder is meant to discover emerging startups and founding projects from their early public traces, as long as possible before their first external startup funding round. The current implementation includes data ingestion plus a bounded early-signal discovery layer; funding verification and startup selection remain future stages:

1. **Data collection and early-signal discovery (Phase 1 plus 2A/2B):** collectors store public traces with provenance; deterministic rules classify signals and explicit text mentions. This is not startup classification and does not check or record equity funding rounds.
2. **Funding verification (future):** a later stage checks per candidate whether an external funding round is documented.
3. **Startup selection (future):** the primary search profile is built from the verification result.

* Research grants, scholarships, funding programmes and competition prizes (EXIST, CORDIS grants, other public funds) are **not** startup funding rounds. Pre-seed, seed, Series A and later external equity rounds are. Funding events must later be documented with source, date, type and, where public, amount.
* Planned funding states (concept only, not in code or database): `funding_round_found` (a reliable source proves an external round), `no_funding_round_found` (research found none; no guarantee that none exists) and `funding_status_unknown` (no reliable check possible or insufficient data). Missing information about a round never proves that no funding was received.
* The primary search profile is meant to contain companies without a proven first external funding round; companies with a documented round are to be flagged separately and excluded from it.
* **Current limitation:** the present data collection gives **no guarantee** that only not-yet-funded startups are captured. Stored organisations may already be funded and are not classified as startups.
* Startup selection and funding verification are documented future tasks; they are not implemented and need explicit approval before work starts (see `AGENTS.md`, section 1.1).

## Offline HTGF assessment

The separate, file-based HTGF assessment evaluates manually curated candidate
evidence against the three supplied HTGF questions. It does not discover
candidates, verify funding, access the database or make an HTGF investment
decision. Funding and HTGF fit remain independent. See
[HTGF assessment](docs/htgf-assessment.md) for the evidence format, history,
commands and tests.

## Contents
1. [Architecture](#architecture)
2. [Setup](#setup)
3. [Running collectors](#running-collectors-cli)
4. [Collectors](#collectors)
5. [Early-signal discovery](#early-signal-discovery)
6. [Database schema](#database-schema)
7. [Data quality rules](#data-quality-rules)
8. [Privacy and legal notes](#privacy-and-legal-notes)
9. [Error handling](#error-handling)
10. [n8n integration](#n8n-integration)
11. [Adding a new source](#adding-a-new-source)
12. [Known limitations](#known-limitations)
13. [Tests](#tests)

## Architecture

```mermaid
flowchart LR
  CLI[CLI / n8n] --> RUN[BaseAdapter.run]
  RUN --> A[Adapters: OpenAlex, GitHub, arXiv, Hugging Face, EXIST, Universities, CORDIS, Manual import]
  HTTP[PoliteHttpClient: spacing, retries, Retry-After, robots.txt] --> A
  A -->|RawRecord| STORE1[(source_records + revisions)]
  A -->|normalize| N[NormalizedBundle: entities, relationships, signals, observations]
  N --> STORE2[(entities, aliases, relationships, signals, observations)]
  DCLI[discovery preview / run] --> DISC[Deterministic discovery rules]
  STORE2 --> DISC
  DISC -->|derived mention signals only| STORE2
```

* `app/adapters/base.py` - template method: `fetch -> store raw -> normalize -> validate -> store normalized`. Raw data is written first, each record in its own savepoint, so one bad record never loses data or stops the run.
* `app/database/repositories.py` - all writes are upserts on unique constraints, which makes every run idempotent.
* `app/discovery/` - classifies existing source signals and individual observations without duplicating them; versioned text rules can add source-record-linked mention signals.
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
| `MANUAL_IMPORT_DIR` | optional | Directory read by `manual_import` (default `data/manual_imports`). Must stay git-ignored. |

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
| `cordis` | public EURIO SPARQL endpoint (read-only `SELECT`) | `sources.yaml` (`cordis`) | EU-funded projects with at least one participant in the configured countries (default `DE`). Project -> `research_project` (`NEW_FUNDING_PROJECT` signal on its start date), participants -> `organization` with property `organization_type` and a `source_asserted` `PARTICIPATED_IN`. See [CORDIS](#cordis) and [Manual import](#manual-import). |
| `manual_import` | local CSV/JSON files, **no network** | `sources.yaml` (`manual_import`) | Reference lists of people and their company, supplied by hand. `person` + `organization` + `WORKS_AT` (`unverified` by default). See [Manual import](#manual-import). |

## Early-signal discovery

Discovery only reads data already ingested into the database; it makes no
network requests. Preview classifications and candidate text mentions without
writing:

```powershell
python -m app.cli discovery preview --limit 100
python -m app.cli discovery preview --source github --limit 100
```

Persist derived mention signals only with the explicit `run` command:

```powershell
python -m app.cli discovery run --source university --limit 100
```

* Existing adapter-generated source signals (`NEW_PUBLICATION`,
  `NEW_REPOSITORY`, `NEW_MODEL`, `NEW_CONTRIBUTOR`, etc.) are returned as
  discovery-category classifications. They are not reinterpreted or duplicated
  as new `signals` rows.
* Individual metric observations are classified by metric and source as weak
  research, technology, developer-activity, or organization-activity evidence.
  A single value is not a trend, growth claim, or threshold event.
* The deterministic text rules emit only `FOUNDING_ACTIVITY_MENTION`,
  `SPINOUT_MENTION`, and `COMMERCIALIZATION_MENTION`. These are lexical
  mentions, not verified founding, spin-out, product launch, sales, or startup
  facts. `event_date` is not inferred from a publication date.
* The write path stores rule ID/version, matched field/term and source-signal
  reference in `signals.properties`; `source_record_id` links to the unchanged
  original record. Upserts use the existing `(entity_id, signal_type,
  source_record_id)` uniqueness constraint. Re-running a rule updates the same
  derived row; obsolete derived matches for processed records are reconciled
  without deleting adapter source signals.
* No schema migration is required. Trend rules that compare observations across
  time, Candidate Resolution, funding verification, startup classification and
  ranking are out of scope.

The full field inventory, rule contract, exclusions and evidence limitations
are in [docs/phase2-signal-contract.md](docs/phase2-signal-contract.md).

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
| CORDIS | Endpoint `https://cordis.europa.eu/datalab/sparql-api` (checked 2026-11-20); `robots.txt` honored, 10 s spacing, 25 projects per page (two requests each), no federated queries, no bulk ZIPs (`/data/` is disallowed). Data: CC BY 4.0 / Commission Decision 2011/833/EU, attribution "(c) European Union, CORDIS" (stored with every record). | No documented endpoint limits. No change date, so each run re-reads a 60-day overlap by project start date. Organisation activity type (university, research centre, company) is not exposed, so `organization_type` is the generic `organization`. |
| Manual import | Local files only; nothing is sent anywhere. | See [Manual import](#manual-import). |

### CORDIS

```powershell
python -m app.cli collect cordis --limit 5 --dry-run
```

* Config: `sources.yaml` -> `cordis` (`countries`, `initial_days`, `lookback_days`, `page_size`, `max_projects_per_run`). Only participants from the configured countries are stored. An unreachable endpoint, a `robots.txt` block or a non-SPARQL answer fails the run; there is no fallback to another endpoint or access method.
* Watermark: project start date plus a skip count, so a capped run resumes inside a start date that holds many projects.
* CORDIS projects are public research funding, not startup funding rounds (see the product goal above).
* **Organisation types:** the data model only knows `university` and `organization`. CORDIS organisations are stored as `organization` with `properties.organization_type = "organization"` (the source gives nothing finer). Types such as `research_institute` or `research_organization` would need a change to `app/domain.py` and the database; that is not part of this phase.

### Manual import

Drop CSV or JSON files into `MANUAL_IMPORT_DIR` (default `data/manual_imports/`, git-ignored with all subdirectories) and run `python -m app.cli collect manual_import [--dry-run]`.

* Columns/keys: `linkedin_url` and `name` (required); `position`, `company`, `project_affiliation` (free text), `verification_status` (`unverified` default, or `manually_verified`, which needs `verification_method` and `checked_at`), `notes`, `row_id`. Unknown columns reject the file. The LinkedIn URL is only checked syntactically (`linkedin.com/in/<profile>`) and never opened.
* A file with any invalid row is rejected as a whole and nothing from it is imported. Rejected files go to `failed/` with a `.problems.txt` that names rows and fields only; the run is `partial` (exit 10).
* Files are moved only after every row was stored: to `processed/` under a neutral name (`<UTC time>_<content hash>`). A failed record, `--limit` or `--dry-run` leaves them in place. `processed/` files are deleted after `processed_retention_days` (30), `failed/` after `failed_retention_days` (14).
* Logs and error messages contain counts, row numbers and field names, never names, companies, URLs or notes. Tests use synthetic data only.
* People and companies are never matched to entities of other sources; within this source a company is identified by its normalized name. Imported rows are personal data in the database: use the erasure procedure below to remove them.

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
* Spin-out, founding and commercialization rules detect bounded text mentions only; they do not verify events or classify startups. No adapter currently emits `NEW_PITCH_PRESENTATION`.

## Tests
```powershell
docker compose up -d
python -m pytest -m "not db and not live"  # safe unit tests; no database required
python -m pytest              # includes DB tests; only use a disposable TEST_DATABASE_URL
python -m pytest -m live      # smoke tests against the real services
```

**Warning:** DB tests reset the `public` schema of `TEST_DATABASE_URL`. Never
point them at a database containing data you need to keep. Discovery preview is
read-only; `discovery run` writes derived mention signals.
Database tests skip automatically when `TEST_DATABASE_URL` is not reachable.

## Integrated Finder API and frontend

## Frontend

```sh
cd frontend
npm ci
npm run dev
```

Die Produktoberfläche spricht über `frontend/src/finder/api/client.ts` mit dem
Backend. Basis-URL ist standardmäßig `http://localhost:8000`; die API muss
`http://localhost:3000` in `CORS_ORIGINS` erlauben. Zugangsdaten gehören in
Backend-Secrets, nicht in den Browser. Auf Loopback (`127.0.0.1`/`localhost`)
ist kein zusätzlicher API-Token nötig; bei Netzwerkbindung verlangt das Backend
weiterhin `API_TOKEN`. `/datenbestand` ist eine separate technische, schreibgeschützte
Ansicht des Adapterdatenbestands in Neon.

## Adapterdaten in die Finder-Pipeline übernehmen

Collector-Fundstellen (`source_records`) werden mit dem Bridge-Befehl in Finder-
Fundstellen überführt und als process-Jobs eingereiht. Ein laufender Worker
verarbeitet sie anschließend mit Graphiti, LLM und Decision-Routen. Stabile
Adapter-IDs machen die Übernahme wiederholbar.

```sh
# Feldmapping prüfen; schreibt keine Finder-Daten und reiht keine Jobs ein.
python3 -m startup_finder sync-adapters --source exist --record-type success_story --limit 1 --dry-run
# Gezielte reale Fundstelle importieren und einen Worker-Job einreihen.
python3 -m startup_finder sync-adapters --source exist --record-type success_story --limit 1
```

Nur Zeilen mit HTTP(S)-URL, Titel und verwertbarem Text werden übernommen. Die
Bridge verändert keine Collector-Originale. Der Worker übernimmt neue und
geänderte Datensätze automatisch in die Graphiti-Pipeline. Diese kann Graphiti-,
Embedding-, Decision- und Modellaufrufe auslösen.

## Decision-Routen

`DECISION_PROVIDER=openai` routet Graphitis Node-Deduplizierung und Edge-Auflösung
über die OpenAI Decisions API (`OPENAI_DECISIONS_MODEL`, Standard `gpt-6-luna`).
Extraktion und Zusammenfassung bleiben beim generativen Modell `OPENAI_MODEL`
(Standard `gpt-6-luna`).
Fehlende Providerunterstützung führt zu einem Fehler, nicht zu einem stillen Fallback.

## Dokumentation und Grenzen

- [API-Vertrag](docs/frontend-contract.md)
- [Architektur, Datenfluss und Betriebsgrenzen](docs/architecture.md)

Der aktuelle Suchauftrag sammelt konfigurierte HTML-, RSS- und manuelle Quellen;
der Prompt ist gespeicherter Auftragskontext. Semantische Quellenauswahl und
offene Discovery anhand des Prompts sind nicht implementiert. Das System ist ein
Team-Prototyp, keine fertige öffentliche Mehrbenutzerplattform. Bewertungen sind
keine automatische Bestätigung der Startup-Qualität oder Anlageempfehlung.
