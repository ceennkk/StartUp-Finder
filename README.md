# StartUp-Finder

> Build a sourcing engine that spots upcoming startups from the traces they leave long before their funding round.

StartUp-Finder identifies potential startups and early-stage ventures from public traces in research, universities, grant-funded projects, open source, and early business activity, and makes them traceable and reviewable. The focus is on evidence with provenance, not on collecting the largest possible number of records.

This repository contains the data collectors and the live StartUp-Finder product prototype. It is intended for local development by the team; it is not a finished public multi-user platform. Assessments and scores are research aids, not investment recommendations or HTGF investment decisions.

`ventureradar`, `VentureRadar-Ingestion`, and the package/table names are historical technical names; the product is **StartUp-Finder**.

## Contents

1. [Overview and implementation status](#overview-and-implementation-status)
2. [Repository layout](#repository-layout)
3. [Architecture](#architecture)
4. [Setup](#setup)
5. [Use the repository](#use-the-repository)
6. [Data collection (collector)](#data-collection-collector)
7. [Early-signal discovery](#early-signal-discovery)
8. [Finder pipeline: API, worker, and knowledge graph](#finder-pipeline-api-worker-and-knowledge-graph)
9. [Frontend](#frontend)
10. [Grants, equity, and the financial model](#grants-equity-and-the-financial-model)
11. [Eligibility and ranking](#eligibility-and-ranking)
12. [HTGF assessment (offline)](#htgf-assessment-offline)
13. [LLM allowlist (ingestion)](#llm-allowlist-ingestion)
14. [Data artifacts and database schema](#data-artifacts-and-database-schema)
15. [Data quality, privacy, and legal considerations](#data-quality-privacy-and-legal-considerations)
16. [Error handling](#error-handling)
17. [Adding a source](#adding-a-source)
18. [Checks](#checks)
19. [Known limitations](#known-limitations)
20. [Further documentation](#further-documentation)

## Overview and implementation status

| Component | Description | Status |
|---|---|---|
| **Data collection** (`app/`, `ventureradar` CLI) | Collect public or manually supplied sources, normalize them, and store them in PostgreSQL (Neon) with provenance | Implemented for `openalex`, `arxiv`, `github`, `huggingface`, `exist`, `university`, `cordis`, and `manual_import`; live verification varies by source |
| **Early-signal discovery** (`app/discovery/`) | Deterministic classification of stored signals/observations and limited text-mention rules | Implemented and tested; does not classify startups |
| **Finder pipeline** (`startup_finder/`) | Adapter bridge, relevance decisions, Graphiti/Neo4j knowledge graph, candidate profiles, research, assessment, evidence-gated ranking, JSON API | Implemented prototype; requires PostgreSQL, Neo4j, and OpenAI; no distributed transaction guarantee |
| **Frontend** (`frontend/`) | Home dashboard, Discover potential map, How it works, Shortlist, candidate assistant, plus a read-only `/datenbestand` view | Next.js 16 / React 19; product data comes from the live Finder API; no mock mode |
| **Financial model** (`app/finance/`, Finder API/domain) | Models grants and external equity separately; Finder stores versioned finance reviews in its PostgreSQL record store | Implemented data model and API; evidence/review remains curated and separate from LLM research claims |
| **Eligibility assessment** (`app/htgf/`, Finder API/domain) | Assesses Germany connection, technology scope, and commercial-register age from cited evidence | Deterministic offline CLI plus append-only live Finder snapshots; no automatic official-register verification |
| **LLM allowlist** (`app/llm/`) | Permission checks, evidence validation, and a fake provider for synthetic data | Deny by default; no real provider integration on the ingestion side |
| **Pitch** (`pitch/`) | Pitch video with synthetic demo data | Separate supporting project |

Important boundaries:

* Collector data is **not** a startup list. Stored organizations may already be funded and are not automatically classified as startups. `EntityType.STARTUP` is only a type value.
* There is **no global entity resolution** at the collector level: entities are source-specific and are never merged across sources or just because their names match. The Finder pipeline matches identities only within the Graphiti graph (model extraction and decision routes), not in the collector tables.
* Grants (EXIST, CORDIS, subsidies, stipends, prizes) are **not** equity rounds. `NEW_FUNDING_PROJECT` and `FUNDED_BY` describe grant or project context.
* Missing search results never prove that a company or financing does not exist.

## Repository layout

| Path | Description |
|---|---|
| `app/cli.py` | Typer `ventureradar` CLI: `collect`, `database`, `ingestion`, `discovery`, `llm`, `htgf` |
| `app/adapters/` | Collectors, registry, university connectors, and plugins |
| `app/config/` | Runtime settings, `search_terms.yaml`, `sources.yaml`, `llm_allowlist.yaml` |
| `app/database/` | SQLAlchemy models, repository, connection, and Alembic migrations |
| `app/discovery/` | Deterministic signal/observation classification and text rules |
| `app/evidence/` | Shared models for sources, documents, claims, evidence, and quote validation |
| `app/finance/` | Financial events, equity findings, and equity assessment |
| `app/htgf/` | Offline HTGF assessment with append-only history |
| `app/llm/` | Allowlist, authorization, analysis schema, fake provider, and runner |
| `app/http/`, `app/ingestion/`, `app/normalization/`, `app/utils/` | HTTP client, Pydantic types, normalization, and utilities |
| `startup_finder/` | Finder API, worker, store, adapter bridge, Graphiti clients, ontology, candidates, ranking, rebuild |
| `frontend/` | Next.js 16 / React 19 product frontend and server-rendered read-only data inventory |
| `data/candidates/` | Point-in-time candidate analysis (as of 2026-11-20) and HTGF inputs/outputs |
| `data/exports/` | Pilot exports for the knowledge graph and finance |
| `docs/` | Architecture, API contract, signal contract, LLM allowlist, financial model, HTGF, pilot handoff, ontology |
| `pitch/` | Pitch video script, scenes, and rendering |
| `scripts/` | Entry-point scripts (`run_collector.py`, `initialize_database.py`) and a one-off pilot script |
| `tests/` | Adapter, discovery, finance, HTGF, LLM, HTTP, database, integration, and normalization tests |

## Architecture

```mermaid
flowchart LR
  subgraph Collector["Data collection (app/)"]
    CLI[ventureradar CLI] --> RUN[BaseAdapter.run]
    HTTP[PoliteHttpClient: delays, retries, Retry-After, robots.txt] --> A
    RUN --> A[Adapters: OpenAlex, GitHub, arXiv, Hugging Face, EXIST, universities, CORDIS, manual import]
    A -->|RawRecord| SR[(source_records + revisions)]
    A -->|normalize| N[entities, aliases, relationships, signals, observations]
    DISC[discovery preview / run] --> N
  end
  subgraph Finder["Finder pipeline (startup_finder/)"]
    BR[Adapter-Bridge] --> J[(jobs / records)]
    J --> W[Worker]
    W --> DEC[Relevance check: Decision API + evidence quote]
    DEC --> G[Graphiti → Neo4j]
    G --> C[Candidate profiles]
    C --> R[Research + assessment + ranking]
    API[JSON-API]
  end
  SR --> BR
  N --> BR
  API --> FE[Next.js-Frontend]
  SR -. read-only .-> FE
```

**Data collection:** `app/adapters/base.py` orchestrates `fetch → store raw data → normalize → validate → store normalized data`. Raw data is stored first (each record in its own savepoint); all writes are upserts against unique constraints, making runs idempotent. Transactions are committed at least every 50 records.

**Finder pipeline:** The adapter bridge reads collector `source_records` and their linked normalized data in read-only mode, then queues processing jobs. The worker checks relevance, uses Graphiti to extract a `StartupVenture` and its direct relationships into Neo4j, materializes candidate profiles in PostgreSQL, and triggers research and assessment. Details: [docs/architecture.md](docs/architecture.md).

## Setup

Requirements: Git, Python 3.12+, Node.js 20.9+, Docker with Compose, and an OpenAI API key for the Finder worker. The local stack uses PostgreSQL and Neo4j containers. No Neon account is needed for local development.

### 1. Clone and install Python dependencies

macOS/Linux:

```sh
git clone https://github.com/ceennkk/StartUp-Finder.git
cd StartUp-Finder
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[live,dev]"
```

Windows PowerShell:

```powershell
git clone https://github.com/ceennkk/StartUp-Finder.git
cd StartUp-Finder
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[live,dev]"
```

The `live` extra installs `graphiti-core`; `dev` installs test dependencies. The collector-only workflow can instead use `python -m pip install -e ".[dev]"`.

### 2. Configure local services and secrets

```sh
cp .env.example .env
```

Edit `.env` locally. For a self-contained development database, set `DATABASE_URL` to the PostgreSQL container started below and set matching `POSTGRES_*` and `NEO4J_PASSWORD` values. Add your OpenAI key. Keep `.env` private and never commit it. Do not point local setup or database tests at Neon or a shared database.

```dotenv
POSTGRES_USER=startup
POSTGRES_PASSWORD=choose-a-local-password
POSTGRES_DB=startup
DATABASE_URL=postgresql://startup:choose-a-local-password@127.0.0.1:5432/startup
NEO4J_PASSWORD=choose-another-local-password
NEO4J_URI=bolt://127.0.0.1:7687
OPENAI_API_KEY=your-key
DECISION_PROVIDER=off
```

`DECISION_PROVIDER=off` disables optional decision routing while retaining the generative Finder model. To use OpenAI Decision routing, choose `DECISION_PROVIDER=openai` and set `OPENAI_DECISIONS_MODEL` to a model ID enabled for your account. The Finder uses `OPENAI_MODEL` (default `gpt-6-luna`) for generation.

### 3. Start the local databases and initialize schemas

```sh
docker compose up -d postgres neo4j
python -m app.cli database init       # Collector schema via Alembic
python -m app.cli database status
python -m startup_finder init-db      # Finder records, jobs, leases, schema_version
```

The collector and Finder use the same `DATABASE_URL` but separate schemas/models: Alembic manages collector tables; `startup_finder init-db` creates the Finder record/job tables. The `docker-compose.yml` (hyphenated) is a separate disposable test database on port `5433`; do not confuse it with the local application stack in `compose.yml` on port `5432`.

`python -m app.cli database init` runs `alembic upgrade head`. Before running either initialization command, verify that `DATABASE_URL` points at the intended local database. **Never initialize or run destructive database tests against Neon or a shared database.**

### Configuration (`.env`)

`.env` is git-ignored. Secrets are read only from the environment and are never stored in code or the database. Variable names are listed in [.env.example](.env.example).

| Variable | Required for | Notes |
|---|---|---|
| `DATABASE_URL` | Collector, discovery, LLM, Finder | Shared PostgreSQL connection string. The collector uses SQLAlchemy; Finder uses psycopg 3. |
| `DATABASE_URL_DIRECT` | Alembic | Unpooled Neon URL; Alembic falls back to `DATABASE_URL` if this is unset. Collectors do **not** use it — to run collectors against the direct endpoint, set `DATABASE_URL` accordingly. |
| `TEST_DATABASE_URL` | Database tests | Use only a disposable database (e.g. Docker at `127.0.0.1:5433`). Tests drop the `public` schema. |
| `GITHUB_TOKEN` | `github` | Token with public read access |
| `OPENALEX_API_KEY` | `openalex` (recommended) | Without a key, a small shared daily budget and basic paging up to 10,000 results apply |
| `HF_TOKEN` | `huggingface` (optional) | Public endpoints work without a token |
| `CONTACT_EMAIL` | Recommended; required for UDE | Sent in the `User-Agent` |
| `MANUAL_IMPORT_DIR` | `manual_import` | Defaults to `data/manual_imports/`; git-ignored |
| `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_RETRIES`, `LOG_LEVEL`, `LOG_FORMAT`, `OBSERVATION_BUCKET` | Collector | Runtime parameters |
| `HOST`, `PORT`, `API_TOKEN`, `CORS_ORIGINS`, `APP_MODE` | Finder API | `API_TOKEN` is required if `HOST` is not loopback; `APP_MODE` must be unset or `live` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Finder worker | Required for generation, research, and assessment; default model is `gpt-6-luna` |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Finder | Required to start the Finder |
| `GRAPHITI_GROUP_ID`, `GRAPHITI_CLIENT_FACTORY`, `GRAPHITI_TELEMETRY_ENABLED`, `SEMAPHORE_LIMIT` | Finder | Graphiti configuration |
| `DECISION_PROVIDER`, `OPENAI_DECISIONS_MODEL`, `JEV_API_KEY`, `JEV_MODEL` | Finder | Set `off`, `openai`, or `jev`; provider-specific access and model IDs are required when enabled |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `compose.yml` | Local Finder stack |

### Docker variants

| File | Purpose |
|---|---|
| `docker-compose.yml` | Disposable test/development database for the collector (PostgreSQL 16, port `5433`, `ventureradar_test`) |
| `compose.yml` | Local PostgreSQL (port `5432`) and Neo4j (`7474`/`7687`) for the Finder pipeline |
| `compose.app.yml` | Adds `api` and `worker`: `docker compose -f compose.yml -f compose.app.yml up --build` |
| `Dockerfile` | Image for the Finder API/worker (`python -m startup_finder serve`) |

For the simplest local workflow, run only PostgreSQL and Neo4j in Docker and start API/worker from the Python environment. The optional `compose.app.yml` binds the API inside the container to `0.0.0.0`; set a nonempty `API_TOKEN` before using it.

## Use the repository

The project has two connected workflows: **collect source data** with `app/`, then **turn eligible source records into candidate profiles** with `startup_finder/`. The frontend is the normal user interface. A useful first local run is:

1. Complete the [setup](#setup), verify `DATABASE_URL`, and start PostgreSQL/Neo4j.
2. Run one small collector preview, then collect a small sample:

   ```sh
   python -m app.cli collect openalex --limit 10 --dry-run
   python -m app.cli collect openalex --limit 10
   python -m app.cli database status
   ```

3. In separate terminals, start the API and worker:

   ```sh
   python -m startup_finder serve
   ```

   ```sh
   python -m startup_finder worker
   ```

   The worker checks for new or changed collector records on a 60-second schedule, then queues relevance, graph extraction, profile, research, and assessment work. Model and graph calls can incur cost.

4. Start the UI in another terminal:

   ```sh
   cd frontend
   npm ci
   npm run dev
   ```

   Open <http://localhost:3000>. The API must allow this origin in `CORS_ORIGINS` (already listed in `.env.example`). The UI has no mock/demo mode and hides product data unless the backend confirms live mode.

5. Use **Home** for system activity, **Discover** for candidate profiles, **How it works** for the pipeline overview, and **Shortlist** for saved candidates. Candidate profiles show evidence and assessment details; the assistant answers against candidate and graph data.

Useful day-to-day commands:

```sh
python -m app.cli database status
python -m app.cli ingestion history --limit 10
python -m startup_finder sync-adapters --limit 10 --dry-run
python -m pytest -m "not db and not live"
cd frontend && npm run check
```

`sync-adapters --dry-run` still opens the configured database and initializes the Finder's own tables, but it does not queue process jobs. A normal `sync-adapters` run queues work for the worker. Before collecting or processing data, double-check the target database and remember that the worker can call paid model/embedding services.

### Typical contribution flow

1. Create a feature branch from the latest `main`.
2. Make the change in the appropriate module, update the corresponding contract/docs, and add or update a focused test when behavior changes.
3. Run safe checks from [Checks](#checks); use only a disposable local database for database tests.
4. Commit the change and open a PR to `main`. Do not commit `.env`, database dumps, credentials, or generated media under `pitch/*/out/`.

## Data collection (collector)

```powershell
python -m app.cli collect openalex --limit 10 --dry-run
python -m app.cli collect github --limit 20 --dry-run
python -m app.cli collect university --source ude_forschung --limit 5 --dry-run
python -m app.cli collect cordis --limit 5 --dry-run
python -m app.cli collect manual_import --dry-run
python -m app.cli collect all
python -m app.cli database status
python -m app.cli ingestion history --limit 10 --source github
```

The installed CLI is named `ventureradar`; `python -m app.cli` is equivalent.

* `--limit N` limits the number of records; a limited run does not advance cursors.
* `--dry-run` fetches and normalizes source data but writes nothing and does not require a database.
* `--source` is supported only for `university` (source key or group).
* stdout contains JSON (one `RunResult` per collector); logs are written to stderr as JSON lines (`LOG_FORMAT=text` for human-readable output).

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 10 | Partial: some records failed; the rest were stored |
| 1 | Failed (previously stored data remains) |
| 2 | Configuration error (unknown collector, missing token / `DATABASE_URL`) |
| 3 | Database unavailable |

### Collector overview

Each collector runs independently and incrementally (cursors in `sync_state` advance only after a fully successful run), supports pagination, and observes rate limits (Tenacity, `Retry-After`). Search scopes are defined in `app/config/search_terms.yaml` and `app/config/sources.yaml`.

| Collector | Access | Behavior and fields | Limitations |
|---|---|---|---|
| `openalex` | REST `/works` | Works by topic with links to German institutions. ID, title, abstract (from inverted index), date, authors + IDs, institutions (ROR), topics, keywords, DOI; citation count as an observation. Max. 100 authors per work. | Cursor based on publication date with a 7-day lookback; older works indexed late may be missed. Data is CC0. |
| `github` | REST + Search | Repository search by topic in 7-day windows (automatically split), README, contributors, commits/issues/PRs (IDs and dates only, **no email addresses or Git author names**). Known repositories are rechecked with ETags. | Requires `GITHUB_TOKEN`; searches are spaced 2.1 s apart; waits longer than 5 min abort. No country filter or Discussions. |
| `arxiv` | Atom API | Categories, oldest first; ID, title, abstract, authors, dates, categories, DOI, PDF **URL** (PDFs are not stored). | 1 request / 3 s; max. 1,000 results per run; no country filter and no stable author IDs. |
| `huggingface` | Hub API | Models, datasets, Spaces, optional model cards (max. 20,000 characters), namespaces as organizations/users, public members (handles only). Observations: downloads, likes. | So far verified only with mocks/fixtures; see [Known limitations](#known-limitations). |
| `exist` | Sitemap + WordPress REST (data) + HTML | Success stories and program pages. | Program associations are keyword matches and `UNVERIFIED` `FUNDED_BY`; no structured grant data or people. |
| `university` | RSS, validated sitemap + JSON-LD, JSON-LD, page metadata, CSS selectors | Explicitly configured sources; no crawling. Active: `kit`, `tu_darmstadt`, `ude_forschung`. | Robots check on each request; non-RSS requests are at least 10 s apart per host. See [UDE](#university-of-duisburg-essen-ude). |
| `cordis` | Public EURIO SPARQL endpoint (`SELECT` only) | EU projects with participants from configured countries (default `DE`): `research_project` with `NEW_FUNDING_PROJECT`; participants as `organization` with `PARTICIPATED_IN`. | 10 s delay, 25 projects per page, max. 1,000 per run, 60-day overlap; CC BY 4.0, attribution “© European Union, CORDIS”. No fallback endpoint. |
| `manual_import` | Local CSV/JSON files, **no network access** | People and companies (`person`, `organization`, `WORKS_AT`, `unverified` by default). | Max. 5 MB / 5,000 rows; LinkedIn URLs are syntax-checked only and never opened. Permanently excluded from LLM processing. |

`foerderdatenbank.de`, Fraunhofer, Max Planck, DLR, GEPRIS, HTGF, Bundesanzeiger, and others are **not** collected due to robots rules or unclear terms of use (findings dated 2026-11-20; see [AGENTS.md](AGENTS.md)). Public accessibility does not grant permission to reuse content.

### CORDIS

* Configuration: `sources.yaml` → `cordis` (`countries`, `initial_days`, `lookback_days`, `page_size`, `max_projects_per_run`). Only participants from configured countries are stored.
* Cursor: project start date plus a skip counter, allowing a limited run to resume within the same date.
* CORDIS does not provide a more specific organization type; `organization_type` remains the generic `organization`.
* CORDIS projects represent public research funding, not startup funding rounds.

### Manual Import

Place files in `MANUAL_IMPORT_DIR` and run `python -m app.cli collect manual_import [--dry-run]`.

* Columns/keys: `linkedin_url`, `name` (required); `position`, `company`, `project_affiliation`, `verification_status` (`unverified` or `manually_verified` with `verification_method` and `checked_at`), `notes`, `row_id`. Unknown columns cause rejection.
* A file containing an invalid row is rejected in its entirety and moved to `failed/` (with a `.problems.txt` file listing only rows and fields); the run is marked `partial`.
* Successfully imported files go to `processed/` (with a neutral name). Retention: 30 days for `processed`, 14 days for `failed`.
* Logs never contain names, companies, URLs, or notes. Tests use synthetic data only.

### University of Duisburg-Essen (UDE)

| Key | Source | Connector / type | Status |
|---|---|---|---|
| `ude_forschung` | `https://www.uni-due.de/rss/forschung.rss` | `rss` / `news` | **aktiv** |
| `ude_aktuell` | `https://www.uni-due.de/rss/aktuell.rss` | `rss` / `news` | disabled |
| `ude_guide` | `https://www.uni-due.de/guide/` + validated sitemap (`/guide/` only) | `page_metadata` / `organization_unit` | disabled |

* `ude_aktuell` and `ude_guide` remain disabled until terms of use are clarified (no terms for automated reuse were found; `robots.txt` blocks `GPTBot`). Selecting a disabled source exits with code 2.
* Stored: title, link, date, teaser (max. 500 characters), and feed metadata as provenance. **Not** stored: full text, enclosures, images, or authors.
* `CONTACT_EMAIL` is required; requests to `www.uni-due.de` are at least 10 s apart; initial fetch is limited to 90 days.
* Sitemaps are validated before use; the checked sitemap listed exactly 5,000 URLs and appears truncated, so it is not a complete site index.

Timestamps are kept distinct: `published_at` is the date from the source, `event_date` is the actual event date (often `NULL`), `first_seen_at` is when the record was first collected, and `created_at`/`updated_at` are database bookkeeping. All timestamps are UTC; unknown values remain `NULL`.

## Early-signal discovery

Discovery reads only data that has already been stored and makes no network requests.

```powershell
python -m app.cli discovery preview --limit 100                  # read-only
python -m app.cli discovery preview --source github --limit 100
python -m app.cli discovery run --source university --limit 100  # writes derived mention signals
```

* Adapter signals (`NEW_PUBLICATION`, `NEW_REPOSITORY`, `NEW_MODEL`, `NEW_FUNDING_PROJECT`, `NEW_CONTRIBUTOR`, `NEW_PRESS_RELEASE`, …) are classified, not duplicated. A repository is not a startup, and a grant-funded project is not an equity round.
* Individual observations are weak activity indicators; a single value is not a trend.
* Versioned text rules produce only `FOUNDING_ACTIVITY_MENTION`, `SPINOUT_MENTION`, and `COMMERCIALIZATION_MENTION`—lexical matches, not confirmed facts. `event_date` is not inferred from the publication date.
* The rule ID/version, field, match, and source reference are stored in `signals.properties`; repeated runs are idempotent.

Details: [docs/phase2-signal-contract.md](docs/phase2-signal-contract.md).

## Finder pipeline: API, worker, and knowledge graph

The Finder pipeline (`startup_finder/`) builds candidate profiles and a knowledge graph from collector data. It runs only in production mode and starts only with PostgreSQL `DATABASE_URL`, Neo4j, and `OPENAI_API_KEY`.

```sh
python -m startup_finder init-db        # Creates Finder tables (records, jobs, leases, schema_version)
python -m startup_finder serve          # JSON API; default http://127.0.0.1:8000
python -m startup_finder worker         # Queue, relevance checks, Graphiti, research, assessment
python -m startup_finder sync-adapters --source exist --limit 10 --dry-run
python -m startup_finder sync-adapters --source exist --limit 10
python -m startup_finder rebuild-graph --group-id startup_finder_de_ontology_v1
```

**Warning:** Every one of these commands—including `sync-adapters --dry-run`—first initializes the Finder tables in the database configured by `DATABASE_URL`. These tables are not managed by Alembic. A run without `--dry-run` queues jobs; the worker then makes billable OpenAI, embedding, and Graphiti calls.

Workflow:

1. **Adapter bridge:** Reads `source_records` and their revisions, entities, aliases, relationships, signals, and observations in read-only mode and creates Finder records. Only records with an HTTP(S) URL, a title, and usable text are imported. The worker polls for new adapter records every 60 seconds.
2. **Relevance check:** The decision route assesses each record; only relevant records are checked by the generative model for a specifically named venture candidate with a verbatim evidence quote. General publications and programs remain in collector PostgreSQL but are not added to the Finder graph.
3. **Knowledge graph:** Graphiti writes to Neo4j using the vocabulary in [docs/startup-sourcing-ontology.ttl](docs/startup-sourcing-ontology.ttl) (ventures, people, organizations, products, technologies, markets, investors, funding rounds, programs, locations, metrics). The API reads a materialized subset in PostgreSQL.
4. **Research and assessment:** Each new candidate triggers research (product, team, location, market, funding rounds/investors) and assessment. Funding is confirmed only when a quote has been verified in a retrieved original document; `not_found` means only “no evidence found in the sources searched.”
5. **Ranking:** Four equally weighted sourcing criteria create a visible score; incomplete evidence is marked provisional. Confirmed eligibility failure or external equity sets the final score to zero. Evaluation jobs have priority over ingestion backlog so profiles receive scores promptly. See [Eligibility and ranking](#eligibility-and-ranking).

API endpoints and data formats: [docs/frontend-contract.md](docs/frontend-contract.md). Search jobs collect configured sources; the prompt is stored as context only—semantic search is not implemented.

## Frontend

```sh
cd frontend
npm ci
npm run dev      # http://localhost:3000
npm run check    # Typecheck + production build
```

The product frontend is served at `/`. Its navigation is **Home**, **Discover**, **How it works**, and **Shortlist**; candidate details open from Discover and the candidate assistant can query candidate and graph data. The language switch supports English and German. The interface communicates with the Finder API through `frontend/src/finder/api/client.ts` (default `http://localhost:8000`; `CORS_ORIGINS` must include `http://localhost:3000`). Product data is displayed only when the API reports `live`; there is no mock API. No token is required for a loopback-bound API; a non-loopback API requires `API_TOKEN`.

`/datenbestand` is a separate technical view that reads collector data from the configured PostgreSQL database on the server side using read-only transactions (entities, relationships, records, runs). It is not the candidate or knowledge-graph view. Details: [frontend/README.md](frontend/README.md).

## Grants, equity, and the financial model

`app/finance/` strictly separates grants from external equity ([docs/financial-support-and-equity.md](docs/financial-support-and-equity.md)):

* `FinancialSupportEvent` describes a curated event with a category (grant, stipend, research funding, prize, equity, angel/VC, loan, convertible instrument, in-kind, other, unknown), status, amount with qualifier (`exact`, `up_to`, `approximate`), roles (applicant, recipient, funder), and the `dilutive`/`repayable` attributes (`yes`/`no`/`unknown`). Each claim has provenance with an exactly validated quote.
* Separately, `assess_equity` returns:
  * `equity_confirmed` — requires an explicit equity finding, evidence, and **documented human review**; distinguishes `completed` from `binding_agreement`.
  * `no_public_equity_round_found` — only after documented, human-reviewed research across company, registry, investor, and media sources; this is **not** proof that no private financing exists.
  * `equity_status_unclear` — all other cases.
* A category such as “Venture Capital” alone does not establish an equity finding. There is no dedicated donation category or fields for purchased shares or ownership percentages.
* **Persistence:** The standalone `app/finance/` model is a deterministic Python domain model. The live Finder stores curated, append-only finance snapshots in its own PostgreSQL record namespace; it does not write them to the collector's normalized finance tables. The pilot export at [data/exports/pilot_finance.json](data/exports/pilot_finance.json) is a separate point-in-time artifact.

## Eligibility and ranking

The live Finder records three eligibility checks alongside every numeric score:

1. The company has a German registered seat, or there is evidence of a concrete plan to move to Germany or establish a German permanent establishment.
2. It is a technology startup in Digital Tech, Industrial, Climate & Deep Tech, Life Sciences, Chemistry, or an adjacent field.
3. Its official commercial-register entry date is no more than three years before the assessment date (inclusive through the third calendar anniversary).

Evidence-backed snapshots remain append-only and can be read/written through `GET`/`POST /api/candidates/{id}/eligibility`. A confirmed failure sets the score to `0`. Missing or inconclusive eligibility evidence leaves a **provisional** score visible; a documented pre-company venture is also scored provisionally. The system does not infer a register date or Germany plan from an unsupported founding year, incubator location, or model guess. Candidate profiles show the evidence and uncertainty.

The model assesses four sourcing criteria: founding intent, technical substance, customer problem, and demand. They are equally weighted (`strong`=100, `moderate`=67, `weak`=33). Unknown criteria receive a neutral `50` in the composite score, so every completed assessment has a numeric result; `scored_criteria` and `score_confidence` show how much is evidence-backed, and the profile marks incomplete reviews provisional. A confirmed eligibility failure, manually confirmed external equity, or quote-verified confirmed dilutive/mixed funding sets the final score to `0`. Non-dilutive grants, stipends, research funding, and prizes do not incur that penalty. “No public round found” does not prove that no private financing exists.

Ranking policy is implemented in `startup_finder/ranking.py`; eligibility validation is in `app/htgf/assessment.py`. The numerical sourcing weights are an initial, unvalidated model and need evaluation against human-reviewed examples.

## HTGF assessment (offline and live)

The CLI workflow assesses manually curated evidence against the same three criteria without database, network, or LLM access. The live Finder uses the deterministic evaluator with evidence snapshots stored in PostgreSQL; it does not automatically verify official registry or Germany-relocation evidence. This assessment is a sourcing aid, not an investment decision.

```sh
python -m app.cli htgf run
```

Input defaults to `data/candidates/htgf_input.json`; outputs include append-only assessment history, an overview CSV, and a research report under `data/candidates/`. Details: [docs/htgf-assessment.md](docs/htgf-assessment.md).

## LLM allowlist (ingestion)

Before each analysis, `app/llm/` checks a source/field allowlist ([app/config/llm_allowlist.yaml](app/config/llm_allowlist.yaml), `default_policy: deny`, currently empty) and validates that each piece of evidence appears verbatim in a curated field.

```sh
python -m app.cli llm preview --limit 100   # Read-only permission check
python -m app.cli llm run --limit 100       # Writes to llm_analyses; synthetic sources only, local fake provider
```

There is no real provider integration here; real source data and `manual_import` are blocked. Results are stored in `llm_analyses` (migration `0002`). This restriction applies to ingestion; the Finder pipeline uses OpenAI independently through its own configuration. Details: [docs/phase2b4-llm-allowlist.md](docs/phase2b4-llm-allowlist.md).

## Data artifacts

| File | Description |
|---|---|
| `data/candidates/candidate_discovery.json`, `candidate_validation.json`, `candidate_overview.csv`, `candidate_research_report.md` | Point-in-time candidate analysis from a Neon snapshot dated 2026-11-20: 8 candidates from EXIST success stories, with separate company and funding statuses and a rule-based research score (0–10). No repeatable code workflow or investment assessment. |
| `data/candidates/htgf_*` | HTGF assessment inputs and outputs |
| `data/exports/knowledge_graph_pilot.json` | Pilot entities, relationships, and source records read from Neon (source `manual_pilot_research`) |
| `data/exports/pilot_finance.json` | Pilot financial events, evidence, equity findings, and assessments |

Pilot provenance, counts, and SQL examples: [docs/knowledge-graph-handoff.md](docs/knowledge-graph-handoff.md).

## Database schema

All primary keys are UUIDs; all timestamps are `timestamptz` (UTC). Collector tables are managed through Alembic (`app/database/migrations/`).

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
  source_records ||--o{ llm_analyses : analysed
```

| Table | Purpose |
|---|---|
| `sources` | Source, type, base URL, and terms URL; identified by `source_name` |
| `ingestion_runs` | One entry per run: status, counters, errors |
| `source_records` | **Original payloads** (JSONB), hash, `published_at`, `first_seen_at`, `last_seen_at`; unique by `(source_id, external_id)` |
| `source_record_revisions` | Previous payloads when content changes |
| `entities` | Normalized entities (13 types), JSONB properties |
| `entity_aliases` | Names, URLs, ORCID/ROR/DOI, and source-specific identifiers |
| `entity_source_records` | Entity ↔ source record provenance |
| `relationships` | Typed edges with `verification_status` (`source_asserted`, `unverified`, `manually_verified`) and required `source_record_id` |
| `signals` | Source- and time-related events, unique per entity, type, and record |
| `observations` | Time series (stars, downloads, citations, etc.), bucketed by `OBSERVATION_BUCKET` |
| `sync_state` | Cursors and ETags per source and query scope |
| `llm_analyses` | Versioned LLM analysis attempts (migration `0002`) |

The Finder pipeline also uses its own non-migrated tables (`records`, `jobs`, `leases`, `schema_version`) and Neo4j. Volatile fields do not create revisions; their history is stored in `observations`.

## Data quality, privacy, and legal considerations

1. Raw data is never overwritten by normalized data; all normalized data links back through `entity_source_records` / `source_record_id`.
2. Unknown values remain `NULL`; do not invent dates, countries, founders, or funding.
3. People with the same name are never merged; organization name variants are aliases.
4. Create relationships only when supported by a source; otherwise mark them `unverified`.
5. Repeated runs do not create duplicates; errors do not corrupt previously stored data.

* Use only public, source-attributed data; no LinkedIn scraping or private profiles.
* Data minimization: no email addresses, Git author names, or Hugging Face members' real names.
* Check `robots.txt` for HTML/RSS requests (fail closed); API terms (rate limits, no arXiv PDFs) are enforced in code.
* Permission to collect data does not grant permission to share it with LLM providers.
* Deletion/correction via `ON DELETE CASCADE` (documented manual procedure, no CLI):

```sql
DELETE FROM entities WHERE id = '<person uuid>';
DELETE FROM source_records WHERE id IN (
  SELECT source_record_id FROM entity_source_records WHERE entity_id = '<person uuid>');
```

In this case, data in Neo4j and the Finder tables must be checked separately or rebuilt using `rebuild-graph`.

## Error handling

* HTTP: retries on transport errors, 429, and 5xx with backoff and `Retry-After`; waits longer than 5 min fail immediately.
* A faulty record is counted and skipped (status `partial`); a fetch error stops the run (exit code 1), and cursors are not advanced.

## Adding a source

1. Add `app/adapters/<name>.py` with a `BaseAdapter` subclass: `name`, `source` (`SourceSpec`), `fetch()` (returns `RawRecord`, uses `self.http`, `get_cursor`/`set_cursor`), and `normalize()` (returns `NormalizedBundle`).
2. Register it in `app/adapters/registry.py`.
3. Add the scope and URLs to `search_terms.yaml` or `sources.yaml`.
4. Add fixtures and tests (normalization, pagination, idempotent reruns).
5. For universities, an entry under `universities.sources` is usually sufficient; set `enabled: false` if terms are unclear.

First check terms, attribution, robots rules, rate limits, and data minimization, and document the review date.

## Tests

```powershell
python -m pytest -m "not db and not live"            # Safe entry point: no database, no network
python -m unittest discover -s tests\finance -t .    # Isolated financial model tests
python -m unittest discover -s tests\htgf -t .       # Isolated HTGF tests
docker compose up -d; python -m pytest               # Includes DB tests; use only with disposable TEST_DATABASE_URL
python -m pytest -m live                             # Smoke tests against real services
cd frontend; npm run check                           # Frontend typecheck and build
```

**Warning:** Database tests drop and recreate the `public` schema of the database configured by `TEST_DATABASE_URL`, then run migrations. Never run them against Neon or a shared database. Database tests are skipped if the test database is unavailable.

## Known limitations

* **Hugging Face:** The latest local live requests failed during TLS certificate verification (`unable to get local issuer certificate`), before any HTTP response. The token, tag formats (`de`, `language:de`), and organization endpoints have not yet been confirmed live. TLS verification is not disabled.
* GitHub and arXiv have no country filter; a German focus is available only through OpenAlex and the German sources.
* Without an API key, OpenAlex is effectively limited to a small number of requests per day.
* HTML sources can change; parsers are covered by fixtures.
* Text rules detect mentions only; no adapter emits `NEW_PITCH_PRESENTATION`.
* No entity resolution across collectors and no trend analysis over observations.
* Financial data is not persisted in Neon; there is no donation category or fields for ownership percentages.
* Finder pipeline: Neo4j and PostgreSQL do not share a transaction (no exactly-once guarantee); no roles/tenant model; ranking weights are unvalidated; model costs are not fully accounted for; `graphiti-core` is not pinned to an exact version.
* Live source excerpts are not claim-level evidence spans and require human review before investment decisions.

## Further documentation

* [AGENTS.md](AGENTS.md) – Product context, source findings, and required change guidelines
* [docs/architecture.md](docs/architecture.md) – Finder architecture, data flow, consistency, ranking, security
* [docs/frontend-contract.md](docs/frontend-contract.md) – API contract
* [docs/phase2-signal-contract.md](docs/phase2-signal-contract.md) – Signal rules and evidence boundaries
* [docs/phase2b4-llm-allowlist.md](docs/phase2b4-llm-allowlist.md) – LLM allowlist and data minimization
* [docs/financial-support-and-equity.md](docs/financial-support-and-equity.md) – Grants and equity assessment
* [docs/htgf-assessment.md](docs/htgf-assessment.md) – HTGF assessment
* [docs/knowledge-graph-handoff.md](docs/knowledge-graph-handoff.md) – Pilot knowledge graph and finance export
* [docs/startup-sourcing-ontology.ttl](docs/startup-sourcing-ontology.ttl) – Knowledge graph ontology
* [frontend/README.md](frontend/README.md), [pitch/README.md](pitch/README.md)
