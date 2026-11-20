# Candidate Discovery and Validation Report

Validation date: 2026-11-20.

## Executive summary

The point-in-time analysis selected **8 candidates** from the stored data. All eight are company-confirmed, research- or technology-based startups. Five have a publicly reported equity funding round; three have funding status `funding_unclear`. No candidate is labeled `no_public_round_found` or `grant_only_no_public_round_found`, because the minimum evidence threshold for asserting absence was not met.

The shortlist is intentionally smaller than 30. The database produced only one clearly relevant, named candidate record per company, all from EXIST; it did not provide independent database corroboration across sources.

## Snapshot and safeguards

- Database/schema: `neondb.public`; transaction mode: `on`.
- Snapshot: `2026-11-20T20:41:23.57222+00:00` (UTC; `REPEATABLE READ`).
- Active ingestion at snapshot: OpenAlex run `d50845c0-2f3a-4512-bc9d-55b59dacf218` started `2026-11-20T20:28:15.203251+00:00`; the report reflects the single committed snapshot, not later ingestion changes.
- Alembic: database `0001`; local migration head `0002`. No migration was run.
- No database writes, schema changes, collectors or external LLMs were used. Only selected fields were exported; full raw payloads were not copied.

## A. Candidate discovery

Snapshot totals: **211 source records**, **1289 entities**, **244 signals**, **1528 relationships**, and **195 observations**.

Source records:
- arxiv: 77
- cordis: 17
- exist: 12
- github: 20
- openalex: 55
- university: 30

Selection rule: a named EXIST success story had to link a concrete technology or science-based product with a research-to-company transition. Projects or papers without a named company/explicit commercial pathway, and standalone repositories, were not promoted. EXIST and other public grants are not equity financing.

Rule-based priority score (0-10): technology specificity (0-3), research-transfer evidence (0-2), commercialization evidence in the stored record (0-2), independent database sources (0-2), and recency within 12 months (0-1). Every shortlisted company has only one database source, so the multi-source component is zero. The score prioritizes research follow-up only; it is not an investment rating and does not imply an unfunded status.

**Independent database evidence:** 0 of 8 candidates have more than one independent database source.

### Ranked shortlist

| Rank | Candidate | Technology area | Score | Company status | Funding status |
|---:|---|---|---:|---|---|
| 1 | Additive Drives | Electric motors and additive manufacturing | 8/10 | `company_confirmed` | `funding_unclear` |
| 2 | Tentris | Graph databases and enterprise AI infrastructure | 8/10 | `company_confirmed` | `funding_round_confirmed` |
| 3 | Porelio | Advanced materials, water treatment and resource recovery | 8/10 | `company_confirmed` | `funding_round_confirmed` |
| 4 | Co-reactive | Climate tech and construction materials | 8/10 | `company_confirmed` | `funding_round_confirmed` |
| 5 | INLEAP Photonics | Photonics and counter-drone systems | 8/10 | `company_confirmed` | `funding_round_confirmed` |
| 6 | Prime Vector Technologies | Biotechnology, vaccines and immunotherapy | 7/10 | `company_confirmed` | `funding_unclear` |
| 7 | Noxon | Neurotechnology and medical devices | 7/10 | `company_confirmed` | `funding_round_confirmed` |
| 8 | AutonomIQ | Industrial AI and manufacturing software | 7/10 | `company_confirmed` | `funding_unclear` |

### Candidate notes

#### 1. Additive Drives
High-performance, lightweight electric motors and control electronics using proprietary 3D-printing and conventional manufacturing processes. **Discovery evidence:** [EXIST story](https://exist.de/success-stories/additive-drives/) (database record `851e8e02-5528-4953-9c35-a80570ea920e`, published 2026-08-06). **Status:** `company_confirmed` / `funding_unclear`. **Priority:** 8/10. **Uncertainty:** The early-2026 financing type, currency, amount and participating investors are not reported in detail.; A company website URL was not confirmed from an accessible source during this review.
- Funding evidence: The EXIST story reports a mid-double-digit-million financing in early 2026 without stating currency, instrument, stage or investors. AM Ventures confirms an investor relationship dating to October 2020, but its page does not establish a specific round. No round terms are asserted.
- Public support (separate from equity): EXIST-Forschungstransfer.

#### 2. Tentris
University of Paderborn spinout developing a graph database for connected enterprise data and AI applications. **Discovery evidence:** [EXIST story](https://exist.de/success-stories/tentris/) (database record `9dc6c932-7248-44e1-91ad-453d80efc877`, published 2026-07-22). **Status:** `company_confirmed` / `funding_round_confirmed`. **Priority:** 8/10. **Uncertainty:** The exact public announcement date and final round amount are not consistent across the reviewed sources.
- Public round: Pre-seed, EUR 2 million (Tech Funding News) / over EUR 2 million (EXIST); announced date not established; lead Bloomhaus Ventures.
- Public support (separate from equity): EXIST-Forschungstransfer.

#### 3. Porelio
Highly porous silicate materials designed for selective PFAS removal and recovery of valuable metals from industrial process streams. **Discovery evidence:** [EXIST story](https://exist.de/success-stories/porelio/) (database record `9a578db1-20ee-484a-a932-cb8dcbacabdd`, published 2026-07-08). **Status:** `company_confirmed` / `funding_round_confirmed`. **Priority:** 8/10. **Uncertainty:** The founding date and the programs/instruments behind the approximately EUR 2.5 million prior public funding were not established.
- Public round: Pre-seed, EUR 2.4 million; announced 2026-07-07; lead Faber.
- Public support (separate from equity): EXIST-Forschungstransfer; Other public funding (program not specified) — approximately EUR 2.5 million.

#### 4. Co-reactive
Continuous CO2 mineralization process converts captured CO2 and silicate or metallurgical slags into CO2-negative supplementary cementitious materials. **Discovery evidence:** [EXIST story](https://exist.de/success-stories/co-reactive/) (database record `e922a098-460b-4dd4-a22d-bccbea336651`, published 2026-06-17). **Status:** `company_confirmed` / `funding_round_confirmed`. **Priority:** 8/10. **Uncertainty:** The exact BIK grant amount is not stated in the reviewed announcement.
- Public round: Seed, EUR 6.5 million; announced 2026-01-28; lead High-Tech Gründerfonds.
- Public support (separate from equity): EXIST-Forschungstransfer; Federal Funding for Industry and Climate (BIK) — seven-figure amount; exact amount not stated.

#### 5. INLEAP Photonics
Eye-safe, high-precision laser systems for counter-drone defense and critical-infrastructure protection, adapted from industrial beam-steering technology. **Discovery evidence:** [EXIST story](https://exist.de/success-stories/inleap-photonics/) (database record `1ed0f629-c345-4b4b-abb6-ed660cfaa7e1`, published 2026-06-14). **Status:** `company_confirmed` / `funding_round_confirmed`. **Priority:** 8/10. **Uncertainty:** The amount and investor list are based on a secondary funding-news report; independently obtained term documents were not available.
- Public round: Seed, approximately EUR 20 million; announced 2026-09-02; lead UVC Partners.
- Public support (separate from equity): EXIST-Forschungstransfer.

#### 6. Prime Vector Technologies
Orf-virus-based viral-vector platform for vaccines and immunotherapies for human and veterinary applications. **Discovery evidence:** [EXIST story](https://exist.de/success-stories/prime-vector-technologies/) (database record `3cb3514f-2c61-4a96-8e16-a15cec710ecb`, published 2026-08-06). **Status:** `company_confirmed` / `funding_unclear`. **Priority:** 7/10. **Uncertainty:** No completed equity round was verified, but a sufficiently broad independent funding search was not possible.; Company website was inaccessible during review.
- Funding evidence: The official EXIST story documents EXIST support and a Boehringer Ingelheim collaboration, but does not confirm equity financing. A collaboration is not treated as an investment. The company site returned HTTP 403 during review; no absence-of-funding claim is made.
- Public support (separate from equity): EXIST-Forschungstransfer.

#### 7. Noxon
Wearable muscle-computer interface combining muscle diagnostics and neuromuscular stimulation for therapy and movement training. **Discovery evidence:** [EXIST story](https://exist.de/success-stories/noxon/) (database record `9e38997a-a000-46a5-974a-004685615620`, published 2026-06-14). **Status:** `company_confirmed` / `funding_round_confirmed`. **Priority:** 7/10. **Uncertainty:** The exact size of the seed round is not public in the sources reviewed.
- Public round: Seed, multi-million euro; exact amount not disclosed; announced 2026-03-02; lead High-Tech Gründerfonds.
- Public support (separate from equity): EXIST-Gründungsstipendium.

#### 8. AutonomIQ
AI software originating in TU Darmstadt research on autonomous machine tools; automates complex manufacturing-planning workflows. **Discovery evidence:** [EXIST story](https://exist.de/success-stories/autonomiq/) (database record `529afe27-d8dc-4b7d-9a2f-2f06f23e7878`, published 2026-06-14). **Status:** `company_confirmed` / `funding_unclear`. **Priority:** 7/10. **Uncertainty:** No completed funding round is confirmed; the official EXIST profile says fundraising is being prepared.; The LAUNCH Rhein-Main profile has inconsistent founding-date fields.
- Funding evidence: The official EXIST story says a funding round is currently being prepared. No completed round is confirmed in the sources reviewed; this is not evidence that no private financing exists.
- Public support (separate from equity): EXIST-Forschungstransfer.

## B. Candidate validation

- Companies confirmed: 8.
- Pre-company projects: 0.
- Funding rounds confirmed: 5.
- `no_public_round_found`: 0.
- `grant_only_no_public_round_found`: 0.
- Funding unclear: 3.
- `not_applicable`: 0.

Confirmed public round evidence is present for INLEAP Photonics, Noxon, Co-reactive, Porelio and Tentris. Additive Drives has a public financing mention and a public investor relationship, but the type and terms of the reported early-2026 financing are not described sufficiently to classify it as an equity round. AutonomIQ is reported to be preparing a round; preparation is not a completed round. Prime Vector’s EXIST profile documents a collaboration with Boehringer Ingelheim, not investment.

For Porelio, public funding of approximately EUR 2.5 million is reported separately from its EUR 2.4 million pre-seed round; the program/instrument is not identified. Co-reactive’s seven-figure BIK grant and EXIST support are separate from its EUR 6.5 million seed. Tentris’s sources use “EUR 2 million” and “over EUR 2 million”; the discrepancy is preserved.

## C. Methodological limits

- All shortlisted discoveries come from EXIST success stories and have no second independent source record linked in the database.
- The snapshot contains records only for arXiv, CORDIS, EXIST, GitHub, OpenAlex and university sources; no Hugging Face records were present.
- The 17 CORDIS projects and general university news records do not name a matched startup or provide an explicit spinout link in the stored relationships. The 20 GitHub repositories and publications are not enough individually to infer a company.
- The OpenAlex ingestion was marked running. Repeatable-read produces a consistent committed snapshot, but rows from its uncommitted work are naturally not visible.
- Database migration version 0001 is behind local revision 0002. Analysis used only tables/columns that were present and queried successfully; no schema update was attempted.
- Public search and accessible sources cannot rule out private angels, undisclosed convertibles, debt or non-public rounds. Paid databases were not accessed, and commercial-register verification was not performed for every candidate.
- The Prime Vector Technologies company site linked by EXIST returned HTTP 403; its identity is supported by the official EXIST story, but the linked site could not be inspected.

## D. Recommendations

1. Keep the candidate shortlist separate from funding eligibility; do not present any `funding_unclear` company as unfunded.
2. Add explicit cross-source organization identifiers (company register IDs, verified domains) and traceable organization-to-project relationships; do not merge on name alone.
3. Store funding claims as sourced events with instrument type (equity, grant, debt, convertible), round stage, date, investors, amount/currency, and confidence.
4. For `no_public_round_found`, store a reproducible search log showing official company news, investor portfolios and multiple independent media/database sources checked, with access dates.
5. Re-run discovery after OpenAlex ingestion completion and when EXIST/university records add linked entity/relationship data; preserve a new snapshot timestamp rather than mixing snapshots.

Detailed source references and per-candidate provenance are in `candidate_discovery.json` and `candidate_validation.json`.
