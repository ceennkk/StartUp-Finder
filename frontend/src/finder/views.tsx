"use client";

import { useEffect, useState } from "react";
import { CandidatePanel } from "./CandidatePanel";
import { useApi, useJobPolling, useLoad } from "./hooks";
import type { CandidateQuery, Job, Search } from "./types";
import { Demo, Empty, ErrorBox, GERMANY_LABEL, JOB_KIND, JobBadge, Loading, PageHead, PriorityPill, STATUS_LABEL, Unknown, fmtDate, fmtTime } from "./ui";

const PAGE = 50;
const FINDING_STATUS: Record<string, string> = { new: "Neu", processing: "In Verarbeitung", processed: "Verarbeitet", failed: "Fehler" };
const errMsg = (e: unknown) => (e instanceof Error ? e.message : "Unbekannter Fehler");

/* ===================== 1 + 2 · Entdecken mit Detailpanel ===================== */
export function Discover({ selected, onSelect }: { selected: string | null; onSelect: (id: string | null) => void }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState<CandidateQuery["status"]>("new");
  const [priority, setPriority] = useState<CandidateQuery["priority"]>("");
  const [germany, setGermany] = useState<CandidateQuery["germany_status"]>("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(q);
      setOffset(0);
    }, 250);
    return () => clearTimeout(t);
  }, [q]);
  const { data, error, loading, reload } = useLoad(
    (api) => api.listCandidates({ q: debounced, status, priority, germany_status: germany, limit: PAGE, offset }),
    [debounced, status, priority, germany, offset],
  );

  return (
    <div className="fa-page">
      <div className="fa-toolbar">
        <h1>
          Entdecken <em>neue Kandidaten</em>
        </h1>
        <label className="fa-search">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, Beschreibung oder Ort" aria-label="Kandidaten nach Name, Beschreibung oder Ort durchsuchen" />
        </label>
        <div className="fa-filters">
          <select value={status} onChange={(e) => (setStatus(e.target.value as CandidateQuery["status"]), setOffset(0))} aria-label="Status" className={status ? "is-set" : ""}>
            <option value="">Alle Status</option>
            <option value="new">Neu</option>
            <option value="shortlisted">Gemerkt</option>
            <option value="rejected">Verworfen</option>
          </select>
          <select value={priority} onChange={(e) => (setPriority(e.target.value as CandidateQuery["priority"]), setOffset(0))} aria-label="Priorität" className={priority ? "is-set" : ""}>
            <option value="">Jede Priorität</option>
            <option value="high">Hoch</option>
            <option value="medium">Mittel</option>
            <option value="low">Niedrig</option>
            <option value="insufficient_data">Zu wenig Daten</option>
          </select>
          <select value={germany} onChange={(e) => (setGermany(e.target.value as CandidateQuery["germany_status"]), setOffset(0))} aria-label="Deutschland-Bezug" className={germany ? "is-set" : ""}>
            <option value="">Jeder Standort</option>
            <option value="confirmed">Deutschland bestätigt</option>
            <option value="likely">Deutschland wahrscheinlich</option>
            <option value="unknown">Standort unklar</option>
            <option value="outside_germany">Außerhalb Deutschlands</option>
          </select>
        </div>
      </div>
      <div className="fa-discover">
        <section className="fa-card fa-results">
          {loading && !data && <Loading label="Kandidaten werden geladen …" />}
          {error && <ErrorBox message={error} onRetry={reload} />}
          {data && (
            <>
              <p className="fa-count">
                {data.total} {data.total === 1 ? "Kandidat" : "Kandidaten"}
                {loading && <span className="fa-spinner fa-spinner--inline" aria-label="aktualisiert" />}
              </p>
              {data.items.length === 0 ? (
                <Empty title="Keine Kandidaten für diese Filter.">
                  <p className="fa-muted">Filter lockern oder unter „Quellen“ Fundstellen verarbeiten.</p>
                </Empty>
              ) : (
                <ul className="fa-items">
                  {data.items.map((c) => (
                    <li key={c.id}>
                      <button className={`fa-item${selected === c.id ? " is-on" : ""}`} onClick={() => onSelect(c.id)} aria-current={selected === c.id}>
                        <span className="fa-item__head">
                          <b>{c.name}</b>
                          <Demo show={c.is_demo} />
                        </span>
                        <span className="fa-item__meta">
                          {c.location || "Ort unbekannt"} · {GERMANY_LABEL[c.germany_status]}
                        </span>
                        <span className="fa-item__desc">{c.description || <Unknown>Beschreibung unbekannt</Unknown>}</span>
                        <span className="fa-item__foot">
                          <PriorityPill p={c.assessment?.priority} />
                          {c.assessment_stale && <span className="fa-tag">Bewertung veraltet</span>}
                          {c.status !== "new" && <span className="fa-tag">{STATUS_LABEL[c.status]}</span>}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {data.total > PAGE && (
                <div className="fa-pager">
                  <button className="fa-link" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                    ← Zurück
                  </button>
                  <span>
                    {offset + 1}–{Math.min(offset + PAGE, data.total)} von {data.total}
                  </span>
                  <button className="fa-link" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
                    Weiter →
                  </button>
                </div>
              )}
            </>
          )}
        </section>
        <section className="fa-card fa-detail">
          {selected ? (
            <CandidatePanel key={selected} id={selected} onChanged={reload} onClose={() => onSelect(null)} />
          ) : (
            <Empty title="Kandidat auswählen">
              <p className="fa-muted">Links einen Eintrag wählen. Profil, Belege und Bewertung erscheinen hier.</p>
            </Empty>
          )}
        </section>
      </div>
    </div>
  );
}

/* ===================== 3 · Shortlist ===================== */
export function Shortlist({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, error, loading, reload } = useLoad((api) => api.listCandidates({ status: "shortlisted", limit: 200 }), []);
  return (
    <div className="fa-page">
      <PageHead title="Shortlist" sub="gemerkte Kandidaten" />
      <section className="fa-card">
        {loading && !data && <Loading />}
        {error && <ErrorBox message={error} onRetry={reload} />}
        {data && data.items.length === 0 && (
          <Empty title="Noch niemand gemerkt.">
            <p className="fa-muted">In „Entdecken“ einen Kandidaten öffnen und „Merken“ wählen.</p>
          </Empty>
        )}
        {data && data.items.length > 0 && (
          <ul className="fa-table-list">
            {data.items.map((c) => (
              <ShortlistRow key={c.id} id={c.id} onOpen={onOpen} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ShortlistRow({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  const { api, toast } = useApi();
  const { data, error, setData } = useLoad((a) => a.getCandidate(id), [id]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  if (error) return <li className="fa-short"><ErrorBox message={error} /></li>;
  if (!data) return <li className="fa-short"><Loading /></li>;
  return (
    <li className="fa-short">
      <div>
        <b>{data.name}</b> <Demo show={data.is_demo} />
        <p className="fa-meta">
          {data.location || "Ort unbekannt"} · <PriorityPill p={data.assessment?.priority} />
        </p>
        {data.assessment?.summary && (
          <p className="fa-short__sum">
            <span className="fa-ai-tag">KI</span> {data.assessment.summary}
          </p>
        )}
        <button className="fa-link" onClick={() => onOpen(id)}>
          Details öffnen
        </button>
      </div>
      <div>
        {data.notes.length > 0 ? (
          <ul className="fa-notes">
            {data.notes.map((n) => (
              <li key={n.id}>
                <span className="fa-meta">{fmtTime(n.created_at)}</span> {n.text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="fa-muted">Keine Notizen.</p>
        )}
        <div className="fa-note">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Notiz hinzufügen" aria-label={`Notiz zu ${data.name}`} />
          <button
            className="htgf-btn htgf-btn--small"
            disabled={!note.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                const n = await api.addNote(id, note);
                setData({ ...data, notes: [n, ...data.notes] });
                setNote("");
                toast("Notiz gespeichert");
              } catch (e) {
                toast(errMsg(e), "error");
              } finally {
                setSaving(false);
              }
            }}
          >
            {saving ? "Speichert …" : "Speichern"}
          </button>
        </div>
      </div>
    </li>
  );
}

/* ===================== 4 · Suchaufträge ===================== */
export function Searches({ onFindings }: { onFindings: () => void }) {
  const { api, toast } = useApi();
  const searches = useLoad((a) => a.listSearches({ limit: 200 }), []);
  const sources = useLoad((a) => a.listSources({ limit: 200 }), []);
  const [prompt, setPrompt] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [interval, setIntervalMin] = useState("");
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState<Record<string, string>>({}); // search id -> job id

  const create = async (run: boolean) => {
    setSaving(true);
    try {
      const s = await api.createSearch({ prompt, source_ids: picked, interval_minutes: interval ? Number(interval) : null });
      setPrompt("");
      toast("Suchauftrag gespeichert");
      if (run) {
        const { job } = await api.runSearch(s.id);
        setRunning((r) => ({ ...r, [s.id]: job.id }));
      }
      searches.reload();
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fa-page">
      <PageHead title="Suchaufträge" sub="erstellen und verfolgen" />
      <section className="fa-card fa-form">
        <label>
          <span>Welche Teams suchst du?</span>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} placeholder="Deutsche Robotikteams mit technischem Prototyp und ersten Pilotkunden." />
        </label>
        <p className="fa-scope">
          <b>Aktueller Umfang:</b> Der Text wird als Auftragskontext gespeichert. Gesammelt wird aus den ausgewählten, konfigurierten Quellen – eine semantische Quellenauswahl
          anhand des Textes gibt es noch nicht.
        </p>
        <div className="fa-pick">
          <span className="fa-h4">Quellen</span>
          {sources.loading && <Loading />}
          {sources.error && <ErrorBox message={sources.error} onRetry={sources.reload} />}
          {sources.data?.items.length === 0 && <span className="fa-muted">Noch keine Quellen – unter „Quellen“ anlegen.</span>}
          {sources.data?.items.map((s) => (
            <label key={s.id} className={`fa-chip${picked.includes(s.id) ? " is-on" : ""}${!s.enabled ? " is-off" : ""}`}>
              <input type="checkbox" checked={picked.includes(s.id)} onChange={() => setPicked((p) => (p.includes(s.id) ? p.filter((x) => x !== s.id) : [...p, s.id]))} />
              {s.name}
              {!s.enabled && " (deaktiviert)"}
            </label>
          ))}
          <span className="fa-muted fa-small">{picked.length ? `${picked.length} ausgewählt` : "keine Auswahl = alle aktiven Quellen (Backend-Standard)"}</span>
        </div>
        <div className="fa-form__row">
          <label className="fa-inline">
            Automatisch wiederholen alle
            <input type="number" min={1} value={interval} onChange={(e) => setIntervalMin(e.target.value)} placeholder="–" aria-label="Intervall in Minuten, leer für manuell" />
            Min.
          </label>
          <div className="fa-form__actions">
            <button className="htgf-btn htgf-btn--outline" disabled={!prompt.trim() || saving} onClick={() => create(false)}>
              Nur speichern
            </button>
            <button className="htgf-btn" disabled={!prompt.trim() || saving} onClick={() => create(true)}>
              Speichern und starten
            </button>
          </div>
        </div>
      </section>
      <section className="fa-card">
        {searches.loading && !searches.data && <Loading />}
        {searches.error && <ErrorBox message={searches.error} onRetry={searches.reload} />}
        {searches.data && searches.data.items.length === 0 && <Empty title="Noch keine Suchaufträge." />}
        {searches.data && searches.data.items.length > 0 && (
          <ul className="fa-table-list">
            {searches.data.items.map((s) => (
              <SearchRow
                key={s.id}
                s={s}
                sourceName={(id) => sources.data?.items.find((x) => x.id === id)?.name ?? id}
                jobId={running[s.id] ?? null}
                onStart={(jid) => setRunning((r) => ({ ...r, [s.id]: jid }))}
                onDone={() => {
                  setRunning((r) => {
                    const n = { ...r };
                    delete n[s.id];
                    return n;
                  });
                  searches.reload();
                }}
                onFindings={onFindings}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

const STEPS = ["Sammeln", "Fundstellen verarbeiten", "Ergebnisse"];

function SearchRow(props: { s: Search; sourceName: (id: string) => string; jobId: string | null; onStart: (id: string) => void; onDone: () => void; onFindings: () => void }) {
  const { s } = props;
  const { api, toast } = useApi();
  const [children, setChildren] = useState<string[] | null>(null);
  const [childState, setChildState] = useState<Record<string, Job["status"]>>({});
  const job = useJobPolling(props.jobId, (j) => {
    if (j.status === "failed") {
      toast(`Suche fehlgeschlagen: ${j.error ?? ""}`, "error");
      props.onDone();
      return;
    }
    const ids = (j.result?.child_job_ids as string[] | undefined) ?? [];
    setChildren(ids);
    if (!ids.length) props.onDone();
  });
  // contract: after search, follow result.child_job_ids – collection done ≠ candidates done
  useEffect(() => {
    if (!children?.length) return;
    let alive = true;
    let t: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const states = await Promise.all(children.map((id) => api.getJob(id).then((j) => [id, j.status] as const).catch(() => [id, "queued"] as const)));
      if (!alive) return;
      setChildState(Object.fromEntries(states));
      if (states.every(([, st]) => st === "succeeded" || st === "failed")) {
        toast("Suche und Verarbeitung abgeschlossen");
        setChildren(null);
        props.onDone();
        return;
      }
      t = setTimeout(tick, 1500);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [children, api]);

  const active = !!props.jobId;
  const doneChildren = Object.values(childState).filter((x) => x === "succeeded" || x === "failed").length;
  const step = !active ? (s.last_job_id ? 3 : -1) : !children ? 0 : 1;
  const findings = s.finding_ids ?? [];
  return (
    <li className="fa-search-row">
      <div className="fa-search-row__q">
        <p>„{s.prompt}“</p>
        <span className="fa-meta">
          Quellen: {s.source_ids.length ? s.source_ids.map(props.sourceName).join(", ") : "alle aktiven"} · {s.interval_minutes ? `alle ${s.interval_minutes} Min.` : "manuell"} · erstellt {fmtDate(s.created_at)}
          {s.next_run_at && ` · nächster Lauf ${fmtTime(s.next_run_at)}`}
        </span>
      </div>
      {(active || s.last_job_id) && (
        <ol className="fa-steps" aria-label="Fortschritt">
          {STEPS.map((st, i) => (
            <li key={st} className={i < step || step === 3 ? "is-done" : i === step ? "is-now" : ""}>
              {st}
              {i === 0 && job && active && !children && <> · <JobBadge s={job.status} /></>}
              {i === 1 && children && <> · {doneChildren}/{children.length}</>}
            </li>
          ))}
        </ol>
      )}
      <div className="fa-search-row__out">
        {!active && s.last_job_id && (
          <>
            <span>{findings.length} Fundstellen gesammelt.</span>
            {findings.length > 0 && (
              <button className="fa-link" onClick={props.onFindings}>
                Fundstellen ansehen
              </button>
            )}
          </>
        )}
        {!active && !s.last_job_id && <span className="fa-muted">Noch nicht gestartet.</span>}
        {!active && (
          <button
            className="htgf-btn htgf-btn--outline htgf-btn--small"
            onClick={async () => {
              try {
                const { job: j } = await api.runSearch(s.id);
                props.onStart(j.id);
                toast("Suche gestartet");
              } catch (e) {
                toast(errMsg(e), "error");
              }
            }}
          >
            {s.last_job_id ? "Erneut ausführen" : "Starten"}
          </button>
        )}
      </div>
    </li>
  );
}

/* ===================== 5 · Quellen und Fundstellen ===================== */
export function Sources() {
  const { api, toast } = useApi();
  const sources = useLoad((a) => a.listSources({ limit: 200 }), []);
  const [srcFilter, setSrcFilter] = useState("");
  const [fq, setFq] = useState("");
  const findings = useLoad((a) => a.listFindings({ source_id: srcFilter || undefined, q: fq || undefined, limit: 100 }), [srcFilter, fq]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("html");
  const [url, setUrl] = useState("");
  const [f, setF] = useState({ source_id: "", url: "", title: "", text: "" });
  const [jobs, setJobs] = useState<Record<string, string>>({});
  const [openFinding, setOpenFinding] = useState<string | null>(null);

  return (
    <div className="fa-page">
      <PageHead title="Quellen" sub="und Fundstellen" />
      <div className="fa-grid2">
        <section className="fa-card">
          <h3 className="fa-h3">Quellen</h3>
          {sources.loading && !sources.data && <Loading />}
          {sources.error && <ErrorBox message={sources.error} onRetry={sources.reload} />}
          {sources.data && sources.data.items.length === 0 && <Empty title="Keine Quellen konfiguriert." />}
          {sources.data && sources.data.items.length > 0 && (
            <table className="fa-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Art</th>
                  <th>Aktiv</th>
                </tr>
              </thead>
              <tbody>
                {sources.data.items.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <button className="fa-link" onClick={() => setSrcFilter(srcFilter === s.id ? "" : s.id)} aria-pressed={srcFilter === s.id}>
                        {s.name}
                      </button>{" "}
                      <Demo show={s.is_demo} />
                      <span className="fa-meta fa-block">{s.url}</span>
                    </td>
                    <td>{s.kind}</td>
                    <td>
                      <label className="fa-toggle">
                        <input
                          type="checkbox"
                          checked={s.enabled}
                          onChange={async (e) => {
                            try {
                              await api.patchSource(s.id, { enabled: e.target.checked });
                              toast(e.target.checked ? "Quelle aktiviert" : "Quelle deaktiviert");
                              sources.reload();
                            } catch (err) {
                              toast(errMsg(err), "error");
                            }
                          }}
                        />
                        <span />
                      </label>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <form
            className="fa-inline-form"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api.createSource({ name, url, kind });
                setName("");
                setUrl("");
                toast("Quelle gespeichert");
                sources.reload();
              } catch (err) {
                toast(errMsg(err), "error");
              }
            }}
          >
            <p className="fa-h4">Quelle hinzufügen</p>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" aria-label="Name der Quelle" required />
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Art">
              <option value="html">HTML-Seite</option>
              <option value="rss">RSS-Feed</option>
              <option value="manual">Manuell</option>
            </select>
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" aria-label="URL" required type="url" />
            <button className="htgf-btn htgf-btn--small" disabled={!name.trim() || !url.trim()}>
              Speichern
            </button>
          </form>
        </section>

        <section className="fa-card">
          <h3 className="fa-h3">
            Fundstellen
            {srcFilter && (
              <span className="fa-meta">
                gefiltert ·{" "}
                <button className="fa-link" onClick={() => setSrcFilter("")}>
                  alle zeigen
                </button>
              </span>
            )}
          </h3>
          <input className="fa-search-sm" value={fq} onChange={(e) => setFq(e.target.value)} placeholder="Fundstellen durchsuchen" aria-label="Fundstellen durchsuchen" />
          {findings.loading && !findings.data && <Loading />}
          {findings.error && <ErrorBox message={findings.error} onRetry={findings.reload} />}
          {findings.data && findings.data.items.length === 0 && <Empty title="Keine Fundstellen." />}
          {findings.data && findings.data.items.length > 0 && (
            <ul className="fa-table-list">
              {findings.data.items.map((fd) => (
                <FindingRow
                  key={fd.id}
                  id={fd.id}
                  title={fd.title ?? fd.url ?? fd.id}
                  text={fd.text}
                  url={fd.url}
                  status={fd.status}
                  isDemo={fd.is_demo}
                  fetchedAt={fd.fetched_at}
                  open={openFinding === fd.id}
                  onToggle={() => setOpenFinding(openFinding === fd.id ? null : fd.id)}
                  jobId={jobs[fd.id] ?? null}
                  onStart={(jid) => setJobs((j) => ({ ...j, [fd.id]: jid }))}
                  onDone={() => {
                    setJobs((j) => {
                      const n = { ...j };
                      delete n[fd.id];
                      return n;
                    });
                    findings.reload();
                  }}
                />
              ))}
            </ul>
          )}
          <form
            className="fa-inline-form"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api.createFinding(f);
                setF({ ...f, url: "", title: "", text: "" });
                toast("Fundstelle importiert");
                findings.reload();
              } catch (err) {
                toast(errMsg(err), "error");
              }
            }}
          >
            <p className="fa-h4">Fundstelle importieren</p>
            <select value={f.source_id} onChange={(e) => setF({ ...f, source_id: e.target.value })} aria-label="Quelle" required>
              <option value="">Quelle wählen</option>
              {sources.data?.items.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Titel" aria-label="Titel" required />
            <input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://…" aria-label="URL der Fundstelle" type="url" required />
            <textarea value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} rows={3} placeholder="Originaltext" aria-label="Originaltext" required />
            <button className="htgf-btn htgf-btn--small" disabled={!f.source_id || !f.title.trim() || !f.url.trim() || !f.text.trim()}>
              Importieren
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}

function FindingRow(props: {
  id: string;
  title: string;
  text: string | null;
  url: string | null;
  status: string;
  isDemo?: boolean;
  fetchedAt?: string | null;
  open: boolean;
  onToggle: () => void;
  jobId: string | null;
  onStart: (jobId: string) => void;
  onDone: () => void;
}) {
  const { api, toast } = useApi();
  const job = useJobPolling(props.jobId, (j) => {
    toast(j.status === "succeeded" ? "Fundstelle verarbeitet" : `Verarbeitung fehlgeschlagen: ${j.error ?? ""}`, j.status === "succeeded" ? "ok" : "error");
    props.onDone();
  });
  return (
    <li className="fa-finding">
      <div className="fa-finding__main">
        <button className="fa-finding__title" onClick={props.onToggle} aria-expanded={props.open}>
          {props.title}
        </button>{" "}
        <Demo show={props.isDemo} />
        <p className="fa-meta">
          {FINDING_STATUS[props.status] ?? props.status} · abgerufen {fmtDate(props.fetchedAt)}
          {props.url && (
            <>
              {" "}
              ·{" "}
              <a href={props.url} target="_blank" rel="noreferrer">
                Original ↗
              </a>
            </>
          )}
        </p>
        {props.open && <pre className="fa-text">{props.text ?? "Kein Originaltext."}</pre>}
      </div>
      {props.jobId ? (
        <span className="fa-running">
          <span className="fa-spinner" aria-hidden="true" /> {job ? <JobBadge s={job.status} /> : "startet"}
        </span>
      ) : (
        <button
          className="htgf-btn htgf-btn--outline htgf-btn--small"
          onClick={async () => {
            try {
              const { job: j } = await api.processFinding(props.id);
              props.onStart(j.id);
            } catch (e) {
              toast(errMsg(e), "error");
            }
          }}
        >
          {props.status === "processed" ? "Erneut verarbeiten" : "Verarbeiten"}
        </button>
      )}
    </li>
  );
}

/* ===================== 6 · Pipeline ===================== */
export function Pipeline() {
  const { api, toast } = useApi();
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const { data, error, loading, reload } = useLoad((a) => a.listJobs({ status: status || undefined, kind: kind || undefined, limit: 200 }), [status, kind]);
  const active = data?.items.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(reload, 2000);
    return () => clearInterval(t);
  }, [active, reload]);
  return (
    <div className="fa-page">
      <PageHead title="Pipeline" sub="Jobs und Verarbeitung">
        <button className="htgf-btn htgf-btn--outline htgf-btn--small" onClick={reload}>
          Aktualisieren
        </button>
      </PageHead>
      <section className="fa-card">
        <div className="fa-filters">
          {[
            ["", "Alle"],
            ["queued", "Wartet"],
            ["running", "Läuft"],
            ["failed", "Fehler"],
            ["succeeded", "Fertig"],
          ].map(([v, l]) => (
            <button key={v} className={`fa-chip${status === v ? " is-on" : ""}`} onClick={() => setStatus(v)}>
              {l}
            </button>
          ))}
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Art" className={kind ? "is-set" : ""}>
            <option value="">Jede Art</option>
            {Object.entries(JOB_KIND).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          {active && <span className="fa-meta">aktualisiert automatisch</span>}
        </div>
        {loading && !data && <Loading />}
        {error && <ErrorBox message={error} onRetry={reload} />}
        {data && data.items.length === 0 && <Empty title="Keine Jobs." />}
        {data && data.items.length > 0 && (
          <table className="fa-table">
            <thead>
              <tr>
                <th>Art</th>
                <th>Status</th>
                <th>Versuche</th>
                <th>Bezug</th>
                <th>Aktualisiert</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((j) => (
                <tr key={j.id}>
                  <td>
                    <b>{JOB_KIND[j.kind] ?? j.kind}</b>
                  </td>
                  <td>
                    <JobBadge s={j.status} />
                    {j.error && <span className="fa-err">{j.error}</span>}
                  </td>
                  <td>
                    {j.attempts} / {j.max_attempts}
                  </td>
                  <td className="fa-meta">{String(j.payload.id ?? "–")}</td>
                  <td>{fmtTime(j.updated_at)}</td>
                  <td>
                    {j.status === "failed" && (
                      <button
                        className="htgf-btn htgf-btn--outline htgf-btn--small"
                        onClick={async () => {
                          try {
                            await api.retryJob(j.id);
                            toast("Job wird wiederholt");
                            reload();
                          } catch (e) {
                            toast(errMsg(e), "error");
                          }
                        }}
                      >
                        Wiederholen
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="fa-muted fa-small fa-mt">Fehlgeschlagene Jobs können vom Backend verzögert automatisch erneut eingereiht werden.</p>
      </section>
    </div>
  );
}

/* ===================== 7 · Systemstatus ===================== */
export function SystemStatus() {
  const { api, config, setConfig, toast } = useApi();
  const health = useLoad((a) => a.health(), []);
  const caps = useLoad((a) => a.capabilities(), []);
  const events = useLoad((a) => a.events({ limit: 20 }), []);
  const [mode, setMode] = useState(config.mode);
  const [url, setUrl] = useState(config.baseUrl);
  const [token, setToken] = useState(config.token);
  const [seeding, setSeeding] = useState(false);
  const h = health.data;
  const c = caps.data;
  return (
    <div className="fa-page">
      <PageHead title="Systemstatus" sub="Betriebsmodus und Dienste" />
      <div className="fa-grid2">
        <section className="fa-card">
          <h3 className="fa-h3">Verbindung</h3>
          {health.error && <ErrorBox message={health.error} onRetry={health.reload} />}
          <dl className="fa-dl">
            <div>
              <dt>Datenquelle</dt>
              <dd>{api.kind === "mock" ? "Mock-API im Browser (synthetisch)" : api.baseUrl}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{health.loading ? "prüft …" : h ? <b>{h.status}</b> : "–"}</dd>
            </div>
            <div>
              <dt>Modus</dt>
              <dd>{h?.mode ?? c?.mode ?? "–"}</dd>
            </div>
            <div>
              <dt>Datenbank</dt>
              <dd>{h?.database ?? "–"}</dd>
            </div>
            <div>
              <dt>Worker</dt>
              <dd>{h?.worker?.last_seen_at ? `zuletzt gesehen ${fmtTime(h.worker.last_seen_at)}` : <Unknown>keine Angabe</Unknown>}</dd>
            </div>
            <div>
              <dt>Graph / Modell</dt>
              <dd>
                {h?.graph_status ?? "–"} / {h?.model_status ?? "–"}
              </dd>
            </div>
          </dl>
          <form
            className="fa-inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              setConfig({ mode, baseUrl: url, token });
              toast("Verbindung gespeichert");
            }}
          >
            <p className="fa-h4">API-Verbindung</p>
            <select value={mode} onChange={(e) => setMode(e.target.value as "mock" | "http")} aria-label="Modus">
              <option value="http">Backend (HTTP)</option>
              <option value="mock">Mock im Browser</option>
            </select>
            <input value={url} onChange={(e) => setUrl(e.target.value)} disabled={mode === "mock"} aria-label="Backend-URL" placeholder="http://localhost:8000" />
            <input value={token} onChange={(e) => setToken(e.target.value)} disabled={mode === "mock"} aria-label="API-Token" placeholder="API-Token (nur Live-Modus)" type="password" autoComplete="off" />
            <button className="htgf-btn htgf-btn--small">Übernehmen</button>
          </form>
          <p className="fa-muted fa-small">Das API-Token ist der Team-Zugang zum Backend und bleibt in diesem Browser. Modellschlüssel liegen ausschließlich im Worker.</p>
        </section>
        <section className="fa-card">
          <h3 className="fa-h3">Fähigkeiten</h3>
          {caps.loading && <Loading />}
          {caps.error && <ErrorBox message={caps.error} onRetry={caps.reload} />}
          {c && (
            <dl className="fa-dl">
              <div>
                <dt>Synthetisch</dt>
                <dd>{c.synthetic ? "ja – alle Ergebnisse sind Demodaten" : "nein"}</dd>
              </div>
              <div>
                <dt>Graph</dt>
                <dd>{c.graph_provider ?? "–"}</dd>
              </div>
              <div>
                <dt>Live-Recherche</dt>
                <dd>{c.live_research ? "aktiv" : "aus"}</dd>
              </div>
              <div>
                <dt>Adapter</dt>
                <dd>{c.adapters?.join(", ") ?? "–"}</dd>
              </div>
              <div>
                <dt>Funktionen</dt>
                <dd>{c.features?.join(", ") ?? "–"}</dd>
              </div>
              {c.deployment_note && (
                <div>
                  <dt>Hinweis</dt>
                  <dd>{c.deployment_note}</dd>
                </div>
              )}
            </dl>
          )}
          {(c?.mode === "demo" || c?.mode === "mock") && (
            <div className="fa-inline-form">
              <p className="fa-h4">Demodaten</p>
              <p className="fa-muted fa-small">POST /demo/seed legt synthetische Fundstellen und Jobs an.</p>
              <button
                className="htgf-btn htgf-btn--outline htgf-btn--small"
                disabled={seeding}
                onClick={async () => {
                  if (!window.confirm("Synthetische Demodaten anlegen?")) return;
                  setSeeding(true);
                  try {
                    await api.seedDemo();
                    toast("Demodaten angelegt");
                    events.reload();
                  } catch (e) {
                    toast(errMsg(e), "error");
                  } finally {
                    setSeeding(false);
                  }
                }}
              >
                {seeding ? "Läuft …" : "Demodaten anlegen"}
              </button>
            </div>
          )}
          <h3 className="fa-h3 fa-mt">Ereignisse</h3>
          {events.error && <ErrorBox message={events.error} onRetry={events.reload} />}
          {events.data && events.data.items.length === 0 && <p className="fa-muted">Keine Ereignisse.</p>}
          <ul className="fa-events">
            {events.data?.items.map((e) => (
              <li key={e.id}>
                <span className="fa-meta">{fmtTime(e.created_at)}</span> <b>{e.action}</b>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
