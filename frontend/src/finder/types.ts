// Types per docs/frontend-contract.md (v1), consumed from the production backend API.

export interface ListResponse<T> {
  items: T[];
  total: number;
}

export type CandidateStatus = "new" | "shortlisted" | "rejected";
export type GermanyStatus = "confirmed" | "likely" | "unknown" | "outside_germany";
export type Priority = "high" | "medium" | "low" | "insufficient_data";
export type Rating = "strong" | "moderate" | "weak" | "unknown";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type JobKind = "process" | "research" | "evaluate" | "search";
export type SourceKind = "html" | "rss" | "manual";

export interface Signal {
  id: string;
  kind: string;
  label: string;
  evidence_id: string;
  date: string | null;
  verification?: string;
}

export interface Conflict {
  field: string;
  previous: string;
  incoming: string;
  finding_id: string;
}

export interface Criterion {
  key: string; // founding_intent | technical_substance | customer_problem | demand
  label: string;
  rating: Rating;
  rationale: string;
  evidence_ids: string[];
}

export interface Assessment {
  id?: string;
  candidate_id?: string;
  priority: Priority;
  summary: string;
  strengths: string[];
  concerns: string[];
  open_questions: string[];
  evidence_ids: string[];
  criteria: Criterion[];
  score?: number | null;
  scored_criteria?: number;
  model?: string;
  profile_version?: number;
  criteria_version?: string | number;
  created_at?: string;
  profile_snapshot?: unknown;
}

export interface Candidate {
  id: string;
  graph_node_id: string;
  name: string;
  description: string;
  website: string;
  location: string;
  germany_status: GermanyStatus;
  entity_type: string;
  people: string[];
  signals: Signal[];
  open_questions: string[];
  status: CandidateStatus;
  profile_version: number;
  finding_ids: string[];
  created_at: string;
  updated_at: string;
  conflicts?: Conflict[];
  /** list + detail */
  assessment?: Assessment | null;
  assessment_stale?: boolean;
  assessment_current?: boolean;
  assessment_rankable?: boolean;
  funding_status?: "confirmed" | "not_found" | "unclear" | "not_researched" | string;
  funding_summary?: string;
  funding_evidence_ids?: string[];
  enrichment_status?: string;
  research_profile?: {
    claims?: { field: string; value: string; evidence_id?: string; finding_id?: string }[];
  };
}

export interface Evidence {
  id: string;
  candidate_id: string;
  finding_id: string;
  episode_id?: string;
  url: string | null;
  title: string | null;
  quote: string;
  kind: "exact_quote" | "source_excerpt";
  attribution?: string;
  published_at: string | null;
  fetched_at: string | null;
  created_at?: string;
}

export interface Note {
  id: string;
  candidate_id: string;
  text: string;
  created_at: string;
}

export interface ResearchRun {
  id: string;
  candidate_id: string;
  summary: string;
  sources: unknown[];
  imported_finding_ids: string[];
  fetch_errors: unknown[];
  created_at: string;
}

export interface CandidateDetail extends Candidate {
  evidence: Evidence[];
  assessment: Assessment | null;
  notes: Note[];
  research_runs: ResearchRun[];
}

export interface Job {
  id: string;
  kind: JobKind | string;
  status: JobStatus;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  attempts: number;
  max_attempts: number;
  available_at?: number | string | null;
  lease_until?: number | string | null;
  created_at: string;
  updated_at: string;
  dedupe_key?: string | null;
}

export interface Source {
  id: string;
  name: string;
  url: string;
  kind: SourceKind | string;
  allowed_hosts?: string[];
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface Finding {
  id: string;
  source_id: string | null;
  source?: string | null;
  url: string | null;
  title: string | null;
  text: string | null;
  external_id?: string | null;
  published_at?: string | null;
  fetched_at?: string | null;
  status: string;
  graph_receipt?: unknown;
  error?: string | null;
}

export interface Search {
  id: string;
  prompt: string;
  source_ids: string[];
  region?: string;
  interval_minutes: number | null;
  next_run_at?: string | null;
  last_job_id: string | null;
  finding_ids?: string[];
  created_at: string;
  updated_at?: string;
}

export interface Health {
  status: string;
  mode?: string;
  database?: string;
  worker?: { id?: string; last_seen_at?: string; mode?: string } | null;
  graph_status?: string;
  model_status?: string;
  [k: string]: unknown;
}

export interface Capabilities {
  mode?: string;
  database?: string;
  graph_provider?: string;
  decision_provider?: string;
  features?: string[];
  adapters?: string[];
  live_research?: boolean;
  deployment_note?: string;
  [k: string]: unknown;
}

export interface FinderEvent {
  id: string;
  action: string;
  entity_id?: string | null;
  data?: Record<string, unknown>;
  created_at: string;
}

export interface GraphNode {
  id: string;
  name: string;
  labels: string[]; // e.g. StartupVenture | Person | Institution
  location?: string;
  [k: string]: unknown;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  fact?: string;
  episode_ids?: string[];
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  mode?: string;
  is_materialized_view?: boolean;
}

export interface CandidateQuery {
  q?: string;
  status?: CandidateStatus | "";
  priority?: Priority | "";
  germany_status?: GermanyStatus | "";
  limit?: number;
  offset?: number;
}
