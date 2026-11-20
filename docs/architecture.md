# Architektur und Betriebsgrenzen

## Module

- `store.py`: PostgreSQL via psycopg. Records mit typisierten Namespaces;
  Jobs/Leases mit eigenen Tabellen und Indizes. SQLite ist kein unterstützter
  Produktivspeicher.
- `domain.py`: API-unabhängige Anwendungslogik und Eingabevalidierung.
- `worker.py`: persistente Queue, Lease-Heartbeat, serialisierter Graphschreiber,
  begrenzte Wiederholungen, Recherche, Bewertung und Intervall-Scheduler.
- `clients.py`: Graphiti-Bridge und OpenAI Responses-Client.
- `model_factory.py`: generatives LLM; optionale Jev/OpenAI-Decision-Routen.
- `candidates.py`: aus aufgelösten StartupVenture-Knoten materialisierte Profile.
- `adapter_bridge.py`: Überführung von Collector-`source_records` in Finder-
  Fundstellen und Jobs; die Collector-Originale bleiben unverändert.
- `fetching.py`: HTML/RSS, Host-Allowlist, öffentliche IP-Prüfung, Abruflimits.
- `api.py`: JSON-API mit Bearer-Token und CORS.

## Datenfluss

Adapter-`source_records` (Originalpayload) → Adapter-Bridge → Finder-Fundstelle → persistenter
process-Job → Graphiti-Episode → LLM-Extraktion und Decision-Identitätsabgleich →
Neo4j-Graph → Graph-Rezept/Receipt und materialisierte Graphansicht in PostgreSQL → Kandidaten/Belege →
evaluate-Job → gespeicherte Bewertung mit Profilsnapshot → API.

Graphiti pflegt Neo4j. Die Extraktion nutzt das Turtle-Vokabular in
`docs/startup-sourcing-ontology.ttl` und die dazu passenden Graphiti-Typen aus
`startup_finder/ontology.py`: Ventures, Personen, Organisationen, Produkte,
Technologien, Probleme, Märkte, Kundensegmente, Investoren, Finanzierungsrunden,
Programme, Standorte und Kennzahlen mit gerichteten, typisierten Relationen.
Die Aufnahme verwendet Graphitis strikte Typprüfung für diese Relationen.
Die API liest eine materialisierte Teilansicht in PostgreSQL,
nicht eine komplette Kopie aller Graphiti-Interna. Recherchen speichern Modelltexte
als Recherchebericht. Nur tatsächlich abgerufene Originalseiten werden neue
Fundstellen. Ein Suchlauf sammelt maximal zehn Quellen und dreißig Fundstellen.

Die Adapter-Bridge liest Zeilen read-only, übergibt Titel, URL, Zeitbezug und die
vollständige Original-JSON-Payload sowie alle mit dem Quelldatensatz verknüpften
fachlichen Daten ins Finder-Fundstellenformat: Quellmetadaten, Lauf, Revisionen,
Entities und Aliase, Relationships, Observations und Signals. Diese bisherigen
Normalisierungen dienen Graphiti als zusätzliche Hinweise mit Provenienz; die
Originalquelle bleibt maßgeblich. Queue-/Lease-Daten und materialisierte Graph-
Ausgaben werden ausgeschlossen, damit keine Betriebsdaten oder eigene KG-Ausgaben
als neue Quellbelege zurücklaufen. Der Worker pollt neue und geänderte Adapter-
datensätze automatisch im 60-Sekunden-Takt und reiht Verarbeitungsjobs ein.
Stabile Quell- und Record-IDs machen Wiederholungen idempotent. Der Adapter-
Produktivpfad schreibt selbst keine regelbasierten Entities oder Relationships.

Vor dem Graphiti-Aufruf bewertet die konfigurierte OpenAI Decision API jeden
Adapterdatensatz anhand der vollständigen Original-Payload und aller verknüpften
Neon-Informationen (Metadaten, Revisionen, Entities/Aliase, Beziehungen,
Beobachtungen und Signals). Nur als relevant bewertete Datensätze werden vom
generativen Modell `gpt-6-luna` auf einen konkret benannten Venture-Kandidaten und
ein wörtliches Belegzitat geprüft. Allgemeine Publikationen, Forschung,
Universitätsmeldungen und generische Entrepreneurship-Programme bleiben als
Neon-Quellbelege erhalten, werden aber nicht in Finder oder KG übernommen.
Zusätzlich begrenzt der Graphiti-Prompt die Extraktion auf ein `StartupVenture`
und dessen direkte Kandidatenbeziehungen; die materialisierte Ansicht enthält nur
Venture-Knoten und direkte Nachbarn. Decision-Auswahl, Modell, Belegzitat und
Ausschlussstatus werden im Finder-Namespace `graph_relevance` gespeichert.

Jeder neu erkannte Kandidat löst automatisch eine Recherche- und eine Bewertungs-
Jobversion für den aktuellen Profilstand aus. Die Recherche sucht Produkt, Team,
Standort, Markt/Traktion und insbesondere Finanzierungsrunden/Investoren. Das
Modell darf Funding nur als bestätigt markieren, wenn ein Zitat in einem abgerufenen
Originaldokument verifiziert wurde. `not_found` bedeutet ausschließlich, dass in
den durchsuchten öffentlichen Quellen kein Beleg gefunden wurde; es bedeutet nicht,
dass kein Funding existiert. Verifizierte Originalseiten werden als Fundstellen
importiert, durch dieselbe Relevanzprüfung geführt und bei positiven Treffern mit
Graphiti in den Knowledge Graph aufgenommen. Geprüfte Zitate, Finanzierungsstatus,
Quellen und Rechercheverlauf bleiben am Kandidatenprofil nachvollziehbar.

## Wiederholungen und Konsistenz

- Fundstellen-/Episode-IDs enthalten Quelle, externe ID und Inhaltsversion.
- Graphschreibzugriffe pro group_id werden mit einer DB-Lease serialisiert.
- PostgreSQL claimt Jobs mit FOR UPDATE SKIP LOCKED. Heartbeats verlängern Job-
  und Pipeline-Leases.
- Erfolgreiche Graphiti-Ergebnisse werden vor Profilbildung gespeichert. Ein Retry
  kann diese wiederverwenden. Profilbildung und Enqueue der Bewertung sind atomar.
- Neo4j und PostgreSQL teilen keine Transaktion. Ein Absturz nach Graphschreiben
  und vor Receipt-Speicherung benötigt manuelle Prüfung. Der Worker überspringt
  einen solchen Episodenknoten nicht still. Kein Exactly-once-Versprechen.
- Nach Verlust einer DB oder eines Graphen ist ein geplanter Rebuild nötig.
- Harte Produktionsgarantien brauchen Fencing bei Lease-Verlust und Recovery
  für partielle Graphiti-Schreibvorgänge. Derzeit Team-Prototyp.

## Explainability

Originaltext, URL, Publikations- und Abrufzeit bleiben erhalten. Graph-Fakten sind
als Modell-Extraktion gekennzeichnet. Beleg-IDs müssen in der Bewertung existieren.
Das prüft Herkunft und Referenzierbarkeit, nicht automatisch semantische Wahrheit.
Live-Quellenausschnitte sind keine exakten, claim-spezifischen Evidenzspannen.
Diese müssen vor einer belastbaren Investmententscheidung ergänzt/geprüft werden.

## Ranking

Das generative Modell bewertet vier Kriterien und liefert keine Gesamtpriorität.
`startup_finder/ranking.py` berechnet einen gleich gewichteten Score. Mindestens
drei Kriterien müssen bewertet und mit Belegreferenzen versehen sein. Aktuelle Scores
werden absteigend sortiert; veraltete oder ältere Kriterienversionen tragen nicht zur
Rangfolge bei. Deutschlandbezug ist weder Score-Faktor noch Standardfilter. Die
Gewichtung ist eine Startversion und muss mit menschlich bewerteten Beispielen
überprüft werden, bevor sie als validiertes Auswahlmodell gilt.

## Sicherheit und Skalierung

Lokaler Standardbind; Live erfordert API-Token. Kein Rollen-/Mandantenmodell.
Quellenabruf prüft Host/IP, verweigert Redirects und begrenzt Größe/Zeit. Für
exponierten Betrieb zusätzlich Egress-Firewall gegen DNS-Rebinding, TLS-Proxy,
Rate Limits und Benutzerautorisierung einsetzen. Quelleninhalte sind untrusted;
Prompts allein bieten keinen vollständigen Prompt-Injection-Schutz.

Record-Listen werden im Prototyp in Python gefiltert. Für große Datenmengen
typisierte JSONB-/relationale Tabellen, DB-seitige Filter und Migrationswerkzeug
ergänzen. Modellkosten werden noch nicht vollständig bilanziert. Versionsgebundene
Providerintegration und Datenbanksicherungen gehören vor öffentlichen Betrieb.

## Upstream

https://github.com/getzep/graphiti

Die optionalen Decision-Routen folgen der dort beschriebenen LLMRuntime-API.
Nicht jede veröffentlichte graphiti-core-Version muss diese enthalten. Eine
installierte, geprüfte Version anschließend exakt pinnen; der aktuelle Live-Extra
gibt bewusst nur einen Versionsbereich an und ist kein reproduzierbarer Lockfile.
