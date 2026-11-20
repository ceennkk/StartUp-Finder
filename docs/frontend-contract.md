# Frontend-Vertrag · v2

Basis: `http://localhost:8000/api`. JSON. Listen: `{items: [...], total: number}`.
Details direkt als Objekt, Jobs als `{job: {...}}`, Fehler als `{detail: string}`.
Alle Zeitangaben ISO 8601 mit Zeitzone. Leere/unbekannte Fakten bleiben leer.

Bei Loopback-Bindung (`127.0.0.1`/`localhost`) ist kein API-Token nötig; bei
Netzwerkbindung verlangt das Backend `Authorization: Bearer <API_TOKEN>` für alle
API-Routen. Modellschlüssel bleiben im Worker. CORS_ORIGINS enthält die erlaubten
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
| GET | /candidates/{id} | Profil + evidence, assessment, notes, research_runs |
| PATCH | /candidates/{id} | `{status:new\|shortlisted\|rejected}` |
| POST | /candidates/{id}/notes | `{text}` → gespeicherte Notiz |
| POST | /candidates/{id}/research | `{}` → 202 + Job |
| POST | /candidates/{id}/evaluate | `{}` → 202 + Job |
| GET | /jobs | Filter: kind, status |
| GET | /jobs/{id} | Jobstatus, Fehler, Ergebnis |
| POST | /jobs/{id}/retry | Nur failed → queued; 202 + Job |
| GET / POST | /searches | Liste / `{prompt,source_ids?:string[],interval_minutes?:number\|null}` |
| GET | /searches/{id} | Auftrag inkl. letzter Fundstellen und Job-ID |
| POST | /searches/{id}/run | `{}` → 202 + Job |
| GET | /graph | `{nodes,edges,mode,is_materialized_view:true}` |
| GET | /events | Ereignisse; Filter entity_id |

Alle Listen: `limit` 1–200 (Standard 50), `offset` >= 0. Fundstellen zusätzlich
`source_id`, `status`, `q`. HTTP: 201 erzeugt, 202 Job, 401 Token fehlt,
404 unbekannte ID/Route, 413 Body zu groß, 422 Eingabe ungültig, 500 intern.

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
- `assessment`: null oder gespeicherte Bewertung.

`source_excerpt` ist ein Dokumentausschnitt, keine verifizierte Textspanne für
jede Profilaussage. Extrahierte deutsche Länderangaben ergeben zunächst `likely`.
Widersprüche bleiben in `conflicts`; sie werden nicht still überschrieben.

## Bewertung

Felder: id, candidate_id, score (0–100 oder null), scored_criteria (0–4),
priority (`high|medium|low|insufficient_data`), summary,
strengths[], concerns[], open_questions[], evidence_ids[], criteria[], model,
profile_version, criteria_version, created_at, profile_snapshot.

Kriterium: key, label, rating (`strong|moderate|weak|unknown`), rationale,
evidence_ids[]. Kriterien: founding_intent, technical_substance, customer_problem,
demand. Alle vier Kriterien sind gleich gewichtet: `strong`=100, `moderate`=67,
`weak`=33. `unknown` wird nicht in den Mittelwert eingerechnet. Ein Score wird
erst ab drei Kriterien mit Belegreferenzen berechnet. `high` beginnt bei 75,
`medium` bei 50, darunter `low`; bei zu wenigen bewertbaren Kriterien gilt
`insufficient_data`. Sortiert wird nach numerischem Score absteigend. Fehlende,
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
