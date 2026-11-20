# Startup Finder – Frontend

Arbeitsoberfläche für VC-Sourcing (HTGF-Stil). Next.js 16, React 19, TypeScript. Spricht die API aus `../docs/frontend-contract.md`.

## Starten

Backend (Demo, synthetische Daten) im Repo-Root:

```sh
python3 -m startup_finder demo
```

Frontend:

```sh
cd frontend
npm install
npm run dev
```

Öffnen: <http://localhost:3000>

Das Backend erlaubt standardmäßig `http://localhost:3000` und `http://localhost:5173` (`CORS_ORIGINS`).

## Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `NEXT_PUBLIC_FINDER_API_URL` | `http://localhost:8000` | Backend-Basis (ohne `/api`) |
| `NEXT_PUBLIC_FINDER_API_MODE` | `http` | `mock` = synthetische Daten im Browser, ohne Backend |

Zur Laufzeit lassen sich URL, Modus und das **API-Token** (Live-Modus, `Authorization: Bearer …`) unter **Systemstatus** setzen; sie bleiben in diesem Browser. Im Browser liegt kein Modellschlüssel.

## Prüfen

```sh
npm run check   # Typecheck + Produktions-Build
```

## Aufbau

```
src/app/            Next-Einstieg (layout, page)
src/finder/
  types.ts          Typen nach frontend-contract.md v1
  api/client.ts     FinderApi-Interface, HTTP-Client (Token, Fehler {detail}), Konfiguration
  api/mock.ts       austauschbarer Mock mit identischen Responses, simuliertem Worker
  hooks.tsx         ApiProvider, useLoad, useJobPolling (1,5 s; stoppt beim Verlassen)
  App.tsx           Navigation (Hash-Routen), Demo-/Verbindungsbanner, Meldungen
  views.tsx         Entdecken, Shortlist, Suchaufträge, Quellen/Fundstellen, Pipeline, Systemstatus
  GraphView.tsx     Graph (GET /api/graph): Personen ↔ Startups ↔ Institutionen, Beziehungsliste
  CandidatePanel.tsx Kandidatendetail
  htgf-base.css     HTGF-Schriften, Tokens, Buttons
  finder-app.css    Oberfläche
public/htgf/        Schriften und Bilder (von htgf.de)
```

## Verhalten nach Vertrag

- Belege hängen als nummerierte Marker an Aussagen; Klick zeigt Zitat bzw. Dokumentausschnitt und Link zum Original.
- KI-Einschätzung ist getrennt von Quelldaten (Modell, Profil-/Kriterienversion, „veraltet“-Hinweis). Keine Erfolgswahrscheinlichkeiten.
- Widersprüche (`conflicts`) werden angezeigt, nicht überschrieben.
- Recherche/Bewertung/Verarbeitung: Job pollen, danach Profil neu laden. Suche: zusätzlich `result.child_job_ids` verfolgen.
- Suchaufträge zeigen ausdrücklich, dass der Text nur Auftragskontext ist und aus den gewählten Quellen gesammelt wird – keine semantische Suche vorgetäuscht.
- Suche in „Entdecken“ deckt sich mit dem Backend: Name, Beschreibung, Standort (keine Personen).
- Graph ist eine schreibgeschützte Ansicht der materialisierten Knoten und Kanten; Startup-Knoten öffnen das Profil.
- Synthetische Daten: Banner bei Mock oder `capabilities.synthetic`/Demomodus, „Demo“-Marker an Einträgen.
