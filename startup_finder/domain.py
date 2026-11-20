"""Application services shared by HTTP handlers and background workers."""
import json
from urllib.parse import urlparse
from .graph import Finding
from .store import now, uid


class NotFound(Exception):
    pass


def text(data, key, maximum=10000):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{key}: nonempty text, maximum {maximum} characters')
    return value.strip()


def http_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Absolute HTTP(S) URL without credentials required')
    return value


class Application:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    def require(self, kind, record_id, connection=None):
        record = self.store.get(kind, record_id, connection)
        if not record:
            raise NotFound(f'{kind} record not found')
        return record

    def capabilities(self):
        return dict(mode=self.settings.mode, synthetic=self.settings.mode == 'demo',
            database='postgresql' if self.store.postgres else 'sqlite-demo',
            graph_provider='graphiti' if self.settings.mode == 'live' else 'synthetic-fixtures',
            decision_provider=self.settings.decision_provider,
            features=['sources', 'findings', 'graph', 'candidates', 'research', 'assessments',
                      'shortlist', 'notes', 'searches', 'jobs', 'retry', 'events', 'scheduling'],
            adapters=['html', 'rss', 'manual'], live_research=self.settings.mode == 'live',
            deployment_note='Team prototype; bearer token in live mode, no multi-tenant authorization.')

    def create_source(self, data):
        url = http_url(text(data, 'url', 2000))
        kind = data.get('kind', 'html')
        if kind not in ('html', 'rss', 'manual'):
            raise ValueError('kind must be html, rss or manual')
        return self.store.put('sources', dict(id=uid(), name=text(data, 'name', 200), url=url,
            kind=kind, enabled=True, allowed_hosts=[urlparse(url).hostname.lower()],
            is_demo=False, created_at=now(), updated_at=now()))

    def import_finding(self, data, connection=None):
        if connection is None:
            with self.store.transaction() as c:
                return self.import_finding(data, c)
        source = self.require('sources', text(data, 'source_id', 100), connection)
        payload = dict(id=str(data.get('external_id') or data.get('url') or ''), source=source['id'],
            url=http_url(text(data, 'url', 2000)), title=text(data, 'title', 1000),
            text=text(data, 'text', 200000), fetched_at=data.get('fetched_at') or now(),
            published_at=data.get('published_at'))
        finding = Finding.from_dict(payload)
        record_id = finding.episode_id(self.settings.group_id)
        existing = self.store.get('findings', record_id, connection)
        if existing:
            return existing
        record = dict(payload, id=record_id, external_id=payload['id'], source_id=source['id'],
            status='new', is_demo=False, graph_receipt=None, created_at=now(), updated_at=now())
        self.store.put('findings', record, connection)
        self.store.event('finding.imported', record_id, connection=connection)
        return record

    def queue(self, kind, record_id):
        namespace = {'process': 'findings', 'research': 'candidates', 'evaluate': 'candidates', 'search': 'searches'}[kind]
        with self.store.transaction() as c:
            self.require(namespace, record_id, c)
            payload = {'id': record_id}
            active = self.store.sql(c, "SELECT * FROM jobs WHERE kind=? AND status IN ('queued','running') AND payload=?", (kind, json.dumps(payload))).fetchone()
            if active:
                return self.store.decode_job(active)
            return self.store.enqueue(kind, payload, f'process:{record_id}' if kind == 'process' else None, c)

    def candidate_detail(self, record_id):
        candidate = dict(self.require('candidates', record_id))
        candidate['evidence'] = [e for e in self.store.list('evidence') if e['candidate_id'] == record_id]
        candidate['notes'] = sorted([n for n in self.store.list('notes') if n['candidate_id'] == record_id], key=lambda n:n['created_at'])
        assessments = sorted([a for a in self.store.list('assessments') if a['candidate_id'] == record_id], key=lambda a:a['created_at'], reverse=True)
        candidate['assessment'] = assessments[0] if assessments else None
        candidate['assessment_stale'] = bool(assessments and assessments[0]['profile_version'] != candidate['profile_version'])
        candidate['research_runs'] = sorted([r for r in self.store.list('research_runs') if r['candidate_id'] == record_id], key=lambda r:r['created_at'], reverse=True)
        return candidate

    def patch_candidate(self, record_id, data):
        if set(data) != {'status'} or data['status'] not in ('new', 'shortlisted', 'rejected'):
            raise ValueError('Only status: new | shortlisted | rejected is editable')
        with self.store.transaction() as c:
            candidate = self.require('candidates', record_id, c)
            candidate.update(status=data['status'], updated_at=now())
            self.store.put('candidates', candidate, c)
            self.store.event('candidate.status_changed', record_id, data, c)
        return self.candidate_detail(record_id)

    def add_note(self, record_id, data):
        self.require('candidates', record_id)
        note = dict(id=uid(), candidate_id=record_id, text=text(data, 'text'), created_at=now())
        self.store.put('notes', note)
        self.store.event('candidate.note_added', record_id)
        return note

    def create_search(self, data):
        prompt = text(data, 'prompt', 2000)
        ids = data.get('source_ids', [])
        if not isinstance(ids, list) or not all(isinstance(s, str) for s in ids):
            raise ValueError('source_ids must be an array of strings')
        for source_id in ids:
            self.require('sources', source_id)
        interval = data.get('interval_minutes')
        if interval is not None and (type(interval) is not int or interval < 15):
            raise ValueError('interval_minutes must be >= 15 or null')
        return self.store.put('searches', dict(id=uid(), prompt=prompt, source_ids=ids, region='DE',
            interval_minutes=interval, next_run_at=None, last_job_id=None, created_at=now(), updated_at=now()))

    def list_candidates(self, query):
        rows = self.store.list('candidates')
        if not query.get('germany_status'):
            rows = [r for r in rows if r['germany_status'] != 'outside_germany']
        for key in ('status', 'germany_status'):
            if query.get(key):
                rows = [r for r in rows if r[key] == query[key]]
        if query.get('q'):
            term = query['q'].casefold()
            rows = [r for r in rows if term in ' '.join([r['name'], r['description'], r['location']]).casefold()]
        assessments = sorted(self.store.list('assessments'), key=lambda a:a['created_at'])
        latest = {a['candidate_id']: a for a in assessments}
        for row in rows:
            row['assessment'] = latest.get(row['id'])
            row['assessment_stale'] = bool(row['assessment'] and row['assessment']['profile_version'] != row['profile_version'])
        if query.get('priority'):
            rows = [r for r in rows if r['assessment'] and r['assessment']['priority'] == query['priority']]
        rank = {'high': 0, 'medium': 1, 'low': 2, 'insufficient_data': 3}
        rows.sort(key=lambda r: (rank.get((r.get('assessment') or {}).get('priority'), 4), r['name'].casefold()))
        return rows

    def graph(self):
        return dict(nodes=self.store.list('graph_nodes'), edges=self.store.list('graph_edges'),
                    mode=self.settings.mode, is_materialized_view=True)
