import type {
  Capabilities,
  ChatResponse,
  Candidate,
  CandidateDetail,
  CandidateQuery,
  CandidateStatus,
  FinderEvent,
  Finding,
  Graph,
  Health,
  Job,
  ListResponse,
  Note,
  Search,
  Source,
} from "../types";

/** Production HTTP client for the endpoints in docs/frontend-contract.md. */
export interface FinderApi {
  readonly kind: "http";
  readonly baseUrl: string;
  health(): Promise<Health>;
  capabilities(): Promise<Capabilities>;
  listSources(p?: Page): Promise<ListResponse<Source>>;
  createSource(body: { name: string; url: string; kind: string }): Promise<Source>;
  getSource(id: string): Promise<Source>;
  patchSource(id: string, body: { enabled: boolean }): Promise<Source>;
  listFindings(p?: Page & { source_id?: string; status?: string; q?: string }): Promise<ListResponse<Finding>>;
  createFinding(body: { source_id: string; url: string; title: string; text: string; external_id?: string; published_at?: string }): Promise<Finding>;
  getFinding(id: string): Promise<Finding>;
  processFinding(id: string): Promise<{ job: Job }>;
  listCandidates(q?: CandidateQuery): Promise<ListResponse<Candidate>>;
  getCandidate(id: string): Promise<CandidateDetail>;
  patchCandidate(id: string, body: { status: CandidateStatus }): Promise<Candidate>;
  addNote(id: string, text: string): Promise<Note>;
  research(id: string): Promise<{ job: Job }>;
  evaluate(id: string): Promise<{ job: Job }>;
  listJobs(p?: Page & { status?: string; kind?: string }): Promise<ListResponse<Job>>;
  getJob(id: string): Promise<Job>;
  retryJob(id: string): Promise<{ job: Job }>;
  listSearches(p?: Page): Promise<ListResponse<Search>>;
  createSearch(body: { prompt: string; source_ids?: string[]; interval_minutes?: number | null }): Promise<Search>;
  getSearch(id: string): Promise<Search>;
  runSearch(id: string): Promise<{ job: Job }>;
  graph(): Promise<Graph>;
  chat(question: string, language: "en" | "de", history?: { role: "user" | "assistant"; content: string }[], candidateId?: string | null): Promise<ChatResponse>;
  events(p?: Page & { entity_id?: string }): Promise<ListResponse<FinderEvent>>;
}

export interface Page {
  limit?: number;
  offset?: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const qs = (params?: object) => {
  if (!params) return "";
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
};

const STATUS_TEXT: Record<number, string> = {
  401: "Not authorized — the API token is missing or invalid.",
  404: "Not found.",
  413: "Request is too large.",
  422: "Invalid input.",
  500: "Internal backend error.",
};

export function createHttpApi(baseUrl: string, token?: string): FinderApi {
  const base = baseUrl.replace(/\/$/, "");
  async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;
    let res: Response;
    try {
      res = await fetch(`${base}/api${path}`, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    } catch {
      throw new ApiError(`Backend not reachable (${base}). Check that it is running and allows this page in CORS_ORIGINS.`, 0);
    }
    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      /* non-JSON body */
    }
    if (!res.ok) {
      const detail = data && typeof data === "object" && "detail" in data ? String((data as { detail: unknown }).detail) : "";
      throw new ApiError(detail || STATUS_TEXT[res.status] || `Error ${res.status}`, res.status);
    }
    return data as T;
  }
  const id = encodeURIComponent;
  return {
    kind: "http",
    baseUrl: base,
    health: () => req("GET", "/health"),
    capabilities: () => req("GET", "/capabilities"),
    listSources: (p) => req("GET", `/sources${qs(p)}`),
    createSource: (b) => req("POST", "/sources", b),
    getSource: (i) => req("GET", `/sources/${id(i)}`),
    patchSource: (i, b) => req("PATCH", `/sources/${id(i)}`, b),
    listFindings: (p) => req("GET", `/findings${qs(p)}`),
    createFinding: (b) => req("POST", "/findings", b),
    getFinding: (i) => req("GET", `/findings/${id(i)}`),
    processFinding: (i) => req("POST", `/findings/${id(i)}/process`, {}),
    listCandidates: (q) => req("GET", `/candidates${qs(q)}`),
    getCandidate: (i) => req("GET", `/candidates/${id(i)}`),
    patchCandidate: (i, b) => req("PATCH", `/candidates/${id(i)}`, b),
    addNote: (i, text) => req("POST", `/candidates/${id(i)}/notes`, { text }),
    research: (i) => req("POST", `/candidates/${id(i)}/research`, {}),
    evaluate: (i) => req("POST", `/candidates/${id(i)}/evaluate`, {}),
    listJobs: (p) => req("GET", `/jobs${qs(p)}`),
    getJob: (i) => req("GET", `/jobs/${id(i)}`),
    retryJob: (i) => req("POST", `/jobs/${id(i)}/retry`, {}),
    listSearches: (p) => req("GET", `/searches${qs(p)}`),
    createSearch: (b) => req("POST", "/searches", b),
    getSearch: (i) => req("GET", `/searches/${id(i)}`),
    runSearch: (i) => req("POST", `/searches/${id(i)}/run`, {}),
    graph: () => req("GET", "/graph"),
    chat: (question, language, history = [], candidateId) => req("POST", "/chat", { question, language, history, candidate_id: candidateId }),
    events: (p) => req("GET", `/events${qs(p)}`),
  };
}

/** Production API configuration: env first, then an optional per-browser override. */
export const DEFAULT_BASE_URL = process.env.NEXT_PUBLIC_FINDER_API_URL || "http://localhost:8000";
const KEY = "finder-api-config";

export interface ApiConfig {
  baseUrl: string;
  /** Team API token (live mode). Not a model key. Kept in this browser only. */
  token: string;
}

export function loadConfig(): ApiConfig {
  const fallback: ApiConfig = { baseUrl: DEFAULT_BASE_URL, token: "" };
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...fallback, ...(JSON.parse(raw) as Partial<ApiConfig>) };
  } catch {
    /* ignore */
  }
  return fallback;
}

export function saveConfig(c: ApiConfig) {
  try {
    localStorage.setItem(KEY, JSON.stringify(c));
  } catch {
    /* ignore */
  }
}
