# StartUp-Finder – Projektwissen und verbindliche Hinweise für Coding-Agenten

Diese Datei beschreibt den Produktkontext, den verifizierten Stand des Repositories und die Regeln für Änderungen. Sie ist Orientierung, aber nie Ersatz für den aktuellen Code, Tests, Konfigurationen und Migrationen. Behaupte keine Funktion als implementiert, wenn Code und gegebenenfalls Tests sie nicht belegen.

## 1. Produktidentität und Vision

**Produktname: StartUp-Finder**

> Build a sourcing engine that spots upcoming startups from the traces they leave long before their funding round.

StartUp-Finder soll potenzielle Start-ups und frühe Gründungsvorhaben anhand öffentlicher Spuren früh erkennen und nachvollziehbar prüfen. Im Mittelpunkt steht nicht die größtmögliche Sammlung von Datensätzen, sondern die spätere Identifikation und Validierung aussichtsreicher Kandidaten.

Relevante Spuren können aus Forschung und Publikationen, Hochschulen und Forschungsgruppen, Technologietransfer und Spin-offs, Entwickler- und Open-Source-Ökosystemen, Forschungs- und Förderprojekten, frühen Unternehmensaktivitäten sowie öffentlich dokumentierten Finanzierungsereignissen stammen.

`ventureradar-ingestion`, `ventureradar`, `VentureRadar-Ingestion`, Modul-, Tabellen- und Datenbanknamen sind derzeit technische Bezeichnungen im Code. Nicht eigenmächtig umbenennen. VentureRadar ist hier ein historischer technischer Paket-/CLI-Name; **StartUp-Finder** ist die Produktidentität. Der aktuelle Code implementiert eine Ingestion- und frühe Signalverarbeitung, keine vollständige Startup-Sourcing-Plattform.

## 2. Umsetzungsstand und Produktphasen

Die folgende Matrix trennt belegte Funktionalität von freigegebenen Entwicklungszielen:

| Stufe | Inhalt | Stand im Repository |
|---|---|---|
| 1. Data Ingestion | Öffentliche bzw. manuell bereitgestellte Quelldaten erfassen, normalisieren, mit Provenienz speichern | Implementiert für `openalex`, `arxiv`, `github`, `huggingface`, `exist`, `university`, `cordis` und `manual_import`; Umfang und Live-Verifizierungsgrad sind quellenabhängig. |
| 2. Early-Signal Discovery | Deterministische Einordnung vorhandener Signals/Observations und begrenzte Text-Erwähnungsregeln | Implementiert und durch Unit-/CLI-/SQL-Tests abgedeckt; keine Kandidatenerkennung, Startup-Klassifikation oder Finanzierungsaussage. |
| 3. Candidate Discovery | Vorläufige Kandidaten aus zusammenhängenden Hinweisen und mehreren Quelldatensätzen bilden | **Als Entwicklungsziel freigegeben, noch nicht implementiert.** |
| 4. Candidate Validation | Unternehmensidentität und externe Finanzierungsrunden unabhängig recherchieren | **Als Entwicklungsziel freigegeben, noch nicht implementiert.** Keine Rechercheausführung oder Validierung in diesem Auftrag. |
| 5. Knowledge Graph | Beziehungen zwischen Unternehmen, Personen, Forschung, Projekten, Organisationen, Repositories und Signalen auswerten | Relationales, quellenbelegtes Entity-/Relationship-Modell vorhanden; kein vollständiger Knowledge-Graph-Dienst, keine globale Entity Resolution und keine Graph-Oberfläche. |
| 6. Startup Discovery Engine | Kandidaten anhand zeitlicher Signale und validierter Fakten transparent priorisieren | Langfristiges Produktziel; Klassifikation, Trendanalyse, Ranking, Dashboard und UI sind nicht implementiert. |

Weitere Abgrenzungen:

- Es gibt keine Candidate- oder Funding-Validation-Module, Datenbanktabellen, CLI-Befehle, Exporte oder Candidate-Artefakte im Repository. Die vorgesehenen Dateinamen stehen in [Abschnitt 7](#7-candidate-discovery--freigegebenes-entwicklungsziel-noch-nicht-implementiert).
- `EntityType.STARTUP` und die LLM-Kategorie `startup_activity` sind lediglich vorhandene Typ-/Schemawerte. Sie implementieren **keine** Startup-Klassifikation.
- `NEW_FUNDING_PROJECT` und `FUNDED_BY` stehen im aktuellen Modell für Förder- bzw. Projektkontext, nicht für eine externe Equity-Finanzierungsrunde.
- Die Erlaubnis, Candidate Discovery und Candidate Validation künftig zu entwickeln, macht sie nicht zu vorhandenem Funktionsumfang. Dafür keine Tabellen, Felder, Enums oder Funktionen als bereits implementiert dokumentieren.

## 3. Produktbegriffe und Finanzierungsregeln

### 3.1 Unternehmen und Finanzierung getrennt bewerten

Ein späterer Kandidatenprozess muss unabhängig voneinander beantworten:

1. Ist ein eigenständiges Unternehmen bestätigt?
2. Ist eine externe Finanzierungsrunde öffentlich belegt?

Die folgenden Werte sind **fachliches Zielvokabular**, keine Enums oder Datenbankwerte im aktuellen Code.

#### Vorgesehener Company Status

| Zielwert | Bedeutung |
|---|---|
| `company_confirmed` | Unternehmen ist durch belastbare Informationen bestätigt. |
| `pre_company_project` | Konkretes Gründungs-/Ausgründungsvorhaben erkennbar, aber kein Unternehmen bestätigt. |
| `research_project_only` | Bisher ausschließlich ein Forschungs- oder Technologieprojekt erkennbar. |
| `company_not_found` | Trotz dokumentierter Recherche wurde kein Unternehmen identifiziert. |
| `company_unclear` | Unternehmensidentität oder Zuordnung ist nicht ausreichend geklärt. |

#### Vorgesehener Funding Status

| Zielwert | Bedeutung |
|---|---|
| `funding_round_confirmed` | Mindestens eine externe Finanzierungsrunde ist öffentlich belegt. |
| `no_public_round_found` | Bei dokumentierter Recherche wurde keine öffentliche Runde gefunden; das beweist nicht, dass keine Finanzierung stattgefunden hat. |
| `grant_only_no_public_round_found` | Öffentliche Förderung gefunden, aber keine öffentliche Equity-Runde gefunden. |
| `funding_unclear` | Hinweise vorhanden, die Finanzierungssituation ist aber nicht ausreichend geklärt. |
| `not_applicable` | Es gibt noch kein eindeutig identifizierbares Unternehmen, dessen Finanzierung geprüft werden kann. |

Unternehmens- und Finanzierungsstatus dürfen nicht zu einem einzigen Feld oder einer einzigen Schlussfolgerung verschmolzen werden. Ein Unternehmen kann bestätigt sein, obwohl sein Funding-Status unklar ist.

### 3.2 Was eine Finanzierungsrunde ist – und was nicht

**Nicht automatisch als Startup-Finanzierungsrunde behandeln:**

- EXIST-Förderungen und andere Förderprogramme;
- CORDIS-Projektzuschüsse;
- öffentliche Zuschüsse und Forschungsbudgets;
- Stipendien und Wettbewerbspreise.

Diese können wertvolle Frühphasensignale sein, belegen aber für sich allein keine Equity-Finanzierung. `NEW_FUNDING_PROJECT`, Förderprogramme und `FUNDED_BY` bleiben daher klar von einer Venture-Finanzierungsrunde getrennt.

Mögliche externe Eigenkapitalfinanzierungen umfassen Angel Investments, Pre-Seed, Seed, Series A und spätere Runden sowie Corporate-Venture-Capital-Investments. Wandeldarlehen und SAFE-Instrumente sind als eigene Finanzierungsinstrumente zu dokumentieren; ohne Quellenbeleg nicht als klassische Runde bezeichnen.

`no_public_round_found` bedeutet ausschließlich: Die dokumentierte Recherche hat keine öffentliche Runde ergeben. Es beweist **nicht**, dass nie Kapital aufgenommen wurde. Nicht öffentliche Angel-Investments, private Beteiligungen und vertrauliche Finanzierungsinstrumente lassen sich dadurch nicht ausschließen.

## 4. Bestehende Architektur und Datenfluss

Technischer Kern ist Python 3.12+, Typer, Pydantic/Pydantic Settings, SQLAlchemy 2, PostgreSQL/JSONB, Alembic, HTTPX, Tenacity, BeautifulSoup und feedparser. Abhängigkeiten und CLI-Entry-Point stehen in [`pyproject.toml`](pyproject.toml).

Die Pipeline wird von [`app/adapters/base.py`](app/adapters/base.py) orchestriert:

1. Ein Adapter liest Rohdaten in `fetch()` mit quellenabhängiger Pagination, Zeitfenstern und optionalen Sync-Cursorn.
2. Jeder Datensatz wird als `RawRecord` mit stabiler quellenbezogener `external_id`, Record-Typ, Original-Payload, optionaler URL und Datumsangaben abgebildet.
3. Der Rohdatensatz wird zuerst in `source_records` upserted. Ein Fehler bei Normalisierung oder Validierung soll so die Quelldaten nicht verwerfen.
4. `normalize()` erzeugt ein `NormalizedBundle` aus Entities, Relationships, Signals und Observations.
5. `validate()` kontrolliert Bundle-Referenzen und Mindestinhalte; lokale Relationship-/Signal-/Observation-Keys müssen auf Entities des Bundles zeigen.
6. [`app/database/repositories.py`](app/database/repositories.py) persistiert mit Upserts und Provenienz.
7. Ein Lauf wird als `IngestionRun` abgeschlossen. Vorgemerkte Sync-Cursor werden nur bei vollständig erfolgreichem Lauf fortgeschrieben.

Ein Datensatzfehler wird gezählt und kann übersprungen werden; ein Fetch-Fehler beendet den Lauf. Bereits committete Daten bleiben erhalten. Die Verarbeitung committet spätestens nach jeweils 50 Datensätzen. `--dry-run` ruft Quelle und Normalisierung auf, schreibt aber keine Roh- oder normalisierten Daten und keine Cursor. Ein limitierter Lauf schreitet den Cursor nicht fort.

`PoliteHttpClient` in [`app/http/client.py`](app/http/client.py) implementiert Timeout, User-Agent, Host-Drosselung, Retry für Transportfehler und ausgewählte HTTP-Fehler sowie optionale `robots.txt`-Prüfung. Bei aktivierter Robots-Prüfung schlägt ein nicht erreichbares `robots.txt` fail-closed fehl. Quelleigene Raten, Lizenzbedingungen und Inhaltsgrenzen gelten zusätzlich.

## 5. Gemeinsames Datenmodell, Provenienz und Graph-Abgrenzung

Typen und erlaubte Domainwerte stehen in [`app/domain.py`](app/domain.py), Pydantic-Modelle in [`app/ingestion/types.py`](app/ingestion/types.py), SQLAlchemy-Modelle in [`app/database/models.py`](app/database/models.py).

| Konzept/Tabelle | Zweck |
|---|---|
| `sources` | Quellmetadaten (`source_name`, Typ, URL und Terms-URL). Der Primärschlüssel ist eine beim Einfügen erzeugte UUID, kein festes Collector-Kürzel. |
| `ingestion_runs` | Status, Zeitpunkte, Zähler und Fehler eines Collector-Laufs |
| `source_records` | Original-Payload, externe ID, Hash, URL und „first/last seen“-Zeit |
| `source_record_revisions` | Vorherige Roh-Payload bei inhaltlicher Änderung |
| `entities` | Normalisierte Personen, Organisationen, Universitäten, Forschungsprojekte, Publikationen, Repositories, Modelle, Datensätze, Spaces, Startups, Events, Förderprogramme und Technologien |
| `entity_aliases` | Namen sowie source-scoped Identifier wie DOI, ORCID, ROR, URL oder Login |
| `entity_source_records` | Provenienz zwischen normalisierter Entity und Quell-Datensatz |
| `relationships` | Gerichtete, typisierte und quellbelegte Beziehungen |
| `signals` | Signale mit Quelle und Zeitbezug |
| `observations` | Zeitreihe numerischer Kennzahlen |
| `sync_state` | Cursor/Watermark je Quelle und Abfragebereich |
| `llm_analyses` | Versionierte, validierte LLM-Analyseversuche; erst durch Migration `0002` ergänzt |

Wichtige Regeln:

- Eine `Source` wird im Ingestion-Code über ihren Namen (`source_name`, z. B. `university`) identifiziert. Source-UUIDs entstehen zur Laufzeit in der Datenbank. Einzelne Hochschul-Feed-Keys wie `ude_forschung` sind Konfigurations-/Record-Identitäten; sie erzeugen keine eigenen Source-Zeilen. Erfinde keine festen Source-UUIDs.
- Entities werden anhand eines quellenbezogenen `SOURCE_IDENTIFIER`-Alias gefunden. Gleiche Namen oder externe Aliaswerte führen nicht automatisch zu einem quellenübergreifenden Merge.
- `EntityDraft.is_primary=True` kennzeichnet die führende Beschreibung aus dem Datensatz. Referenzierte Entities füllen eher Lücken, statt vorhandene Primärdaten zu überschreiben.
- Roh-Payload und normalisierte Daten bleiben getrennt. Beziehungen, Signale und Messwerte müssen zu ihrem `source_record_id` zurückverfolgbar sein.
- Ein Adapter kann volatile Felder aus dem Content-Hash ausnehmen oder mit `hash_basis` nur stabile Felder hashen. Änderungen an solchen Messwerten gehören in Observations; inhaltliche Änderungen sichern den vorherigen Rohdatensatz als Revision.
- Observations werden je Entity/Kennzahl nach UTC-Stunde oder -Tag gebucktet (`OBSERVATION_BUCKET`).
- Unbekannte Werte bleiben `NULL`; Daten und Ereignisdaten nicht aus Veröffentlichungsdaten ableiten. Beziehungen mit unsicherer Grundlage als `UNVERIFIED` markieren.

Das relationale Modell stellt eine graphartige Basis mit Entities, Kanten und Provenienz bereit. Es gibt jedoch keinen separaten Graph-Store, keine globale Entity Resolution, keine Candidate-Knoten/-Tabellen, keine vollständige Graphanalyse und keine UI. Nicht aus der Existenz von `relationships` auf eine implementierte Knowledge-Graph-Anwendung schließen.

Migrationen:

- [`app/database/migrations/versions/20261120_0001_initial_schema.py`](app/database/migrations/versions/20261120_0001_initial_schema.py) legt die Basis- und Graph-Grundlagentabellen für Ingestion an.
- [`app/database/migrations/versions/20261120_0002_llm_analyses.py`](app/database/migrations/versions/20261120_0002_llm_analyses.py) ergänzt ausschließlich `llm_analyses`; sie enthält keine Candidate- oder Funding-Validation-Tabellen.
- Normale Ingestion und Early-Signal-Discovery verwenden keine LLM-Analysen und erfordern fachlich keine LLM-Ausführung. `database init` führt allerdings technisch `alembic upgrade head` aus und würde alle vorhandenen Migrationen einschließlich `0002` anwenden.

## 6. Ingestion-Collector und Quellen

Registrierung und CLI-Namen stehen in [`app/adapters/registry.py`](app/adapters/registry.py). Laufende Sammelbereiche und Parameter stehen in [`app/config/search_terms.yaml`](app/config/search_terms.yaml) sowie [`app/config/sources.yaml`](app/config/sources.yaml). Die Source-ID ist – wo in der Tabelle angegeben – der Collector-/`source_name`-Schlüssel; kein Schlüssel ist eine UUID.

| Source-ID / Collector | Status und Umfang | Begrenzungen, Datenqualität und Einschränkungen |
|---|---|---|
| `openalex` | Registrierter API-Collector; Werke mit deutschen Institutionsbezügen nach Themenbegriffen | 100 Datensätze pro Seite, Startfenster 30 Tage, 7-Tage-Lookback, maximal 100 Autor:innen pro Werk werden normalisiert. Ohne API-Key Basic-Paging bis 10.000 Ergebnisse pro Abfrage; der Key-freie Zugriff ist budgetbegrenzt. Die vorhandene README nennt widersprüchliche konkrete Tagesbudgets; vor einer belastbaren Angabe extern prüfen. OpenAlex-Adapter beschreibt die Daten als CC0. Späte Indexierung älterer Publikationen kann durch publication-date-basierte Cursor übersehen werden. |
| `github` | Registrierter Collector, benötigt `GITHUB_TOKEN`; Topic-Suche, keine Geografie | Sucht in 7-Tage-Fenstern, splittet zu große Fenster, max. 100 Repositories pro Query/Lauf, mindestens 3 Stars, refreshed 25 bekannte Repositories. Search wird mit 2,1 s Abstand gedrosselt; Core-/Search-Rate-Limits werden behandelt, Wartezeiten über fünf Minuten führen zum Abbruch. Activity-Abruf max. 30 Items je Typ. Keine Git-Autorennamen oder E-Mail-Adressen; Discussions werden nicht gesammelt. |
| `arxiv` | Registrierter API-Collector nach Kategorien; keine Länderfilterung | max. 1 Anfrage alle 3 Sekunden, initial 3 Tage, 1-Tages-Lookback, max. 1.000 Ergebnisse pro Lauf, oldest-first. Metadaten laut Adapter CC0; PDFs werden nicht gespeichert, höchstens als URL referenziert. Autoren haben keine stabilen Quell-IDs. |
| `huggingface` | Registrierter Hub-Collector für Modelle, Datensätze, Spaces; Tag-/Suchscope konfiguriert | max. 100 Items pro Query, max. 50 Namespace-Lookups, Kartenabruf optional und auf 20.000 Zeichen begrenzt. Öffentliche Endpunkte möglich, `HF_TOKEN` optional. Entwicklungsnetz-Erreichbarkeit war am 2026-11-20 nicht gegeben; nur Mock-Tests. Tag-Formate und Organisationsendpunkte sind vor Live-Betrieb zu bestätigen. |
| `exist` | Registrierter HTML-/Sitemap-Collector für Erfolgsgeschichten und Programmseiten | Liest Sitemap, verwendet WordPress-API nur für Publikationsdaten, 2 s Host-Abstand, 7-Tage-Lookback. Programmbeziehungen entstehen aus Keywords und sind `UNVERIFIED`. Keine Personenerkennung; strukturierte Förder-/Projektstartdaten bleiben unbekannt. |
| `university` | Registrierter Sammel-Collector; Quellenstatus siehe Quell-Keys weiter unten | RSS/Atom, validierte Sitemap+JSON-LD, JSON-LD, Page-Metadata oder CSS-Selektoren. Explizite Quellen, kein blindes Crawling. Robots-Prüfung für jeden Abruf. RSS standardmäßig 2 s Abstand; Nicht-RSS mindestens 10 s pro Host. Teaser und HTML-Felder sind begrenzt, Volltexte/Autoren nicht pauschal gespeichert. |
| `cordis` | Registrierter Collector über den öffentlichen EURIO-SPARQL-Endpunkt; Standard-Land `DE` | Nur read-only `SELECT`; 10 s Mindestabstand, Seite standardmäßig 25/max. 50 Projekte, 2 Requests pro Seite, max. 1.000 Projekte pro Lauf. Erstabruf 90 Tage, danach 60-Tage-Overlap, da kein Änderungsdatum genutzt wird. Nur Beteiligte aus konfigurierten Ländern. CC BY 4.0; Attribution „© European Union, CORDIS“ wird laut Adapter mitgeführt. Organisationstyp bleibt generisch `organization`. Keine Bulk-ZIPs oder Fallback-Endpunkte. |
| `manual_import` | Registrierter lokaler CSV-/JSON-Import; kein Netzwerkzugriff | Standardverzeichnis `data/manual_imports/`; max. 5 MB und 5.000 Zeilen je Datei. LinkedIn-URLs werden nur syntaktisch validiert und nie geöffnet. Gültige Dateien werden nach erfolgreichem Import verschoben; `processed`-Retention 30 Tage, `failed` 14 Tage. Fehlermeldungen nennen keine Zellinhalte. Enthält dennoch personenbezogene Daten und ist dauerhaft von der LLM-Allowlist ausgeschlossen. |

### 6.1 Hochschul-Quell-Keys und Status

Alle aktiven und deaktivierten Feed-/Seiten-Keys gehören zum Sammel-Collector `university`:

| Quell-Key | Gruppe | Connector / Art | Konfigurationsstatus |
|---|---|---|---|
| `kit` | – | RSS / `press_release` | aktiv (implizites `enabled: true`) |
| `tu_darmstadt` | – | RSS / `news` | aktiv (implizites `enabled: true`) |
| `ude_forschung` | `ude` | RSS / `news` | aktiv |
| `ude_aktuell` | `ude` | RSS / `news` | deaktiviert |
| `ude_guide` | `ude` | `page_metadata` + validierte Sitemap / `organization_unit` | deaktiviert |

University-Source-Keys prägen die `external_id` der Datensätze und den Cursor-Scope; alle diese Datensätze gehören zur Source `university`. `--source` akzeptiert beim Collector `university` einen Quell-Key oder eine Gruppe; die UDE-Gruppe schlägt fehl, solange deaktivierte Mitglieder explizit enthalten sind. Generische Testvorlagen sind kommentiert und nicht aktiv.

Für UDE sind Quellenprüfung und einige Laufbefunde in der vorhandenen Projektdokumentation auf den **20.11.2026** datiert; sie wurden bei dieser AGENTS-Überarbeitung nicht erneut extern geprüft:

- `ude_forschung`: Forschungs-RSS, aktiv; höchstens 200 Items und initial 90 Tage, 10 s Abstand, `CONTACT_EMAIL` erforderlich. Laut bestehender Dokumentation wurden nur Feed-Metadaten und ein maximal 500 Zeichen langer Teaser gespeichert, keine Volltexte, Autoren, Enclosures oder Bilder.
- `ude_aktuell` und `ude_guide`: deaktiviert, bis Nutzungsbedingungen geklärt sind. Die vorhandene Dokumentation nennt eine `GPTBot`-Sperre in `robots.txt`; sie ist kein Grund, den Crawler für KI-Training zu nutzen.
- `ude_guide`: nur Titel/Meta-Beschreibung; Sitemap wird vor Nutzung geprüft und auf `/guide/` begrenzt. Die historische Prüfung nannte genau 5.000 Sitemap-URLs und sechs `/guide/`-URLs; dies kann unvollständig oder inzwischen veraltet sein.
- Live geprüft laut bestehender Dokumentation: UDE-Forschungs-RSS mit gedrosseltem Dry-Run und gespeichertem, idempotentem Lauf; GUIDE nur Fixture-/Mock-Test. Die große Feed-Übersichtsseite `feeds.php` nicht ungezielt abrufen.

### 6.2 Forschungsstand der Quellen und ausgeschlossene Quellen

Die bestehende Projektdokumentation hält folgende Befunde unter Prüfdatum **2026-11-20** fest. Diese Angaben wurden in diesem Auftrag nicht erneut live verifiziert; sie sind Hinweise zur Quellenprüfung, keine Rechtsberatung:

- Hinterlegte Source-/Terms-Referenzen (aus Code/README; keine erneute externe Prüfung in diesem Auftrag):

  | Collector/Quelle | Hinterlegte Referenz |
  |---|---|
  | OpenAlex | API `https://api.openalex.org`; Rate-Limit-/API-Information `https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication` |
  | GitHub | API `https://api.github.com`; API-Terms `https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms` |
  | arXiv | API `https://export.arxiv.org/api`; Terms `https://info.arxiv.org/help/api/tou.html` |
  | Hugging Face | Hub `https://huggingface.co`; Terms `https://huggingface.co/terms-of-service` |
  | EXIST | `https://exist.de`; hinterlegte Rechts-/Datenschutzreferenz `https://exist.de/datenschutz/` |
  | KIT | RSS `https://kit.edu/pi.rss`; SourceSpec hinterlegt keine Terms-URL |
  | TU Darmstadt | RSS `https://www.tu-darmstadt.de/universitaet/aktuelles_meldungen/neues_aus_der_tu_rss.de.rss`; SourceSpec hinterlegt keine Terms-URL |
  | UDE | Forschungs-RSS `https://www.uni-due.de/rss/forschung.rss`, allgemeiner RSS `https://www.uni-due.de/rss/aktuell.rss`, GUIDE `https://www.uni-due.de/guide/`; laut vorhandenem Recherchebefund keine Bedingungen zur automatisierten Wiederverwendung gefunden |
  | CORDIS | SPARQL `https://cordis.europa.eu/datalab/sparql-api`; Rechts-/Lizenzreferenz `https://cordis.europa.eu/about/legal`, SPARQL-Hilfe `https://cordis.europa.eu/about/sparql` |
  | Manual Import | lokale Dateien; kein externer Abruf und keine Source-Terms-URL |

- CORDIS/EURIO: laut Dokumentation am 2026-11-20 geprüft (Robots erlaubt den verwendeten Endpoint, JSON-Antwort, Offset-Paging, keine Authentifizierung; etwa 24.000 Projekte mit deutscher Beteiligung). Der Endpoint dokumentiert keine Limits; aktuelle Konfiguration drosselt vorsorglich.
- `foerderdatenbank.de`: nicht implementiert; laut Recherche sperrt `robots.txt` die Suchpfade und setzt `Crawl-delay: 30`.
- Fraunhofer-RSS: kommerzielle Nutzung laut damaligem Impressum nur mit schriftlicher Genehmigung. Max-Planck-Gesellschaft: alle Rechte vorbehalten. DLR: Bedingungen auf Presse/Rundfunk gerichtet; Bilder CC BY-NC-ND.
- Leibniz-RSS mischt nach damaliger Prüfung Institutsmeldungen und Magazin; Hamburg-Atomfeed: keine Bedingungen gefunden. STARTPLATZ: Vervielfältigung laut Impressum nur mit schriftlicher Zustimmung.
- SPRIND, UnternehmerTUM, TUM, Max Planck Innovation, Deutscher Gründerpreis und Gründungswoche: trotz technisch offener Robots keine Bedingungen für automatisierte Wiederverwendung gefunden; daher nicht als Collector implementiert.
- GEPRIS: `robots.txt` sperrt laut Befund alle Pfade. HTGF: damalige Content-Signale `ai-input=no`, `ai-train=no`. Bundesanzeiger: automatisierter Abruf laut Befund untersagt.
- Kein Event-Collector ist implementiert. Quellen mit ungeklärten Rechten/Terms nicht eigenmächtig aktivieren oder ergänzen.

Bei Änderungen an Quellen: Basis- und Terms-URL, Prüfdatum, Nutzungsbedingungen, Attribution, Robots, Raten und Datenminimierung prüfen; Status im Quellkonfigurationsabschnitt aktuell halten. Die bloße öffentliche Abrufbarkeit ist keine Wiederverwendungserlaubnis. Für manuell bereitgestellte Daten gelten dieselben Datenschutz- und Nutzungsregeln.

## 7. Candidate Discovery – freigegebenes Entwicklungsziel, noch nicht implementiert

Candidate Discovery soll aus bestehenden Rohdatensätzen und frühen Signalen mögliche Kandidaten bilden, ohne auf einen vollständig implementierten Knowledge Graph zu warten. Mögliche Eingaben sind:

`source_records`, `entities`, `entity_aliases`, `entity_source_records`, `relationships`, `signals` und `observations`.

Potenzielle Hinweise können Publikationen und Forschungsergebnisse, Universitätszugehörigkeit, Repositories und Entwickleraktivität, EXIST-Gründungsvorhaben, Forschungsprojekte mit Verwertungspotenzial und Technologietransfer umfassen. Ein einzelner Hinweis reicht nicht automatisch für einen Kandidaten. Mehrere zusammenhängende und möglichst unabhängige Quellen sind aussagekräftiger.

Verbindliche Interpretationsregeln:

- Ein Forschungsprojekt ist nicht automatisch ein Unternehmen.
- Ein Repository ist nicht automatisch ein Produkt oder Startup.
- Eine Universität ist nicht automatisch ein Gründerteam.
- Textnennung oder technischer Erfolg ist kein Beweis für Gründung oder Finanzierung.
- Unsichere Identitätszuordnungen sichtbar unsicher halten; keine Sicherheit vortäuschen.
- Candidate Discovery darf globale Entities nicht unkontrolliert zusammenführen oder ändern.
- Quellenübergreifende **Kandidatenzuordnung** ist ein vorläufiger Analysebezug. Sie ist nicht gleichbedeutend mit dauerhafter globaler Entity Resolution oder dem Merge von Entity-IDs.
- Kandidaten müssen auf Quell- und Entity-Belege zurückverweisen; originale Quelldatensätze bleiben unverändert.

Vorgesehene Ergebnisartefakte sind `candidate_discovery.json`, `candidate_validation.json`, `candidate_overview.csv` und `candidate_research_report.md`. Diese Dateien und ihre Erzeugung sind derzeit nicht vorhanden.

Als künftige Discovery-Ausgabe fachlich vorsehen: stabile Candidate-ID, Bezeichnung, Kandidatentyp, Kurzbeschreibung, referenzierte Entity- und Source-Record-IDs, erkannte Signals, Quellenbelege, Begründung, Zeitbezug und Unsicherheiten. Wiederholte Analysen sollen Kandidaten anhand stabiler, nicht von Anzeigenamen oder Reihenfolge abhängiger IDs wiedererkennen und aktualisieren; Änderungen der Evidenz/Zuordnung nachvollziehbar halten, nicht durch wechselnde Namen Duplikate anlegen. Der konkrete Persistenzmechanismus ist noch zu entwerfen. Keine Candidate-Tabellen oder Spalten ohne explizite Schemaentscheidung und Migration hinzufügen.

## 8. Candidate Validation und Funding Verification – freigegebenes Entwicklungsziel

Candidate Validation muss unabhängig von der ursprünglichen Discovery aktuelle, öffentlich zugängliche Informationen recherchieren. Die bestehende Ingestion-Datenbank allein genügt nicht als Validierung. Die beiden Fragen aus Abschnitt [Produktbegriffe](#3-produktbegriffe-und-finanzierungsregeln) sind getrennt zu beantworten: eigenständiges Unternehmen vorhanden? Externe Runde öffentlich belegt?

Künftige Ergebnisse sollen mindestens festhalten:

- Candidate-ID und geprüfte Unternehmensidentität;
- Company Status und Funding Status als getrennte Werte;
- Unternehmenswebsite und offizielle Quellen;
- Gründungsdatum, nur sofern belegt;
- mögliche Verbindung zur ursprünglichen Forschung oder zum Technologieteam;
- bekannte Investoren, Finanzierungsereignisse, Instrumente, Finanzierungsart und Datum; Betrag nur, wenn öffentlich belegt;
- Fördermittel separat von Equity-Finanzierungen;
- Recherchequellen mit URL, Herausgeber, Veröffentlichungsdatum soweit vorhanden und tatsächlichem Ereignisdatum, sowie Abruf-/Prüfdatum;
- Evidenzqualität, offene Fragen und Unsicherheiten.

Bevorzuge offizielle Unternehmens- und Investorenseiten sowie zuverlässige Nachrichten- und Registerquellen. Verwende mehrere unabhängige Belege, wenn eine belastbare Aussage erforderlich ist. Erfinde keine Fakten. Fehlende Suchtreffer beweisen nicht das Fehlen eines Unternehmens oder einer Finanzierung. Beachte Nutzungsbedingungen, Urheberrecht, Robots-Regeln und Datenschutz der Recherchequellen.

**Kein Validierungsprozess ist derzeit implementiert.** Es gibt keine Finanzierungsstatus-Enums, keine `company_status`-/`funding_status`-Spalten, keine Validierungsadapter, keine CLI-Befehle, keine Kandidaten-Berichte und keinen Finanzierungsrunden-Datensatz. Die geplanten Company-/Funding-Statuswerte in Abschnitt 3 dürfen nicht als aktuelle Code-Enums beschrieben oder verwendet werden, solange sie nicht ausdrücklich implementiert und migriert sind.

## 9. Knowledge Graph

Die Tabellen `entities`, `entity_aliases`, `entity_source_records`, `relationships`, `signals` und `observations` liefern eine relationale Graph-Grundlage mit quellenbezogener Identität und nachvollziehbaren Kanten. Das ist kein vollständiger Graph-MVP: Es gibt keine Candidate Resolution, keinen globalen Cross-Source-Merge, keinen dedizierten Graph-Store, keine Graph-Abfragen/Visualisierung und keine UI.

Candidate Discovery und Candidate Validation sollen konzeptionell ohne Vollständigkeit des Knowledge Graphen nutzbar sein. Sie können vorhandene Relationen und Provenienz lesen; keine globale Identität durch heuristische Namensübereinstimmung herstellen. Eine spätere dauerhafte Entity Resolution benötigt eigene explizite Regeln, Evidenz, Unsicherheitsbehandlung und Schema-/Migrationsfreigabe.

## 10. LLM- und KI-Funktionen

LLM-Analyse ist von deterministischer Early-Signal-Discovery sowie externer Candidate Validation getrennt:

- `app/llm/` enthält ein provider-neutrales Interface, striktes Pydantic-Ausgabeschema, Evidenzvalidierung, Allowlist, Runner und einen lokalen Fake Provider.
- [`app/config/llm_allowlist.yaml`](app/config/llm_allowlist.yaml) enthält `default_policy: deny` und eine leere Quellen-Allowlist. Der Allowlist-Loader verlangt explizite Field-Auswahl, Zweck, Prüfdatum, Reviewer, Terms-Referenz und Review-Zusammenfassung.
- Der aktuelle Runner ruft ausschließlich den lokalen `FakeLLMProvider` ohne Netzwerk-I/O auf und beschränkt ihn auf synthetische Quellen (`synthetic_*`). Reale Quell-Datensätze werden blockiert; `manual_import` ist ausdrücklich und dauerhaft blockiert.
- `ventureradar llm preview` prüft Allowlist-Berechtigung read-only; `ventureradar llm run` kann ausschließlich synthetische, freigegebene Testdaten mit Fake Provider verarbeiten und Ergebnisse persistieren. Es existiert keine echte Provider-Integration. Nicht durch Allowlist-Änderung oder Umgebungsvariable umgehen.
- Jede Evidenz muss auf ein tatsächlich kuratiertes Feld verweisen und wörtlich darin vorkommen. Originaldaten werden nicht geändert. Die Analyse behauptet weder Startup-Status noch Funding, Entity Resolution oder Score.
- Migration `0002` ergänzt `llm_analyses`: Analyse-Hash und Source Record, Analyzer-/Prompt-/Schema-/Provider-/Model-Version, validiertes JSONB-Ergebnis oder sichere Fehlerkategorie, Usage-Werte und Zeitstempel. Erfolgreiche Identitäten sind idempotent; Fehlschläge speichern keine Ergebnis-Payload.

Keine externen Quelldaten an nicht freigegebene LLM-Anbieter senden. Eine Erlaubnis zur Datensammlung ist keine Erlaubnis zur LLM-Weitergabe. Keine echten Provider oder externen API-Aufrufe aktivieren, bevor Datenschutz, Urheberrecht, Anbieterbedingungen, Aufbewahrung und jede Source-/Field-Freigabe ausdrücklich geklärt sind. Keine vollständigen Artikel, unnötigen personenbezogenen Rohdaten oder vollständigen Prompts übertragen oder persistieren. Herkunft und Evidenz jeder KI-Ableitung erhalten. Weitere Implementierungsdetails stehen in [`docs/phase2b4-llm-allowlist.md`](docs/phase2b4-llm-allowlist.md).

## 11. Deterministische Early-Signal Discovery

Discovery-Code steht in [`app/discovery/`](app/discovery/), Detailregeln und Ausschlüsse in [`docs/phase2-signal-contract.md`](docs/phase2-signal-contract.md). Tests liegen in `tests/discovery/`. Die Funktion arbeitet über bereits gespeicherte Signals und Observations; sie ruft keine externen Quellen ab.

```powershell
python -m app.cli discovery preview --limit 100
python -m app.cli discovery preview --source github --limit 100
python -m app.cli discovery run --source university --limit 100
```

- `preview` ist read-only: Quellsignale/Observations klassifizieren und Text-Treffer anzeigen.
- `run` schreibt/reconciliert nur abgeleitete Text-Erwähnungs-Signals. Bestehende Quellsignale werden nicht dupliziert.
- Quellsignale wie `NEW_PUBLICATION`, `NEW_REPOSITORY`, `NEW_RESEARCH_PROJECT`, `NEW_FUNDING_PROJECT`, `NEW_MODEL`, `NEW_DATASET`, `NEW_SPACE`, `NEW_CONTRIBUTOR` und `NEW_PRESS_RELEASE` erhalten eine Kategorie und Interpretation; z. B. ist ein Repository kein Startup und ein öffentlich gefördertes Projekt keine Equity-Runde.
- Einzelne Observations werden je Source und Kennzahl als schwache Forschungs-, Technologie-, Entwickler- oder Organisationsaktivität klassifiziert. Ein einzelner Wert ist kein Trend, Wachstum oder Schwellenereignis.
- Versionierte deterministische Textregeln erzeugen `FOUNDING_ACTIVITY_MENTION`, `SPINOUT_MENTION` und `COMMERCIALIZATION_MENTION` nur in definierten Source-/Record-Kontexten. Negierte Erwähnungen werden teilweise ausgeschlossen. Es bleiben Texttreffer, keine bestätigten Gründungs-, Spin-out-, Produkt-, Verkaufs- oder Startup-Fakten.
- Kein Adapter emittiert derzeit `NEW_PITCH_PRESENTATION`.
- Die Ableitung speichert Regel-ID/-Version, Feld und Trefferbegriff sowie Verweise auf Source-Signal und Source-Record. Wiederholtes Ausführen ist idempotent und reconciliert veraltete, abgeleitete Treffer nur im bearbeiteten Scope.
- `event_date` wird nicht aus einem Publikationsdatum erfunden.

Nicht implementiert: Vergleich von Observations über Zeit als Trendregel, Kandidatenbildung, Cross-Source-Entity Resolution, Funding Verification, Startup-Klassifikation und Ranking.

## 12. Konfiguration, Datenbank und Betriebsregeln

Einstellungen in [`app/config/settings.py`](app/config/settings.py) kommen aus der Umgebung bzw. `.env`; YAML-Quellenkonfigurationen sind im Paket. Wichtige Namen sind `DATABASE_URL`, `DATABASE_URL_DIRECT`, `TEST_DATABASE_URL`, `GITHUB_TOKEN`, `OPENALEX_API_KEY`, `HF_TOKEN`, `CONTACT_EMAIL`, `MANUAL_IMPORT_DIR`, `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_RETRIES`, `LOG_LEVEL`, `LOG_FORMAT` und `OBSERVATION_BUCKET`. `.env` ist git-ignored. Nie Secret-Werte in Ausgaben, Doku oder Commits kopieren; nur prüfen, ob eine benötigte Variable gesetzt ist.

### Neon-Ziel und tatsächliche Codeverdrahtung

**Betriebsfreigabe:** Für freigegebene Neon-Arbeiten ist `DATABASE_URL_DIRECT` das autorisierte Ziel. `DATABASE_URL` nicht ungeprüft als produktives Neon-Ziel annehmen. Keine Connection Strings, Passwörter oder Zugangsdaten ausgeben. Vor jedem Schreibzugriff das Ziel eindeutig und ohne Offenlegung des Werts prüfen.

**Aktuelle technische Verdrahtung (nicht eigenmächtig ändern):**

- `make_engine()` ohne `direct=True` verwendet `DATABASE_URL`.
- Alembic [`app/database/migrations/env.py`](app/database/migrations/env.py) ruft `make_engine(direct=True)` auf; `make_engine` fällt jedoch technisch auf `DATABASE_URL` zurück, wenn `DATABASE_URL_DIRECT` fehlt.
- Collector-, Discovery-, LLM-, History- und Status-CLI nutzen `make_engine()` ohne `direct=True`, also `DATABASE_URL`.
- Für freigegebene Collector-Unterprozesse muss daher der effektive Wert von `DATABASE_URL` ausdrücklich auf das autorisierte Direct-Ziel geroutet werden. Nur `DATABASE_URL_DIRECT` zu setzen ändert die Collector-Verbindung nicht.

Diese Hinweise beschreiben einen Betriebsunterschied, keine Anweisung, die Verbindungskonfiguration, CLI oder Migrationen im Rahmen einer Dokumentationsaufgabe umzubauen. Keine Live-Verbindung aufbauen oder einen Schreibbefehl ausführen, sofern dies nicht ausdrücklich freigegeben ist.

`database init` führt `alembic upgrade head` aus und kann alle enthaltenen Revisionen bis `head` anwenden; niemals ungeprüft gegen Neon starten. Migration `0002` ergänzt LLM-Analysen und ist für die fachlichen Abläufe Ingestion und Candidate Discovery nicht erforderlich. Da `database init` aber auf `head` aktualisiert, würde es sie dennoch anwenden.

Der lokale PostgreSQL-Dienst aus [`docker-compose.yml`](docker-compose.yml) ist für entbehrliche Entwicklung/Testdaten vorgesehen (PostgreSQL 16, Port `5433`, DB-Name `ventureradar_test`). Verwende keinen geteilten oder produktiven DB-Endpoint als Testziel.

## 13. Entwicklung, CLI und Tests

Voraussetzung ist Python 3.12+. README-Setup hält die virtuelle Umgebung möglichst außerhalb von OneDrive:

```powershell
python -m venv C:\Users\<you>\venvs\startup-finder
C:\Users\<you>\venvs\startup-finder\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` ausschließlich lokal befüllen. Für eine lokale Datenbank: `docker compose up -d`. CLI-Beispiele:

```powershell
python -m app.cli database status
python -m app.cli collect openalex --limit 10 --dry-run
python -m app.cli collect university --source ude_forschung --limit 5 --dry-run
python -m app.cli collect cordis --limit 5 --dry-run
python -m app.cli collect manual_import --dry-run
python -m app.cli ingestion history --limit 10 --source github
python -m app.cli discovery preview --source university --limit 100
python -m app.cli llm preview --limit 100
```

Die installierte CLI heißt `ventureradar`; `python -m app.cli ...` ist die direkte Alternative. `--dry-run` benötigt für Collector keinen Datenbank-Schreibzugriff, aber Discovery- und LLM-Preview lesen jeweils aus der Datenbank. `--source` bei `collect` ist nur für `university` erlaubt. Collector-Exit-Codes: `0` erfolgreich, `10` partiell, `1` fehlgeschlagen, `2` Konfiguration, `3` Datenbank. stdout enthält JSON, Logs schreiben nach stderr.

Für Tests ohne Datenbank und ohne externe Live-Aufrufe ist `python -m pytest -m "not db and not live"` der sichere Unit-Test-Einstieg.

Tests sind mit pytest konfiguriert (`tests/`, Standardmarker `not live` in [`pyproject.toml`](pyproject.toml)). Adapter- und HTTP-Tests verwenden überwiegend HTTP-Mocks/Fixtures. Discovery-Regeln, CLI-Verhalten, SQL-Statements und LLM-Allowlist/Schema/Runner sind in eigenen Tests abgedeckt. Candidate Discovery und Candidate Validation besitzen keine Tests, da sie nicht implementiert sind.

**Destruktive DB-Testfixture:** [`tests/conftest.py`](tests/conftest.py) löscht das `public`-Schema der unter `TEST_DATABASE_URL` konfigurierten Datenbank, erstellt es neu und migriert bis `head`. DB-markierte Tests ausschließlich auf einer eigens dafür vorgesehenen, entbehrlichen Testdatenbank ausführen. Niemals DB-Tests gegen Neon, Produktiv- oder gemeinsam genutzte Datenbanken ausführen. In diesem Dokumentationsauftrag keine Collector, Migrationen oder DB-Tests starten.

Migrationsregeln:

1. SQLAlchemy-Modelle in `app/database/models.py` ändern.
2. Eine neue Alembic-Migration erstellen; freigegebene/benutzte Migrationen nicht rückwirkend editieren.
3. Upgrade/Downgrade und Migration-/Metadata-Tests gezielt auf einer sicheren Test-DB prüfen.
4. Keine Candidate-/Funding-Tabellen oder Statusspalten ohne ausdrückliche Fach- und Schemafreigabe ergänzen.

## 14. Verbindliche Agentenregeln

1. Vor Änderungen relevante Implementierungen, Tests, YAML-Konfigurationen und Migrationen lesen. Der Code bleibt die Quelle der Wahrheit; diese Datei bei erkannter Abweichung korrigieren.
2. Implementierte Funktion, teilweise getestete Funktion, freigegebenes Entwicklungsziel und nicht implementierte/ausgeschlossene Funktion sichtbar unterscheiden. Geplantes nie als vorhanden bezeichnen.
3. Bestehende Typen, Collector, Normalisierer, HTTP-Client und `IngestionRepository` wiederverwenden. Keine zweite Persistenz-/Datenflussarchitektur ohne klaren Bedarf einführen.
4. Quell-IDs, externe IDs, source keys, Cursor, History und Provenienz nicht stillschweigend ändern oder entfernen.
5. Keine automatische Cross-Source-Entity-Merge-Logik ohne ausdrückliche Freigabe. Kandidatenzuordnung ist kein globaler Entity-Merge.
6. Keine Unternehmens- oder Finanzierungsaussage ohne konkrete Evidenz/Quellenbeleg. Förderung strikt von Equity-Runden trennen; Fehlende Treffer nicht als bewiesenes Nichtvorhandensein darstellen.
7. Unsicherheit, nicht verifizierte Beziehungen und fehlende Werte erhalten; nichts erfinden oder stillschweigend als erfolgreich interpretieren.
8. Öffentliche Zugänglichkeit nicht mit Nutzungs-/LLM-Recht gleichsetzen. Quellenbedingungen, Attribution, Robots, Raten, Datenminimierung und angegebene Live-Prüfgrenzen beachten.
9. Keine Live-Collector, externen Validierungsrecherchen, LLM-Provider-Aufrufe oder Produktions-/Neon-Schreibzugriffe ohne ausdrückliche Freigabe.
10. Keine destruktiven Datenbanktests gegen geteilte oder produktive Datenbanken. DB-Tests nur mit sicher isolierter, wegwerfbarer `TEST_DATABASE_URL`.
11. Keine Secrets, Connection Strings, persönlichen Daten, manuell importierten Rohdaten oder vollständigen personenbezogenen Inhalte in Logs, Dokumentation, Tests oder Commits.
12. Schemaänderungen nur mit neuer Alembic-Revision. Keine Candidate- oder Funding-Persistenz ohne explizite Migration und Freigabe.
13. Änderungen eng am Auftrag halten, direkt betroffene Tests/Dokumentation aktualisieren und den kleinsten sicheren Testumfang ausführen. Bei reiner Dokumentation keine Laufzeittests nötig.

## 15. Verzeichnisübersicht und Referenzdokumente

| Pfad | Inhalt |
|---|---|
| `app/cli.py` | Typer-CLI für Collector, Datenbankstatus/-initialisierung, Run-Historie, Discovery und LLM |
| `app/adapters/` | Collector, Registry, Hochschul-Connectoren und Plugins |
| `app/config/` | Runtime-Einstellungen, Suchbegriffe, Quellen und LLM-Allowlist |
| `app/database/` | SQLAlchemy-Modelle, Repository, DB-Verbindung und Migrationen |
| `app/discovery/` | Deterministische Signal-/Observation-Klassifikation und Text-Erwähnungsregeln |
| `app/llm/` | Allowlist, kuratierte Eingaben, strukturierte Analyse, Fake Provider und Runner |
| `app/http/` | Gemeinsamer gedrosselter/retryfähiger HTTP-Client |
| `app/ingestion/` | Pydantic-Eingabe-/Ergebnistypen |
| `app/normalization/` | Wiederverwendbare Normalisierung für Personen, Organisationen, Texte und Publikationen |
| `app/utils/` | Datumsfunktionen, Hashing und Logging |
| `scripts/` | CLI-Einstiegsskripte |
| `tests/` | Adapter-, Discovery-, LLM-, Integration-, DB-, HTTP-, Pipeline- und Normalisierungstests |
| `docs/phase2-signal-contract.md` | Detaillierter Vertrag für Early-Signal-Regeln und Evidenzgrenzen |
| `docs/phase2b4-llm-allowlist.md` | LLM-Allowlist, Datenminimierung und aktuelle Provider-Sperren |
| `README.md` | Setup, Collectordetails, Betrieb, Quellenbefunde, Datenschutz und bekannte Einschränkungen |

## 16. Quellenbefunde und technische Grenzen

Die in diesem Dokument genannten Recherchebefunde stammen – soweit ausdrücklich markiert – aus den bereits im Repository dokumentierten Prüfungen vom **20.11.2026**. Sie wurden bei dieser Aktualisierung nicht erneut extern recherchiert. Bei späteren Änderungen müssen aktuelle Terms, Robots-Regeln und technische Limits geprüft und mit Prüfdatum dokumentiert werden.

- Die Quelle `foerderdatenbank.de` wird nicht gesammelt; laut dokumentiertem Befund sperrt Robots die Suchpfade und nennt Crawl-Delay 30.
- `huggingface.co` war aus dem damaligen Entwicklungsnetz nicht erreichbar; Live-Verhalten, Tag-Formate und Organisationseinstiegspunkte bleiben zu bestätigen.
- Für UDE sind nur freigegebene/aktivierte Konfigurationsquellen zu verwenden; `ude_aktuell` und `ude_guide` bleiben bis zur Klärung deaktiviert.
- CORDIS-Projektförderung und EXIST-Programmbezug sind Frühphasenkontext, keine Venture-Finanzierungsrunden.
- GitHub und arXiv haben keinen Länderfilter. Eine deutsche Ausrichtung ergibt sich nicht automatisch aus diesen Quellen.
- OpenAlex' publication-date-/Lookback-Cursor kann verspätet indexierte ältere Werke verpassen.
- Keine angeführte Quelle ist automatisch für LLM-Verarbeitung, kommerzielle Wiederverwendung oder beliebige Langzeitarchivierung freigegeben.
