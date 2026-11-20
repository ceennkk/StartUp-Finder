# Phase 2A/2B: signal contract and data quality

## Scope and evidence levels

This document covers deterministic signal classification and single-source-record
discovery only. It does not identify startups, merge entities, verify funding,
or rank candidates. International sources already configured in the project
remain in scope.

Data-quality statements are separated by evidence:

* **Static inspection** describes fields and behavior visible in adapter and
  schema code.
* **Test evidence** describes behavior covered by fixtures and assertions; it
  does not establish source completeness.
* **Empirical profile** requires a read-only query against a suitable local
  dataset. It must not be run against a production database without approval.

The configured local test database was inspected in read-only transactions. At
inspection time it contained one synthetic `fake` source record: `published_at`
was absent (0/1), `first_seen_at` present (1/1), external ID and source
reference present (1/1 each), description-like top-level fields absent (0/1),
and an entity-source link present (1/1). Its one `NEW_REPOSITORY` signal had
neither `event_date` nor `published_at`; its one `stars` observation had an
`observed_at` and no unit. These synthetic data are not suitable for measuring
actual source coverage, field completeness, or signal quality. No production
database was queried.

## Signal layers

### Source signals

Source signals are emitted by adapters and retain their original meaning. They
are evidence that an adapter observed the source event, not that a startup or
founding event occurred.

| Existing type | Adapter | Meaning in this repository |
|---|---|---|
| `NEW_PUBLICATION` | OpenAlex, arXiv | A publication/preprint record was collected. |
| `NEW_REPOSITORY` | GitHub | A repository record was collected. |
| `NEW_CONTRIBUTOR` | GitHub | A contributor was listed for a repository. |
| `NEW_MODEL`, `NEW_DATASET`, `NEW_SPACE` | Hugging Face | A Hub asset was collected. |
| `NEW_PRESS_RELEASE` | UniversityAdapter | A configured news/press-release item was collected. |
| `NEW_RESEARCH_PROJECT` | UniversityAdapter | A configured research-project item was collected. |
| `NEW_FUNDING_PROJECT` | CORDIS, EXIST | A public research/funding-related project or EXIST story was collected; this is not an equity funding round. |
| `NEW_PITCH_PRESENTATION` | No current adapter emission found | Enum member without an observed producer in the inspected adapters. |

Discovery categories for existing source signals are classifications returned
by the discovery engine. They do not create a second `Signal` row.

### Derived discovery signals

The first implementation derives only explicit-text **mentions** from one
source record and an existing source signal that identifies the related
entity. A mention is not independent verification. Each stored derived signal
records `discovery_rule_id`, `discovery_rule_version`, the matched field and
term, and the source signal ID in `properties`; `source_record_id` remains the
direct provenance link.

No rules compare multiple observations or establish trends. New derived signal
types reuse the existing string-valued `signals.signal_type` column and its
unique constraint on `(entity_id, signal_type, source_record_id)`.

## Static field inventory

These are field paths read from current adapter payloads; a field being
available in code does not imply it is populated in stored records.

| Source / adapter | Existing source event | Relevant payload fields available in code | Candidate discovery use |
|---|---|---|---|
| OpenAlex / `OpenAlexAdapter` | `NEW_PUBLICATION` | `id`, `title` or `display_name`, `publication_date`, `abstract_inverted_index`, `authorships[].author.id`, `authorships[].author.display_name`, `authorships[].institutions[].id`, `.display_name`, `.ror`, `.country_code`, `topics[].display_name`, `keywords[].display_name`, `cited_by_count` | Research output classification; no direct founding rule. |
| arXiv / `ArxivAdapter` | `NEW_PUBLICATION` | `arxiv_id`, `title`, `summary`, `authors[].name`, `authors[].affiliations[]`, `published`, `updated`, `categories[]`, `doi` | Research output classification; affiliations are optional and are not spin-out evidence. |
| GitHub / `GitHubAdapter` | `NEW_REPOSITORY`, `NEW_CONTRIBUTOR` | `repository.id`, `.full_name`, `.created_at`, `.pushed_at`, `.description`, `.topics`, `.language`, `.fork`, `.archived`, `.owner.id`, `.owner.type`, README `readme.text`; contributor `id`, `login`, `type`, `contributions`; observations `stars`, `forks`, `open_issues_and_prs`, `subscribers`, `contributors`, `commits`, `pull_requests` | Technology and contributor classifications; bounded text rules may detect founding/commercialization mentions. |
| Hugging Face / `HuggingFaceAdapter` | `NEW_MODEL`, `NEW_DATASET`, `NEW_SPACE` | `id`/`modelId`, `createdAt`, `lastModified`, `author`, `tags`, `description`, `card_text`, card metadata; organization overview/member fields; observations `downloads`, `downloads_all_time`, `likes`, `followers`, `models`, `datasets`, `spaces`, `public_members` | Technology classification; bounded text rules may detect founding/commercialization mentions. |
| EXIST / `ExistAdapter` | `NEW_FUNDING_PROJECT` for success stories | `title`, `subtitle`, `summary`, `url`, `website_url`, `published`, `programs_mentioned[]`; program-page records contain configured key/name, title, description and URL | Text mentions may be classified; a programme mention or success story is not a funding round or proof of company founding. |
| University / `UniversityAdapter` | `NEW_PRESS_RELEASE`, `NEW_RESEARCH_PROJECT` | `title`, `summary`, `url`, `published`, `tags`, configured `kind`, optional configured/plugin `extra`; organization-unit entries are modeled separately | Text mentions may be classified for news/press-release records; configured kind is not startup classification. |
| CORDIS / `CordisAdapter` | `NEW_FUNDING_PROJECT` | `project_id`, `title`, `start_date`, `end_date`, `rcn`, `status`, `abstract`, `participants[].org_uri`, `.name`, `.url`, `.countries`, `.roles`, license/attribution | Research/funding-project classification only. CORDIS funding is not an external startup equity round. |
| Manual import / `ManualImportAdapter` | No source signal emitted | `name`, `position`, `company`, `project_affiliation`, verification fields; LinkedIn URL is stored as a reference | No text discovery rule in the initial version; this source contains personal data and is not needed for discovery mentions. |

Database timestamps distinguish source publication (`published_at`), described
event (`event_date`), first system observation (`first_seen_at`) and database
bookkeeping (`created_at`/`updated_at`). Rules must not substitute a publication
date for a founding, spin-out, launch, or other real-world event date.

## Discovery classifications for source signals

These mappings are returned as classifications only; they preserve the
original source signal and do not insert another row.

| Source signal | Discovery category | Strength | Exclusions / interpretation |
|---|---|---|---|
| `NEW_PUBLICATION` | `research` | Explicit source event; weak startup relevance | Publication does not establish commercialization or founding. |
| `NEW_RESEARCH_PROJECT` | `research` | Explicit source event; weak startup relevance | Project is not a company. |
| `NEW_REPOSITORY`, `NEW_MODEL`, `NEW_DATASET`, `NEW_SPACE` | `technology` | Explicit source event; weak startup relevance | Asset creation is not a product launch or startup. |
| `NEW_CONTRIBUTOR` | `developer_activity` | Explicit source event; weak team/founding relevance | Contributor is not necessarily a team member or founder. |
| `NEW_PRESS_RELEASE` | `public_announcement` | Explicit source event; unknown startup relevance | A news item need not concern a company or founding. |
| `NEW_FUNDING_PROJECT` | `public_research_or_program_context` | Explicit source event; no equity-round meaning | Grants, scholarships, programme mentions and research budgets are not startup funding rounds. |
| `NEW_PITCH_PRESENTATION` | `pitch_activity` | Weak until an adapter provides source evidence | No current adapter producer was found; do not infer a pitch from unrelated data. |

## Individual observation classifications

Observations are classified by their source and exact metric name. Every
individual measurement remains an observation, not a second `Signal` row.
There is deliberately no minimum-value threshold: a zero or one-time count is
still just a single weak activity/attention measurement, not evidence of
growth. The result retains observation ID, value, unit, `observed_at`,
`source_record_id` and entity ID.

| Source / metric fields | Discovery category | Strength and interpretation |
|---|---|---|
| GitHub `stars`, `forks`, `open_issues_and_prs`, `subscribers` | `technology` | Weak single repository metric; no growth or startup claim. |
| GitHub `contributors`, `commits`, `pull_requests` | `developer_activity` | Weak single activity count; no team-growth claim. |
| Hugging Face `downloads`, `downloads_all_time`, `likes` | `technology` | Weak single Hub metric; no growth or startup claim. |
| Hugging Face `followers`, `models`, `datasets`, `spaces`, `public_members` | `organization_activity` | Weak single organization-level count; no startup or team claim. |
| OpenAlex `citation_count` | `research` | Weak single citation count; no quality or founding claim. |

There is intentionally no `startup_activity` class: an organization account or
its asset activity is not evidence that the organization is a startup.
Organization-level observations remain classified as `organization_activity`.

## Derived signal rules

All rules require an existing source signal on the same source record and use
that signal's entity as the target. Each rule is evaluated at most once per
`(rule_id, source_record_id, entity_id)`. Only the first matching field/term
is retained. Negated phrases are excluded. Results are mentions, not verified
facts.

| Technical type / rule | Meaning and trigger | Allowed source records / exact fields | Minimum data and exclusions | Strength, examples, and time |
|---|---|---|---|---|
| `FOUNDING_ACTIVITY_MENTION` / `founding-activity-mention` | A controlled founding phrase appears in a record. | EXIST `success_story`: `title`, `subtitle`, `summary`; University `news`/`press_release`: `title`, `summary`; GitHub `repository`: `repository.description`, `readme.text`; Hugging Face `model`/`dataset`/`space`: `description`, `card_text`. | Requires non-empty allowed text and a linked source signal/entity. Excludes simple negations such as “not founded”, “nicht gegründet”, “no founding”. Program pages and CORDIS project records are out of scope. | Weak mention; not founding proof. Positive: “company was founded …”. Negative: “not yet founded …”. `published_at` is publication time; `event_date` remains null. |
| `SPINOUT_MENTION` / `spinout-mention` | An explicit spin-off/spin-out or German Ausgründung phrase appears. | EXIST `success_story`: `title`, `subtitle`, `summary`; University `news`/`press_release`: `title`, `summary`. | Requires allowed text plus a linked source signal/entity. Excludes negated mentions and generic university affiliation/project participation. | Weak mention until verified. Positive: “university spin-out”. Negative: a paper author lists a university affiliation. `published_at` is publication time; no spin-out date is inferred. |
| `COMMERCIALIZATION_MENTION` / `commercialization-mention` | An explicit product/market launch or commercialization phrase appears. | EXIST `success_story`: `title`, `subtitle`, `summary`; University `news`/`press_release`: `title`, `summary`; GitHub `repository`: `repository.description`, `readme.text`; Hugging Face `model`/`dataset`/`space`: `description`, `card_text`. | Requires allowed text plus a linked source signal/entity. Excludes negated launch/sales phrases. A homepage, repo, model or demo alone is not enough. | Weak mention; no proof of sales, customers or revenue. Positive: “commercial launch”. Negative: “not yet on the market”. `published_at` is publication time; no market-entry date is inferred. |

Positive and negative examples above describe rule semantics, not results from
real stored records. These lexical rules may still produce false positives;
their matched field and term must remain inspectable.

## Persistence and idempotence contract

* Existing source signals remain unchanged. Classifying them does not create
  duplicate signals.
* Derived rows use the existing `Signal` model and `source_record_id`.
* The uniqueness constraint is
  `(entity_id, signal_type, source_record_id)`. The repository upserts on this
  constraint, retaining one row when a rule is re-run.
* `rule_id` and `rule_version` are stored in JSONB `properties`. If a matching
  rule version changes, the same derived signal row is updated rather than
  duplicated.
* The discovery repository reconciles only rows marked with known discovery
  rule IDs for the processed `(entity_id, source_record_id)`. If a rule no
  longer matches that record, its obsolete derived row is removed. Source
  signals are never deleted or rewritten by this reconciliation.
* The first release handles one source record at a time. Trend rules requiring
  multiple time-separated observations and multi-record evidence are deferred.
* No table or column changes are required. The `signals.signal_type` column is
  a string and `properties` is JSONB. Adding DB constraints later would require
  a separate schema decision and migration.
