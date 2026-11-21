# Frontend-Vertrag · v2

Basis: `http://localhost:8000/api`. JSON. Listen: `{items: [...], total: number}`.
Details direkt als Objekt, Jobs als `{job: {...}}`, Fehler als `{detail: string}`.
Alle Zeitangaben ISO 8601 mit Zeitzone. Leere/unbekannte Fakten bleiben leer.

Bei Loopback-Bindung (`127.0.0.1`/`localhost`) ist kein API-Token nötig; bei
Netzwerkbindung verlangt das Backend `Authorization: Bearer <API_TOKEN>` für alle
API-Routen. Modellschlüssel bleiben serverseitig im Backend und Worker. CORS_ORIGINS enthält die erlaubten
Frontend-Origins. Ein Team-Token ersetzt kein späteres Benutzer-/Mandanten-Rechtesystem. Das Frontend
zeigt Produktdaten nur, wenn `/capabilities` `mode: "live"` meldet.

## Endpunkte

| Methode | Route | Request / Ergebnis |
|---|---|---|
| GET | /health | DB-Status, Modus `live`, Worker-Zeitstempel. Modell/Graph: `not_probed` |
| GET | /capabilities | Modus `live`, Adapter, Funktionsumfang und Grenzen |
| GET / POST | /sources | Liste / `{name,url,kind:html\|rss\|manual}` |
| GET / PATCH | /sources/{id} | Quelle / `{enabled:boolean}` |
| GET / POST | /findings | Liste / `{source_id,url,title,text,external_id?,published_at?,fetched_at?}` |
| GET | /findings/{id} | Originaltext, Quellenmetadaten, Verarbeitungsstatus |
| POST | /findings/{id}/process | `{}` → 202 + Job |
| GET | /candidates | Filter: q, status, germany_status, priority |
| GET | /candidates/{id} | Profil + evidence, assessment, notes, research_runs, current eligibility snapshot |
| GET | /candidates/{id}/eligibility | Current eligibility snapshot and append-only history |
| POST | /candidates/{id}/eligibility | Save evidence-backed eligibility review and queue a new assessment |
| PATCH | /candidates/{id} | `{status:new\|shortlisted\|rejected}` |
| POST | /candidates/{id}/notes | `{text}` → gespeicherte Notiz |
| GET | /candidates/{id}/finance | Aktueller Finanzierungsstand plus unveränderliche Prüfungshistorie |
| POST | /candidates/{id}/finance | Finanzierungs-Snapshot `{as_of,events,findings,coverage?}` → 202 + neuem Bewertungsjob; identische Snapshots → 200 |
| POST | /candidates/{id}/research | `{}` → 202 + Job |
| POST | /candidates/{id}/evaluate | `{}` → 202 + Job |
| GET | /jobs | Filter: kind, status |
| GET | /jobs/{id} | Jobstatus, Fehler, Ergebnis |
| POST | /jobs/{id}/retry | Nur failed → queued; 202 + Job |
| GET / POST | /searches | Liste / `{prompt,source_ids?:string[],interval_minutes?:number\|null}` |
| GET | /searches/{id} | Auftrag inkl. letzter Fundstellen und Job-ID |
| POST | /searches/{id}/run | `{}` → 202 + Job |
| GET | /graph | `{nodes,edges,mode,is_materialized_view:true}` |
| POST | /chat | `{question,language:en\|de,history?:[{role:user\|assistant,content}],candidate_id?:string}` → `{answer,citations:[{id,kind,title,quote,url,candidate_id}]}` |
| GET | /events | Ereignisse; Filter entity_id |

Alle Listen: `limit` 1–200 (Standard 50), `offset` >= 0. Fundstellen zusätzlich
`source_id`, `status`, `q`. HTTP: 201 erzeugt, 202 Job, 401 Token fehlt,
404 unbekannte ID/Route, 413 Body zu groß, 422 Eingabe ungültig, 500 intern.
`/chat` nutzt serverseitiges OpenAI-Tool-Calling. Das Modell kann
`search_knowledge_graph` (Graphiti → Neo4j) und `search_candidate_profiles`
(Kandidatenprofile, Bewertungen und Originalbelege aus PostgreSQL) aufrufen.
Die Tools liefern gespeicherte Fakten; Quellen-IDs der finalen Antwort werden
serverseitig validiert. Der API-Key bleibt im Backend. 503 bedeutet, dass ein
Daten- oder Modell-Tool nicht verfügbar war. Maximal 8 Konversationsturns und
1.200 Zeichen pro Nachricht.

## Kandidat

```typescript
interface Candidate {
  id: string;
  graph_node_id: string;
  name: string;
  description: string;
  website: string;
  location: string;
  germany_status: 'confirmed' | 'likely' | 'unknown' | 'outside_germany';
  entity_type: 'venture';
  people: string[];
  signals: {id:string; kind:string; label:string; evidence_id:string;
            date:string|null; verification?:string}[];
  open_questions: string[];
  status: 'new' | 'shortlisted' | 'rejected';
  profile_version: number;
  finding_ids: string[];
  created_at: string;
  updated_at: string;
  conflicts?: {field:string; previous:string; incoming:string; finding_id:string}[];
}
```

Listen ergänzen `assessment`, `assessment_stale`, `assessment_current` und
`assessment_rankable`. Detail ergänzt:

- `evidence`: id, candidate_id, finding_id, episode_id, url, title, quote,
  kind (`exact_quote` oder `source_excerpt`), attribution, published_at, fetched_at,
  created_at.
- `notes`: id, candidate_id, text, created_at.
- `research_runs`: id, candidate_id, summary, sources, imported_finding_ids,
  fetch_errors, created_at.
- `finance`: current versioned finance snapshot, with events, equity findings,
  search coverage, human-review attribution, and deterministic equity assessment.
- Candidate financing fields: `funding_status` (`confirmed|not_found|unclear`),
  `funding_type` (`dilutive|non_dilutive|mixed|unclear|not_applicable`), and
  `funding_evidence_ids`. Research claims include `funding_nature`; verified
  source quotes classify reported funding but do not confirm external equity
  or change the score. The finance-domain assessment is separate and curated;
  write complete snapshots through `/candidates/{id}/finance`. These records
  are validated and appended to PostgreSQL, then a new assessment is queued.
- `eligibility`: latest evidence-backed review of Germany connection, technology
  sector, and commercial-register age. Reviews are append-only. The write payload
  contains `assessment_date`, `technology`, `company_age`, `germany`, and `reviewer`;
  criterion evidence retains its source URL, publisher, claim and reliability.
- `assessment`: null oder gespeicherte Bewertung.

`source_excerpt` ist ein Dokumentausschnitt, keine verifizierte Textspanne für
jede Profilaussage. Extrahierte deutsche Länderangaben ergeben zunächst `likely`.
Widersprüche bleiben in `conflicts`; sie werden nicht still überschrieben.

## Bewertung

Felder: id, candidate_id, score (0–100 oder null), criteria_score (0–100 oder null),
funding_status, funding_type, equity_status, funding_adjustment, funding_effect, scored_criteria (0–4),
priority (`high|medium|low|insufficient_data`), summary,
strengths[], concerns[], open_questions[], evidence_ids[], criteria[], model,
profile_version, criteria_version, created_at, profile_snapshot.

Kriterium: key, label, rating (`strong|moderate|weak|unknown`), rationale,
evidence_ids[]. Kriterien: founding_intent, technical_substance, customer_problem,
demand. Alle vier Kriterien sind gleich gewichtet: `strong`=100, `moderate`=67,
`weak`=33. `criteria_score` ist der Mittelwert der belegten Kriterien. Für den
immer sichtbaren Gesamtscore erhalten unbekannte Kriterien einen neutralen Wert
von 50. `scored_criteria`, `score_confidence` (`high|medium|low`) und
`score_provisional` zeigen die Belegabdeckung. `high` beginnt bei 75, `medium`
bei 50, darunter `low`.
`equity_status: equity_confirmed` aus der getrennten Finanzierungsbewertung oder
`funding_status: confirmed` zusammen mit `funding_type: dilutive|mixed` setzt den
finalen Score auf 0 und die Priorität auf `low`. Die erste Regel setzt einen
manuell geprüften externen Equity-Beleg voraus; die zweite braucht eine
bestätigte, im Originaltext zitierte private/verwässernde Finanzierungsrunde.
Unklare Finanzierung begrenzt den Score nicht. Zuschüsse, Stipendien,
Forschungsgelder und Preise gelten nicht als Equity; ihr Dilution-Status wird
separat geführt. `funding_effect` erklärt die Behandlung; `funding_adjustment`
zeigt die Änderung gegenüber `criteria_score`. Ohne manuell kuratierte Finanzdaten
bleibt `equity_status` leer und die Finanzierung beeinflusst das Ranking nicht.
The three HTGF fit checks accompany each score: a documented failure sets the
final score to `0`, while missing or inconclusive evidence leaves a provisional
score visible until reviewed. A company must be a technology startup in Digital Tech, Industrial,
Climate & Deep Tech, Life Sciences, Chemistry or an adjacent field; have a
registered German seat or a documented plan to relocate/open a German
establishment; and be registered for no more than three years. Age is measured
from the official commercial-register date, inclusively through the third
calendar anniversary. A pre-company venture remains provisionally scored until
the company-age evidence is resolved. Unknown sourcing criteria use a neutral
50-point prior; confirmed external equity remains a separate override to zero.

Sortiert wird nach finalem Score absteigend. Fehlende,
veraltete und alte Kriterienversionen stehen danach und zählen nicht für
Prioritätsfilter. Standort und Deutschlandbezug sind Profilmetadaten und keine
Bewertungskriterien oder Standardfilter. Keine Erfolgswahrscheinlichkeiten.
`assessment_stale` zeigt,
dass das aktuelle Profil neuer als die Bewertung ist.

## Jobs

Felder: id, kind (`process|research|evaluate|search`), status
(`queued|running|succeeded|failed`), payload, result, error, attempts,
max_attempts, available_at, lease_until, created_at, updated_at, dedupe_key.

Alle 1–3 Sekunden `GET /jobs/{id}` pollen. Bei succeeded/failed stoppen.
Nach process/evaluate/research Profile erneut laden. Nach search zusätzlich die
`result.child_job_ids` verfolgen: Sammlung abgeschlossen bedeutet noch nicht,
dass Kandidaten und Bewertungen fertig sind. Bei Verlassen der Ansicht Polling
abbrechen. Fehlerjobs können verzögert automatisch wieder queued werden.

## Aktuelle Suchgrenze

Suchaufträge sammeln konfigurierte Quellen; der Prompt wird als Auftragstext
gespeichert. Semantische Quellenauswahl und offene Discovery anhand des Prompts
sind noch nicht implementiert. Keine entsprechende UI-Funktion vortäuschen.

## Betriebsmodus

Es gibt ausschließlich Produktivbetrieb. `APP_MODE` darf fehlen oder muss `live`
sein. Die Backend-Konfiguration verlangt PostgreSQL, Neo4j, OpenAI und einen
API-Token; bei fehlender Konfiguration startet der Prozess nicht. Es gibt weder
einen Demo-Endpunkt noch eine Mock-API im Frontend.
