"use client";

import { useLoad } from "./hooks";
import { useEffect } from "react";
import type { Candidate } from "./types";
import { Empty, ErrorBox, Loading } from "./ui";

export function Shortlist({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, error, loading, reload } = useLoad(
    (api) => api.listCandidates({ status: "shortlisted", limit: 200 }), [],
  );
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  return <div className="fa-page">
    <header className="fa-landscape__header"><h1>Shortlist</h1></header>
    <section className="fa-card fa-shortlist">
      {loading && !data && <Loading label="" />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {data && data.items.length === 0 && <Empty title="Noch keine gemerkten Kandidaten." />}
      {data && data.items.length > 0 && <ul className="fa-shortlist__items">
        {data.items.map((candidate) => <ShortlistRow key={candidate.id} candidate={candidate} onOpen={onOpen} />)}
      </ul>}
    </section>
  </div>;
}

function ShortlistRow({ candidate, onOpen }: { candidate: Candidate; onOpen: (id: string) => void }) {
  return <li>
    <button className="fa-shortlist__item" onClick={() => onOpen(candidate.id)}>
      <span><b>{candidate.name}</b><small>{candidate.location || ""}</small></span>
      {candidate.assessment_rankable && typeof candidate.assessment?.score === "number" && <strong>{candidate.assessment.score}<small>/100</small></strong>}
      <span className="fa-shortlist__arrow" aria-hidden="true">↗</span>
    </button>
  </li>;
}
