"use client";

import { useEffect, type CSSProperties } from "react";
import { useApi, useLoad } from "./hooks";
import type { Candidate, Finding } from "./types";
import { ErrorBox, Loading, fmtTime } from "./ui";
import { useLanguage, type TranslationKey } from "./i18n";

interface DashboardData {
  candidates: { items: Candidate[]; total: number };
  shortlist: number;
  sources: number;
  activeJobs: number;
}

async function loadDashboard(api: ReturnType<typeof useApi>["api"]): Promise<DashboardData> {
  const [candidates, shortlist, sources, running, queued] = await Promise.all([
    api.listCandidates({ limit: 200 }),
    api.listCandidates({ status: "shortlisted", limit: 1 }),
    api.listSources({ limit: 1 }),
    api.listJobs({ status: "running", limit: 1 }),
    api.listJobs({ status: "queued", limit: 1 }),
  ]);
  return {
    candidates,
    shortlist: shortlist.total,
    sources: sources.total,
    activeJobs: running.total + queued.total,
  };
}

const place = (candidate: Candidate) => candidate.location?.split(";")[0]?.trim() || candidate.entity_type?.replaceAll("_", " ") || "";

/** Findings often carry only a URL as title. Turn it into "domain · readable path". */
function findingLabel(finding: Finding) {
  const raw = finding.title && !/^https?:\/\//.test(finding.title) ? finding.title : null;
  try {
    const url = new URL(finding.url || finding.title || "");
    const host = url.hostname.replace(/^www\./, "");
    const slug = url.pathname.split("/").filter(Boolean).filter((part) => !/^(de|en|news|articles?|blog)$/i.test(part)).pop() ?? "";
    const words = decodeURIComponent(slug).replace(/\.[a-z]+$/i, "").replace(/[-_]+/g, " ").trim();
    return { host, text: raw ?? (words ? words.charAt(0).toUpperCase() + words.slice(1) : host) };
  } catch {
    return { host: (finding.source ?? "").replace(/^research:/, ""), text: raw ?? finding.title ?? "" };
  }
}

function ago(iso: string | null | undefined, locale: string) {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - Date.parse(iso)) / 60000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (minutes < 60) return rtf.format(-Math.max(minutes, 1), "minute");
  if (minutes < 60 * 48) return rtf.format(-Math.round(minutes / 60), "hour");
  return rtf.format(-Math.round(minutes / 1440), "day");
}

function LiveTicker({ locale }: { locale: string }) {
  const { t } = useLanguage();
  const { data } = useLoad((api) => api.listFindings({ limit: 24 }), []);
  const items = (data?.items ?? []).map((finding) => ({ id: finding.id, ...findingLabel(finding), when: ago(finding.fetched_at ?? finding.published_at, locale) })).filter((item) => item.text && item.text !== item.host && item.text.trim().length >= 12 && !/\d{6,}/.test(item.text) && !/[a-z0-9]{20,}/i.test(item.text) && !/(linkedin|facebook|instagram|twitter|x\.com|xing|youtube|tiktok)\./i.test(item.host) && !/^(impressum|imprint|privacy|datenschutz|kontakt|contact|about|legal|home|index)$/i.test(item.text.trim()));
  const seen = new Set<string>();
  const unique = items.filter((item) => { const key = item.text.toLowerCase(); if (seen.has(key)) return false; seen.add(key); return true; });
  if (!unique.length) return null;
  const loop = [...unique, ...unique];
  return <section className="hm-ticker" aria-label={t("homeLiveLabel")}>
    <span className="hm-ticker__label"><i aria-hidden="true" />{t("homeLiveLabel")}</span>
    <div className="hm-ticker__viewport">
      <ul className="hm-ticker__track" style={{ animationDuration: `${Math.max(unique.length * 6, 40)}s` }}>
        {loop.map((item, index) => <li key={`${item.id}-${index}`} aria-hidden={index >= unique.length}><b>{item.host}</b><span>{item.text}</span><small>{item.when}</small></li>)}
      </ul>
    </div>
  </section>;
}

const CRITERIA_LABEL: Record<string, TranslationKey> = { founding_intent: "hxCrit1", technical_substance: "hxCrit2", customer_problem: "hxCrit3", demand: "hxCrit4" };
const RATING_LABEL: Record<string, TranslationKey> = { strong: "hxStrong", moderate: "hxModerate", weak: "hxWeak" };
const RATING_VALUE: Record<string, number> = { strong: 100, moderate: 67, weak: 33 };

function Feature({ candidate, onOpen }: { candidate: Candidate; onOpen: (id: string) => void }) {
  const { t } = useLanguage();
  const { data } = useLoad((api) => api.getCandidate(candidate.id), [candidate.id]);
  const quote = data?.evidence.find((item) => item.quote && item.quote.length > 60 && item.quote.length < 260);
  const criteria = data?.assessment?.criteria ?? candidate.assessment?.criteria ?? [];
  let source = "";
  try { source = quote?.url ? new URL(quote.url).hostname.replace(/^www\./, "") : ""; } catch { source = ""; }
  return <section className="hm-feature" aria-labelledby="hm-feature-name">
    <div className="hm-feature__glow" aria-hidden="true" />
    <div className="hm-feature__top">
      <p className="hm-kicker">{t("homeFeatureLabel")}</p>
      <span className="hm-feature__place">{place(candidate)}</span>
    </div>
    <div className="hm-feature__main">
      <h2 id="hm-feature-name">{candidate.name}</h2>
      <strong className="hm-feature__score">{candidate.assessment?.score}<small>/100</small></strong>
    </div>
    <div className="hm-feature__body">
      {quote ? <figure className="hm-feature__quote">
        <p className="hm-kicker">{t("homeFeatureEvidence")}</p>
        <blockquote>“{quote.quote.trim()}”</blockquote>
        {source && <figcaption>{source}</figcaption>}
      </figure> : <p className="hm-feature__desc">{candidate.description}</p>}
      <ul className="hm-feature__criteria">
        {criteria.map((criterion) => <li key={criterion.key} style={{ "--v": RATING_VALUE[criterion.rating] ?? 0 } as CSSProperties}>
          <span>{CRITERIA_LABEL[criterion.key] ? t(CRITERIA_LABEL[criterion.key]) : criterion.label}</span>
          <i><u /></i>
          <b>{RATING_LABEL[criterion.rating] ? t(RATING_LABEL[criterion.rating]) : t("hxOpen")}</b>
        </li>)}
      </ul>
    </div>
    <button className="hm-btn hm-btn--fill hm-feature__cta" onClick={() => onOpen(candidate.id)}>{t("homeFeatureCta")}</button>
  </section>;
}

function Teaser() {
  const { t } = useLanguage();
  const steps: TranslationKey[] = ["hiwS1T", "hiwS2T", "hiwS3T", "hiwS4T"];
  return <section className="hm-teaser" aria-labelledby="hm-teaser-title">
    <div className="hm-teaser__glow" aria-hidden="true" />
    <p className="hm-kicker">{t("howItWorks")}</p>
    <h2 id="hm-teaser-title">{t("pipelineTitleA")}<br /><em>{t("pipelineTitleB")}</em></h2>
    <ol>{steps.map((step, index) => <li key={step}><span>{String(index + 1).padStart(2, "0")}</span>{t(step)}</li>)}</ol>
    <a className="hm-teaser__cta" href="#/pipeline">{t("homeTeaserCta")} →</a>
  </section>;
}

export function HomeDashboard({ onDiscover, onShortlist, onOpen }: { onDiscover: () => void; onShortlist: () => void; onOpen: (id: string) => void }) {
  const { language, t } = useLanguage();
  const { data, error, loading, reload } = useLoad((client) => loadDashboard(client), []);
  const locale = language === "de" ? "de-DE" : "en-US";

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const candidates = data?.candidates.items ?? [];
  const ranked = candidates
    .filter((candidate) => candidate.assessment_rankable && typeof candidate.assessment?.score === "number")
    .sort((a, b) => (b.assessment?.score ?? 0) - (a.assessment?.score ?? 0))
    .slice(0, 5);
  const [lead, ...rest] = ranked;
  const latest = candidates.reduce<Candidate | null>((current, candidate) => !current || candidate.updated_at > current.updated_at ? candidate : current, null);

  return <div className="hm" aria-labelledby="home-title">
    <header className="hm-hero">
      <div className="hm-hero__glow" aria-hidden="true" />
      <p className="hm-kicker">{t("homeEyebrow")}</p>
      <h1 id="home-title">{t("homeTitle")}</h1>
      <p className="hm-lead">{t("homeLead")}</p>
      <div className="hm-actions">
        <button className="hm-btn hm-btn--fill" onClick={onDiscover}>{t("homeDiscoverAction")}</button>
        <button className="hm-btn" onClick={onShortlist}>{t("homeShortlistAction")}</button>
      </div>
    </header>

    <LiveTicker locale={locale} />

    {error && <ErrorBox message={error} onRetry={reload} />}
    {loading && !data && <div className="hm-loading"><Loading label={t("homeLoading")} /></div>}

    {data && <>

      <section className="hm-ranked" aria-labelledby="home-ranked-title">
        <header className="hm-head">
          <p className="hm-kicker">{t("homeSignal")}</p>
          <h2 id="home-ranked-title">{t("homeRankedTitle")}</h2>
        </header>

        {!lead && <div className="hm-empty"><p>{t("homeNoRanked")}</p><button className="hm-btn" onClick={onDiscover}>{t("homeExplore")}</button></div>}

        {lead && <Feature candidate={lead} onOpen={onOpen} />}

        {rest.length > 0 && <div className="hm-grid">
          {rest.map((candidate, index) => <button className="hm-card" key={candidate.id} onClick={() => onOpen(candidate.id)}>
            <span className="hm-card__n">{String(index + 2).padStart(2, "0")}</span>
            <span className="hm-card__score">{candidate.assessment?.score}<small>/100</small></span>
            <span className="hm-card__name">{candidate.name}</span>
            <span className="hm-card__place">{place(candidate)}</span>
          </button>)}
        </div>}

        <footer className="hm-foot">
          <span className={`hm-status${data.activeJobs > 0 ? " is-busy" : ""}`}>{data.activeJobs > 0 ? t("homePipelineBusy", { count: data.activeJobs }) : t("homePipelineIdle")}</span>
          <span>{t("insSources", { count: data.sources.toLocaleString(locale) })}</span>
          {latest && <span>{t("homeUpdated", { date: fmtTime(latest.updated_at, language) })}</span>}
          <button className="hm-link" onClick={onDiscover}>{t("homeAllCandidates")} →</button>
        </footer>
      </section>

      <Teaser />
    </>}
  </div>;
}
