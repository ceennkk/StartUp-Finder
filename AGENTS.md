# StartUp-Finder / VentureRadar Ingestion – Projektwissen für KI-Agenten

Diese Datei beschreibt den aktuellen Stand des Repositorys und dient als Kontext für Coding-Agenten. Lies vor einer Änderung zusätzlich die betroffenen Implementierungen, Tests und Konfigurationen; diese Datei ist eine Orientierung, kein Ersatz für den Quellcode.

## 1. Zweck und aktueller Umfang

Das Python-Paket `ventureradar-ingestion` sammelt öffentliche Daten aus mehreren externen Quellen, bewahrt die Quelldatensätze auf, normalisiert sie in ein gemeinsames Entitäts- und Beziehungsmodell und schreibt alles nach PostgreSQL. Die Daten sollen Signale zu Forschung, Technologie und möglichen Start-ups auffindbar machen.

Der Repository-Name lautet `StartUp-Finder`, der Paket- und CLI-Name ist `ventureradar-ingestion` beziehungsweise `ventureradar`. Es handelt sich derzeit primär um einen Collector und eine Persistenzschicht, nicht um eine Webanwendung oder ein UI.

Technischer Kern: Python 3.12+, Typer für die CLI, Pydantic Settings und Modelle, SQLAlchemy 2 für den Datenzugriff, PostgreSQL mit JSONB, Alembic für Schema-Migrationen, HTTPX und Tenacity für HTTP/Retry sowie BeautifulSoup/feedparser für HTML- und Feed-Verarbeitung. Die Abhängigkeiten und das Console-Script sind in [`pyproject.toml`](pyproject.toml) deklariert.

Aktuell registrierte Collector-Namen:

- `openalex` – wissenschaftliche Arbeiten und Forschungsinstitutionen
- `github` – öffentliche Repositories, Contributors und Aktivitätskennzahlen
- `arxiv` – Preprints und Metadaten
- `huggingface` – Modelle, Datensätze, Spaces und Organisationen
- `exist` – EXIST-Erfolgsgeschichten und Förderprogramme
- `university` – ausgewählte Hochschulmeldungen und Forschungsprojekte

Die Collector-Registrierung steht in [`app/adapters/registry.py`](app/adapters/registry.py). Laufzeitparameter und Suchbereiche liegen in [`app/config/search_terms.yaml`](app/config/search_terms.yaml) und [`app/config/sources.yaml`](app/config/sources.yaml).

**Projektumfang:** Umgesetzt ist ausschließlich Phase 1 (Datenbasis und Ingestion). Nicht Teil davon und nur auf ausdrückliche Freigabe zu beginnen: Start-up-Scoring/-Klassifikation, Entity Resolution/Merging, Team-Erkennung, Marktanalyse, KI-Analyse, Rankings, Dashboard/Frontend, FastAPI.

## 2. Architektur und Datenfluss

Die zentrale Pipeline ist in [`app/adapters/base.py`](app/adapters/base.py) implementiert. Jeder Adapter liefert Quelldaten, die gemeinsame Basisklasse übernimmt Orchestrierung und Persistenz:

1. `fetch()` liest Quelleinträge mit Pagination, Zeitfenstern und gegebenenfalls einem gespeicherten Sync-Cursor.
2. Jeder Eintrag wird als `RawRecord` mit stabiler quellspezifischer `external_id`, Typ, Original-Payload, kanonischer URL und optionalem Veröffentlichungszeitpunkt abgebildet.
3. Die Rohdaten werden zuerst als `source_records` upserted. Dadurch bleiben sie auch erhalten, wenn die anschließende Normalisierung dieses Eintrags fehlschlägt.
4. `normalize(raw)` erzeugt ein `NormalizedBundle` aus Entities, Relationships, Signals und Observations.
5. `validate(bundle)` prüft, dass ein Bundle mindestens eine Entity enthält und alle lokalen Referenzen auf existierende Entity-Keys zeigen.
6. Das Bundle wird über [`app/database/repositories.py`](app/database/repositories.py) idempotent persistiert.
7. Am Ende werden der `IngestionRun` abgeschlossen und – nur bei erfolgreichem Lauf – die vorgemerkten Sync-Cursor gespeichert.

`--dry-run` ruft weiterhin Quelle und Normalisierung auf und validiert die Bundles, schreibt aber weder Daten noch Sync-Cursor. `--limit` begrenzt die Zahl der verarbeiteten Quelldatensätze eines Laufs.

Einzelne fehlerhafte Datensätze werden gezählt und geloggt; übrige Datensätze können weiterlaufen. Ein Fehler beim Abruf kann den Lauf als fehlgeschlagen beenden, bereits verarbeitete Datensätze bleiben aber erhalten. Die Verarbeitung committet spätestens alle 50 Einträge. Sync-Cursor werden bei einem fehlgeschlagenen oder partiellen Lauf nicht fortgeschrieben, damit fehlende Daten später erneut abgerufen werden können.

## 3. Gemeinsames Datenmodell

Die Typen und erlaubten Enum-Werte sind in [`app/domain.py`](app/domain.py) festgelegt. Die Eingabe- und Zwischenmodelle mit Pydantic stehen in [`app/ingestion/types.py`](app/ingestion/types.py).

- **Entity**: normalisierte Person, Organisation, Universität, Forschungsprojekt, Publikation, Repository, Modell, Datensatz, Space, Startup, Event, Förderprogramm oder Technologie.
- **Alias**: zusätzlicher Name oder Identifier einer Entity, etwa DOI, ORCID, ROR, URL oder Login.
- **Relationship**: gerichtete und quellenbelegte Beziehung zwischen zwei Entities, z. B. `AUTHORED`, `MEMBER_OF`, `OWNED_BY`, `FUNDED_BY` oder `PUBLISHED_BY`.
- **Signal**: zeitlicher Hinweis wie neue Publikation, neues Repository, neues Modell oder neue Pressemitteilung.
- **Observation**: numerischer Messwert zu einer Entity, z. B. Sterne, Downloads, Zitationen oder Follower zu einem Messzeitpunkt.
- **SourceRecord**: Originaldatensatz einer konkreten Quelle; er ist die Provenienz für die daraus extrahierten Entities, Beziehungen und Signale.

Die SQLAlchemy-Modelle sind in [`app/database/models.py`](app/database/models.py), das initiale Schema in [`app/database/migrations/versions/20261120_0001_initial_schema.py`](app/database/migrations/versions/20261120_0001_initial_schema.py) definiert. Kern-Tabellen:

| Tabelle | Zweck |
| --- | --- |
| `sources` | Metadaten der externen Quellen |
| `ingestion_runs` | Status, Zeitpunkte, Zähler und Fehler eines Collector-Laufs |
| `source_records` | Aktueller Rohdatensatz mit Hash und „first/last seen“-Zeit |
| `source_record_revisions` | Vorherige Roh-Payloads nach inhaltlichen Änderungen |
| `entities` | Gemeinsame normalisierte Objekte |
| `entity_aliases` | Namen und source-scoped externe Identifiers |
| `entity_source_records` | Provenienz: welche Quelle und welcher Datensatz eine Entity geliefert hat |
| `relationships` | Gerichtete, quellenbelegte Entity-Kanten |
| `signals` | Signale mit Quelle und Zeitbezug |
| `observations` | Zeitreihe numerischer Kennzahlen |
| `sync_state` | Inkrementelle Cursor je Quelle und Abfragebereich |

### Identität, Änderungsverfolgung und Provenienz

- Entities werden anhand eines quellenbezogenen `SOURCE_IDENTIFIER`-Alias gefunden. Derzeit werden Entities **nicht automatisch zwischen unterschiedlichen Quellen zusammengeführt**; gleiche Namen allein sind kein Merge-Schlüssel.
- `EntityDraft.is_primary=True` kennzeichnet die Entity, deren Quelldatensatz maßgeblich für normalisierte Felder ist. Bei referenzierten Entities werden eher fehlende Informationen ergänzt, statt ihre bestehenden Werte zu überschreiben.
- Payloads werden deterministisch gehasht. Ein Adapter kann volatile Felder aus dem Hash ausschließen oder über `hash_basis` nur stabile Felder berücksichtigen. Reine volatile Änderungen aktualisieren den Rohdatensatz, erzeugen aber keine Revision; fachliche Änderungen sichern vorherige Roh-Payloads in `source_record_revisions`.
- Veränderungen an Kennzahlen gehören in `Observation`, nicht in eine künstliche Entity-Revision. Beobachtungen werden je Entity und Kennzahl nach Stunde oder Tag gebucktet (Einstellung `OBSERVATION_BUCKET`).
- Beziehungen haben einen `verification_status`. Aus bloßen Keyword-Treffern abgeleitete Aussagen müssen als `UNVERIFIED` markiert bleiben und dürfen nicht als bestätigte Fakten dargestellt werden.
- Beziehungen und Signals behalten die Quelle beziehungsweise den `source_record_id` als Provenienz; diese Verbindung nicht entfernen.

## 4. Collector und Quellenverhalten

Alle Adapter erben von `BaseAdapter` und implementieren mindestens `fetch()` und `normalize()`. Die gemeinsame HTTP-Infrastruktur liegt in [`app/http/client.py`](app/http/client.py): `PoliteHttpClient` bietet Timeouts, User-Agent, Abstände pro Host, Retry bei Transportfehlern und ausgewählten HTTP-Statuscodes sowie optional `robots.txt`-Prüfung. Bei nicht erreichbarer `robots.txt` wird für entsprechende Prüfungen fail-closed verfahren; der `robots.txt`-Abruf selbst läuft durch die Host-Drosselung. Der User-Agent enthält `CONTACT_EMAIL`, falls gesetzt (`VentureRadar-Ingestion/0.1 (research collector for public sources; contact: <E-Mail>)`).

### OpenAlex

Liest Werke über die OpenAlex-API. Themenbegriffe, Länderfilter, Startzeitraum, Überlappungszeitraum und Autorenlimit stehen unter `openalex` in `search_terms.yaml`. Standardmäßig wird auf Institutionen mit Ländercode `DE` gefiltert. Mit API-Key wird Cursor-Pagination verwendet; ohne Key ist der Abruf auf Basic-Pagination und maximal 10.000 Treffer pro Abfrage begrenzt. Normalisiert Werke, Autor:innen und Institutionen und erzeugt Publikationssignale, Autorenschafts-/Mitgliedschaftsbeziehungen sowie Zitationsbeobachtungen.

### GitHub

Benötigt `GITHUB_TOKEN`, sonst ist der Adapter nicht konfigurierbar. Sucht Repositories nach Topics und Erstellungszeiträumen, splittet zu große Suchfenster und begrenzt die Abfrage. Bereits bekannte Repositories können für neue Kennzahlen und Aktivitätsdaten erneut gelesen werden. Sterne und weitere Zähler sind Observations; stabile Repository-Merkmale bilden die Hash-Basis. API-Such- und Host-Limits sind im Adapter berücksichtigt. Erfasste Contributor- und Aktivitätsdaten werden minimiert; z. B. werden Commit-Autorennamen und E-Mail-Adressen nicht gespeichert.

### arXiv

Liest Metadaten über die offizielle Atom-API nach konfigurierten Kategorien und optionalen Begriffen. Der Adapter drosselt auf höchstens eine Anfrage alle drei Sekunden, sortiert ältere Treffer zuerst und begrenzt die Ergebnisse pro Lauf. Abstracts, Autoren, Kategorien und Identifier werden normalisiert. PDFs werden nicht gespeichert; ihre URL kann als Link-Metadatum vorkommen.

### Hugging Face

Liest `models`, `datasets` und `spaces` nach konfigurierten Filtern und Suchbegriffen. Model-/Dataset-Cards werden optional und mit Zeichenlimit gelesen. Namespace-Lookups unterscheiden Organisationen und Benutzer; öffentliche Organisationsmitglieder werden nur mit begrenzten, öffentlichen Profildaten berücksichtigt. Downloads, Likes und verwandte Zähler landen als Observations.

### EXIST

Liest konfigurierte Programmseiten und Erfolgsgeschichten aus der Sitemap. Der öffentliche WordPress-Endpunkt wird ergänzend nur für Veröffentlichungsdaten genutzt; Story-Inhalte kommen aus HTML. Programmnennungen werden über konfigurierbare Keywords erkannt und als **unverifizierte** Förderbeziehung modelliert. Personen werden nicht aus Interviewtext extrahiert. Der Adapter respektiert `robots.txt` und konfiguriert eine Mindestpause pro Host.

### Hochschulen

Die Hochschulquellen stehen unter `universities.sources` in `sources.yaml`; konfiguriert sind KIT, TU Darmstadt und die Universität Duisburg-Essen (UDE). `UniversityAdapter` unterstützt die Connectoren `rss`, `sitemap` (validierte Sitemap + JSON-LD pro passender URL), `jsonld` (explizite URLs), `page_metadata` (explizite URLs und/oder validierte Sitemap mit Pfadpräfix; nur Titel und Meta-Beschreibung) und `html` (CSS-Selektoren auf einer Listingseite). Es wird nicht allgemein oder unbeschränkt gecrawlt. Die Connectoren stehen in [`app/adapters/university/connectors.py`](app/adapters/university/connectors.py); optionale quellspezifische Anpassungen liegen in [`app/adapters/university/plugins.py`](app/adapters/university/plugins.py). Der KIT-Plugin ergänzt eine aus der URL extrahierte Pressemitteilungsnummer.

Quellenoptionen in `sources.yaml`: `enabled` (`false` = Collector aus), `group` (Quellen derselben Hochschule teilen eine Universitäts-Entity `university:<group>`), `kind` (`press_release`, `news`, `research_project`, `organization_unit`), `min_interval_seconds`, `require_contact_email`, `initial_days` (Zeitfenster beim ersten Lauf ohne Cursor, Standard 30), `lookback_days`, `max_items`, `properties` (zusätzliche Entity-Eigenschaften), `unit_name`/`unit_aliases` (für `organization_unit`). Regeln im Adapter: Nicht-RSS-Connectoren warten mindestens 10 s pro Host; ohne `CONTACT_EMAIL` bricht eine Quelle mit `require_contact_email` mit einem Konfigurationsfehler ab; eine explizit per `--source` gewählte deaktivierte Quelle ist ein Konfigurationsfehler (Exit-Code 2); jede Sitemap wird vor der Nutzung mit `validate_sitemap()` geprüft (kein DOCTYPE/Entities, `urlset` im Sitemap-Namespace, 1 bis 50.000 URLs, nur Hosts der Sitemap), ein Fehler lässt die Quelle fehlschlagen statt still auf etwas anderes zurückzufallen. Gespeichert werden nur Metadaten, Links, Datum und ein Teaser von höchstens 500 Zeichen; keine Volltexte (`content:encoded`), Bilder/Enclosures oder Autoren.

**UDE (erstes ausgearbeitetes Beispiel, Gruppe `ude`):** `ude_forschung` (RSS, aktiv), `ude_aktuell` (RSS, deaktiviert) und `ude_guide` (Gründungszentrum GUIDE, `page_metadata` + Sitemap-Präfix `/guide/`, deaktiviert; als `organization_unit` `unit:ude_guide` mit `MEMBER_OF` zur Universität, ohne Signal, nur die Startseite aktualisiert die Entity). Zwei Quellen sind deaktiviert, weil keine Nutzungsbedingungen für automatisierte Weiterverwendung gefunden wurden und die `robots.txt` `GPTBot` ausdrücklich sperrt; sie erst nach Klärung aktivieren, die Daten nicht für KI-Training verwenden. Die UDE-Sitemap listet genau 5.000 URLs (vermutlich gekappt) und gilt nicht als vollständiger Index. Tests: [`tests/adapters/test_university_ude.py`](tests/adapters/test_university_ude.py) mit Fixtures `ude_forschung.rss`, `ude_sitemap.xml`, `ude_guide.html`.

## 5. Konfiguration und Einstellungen

- [`app/config/search_terms.yaml`](app/config/search_terms.yaml): Suchbegriffe, Topics, Kategorien, Zeiträume, Caps und adapterbezogene Abrufgrenzen für API-Collector.
- [`app/config/sources.yaml`](app/config/sources.yaml): HTML-/RSS-Quellen, Hochschulen, URLs, Programme und Extraktionsoptionen.
- [`app/config/settings.py`](app/config/settings.py): Pydantic-Settings, YAML-Lader und Umgebungsvariablen. Einstellungen werden pro Prozess gecacht.
- `.env.example`: Variablennamen und lokale Konfigurationsvorlage. Zugangsdaten gehören ausschließlich in eine lokale, nicht versionierte `.env` oder sichere Deployment-Secrets; niemals in Dokumentation, Tests, Logs oder Commits kopieren.

Wichtige Umgebungsvariablen: `DATABASE_URL`, optional `DATABASE_URL_DIRECT`, `TEST_DATABASE_URL`, `GITHUB_TOKEN`, `OPENALEX_API_KEY`, `HF_TOKEN`, `CONTACT_EMAIL`, `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_RETRIES`, `LOG_LEVEL`, `LOG_FORMAT` und `OBSERVATION_BUCKET`. `DATABASE_URL` wird für normale DB-Verbindungen genutzt; Migrationen verwenden bevorzugt `DATABASE_URL_DIRECT`. Der PostgreSQL-Treiber wird bei Bedarf auf psycopg 3 normalisiert.

Bevor du Suchbereiche oder Quellen änderst, prüfe die Nutzungsbedingungen und Abrufregeln der jeweiligen Quelle. Halte Begrenzungen, Host-Abstände und `robots.txt`-Vorgaben ein; nimm keine Zugangsdaten in YAML auf.

## 6. Lokales Entwickeln und Ausführen

Voraussetzung ist Python 3.12 oder neuer.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

`.env` lokal mit den nötigen Verbindungsdaten konfigurieren. Eine lokale PostgreSQL-Instanz für Tests kann über Docker Compose gestartet werden:

```powershell
docker compose up -d postgres
```

Der Compose-Dienst veröffentlicht PostgreSQL auf Port `5433`; die Testdatenbank heißt `ventureradar_test`. Stelle sicher, dass `TEST_DATABASE_URL` auf genau diese dedizierte Testdatenbank zeigt. Teste niemals gegen eine produktive oder anderweitig wertvolle Datenbank.

CLI-Beispiele:

```powershell
ventureradar database init
ventureradar database status
ventureradar collect openalex --limit 10 --dry-run
ventureradar collect all --limit 10
ventureradar collect university --source ude_forschung --limit 5 --dry-run
ventureradar ingestion history --limit 20 --source github
```

`collect --source` gilt nur für `university` (Quellschlüssel oder Gruppe, z. B. `ude_forschung`, `ude`); für andere Collector ist es ein Konfigurationsfehler (Exit-Code 2).

Alternativ zur installierten CLI kann `python -m app.cli ...` verwendet werden. `python scripts/initialize_database.py` führt `database init` aus; `python scripts/run_collector.py` delegiert an die CLI. Collector-Läufe geben JSON-Ergebnisse aus. Exit-Codes: `0` erfolgreich, `10` partiell, `1` fehlgeschlagen, `2` Konfiguration, `3` Datenbank.

`database init` wendet Alembic-Migrationen bis `head` an. `database status` prüft Verbindung, Migrationstand und Tabellenzähler. Die CLI erstellt das Schema nicht neben Alembic direkt aus SQLAlchemy-Metadaten.

## 7. Tests und wichtige Sicherheitsaspekte

```powershell
python -m pytest
python -m pytest tests\adapters\test_github.py tests\ingestion\test_pipeline.py
python -m pytest -m db
```

Die Pytest-Konfiguration in [`pyproject.toml`](pyproject.toml) schließt standardmäßig mit `-m 'not live'` Tests aus, die reale externe Dienste aufrufen. Adapter- und HTTP-Tests verwenden HTTP-Mocks/Fixtures; DB- und Migrationstests sind mit `db` markiert und überspringen sich, wenn die konfigurierte Testdatenbank nicht erreichbar ist.

**Achtung:** Die DB-Fixture in [`tests/conftest.py`](tests/conftest.py) löscht vor den DB-Tests das `public`-Schema der unter `TEST_DATABASE_URL` erreichbaren Datenbank und erstellt es neu. Führe DB-Tests daher ausschließlich gegen eine entbehrliche, dedizierte Testdatenbank aus.

Bei Änderungen sollen passende Parser-, Adapter-, Pipeline- und/oder Migrationstests ergänzt oder angepasst werden. Nutze Fixture-Dateien in `tests/fixtures/` für repräsentative API-, XML- und HTML-Antworten; verwende keine echten Tokens oder produktiven Daten in Fixtures.

## 8. Muster zum Erweitern

### Neuen API-/HTML-Collector ergänzen

1. Adapter unter `app/adapters/` von `BaseAdapter` ableiten; stabilen Collector-Namen und `SourceSpec` festlegen.
2. `fetch()` als Iterator von `RawRecord` implementieren. Externe IDs müssen stabil und innerhalb der Quelle eindeutig sein; Pagination, Grenzen, Retries, Rate Limits, Terms und gegebenenfalls `robots.txt` beachten.
3. `normalize()` ausschließlich aus verfügbaren Quelldaten ein `NormalizedBundle` bauen. Unbekannte Werte nicht erfinden; optionalen Feldern `None` lassen.
4. Nur belegte Beziehungen erstellen; schwache/inferierte Hinweise als `UNVERIFIED` markieren.
5. Adapter in `app/adapters/registry.py` eintragen und passende Konfiguration in den bestehenden YAML-Dateien ergänzen.
6. HTTP- und Adaptertests mit Mock-Transporten/Fixtures schreiben; Idempotenz, Fehler, Pagination, Dry-Run und Cursorverhalten testen.

Für eine zusätzliche Universität zuerst einen passenden vorhandenen Connector und die `universities.sources`-Konfiguration verwenden (Vorlage: die UDE-Einträge). Robots.txt und Nutzungsbedingungen prüfen und die Quelle mit `enabled: false` belassen, solange etwas unklar ist. Einen Plugin-Hook nur hinzufügen, wenn die generischen Connectoren nicht ausreichen.

### Datenbankschema ändern

1. SQLAlchemy-Modelle in `app/database/models.py` ändern.
2. Eine neue Alembic-Revision erzeugen und prüfen, dass Upgrade und Downgrade korrekt sind; bestehende Migrationen nicht nachträglich umschreiben, sobald sie als geteilt gelten.
3. Migrationstests ausführen und sicherstellen, dass `compare_metadata` keine unbeabsichtigte Differenz findet.

Bei Persistenzänderungen auch Constraints, Quell-Provenienz, Upsert-Idempotenz und bestehende Datensätze berücksichtigen. Schreiblogik gehört in `IngestionRepository`, nicht in einzelne Adapter.

## 9. Verzeichnisübersicht

| Pfad | Inhalt |
| --- | --- |
| `app/cli.py` | Typer-CLI, Collector-Ausführung, DB-Status und Run-Historie |
| `app/adapters/` | Quellenadapter, Registrierung und Hochschul-Connectoren |
| `app/config/` | Settings sowie YAML-Quellen- und Suchkonfiguration |
| `app/database/` | Verbindung, SQLAlchemy-Modelle, Repository und Alembic-Migrationen |
| `app/http/` | Gemeinsamer höflicher HTTP-Client mit Retry-/Robots-Logik |
| `app/ingestion/` | Pydantic-Typen für Rohdatensätze, Bundles und Ergebnisse |
| `app/normalization/` | Wiederverwendbare Normalisierung für Personen, Organisationen, Texte und Publikationen |
| `app/utils/` | Zeit-/Datumsfunktionen, Hashing und Logging |
| `scripts/` | Kleine Einstiegsskripte, die an die CLI delegieren |
| `tests/` | Adapter-, Pipeline-, Datenbank-, HTTP- und Normalisierungstests |
| `docker-compose.yml` | Lokaler PostgreSQL-Dienst für Entwicklung und Tests |
| `pyproject.toml` | Paketmetadaten, Abhängigkeiten, Console-Script und Pytest-Konfiguration |
| `alembic.ini` | Alembic-Migrationspfad und Logging-Konfiguration |

## 10. Leitlinien für Änderungen durch Agenten

- Lies vor Änderungen die relevanten Implementierungen und Tests; halte Änderungen eng am Auftrag.
- Bevorzuge bestehende gemeinsame Typen, Normalisierer, HTTP- und Repository-Helfer gegenüber parallel implementierter Logik.
- Halte Datenquellen, externe IDs und Cursor getrennt; führe nicht stillschweigend quellenübergreifende Entity-Merges ein.
- Bewahre Rohdaten, Provenienz und bisherige Fehlersemantik. Keine stillen Fallbacks, die einen fehlgeschlagenen Abruf als erfolgreichen leeren Lauf ausgeben.
- Aktualisiere direkt betroffene Tests und Dokumentation; führe den kleinsten passenden Testumfang aus.
- Committe keine Secrets, lokalen `.env`-Dateien, personenbezogenen Rohdaten oder privaten Zugangsdaten.
- Gib Werte aus `.env` (Tokens, Keys, Passwörter, E-Mail-Adressen) weder in Terminalausgaben noch in Dateien aus; prüfe nur, ob sie gesetzt sind.
- Rufe keine sehr großen Seiten ab (z. B. die UDE-Feed-Übersicht `feeds.php`) und halte bei Live-Prüfungen Abstände und Limits ein.

## 11. Recherchierte Quellen (Stand 2026-11-20)

Welche externen Quellen für die Entwicklung herangezogen oder vom Code abgerufen werden. „Live geprüft“ bedeutet: im Rahmen der Entwicklung real abgerufen (UDE am 2026-11-20 mit wenigen, gedrosselten Anfragen). Alle anderen Einträge sind die im Code hinterlegten Basis- bzw. Terms-URLs und wurden hier nicht erneut inhaltlich bewertet.

### Universität Duisburg-Essen (live geprüft)

| Quelle | URL | Verwendung / Befund |
| --- | --- | --- |
| Forschungs-RSS | https://www.uni-due.de/rss/forschung.rss | Aktiver Collector `ude_forschung`; Live-Dry-Run und gespeicherter Lauf (5 Datensätze, zweiter Lauf idempotent) |
| Allgemeiner News-RSS | https://www.uni-due.de/rss/aktuell.rss | Konfiguriert als `ude_aktuell`, deaktiviert |
| RSS-Übersicht | https://www.uni-due.de/de/presse/feeds.php | Quelle der Feed-URLs; Seite sehr groß, nicht erneut komplett laden |
| GUIDE (Gründungszentrum) | https://www.uni-due.de/guide/ | Konfiguriert als `ude_guide`, deaktiviert; nur Titel und Meta-Beschreibung; nicht live abgerufen, nur mit Fixtures getestet |
| robots.txt | https://www.uni-due.de/robots.txt | Wird vor jedem Abruf beachtet; sperrt `GPTBot` |
| Sitemap | https://www.uni-due.de/sitemap.xml | Valides `urlset`, genau 5.000 URLs, davon 6 unter `/guide/`; wird vor Nutzung validiert |

Keine Nutzungs- oder Lizenzbedingungen für automatisierte Weiterverwendung der UDE-Inhalte gefunden; deshalb sind `ude_aktuell` und `ude_guide` aus.

### Weitere konfigurierte Quellen (in `sources.yaml` bzw. `SourceSpec`)

| Collector | Basis-URL | Hinterlegte Terms-/Limit-Seite |
| --- | --- | --- |
| `openalex` | https://api.openalex.org | https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication |
| `github` | https://api.github.com | https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms |
| `arxiv` | https://export.arxiv.org/api | https://info.arxiv.org/help/api/tou.html (höchstens 1 Anfrage je 3 s) |
| `huggingface` | Hub-API von huggingface.co (im Entwicklungsnetz nicht erreichbar, nur mit Mocks getestet) | https://huggingface.co/terms-of-service |
| `exist` | https://exist.de (Programmseiten und Erfolgsgeschichten aus der Sitemap) | https://exist.de/datenschutz/ |
| `university` / KIT | https://kit.edu/pi.rss | – |
| `university` / TU Darmstadt | https://www.tu-darmstadt.de/universitaet/aktuelles_meldungen/neues_aus_der_tu_rss.de.rss | – |

Beim Hinzufügen oder Ändern einer Quelle diesen Abschnitt mit URL, Prüfdatum und Befund (Terms, `robots.txt`, Limits) aktualisieren.
