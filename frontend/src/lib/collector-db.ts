import "server-only";

import { loadEnvConfig } from "@next/env";
import { Pool, type PoolClient } from "pg";
import path from "node:path";

loadEnvConfig(path.resolve(process.cwd(), ".."));

declare global {
  // eslint-disable-next-line no-var
  var collectorPool: Pool | undefined;
}

function getPool() {
  const connectionString = process.env.DATABASE_URL || process.env.DATABASE_URL_DIRECT;
  if (!connectionString) throw new Error("DATABASE_URL fehlt in der Projekt-.env.");
  globalThis.collectorPool ??= new Pool({
    connectionString,
    max: 3,
    connectionTimeoutMillis: 8000,
    idleTimeoutMillis: 30000,
    allowExitOnIdle: true,
  });
  return globalThis.collectorPool;
}

async function readOnly<T>(query: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await getPool().connect();
  try {
    await client.query("BEGIN READ ONLY");
    return await query(client);
  } finally {
    try {
      await client.query("ROLLBACK");
    } finally {
      client.release();
    }
  }
}

export type DashboardView = "overview" | "entities" | "relationships" | "records" | "runs";

export interface EntityTypeCount {
  entityType: string;
  count: number;
}

export interface SourceSummary {
  name: string;
  type: string;
  url: string | null;
  recordCount: number;
}

export interface IngestionRunRow {
  id: string;
  sourceName: string;
  status: string;
  startedAt: string;
  completedAt: string | null;
  fetched: number;
  created: number;
  updated: number;
  failed: number;
  error: string | null;
}

export interface EntityRow {
  id: string;
  entityType: string;
  name: string;
  description: string | null;
  sourceCount: number;
  updatedAt: string;
}

export interface RelationshipRow {
  id: string;
  sourceName: string;
  sourceType: string;
  relation: string;
  targetName: string;
  targetType: string;
  verification: string;
  confidence: string | null;
  sourceNameFrom: string;
  sourceUrl: string | null;
}

export interface SourceRecordRow {
  id: string;
  sourceName: string;
  recordType: string;
  title: string;
  url: string | null;
  publishedAt: string | null;
  lastSeenAt: string;
  entityCount: number;
}

export interface DashboardData {
  counts: {
    sources: number;
    sourceRecords: number;
    entities: number;
    relationships: number;
    signals: number;
    observations: number;
    runs: number;
  };
  entityTypes: EntityTypeCount[];
  sources: SourceSummary[];
  recentRuns: IngestionRunRow[];
  entities: EntityRow[];
  entityTotal: number;
  relationships: RelationshipRow[];
  records: SourceRecordRow[];
  runs: IngestionRunRow[];
}

const number = (value: string | number | null | undefined) => Number(value ?? 0);

export async function getDashboardData(view: DashboardView, search = "", entityType = ""): Promise<DashboardData> {
  try {
    return await readOnly(async (client) => {
      const countResult = await client.query<{
        sources: string;
        source_records: string;
        entities: string;
        relationships: string;
        signals: string;
        observations: string;
        runs: string;
      }>(`SELECT
        (SELECT count(*) FROM sources) AS sources,
        (SELECT count(*) FROM source_records) AS source_records,
        (SELECT count(*) FROM entities) AS entities,
        (SELECT count(*) FROM relationships) AS relationships,
        (SELECT count(*) FROM signals) AS signals,
        (SELECT count(*) FROM observations) AS observations,
        (SELECT count(*) FROM ingestion_runs) AS runs`);
      const c = countResult.rows[0];

      const typeResult = await client.query<{ entity_type: string; count: string }>(
        `SELECT entity_type, count(*) AS count FROM entities GROUP BY entity_type ORDER BY count(*) DESC, entity_type`,
      );
      const sourceResult = await client.query<{ name: string; type: string; url: string | null; count: string }>(
        `SELECT s.source_name AS name, s.source_type AS type, s.base_url AS url, count(sr.id) AS count
         FROM sources s LEFT JOIN source_records sr ON sr.source_id = s.id
         GROUP BY s.id, s.source_name, s.source_type, s.base_url ORDER BY count(sr.id) DESC, s.source_name`,
      );
      const runSql = `SELECT ir.id::text, s.source_name AS source_name, ir.status,
          ir.started_at::text, ir.completed_at::text, ir.records_fetched AS fetched,
          ir.records_created AS created, ir.records_updated AS updated, ir.records_failed AS failed,
          ir.error_message AS error
        FROM ingestion_runs ir JOIN sources s ON s.id = ir.source_id
        ORDER BY ir.started_at DESC LIMIT 12`;
      const recentRunResult = await client.query<IngestionRunRow>(runSql);

      let entities: EntityRow[] = [];
      let entityTotal = 0;
      if (view === "entities") {
        const terms = search.trim() ? `%${search.trim().slice(0, 120)}%` : null;
        const type = entityType.trim() || null;
        const totalResult = await client.query<{ count: string }>(
          `SELECT count(*) AS count FROM entities
           WHERE ($1::text IS NULL OR entity_type = $1)
             AND ($2::text IS NULL OR canonical_name ILIKE $2 OR COALESCE(description, '') ILIKE $2)`,
          [type, terms],
        );
        entityTotal = number(totalResult.rows[0]?.count);
        const entityResult = await client.query<EntityRow>(
          `SELECT e.id::text, e.entity_type AS "entityType", e.canonical_name AS name,
              e.description, count(DISTINCT esr.source_record_id)::int AS "sourceCount",
              e.updated_at::text AS "updatedAt"
           FROM entities e
           LEFT JOIN entity_source_records esr ON esr.entity_id = e.id
           WHERE ($1::text IS NULL OR e.entity_type = $1)
             AND ($2::text IS NULL OR e.canonical_name ILIKE $2 OR COALESCE(e.description, '') ILIKE $2)
           GROUP BY e.id ORDER BY e.updated_at DESC, e.canonical_name LIMIT 100`,
          [type, terms],
        );
        entities = entityResult.rows;
      }

      let relationships: RelationshipRow[] = [];
      if (view === "relationships") {
        const relationResult = await client.query<RelationshipRow>(
          `SELECT r.id::text, a.canonical_name AS "sourceName", a.entity_type AS "sourceType",
              r.relationship_type AS relation, b.canonical_name AS "targetName", b.entity_type AS "targetType",
              r.verification_status AS verification, r.confidence::text,
              s.source_name AS "sourceNameFrom", sr.canonical_url AS "sourceUrl"
           FROM relationships r
           JOIN entities a ON a.id = r.source_entity_id
           JOIN entities b ON b.id = r.target_entity_id
           JOIN source_records sr ON sr.id = r.source_record_id
           JOIN sources s ON s.id = sr.source_id
           ORDER BY r.last_seen_at DESC LIMIT 100`,
        );
        relationships = relationResult.rows;
      }

      let records: SourceRecordRow[] = [];
      if (view === "records") {
        const recordResult = await client.query<SourceRecordRow>(
          `SELECT sr.id::text, s.source_name AS "sourceName", sr.record_type AS "recordType",
              COALESCE(sr.raw_payload->>'title', sr.raw_payload->>'name', sr.raw_payload->>'display_name', sr.record_type) AS title,
              sr.canonical_url AS url, sr.published_at::text AS "publishedAt", sr.last_seen_at::text AS "lastSeenAt",
              (SELECT count(*)::int FROM entity_source_records esr WHERE esr.source_record_id = sr.id) AS "entityCount"
           FROM source_records sr JOIN sources s ON s.id = sr.source_id
           ORDER BY sr.last_seen_at DESC LIMIT 100`,
        );
        records = recordResult.rows;
      }

      let runs: IngestionRunRow[] = [];
      if (view === "runs") {
        const allRuns = await client.query<IngestionRunRow>(runSql.replace("LIMIT 12", "LIMIT 100"));
        runs = allRuns.rows;
      }

      return {
        counts: {
          sources: number(c.sources),
          sourceRecords: number(c.source_records),
          entities: number(c.entities),
          relationships: number(c.relationships),
          signals: number(c.signals),
          observations: number(c.observations),
          runs: number(c.runs),
        },
        entityTypes: typeResult.rows.map((row) => ({ entityType: row.entity_type, count: number(row.count) })),
        sources: sourceResult.rows.map((row) => ({ ...row, recordCount: number(row.count) })),
        recentRuns: recentRunResult.rows,
        entities,
        entityTotal,
        relationships,
        records,
        runs,
      };
    });
  } catch (error) {
    if (error instanceof Error && error.message === "DATABASE_URL fehlt in der Projekt-.env.") throw error;
    throw new Error("Die schreibgeschützte Verbindung zur Neon-Datenbank ist fehlgeschlagen.");
  }
}
