"use client";

import type { ReactNode } from "react";
import type {
  CandidateStatus,
  GermanyStatus,
  JobStatus,
  Priority,
} from "./types";

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

export const fmtDate = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString("de-DE", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "–";
export const fmtTime = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString("de-DE", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "–";

export function Loading({ label = "Lädt …" }: { label?: string }) {
  return (
    <div className="fa-state" role="status" aria-live="polite">
      <span className="fa-spinner" aria-hidden="true" />
      {label}
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
  return (
    <div className="fa-state fa-state--error" role="alert">
      <b>Das hat nicht geklappt.</b> {message}
      {onRetry && (
        <button className="fa-link" onClick={onRetry}>
          Erneut versuchen
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

export function Demo({ show }: { show?: boolean }) {
  if (!show) return null;
  return (
    <span
      className="fa-demo"
      title="Synthetische Demodaten – keine echten Personen oder Unternehmen"
    >
      Demo
    </span>
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
