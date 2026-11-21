# Pilot Knowledge Graph and Finance Handoff

## Scope and persistence

This is an additive, one-off curated import of short excerpts from public source pages. No automated collector, HF request, migration, DDL, LLM provider, or production collector was run. The database remained at Alembic revision `0001`; the only new source is `manual_pilot_research` (`SourceType.MANUAL`), not a registered collector.

The first successful run created 11 source records, 10 source-scoped entities, 24 aliases, 15 entity/source-record links, and 4 relationships. A second idempotent run added the Fraunhofer IOSB research-origin excerpt to the existing nodeline source record: 1 record was updated, 10 were unchanged, and 1 source-record revision was retained. The final pilot scope still contains 11 source records, 10 entities, and 4 relationships; no signals or observations were created. No existing entities or records were merged or deleted. Existing candidate/HTGF artifacts were verified unchanged.

| Table | Before | After |
|---|---:|---:|
| `sources` | 6 | 7 |
| `ingestion_runs` | 24 | 26 |
| `source_records` | 450 | 461 |
| `entities` | 2,374 | 2,384 |
| `entity_aliases` | 6,595 | 6,619 |
| `entity_source_records` | 2,608 | 2,623 |
| `relationships` | 2,804 | 2,808 |
| `signals` | 624 | 624 |
| `observations` | 800 | 800 |

Pilot company entity IDs:

| Company | Entity UUID |
|---|---|
| OnSite Solutions GmbH | `edfb4d6f-5e78-472e-885b-9d98e820c266` |
| nodeline GmbH | `273fb5d2-515d-4bad-a921-0a928611ece3` |
| Floronics | `fb0446b4-2ff7-47f2-9ef1-9eaa106a8fc3` |
| deepset GmbH | `da9cdb25-d6be-41a5-91c0-901eeecbf433` |

All four are stored as `organization`, not `startup`. Entity identity is source-scoped; matching names do not merge entities from different sources.

## Evidence and finance interpretation

- **OnSite:** Its official imprint confirms OnSite Solutions GmbH in Karlsruhe. KIT-FORGE describes BAIOSS and says the founding team is currently supported through the EXIST-Gründerstipendium. The amount and legal recipient are not stated; the support is not equity.
- **nodeline:** Its official imprint confirms nodeline GmbH; KIT-FORGE describes flowAI. The 21 August 2026 profile says a StartupSecure application had been submitted and the team was waiting for the decision. It does **not** document an award, contract, payment, amount, or company receipt. The previously circulated €798,682 is therefore not recorded as a nodeline grant.
- **Floronics:** Its own site describes a pre-launch deep-tech startup and the SIFcam product. The legal form “GmbH i.G.” was not confirmed by an official legal notice. The Future GreenTech Incubator page offers up to €300,000 non-dilutive funding to selected startups, but no source found confirms that Floronics applied, was selected, or received funds. The offer is recorded only as `program_offer`, not an award.
- **deepset:** Its official imprint confirms deepset GmbH in Berlin. TechCrunch reported a USD 30 million funding round announced in 2023, led by Balderton Capital with GV and Harpoon Ventures participating. The retrieved report does not establish the instrument or share terms, and no human review was supplied. The event is preserved as a reported round; the separate equity assessment remains `equity_status_unclear`. No “pre-first-round” classification is assigned.

The finance export contains four events: an EXIST founder-stipend participation, a pending StartupSecure application, the general Future GreenTech program offer, and deepset’s reported round. It also contains one unverified deepset equity finding. All four assessments remain `equity_status_unclear`: there is no human-reviewed finding or complete reviewed search coverage. No reviewer, evidence, document, or external identifier was fabricated.

Finance events and equity assessments are **not persisted in Neon tables**. They are supplemental, reproducible JSON based on the saved source records, not SQL-queryable finance facts. The schema has no Candidate or finance-event table. Do not interpret absence of an edge or signal as evidence that no funding occurred.

## Exports

- [`pilot_finance.json`](../data/exports/pilot_finance.json) — finance events, evidence extracts, source-record IDs, unverified findings, and assessments.
- [`knowledge_graph_pilot.json`](../data/exports/knowledge_graph_pilot.json) — database-read entities, relationships, signals, observations, and source records.

The graph export contains four `DEVELOPED` edges (company to product/technology). KIT/Fraunhofer research origins and other program support remain visible in source excerpts; no edge was created where the current relationship enum would imply an unsupported current collaboration, spin-off, award, or program participation. Program pages are represented as their own source-scoped nodes, without a candidate edge. No signal type accurately represented the pending application or general offer without overstating them, so no pilot signals were added.

## Read-only SQL examples

Run these against the authorized Neon database using a read-only connection. They were executed after the import. The source name scopes the examples to this pilot.

### 1. Pilot organizations and linked source records

Returns four organizations and nine company-linked source records.

```sql
SELECT e.canonical_name,
       e.id AS entity_id,
       array_agg(DISTINCT sr.canonical_url ORDER BY sr.canonical_url) AS source_urls,
       count(DISTINCT sr.id) AS source_record_count
FROM public.entities AS e
JOIN public.entity_aliases AS a ON a.entity_id = e.id
JOIN public.sources AS s ON s.id = a.source_id
JOIN public.entity_source_records AS es ON es.entity_id = e.id
JOIN public.source_records AS sr ON sr.id = es.source_record_id
WHERE s.source_name = 'manual_pilot_research'
  AND a.alias_type = 'source_identifier'
  AND a.external_identifier LIKE 'organization:%'
GROUP BY e.id, e.canonical_name
ORDER BY e.canonical_name;
```

### 2. Persisted company/product relationships

Returns the four source-asserted `DEVELOPED` relationships. It does not imply a verified research spin-off or current collaboration.

```sql
SELECT source_entity.canonical_name AS source_entity,
       r.relationship_type,
       target_entity.canonical_name AS target_entity,
       r.verification_status,
       sr.canonical_url
FROM public.relationships AS r
JOIN public.entities AS source_entity ON source_entity.id = r.source_entity_id
JOIN public.entities AS target_entity ON target_entity.id = r.target_entity_id
JOIN public.source_records AS sr ON sr.id = r.source_record_id
JOIN public.sources AS s ON s.id = sr.source_id
WHERE s.source_name = 'manual_pilot_research'
ORDER BY source_entity.canonical_name;
```

### 3. Grant-related excerpts attached to pilot organizations

This is a text-evidence lookup, **not** a query for awarded or paid grants. It returns the EXIST and StartupSecure excerpts; inspect event scope/status in the finance JSON.

```sql
SELECT e.canonical_name,
       sr.canonical_url,
       q ->> 'quote' AS excerpt
FROM public.entities AS e
JOIN public.entity_source_records AS es ON es.entity_id = e.id
JOIN public.source_records AS sr ON sr.id = es.source_record_id
JOIN public.sources AS s ON s.id = sr.source_id
CROSS JOIN LATERAL jsonb_array_elements(sr.raw_payload -> 'evidence') AS q
WHERE s.source_name = 'manual_pilot_research'
  AND e.id IN (
      SELECT a.entity_id
      FROM public.entity_aliases AS a
      JOIN public.sources AS pilot_source ON pilot_source.id = a.source_id
      WHERE pilot_source.source_name = 'manual_pilot_research'
        AND a.external_identifier LIKE 'organization:%'
  )
  AND ((q ->> 'quote') ILIKE '%EXIST%'
       OR (q ->> 'quote') ILIKE '%Förderantrag%')
ORDER BY e.canonical_name;
```

### 4. deepset's reported funding-round excerpt

Returns one TechCrunch excerpt. A news report is not, by itself, the manually reviewed equity confirmation required by the finance rules.

```sql
SELECT e.canonical_name,
       sr.canonical_url,
       q ->> 'quote' AS excerpt
FROM public.entities AS e
JOIN public.entity_source_records AS es ON es.entity_id = e.id
JOIN public.source_records AS sr ON sr.id = es.source_record_id
CROSS JOIN LATERAL jsonb_array_elements(sr.raw_payload -> 'evidence') AS q
WHERE e.canonical_name = 'deepset GmbH'
  AND sr.canonical_url LIKE 'https://techcrunch.com/%'
  AND (q ->> 'quote') ILIKE '%$30 million%';
```

### 5–7. Signals, observations, and pilot record count

Queries 5 and 6 return zero rows; query 7 returns 11 source records.

```sql
-- 5. No pilot signals were created.
SELECT e.canonical_name, x.signal_type, sr.canonical_url
FROM public.signals AS x
JOIN public.entities AS e ON e.id = x.entity_id
JOIN public.source_records AS sr ON sr.id = x.source_record_id
JOIN public.sources AS s ON s.id = sr.source_id
WHERE s.source_name = 'manual_pilot_research';

-- 6. No pilot observations were created.
SELECT e.canonical_name, o.metric_name, o.metric_value, o.observed_at
FROM public.observations AS o
JOIN public.entities AS e ON e.id = o.entity_id
JOIN public.source_records AS sr ON sr.id = o.source_record_id
JOIN public.sources AS s ON s.id = sr.source_id
WHERE s.source_name = 'manual_pilot_research';

-- 7. Count pilot source records.
SELECT s.source_name, count(*) AS record_count
FROM public.source_records AS sr
JOIN public.sources AS s ON s.id = sr.source_id
WHERE s.source_name = 'manual_pilot_research'
GROUP BY s.source_name;
```

There is deliberately no SQL query for “confirmed equity events” or “unclear equity candidates”: those facts are not persisted in the current schema. Read those assessments from `pilot_finance.json`; do not infer them from `FUNDED_BY`, grant records, or text-search results.
