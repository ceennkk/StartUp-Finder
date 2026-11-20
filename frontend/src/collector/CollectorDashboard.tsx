import type {
  DashboardData,
  DashboardView,
  EntityRow,
  IngestionRunRow,
  RelationshipRow,
  SourceRecordRow,
} from "../lib/collector-db";

const NAV: { id: DashboardView; label: string }[] = [
  { id: "overview", label: "Überblick" },
  { id: "entities", label: "Entitäten" },
  { id: "relationships", label: "Beziehungen" },
  { id: "records", label: "Fundstellen" },
  { id: "runs", label: "Ingestion-Läufe" },
];

const fmtDate = (value: string | null | undefined) => {
  if (!value) return "–";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(date);
};

const entityTypeLabel = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());

function Status({ value }: { value: string }) {
  return <span className={`live-status live-status--${value}`}>{value}</span>;
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
  return (
    <div className="htgf fa fa-live">
      <header className="fa-bar live-bar">
        <a href="/datenbestand" className="fa-logo" aria-label="StartUp Finder Datenbestand">
          <img src="/htgf/images/htgf-logo--black.svg" alt="HTGF" />
          <span>StartUp Finder</span>
        </a>
        <nav className="fa-nav live-nav" aria-label="Datenbereiche">
          {NAV.map((item) => (
            <a
              key={item.id}
              className={view === item.id ? "is-on" : ""}
              href={item.id === "overview" ? "/datenbestand" : `/datenbestand?view=${item.id}`}
              aria-current={view === item.id ? "page" : undefined}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <span className="live-db-badge"><i /> Neon · Nur Lesen</span>
        <a className="live-product-link" href="/">Zur Produktansicht →</a>
      </header>

      <main className="live-main">
        <div className="live-head">
          <div>
            <p className="live-kicker">LIVE-DATENBESTAND</p>
            <h1>{NAV.find((item) => item.id === view)?.label ?? "Überblick"}</h1>
            <p className="live-subtitle">Direkt aus den gespeicherten Adapterdaten und ihrer Provenienz.</p>
          </div>
          <div className="live-readonly"><span>●</span> Verbindung schreibgeschützt</div>
        </div>

        {error ? (
          <section className="live-error" role="alert">
            <h2>Keine Datenbankverbindung</h2>
            <p>{error}</p>
            <p className="fa-meta">Die Zugangsdaten bleiben serverseitig. Es wurden keine Datensätze geändert.</p>
          </section>
        ) : data ? (
          <>
            <div className="live-stats">
              <Stat label="Quellen" value={data.counts.sources} />
              <Stat label="Fundstellen" value={data.counts.sourceRecords} />
              <Stat label="Entitäten" value={data.counts.entities} />
              <Stat label="Beziehungen" value={data.counts.relationships} />
              <Stat label="Signale" value={data.counts.signals} />
              <Stat label="Ingestion-Läufe" value={data.counts.runs} />
            </div>

            {view === "overview" && <Overview data={data} />}
            {view === "entities" && <Entities data={data} search={search} entityType={entityType} />}
            {view === "relationships" && <Relationships rows={data.relationships} />}
            {view === "records" && <Records rows={data.records} />}
            {view === "runs" && <Runs rows={data.runs} />}
          </>
        ) : null}
        <footer className="live-footer">Alle Ansichten lesen aus Neon. Dieses Frontend schreibt keine Daten.</footer>
      </main>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <section className="live-stat">
      <span>{label}</span>
      <strong>{new Intl.NumberFormat("de-DE").format(value)}</strong>
    </section>
  );
}

function Overview({ data }: { data: DashboardData }) {
  return (
    <div className="live-columns">
      <section className="live-panel">
        <div className="live-panel-head">
          <div><p className="live-kicker">NORMALISIERT</p><h2>Entitätstypen</h2></div>
          <a href="/datenbestand?view=entities">Alle Entitäten →</a>
        </div>
        <div className="live-type-list">
          {data.entityTypes.map((item) => (
            <a key={item.entityType} href={`/datenbestand?view=entities&type=${encodeURIComponent(item.entityType)}`}>
              <span>{entityTypeLabel(item.entityType)}</span><b>{new Intl.NumberFormat("de-DE").format(item.count)}</b>
            </a>
          ))}
          {data.entityTypes.length === 0 && <p className="fa-muted">Noch keine Entitäten gespeichert.</p>}
        </div>
      </section>
      <section className="live-panel">
        <div className="live-panel-head">
          <div><p className="live-kicker">DATENHERKUNFT</p><h2>Quellen</h2></div>
          <a href="/datenbestand?view=records">Fundstellen ansehen →</a>
        </div>
        <div className="live-source-list">
          {data.sources.map((source) => (
            <div key={source.name} className="live-source-row">
              <div><strong>{source.name}</strong><span>{entityTypeLabel(source.type)}{source.url ? ` · ${source.url}` : ""}</span></div>
              <b>{new Intl.NumberFormat("de-DE").format(source.recordCount)}</b>
            </div>
          ))}
          {data.sources.length === 0 && <p className="fa-muted">Noch keine Quellen registriert.</p>}
        </div>
      </section>
      <section className="live-panel live-panel--wide">
        <div className="live-panel-head">
          <div><p className="live-kicker">LETZTE AKTIVITÄT</p><h2>Ingestion-Läufe</h2></div>
          <a href="/datenbestand?view=runs">Alle Läufe →</a>
        </div>
        <RunTable rows={data.recentRuns} />
      </section>
    </div>
  );
}

function Entities({ data, search, entityType }: { data: DashboardData; search: string; entityType: string }) {
  return (
    <section className="live-panel">
      <div className="live-panel-head">
        <div><p className="live-kicker">NORMALISIERTES DATENMODELL</p><h2>{data.entityTotal.toLocaleString("de-DE")} Treffer</h2></div>
      </div>
      <form className="live-filters" action="/datenbestand" method="get">
        <input type="hidden" name="view" value="entities" />
        <label>Suche<input name="q" defaultValue={search} placeholder="Name oder Beschreibung" /></label>
        <label>Typ<select name="type" defaultValue={entityType}><option value="">Alle Typen</option>{data.entityTypes.map((item) => <option key={item.entityType} value={item.entityType}>{entityTypeLabel(item.entityType)}</option>)}</select></label>
        <button type="submit">Filtern</button>
      </form>
      <div className="live-table-scroll">
        <table className="live-table">
          <thead><tr><th>Name</th><th>Typ</th><th>Beschreibung</th><th>Quellenbelege</th><th>Aktualisiert</th></tr></thead>
          <tbody>
            {data.entities.map((row: EntityRow) => <tr key={row.id}>
              <td><strong>{row.name}</strong><small className="live-id">{row.id}</small></td>
              <td><span className="live-type-pill">{entityTypeLabel(row.entityType)}</span></td>
              <td className="live-description">{row.description || <span className="fa-muted">Keine Beschreibung</span>}</td>
              <td>{row.sourceCount}</td><td>{fmtDate(row.updatedAt)}</td>
            </tr>)}
            {data.entities.length === 0 && <tr><td colSpan={5} className="live-empty">Keine Entitäten für diesen Filter gefunden.</td></tr>}
          </tbody>
        </table>
      </div>
      {data.entityTotal > data.entities.length && <p className="live-footnote">Es werden die neuesten {data.entities.length} von {data.entityTotal.toLocaleString("de-DE")} Treffern angezeigt.</p>}
    </section>
  );
}

function Relationships({ rows }: { rows: RelationshipRow[] }) {
  return (
    <section className="live-panel">
      <div className="live-panel-head"><div><p className="live-kicker">QUELLENBELEGTE KANTEN</p><h2>Neueste Beziehungen</h2></div><span className="live-count">{rows.length} angezeigt</span></div>
      <div className="live-table-scroll">
        <table className="live-table">
          <thead><tr><th>Von</th><th>Beziehung</th><th>Zu</th><th>Prüfstatus</th><th>Konfidenz</th><th>Quelle</th></tr></thead>
          <tbody>
            {rows.map((row) => <tr key={row.id}>
              <td><strong>{row.sourceName}</strong><small>{entityTypeLabel(row.sourceType)}</small></td>
              <td><span className="live-edge">{entityTypeLabel(row.relation)}</span></td>
              <td><strong>{row.targetName}</strong><small>{entityTypeLabel(row.targetType)}</small></td>
              <td><Status value={row.verification} /></td>
              <td>{row.confidence ?? "–"}</td>
              <td>{row.sourceUrl ? <a href={row.sourceUrl} target="_blank" rel="noreferrer">{row.sourceNameFrom} ↗</a> : row.sourceNameFrom}</td>
            </tr>)}
            {rows.length === 0 && <tr><td colSpan={6} className="live-empty">Keine Beziehungen vorhanden.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="live-footnote">Die Tabelle zeigt bis zu 100 zuletzt beobachtete Beziehungen. Jede Kante bleibt mit ihrer Fundstelle verknüpft.</p>
    </section>
  );
}

function Records({ rows }: { rows: SourceRecordRow[] }) {
  return (
    <section className="live-panel">
      <div className="live-panel-head"><div><p className="live-kicker">ORIGINALDATEN</p><h2>Zuletzt gesehene Fundstellen</h2></div><span className="live-count">{rows.length} angezeigt</span></div>
      <div className="live-table-scroll">
        <table className="live-table">
          <thead><tr><th>Titel / Datensatz</th><th>Quelle</th><th>Typ</th><th>Verknüpfte Entitäten</th><th>Veröffentlicht</th><th>Zuletzt gesehen</th></tr></thead>
          <tbody>
            {rows.map((row: SourceRecordRow) => <tr key={row.id}>
              <td><strong>{row.title}</strong>{row.url && <a className="live-record-url" href={row.url} target="_blank" rel="noreferrer">Original öffnen ↗</a>}</td>
              <td>{row.sourceName}</td><td><span className="live-type-pill">{entityTypeLabel(row.recordType)}</span></td>
              <td>{row.entityCount}</td><td>{fmtDate(row.publishedAt)}</td><td>{fmtDate(row.lastSeenAt)}</td>
            </tr>)}
            {rows.length === 0 && <tr><td colSpan={6} className="live-empty">Keine Fundstellen vorhanden.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="live-footnote">Die Roh-Payloads bleiben in Neon gespeichert. Diese Liste zeigt nur Metadaten und öffnet bei Bedarf die Originalquelle.</p>
    </section>
  );
}

function Runs({ rows }: { rows: IngestionRunRow[] }) {
  return <section className="live-panel"><div className="live-panel-head"><div><p className="live-kicker">ADAPTER-VERARBEITUNG</p><h2>Letzte Ingestion-Läufe</h2></div><span className="live-count">{rows.length} angezeigt</span></div><RunTable rows={rows} /></section>;
}

function RunTable({ rows }: { rows: IngestionRunRow[] }) {
  return (
    <div className="live-table-scroll">
      <table className="live-table">
        <thead><tr><th>Quelle</th><th>Status</th><th>Gestartet</th><th>Abgerufen</th><th>Neu</th><th>Aktualisiert</th><th>Fehler</th></tr></thead>
        <tbody>
          {rows.map((row: IngestionRunRow) => <tr key={row.id}>
            <td><strong>{row.sourceName}</strong><small className="live-id">{row.id}</small></td>
            <td><Status value={row.status} /></td><td>{fmtDate(row.startedAt)}</td><td>{row.fetched}</td><td>{row.created}</td><td>{row.updated}</td>
            <td>{row.failed}{row.error && <small className="live-run-error">{row.error}</small>}</td>
          </tr>)}
          {rows.length === 0 && <tr><td colSpan={7} className="live-empty">Noch keine Läufe gespeichert.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
