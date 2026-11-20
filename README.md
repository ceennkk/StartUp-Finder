# Startup Finder

Produktionsworkflow für VC-Sourcing: Quellenadapter speichern Originalfundstellen
in PostgreSQL. Ein Worker bereitet Änderungen auf und verarbeitet sie über
Graphiti und LLM-Routen zum Knowledge Graph in Neo4j. Daraus entstehen
Kandidatenprofile, Recherchen und Bewertungen in PostgreSQL, die Backend-API und
Frontend bereitstellen.

## Produktionsbetrieb

Der Finder unterstützt ausschließlich den Produktivbetrieb. Es gibt keinen
Demo-Server, keine synthetischen Produktdaten und keine Laufzeit-Mock-API. Ohne
gültige PostgreSQL-, Neo4j-, OpenAI- und API-Token-Konfiguration startet der
Backend-Prozess nicht. `.env.example` enthält nur Platzhalter.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[live]'
cp .env.example .env
```

In `.env` produktive Zugangsdaten setzen, einschließlich `DATABASE_URL` für
PostgreSQL/Neon, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `OPENAI_API_KEY`
und eines starken `API_TOKEN`. `APP_MODE` muss `live` sein oder entfallen.

```sh
python3 -m startup_finder init-db
python3 -m startup_finder serve
# Zweites Terminal, gleiche Umgebung:
python3 -m startup_finder worker
```

Für Aura `NEO4J_URI`, Benutzer und Passwort setzen. Modellaufrufe für Graphiti,
Recherche und Bewertung können Kosten verursachen. Vor einem produktiven Lauf
die konfigurierten Quellen, Datenbankzugänge und Providerkosten prüfen. Das
generative Modell ist standardmäßig `gpt-6-luna` (`OPENAI_MODEL`).

## Architektur

| Baustein | Aufgabe |
|---|---|
| Quellenadapter | Originalfundstellen und Adapterdaten aufnehmen |
| PostgreSQL | Fundstellen, Jobs, Profile, Bewertungen und Nutzeraktionen persistieren |
| Worker | Änderungen prüfen, Jobs verarbeiten, Recherche und Bewertung ausführen |
| Graphiti + generatives LLM | Fundstellen als Episoden verarbeiten und den Knowledge Graph pflegen |
| Decision-Routen | Optional Identitätsabgleich und Deduplizierung routen |
| Neo4j | Knowledge Graph speichern |
| Kandidatenmodul | Aufgelöste Venture-Knoten mit Belegen zu Profilen materialisieren |
| Backend-API | Produktfunktionen und gespeicherte Daten bereitstellen |
| Frontend | Kandidaten, Quellen, Graph, Recherche, Bewertung und Shortlists anzeigen |

Die Ontologie für Graphiti-Entitäten und gerichtete Beziehungen steht als RDF/Turtle
in `docs/startup-sourcing-ontology.ttl`; die Graphiti-Extraktion verwendet die
passenden Pydantic-Typen und strikten Relationship-Signaturen aus
`startup_finder/ontology.py`.

Recherche- und Bewertungsstände referenzieren einen gespeicherten Profilstand.
Originalseiten werden als neue Fundstellen zurück in die Verarbeitung gegeben.
Die API liest eine materialisierte Graphansicht in PostgreSQL, nicht alle
Graphiti-internen Daten direkt aus Neo4j.

## Frontend

```sh
cd frontend
npm ci
npm run dev
```

Die Produktoberfläche spricht über `frontend/src/finder/api/client.ts` mit dem
Backend. Basis-URL ist standardmäßig `http://localhost:8000`; die API muss
`http://localhost:3000` in `CORS_ORIGINS` erlauben. Zugangsdaten gehören in
Backend-Secrets, nicht in den Browser. Auf Loopback (`127.0.0.1`/`localhost`)
ist kein zusätzlicher API-Token nötig; bei Netzwerkbindung verlangt das Backend
weiterhin `API_TOKEN`. `/datenbestand` ist eine separate technische, schreibgeschützte
Ansicht des Adapterdatenbestands in Neon.

## Adapterdaten in die Finder-Pipeline übernehmen

Collector-Fundstellen (`source_records`) werden mit dem Bridge-Befehl in Finder-
Fundstellen überführt und als process-Jobs eingereiht. Ein laufender Worker
verarbeitet sie anschließend mit Graphiti, LLM und Decision-Routen. Stabile
Adapter-IDs machen die Übernahme wiederholbar.

```sh
# Feldmapping prüfen; schreibt keine Finder-Daten und reiht keine Jobs ein.
python3 -m startup_finder sync-adapters --source exist --record-type success_story --limit 1 --dry-run
# Gezielte reale Fundstelle importieren und einen Worker-Job einreihen.
python3 -m startup_finder sync-adapters --source exist --record-type success_story --limit 1
```

Nur Zeilen mit HTTP(S)-URL, Titel und verwertbarem Text werden übernommen. Die
Bridge verändert keine Collector-Originale. Der Worker übernimmt neue und
geänderte Datensätze automatisch in die Graphiti-Pipeline. Diese kann Graphiti-,
Embedding-, Decision- und Modellaufrufe auslösen.

## Decision-Routen

`DECISION_PROVIDER=openai` routet Graphitis Node-Deduplizierung und Edge-Auflösung
über die OpenAI Decisions API (`OPENAI_DECISIONS_MODEL`, Standard `gpt-6-luna`).
Extraktion und Zusammenfassung bleiben beim generativen Modell `OPENAI_MODEL`
(Standard `gpt-6-luna`).
Fehlende Providerunterstützung führt zu einem Fehler, nicht zu einem stillen Fallback.

## Dokumentation und Grenzen

- [API-Vertrag](docs/frontend-contract.md)
- [Architektur, Datenfluss und Betriebsgrenzen](docs/architecture.md)

Der aktuelle Suchauftrag sammelt konfigurierte HTML-, RSS- und manuelle Quellen;
der Prompt ist gespeicherter Auftragskontext. Semantische Quellenauswahl und
offene Discovery anhand des Prompts sind nicht implementiert. Das System ist ein
Team-Prototyp, keine fertige öffentliche Mehrbenutzerplattform. Bewertungen sind
keine automatische Bestätigung der Startup-Qualität oder Anlageempfehlung.
