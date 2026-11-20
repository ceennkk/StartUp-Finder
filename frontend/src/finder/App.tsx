"use client";

/* eslint-disable @next/next/no-img-element */
import { useCallback, useEffect, useState } from "react";
import { ApiProvider, useApi, useLoad } from "./hooks";
import { GraphView } from "./GraphView";
import { Discover, Pipeline, Searches, Shortlist, Sources, SystemStatus } from "./views";

type View = "entdecken" | "shortlist" | "suchen" | "quellen" | "graph" | "pipeline" | "system";
const NAV: { id: View; label: string }[] = [
  { id: "entdecken", label: "Entdecken" },
  { id: "shortlist", label: "Shortlist" },
  { id: "suchen", label: "Suchaufträge" },
  { id: "quellen", label: "Quellen" },
  { id: "graph", label: "Graph" },
  { id: "pipeline", label: "Pipeline" },
  { id: "system", label: "Systemstatus" },
];

/** Hash routes: #/entdecken, #/entdecken/<candidateId>, #/pipeline … */
function parseHash(): { view: View; id: string | null } {
  const [, v, id] = window.location.hash.replace(/^#/, "").split("/");
  return { view: NAV.find((n) => n.id === v)?.id ?? "entdecken", id: id ? decodeURIComponent(id) : null };
}

/** Synthetic data is always labelled: mock mode, or backend reports synthetic / demo mode. */
function Banner() {
  const { api } = useApi();
  const { data, error } = useLoad((a) => a.capabilities(), []);
  if (api.kind === "mock")
    return (
      <div className="fa-banner" role="note">
        <b>Demodaten.</b> Mock-API im Browser – alle Einträge sind synthetisch. Backend unter Systemstatus verbinden.
      </div>
    );
  if (error)
    return (
      <div className="fa-banner fa-banner--warn" role="alert">
        <b>Keine Verbindung</b> zu {api.baseUrl}. {error}
      </div>
    );
  if (data?.synthetic || data?.mode === "demo")
    return (
      <div className="fa-banner" role="note">
        <b>Demomodus.</b> Das Backend liefert synthetische Testdaten – keine realen Teams oder Personen.
      </div>
    );
  return null;
}

function Shell() {
  const [route, setRoute] = useState<{ view: View; id: string | null }>({ view: "entdecken", id: null });
  useEffect(() => {
    const sync = () => setRoute(parseHash());
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const go = useCallback((view: View, id: string | null = null) => {
    window.location.hash = `/${view}${id ? `/${encodeURIComponent(id)}` : ""}`;
  }, []);

  return (
    <div className="fa">
      <header className="fa-bar">
        <a href="#/entdecken" className="fa-logo" aria-label="Startup Finder – Entdecken">
          <img src="/htgf/images/htgf-logo--black.svg" alt="HTGF" />
          <span>Startup Finder</span>
        </a>
        <nav className="fa-nav" aria-label="Bereiche">
          {NAV.map((n) => (
            <button key={n.id} className={route.view === n.id ? "is-on" : ""} aria-current={route.view === n.id ? "page" : undefined} onClick={() => go(n.id)}>
              {n.label}
            </button>
          ))}
        </nav>
      </header>
      <Banner />
      <main className="fa-main">
        {route.view === "entdecken" && <Discover selected={route.id} onSelect={(id) => go("entdecken", id)} />}
        {route.view === "shortlist" && <Shortlist onOpen={(id) => go("entdecken", id)} />}
        {route.view === "suchen" && <Searches onFindings={() => go("quellen")} />}
        {route.view === "quellen" && <Sources />}
        {route.view === "graph" && <GraphView onOpen={(id) => go("entdecken", id)} />}
        {route.view === "pipeline" && <Pipeline />}
        {route.view === "system" && <SystemStatus />}
      </main>
    </div>
  );
}

export function FinderApp() {
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "error" } | null>(null);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), toast.tone === "error" ? 6000 : 2600);
    return () => clearTimeout(t);
  }, [toast]);
  const onToast = useCallback((msg: string, tone: "ok" | "error" = "ok") => setToast({ msg, tone }), []);
  return (
    <ApiProvider onToast={onToast}>
      <Shell />
      {toast && (
        <div className={`fa-toast fa-toast--${toast.tone}`} role={toast.tone === "error" ? "alert" : "status"}>
          {toast.msg}
        </div>
      )}
    </ApiProvider>
  );
}
