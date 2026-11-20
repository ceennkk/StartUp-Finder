# Phase 2B.4 – LLM source and field allowlist

External LLM processing is disabled by default. The checked-in
`app/config/llm_allowlist.yaml` contains an empty source map and a deny-by-default
policy. There are currently no approved sources or fields.

An eventual source entry must document its field paths, affirmative approval,
purpose, review date, reviewer, terms reference, and a concise review summary.
This is an operational record of review, not legal advice or a substitute for
checking current rights and data-processing terms. Approval is source- and
field-specific; enabling general LLM functionality cannot widen it.

The following is an inventory for future review, not approval:

| Adapter/source scope | Candidate fields to review | Current status |
|---|---|---|
| OpenAlex | `title`, `display_name`, `publication_date`, `primary_topic.display_name`, `topics[].display_name`, `keywords[].display_name`, abstract text | Blocked |
| arXiv | `title`, `categories[]`, `primary_category`, `journal_ref`, `comment`, `summary` | Blocked |
| GitHub | `repository.description`, `repository.topics[]`, `repository.language`, README text | Blocked |
| Hugging Face | selected model/dataset/space description or card text | Blocked |
| EXIST | `title`, `subtitle`, `summary`, `programs_mentioned[]`; program page `title` and `description` | Blocked |
| UniversityAdapter | per configured feed, such as `university:ude_forschung`: `title`, permitted teaser/summary and selected tags | Blocked |
| CORDIS | `title`, `abstract`, project status and date fields | Blocked |
| ManualImportAdapter | No fields | Permanently blocked in Phase 2B.4 |

Authors, affiliations, contributors, handles, personal names, and other
unnecessary personal data are excluded. Permission to collect a record does not
imply permission to send it to an external provider. Unclear commercial,
copyright, privacy, transfer, or retention terms mean denial.

The curated-input builder includes only explicitly listed present fields.
The content hash is calculated from the canonical representation of the exact
source scope, record type, and field values selected for the provider. Original
records are not modified.

## Runtime and persistence safeguards

The checked-in production allowlist has no entries and there is no CLI or
environment-variable override. The allowlist builder always loads that
configuration. Tests inject approvals only by monkeypatching the loader with
in-memory entries named `synthetic_*`; those entries select synthetic fixture
data and cannot approve a real adapter's source scope.

The provider interface is provider-neutral, but the only implementation is a
local fake. It performs no I/O and is restricted by the runner to synthetic
source names. Real adapter records are therefore blocked even if an operator
later adds an allowlist entry until a real provider receives a separate
approval and is implemented.

The analyzer returns a strict Pydantic schema with research, technology,
developer activity, founding, spin-out, commercialization, and startup activity
categories; optional founding/spin-out/commercialization mention types;
technology and application areas; product/founding/commercialization hints;
signal strength; uncertainties; and short evidence quotes with field paths.
Each evidence path must be a curated input field, and each quote must occur
verbatim in that field. The output does not resolve entities, assert startup
status, assess funding, or calculate a score.

Use `ventureradar llm preview` for a read-only eligibility preview and
`ventureradar llm run` only for an explicitly requested persistent run. Neither
command prints source text or URLs. With the current empty allowlist, real
records are blocked and no analysis rows are created. The fake provider can
persist only synthetic fixture analysis.

`llm_analyses` stores only schema-validated JSONB results, input hash, source
record reference, analyzer/prompt/schema/provider/model versions, validation
status, token usage, and timestamp. Successful identities are protected by a
partial unique index and are not overwritten; failed/invalid attempts have no
result JSON and are recorded separately using safe error codes. Migration
`0002` is included as a migration file. The repository's DB-test fixture drops
and recreates the `public` schema before applying migrations; only run DB-marked
tests after confirming `TEST_DATABASE_URL` points to a disposable database.
Phase 2B.4 does not invoke migrations against configured application databases.

Phase 2B.4 has no real provider implementation and makes no external LLM
requests. Manual import cannot be enabled. Current licensing, privacy, terms,
and provider questions remain unresolved for every real source and must be
reviewed before any future external provider is allowed.
