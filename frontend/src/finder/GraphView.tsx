"use client";

import { useMemo, useState } from "react";
import { useLoad } from "./hooks";
import type { GraphNode } from "./types";
import { Demo, Empty, ErrorBox, Loading, PageHead } from "./ui";

const RELATION: Record<string, string> = { WORKS_ON: "arbeitet an", FOUNDED: "gründet", SUPPORTED_BY: "begleitet von", AFFILIATED_WITH: "verbunden mit", LOCATED_IN: "sitzt in" };
const COLS = [
  { key: "person", title: "Personen", match: (n: GraphNode) => n.labels.includes("Person") },
  { key: "venture", title: "Startups", match: (n: GraphNode) => n.labels.includes("StartupVenture") },
  { key: "other", title: "Institutionen und Weiteres", match: (n: GraphNode) => !n.labels.includes("Person") && !n.labels.includes("StartupVenture") },
] as const;

const W = 1000;
const ROW = 56;
const PAD = 40;
const X = [140, 500, 860];

/** Read-only view of the materialised graph (GET /api/graph). Ventures open the candidate. */
export function GraphView({ onOpen }: { onOpen: (candidateId: string) => void }) {
  const { data, error, loading, reload } = useLoad((a) => a.graph(), []);
  const [hover, setHover] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const layout = useMemo(() => {
    if (!data) return null;
    const pos = new Map<string, { x: number; y: number; col: number }>();
    // only columns that have nodes; spread them across the width
    const filled = COLS.map((c) => ({ ...c, nodes: data.nodes.filter(c.match).sort((a, b) => a.name.localeCompare(b.name, "de")) })).filter((c) => c.nodes.length > 0 || c.key === "venture");
    const xs = filled.length === 3 ? X : filled.length === 2 ? [250, 750] : [500];
    const cols = filled.map((c, ci) => {
      c.nodes.forEach((n, i) => pos.set(n.id, { x: xs[ci], y: PAD + 30 + i * ROW, col: ci }));
      return { ...c, x: xs[ci] };
    });
    const height = PAD * 2 + 30 + Math.max(1, ...cols.map((c) => c.nodes.length)) * ROW;
    return { pos, cols, height };
  }, [data]);

  if (loading && !data) return <Loading label="Graph wird geladen …" />;

  const term = q.trim().toLowerCase();
  const nodeName = (id: string) => data?.nodes.find((n) => n.id === id)?.name ?? id;
  const connected = (id: string) => (hover ? hover === id || data!.edges.some((e) => (e.source === hover && e.target === id) || (e.target === hover && e.source === id)) : true);
  const matches = (n: GraphNode) => !term || n.name.toLowerCase().includes(term);

  return (
    <div className="fa-page">
      <PageHead title="Graph" sub="Personen, Startups, Institutionen">
        <input className="fa-search-sm fa-graph__search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Knoten suchen" aria-label="Knoten im Graph suchen" />
        <button className="htgf-btn htgf-btn--outline htgf-btn--small" onClick={reload}>
          Aktualisieren
        </button>
      </PageHead>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {data && layout && (
        <>
          <section className="fa-card fa-graph">
            <p className="fa-meta fa-graph__note">
              Materialisierte Ansicht aus dem Graph · Modus {data.mode ?? "unbekannt"} · {data.nodes.length} Knoten, {data.edges.length} Beziehungen. Startups anklicken öffnet das Profil.
            </p>
            {data.nodes.length === 0 ? (
              <Empty title="Der Graph ist noch leer.">
                <p className="fa-muted">Fundstellen verarbeiten, dann erscheinen hier Personen, Startups und ihre Beziehungen.</p>
              </Empty>
            ) : (
              <svg viewBox={`0 0 ${W} ${layout.height}`} className="fa-graph__svg" role="img" aria-label="Beziehungsgraph">
                {layout.cols.map((c) => (
                  <text key={c.key} x={c.x} y={PAD} textAnchor="middle" className="fa-graph__col">
                    {c.title} ({c.nodes.length})
                  </text>
                ))}
                {data.edges.map((e) => {
                  const a = layout.pos.get(e.source);
                  const b = layout.pos.get(e.target);
                  if (!a || !b) return null;
                  const [l, r] = a.x <= b.x ? [a, b] : [b, a];
                  const on = !hover || e.source === hover || e.target === hover;
                  const mx = (l.x + r.x) / 2;
                  return (
                    <g key={e.id} className={`fa-graph__edge${on ? "" : " is-dim"}${hover && on ? " is-on" : ""}`}>
                      <path d={`M ${l.x + 70} ${l.y} C ${mx} ${l.y}, ${mx} ${r.y}, ${r.x - 70} ${r.y}`} />
                      {hover && on && (
                        <text x={mx} y={(l.y + r.y) / 2 - 6} textAnchor="middle" className="fa-graph__rel">
                          {RELATION[e.relation] ?? e.relation.toLowerCase().replace(/_/g, " ")}
                        </text>
                      )}
                    </g>
                  );
                })}
                {layout.cols.map((c) =>
                  c.nodes.map((n) => {
                    const p = layout.pos.get(n.id)!;
                    const venture = c.key === "venture";
                    const dim = !connected(n.id) || !matches(n);
                    return (
                      <g
                        key={n.id}
                        className={`fa-graph__node fa-graph__node--${c.key}${dim ? " is-dim" : ""}${term && matches(n) ? " is-match" : ""}`}
                        transform={`translate(${p.x} ${p.y})`}
                        onMouseEnter={() => setHover(n.id)}
                        onMouseLeave={() => setHover(null)}
                        onFocus={() => setHover(n.id)}
                        onBlur={() => setHover(null)}
                        onClick={venture ? () => onOpen(n.id) : undefined}
                        onKeyDown={venture ? (ev) => ev.key === "Enter" && onOpen(n.id) : undefined}
                        tabIndex={0}
                        role={venture ? "link" : undefined}
                        aria-label={venture ? `${n.name} – Profil öffnen` : n.name}
                      >
                        <rect x={-70} y={-18} width={140} height={36} rx={18} />
                        <text textAnchor="middle" y={5}>
                          {n.name.length > 18 ? `${n.name.slice(0, 17)}…` : n.name}
                        </text>
                      </g>
                    );
                  }),
                )}
              </svg>
            )}
          </section>

          {data.edges.length > 0 && (
            <section className="fa-card">
              <h3 className="fa-h3">Beziehungen</h3>
              <table className="fa-table">
                <thead>
                  <tr>
                    <th>Von</th>
                    <th>Beziehung</th>
                    <th>Zu</th>
                    <th>Aussage aus der Quelle</th>
                    <th>Fundstellen</th>
                  </tr>
                </thead>
                <tbody>
                  {data.edges
                    .filter((e) => !term || nodeName(e.source).toLowerCase().includes(term) || nodeName(e.target).toLowerCase().includes(term))
                    .map((e) => (
                      <tr key={e.id} onMouseEnter={() => setHover(e.source)} onMouseLeave={() => setHover(null)}>
                        <td>{nodeName(e.source)}</td>
                        <td>{RELATION[e.relation] ?? e.relation}</td>
                        <td>{nodeName(e.target)}</td>
                        <td>
                          {e.fact ?? "–"} <Demo show={e.is_demo} />
                        </td>
                        <td>{e.episode_ids?.length ?? 0}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}
    </div>
  );
}
