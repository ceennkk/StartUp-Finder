"use client";

import { useMemo, useState } from "react";
import type { GraphEdge, GraphNode } from "./types";
import { Empty, ErrorBox, Loading, PageHead } from "./ui";
import { useLoad } from "./hooks";

const RELATION: Record<string, string> = { WORKS_ON: "arbeitet an", FOUNDED: "gründet", FOUNDS: "gründet", WORKSAT: "arbeitet bei", BUILDS: "entwickelt", USESTECHNOLOGY: "nutzt Technologie", ADDRESSES: "adressiert Problem", TARGETS: "richtet sich an", OPERATESIN: "aktiv in Markt", LOCATEDIN: "sitzt in", FUNDEDBY: "finanziert durch", INVESTEDIN: "investiert in", PARTICIPATESIN: "nimmt teil an", HASFUNDINGROUND: "Finanzierungsrunde", HASMETRIC: "Kennzahl", ACQUIREDBY: "übernommen von", SUPPORTED_BY: "begleitet von", AFFILIATED_WITH: "verbunden mit", LOCATED_IN: "sitzt in" };
const CATEGORIES = [
  { key: "person", title: "Personen", singular: "Person", color: "person", match: (n: GraphNode) => n.labels.includes("Person") },
  { key: "venture", title: "Startups", singular: "Startup", color: "venture", match: (n: GraphNode) => n.labels.includes("StartupVenture") },
  { key: "other", title: "Institutionen & Weitere", singular: "Weitere Entity", color: "other", match: (n: GraphNode) => !n.labels.includes("Person") && !n.labels.includes("StartupVenture") },
] as const;
type CategoryKey = (typeof CATEGORIES)[number]["key"];
const W = 1000;
const ROW = 68;
const PAD = 46;
const X = [145, 500, 855];
const OVERVIEW_LIMIT = 60;
const labelRelation = (relation: string) => RELATION[relation] ?? relation.toLowerCase().replace(/_/g, " ");

/** Interactive read-only graph. Selecting a node reveals its neighborhood and evidence. */
export function GraphView({ onOpen }: { onOpen: (candidateId: string) => void }) {
  const { data, error, loading, reload } = useLoad((a) => a.graph(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<CategoryKey | "all">("all");
  const [relationFilter, setRelationFilter] = useState("all");
  const [neighborsOnly, setNeighborsOnly] = useState(true);
  const [showIsolated, setShowIsolated] = useState(false);
  const [showLabels, setShowLabels] = useState(false);

  const model = useMemo(() => {
    if (!data) return null;
    const term = q.trim().toLocaleLowerCase("de");
    const byId = new Map(data.nodes.map((node) => [node.id, node]));
    const categoryOf = (node: GraphNode): CategoryKey => node.labels.includes("Person") ? "person" : node.labels.includes("StartupVenture") ? "venture" : "other";
    let edges = data.edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target));
    if (relationFilter !== "all") edges = edges.filter((edge) => edge.relation === relationFilter);
    const matchesCategory = (node: GraphNode) => category === "all" || categoryOf(node) === category;
    const adjacent = new Set(edges.flatMap((edge) => [edge.source, edge.target]));
    let nodes: GraphNode[];
    if (selected && neighborsOnly) {
      const neighborhood = new Set([selected]);
      for (const edge of edges) {
        if (edge.source === selected) neighborhood.add(edge.target);
        if (edge.target === selected) neighborhood.add(edge.source);
      }
      nodes = data.nodes.filter((node) => neighborhood.has(node.id));
    } else if (term) {
      const matches = new Set(data.nodes.filter((node) => matchesCategory(node) && node.name.toLocaleLowerCase("de").includes(term)).map((node) => node.id));
      const neighborhood = new Set(matches);
      for (const edge of edges) {
        if (matches.has(edge.source)) neighborhood.add(edge.target);
        if (matches.has(edge.target)) neighborhood.add(edge.source);
      }
      nodes = data.nodes.filter((node) => neighborhood.has(node.id));
    } else {
      nodes = data.nodes.filter((node) => matchesCategory(node) && (showIsolated || adjacent.has(node.id)));
      if (!showIsolated && nodes.length > OVERVIEW_LIMIT) {
        const degree = new Map<string, number>(nodes.map((node): [string, number] => [node.id, 0]));
        for (const edge of edges) {
          if (degree.has(edge.source)) degree.set(edge.source, degree.get(edge.source)! + 1);
          if (degree.has(edge.target)) degree.set(edge.target, degree.get(edge.target)! + 1);
        }
        nodes = [...nodes].sort((a, b) => (degree.get(b.id)! - degree.get(a.id)!) || a.name.localeCompare(b.name, "de")).slice(0, OVERVIEW_LIMIT);
      }
    }
    const overviewLimited = !term && !selected && !showIsolated && data.nodes.some((node) => matchesCategory(node) && adjacent.has(node.id)) && nodes.length === OVERVIEW_LIMIT;
    const visible = new Set(nodes.map((node) => node.id));
    edges = edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target));
    const pos = new Map<string, { x: number; y: number }>();
    const cols = CATEGORIES.map((spec, ci) => {
      const items = nodes.filter((node) => categoryOf(node) === spec.key).sort((a, b) => a.name.localeCompare(b.name, "de"));
      const totalHeight = Math.max(0, (items.length - 1) * ROW);
      items.forEach((node, i) => pos.set(node.id, { x: X[ci], y: PAD + 28 + i * ROW }));
      return { ...spec, nodes: items, x: X[ci], totalHeight };
    }).filter((col) => col.nodes.length > 0);
    const maxCount = Math.max(1, ...cols.map((col) => col.nodes.length));
    const height = PAD * 2 + 28 + maxCount * ROW;
    const relations = [...new Set(data.edges.map((edge) => edge.relation))].sort();
    const chosen = selected ? byId.get(selected) : undefined;
    const incident = chosen ? data.edges.filter((edge) => edge.source === chosen.id || edge.target === chosen.id) : [];
    return { byId, categoryOf, nodes, edges, pos, cols, height, relations, chosen, incident, overviewLimited };
  }, [data, q, category, relationFilter, neighborsOnly, selected]);

  if (loading && !data) return <Loading label="Graph wird geladen …" />;
  if (!model || !data) return <div className="fa-page">{error && <ErrorBox message={error} onRetry={reload} />}</div>;
  const focus = hover ?? selected;
  const connected = (id: string) => !focus || focus === id || model.edges.some((edge) => (edge.source === focus && edge.target === id) || (edge.target === focus && edge.source === id));
  const clearFilters = () => { setQ(""); setCategory("all"); setRelationFilter("all"); setNeighborsOnly(true); setShowIsolated(false); setSelected(null); };

  return (
    <div className="fa-page">
      <PageHead title="Graph" sub="Entitäten und ihre belegten Beziehungen">
        <input className="fa-search-sm fa-graph__search" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Entity suchen …" aria-label="Entity im Graph suchen" />
        <button className="htgf-btn htgf-btn--outline htgf-btn--small" onClick={reload}>Aktualisieren</button>
      </PageHead>
      {error && <ErrorBox message={error} onRetry={reload} />}
      <section className="fa-card fa-graph">
        <div className="fa-graph__intro"><div><h2>Zusammenhänge</h2><p className="fa-meta">{data.nodes.length} Entities · {data.edges.length} Beziehungen · {data.mode ?? "Modus unbekannt"}</p></div></div>
        {data.nodes.length === 0 ? <Empty title="Der Graph ist noch leer."><p className="fa-muted">Fundstellen verarbeiten, dann erscheinen hier Entities und ihre Beziehungen.</p></Empty> : <>
          <div className="fa-graph__controls">
            <div className="fa-graph__filters" aria-label="Entitytypen filtern">
              <button className={`fa-chip${category === "all" ? " is-on" : ""}`} onClick={() => setCategory("all")}>Alle <span>{data.nodes.length}</span></button>
              {CATEGORIES.map((spec) => <button key={spec.key} className={`fa-chip${category === spec.key ? " is-on" : ""}`} onClick={() => setCategory(spec.key)}>{spec.title} <span>{data.nodes.filter(spec.match).length}</span></button>)}
            </div>
            <div className="fa-graph__options">
              <label className="fa-graph__select-label">Beziehung<select value={relationFilter} onChange={(event) => setRelationFilter(event.target.value)}><option value="all">Alle Arten</option>{model.relations.map((relation) => <option key={relation} value={relation}>{labelRelation(relation)}</option>)}</select></label>
              <details className="fa-graph__advanced"><summary>Ansicht</summary><div><label className="fa-graph__toggle"><input type="checkbox" checked={neighborsOnly} onChange={(event) => setNeighborsOnly(event.target.checked)} /> Direkte Umgebung bei Auswahl</label><label className="fa-graph__toggle"><input type="checkbox" checked={showIsolated} onChange={(event) => setShowIsolated(event.target.checked)} /> Entities ohne Verbindung</label><label className="fa-graph__toggle"><input type="checkbox" checked={showLabels} onChange={(event) => setShowLabels(event.target.checked)} /> Beziehungstexte anzeigen</label></div></details>
              <button className="fa-link fa-graph__reset" onClick={clearFilters}>Filter zurücksetzen</button>
            </div>
          </div>
          <div className="fa-graph__workspace">
            <div className="fa-graph__canvas-wrap">
              {model.nodes.length === 0 ? <Empty title="Keine Entities für diese Auswahl."><button className="fa-link" onClick={clearFilters}>Filter zurücksetzen</button></Empty> : <svg viewBox={`0 0 ${W} ${model.height}`} className="fa-graph__svg" role="group" aria-label="Interaktiver Beziehungsgraph">
                <defs><marker id="fa-graph-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
                {model.cols.map((col) => <g key={col.key} className={`fa-graph__lane fa-graph__lane--${col.color}`}><rect x={col.x - 155} y={18} width="310" height={model.height - 36} rx="24"/><text x={col.x} y={PAD} textAnchor="middle" className="fa-graph__col">{col.title}<tspan> {col.nodes.length}</tspan></text></g>)}
                {model.edges.map((edge) => {
                  const a = model.pos.get(edge.source); const b = model.pos.get(edge.target); if (!a || !b) return null;
                  const left = a.x <= b.x ? a : b; const right = a.x <= b.x ? b : a; const active = !focus || edge.source === focus || edge.target === focus;
                  const mid = (left.x + right.x) / 2; const curve = `M ${left.x + 72} ${left.y} C ${mid} ${left.y}, ${mid} ${right.y}, ${right.x - 72} ${right.y}`;
                  return <g key={edge.id} className={`fa-graph__edge${active ? " is-active" : " is-muted"}`}><path d={curve} markerEnd="url(#fa-graph-arrow)" />{showLabels && active && <text x={mid} y={(left.y + right.y) / 2 - 7} textAnchor="middle" className="fa-graph__rel">{labelRelation(edge.relation)}</text>}</g>;
                })}
                {model.cols.flatMap((col) => col.nodes.map((node) => {
                  const p = model.pos.get(node.id)!; const isSelected = selected === node.id; const isDim = !connected(node.id); const title = node.name.length > 23 ? `${node.name.slice(0, 22)}…` : node.name;
                  return <g key={node.id} className={`fa-graph__node fa-graph__node--${col.color}${isSelected ? " is-selected" : ""}${isDim ? " is-dim" : ""}`} transform={`translate(${p.x} ${p.y})`} onMouseEnter={() => setHover(node.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(node.id)} onBlur={() => setHover(null)} onClick={() => setSelected(isSelected ? null : node.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(isSelected ? null : node.id); } }} tabIndex={0} role="button" aria-pressed={isSelected} aria-label={`${node.name} auswählen`}>
                    <title>{node.name} · {node.labels.join(", ")}</title><rect x={-78} y={-23} width={156} height={46} rx={col.key === "venture" ? 15 : 23}/><circle className="fa-graph__dot" cx={-58} cy={0} r={5}/><text textAnchor="middle" y={5}>{title}</text>
                  </g>;
                }))}
              </svg>}
              <p className="fa-graph__count">{model.nodes.length} angezeigt{model.overviewLimited ? ` · ${data.nodes.length} insgesamt, Auswahl nach Vernetzung` : ""} <span>·</span> Entity anklicken oder suchen für direkte Beziehungen</p>
            </div>
            <aside className="fa-graph__detail" aria-live="polite">
              {model.chosen ? <>
                <div className="fa-graph__detail-top"><span className={`fa-graph__type fa-graph__type--${model.categoryOf(model.chosen!)}`}>{CATEGORIES.find((spec) => spec.key === model.categoryOf(model.chosen!))?.singular}</span><button className="fa-graph__close" onClick={() => setSelected(null)} aria-label="Auswahl aufheben">×</button></div>
                <h3>{model.chosen.name}</h3>
                <p className="fa-meta">{model.chosen.labels.join(" · ")}</p>
                {model.chosen.location && <p className="fa-graph__location">⌖ {model.chosen.location}</p>}
                <div className="fa-graph__degree"><b>{model.incident.length}</b><span>direkte Beziehungen</span></div>
                {model.incident.length ? <ul className="fa-graph__neighbor-list">{model.incident.slice(0, 8).map((edge) => { const otherId = edge.source === model.chosen!.id ? edge.target : edge.source; return <li key={edge.id}><span>{labelRelation(edge.relation)}</span><button onClick={() => setSelected(otherId)}>{model.byId.get(otherId)?.name ?? otherId}</button>{edge.fact && <small>{edge.fact}</small>}</li>; })}</ul> : <p className="fa-meta">Noch keine Beziehungen gespeichert.</p>}
                {model.categoryOf(model.chosen) === "venture" && <button className="htgf-btn htgf-btn--primary htgf-btn--small fa-graph__open" onClick={() => onOpen(model.chosen!.id)}>Startup-Profil öffnen →</button>}
              </> : <div className="fa-graph__hint"><span className="fa-graph__hint-icon">✳</span><h3>Entity auswählen</h3><p>Klicke einen Knoten an. Dann siehst du direkte Verbindungen, Beziehungsdetails und den Weg zum Startup-Profil.</p></div>}
            </aside>
          </div>
          {model.edges.length > 0 && <details className="fa-graph__table"><summary>Alle Beziehungen als Liste <span>{model.edges.length}</span></summary><div className="fa-graph__table-scroll"><table className="fa-table"><thead><tr><th>Von</th><th>Beziehung</th><th>Zu</th><th>Quellenaussage</th><th>Fundstellen</th></tr></thead><tbody>{model.edges.map((edge: GraphEdge) => <tr key={edge.id} onMouseEnter={() => setHover(edge.source)} onMouseLeave={() => setHover(null)}><td><button className="fa-link" onClick={() => setSelected(edge.source)}>{model.byId.get(edge.source)?.name ?? edge.source}</button></td><td>{labelRelation(edge.relation)}</td><td><button className="fa-link" onClick={() => setSelected(edge.target)}>{model.byId.get(edge.target)?.name ?? edge.target}</button></td><td>{edge.fact ?? "–"}</td><td>{edge.episode_ids?.length ?? 0}</td></tr>)}</tbody></table></div></details>}
        </>}
      </section>
    </div>
  );
}
