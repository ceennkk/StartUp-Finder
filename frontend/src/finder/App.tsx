"use client";

/* eslint-disable @next/next/no-img-element */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiProvider, useLoad } from "./hooks";
import { useLanguage, type TranslationKey } from "./i18n";
import { CandidateChat } from "./CandidateChat";
import { PotentialMap } from "./PotentialMap";
import { PipelinePage } from "./PipelinePage";
import { HomeDashboard } from "./HomeDashboard";
import { Shortlist } from "./views";

type View = "home" | "entdecken" | "pipeline" | "shortlist";
const NAV: { id: View; key: TranslationKey }[] = [
  { id: "home", key: "home" },
  { id: "entdecken", key: "discover" },
  { id: "pipeline", key: "howItWorks" },
  { id: "shortlist", key: "shortlist" },
];

/** Hash routes for the three product areas. */
function parseHash(): { view: View; id: string | null } {
  const [, v, id] = window.location.hash.replace(/^#/, "").split("/");
  return { view: NAV.find((n) => n.id === v)?.id ?? "home", id: id ? decodeURIComponent(id) : null };
}

/** Product data remains hidden unless the API explicitly confirms production mode. */
function ProductionGate({ children }: { children: ReactNode }) {
  const { t } = useLanguage();
  const { data, error } = useLoad((a) => a.capabilities(), []);
  if (error)
    return (
      <div className="fa-banner fa-banner--warn" role="alert">
        <b>{t("backendUnavailable")}</b> {error}
      </div>
    );
  if (!data)
    return (
      <div className="fa-banner" role="status">
        {t("checkingBackend")}
      </div>
    );
  if (data.mode !== "live")
    return (
      <div className="fa-banner fa-banner--warn" role="alert">
        <b>{t("accessBlocked")}</b> {t("liveNotConfirmed")}
      </div>
    );
  return <>{children}</>;
}

function Shell() {
  const { language, setLanguage, t } = useLanguage();
  const [route, setRoute] = useState<{ view: View; id: string | null }>({ view: "home", id: null });
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
  const selectCandidate = useCallback((id: string | null) => go("entdecken", id), [go]);

  return (
    <div className="fa">
      <header className="fa-bar">
        <a href="#/home" className="fa-logo" aria-label={`Pre-Round Startup Finder – ${t("home")} `}>
          <img src="/htgf/images/htgf-logo--black.svg" alt="HTGF" />
          <span>Pre-Round Startup Finder</span>
        </a>
        <nav className="fa-nav" aria-label={t("navigation") }>
          {NAV.map((n) => (
            <button key={n.id} className={route.view === n.id ? "is-on" : ""} aria-current={route.view === n.id ? "page" : undefined} onClick={() => go(n.id)}>
              {t(n.key)}
            </button>
          ))}
        </nav>
        <div className="fa-language" role="group" aria-label={t("language")}>
          {(["en", "de"] as const).map((value) => <button key={value} type="button" className={language === value ? "is-on" : ""} aria-pressed={language === value} onClick={() => setLanguage(value)}>{value.toUpperCase()}</button>)}
        </div>
      </header>
      <main className="fa-main">
        <ProductionGate>
          {route.view === "home" && <HomeDashboard onDiscover={() => go("entdecken")} onShortlist={() => go("shortlist")} onOpen={(id) => go("entdecken", id)} />}
          {route.view === "entdecken" && <PotentialMap selectedId={route.id} onSelect={selectCandidate} />}
          {route.view === "pipeline" && <PipelinePage />}
          {route.view === "shortlist" && <Shortlist onOpen={(id) => go("entdecken", id)} />}
          <CandidateChat candidateId={route.view === "entdecken" ? route.id : null} />
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
