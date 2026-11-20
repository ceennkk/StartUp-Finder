"""Transactional PostgreSQL store; SQLite is an explicit offline demo backend.

JSON documents keep frontend payloads stable. Separate indexed fields serve job
claiming, idempotency and graph identity. Each transaction uses its own connection.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid4())


class Store:
    def __init__(self, url):
        self.url = url
        self.postgres = url.startswith(('postgresql://', 'postgres://'))
        if not self.postgres:
            if not url.startswith('sqlite:///'):
                raise ValueError('Unsupported database URL')
            Path(url[10:]).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def transaction(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            connection = psycopg.connect(self.url, row_factory=dict_row)
        else:
            connection = sqlite3.connect(self.url[10:], timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('BEGIN IMMEDIATE')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def sql(self, connection, query, args=()):
        return connection.execute(query.replace('?', '%s') if self.postgres else query, args)

    def initialize(self):
        with self.transaction() as c:
            # Applied idempotently; schema_version records this initial migration.
            for statement in (
                'CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)',
                'CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(kind,id))',
                'CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT, attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL, available_at DOUBLE PRECISION NOT NULL, lease_until DOUBLE PRECISION, lease_token TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, dedupe_key TEXT UNIQUE)',
                'CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status, available_at)',
                'CREATE TABLE IF NOT EXISTS leases (name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL)',
            ):
                self.sql(c, statement)
            self.sql(c, 'INSERT INTO schema_version(version) VALUES (1) ON CONFLICT(version) DO NOTHING')

    def get(self, kind, record_id, connection=None):
        if connection is None:
            with self.transaction() as c:
                return self.get(kind, record_id, c)
        # Read-modify-write callers keep this lock until their transaction ends,
        # preventing worker profile updates from overwriting concurrent user actions.
        suffix = ' FOR UPDATE' if self.postgres else ''
        row = self.sql(connection, 'SELECT data FROM records WHERE kind=? AND id=?'+suffix, (kind, record_id)).fetchone()
        return json.loads(row['data']) if row else None

    def put(self, kind, data, connection=None):
        if connection is None:
            with self.transaction() as c:
                return self.put(kind, data, c)
        self.sql(connection, 'INSERT INTO records(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',
                 (kind, data['id'], json.dumps(data, ensure_ascii=False)))
        return data

    def list(self, kind, connection=None):
        if connection is None:
            with self.transaction() as c:
                return self.list(kind, c)
        return [json.loads(r['data']) for r in self.sql(connection, 'SELECT data FROM records WHERE kind=? ORDER BY id', (kind,)).fetchall()]

    def event(self, action, entity_id, data=None, connection=None):
        return self.put('events', dict(id=uid(), action=action, entity_id=entity_id, data=data or {}, created_at=now()), connection)

    def enqueue(self, kind, payload, dedupe_key=None, connection=None):
        if connection is None:
            with self.transaction() as c:
                return self.enqueue(kind, payload, dedupe_key, c)
        stamp = now()
        job_id = uid()
        self.sql(connection, 'INSERT INTO jobs(id,kind,status,payload,attempts,max_attempts,available_at,created_at,updated_at,dedupe_key) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(dedupe_key) DO NOTHING',
                 (job_id, kind, 'queued', json.dumps(payload), 0, 3, time.time(), stamp, stamp, dedupe_key))
        query, args = ('SELECT * FROM jobs WHERE dedupe_key=?', (dedupe_key,)) if dedupe_key else ('SELECT * FROM jobs WHERE id=?', (job_id,))
        return self.decode_job(self.sql(connection, query, args).fetchone())

    @staticmethod
    def decode_job(row):
        if not row:
            return None
        result = dict(row)
        for key in ('payload', 'result'):
            result[key] = json.loads(result[key]) if result[key] else ({} if key == 'payload' else None)
        result.pop('lease_token', None)
        return result

    def jobs(self, job_id=None):
        with self.transaction() as c:
            if job_id:
                return self.decode_job(self.sql(c, 'SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
            return [self.decode_job(r) for r in self.sql(c, 'SELECT * FROM jobs ORDER BY created_at DESC').fetchall()]

    def claim(self, lease_seconds):
        with self.transaction() as c:
            clock = time.time()
            self.sql(c, "UPDATE jobs SET status=CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END, error='Worker lease expired', updated_at=? WHERE status='running' AND lease_until < ?", (now(), clock))
            suffix = ' FOR UPDATE SKIP LOCKED' if self.postgres else ''
            row = self.sql(c, "SELECT * FROM jobs WHERE status='queued' AND available_at <= ? ORDER BY created_at LIMIT 1" + suffix, (clock,)).fetchone()
            if not row:
                return None
            token = uid()
            self.sql(c, "UPDATE jobs SET status='running', attempts=attempts+1, lease_until=?, lease_token=?, updated_at=? WHERE id=?", (clock + lease_seconds, token, now(), row['id']))
            job = self.decode_job(self.sql(c, 'SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())
            job['_lease_token'] = token
            return job

    def heartbeat(self, job, lease_seconds):
        with self.transaction() as c:
            return self.sql(c, "UPDATE jobs SET lease_until=? WHERE id=? AND status='running' AND lease_token=?", (time.time()+lease_seconds, job['id'], job['_lease_token'])).rowcount == 1

    def finish(self, job, result=None, error=None):
        status = 'queued' if error and job['attempts'] < job['max_attempts'] else ('failed' if error else 'succeeded')
        with self.transaction() as c:
            self.sql(c, 'UPDATE jobs SET status=?, result=?, error=?, available_at=?, lease_until=NULL, updated_at=? WHERE id=? AND lease_token=?',
                     (status, json.dumps(result) if result is not None else None, error, time.time()+min(60, 2**job['attempts']), now(), job['id'], job['_lease_token']))

    def retry(self, job_id):
        with self.transaction() as c:
            changed = self.sql(c, "UPDATE jobs SET status='queued', attempts=0, error=NULL, available_at=?, updated_at=? WHERE id=? AND status='failed'", (time.time(), now(), job_id)).rowcount
        if not changed:
            raise ValueError('Only failed jobs can be retried')
        return self.jobs(job_id)

    def acquire(self, name, owner, seconds):
        with self.transaction() as c:
            self.sql(c, 'INSERT INTO leases(name,owner,expires_at) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner, expires_at=excluded.expires_at WHERE leases.expires_at < ? OR leases.owner=?', (name, owner, time.time()+seconds, time.time(), owner))
            row = self.sql(c, 'SELECT owner FROM leases WHERE name=?', (name,)).fetchone()
            return row['owner'] == owner

    def release(self, name, owner):
        with self.transaction() as c:
            self.sql(c, 'DELETE FROM leases WHERE name=? AND owner=?', (name, owner))
