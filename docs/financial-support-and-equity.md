# Financial support and external equity: offline domain foundation

`app.finance` defines versioned Pydantic models and a deterministic assessment
function. It does not open a database, call a provider, fetch sources, persist
data, change candidate results, or modify the HTGF assessment. It is not a
financial, legal or investment decision.

## Financial support

`FinancialSupportEvent` describes one curated event with a `candidate_id` and
its own `event_id`. Its category includes grants, stipends, research funding,
prizes, equity, angel/VC investments, loans, convertibles, in-kind support,
other and unknown. Applicant, legal recipient, beneficiary and funder are
independent optional values; none is inferred from another.

Amounts use `Decimal`, an uppercase three-letter currency and an explicit
qualifier (`exact`, `up_to`, or `approximate`). Statuses are independent
reported facts, not an automatically advanced lifecycle: announcement does not
imply approval; approval does not imply payment. `program_offer` and
`program_participation` cannot claim individual approval, contract or payment.
Repayability and dilution each default to unknown. Sources of financial support
and confirmed equity are independent; an event category is never enough to
produce an equity finding.

Each event carries `Provenance`: existing `Source`, `Document`, `ClaimExtraction`,
`Claim` and `Evidence` models. Validation checks candidate identity, source and
document references, field paths and exact quotes using the existing evidence
validator. Dates and amounts are validated. A valid quote does **not** establish
that a source is reliable or that every entered event field follows from it.
Human curators must separately verify the meaning, entity, role, amount,
instrument, terms and status against the underlying source. Hypotheses and
unresolved claims must not be presented as confirmed facts. In particular,
program ceilings are not individual awards and program participation does not
establish disbursement.

## Independent equity assessment

`assess_equity` takes separate curated `EquityFinding` inputs and optional
financial events and search coverage:

- `equity_confirmed`: an explicit external-equity fact candidate, a non-unclear
  stage, and a recorded human verification without unresolved conflicts or
  uncertainties. The result retains `completed` versus `binding_agreement`;
  a binding agreement is not a completed round. A reviewer must establish
  actual external ownership or a binding agreement from the evidence.
- `no_public_equity_round_found`: no equity finding, all four declared source
  families (company, registry, investor and independent media), at least four
  distinct source IDs, searches completed on the assessment date with no
  public equity found, no open questions, a same-day human review, and all
  supplied event IDs explicitly reviewed. This is a point-in-time search
  result, **not** proof that private investments do not exist.
- `equity_status_unclear`: all other cases, including no evidence, an
  unverified finding, inaccessible sources, incomplete coverage or unresolved
  questions.

Coverage records include source, queries, date, outcome and notes. This
conservative initial gate requires same-day searches; the four families are a
minimum structural contract, not proof that the search is exhaustive. Reviewers
must verify identity, scope, source independence, all relevant instruments,
access restrictions, and search quality. All relevant events and findings must
be supplied. A caller could omit data, mislabel sources, or falsely claim human
review: these local models do not authenticate reviewers or independently
research facts. Do not equate this status with the legacy `funding_status`.

SAFE and convertible notes remain `convertible_instrument` events. They are
neither normal loans nor completed equity by default; an independently
documented acquisition or binding agreement needs its own equity finding.
Investor, supporter or partner labels and logos are not evidence of share
ownership. LLM claims are candidates only; a recorded human review is required
for a confirmed finding or a negative search assessment. The existing
deny-by-default LLM policy and provider authorization remain untouched.

## Isolated tests and future storage

Run `python -m unittest discover -s tests\\finance -t .` without DB fixtures or
network access. The named company examples are illustrative, partial research
inputs, not persisted or independently re-verified financing records.

No schema or persistence is added in this phase. Later Neon integration would
need separate approval for a schema design and migration: versioned event and
assessment identities, entity/recipient roles, immutable document snapshots,
many-to-many evidence and claims, coverage and authenticated review history,
deduplication and idempotent transactions. Existing JSONB and generic
`FUNDED_BY` edges alone do not guarantee these invariants.
