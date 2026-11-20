# Startup Finder – Frontend

Next.js 16, React 19, TypeScript. Das Finder-Produktfrontend spricht für alle
Produktdaten ausschließlich mit dem Backend über den Vertrag in
`../docs/frontend-contract.md`. Es gibt keinen Demo-Modus und keine Mock-API.

## Starten

```sh
cd frontend
npm ci
npm run dev
```

Öffnen: <http://localhost:3000>. Das Produktionsbackend läuft standardmäßig auf
<http://localhost:8000>. Lokale Loopback-Verbindungen benötigen keine manuelle
Tokeneingabe. Bei entfernten Backends ist ein Bearer-Token erforderlich. Die
Oberfläche zeigt Kandidaten- und Graphdaten erst, wenn die API `live` bestätigt.

Die Produktoberfläche greift nicht direkt auf PostgreSQL oder Neo4j zu. Die
separate technische Ansicht unter `/datenbestand` liest Adapterdaten serverseitig
aus Neon in schreibgeschützten Transaktionen. Sie ist keine Graph- oder
Kandidatenansicht.

## Verbindung und Sicherheit

Das Backend muss `http://localhost:3000` in `CORS_ORIGINS` erlauben. Im Browser
wird kein Datenbankzugang hinterlegt. Nur `/datenbestand` verbindet sich
serverseitig mit Neon; für Deployments DB-Zugangsdaten als Secrets konfigurieren
und eine Rolle ohne Schreibrechte verwenden.

## Prüfen

```sh
npm run check
```

## Aufbau

```
src/app/            Produktfrontend auf /; Datenbestandsansicht auf /datenbestand
src/collector/      Tabellenansicht für Neon-Entitäten, Beziehungen, Fundstellen und Läufe
src/lib/collector-db.ts  Serverseitiger PostgreSQL-Zugriff in Read-only-Transaktionen
src/finder/
  types.ts          Typen nach frontend-contract.md
  api/client.ts     Produktions-HTTP-Client (Token, Fehler {detail}), Konfiguration
  hooks.tsx         ApiProvider, useLoad, useJobPolling
  App.tsx           Navigation und fail-closed Produktionsstatusprüfung
  views.tsx         Kandidaten, Shortlist, Suchaufträge, Quellen, Pipeline, Systemstatus
  GraphView.tsx     Materialisierter Graph mit Beziehungsliste
  CandidatePanel.tsx Kandidatendetail
```

Suche und Filter entsprechen dem Backendvertrag. Bewertungen bleiben an den
gespeicherten Profilstand gebunden; Widersprüche werden angezeigt, nicht
überschrieben. Suchaufträge speichern den Prompt als Kontext und sammeln
konfigurierte Quellen; sie sind keine semantische Suche.
