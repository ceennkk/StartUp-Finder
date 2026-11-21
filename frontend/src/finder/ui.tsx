"use client";

import type { ReactNode } from "react";
import type {
  Assessment,
  CandidateStatus,
  GermanyStatus,
  JobStatus,
  Priority,
} from "./types";
import { useLanguage } from "./i18n";

export const PRIORITY_LABEL: Record<Priority, string> = {
  high: "Hoch",
  medium: "Mittel",
  low: "Niedrig",
  insufficient_data: "Zu wenig Daten",
};
export const GERMANY_LABEL: Record<GermanyStatus, string> = {
  confirmed: "Deutschland bestätigt",
  likely: "Deutschland wahrscheinlich",
  unknown: "Standort unklar",
  outside_germany: "Außerhalb Deutschlands",
};
export const STATUS_LABEL: Record<CandidateStatus, string> = {
  new: "Neu",
  shortlisted: "Gemerkt",
  rejected: "Verworfen",
};
export const JOB_LABEL: Record<JobStatus, string> = {
  queued: "Wartet",
  running: "Läuft",
  succeeded: "Fertig",
  failed: "Fehler",
};
export const JOB_KIND: Record<string, string> = {
  process: "Fundstelle verarbeiten",
  research: "Recherche",
  evaluate: "Bewertung",
  search: "Suchauftrag",
};
export const RATING_LABEL: Record<string, string> = {
  strong: "stark",
  moderate: "mittel",
  weak: "schwach",
  unknown: "unbekannt",
};

export const fmtDate = (iso?: string | null, language: "en" | "de" = "en") =>
  iso
    ? new Date(iso).toLocaleDateString(language === "de" ? "de-DE" : "en-US", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "–";
export const fmtTime = (iso?: string | null, language: "en" | "de" = "en") =>
  iso
    ? new Date(iso).toLocaleString(language === "de" ? "de-DE" : "en-US", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "–";

export function Loading({ label = "" }: { label?: string }) {
  const { t } = useLanguage();
  return (
    <div className="fa-state" role="status" aria-live="polite">
      <span className="fa-spinner" aria-hidden="true" />
      {label || t("loading")}
    </div>
  );
}

export function ErrorBox({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  const { language, t } = useLanguage();
  const knownMessages: Record<string, Parameters<typeof t>[0]> = {
    "Not authorized — the API token is missing or invalid.": "authMissing",
    "Not found.": "notFound",
    "Request is too large.": "tooLarge",
    "Invalid input.": "invalidInput",
    "Internal backend error.": "internalError",
  };
  const backendFailure = message.match(/^Backend not reachable \((.+)\)\./);
  const displayMessage = language === "de"
    ? backendFailure ? t("backendNotReachable", { base: backendFailure[1] }) : knownMessages[message] ? t(knownMessages[message]) : message
    : message;
  return (
    <div className="fa-state fa-state--error" role="alert">
      <b>{t("errorTitle")}</b> {displayMessage}
      {onRetry && (
        <button className="fa-link" onClick={onRetry}>
          {t("tryAgain")}
        </button>
      )}
    </div>
  );
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="fa-empty">
      <p className="fa-empty__title">{title}</p>
      {children}
    </div>
  );
}

export function Unknown({ children = "Unbekannt" }: { children?: ReactNode }) {
  return <span className="fa-unknown">{children}</span>;
}

export function PriorityPill({ p }: { p?: Priority | null }) {
  const v = p ?? "insufficient_data";
  return (
    <span className={`fa-prio fa-prio--${v}`}>
      {v === "insufficient_data"
        ? "Keine Bewertung"
        : `Priorität ${PRIORITY_LABEL[v].toLowerCase()}`}
    </span>
  );
}

export function RankDisplay({ assessment, current }: { assessment?: Assessment | null; current?: boolean }) {
  const { t } = useLanguage();
  if (!assessment) return <span className="fa-rank fa-rank--empty">{t("notAssessed")}</span>;
  if (!current) return <span className="fa-rank fa-rank--empty">{t("reassess")}</span>;
  if (assessment.score == null) return <span className="fa-rank fa-rank--empty">{t("insufficientEvidence", { count: assessment.scored_criteria ?? 0 })}</span>;
  return <span className={`fa-rank fa-rank--${assessment.priority}`}>
    <b>{assessment.score}</b><span>/100</span><small>{t(`priority${assessment.priority[0].toUpperCase()}${assessment.priority.slice(1)}` as "priorityHigh" | "priorityMedium" | "priorityLow" | "priorityInsufficient")} · {t("criteriaCovered", { count: assessment.scored_criteria ?? 0 })}</small>
  </span>;
}

export function JobBadge({ s }: { s: JobStatus }) {
  return <span className={`fa-job fa-job--${s}`}>{JOB_LABEL[s]}</span>;
}

export function PageHead({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: string;
  children?: ReactNode;
}) {
  return (
    <header className="fa-head">
      <h1>
        {title}
        {sub && (
          <>
            {" "}
            <br />
            <em>{sub}</em>
          </>
        )}
      </h1>
      {children && <div className="fa-head__actions">{children}</div>}
    </header>
  );
}
