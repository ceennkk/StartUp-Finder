import type {
  DashboardData,
  DashboardView,
  EntityRow,
  IngestionRunRow,
  RelationshipRow,
  SourceRecordRow,
} from "../lib/collector-db";
import { useLanguage } from "../finder/i18n";

const NAV: { id: DashboardView; label: string }[] = [
  { id: "overview", label: "Überblick" },
  { id: "entities", label: "Entitäten" },
  { id: "relationships", label: "Beziehungen" },
  { id: "records", label: "Fundstellen" },
  { id: "runs", label: "Ingestion-Läufe" },
];

const EN: Record<string, string> = {
  "Sprache": "Language",
  "Überblick": "Overview", "Entitäten": "Entities", "Beziehungen": "Relationships", "Fundstellen": "Source records", "Ingestion-Läufe": "Ingestion runs",
  "Datenbereiche": "Data sections", "Neon · Nur Lesen": "Neon · Read only", "Zur Produktansicht →": "Back to product →",
  "LIVE-DATENBESTAND": "LIVE DATA INVENTORY", "Direkt aus den gespeicherten Adapterdaten und ihrer Provenienz.": "Directly from stored adapter data and its provenance.",
  "Verbindung schreibgeschützt": "Read-only connection", "Keine Datenbankverbindung": "Database connection unavailable",
  "Die Zugangsdaten bleiben serverseitig. Es wurden keine Datensätze geändert.": "Credentials stay on the server. No records were changed.",
  "Alle Ansichten lesen aus Neon. Dieses Frontend schreibt keine Daten.": "All views read from Neon. This frontend does not write data.",
  "Quellen": "Sources", "Signale": "Signals", "NORMALISIERT": "NORMALIZED", "Entitätstypen": "Entity types",
  "Alle Entitäten →": "All entities →", "Noch keine Entitäten gespeichert.": "No entities stored yet.", "DATENHERKUNFT": "DATA PROVENANCE",
  "Fundstellen ansehen →": "View source records →", "Noch keine Quellen registriert.": "No sources registered yet.", "LETZTE AKTIVITÄT": "LATEST ACTIVITY",
  "Alle Läufe →": "All runs →", "NORMALISIERTES DATENMODELL": "NORMALIZED DATA MODEL", "Treffer": "results",
  "Suche": "Search", "Name oder Beschreibung": "Name or description", "Typ": "Type", "Alle Typen": "All types", "Filtern": "Filter",
  "Name": "Name", "Beschreibung": "Description", "Quellenbelege": "Source records", "Aktualisiert": "Updated",
  "Keine Beschreibung": "No description", "Keine Entitäten für diesen Filter gefunden.": "No entities match this filter.",
  "Es werden die neuesten": "Showing the newest", "von": "of", "Treffern angezeigt.": "results.",
  "QUELLENBELEGTE KANTEN": "SOURCE-BACKED EDGES", "Neueste Beziehungen": "Latest relationships", "angezeigt": "shown",
  "Von": "From", "Beziehung": "Relationship", "Zu": "To", "Prüfstatus": "Verification", "Konfidenz": "Confidence", "Quelle": "Source",
  "Keine Beziehungen vorhanden.": "No relationships available.", "Die Tabelle zeigt bis zu 100 zuletzt beobachtete Beziehungen. Jede Kante bleibt mit ihrer Fundstelle verknüpft.": "Showing up to 100 most recently observed relationships. Each edge remains linked to its source record.",
  "ORIGINALDATEN": "ORIGINAL DATA", "Zuletzt gesehene Fundstellen": "Recently observed source records", "Titel / Datensatz": "Title / record",
  "Verknüpfte Entitäten": "Linked entities", "Veröffentlicht": "Published", "Zuletzt gesehen": "Last seen", "Original öffnen ↗": "Open original ↗",
  "Keine Fundstellen vorhanden.": "No source records available.", "Die Roh-Payloads bleiben in Neon gespeichert. Diese Liste zeigt nur Metadaten und öffnet bei Bedarf die Originalquelle.": "Raw payloads remain stored in Neon. This list shows metadata and links to the original source.",
  "ADAPTER-VERARBEITUNG": "ADAPTER PROCESSING", "Letzte Ingestion-Läufe": "Latest ingestion runs", "Status": "Status", "Gestartet": "Started",
  "Abgerufen": "Fetched", "Neu": "New", "Fehler": "Errors", "Noch keine Läufe gespeichert.": "No runs stored yet.",
  "queued": "Queued", "running": "Running", "succeeded": "Succeeded", "failed": "Failed", "valid": "Valid", "invalid": "Invalid",
  "pending": "Pending", "verified": "Verified", "unverified": "Unverified", "complete": "Complete", "partial": "Partial",
};

const word = (value: string, language: "en" | "de") => language === "en" ? (EN[value] ?? value) : value;
const number = (value: number, language: "en" | "de") => new Intl.NumberFormat(language === "de" ? "de-DE" : "en-US").format(value);
const fmtDate = (value: string | null | undefined, language: "en" | "de") => {
  if (!value) return "–";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(language === "de" ? "de-DE" : "en-US", { dateStyle: "medium", timeStyle: "short" }).format(date);
};

const entityTypeLabel = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());

function Status({ value }: { value: string }) {
  const { language } = useLanguage();
  return <span className={`live-status live-status--${value}`}>{word(value, language)}</span>;
}

export function CollectorDashboard({
  data,
  error,
  view,
  search,
  entityType,
}: {
  data: DashboardData | null;
  error: string | null;
  view: DashboardView;
  search: string;
  entityType: string;
}) {
  const { language, setLanguage } = useLanguage();
  const tr = (value: string) => word(value, language);
  const format = (value: number) => number(value, language);
  return (
    <div className="htgf fa fa-live">
      <header className="fa-bar live-bar">
        <a href="/datenbestand" className="fa-logo" aria-label={`Pre-Round ${tr("Fundstellen")}`}>
          <img src="/htgf/images/htgf-logo--black.svg" alt="HTGF" />
          <span>Pre-Round</span>
        </a>
        <nav className="fa-nav live-nav" aria-label={tr("Datenbereiche")}>
          {NAV.map((item) => (
            <a
              key={item.id}
              className={view === item.id ? "is-on" : ""}
              href={item.id === "overview" ? "/datenbestand" : `/datenbestand?view=${item.id}`}
              aria-current={view === item.id ? "page" : undefined}
            >
              {tr(item.label)}
            </a>
          ))}
        </nav>
        <span className="live-db-badge"><i /> {tr("Neon · Nur Lesen")}</span>
        <div className="fa-language live-language" role="group" aria-label={tr("Sprache")}>
          {(["en", "de"] as const).map((value) => <button key={value} type="button" className={language === value ? "is-on" : ""} aria-pressed={language === value} onClick={() => setLanguage(value)}>{value.toUpperCase()}</button>)}
        </div>
        <a className="live-product-link" href="/">{tr("Zur Produktansicht →")}</a>
      </header>

      <main className="live-main">
        <div className="live-head">
          <div>
            <p className="live-kicker">{tr("LIVE-DATENBESTAND")}</p>
            <h1>{tr(NAV.find((item) => item.id === view)?.label ?? "Überblick")}</h1>
            <p className="live-subtitle">{tr("Direkt aus den gespeicherten Adapterdaten und ihrer Provenienz.")}</p>
          </div>
          <div className="live-readonly"><span>●</span> {tr("Verbindung schreibgeschützt")}</div>
        </div>

        {error ? (
          <section className="live-error" role="alert">
            <h2>{tr("Keine Datenbankverbindung")}</h2>
            <p>{error === "missing_database" ? (language === "de" ? "DATABASE_URL fehlt. Hinterlege die Neon-Verbindung in der Projekt-.env." : "DATABASE_URL is missing. Add the Neon connection string to the project .env.") : error === "database_connection" ? (language === "de" ? "Verbindung nicht möglich. Prüfe DATABASE_URL und den Netzwerkzugriff des Frontend-Servers." : "Could not connect. Check DATABASE_URL and the frontend server’s network access.") : error}</p>
            <p className="fa-meta">{tr("Die Zugangsdaten bleiben serverseitig. Es wurden keine Datensätze geändert.")}</p>
          </section>
        ) : data ? (
          <>
            <div className="live-stats">
              <Stat label={tr("Quellen")} value={data.counts.sources} language={language} />
              <Stat label={tr("Fundstellen")} value={data.counts.sourceRecords} language={language} />
              <Stat label={tr("Entitäten")} value={data.counts.entities} language={language} />
              <Stat label={tr("Beziehungen")} value={data.counts.relationships} language={language} />
              <Stat label={tr("Signale")} value={data.counts.signals} language={language} />
              <Stat label={tr("Ingestion-Läufe")} value={data.counts.runs} language={language} />
            </div>

            {view === "overview" && <Overview data={data} />}
            {view === "entities" && <Entities data={data} search={search} entityType={entityType} />}
            {view === "relationships" && <Relationships rows={data.relationships} />}
            {view === "records" && <Records rows={data.records} />}
            {view === "runs" && <Runs rows={data.runs} />}
          </>
        ) : null}
        <footer className="live-footer">{tr("Alle Ansichten lesen aus Neon. Dieses Frontend schreibt keine Daten.")}</footer>
      </main>
    </div>
  );
}

function Stat({ label, value, language }: { label: string; value: number; language: "en" | "de" }) {
  return (
    <section className="live-stat">
      <span>{label}</span>
      <strong>{number(value, language)}</strong>
    </section>
  );
}

function Overview({ data }: { data: DashboardData }) {
  const { language } = useLanguage();
  const tr = (value: string) => word(value, language);
  const format = (value: number) => number(value, language);
  return (
    <div className="live-columns">
      <section className="live-panel">
        <div className="live-panel-head">
          <div><p className="live-kicker">{tr("NORMALISIERT")}</p><h2>{tr("Entitätstypen")}</h2></div>
          <a href="/datenbestand?view=entities">{tr("Alle Entitäten →")}</a>
        </div>
        <div className="live-type-list">
          {data.entityTypes.map((item) => (
            <a key={item.entityType} href={`/datenbestand?view=entities&type=${encodeURIComponent(item.entityType)}`}>
              <span>{entityTypeLabel(item.entityType)}</span><b>{format(item.count)}</b>
            </a>
          ))}
          {data.entityTypes.length === 0 && <p className="fa-muted">{tr("Noch keine Entitäten gespeichert.")}</p>}
        </div>
      </section>
      <section className="live-panel">
        <div className="live-panel-head">
          <div><p className="live-kicker">{tr("DATENHERKUNFT")}</p><h2>{tr("Quellen")}</h2></div>
          <a href="/datenbestand?view=records">{tr("Fundstellen ansehen →")}</a>
        </div>
        <div className="live-source-list">
          {data.sources.map((source) => (
            <div key={source.name} className="live-source-row">
              <div><strong>{source.name}</strong><span>{entityTypeLabel(source.type)}{source.url ? ` · ${source.url}` : ""}</span></div>
              <b>{format(source.recordCount)}</b>
            </div>
          ))}
          {data.sources.length === 0 && <p className="fa-muted">{tr("Noch keine Quellen registriert.")}</p>}
        </div>
      </section>
      <section className="live-panel live-panel--wide">
        <div className="live-panel-head">
          <div><p className="live-kicker">{tr("LETZTE AKTIVITÄT")}</p><h2>{tr("Ingestion-Läufe")}</h2></div>
          <a href="/datenbestand?view=runs">{tr("Alle Läufe →")}</a>
        </div>
        <RunTable rows={data.recentRuns} />
      </section>
    </div>
  );
}

function Entities({ data, search, entityType }: { data: DashboardData; search: string; entityType: string }) {
  const { language } = useLanguage();
  const tr = (value: string) => word(value, language);
  const format = (value: number) => number(value, language);
  return (
    <section className="live-panel">
      <div className="live-panel-head">
        <div><p className="live-kicker">{tr("NORMALISIERTES DATENMODELL")}</p><h2>{format(data.entityTotal)} {tr("Treffer")}</h2></div>
      </div>
      <form className="live-filters" action="/datenbestand" method="get">
        <input type="hidden" name="view" value="entities" />
        <label>{tr("Suche")}<input name="q" defaultValue={search} placeholder={tr("Name oder Beschreibung")} /></label>
        <label>{tr("Typ")}<select name="type" defaultValue={entityType}><option value="">{tr("Alle Typen")}</option>{data.entityTypes.map((item) => <option key={item.entityType} value={item.entityType}>{entityTypeLabel(item.entityType)}</option>)}</select></label>
        <button type="submit">{tr("Filtern")}</button>
      </form>
      <div className="live-table-scroll">
        <table className="live-table">
          <thead><tr><th>{tr("Name")}</th><th>{tr("Typ")}</th><th>{tr("Beschreibung")}</th><th>{tr("Quellenbelege")}</th><th>{tr("Aktualisiert")}</th></tr></thead>
          <tbody>
            {data.entities.map((row: EntityRow) => <tr key={row.id}>
              <td><strong>{row.name}</strong><small className="live-id">{row.id}</small></td>
              <td><span className="live-type-pill">{entityTypeLabel(row.entityType)}</span></td>
              <td className="live-description">{row.description || <span className="fa-muted">{tr("Keine Beschreibung")}</span>}</td>
              <td>{format(row.sourceCount)}</td><td>{fmtDate(row.updatedAt, language)}</td>
            </tr>)}
            {data.entities.length === 0 && <tr><td colSpan={5} className="live-empty">{tr("Keine Entitäten für diesen Filter gefunden.")}</td></tr>}
          </tbody>
        </table>
      </div>
      {data.entityTotal > data.entities.length && <p className="live-footnote">{language === "de" ? `Es werden die neuesten ${format(data.entities.length)} von ${format(data.entityTotal)} Treffern angezeigt.` : `Showing the newest ${format(data.entities.length)} of ${format(data.entityTotal)} results.`}</p>}
    </section>
  );
}

function Relationships({ rows }: { rows: RelationshipRow[] }) {
  const { language } = useLanguage();
  const tr = (value: string) => word(value, language);
  return (
    <section className="live-panel">
      <div className="live-panel-head"><div><p className="live-kicker">{tr("QUELLENBELEGTE KANTEN")}</p><h2>{tr("Neueste Beziehungen")}</h2></div><span className="live-count">{rows.length} {tr("angezeigt")}</span></div>
      <div className="live-table-scroll">
        <table className="live-table">
          <thead><tr><th>{tr("Von")}</th><th>{tr("Beziehung")}</th><th>{tr("Zu")}</th><th>{tr("Prüfstatus")}</th><th>{tr("Konfidenz")}</th><th>{tr("Quelle")}</th></tr></thead>
          <tbody>
            {rows.map((row) => <tr key={row.id}>
              <td><strong>{row.sourceName}</strong><small>{entityTypeLabel(row.sourceType)}</small></td>
              <td><span className="live-edge">{entityTypeLabel(row.relation)}</span></td>
              <td><strong>{row.targetName}</strong><small>{entityTypeLabel(row.targetType)}</small></td>
              <td><Status value={row.verification} /></td>
              <td>{row.confidence ?? "–"}</td>
              <td>{row.sourceUrl ? <a href={row.sourceUrl} target="_blank" rel="noreferrer">{row.sourceNameFrom} ↗</a> : row.sourceNameFrom}</td>
            </tr>)}
            {rows.length === 0 && <tr><td colSpan={6} className="live-empty">{tr("Keine Beziehungen vorhanden.")}</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="live-footnote">{tr("Die Tabelle zeigt bis zu 100 zuletzt beobachtete Beziehungen. Jede Kante bleibt mit ihrer Fundstelle verknüpft.")}</p>
    </section>
  );
}

function Records({ rows }: { rows: SourceRecordRow[] }) {
  const { language } = useLanguage();
  const tr = (value: string) => word(value, language);
  return (
    <section className="live-panel">
      <div className="live-panel-head"><div><p className="live-kicker">{tr("ORIGINALDATEN")}</p><h2>{tr("Zuletzt gesehene Fundstellen")}</h2></div><span className="live-count">{rows.length} {tr("angezeigt")}</span></div>
      <div className="live-table-scroll">
        <table className="live-table">
          <thead><tr><th>{tr("Titel / Datensatz")}</th><th>{tr("Quelle")}</th><th>{tr("Typ")}</th><th>{tr("Verknüpfte Entitäten")}</th><th>{tr("Veröffentlicht")}</th><th>{tr("Zuletzt gesehen")}</th></tr></thead>
          <tbody>
            {rows.map((row: SourceRecordRow) => <tr key={row.id}>
              <td><strong>{row.title}</strong>{row.url && <a className="live-record-url" href={row.url} target="_blank" rel="noreferrer">{tr("Original öffnen ↗")}</a>}</td>
              <td>{row.sourceName}</td><td><span className="live-type-pill">{entityTypeLabel(row.recordType)}</span></td>
              <td>{number(row.entityCount, language)}</td><td>{fmtDate(row.publishedAt, language)}</td><td>{fmtDate(row.lastSeenAt, language)}</td>
            </tr>)}
            {rows.length === 0 && <tr><td colSpan={6} className="live-empty">{tr("Keine Fundstellen vorhanden.")}</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="live-footnote">{tr("Die Roh-Payloads bleiben in Neon gespeichert. Diese Liste zeigt nur Metadaten und öffnet bei Bedarf die Originalquelle.")}</p>
    </section>
  );
}

function Runs({ rows }: { rows: IngestionRunRow[] }) {
  const { language } = useLanguage();
  const tr = (value: string) => word(value, language);
  return <section className="live-panel"><div className="live-panel-head"><div><p className="live-kicker">{tr("ADAPTER-VERARBEITUNG")}</p><h2>{tr("Letzte Ingestion-Läufe")}</h2></div><span className="live-count">{rows.length} {tr("angezeigt")}</span></div><RunTable rows={rows} /></section>;
}

function RunTable({ rows }: { rows: IngestionRunRow[] }) {
  const { language } = useLanguage();
  const tr = (value: string) => word(value, language);
  return (
    <div className="live-table-scroll">
      <table className="live-table">
        <thead><tr><th>{tr("Quelle")}</th><th>{tr("Status")}</th><th>{tr("Gestartet")}</th><th>{tr("Abgerufen")}</th><th>{tr("Neu")}</th><th>{tr("Aktualisiert")}</th><th>{tr("Fehler")}</th></tr></thead>
        <tbody>
          {rows.map((row: IngestionRunRow) => <tr key={row.id}>
            <td><strong>{row.sourceName}</strong><small className="live-id">{row.id}</small></td>
            <td><Status value={row.status} /></td><td>{fmtDate(row.startedAt, language)}</td><td>{number(row.fetched, language)}</td><td>{number(row.created, language)}</td><td>{number(row.updated, language)}</td>
            <td>{number(row.failed, language)}{row.error && <small className="live-run-error">{row.error}</small>}</td>
          </tr>)}
          {rows.length === 0 && <tr><td colSpan={7} className="live-empty">{tr("Noch keine Läufe gespeichert.")}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
