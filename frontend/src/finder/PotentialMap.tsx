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

function teamPriority(candidate: Candidate, teamPickId: string | undefined) {
  if (candidate.id === teamPickId) return 100;
  const evidenceScore = rank(candidate);
  return evidenceScore === null ? null : Math.round(evidenceScore * 0.75);
}

type PackedBubble = { candidate: Candidate; x: number; y: number; radius: number; index: number };

function packCandidates(candidates: Candidate[], teamPickId: string | undefined) {
  const width = 1000;
  let height = Math.max(700, Math.ceil(candidates.length / 4) * 115);
  const items = candidates.map((candidate, index) => ({ candidate, index, score: teamPriority(candidate, teamPickId) }))
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || a.index - b.index);
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  for (let expansion = 0; expansion < 7; expansion++, height = Math.ceil(height * 1.18)) {
    const placed: PackedBubble[] = [];
    let failed = false;
    for (const item of items) {
      const baseRadius = item.score === null ? 43 : 43 + item.score * 0.32;
      let position: { x: number; y: number; radius: number } | null = null;
      for (let shrink = 0; shrink < 5 && !position; shrink++) {
        const radius = baseRadius * (1 - shrink * 0.07);
        for (let step = 0; step < 9000; step++) {
          const distance = 8.2 * Math.sqrt(step);
          const angle = step * goldenAngle + item.index * 0.173;
          const x = width / 2 + Math.cos(angle) * distance;
          const y = height / 2 + Math.sin(angle) * distance;
          if (x - radius < 8 || x + radius > width - 8 || y - radius < 8 || y + radius > height - 8) continue;
          if (placed.some((circle) => Math.hypot(x - circle.x, y - circle.y) < radius + circle.radius + 9)) continue;
          position = { x, y, radius };
          break;
        }
      }
      if (!position) { failed = true; break; }
      placed.push({ candidate: item.candidate, index: item.index, ...position });
    }
    if (!failed) {
      const left = Math.min(...placed.map((circle) => circle.x - circle.radius));
      const right = Math.max(...placed.map((circle) => circle.x + circle.radius));
      const top = Math.min(...placed.map((circle) => circle.y - circle.radius));
      const bottom = Math.max(...placed.map((circle) => circle.y + circle.radius));
      const dx = width / 2 - (left + right) / 2;
      const cloudHeight = Math.ceil(bottom - top + 104);
      const dy = 52 - top;
      return { bubbles: placed.map((circle) => ({ ...circle, x: circle.x + dx, y: circle.y + dy })), width, height: cloudHeight };
    }
  }

  // Guaranteed non-overlapping fallback: centered, staggered rows.
  const bubbles: PackedBubble[] = [];
  let x = 0, y = 54, rowHeight = 0;
  for (const item of items) {
    const radius = Math.min(58, item.score === null ? 43 : 43 + item.score * 0.32);
    if (x + radius > width - 8) { x = 0; y += rowHeight + 12; rowHeight = 0; }
    bubbles.push({ candidate: item.candidate, index: item.index, x: x + radius, y, radius });
    x += radius * 2 + 12;
    rowHeight = Math.max(rowHeight, radius * 2);
  }
  const fallbackHeight = Math.max(height, y + rowHeight / 2 + 20);
  return { bubbles, width, height: fallbackHeight };
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

function Bubble({ candidate, selected, onSelect, label, pendingLabel, teamPick, score, x, y, diameter, width, height, index }: { candidate: Candidate; selected: boolean; onSelect: () => void; label: string; pendingLabel: string; teamPick: boolean; score: number | null; x: number; y: number; diameter: number; width: number; height: number; index: number }) {
  const [logoFailed, setLogoFailed] = useState(false);
  const favicon = candidate.website ? faviconFor(candidate.website) : null;
  const level = score === null ? "pending" : score >= 85 ? "high" : score >= 70 ? "medium" : "early";
  const monogram = initials(candidate.name);
  return (
    <button
      className={`fa-landscape__bubble fa-landscape__bubble--${level}${selected ? " is-selected" : ""}`}
      onClick={onSelect}
      style={{ left: `${x / width * 100}%`, top: `${y / height * 100}%`, width: `${diameter / width * 100}%`, "--bubble-delay": `${(index % 8) * 35}ms` } as CSSProperties & { "--bubble-delay": string }}
      aria-pressed={selected}
      aria-label={label}
    >
      <span className="fa-landscape__bubble-orb" aria-hidden="true" />
      <span className="fa-landscape__bubble-content">
        <span className="fa-landscape__bubble-mark">{favicon && !logoFailed ? <img src={favicon} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setLogoFailed(true)} /> : <b>{monogram || "?"}</b>}</span>
        <span className="fa-landscape__bubble-name">{candidate.name}</span>
        <span className="fa-landscape__bubble-score">{score === null ? "—" : score}{score !== null && <small>/100</small>}</span>
        {teamPick && <span className="fa-landscape__bubble-note">Team pick</span>}
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
    .filter((candidate) => candidate.status === "new" || candidate.status === "shortlisted" || candidate.id === selectedId)
    .filter((candidate) => !term || `${candidate.name} ${candidate.description} ${candidate.location}`.toLocaleLowerCase("de").includes(term))
    .sort((a, b) => Number(b.status === "shortlisted") - Number(a.status === "shortlisted") || (rank(b) ?? 0) - (rank(a) ?? 0) || a.name.localeCompare(b.name, "de")), [data, term]);
  const teamPickId = candidates.find((candidate) => candidate.status === "shortlisted")?.id;
  const packed = useMemo(() => packCandidates(candidates, teamPickId), [candidates, teamPickId]);
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
            <div className="fa-landscape__field-caption"><b>{t("candidates", { count: candidates.length })}</b><span>{teamPickId ? t("teamPickHint") : t("potentialHint")}</span></div>
            <div className="fa-landscape__bubbles" style={{ aspectRatio: `${packed.width} / ${packed.height}` }}>
              {packed.bubbles.map(({ candidate, x, y, radius, index }) => {
                const evidenceScore = rank(candidate);
                const score = teamPriority(candidate, teamPickId);
                const eligibilityPending = candidate.assessment?.eligibility_effect === "eligibility_unverified" || candidate.assessment?.eligibility_effect === "company_not_registered";
                const pendingLabel = candidate.assessment?.eligibility_effect === "company_not_registered"
                  ? t("eligibilityPreCompany")
                  : eligibilityPending ? t("eligibilityReviewNeeded") : t("scorePending");
                const label = score !== null ? t("bubbleLabel", { name: candidate.name, score })
                  : eligibilityPending ? t("bubbleEligibilityPending", { name: candidate.name })
                    : t("bubblePendingLabel", { name: candidate.name });
                return <Bubble key={candidate.id} candidate={candidate} selected={candidate.id === selectedId} onSelect={() => onSelect(candidate.id === selectedId ? null : candidate.id)} label={label} pendingLabel={pendingLabel} teamPick={candidate.id === teamPickId} score={evidenceScore === null && candidate.id !== teamPickId ? null : score} x={x} y={y} diameter={radius * 2} width={packed.width} height={packed.height} index={index} />;
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
