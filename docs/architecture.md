# Architektur und Betriebsgrenzen

## Module

- `store.py`: PostgreSQL via psycopg, SQLite nur für Offline-Demo. Records mit
  typisierten Namespaces; Jobs/Leases mit eigenen Tabellen und Indizes.
- `domain.py`: API-unabhängige Anwendungslogik und Eingabevalidierung.
- `worker.py`: persistente Queue, Lease-Heartbeat, serialisierter Graphschreiber,
  begrenzte Wiederholungen, Recherche, Bewertung und Intervall-Scheduler.
- `clients.py`: Graphiti-Bridge, OpenAI Responses-Client und explizite Demo-Clients.
- `model_factory.py`: generatives LLM; optionale Jev/OpenAI-Decision-Routen.
- `candidates.py`: aus aufgelösten StartupVenture-Knoten materialisierte Profile.
- `fetching.py`: HTML/RSS, Host-Allowlist, öffentliche IP-Prüfung, Abruflimits.
- `api.py`: JSON-API mit Bearer-Token, CORS und statischer Funktionsvorschau.

## Datenfluss

Fundstelle → persistenter process-Job → Graphiti-Episode → aufgelöste Graphknoten
und Beziehungen → Graph-Rezept/Receipt in PostgreSQL → Kandidaten/Belege →
evaluate-Job → gespeicherte Bewertung mit Profilsnapshot → API.

Graphiti pflegt Neo4j. Die API liest eine materialisierte Teilansicht in PostgreSQL,
nicht eine komplette Kopie aller Graphiti-Interna. Recherchen speichern Modelltexte
als Recherchebericht. Nur tatsächlich abgerufene Originalseiten werden neue
Fundstellen. Ein Suchlauf sammelt maximal zehn Quellen und dreißig Fundstellen.

## Wiederholungen und Konsistenz

- Fundstellen-/Episode-IDs enthalten Quelle, externe ID und Inhaltsversion.
- Graphschreibzugriffe pro group_id werden mit einer DB-Lease serialisiert.
- PostgreSQL claimt Jobs mit FOR UPDATE SKIP LOCKED; SQLite verwendet eine
  Schreibtransaktion. Heartbeats verlängern Job- und Pipeline-Leases.
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
