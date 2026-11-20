# HTGF Eligibility Assessment

This independent offline component evaluates the three supplied HTGF questions.
It is a sourcing aid, not an HTGF investment or funding decision. It does not
perform online research, call an LLM, open a database connection or infer the
funding status.

## Files and commands

- `data/candidates/htgf_input.json`: manually curated, versioned assessment inputs.
- `data/candidates/htgf_assessments.json`: append-only history keyed by candidate ID.
- `data/candidates/htgf_overview.csv`: filterable latest HTGF and funding results.
- `data/candidates/htgf_research_report.md`: sources, findings and open questions.

Run from the repository root with `python -m app.htgf` or, in an installed project,
`python -m app.cli htgf run`. Each path can be overridden with `--input`,
`--discovery`, `--validation`, `--history`, `--csv`, and `--report`. Input files
and the original discovery, validation, CSV and report names are protected from
output overwrites. The original discovery and validation data are read only.

## Evidence and input contract

Each input candidate has `candidate_id`, `name`, `assessment_date` and three
sections: `technology`, `company_age`, and `germany`. Each section contains
`rationale`, `evidence`, `uncertainties`, and `contradictions`. Every evidence
item provides `title`, HTTP(S) `url`, `publisher`, `source_type`, `claim`,
`published_at` (date or null), `accessed_on`, `reliability`, and a
`contradictions` list. The input date may not precede the cited publication or
access date. A human must verify that each cited claim actually supports the
particular criterion and legal entity; this module does not read source URLs.

Technology inputs keep `tech_startup_status` separate from the `fields` list.
Multiple relevant fields are possible; `outside_scope` and `unclear` are
exclusive values. A positive tech-startup finding also requires nonempty
`product`, `technology`, `business_model` and `business_field` descriptions.
Labels without relevant evidence, unresolved uncertainties, low-quality sources,
or unresolved contradictions cannot establish eligibility.

Company age requires `registration_status`, the uniquely identified
`legal_entity_name`, `incorporation_date`, `registration_country`,
`registry_name`, optionally `registry_id`, and a high-reliability official
registry source. Three years expire on the third calendar anniversary, inclusive;
a February 29 registration has a February 28 anniversary in non-leap years.
Founding years, project start dates and programme dates are not substitutes.
An unsupported or future registration date remains unclear.

The Germany section accepts `registered_seat_in_germany`,
`relocation_to_germany_planned`, `german_permanent_establishment_planned`,
`no_germany_connection`, or `unclear`. A planned move or establishment needs
`concrete_plan: true` and a high-reliability official company or independent
media source. University or founder location does not establish a registered seat.
For a Germany determination, `legal_entity_name` identifies the same legal entity
as in the age section when that identity is known.
For a pre-company result, the age section must explicitly document both a
concrete venture and the absence of an already registered company with reliable
evidence; missing register data alone is never sufficient.

## History and safety

Each assessment stores its exact curated input, candidate-source fingerprints,
schema version, deterministic assessment ID and UTC execution time. Identical
inputs and source snapshots are idempotent; changed inputs append a new version.
An exclusive sidecar `.lock` serializes writers and remains present for later
writers. A temporary file in the same directory is flushed and atomically
replaced, leaving the previous history intact on write failure. Old entries are
not modified. Never delete or replace the lock file while writers are running.
Exports reload the history under the same lock so concurrent runs cannot
publish older views after newer history. CSV and report are independently
atomically written views; rerun the command if an export fails after history
was saved.

The current eight assessments use only the already stored and cited EXIST
research-to-company summaries. Technology mappings are provisional because
current commercial and business-model details have not been independently
verified; official register entries and Germany-presence evidence are missing.
No current web check is implied by the assessment date.

## Isolated tests

`python -m unittest discover -s tests\\htgf -t .` runs only HTGF unit and
local-process tests without opening a database connection. When using pytest,
run only `tests/htgf` and do not request the database fixtures.
