"use client";

import { useEffect, useState } from "react";
import { useApi, useLoad } from "./hooks";
import type { CandidateDetail, CandidateStatus, Evidence } from "./types";
import { ErrorBox, GERMANY_LABEL, Loading, RATING_LABEL, fmtDate, fmtTime } from "./ui";

function EvidenceRefs({ ids, evidence }: { ids: (string | null | undefined)[]; evidence: Evidence[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const clean = ids.filter((id): id is string => !!id);
  if (!clean.length) return null;
  return <span className="fa-refs">
    {clean.map((id) => {
      const index = evidence.findIndex((item) => item.id === id);
      const item = evidence[index];
      if (!item) return null;
      return <span key={id} className="fa-ref">
        <button className={`fa-ref__btn${open === id ? " is-on" : ""}`} onClick={() => setOpen(open === id ? null : id)} aria-expanded={open === id} aria-label={`Beleg ${index + 1} anzeigen`}>{index + 1}</button>
        {open === id && <span className="fa-ref__pop" role="dialog" aria-label={`Beleg ${index + 1}`}>
          <span className="fa-ref__src">{item.title ?? "Quelle"} · {item.published_at ? fmtDate(item.published_at) : fmtDate(item.fetched_at)}</span>
          <q>{item.quote}</q>
          {item.url && <a href={item.url} target="_blank" rel="noreferrer">Original öffnen ↗</a>}
        </span>}
      </span>;
    })}
  </span>;
}

const FUNDING_STATUS: Record<string, string> = {
  confirmed: "Finanzierung belegt",
  not_found: "Keine Finanzierung öffentlich gefunden",
  unclear: "Finanzierungsstand unklar",
  not_researched: "",
};

export function CandidatePanel({ id, onChanged, onClose }: { id: string; onChanged: () => void; onClose: () => void }) {
  const { api, toast } = useApi();
  const { data: candidate, error, loading, reload, setData } = useLoad((client) => client.getCandidate(id), [id]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  if (loading && !candidate) return <Loading label="" />;
  if (error && !candidate) return <ErrorBox message={error} onRetry={reload} />;
  if (!candidate) return null;

  const assessment = candidate.assessment_current && typeof candidate.assessment?.score === "number" ? candidate.assessment : null;
  const contentDates = [assessment?.created_at, ...candidate.evidence.map((item) => item.fetched_at), ...candidate.research_runs.map((item) => item.created_at)]
    .filter((date): date is string => !!date).sort();
  const dataAsOf = contentDates.at(-1);

  const setStatus = async (status: CandidateStatus) => {
    setBusy(true);
    try {
      const updated = await api.patchCandidate(candidate.id, { status });
      setData({ ...candidate, status: updated.status, updated_at: updated.updated_at } as CandidateDetail);
      toast(status === "shortlisted" ? "Auf die Shortlist gesetzt" : status === "rejected" ? "Kandidat ausgeblendet" : "Kandidat wiederhergestellt");
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Speichern fehlgeschlagen", "error");
    } finally {
      setBusy(false);
    }
  };

  const saveNote = async () => {
    if (!note.trim()) return;
    setBusy(true);
    try {
      const saved = await api.addNote(candidate.id, note);
      setData({ ...candidate, notes: [saved, ...candidate.notes] });
      setNote("");
      toast("Notiz gespeichert");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Notiz nicht gespeichert", "error");
    } finally {
      setBusy(false);
    }
  };

  return <article className="fa-cand fa-cand--compact">
    <header className="fa-cand__head">
      <div className="fa-cand__top">
        <p className="fa-meta">{candidate.location || GERMANY_LABEL[candidate.germany_status]}{candidate.website && <> · <a href={candidate.website} target="_blank" rel="noreferrer">Website ↗</a></>}</p>
        <button className="fa-close" onClick={onClose} aria-label="Profil schließen">×</button>
      </div>
      <h2>{candidate.name}</h2>
      {candidate.description && <p className="fa-cand__desc">{candidate.description}</p>}
      <div className="fa-cand__actions">
        <button className={`htgf-btn${candidate.status === "shortlisted" ? " htgf-btn--outline" : ""}`} disabled={busy} onClick={() => setStatus(candidate.status === "shortlisted" ? "new" : "shortlisted")}>
          {candidate.status === "shortlisted" ? "Gemerkt" : "Merken"}
        </button>
        <button className="fa-link" disabled={busy} onClick={() => setStatus(candidate.status === "rejected" ? "new" : "rejected")}>
          {candidate.status === "rejected" ? "Wiederherstellen" : "Ausblenden"}
        </button>
      </div>
      {dataAsOf && <p className="fa-cand__updated">Aktualisiert {fmtTime(dataAsOf)}</p>}
    </header>

    {assessment && <section className="fa-cand__rank" aria-label="Bewertung und Begründung">
      <div className="fa-cand__rank-score"><strong>{assessment.score}</strong><span>/100</span></div>
      <p className="fa-cand__summary">{assessment.summary} <EvidenceRefs ids={assessment.evidence_ids} evidence={candidate.evidence} /></p>
      <details className="fa-cand__more">
        <summary>Warum dieser Score?</summary>
        <div className="fa-cand__criteria">
          {assessment.criteria.map((criterion) => <div className="fa-cand__criterion" key={criterion.key}>
            <div><b>{criterion.label}</b><span>{RATING_LABEL[criterion.rating] ?? criterion.rating}</span></div>
            <p>{criterion.rationale} <EvidenceRefs ids={criterion.evidence_ids} evidence={candidate.evidence} /></p>
          </div>)}
        </div>
        {assessment.strengths.length > 0 && <p><b>Stärken:</b> {assessment.strengths.join(" · ")}</p>}
        {assessment.concerns.length > 0 && <p><b>Risiken:</b> {assessment.concerns.join(" · ")}</p>}
      </details>
    </section>}

    <details className="fa-cand__more fa-cand__more--profile">
      <summary>Profil &amp; Quellen</summary>
      <div className="fa-cand__profile-data">
        {FUNDING_STATUS[candidate.funding_status ?? "not_researched"] && <p><b>{FUNDING_STATUS[candidate.funding_status ?? "not_researched"]}</b>{candidate.funding_summary && <> · {candidate.funding_summary}</>}</p>}
        {candidate.research_profile?.claims?.map((claim, index) => <p key={`${claim.field}:${index}`}><b>{claim.field.replaceAll("_", " ")}</b> · {claim.value} <EvidenceRefs ids={[claim.evidence_id]} evidence={candidate.evidence} /></p>)}
        {candidate.signals.map((signal) => <p key={signal.id}>{signal.date ? `${fmtDate(signal.date)} · ` : ""}{signal.label} <EvidenceRefs ids={[signal.evidence_id]} evidence={candidate.evidence} /></p>)}
        {candidate.people.length > 0 && <p><b>Team</b> · {candidate.people.join(", ")}</p>}
        {candidate.evidence.map((item, index) => <p key={item.id}><b>{item.title ?? `Quelle ${index + 1}`}</b> · {item.published_at ? fmtDate(item.published_at) : fmtDate(item.fetched_at)}{item.url && <> · <a href={item.url} target="_blank" rel="noreferrer">Öffnen ↗</a></>}</p>)}
      </div>
    </details>

    <details className="fa-cand__more fa-cand__more--notes">
      <summary>Teamnotizen{candidate.notes.length ? ` · ${candidate.notes.length}` : ""}</summary>
      <div className="fa-cand__notes">
        <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Notiz hinzufügen" aria-label="Notiz für das Team" rows={2} />
        <button className="htgf-btn htgf-btn--small" disabled={!note.trim() || busy} onClick={saveNote}>Speichern</button>
        {candidate.notes.map((item) => <p key={item.id}>{item.text}<small>{fmtTime(item.created_at)}</small></p>)}
      </div>
    </details>
  </article>;
}
