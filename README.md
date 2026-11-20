# Startup Finder

Modulares Backend für deutsches VC-Sourcing mit Graphiti. Enthält Fundstellen,
Jobs, Kandidatenbildung, Recherche, Bewertung, Shortlist und eine funktionale
API-Vorschau. Das separate Produktfrontend kann parallel gegen die API entstehen.

## Sofortige Offline-Vorschau

Python 3.11+; keine Installation, Datenbankserver oder Modellschlüssel erforderlich:

```sh
cd StartUp-Finder
python3 -m startup_finder demo
```

Öffnen: http://localhost:8000/preview

Der Befehl startet API und Worker, legt SQLite unter `data/demo.sqlite3` an und
verarbeitet drei explizit synthetische Teams. Alle Demo-Ergebnisse sind entsprechend
gekennzeichnet. Hier laufen keine echten Graphiti-/Modellaufrufe. Arbiträre Texte
werden im Demo-Modus nicht als vermeintlich echte AI-Ergebnisse verarbeitet.

Port ändern: `python3 -m startup_finder demo --port 8001`.

## Was funktioniert?

| Baustein | Umsetzung |
|---|---|
| PostgreSQL | persistente Fundstellen, Jobs, Profile, Bewertungen und Nutzeraktionen; SQLite nur offline |
| Worker | Jobs claimen, Heartbeats, Backoff/Retry, serialisierte Graphschreibzugriffe, Scheduler |
| Graphiti | Episodenimport, eigene StartupVenture/Person/Institution-Typen und Graphpflege |
| Modell-Clients | OpenAI Responses für Recherche/Bewertung, Graphiti-LLM und optionale Decision-Routen |
| Graphdatenbank | Neo4j; API liest daraus materialisierte Resultate in PostgreSQL |
| Kandidatenmodul | Profile aus aufgelösten Graphknoten, Belege, Konflikte, Versionen |
| Recherche/Bewertung | zitierte Webrecherche, Originalseitenimport, Kriterien, Gegenargumente, Profilsnapshot |
| Backend-API | Quellen, Fundstellen, Kandidaten, Shortlist/Notizen, Jobs, Graph und Systemstatus |

Aktuelle Suchaufträge sammeln konfigurierte HTML-/RSS-/manuelle Quellen. Ihr
Freitext ist gespeicherter Auftragskontext; offene semantische Quellenentdeckung
ist noch keine implementierte Funktion. Eigene GitHub/Hugging-Face-Adapter können
über `Application.import_finding` dasselbe Fundstellenformat einspeisen.

## Live lokal

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[live]'
cp .env.example .env
```

In `.env` setzen:

- `APP_MODE=live`
- `DATABASE_URL=postgresql://startup:DEIN_PASSWORT@localhost:5432/startup`
- `POSTGRES_PASSWORD` passend zur URL, `NEO4J_PASSWORD`
- `OPENAI_API_KEY`, ein verfügbarer `OPENAI_MODEL`, `API_TOKEN`

```sh
docker compose up -d
python3 -m startup_finder init-db
python3 -m startup_finder serve
# Zweites Terminal, gleiche .env und Umgebung:
python3 -m startup_finder worker
```

Für Aura `NEO4J_URI`, Benutzer und Passwort ersetzen. Neo4j Browser lokal:
http://localhost:7474. Neo4j und PostgreSQL haben persistente Docker-Volumes.
Alle Container inklusive API/Worker: `docker compose -f compose.yml -f compose.app.yml up --build`.
Für das Compose-URL-Beispiel keine reservierten URL-Zeichen im Passwort verwenden
oder DATABASE_URL korrekt URL-escapen/als Secret konfigurieren.

Live-Fundstellen über POST /api/findings importieren und POST
/api/findings/{id}/process starten. Frontend/API-Aufrufe benötigen den Bearer-Token.
Recherche und Bewertung sowie Graphiti-Ingestion können Modellkosten verursachen.

## Jev / OpenAI Decisions

Standard: `DECISION_PROVIDER=off`, generatives Modell übernimmt Graphiti-Aufgaben.
Optional `jev` mit `JEV_API_KEY` oder `openai` mit `OPENAI_DECISIONS_MODEL` und
entsprechendem Providerzugriff. Nur Node-Deduplizierung/Edge-Auflösung werden
umgeroutet; Extraktion/Summaries bleiben generativ. Integration folgt Graphitis
aktueller LLMRuntime-API. Fehlt diese in der installierten Veröffentlichung,
meldet der Worker einen Fehler; kein stiller Fallback.

Alternativ `GRAPHITI_CLIENT_FACTORY=mein_modul:create_client` konfigurieren; die
Funktion erhält Settings und liefert eine fertig konfigurierte Graphiti-Instanz.
Die tatsächlichen Provideraufrufe sind ohne Zugangsdaten noch nicht verifiziert.

## Frontend und Architektur

- [API-Vertrag](docs/frontend-contract.md): Routen, Requests, Objekte, Polling und Grenzen.
- [Architektur](docs/architecture.md): Bausteine, Datenfluss, Recovery und Sicherheit.
- Funktionsvorschau: Entdecken, Shortlist, Suchaufträge, Quellen/Fundstellen,
  Jobs/Retry, Graph und Systemstatus.

## Tests

```sh
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/smoke_demo.py
node --check startup_finder/static/preview.js
```

Offline-Tests prüfen unter anderem kompletten Demo-Durchlauf, Duplikatvermeidung,
Profilupdates, Nutzeraktionen, Graph-Receipt-Recovery, Job-Leases, API-Auth,
CORS, ungültige Beleg-IDs und Netzwerkziel-Validierung.

Nicht live verifiziert: PostgreSQL, Neo4j/Graphiti sowie externe Modell- und
Decision-Aufrufe. Docker und Providerzugänge werden dafür benötigt. Live-Abhängigkeiten
haben noch keinen geprüften Lockfile. Vor Deployment Versionen pinnen und echte
Integrationsläufe ausführen.

HTTP-Server und Datenschema sind für einen lokalen/team-internen Prototyp gedacht,
nicht als fertig abgesicherte öffentliche Mehrbenutzerplattform. Keine automatische
Bestätigung von Startup-Qualität, deutschen Unternehmenssitzen oder Finanzierungsfreiheit.
