"""Idempotent bridge from collector source_records into Finder findings."""
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import urlparse


TEXT_FIELDS = ("summary", "description", "abstract", "readme", "comment", "subtitle")
URL_FIELDS = ("url", "source_url", "abs_url", "website_url")


def _plain(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(x for item in value if (x := _plain(item)))
    if isinstance(value, dict):
        if all(isinstance(v, list) for v in value.values()):  # OpenAlex inverted abstract
            words = {}
            for token, positions in value.items():
                for position in positions:
                    words[int(position)] = token
            return " ".join(words[k] for k in sorted(words))
        return ""
    return ""


def map_record(row):
    """Map one collector row; retain source/id/time and original fields in text."""
    payload = row["raw_payload"] or {}
    title = next((_plain(payload.get(k)) for k in ("title", "display_name", "configured_name") if _plain(payload.get(k))), "")
    url = row.get("canonical_url") or next((_plain(payload.get(k)) for k in URL_FIELDS if _plain(payload.get(k))), "")
    if not title:
        title = f"{row['record_type']}: {row.get('external_id') or row['id']}"
    if not url or urlparse(url).scheme not in ("http", "https"):
        return None
    source = row["source_name"]
    database_context = row.get("database_context") or {}
    payload = payload if isinstance(payload, dict) else {}
    relevance_context = {
        "source": source,
        "record_type": row["record_type"],
        "title": title,
        "url": url,
        "content": {
            key: _plain(payload.get(key))[:3500]
            for key in ("summary", "description", "abstract", "subtitle", "readme", "comment")
            if _plain(payload.get(key))
        },
        "linked_entities": [
            {"name": link.get("entity", {}).get("canonical_name"),
             "type": link.get("entity", {}).get("entity_type"),
             "aliases": [a.get("alias") for a in link.get("aliases", [])[:8]]}
            for link in database_context.get("entities", [])[:30]
        ],
        "linked_relationships": [
            {"type": link.get("relationship", {}).get("relationship_type"),
             "source": link.get("source_entity", {}).get("canonical_name"),
             "target": link.get("target_entity", {}).get("canonical_name")}
            for link in database_context.get("relationships", [])[:30]
        ],
        "signals": [
            {"type": link.get("signal", {}).get("signal_type"),
             "description": link.get("signal", {}).get("signal_description"),
             "entity": link.get("entity", {}).get("canonical_name")}
            for link in database_context.get("signals", [])[:20]
        ],
    }
    body = (f"Quelle: {source} ({row['record_type']})\n"
            f"Externe ID: {row.get('external_id') or row['id']}\n"
            "Originaldatensatz (JSON):\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
            + "\nMit demselben Quelldatensatz verknüpfte Datenbankinformationen (JSON):\n"
            + json.dumps(database_context, ensure_ascii=False, separators=(",", ":"), default=str))
    fetched = row.get("updated_at") or row.get("last_seen_at") or datetime.now(timezone.utc)
    published = row.get("published_at")
    return {
        "source_id": f"adapter:{row['source_id']}",
        "source_name": source,
        "source_url": row.get("base_url") or url,
        "external_id": f"adapter-record:{row['id']}",
        "url": url,
        "title": title[:1000],
        "text": body[:200000],
        # The preselection model sees the complete source payload and linked Neon
        # context. The Finder finding keeps its bounded field above.
        "decision_context": body,
        "relevance_context": relevance_context,
        "fetched_at": fetched.isoformat(),
        "published_at": published.isoformat() if published else None,
    }


ADAPTER_RECORD_QUERY = """SELECT sr.id, sr.source_id, sr.external_id, s.source_name, s.base_url, sr.record_type,
                     sr.canonical_url, sr.raw_payload, sr.published_at, sr.updated_at,
                     sr.last_seen_at,
                     jsonb_build_object(
                       'source', to_jsonb(s),
                       'ingestion_run', (SELECT to_jsonb(ir) FROM ingestion_runs ir
                                         WHERE ir.id=sr.last_ingestion_run_id),
                       'revisions', COALESCE((SELECT jsonb_agg(to_jsonb(rev) ORDER BY rev.superseded_at)
                                              FROM source_record_revisions rev
                                              WHERE rev.source_record_id=sr.id), '[]'::jsonb),
                       'entities', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                           'entity', to_jsonb(e), 'source_link', to_jsonb(esr),
                           'aliases', COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.alias)
                                                FROM entity_aliases a WHERE a.entity_id=e.id), '[]'::jsonb)
                         ) ORDER BY e.canonical_name)
                         FROM entity_source_records esr JOIN entities e ON e.id=esr.entity_id
                         WHERE esr.source_record_id=sr.id), '[]'::jsonb),
                       'relationships', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                           'relationship', to_jsonb(rel),
                           'source_entity', to_jsonb(src), 'target_entity', to_jsonb(dst)
                         ) ORDER BY rel.relationship_type, rel.id)
                         FROM relationships rel
                         JOIN entities src ON src.id=rel.source_entity_id
                         JOIN entities dst ON dst.id=rel.target_entity_id
                         WHERE rel.source_record_id=sr.id), '[]'::jsonb),
                       'observations', COALESCE((SELECT jsonb_agg(to_jsonb(obs) ORDER BY obs.observed_at, obs.id)
                                                 FROM observations obs WHERE obs.source_record_id=sr.id), '[]'::jsonb),
                       'signals', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                           'signal', to_jsonb(sig), 'entity', to_jsonb(e)
                         ) ORDER BY sig.created_at, sig.id)
                         FROM signals sig JOIN entities e ON e.id=sig.entity_id
                         WHERE sig.source_record_id=sr.id), '[]'::jsonb)
                     ) AS database_context
              FROM source_records sr JOIN sources s ON s.id=sr.source_id
              WHERE (%s::text IS NULL OR s.source_name=%s::text)
                AND (%s::text IS NULL OR sr.record_type=%s::text)
              ORDER BY sr.updated_at DESC, sr.id LIMIT %s"""


def read_adapter_records(database_url, limit=1000, source_name=None, record_type=None):
    """Read raw records and source-linked domain context without writing Finder state."""
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be 1..1000")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(database_url, row_factory=dict_row) as db:
        rows = db.execute(ADAPTER_RECORD_QUERY,
                          (source_name, source_name, record_type, record_type, limit)).fetchall()
    mapped = [map_record(row) for row in rows]
    items = [item for item in mapped if item]
    return {"read": len(rows), "items": items, "skipped": len(rows) - len(items)}


def import_adapter_records(app, limit=100, source_name=None, record_type=None, dry_run=False):
    """Read collector data and enqueue process jobs without altering collector rows."""
    result = read_adapter_records(app.settings.database_url, limit, source_name, record_type)
    imported, errors = [], []
    relevance_skipped = 0
    relevance_cache = {row['id']: row for row in app.store.list('graph_relevance')}
    for mapped in result["items"]:
        cached = relevance_cache.get(mapped['external_id'])
        context_hash = hashlib.sha256(json.dumps(
            mapped.get('decision_context', mapped['text']), ensure_ascii=False).encode()).hexdigest()
        if cached and cached.get('context_hash') == context_hash and not cached.get('relevant'):
            relevance_skipped += 1
            continue
        if dry_run:
            imported.append({"external_id": mapped["external_id"], "source": mapped["source_name"], "title": mapped["title"]})
            continue
        try:
            source = app.store.get("sources", mapped["source_id"])
            if not source:
                from urllib.parse import urlparse
                app.store.put("sources", {
                    "id": mapped["source_id"], "name": mapped["source_name"],
                    "url": mapped["source_url"], "kind": "manual", "enabled": False,
                    "allowed_hosts": [urlparse(mapped["source_url"]).hostname],
                    "created_at": mapped["fetched_at"], "updated_at": mapped["fetched_at"],
                })
            finding = app.import_finding(mapped)
            if cached and cached.get('context_hash') == context_hash and cached.get('relevant'):
                finding.update(candidate_relevance_checked=True,
                    candidate_relevance={key: cached.get(key) for key in
                        ('candidate_name', 'evidence_type', 'evidence_quote', 'reason', 'model')},
                    updated_at=datetime.now(timezone.utc).isoformat())
                app.store.put('findings', finding)
            if finding.get("status") in ("processed", "excluded_irrelevant", "excluded_no_startup_entity"):
                continue
            if finding.get('candidate_relevance_checked'):
                # A previously screened relevant row can go straight to graph extraction.
                job = app.queue('process', finding['id'])
                imported.append({"finding_id": finding["id"], "job_id": job["id"], "title": finding["title"]})
                continue
            job = app.queue("process", finding["id"])
            imported.append({"finding_id": finding["id"], "job_id": job["id"], "title": finding["title"]})
        except Exception as exc:
            errors.append({"external_id": mapped["external_id"], "error": type(exc).__name__})
    return {"read": result["read"], "imported": len(imported),
            "skipped": result["skipped"] + relevance_skipped,
            "errors": errors, "items": imported}
