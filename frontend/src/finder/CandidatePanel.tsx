"use client";

import { useState } from "react";
import { useApi, useJobPolling, useLoad } from "./hooks";
import type { CandidateDetail, CandidateStatus, Evidence, Job } from "./types";
import { Demo, ErrorBox, GERMANY_LABEL, JOB_KIND, JobBadge, Loading, PriorityPill, RATING_LABEL, Unknown, fmtDate, fmtTime } from "./ui";

const SIGNAL_KIND: Record<string, string> = {
  founding_intent: "Gründungsabsicht",
  prototype: "Prototyp",
  germany_location: "Standort",
  pilot_interest: "Pilotinteresse",
  funding: "Förderung",
  hiring: "Einstellung",
  launch: "Produktstart",
  event: "Event",
};
const FIELD_LABEL: Record<string, string> = { location: "Standort", website: "Website", description: "Beschreibung", name: "Name", people: "Personen" };

/** Numbered source marker right next to a statement. Click: text passage + link to the original. */
function EvidenceRefs({ ids, evidence }: { ids: (string | null | undefined)[]; evidence: Evidence[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const clean = ids.filter((x): x is string => !!x);
  if (!clean.length) return <span className="fa-noev">ohne Beleg</span>;
  return (
    <span className="fa-refs">
      {clean.map((id) => {
        const i = evidence.findIndex((e) => e.id === id);
        const e = evidence[i];
        if (!e)
          return (
            <span key={id} className="fa-noev" title={id}>
              Beleg fehlt
            </span>
          );
        return (
          <span key={id} className="fa-ref">
            <button className={`fa-ref__btn${open === id ? " is-on" : ""}`} onClick={() => setOpen(open === id ? null : id)} aria-expanded={open === id} aria-label={`Beleg ${i + 1} anzeigen`}>
              {i + 1}
            </button>
            {open === id && (
              <span className="fa-ref__pop" role="dialog" aria-label={`Beleg ${i + 1}`}>
                <span className="fa-ref__src">
                  {e.kind === "exact_quote" ? "Wörtliches Zitat" : "Dokumentausschnitt"} · {e.title ?? "ohne Titel"}
                </span>
                <q>{e.quote}</q>
                {e.kind === "source_excerpt" && <span className="fa-ref__note">Ausschnitt belegt nicht jede einzelne Profilaussage.</span>}
                {e.url ? (
                  <a href={e.url} target="_blank" rel="noreferrer">
                    Original öffnen ↗
                  </a>
                ) : (
                  <Unknown>kein Link zum Original</Unknown>
                )}
              </span>
            )}
          </span>
        );
      })}
    </span>
  );
}

export function CandidatePanel({ id, onChanged, onClose }: { id: string; onChanged: () => void; onClose: () => void }) {
  const { api, toast } = useApi();
  const { data: c, error, loading, reload, setData } = useLoad((a) => a.getCandidate(id), [id]);
  const [busy, setBusy] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const job = useJobPolling(jobId, (j: Job) => {
    setJobId(null);
    if (j.status === "succeeded") {
      toast(`${JOB_KIND[j.kind] ?? j.kind} abgeschlossen – Profil neu geladen`);
      reload();
      onChanged();
    } else toast(`${JOB_KIND[j.kind] ?? j.kind} fehlgeschlagen: ${j.error ?? "unbekannt"}`, "error");
  });

  if (loading && !c) return <Loading label="Kandidat wird geladen …" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!c) return null;

  const setStatus = async (status: CandidateStatus) => {
    setBusy("status");
    try {
      const updated = await api.patchCandidate(c.id, { status });
      setData({ ...c, status: updated.status, updated_at: updated.updated_at } as CandidateDetail);
      toast(status === "shortlisted" ? "Auf die Shortlist gesetzt" : status === "rejected" ? "Verworfen" : "Zurück auf „Neu“");
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Speichern fehlgeschlagen", "error");
    } finally {
      setBusy(null);
    }
  };
  const startJob = async (kind: "research" | "evaluate") => {
    setBusy(kind);
    try {
      const { job } = kind === "research" ? await api.research(c.id) : await api.evaluate(c.id);
      setJobId(job.id);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Konnte nicht gestartet werden", "error");
    } finally {
      setBusy(null);
    }
  };
  const saveNote = async () => {
    setBusy("note");
    try {
      const n = await api.addNote(c.id, note);
      setData({ ...c, notes: [n, ...c.notes] });
      setNote("");
      toast("Notiz gespeichert");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Notiz nicht gespeichert", "error");
    } finally {
      setBusy(null);
    }
  };

  const a = c.assessment;
  const questions = [...new Set([...(c.open_questions ?? []), ...(a?.open_questions ?? [])])];
  const running = !!jobId;

  return (
    <article className="fa-cand">
      {/* Überblick – Quelldaten */}
      <header className="fa-cand__head">
        <div className="fa-cand__top">
          <p className="fa-meta">
            {c.location || <Unknown>Standort unbekannt</Unknown>} · {GERMANY_LABEL[c.germany_status]} ·{" "}
            {c.website ? (
              <a href={c.website} target="_blank" rel="noreferrer">
                Website ↗
              </a>
            ) : (
              <Unknown>keine Website bekannt</Unknown>
            )}{" "}
            <Demo show={c.is_demo} />
          </p>
          <button className="fa-close" onClick={onClose} aria-label="Detail schließen">
            ✕
          </button>
        </div>
        <h2>{c.name}</h2>
        <p className="fa-cand__desc">{c.description || <Unknown>Produktbeschreibung unbekannt</Unknown>}</p>
        <div className="fa-cand__actions">
          {c.status !== "shortlisted" ? (
            <button className="htgf-btn" disabled={busy === "status"} onClick={() => setStatus("shortlisted")}>
              Merken
            </button>
          ) : (
            <button className="htgf-btn htgf-btn--outline" disabled={busy === "status"} onClick={() => setStatus("new")}>
              Gemerkt
            </button>
          )}
          <button className="fa-link" disabled={busy === "status"} onClick={() => setStatus(c.status === "rejected" ? "new" : "rejected")}>
            {c.status === "rejected" ? "Wiederherstellen" : "Verwerfen"}
          </button>
          <span className="fa-cand__jobs">
            <button className="fa-link" disabled={running || !!busy} onClick={() => startJob("research")}>
              Recherche starten
            </button>
            <button className="fa-link" disabled={running || !!busy} onClick={() => startJob("evaluate")}>
              Neu bewerten
            </button>
          </span>
        </div>
        {running && (
          <p className="fa-running" role="status">
            <span className="fa-spinner" aria-hidden="true" /> {JOB_KIND[job?.kind ?? ""] ?? "Job"} {job ? <JobBadge s={job.status} /> : "wird gestartet"} – das Profil wird danach neu geladen.
          </p>
        )}
      </header>

      {/* KI-Einschätzung – getrennt von den Quelldaten */}
      <section className="fa-ai" aria-label="KI-Einschätzung">
        <div className="fa-ai__label">
          <b>KI-Einschätzung</b>
          {a && (
            <span>
              {a.model ?? "Modell unbekannt"} · Profil v{a.profile_version ?? "?"} · Kriterien {a.criteria_version ?? "?"} · {fmtTime(a.created_at)}
            </span>
          )}
        </div>
        {!a ? (
          <p className="fa-muted">Noch keine Bewertung. „Neu bewerten“ startet sie im Backend.</p>
        ) : (
          <>
            {c.assessment_stale && <p className="fa-stale">Das Profil ist neuer als diese Bewertung. „Neu bewerten“ aktualisiert sie.</p>}
            <div className="fa-ai__top">
              <PriorityPill p={a.priority} />
              <p className="fa-hint">Priorisierung für das Sourcing – keine Erfolgswahrscheinlichkeit.</p>
            </div>
            <p className="fa-ai__summary">
              {a.summary} <EvidenceRefs ids={a.evidence_ids} evidence={c.evidence} />
            </p>
            {a.criteria.length > 0 && (
              <table className="fa-crit">
                <thead>
                  <tr>
                    <th>Kriterium</th>
                    <th>Einschätzung</th>
                    <th>Begründung und Belege</th>
                  </tr>
                </thead>
                <tbody>
                  {a.criteria.map((k) => (
                    <tr key={k.key}>
                      <td>{k.label}</td>
                      <td>
                        <span className={`fa-rating fa-rating--${k.rating}`}>{RATING_LABEL[k.rating] ?? k.rating}</span>
                      </td>
                      <td>
                        {k.rationale} <EvidenceRefs ids={k.evidence_ids} evidence={c.evidence} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="fa-cols">
              <div>
                <h4>Stärken</h4>
                {a.strengths.length ? (
                  <ul>
                    {a.strengths.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                ) : (
                  <Unknown>keine genannt</Unknown>
                )}
              </div>
              <div>
                <h4>Gegenargumente</h4>
                {a.concerns.length ? (
                  <ul>
                    {a.concerns.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                ) : (
                  <Unknown>keine genannt</Unknown>
                )}
              </div>
            </div>
          </>
        )}
      </section>

      {/* Quelldaten */}
      {c.conflicts && c.conflicts.length > 0 && (
        <section className="fa-sec">
          <h3>
            Widersprüche <span>werden nicht still überschrieben</span>
          </h3>
          <ul className="fa-rows fa-rows--conflicts">
            {c.conflicts.map((k, i) => (
              <li key={i}>
                <span className="fa-rows__kind">{FIELD_LABEL[k.field] ?? k.field}</span>
                <span>
                  bisher <b>{k.previous || "leer"}</b>, neu <b>{k.incoming || "leer"}</b>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="fa-sec">
        <h3>Offene Fragen</h3>
        {questions.length ? (
          <ul className="fa-list">
            {questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        ) : (
          <p className="fa-muted">Keine offenen Fragen erfasst.</p>
        )}
      </section>

      <section className="fa-sec">
        <h3>
          Signale <span>aus Quelldaten</span>
        </h3>
        {c.signals.length ? (
          <ol className={`fa-rows fa-rows--signals${c.signals.some((x) => x.date) ? "" : " no-date"}`}>
            {[...c.signals]
              .sort((x, y) => (y.date ?? "").localeCompare(x.date ?? ""))
              .map((s) => (
                <li key={s.id}>
                  <span className="fa-rows__date">{s.date ? fmtDate(s.date) : "–"}</span>
                  <span className="fa-rows__kind">{(SIGNAL_KIND[s.kind] ?? s.kind.replace(/_/g, " ")) === s.label ? "" : SIGNAL_KIND[s.kind] ?? s.kind.replace(/_/g, " ")}</span>
                  <span>
                    {s.label}
                    {s.verification && <span className="fa-meta"> · {s.verification}</span>} <EvidenceRefs ids={[s.evidence_id]} evidence={c.evidence} />
                  </span>
                </li>
              ))}
          </ol>
        ) : (
          <p className="fa-muted">Keine Signale.</p>
        )}
      </section>

      <section className="fa-sec">
        <h3>Personen</h3>
        {c.people.length ? (
          <ul className="fa-list">
            {c.people.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : (
          <p>
            <Unknown>Team unbekannt</Unknown>
          </p>
        )}
      </section>

      <section className="fa-sec">
        <h3>
          Belege <span>{c.evidence.length}</span>
        </h3>
        {c.evidence.length ? (
          <ol className="fa-ev">
            {c.evidence.map((e, i) => (
              <li key={e.id}>
                <span className="fa-ev__n">{i + 1}</span>
                <div>
                  <q>{e.quote}</q>
                  <p className="fa-meta">
                    {e.kind === "exact_quote" ? "Wörtliches Zitat" : "Dokumentausschnitt"} · {e.title ?? "ohne Titel"} · veröffentlicht {e.published_at ? fmtDate(e.published_at) : "unbekannt"} · abgerufen {fmtDate(e.fetched_at)} ·{" "}
                    {e.url ? (
                      <a href={e.url} target="_blank" rel="noreferrer">
                        Original ↗
                      </a>
                    ) : (
                      <Unknown>kein Link</Unknown>
                    )}{" "}
                    <Demo show={e.is_demo} />
                  </p>
                  {e.attribution && <p className="fa-meta fa-small">{e.attribution}</p>}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="fa-muted">Noch keine Belege.</p>
        )}
      </section>

      <section className="fa-sec">
        <h3>Notizen</h3>
        <div className="fa-note">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Notiz für das Team …" aria-label="Neue Notiz" rows={3} />
          <button className="htgf-btn htgf-btn--small" disabled={!note.trim() || busy === "note"} onClick={saveNote}>
            {busy === "note" ? "Speichert …" : "Notiz speichern"}
          </button>
        </div>
        {c.notes.length > 0 && (
          <ul className="fa-rows fa-rows--notes">
            {c.notes.map((n) => (
              <li key={n.id}>
                <span className="fa-rows__date">{fmtTime(n.created_at)}</span>
                <span>{n.text}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="fa-sec">
        <h3>Rechercheverlauf</h3>
        {c.research_runs.length ? (
          <ol className="fa-rows fa-rows--notes">
            {c.research_runs.map((r) => (
              <li key={r.id}>
                <span className="fa-rows__date">{fmtTime(r.created_at)}</span>
                <span>
                  {r.summary} <Demo show={r.is_demo} />
                  <span className="fa-meta">
                    {" "}
                    · {r.sources.length} Quellen · {r.imported_finding_ids.length} importierte Fundstellen
                    {r.fetch_errors.length > 0 && <span className="fa-err">{r.fetch_errors.length} Abruffehler</span>}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="fa-muted">Noch keine Recherche gelaufen.</p>
        )}
      </section>
    </article>
  );
}
