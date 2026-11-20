"use client";

/* eslint-disable @next/next/no-img-element */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiProvider, useLoad } from "./hooks";
import { PotentialMap } from "./PotentialMap";
import { Shortlist } from "./views";

type View = "entdecken" | "shortlist";
const NAV: { id: View; label: string }[] = [
  { id: "entdecken", label: "Entdecken" },
  { id: "shortlist", label: "Shortlist" },
];

/** Hash routes: #/entdecken, #/entdecken/<candidateId>, #/shortlist. */
function parseHash(): { view: View; id: string | null } {
  const [, v, id] = window.location.hash.replace(/^#/, "").split("/");
  return { view: NAV.find((n) => n.id === v)?.id ?? "entdecken", id: id ? decodeURIComponent(id) : null };
}

/** Product data remains hidden unless the API explicitly confirms production mode. */
function ProductionGate({ children }: { children: ReactNode }) {
  const { data, error } = useLoad((a) => a.capabilities(), []);
  if (error)
    return (
      <div className="fa-banner fa-banner--warn" role="alert">
        <b>Produktivbackend nicht verfügbar.</b> {error}
      </div>
    );
  if (!data)
    return (
      <div className="fa-banner" role="status">
        Produktivstatus der API wird geprüft …
      </div>
    );
  if (data.mode !== "live")
    return (
      <div className="fa-banner fa-banner--warn" role="alert">
        <b>Produktivzugriff gesperrt.</b> Die API bestätigt keinen Livebetrieb. Kandidatenprofile werden nicht angezeigt.
      </div>
    );
  return <>{children}</>;
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
    const hash = `#/${view}${id ? `/${encodeURIComponent(id)}` : ""}`;
    if (window.location.hash !== hash) window.location.hash = hash;
    setRoute({ view, id });
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
      <main className="fa-main">
        <ProductionGate>
          {route.view === "entdecken" && <PotentialMap selectedId={route.id} onSelect={(id) => go("entdecken", id)} />}
          {route.view === "shortlist" && <Shortlist onOpen={(id) => go("entdecken", id)} />}
        </ProductionGate>
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
