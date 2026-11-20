"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { CandidatePanel } from "./CandidatePanel";
import { useLoad } from "./hooks";
import type { FinderApi } from "./api/client";
import type { Candidate } from "./types";
import { Empty, ErrorBox, Loading } from "./ui";

const PAGE_SIZE = 200;

async function loadAllCandidates(api: FinderApi) {
  const first = await api.listCandidates({ limit: PAGE_SIZE, offset: 0 });
  const items = [...first.items];
  for (let offset = PAGE_SIZE; offset < first.total; offset += PAGE_SIZE) {
    items.push(...(await api.listCandidates({ limit: PAGE_SIZE, offset })).items);
  }
  return { items, total: first.total };
}

function rank(candidate: Candidate) {
  const score = candidate.assessment?.score;
  return candidate.assessment_rankable && typeof score === "number" ? score : null;
}

function Bubble({ candidate, selected, onSelect }: { candidate: Candidate; selected: boolean; onSelect: () => void }) {
  const score = rank(candidate) ?? 0;
  const diameter = Math.round(104 + 108 * Math.pow(score / 100, 1.5));
  return (
    <button
      className={`fa-landscape__bubble${selected ? " is-selected" : ""}`}
      onClick={onSelect}
      style={{ "--bubble-diameter": `${diameter}px` } as CSSProperties & { "--bubble-diameter": string }}
      aria-pressed={selected}
      aria-label={`${candidate.name}: ${score} von 100. Profil öffnen`}
    >
      <span className="fa-landscape__bubble-name">{candidate.name}</span>
      <span className="fa-landscape__bubble-score">{score}</span>
    </button>
  );
}

export function PotentialMap({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string | null) => void }) {
  const { data, error, loading, reload } = useLoad(loadAllCandidates, []);
  const [query, setQuery] = useState("");
  const term = query.trim().toLocaleLowerCase("de");
  const candidates = useMemo(() => (data?.items ?? [])
    .filter((candidate) => candidate.status === "new" || candidate.id === selectedId)
    .filter((candidate) => rank(candidate) !== null)
    .filter((candidate) => !term || `${candidate.name} ${candidate.description} ${candidate.location}`.toLocaleLowerCase("de").includes(term))
    .sort((a, b) => (rank(b) ?? 0) - (rank(a) ?? 0) || a.name.localeCompare(b.name, "de")), [data, term]);
  const selected = data?.items.find((candidate) => candidate.id === selectedId);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  return (
    <div className="fa-landscape-page">
      <header className="fa-landscape__header">
        <h1>Entdecken</h1>
        <label className="fa-landscape__search">
          <span aria-hidden="true">⌕</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Kandidat suchen" aria-label="Kandidaten suchen" />
        </label>
      </header>

      <section className={`fa-landscape${selected ? " has-selection" : ""}`} aria-label="Kandidaten nach Potenzial">
        {loading && !data && <div className="fa-landscape__loading"><Loading label="" /></div>}
        {error && <ErrorBox message={error} onRetry={reload} />}
        {data && candidates.length === 0 && !selected && <Empty title={data.total === 0 ? "Noch keine Kandidaten vorhanden." : "Keine Treffer."} />}
        {data && (candidates.length > 0 || selected) && <>
          <div className="fa-landscape__field">
            <div className="fa-landscape__field-caption"><b>{candidates.length} Kandidaten</b><span>Größerer Kreis = höheres Potenzial</span></div>
            <div className="fa-landscape__bubbles">
              {candidates.map((candidate) => <Bubble key={candidate.id} candidate={candidate} selected={candidate.id === selectedId} onSelect={() => onSelect(candidate.id === selectedId ? null : candidate.id)} />)}
            </div>
          </div>
          {selected && <aside className="fa-landscape__profile" aria-label={`${selected.name}: Profil`}>
            <CandidatePanel key={selected.id} id={selected.id} onChanged={reload} onClose={() => onSelect(null)} />
          </aside>}
        </>}
      </section>
    </div>
  );
}
