// In-browser mock of the Startup Finder API – same response shapes as docs/frontend-contract.md.
// ALL DATA IS SYNTHETIC (is_demo: true). No real teams, people or sources.
import type { FinderApi } from "./client";
import { ApiError } from "./client";
import type { Assessment, Candidate, CandidateDetail, Evidence, FinderEvent, Finding, Graph, Job, ListResponse, Search, Source } from "../types";

const now = () => new Date().toISOString();
let seq = 1000;
const uid = (p: string) => `${p}-${(seq++).toString(36)}`;
const wait = (ms = 150 + Math.random() * 200) => new Promise((r) => setTimeout(r, ms));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const page = <T,>(items: T[], p?: { limit?: number; offset?: number }): ListResponse<T> => ({
  items: clone(items.slice(p?.offset ?? 0, (p?.offset ?? 0) + (p?.limit ?? 50))),
  total: items.length,
});

interface Db {
  sources: Source[];
  findings: Finding[];
  candidates: CandidateDetail[];
  jobs: (Job & { _fail?: boolean })[];
  searches: Search[];
  events: FinderEvent[];
}

const T0 = "2026-11-19T09:00:00+00:00";

function evidence(id: string, cand: string, finding: string, quote: string, title: string): Evidence {
  return { id, candidate_id: cand, finding_id: finding, url: "https://example.org/demo", title, quote, kind: "exact_quote", attribution: "Source linked by extraction; excerpt is not proof of every profile field.", published_at: null, fetched_at: T0, is_demo: true };
}

function assessment(cand: string, priority: Assessment["priority"], ev: string[]): Assessment {
  const crit = (key: string, label: string, rating: Assessment["criteria"][number]["rating"], rationale: string) => ({ key, label, rating, rationale, evidence_ids: rating === "unknown" ? [] : ev });
  return {
    id: `assessment:${cand}`,
    candidate_id: cand,
    priority,
    summary: "DEMO: regelbasierte Vorschau anhand synthetischer Belege.",
    strengths: ["Gründungsabsicht dokumentiert."],
    concerns: ["Keine unabhängig bestätigte Zahlungsbereitschaft."],
    open_questions: ["Bisherige Finanzierung überprüfen."],
    evidence_ids: ev,
    criteria: [
      crit("founding_intent", "Gründungsabsicht", "moderate", "Synthetischer Hinweis vorhanden; keine unabhängige Validierung."),
      crit("technical_substance", "Technische Substanz", "moderate", "Prototyp erwähnt; Umfang unbekannt."),
      crit("customer_problem", "Kundenproblem", "weak", "Problem nur allgemein beschrieben."),
      crit("demand", "Nachfrage", "unknown", "Kein Beleg für Zahlungsbereitschaft."),
      crit("germany_fit", "Deutschland-Bezug", "strong", "Standort Deutschland genannt."),
    ],
    model: "demo-rules",
    profile_version: 1,
    criteria_version: 1,
    created_at: T0,
    is_demo: true,
  };
}

function cand(id: string, name: string, description: string, location: string, people: string[], finding: string, quote: string, priority: Assessment["priority"] | null): CandidateDetail {
  const evId = `ev-${id}`;
  return {
    id,
    graph_node_id: id,
    name,
    description,
    website: `https://example.org/${id}`,
    location,
    germany_status: "likely",
    entity_type: "venture",
    people,
    signals: [
      { id: `${id}-s1`, kind: "founding_intent", label: "Gründungsabsicht", evidence_id: evId, date: null, is_demo: true },
      { id: `${id}-s2`, kind: "prototype", label: "Prototyp", evidence_id: evId, date: null, is_demo: true },
      { id: `${id}-s3`, kind: "germany_location", label: "Standortangabe Deutschland", evidence_id: evId, date: null, is_demo: true },
    ],
    open_questions: ["Bisherige Finanzierung überprüfen.", "Tatsächlichen oder geplanten Unternehmenssitz bestätigen."],
    status: "new",
    is_demo: true,
    profile_version: 1,
    finding_ids: [finding],
    created_at: T0,
    updated_at: T0,
    evidence: [evidence(evId, id, finding, quote, `DEMO: ${name}`)],
    assessment: priority ? assessment(id, priority, [evId]) : null,
    assessment_stale: false,
    notes: [],
    research_runs: [],
  };
}

function seed(): Db {
  const src: Source = { id: "demo-source", name: "Synthetisches Gründungszentrum", url: "https://example.org/demo", kind: "manual", allowed_hosts: ["example.org"], enabled: true, is_demo: true, created_at: T0, updated_at: T0 };
  const f = (id: string, title: string, text: string, status = "processed"): Finding => ({ id, source_id: "demo-source", source: "demo-source", url: "https://example.org/demo", title, text: `SYNTHETISCH – KEIN REALER LEAD.\n${text}`, published_at: null, fetched_at: T0, status, is_demo: true });
  const findings = [
    f("f-energy", "DEMO: DemoEnergy", "Sam Beispiel plant die Gründung von DemoEnergy in München. Ein Prototyp liegt vor."),
    f("f-robot", "DEMO: DemoRobotics", "Alex Muster baut in Aachen einen Greifer-Prototyp; ein Pilotkunde ist im Gespräch."),
    f("f-bio", "DEMO: DemoBio", "Kim Probe entwickelt in Heidelberg ein Enzym-Verfahren; Gründung geplant."),
    f("f-new", "DEMO: DemoSensor", "Ein Team aus Jena arbeitet an einem Gassensor.", "new"),
  ];
  const c1 = cand("c-energy", "DemoEnergy", "Fiktive Software zur Planung industrieller Energienutzung.", "München", ["Sam Beispiel"], "f-energy", findings[0].text!.split("\n")[1], "medium");
  const c2 = cand("c-robot", "DemoRobotics", "Fiktiver Greifer für Kleinserienfertigung.", "Aachen", ["Alex Muster"], "f-robot", findings[1].text!.split("\n")[1], "high");
  const c3 = cand("c-bio", "DemoBio", "Fiktives Enzym-Verfahren für Kunststoffrecycling.", "Heidelberg", ["Kim Probe"], "f-bio", findings[2].text!.split("\n")[1], null);
  c3.conflicts = [{ field: "location", previous: "Heidelberg", incoming: "Mannheim", finding_id: "f-bio" }];
  return {
    sources: [src],
    findings,
    candidates: [c2, c1, c3],
    jobs: [
      { id: "job-seed-1", kind: "evaluate", status: "succeeded", payload: { id: "c-energy" }, result: { assessment_id: "assessment:c-energy" }, error: null, attempts: 1, max_attempts: 3, created_at: T0, updated_at: T0 },
      { id: "job-seed-2", kind: "process", status: "failed", payload: { id: "f-x" }, result: null, error: "Quelle antwortete mit 503 (synthetischer Fehler).", attempts: 3, max_attempts: 3, created_at: T0, updated_at: T0 },
    ],
    searches: [],
    events: [],
  };
}

const summary = (c: CandidateDetail): Candidate => {
  const { evidence: _e, notes: _n, research_runs: _r, ...rest } = c;
  void _e;
  void _n;
  void _r;
  return rest;
};

export function createMockApi(): FinderApi {
  let db = seed();
  const log = (action: string, entity_id: string | null, data: Record<string, unknown> = {}) => db.events.unshift({ id: uid("evt"), action, entity_id, data, created_at: now() });
  const find = <T extends { id: string }>(arr: T[], id: string, what: string) => {
    const x = arr.find((i) => i.id === id);
    if (!x) throw new ApiError(`${what} record not found`, 404);
    return x;
  };

  /** Simulated worker: queued → running → succeeded/failed. */
  function enqueue(kind: string, payload: Record<string, unknown>, work: () => Record<string, unknown>, failFirst = false) {
    const job: Db["jobs"][number] = { id: uid("job"), kind, status: "queued", payload, result: null, error: null, attempts: 0, max_attempts: 3, created_at: now(), updated_at: now(), _fail: failFirst };
    db.jobs.unshift(job);
    const run = () => {
      setTimeout(() => Object.assign(job, { status: "running", attempts: job.attempts + 1, updated_at: now() }), 400);
      setTimeout(() => {
        job.updated_at = now();
        if (job._fail && job.attempts === 1) {
          Object.assign(job, { status: "failed", error: "Zeitüberschreitung beim Abruf (synthetischer Fehler – bitte wiederholen)." });
          log("job.failed", job.id);
          return;
        }
        try {
          Object.assign(job, { result: work(), status: "succeeded", error: null });
          log(`${kind}.succeeded`, (payload.id as string) ?? null);
        } catch (e) {
          Object.assign(job, { status: "failed", error: e instanceof Error ? e.message : "Fehler" });
        }
      }, 1800);
    };
    (job as Job & { _run?: () => void })._run = run;
    run();
    const { _fail: _f, ...out } = job;
    void _f;
    return { job: clone(out) as Job };
  }
  const strip = (j: Db["jobs"][number]): Job => {
    const { _fail: _f, ...rest } = j as Db["jobs"][number] & { _run?: unknown };
    void _f;
    delete (rest as { _run?: unknown })._run;
    return clone(rest);
  };

  return {
    kind: "mock",
    baseUrl: null,
    async health() {
      await wait();
      return { status: "ok", mode: "mock", database: "browser", worker: { id: "mock", last_seen_at: now(), mode: "mock" }, graph_status: "not_probed", model_status: "not_probed" };
    },
    async capabilities() {
      await wait();
      return { mode: "mock", synthetic: true, database: "browser-memory", graph_provider: "none", decision_provider: "off", features: ["sources", "findings", "candidates", "research", "assessments", "shortlist", "notes", "searches", "jobs", "retry", "events"], adapters: ["html", "rss", "manual"], live_research: false, deployment_note: "Frontend-Mock im Browser – keine Backend-Verbindung." };
    },
    async listSources(p) {
      await wait();
      return page(db.sources, p);
    },
    async createSource(b) {
      await wait();
      if (!b.name?.trim() || !b.url?.trim()) throw new ApiError("name und url sind erforderlich", 422);
      const s: Source = { id: uid("src"), name: b.name, url: b.url, kind: b.kind, allowed_hosts: [], enabled: true, is_demo: true, created_at: now(), updated_at: now() };
      db.sources.push(s);
      log("source.created", s.id);
      return clone(s);
    },
    async getSource(id) {
      await wait();
      return clone(find(db.sources, id, "sources"));
    },
    async patchSource(id, b) {
      await wait();
      const s = find(db.sources, id, "sources");
      s.enabled = b.enabled;
      s.updated_at = now();
      return clone(s);
    },
    async listFindings(p) {
      await wait();
      let items = db.findings;
      if (p?.source_id) items = items.filter((f) => f.source_id === p.source_id);
      if (p?.status) items = items.filter((f) => f.status === p.status);
      if (p?.q) items = items.filter((f) => `${f.title} ${f.text}`.toLowerCase().includes(p.q!.toLowerCase()));
      return page(items, p);
    },
    async createFinding(b) {
      await wait();
      if (!b.source_id || !b.url || !b.title || !b.text) throw new ApiError("source_id, url, title und text sind erforderlich", 422);
      const f: Finding = { id: uid("f"), source_id: b.source_id, source: b.source_id, url: b.url, title: b.title, text: b.text, published_at: b.published_at ?? null, fetched_at: now(), status: "new", is_demo: true };
      db.findings.unshift(f);
      return clone(f);
    },
    async getFinding(id) {
      await wait();
      return clone(find(db.findings, id, "findings"));
    },
    async processFinding(id) {
      await wait();
      const f = find(db.findings, id, "findings");
      // contract: demo only extracts explicit synthetic fixtures – arbitrary text yields no candidate
      return enqueue(
        "process",
        { id },
        () => {
          f.status = "processed";
          return { candidate_ids: [] };
        },
        f.id === "f-new",
      );
    },
    async listCandidates(q = {}) {
      await wait();
      const term = q.q?.trim().toLowerCase();
      let items = db.candidates.map(summary);
      // like the backend: outside_germany is hidden unless that filter is set explicitly
      if (!q.germany_status) items = items.filter((c) => c.germany_status !== "outside_germany");
      if (q.status) items = items.filter((c) => c.status === q.status);
      if (q.priority) items = items.filter((c) => (c.assessment?.priority ?? "insufficient_data") === q.priority);
      if (q.germany_status) items = items.filter((c) => c.germany_status === q.germany_status);
      // like the backend: name, description and location only
      if (term) items = items.filter((c) => [c.name, c.description, c.location].join(" ").toLowerCase().includes(term));
      return page(items, q);
    },
    async getCandidate(id) {
      await wait();
      return clone(find(db.candidates, id, "candidates"));
    },
    async patchCandidate(id, b) {
      await wait();
      const c = find(db.candidates, id, "candidates");
      c.status = b.status;
      c.updated_at = now();
      log(`candidate.${b.status}`, id);
      return summary(clone(c));
    },
    async addNote(id, text) {
      await wait();
      if (!text.trim()) throw new ApiError("text darf nicht leer sein", 422);
      const c = find(db.candidates, id, "candidates");
      const n = { id: uid("note"), candidate_id: id, text: text.trim(), created_at: now() };
      c.notes.unshift(n);
      return clone(n);
    },
    async research(id) {
      await wait();
      const c = find(db.candidates, id, "candidates");
      return enqueue("research", { id }, () => {
        c.research_runs.unshift({ id: uid("run"), candidate_id: id, summary: "DEMO: gekennzeichneter Recherchelauf ohne Internetabfrage.", sources: [], imported_finding_ids: [], fetch_errors: [], created_at: now(), is_demo: true });
        c.updated_at = now();
        if (c.assessment) c.assessment_stale = true;
        return { run_id: c.research_runs[0].id };
      });
    },
    async evaluate(id) {
      await wait();
      const c = find(db.candidates, id, "candidates");
      return enqueue("evaluate", { id }, () => {
        c.assessment = assessment(id, c.evidence.length ? "medium" : "insufficient_data", c.evidence.map((e) => e.id));
        c.assessment.created_at = now();
        c.assessment_stale = false;
        return { assessment_id: c.assessment.id };
      });
    },
    async listJobs(p) {
      await wait();
      let items = db.jobs;
      if (p?.status) items = items.filter((j) => j.status === p.status);
      if (p?.kind) items = items.filter((j) => j.kind === p.kind);
      return { items: items.slice(p?.offset ?? 0, (p?.offset ?? 0) + (p?.limit ?? 50)).map(strip), total: items.length };
    },
    async getJob(id) {
      await wait(100);
      return strip(find(db.jobs, id, "jobs"));
    },
    async retryJob(id) {
      await wait();
      const j = find(db.jobs, id, "jobs") as Db["jobs"][number] & { _run?: () => void };
      if (j.status !== "failed") throw new ApiError("Nur fehlgeschlagene Jobs können wiederholt werden", 422);
      Object.assign(j, { status: "queued", error: null, updated_at: now() });
      if (j._run) j._run();
      else {
        setTimeout(() => Object.assign(j, { status: "running", attempts: j.attempts + 1, updated_at: now() }), 400);
        setTimeout(() => Object.assign(j, { status: "succeeded", result: {}, updated_at: now() }), 2000);
      }
      return { job: strip(j) };
    },
    async listSearches(p) {
      await wait();
      return page(db.searches, p);
    },
    async createSearch(b) {
      await wait();
      if (!b.prompt?.trim()) throw new ApiError("prompt ist erforderlich", 422);
      const s: Search = { id: uid("search"), prompt: b.prompt.trim(), source_ids: b.source_ids ?? [], region: "DE", interval_minutes: b.interval_minutes ?? null, next_run_at: null, last_job_id: null, created_at: now(), updated_at: now() };
      db.searches.unshift(s);
      return clone(s);
    },
    async getSearch(id) {
      await wait();
      return clone(find(db.searches, id, "searches"));
    },
    async runSearch(id) {
      await wait();
      const s = find(db.searches, id, "searches");
      const res = enqueue("search", { id }, () => {
        const ids = db.findings.filter((f) => !s.source_ids.length || s.source_ids.includes(f.source_id ?? "")).map((f) => f.id);
        s.finding_ids = ids;
        const children = ids.slice(0, 3).map((fid) => enqueue("process", { id: fid }, () => ({ candidate_ids: [] })).job.id);
        return { finding_ids: ids, child_job_ids: children, source_errors: [], scope: "Configured-source collection; prompt is saved context, not yet semantic discovery." };
      });
      s.last_job_id = res.job.id;
      s.updated_at = now();
      return res;
    },
    async graph() {
      await wait();
      const nodes: Graph["nodes"] = [];
      const edges: Graph["edges"] = [];
      db.candidates.forEach((c) => {
        nodes.push({ id: c.graph_node_id, name: c.name, labels: ["StartupVenture"], location: c.location, is_demo: true });
        c.people.forEach((p) => {
          const pid = `person-${p}`;
          if (!nodes.some((n) => n.id === pid)) nodes.push({ id: pid, name: p, labels: ["Person"], is_demo: true });
          edges.push({ id: `e-${pid}-${c.id}`, source: pid, target: c.graph_node_id, relation: "WORKS_ON", fact: `${p} arbeitet an ${c.name}`, episode_ids: c.finding_ids, is_demo: true });
        });
      });
      nodes.push({ id: "inst-demo", name: "Synthetisches Gründungszentrum", labels: ["Institution"], is_demo: true });
      edges.push({ id: "e-inst-robot", source: "c-robot", target: "inst-demo", relation: "SUPPORTED_BY", fact: "DemoRobotics wird vom Gründungszentrum begleitet", episode_ids: ["f-robot"], is_demo: true });
      return { nodes, edges, mode: "mock", is_materialized_view: true };
    },
    async events(p) {
      await wait();
      const items = p?.entity_id ? db.events.filter((e) => e.entity_id === p.entity_id) : db.events;
      return page(items, p);
    },
    async seedDemo() {
      await wait(400);
      db = seed();
      log("demo.seeded", null);
      return { ok: true };
    },
  };
}
