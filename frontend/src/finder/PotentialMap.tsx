"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { CandidatePanel } from "./CandidatePanel";
import { useLoad } from "./hooks";
import { useLanguage } from "./i18n";
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

function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const useful = words.filter((word) => !/^(inc\.?|ltd\.?|gmbh|ag|se|the)$/i.test(word));
  return (useful.length > 1 ? useful.slice(0, 2).map((word) => word[0]) : [(useful[0] ?? name)[0], (useful[0] ?? name)[1]]).join("").toUpperCase();
}

function faviconFor(website: string) {
  try {
    const url = new URL(website);
    if (url.protocol === "http:" || url.protocol === "https:") return new URL("/favicon.ico", url.origin).toString();
  } catch { /* show the generated monogram when no valid company website exists */ }
  return null;
}

type PackedBubble = { candidate: Candidate; x: number; y: number; radius: number; index: number };

const GAP = 22;

function packCandidates(candidates: Candidate[]): PackedBubble[] {
  const W = 1000, H = 650;
  const scores = candidates.map(rank).filter((value): value is number => value !== null);
  const min = scores.length ? Math.min(...scores) : 0;
  const max = scores.length ? Math.max(...scores) : 0;
  const shrink = Math.min(1, Math.sqrt(14 / Math.max(candidates.length, 14)));
  const circles = candidates.map((candidate, index) => {
    const score = rank(candidate);
    const fraction = score === null ? 0 : max === min ? .55 : (score - min) / (max - min);
    return { candidate, index, radius: Math.round((score === null ? 48 : 68 + fraction * 53) * shrink) };
  }).sort((a, b) => b.radius - a.radius || a.index - b.index);
  const placed: PackedBubble[] = [];

  for (const item of circles) {
    let radius = item.radius;
    let best: { x: number; y: number; cost: number } | null = null;
    while (radius >= 24 && !best) {
      const points: { x: number; y: number; cost: number }[] = [];
      if (!placed.length) points.push({ x: W / 2, y: H / 2, cost: 0 });
      for (const other of placed) {
        const distance = other.radius + radius + GAP;
        for (let step = 0; step < 72; step++) {
          const angle = (step / 72) * Math.PI * 2 + item.index * 0.137;
          const x = other.x + Math.cos(angle) * distance;
          const y = other.y + Math.sin(angle) * distance;
          if (x - radius < 8 || x + radius > W - 8 || y - radius < 8 || y + radius > H - 8) continue;
          if (placed.some((circle) => Math.hypot(x - circle.x, y - circle.y) < radius + circle.radius + GAP - 1)) continue;
          const xs = [...placed.map((circle) => circle.x), x];
          const ys = [...placed.map((circle) => circle.y), y];
          const spanX = Math.max(...xs.map((value, i) => value + (i === xs.length - 1 ? radius : placed[i].radius))) - Math.min(...xs.map((value, i) => value - (i === xs.length - 1 ? radius : placed[i].radius)));
          const spanY = Math.max(...ys.map((value, i) => value + (i === ys.length - 1 ? radius : placed[i].radius))) - Math.min(...ys.map((value, i) => value - (i === ys.length - 1 ? radius : placed[i].radius)));
          const centerBias = Math.hypot(x - W / 2, y - H / 2) * 5;
          points.push({ x, y, cost: spanX * spanY + centerBias });
        }
      }
      if (points.length) best = points.reduce((winner, point) => point.cost < winner.cost ? point : winner);
      else radius = Math.floor(radius * .92);
    }
    if (!best) best = { x: W / 2 + (item.index % 5 - 2) * 90, y: H / 2 + (Math.floor(item.index / 5) - 1) * 115, cost: 0 };
    placed.push({ candidate: item.candidate, x: best.x, y: best.y, radius, index: item.index });
  }
  if (!placed.length) return placed;
  // Centre the finished cluster in the field so it never hugs one edge.
  const left = Math.min(...placed.map((c) => c.x - c.radius)), right = Math.max(...placed.map((c) => c.x + c.radius));
  const top = Math.min(...placed.map((c) => c.y - c.radius)), bottom = Math.max(...placed.map((c) => c.y + c.radius));
  const dx = W / 2 - (left + right) / 2, dy = H / 2 - (top + bottom) / 2;
  return placed.map((c) => ({ ...c, x: c.x + dx, y: c.y + dy }));
}

function Bubble({ candidate, selected, onSelect, label, pendingLabel, x, y, diameter, index }: { candidate: Candidate; selected: boolean; onSelect: () => void; label: string; pendingLabel: string; x: number; y: number; diameter: number; index: number }) {
  const score = rank(candidate);
  const [logoFailed, setLogoFailed] = useState(false);
  const favicon = candidate.website ? faviconFor(candidate.website) : null;
  const level = score === null ? "pending" : score >= 85 ? "high" : score >= 70 ? "medium" : "early";
  const monogram = initials(candidate.name);
  return (
    <button
      className={`fa-landscape__bubble fa-landscape__bubble--${level}${selected ? " is-selected" : ""}`}
      onClick={onSelect}
      style={{ "--bubble-x": `${x / 10}%`, "--bubble-y": `${y / 6.5}%`, "--bubble-size": `${diameter / 10}%`, "--bubble-delay": `${(index % 8) * -0.24}s` } as CSSProperties & { "--bubble-x": string; "--bubble-y": string; "--bubble-size": string; "--bubble-delay": string }}
      aria-pressed={selected}
      aria-label={label}
    >
      <span className="fa-landscape__bubble-orb" aria-hidden="true" />
      <span className="fa-landscape__bubble-content">
        <span className="fa-landscape__bubble-mark">{favicon && !logoFailed ? <img src={favicon} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setLogoFailed(true)} /> : <b>{monogram || "?"}</b>}</span>
        <span className="fa-landscape__bubble-name">{candidate.name}</span>
        <span className="fa-landscape__bubble-score">{score === null ? "—" : score}{score !== null && <small>/100</small>}</span>
        {score === null && <span className="fa-landscape__bubble-note">{pendingLabel}</span>}
      </span>
    </button>
  );
}

export function PotentialMap({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string | null) => void }) {
  const { t } = useLanguage();
  const { data, error, loading, reload } = useLoad(loadAllCandidates, []);
  const [query, setQuery] = useState("");
  const term = query.trim().toLocaleLowerCase("de");
  const candidates = useMemo(() => (data?.items ?? [])
    .filter((candidate) => candidate.status === "new" || candidate.id === selectedId)
    .filter((candidate) => !term || `${candidate.name} ${candidate.description} ${candidate.location}`.toLocaleLowerCase("de").includes(term))
    .sort((a, b) => (rank(b) ?? 0) - (rank(a) ?? 0) || a.name.localeCompare(b.name, "de")), [data, term]);
  const packed = useMemo(() => packCandidates(candidates), [candidates]);
  const selected = data?.items.find((candidate) => candidate.id === selectedId);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const selectedCandidateId = selected?.id;
  useEffect(() => {
    if (!selectedCandidateId) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onSelect(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [selectedCandidateId, onSelect]);

  return (
    <div className="fa-landscape-page">
      <header className="fa-landscape__header">
        <h1>{t("discover")}</h1>
        <label className="fa-landscape__search">
          <span aria-hidden="true">⌕</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("searchCandidates")} aria-label={t("candidateSearchLabel")} />
        </label>
      </header>

      <section className={`fa-landscape${selected ? " has-selection" : ""}`} aria-label={t("discover")}>
        {loading && !data && <div className="fa-landscape__loading"><Loading label="" /></div>}
        {error && <ErrorBox message={error} onRetry={reload} />}
        {data && candidates.length === 0 && !selected && <Empty title={data.total === 0 ? t("noCandidates") : t("noMatches")} />}
        {data && (candidates.length > 0 || selected) && <>
          <div className="fa-landscape__field">
            <div className="fa-landscape__field-caption"><b>{t("candidates", { count: candidates.length })}</b><span>{t("potentialHint")}</span></div>
            <div className="fa-landscape__bubbles">
              {packed.map(({ candidate, x, y, radius, index }) => {
                const score = rank(candidate);
                const eligibilityPending = candidate.assessment?.eligibility_effect === "eligibility_unverified" || candidate.assessment?.eligibility_effect === "company_not_registered";
                const pendingLabel = candidate.assessment?.eligibility_effect === "company_not_registered"
                  ? t("eligibilityPreCompany")
                  : eligibilityPending ? t("eligibilityReviewNeeded") : t("scorePending");
                const label = score !== null ? t("bubbleLabel", { name: candidate.name, score })
                  : eligibilityPending ? t("bubbleEligibilityPending", { name: candidate.name })
                    : t("bubblePendingLabel", { name: candidate.name });
                return <Bubble key={candidate.id} candidate={candidate} selected={candidate.id === selectedId} onSelect={() => onSelect(candidate.id === selectedId ? null : candidate.id)} label={label} pendingLabel={pendingLabel} x={x} y={y} diameter={radius * 2} index={index} />;
              })}
            </div>
          </div>
        </>}
      </section>
      {selected && <div className="fa-pmap__backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onSelect(null); }}>
        <section className="fa-pmap__modal" role="dialog" aria-modal="true" aria-label={`${selected.name} – ${t("profileSources")}`}>
          <CandidatePanel key={selected.id} id={selected.id} preview={selected} onChanged={reload} onClose={() => onSelect(null)} />
        </section>
      </div>}
    </div>
  );
}
