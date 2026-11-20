"""Persistent jobs, lease renewal, retries and incremental ingestion."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import logging
import threading
from urllib.parse import urlparse
from .candidates import materialize
from .clients import DemoModels, GraphBridge, OpenAIModels
from .fetching import collect, fetch, text_from_html
from .graph import Finding
from .store import now, uid

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, app, bridge=None, models=None):
        self.app, self.store, self.settings = app, app.store, app.settings
        self.bridge = bridge or GraphBridge(self.settings)
        self.models = models or (DemoModels() if self.settings.mode == 'demo' else OpenAIModels(self.settings))

    def process(self, finding_id):
        finding = self.app.require('findings', finding_id)
        if finding['status'] == 'processed':
            return dict(candidate_ids=finding.get('candidate_ids', []), unchanged=True)
        if self.settings.mode == 'demo' and not finding.get('is_demo'):
            raise ValueError('Demo extracts only seeded structured fixtures. Use live mode for arbitrary text extraction.')
        receipt = finding.get('graph_receipt')
        if not receipt:
            value = Finding.from_dict({**finding, 'id': finding['external_id']})
            wrapped = SimpleNamespace(**value.__dict__, episode_id=value.episode_id,
                                      demo_entities=finding.get('demo_entities', []))
            receipt = self.bridge.ingest(wrapped)
            finding.update(graph_receipt=receipt, status='graph_processed', updated_at=now())
            self.store.put('findings', finding)
        ids = materialize(self.app, finding, receipt)
        return dict(candidate_ids=ids, episode_id=receipt['episode_id'])

    def evaluate(self, candidate_id, job_id):
        assessment_id = f'assessment:{job_id}'
        existing = self.store.get('assessments', assessment_id)
        if existing:
            return {'assessment_id': existing['id'], 'unchanged': True}
        detail = self.app.candidate_detail(candidate_id)
        profile = {key: value for key, value in detail.items()
                   if key not in ('assessment', 'assessment_stale', 'research_runs', 'notes')}
        result = self.models.evaluate(profile)
        # Validate citation IDs even for custom model implementations.
        allowed = {e['id'] for e in profile['evidence']}
        citations = result['evidence_ids'] + [i for criterion in result['criteria'] for i in criterion['evidence_ids']]
        if not set(citations) <= allowed:
            raise ValueError('Unknown evidence IDs in assessment')
        result.update(id=assessment_id, candidate_id=candidate_id, profile_version=profile['profile_version'],
                      criteria_version='htgf-sourcing-v1', is_demo=self.settings.mode == 'demo',
                      created_at=now(), profile_snapshot=profile)
        self.store.put('assessments', result)
        self.store.event('candidate.evaluated', candidate_id, {'assessment_id': result['id']})
        return {'assessment_id': result['id'], 'profile_version': profile['profile_version']}

    def research(self, candidate_id, job_id):
        record_id = f'research:{job_id}'
        existing = self.store.get('research_runs', record_id)
        if existing:
            return existing
        candidate = self.app.candidate_detail(candidate_id)
        result = self.models.research(candidate)
        result.update(id=record_id, candidate_id=candidate_id, created_at=now(),
                      is_demo=self.settings.mode == 'demo', imported_finding_ids=[], fetch_errors=[])
        if self.settings.mode == 'live':
            for source in result['sources'][:5]:
                try:
                    host = urlparse(source['url']).hostname
                    body = fetch(source['url'], [host])
                    # Store original fetched text, never the model's research summary as fact.
                    source_id = 'research:'+host
                    if not self.store.get('sources', source_id):
                        self.store.put('sources', dict(id=source_id, name=host, url=source['url'], kind='manual',
                            allowed_hosts=[host], enabled=False, is_demo=False, created_at=now(), updated_at=now()))
                    finding = self.app.import_finding(dict(source_id=source_id, url=source['url'],
                        title=source['title'], text=text_from_html(body)))
                    result['imported_finding_ids'].append(finding['id'])
                    self.app.queue('process', finding['id'])
                except Exception as exc:
                    result['fetch_errors'].append(dict(url=source['url'], error=type(exc).__name__))
        self.store.put('research_runs', result)
        self.store.event('research.completed', candidate_id, {'research_id': record_id})
        return result

    def search(self, search_id, job_id):
        search = self.app.require('searches', search_id)
        selected = search['source_ids'] or [s['id'] for s in self.store.list('sources') if s['enabled']]
        imported, jobs, errors = [], [], []
        for source_id in selected[:10]:
            source = self.app.require('sources', source_id)
            try:
                if source['kind'] == 'manual':
                    findings = [f for f in self.store.list('findings') if f['source_id'] == source_id]
                elif self.settings.mode == 'demo':
                    raise ValueError('External fetching disabled in demo mode')
                else:
                    findings = [self.app.import_finding(dict(source_id=source_id, **item)) for item in collect(source, limit=10)]
                for finding in findings[:max(0, 30-len(imported))]:
                    imported.append(finding['id'])
                    jobs.append(self.app.queue('process', finding['id'])['id'])
            except Exception as exc:
                errors.append(dict(source_id=source_id, error=type(exc).__name__))
        interval = search['interval_minutes']
        search.update(last_job_id=job_id, finding_ids=imported, updated_at=now(),
            next_run_at=(datetime.now(timezone.utc)+timedelta(minutes=interval)).isoformat() if interval else None)
        self.store.put('searches', search)
        if errors and not imported:
            raise RuntimeError('All selected source fetches failed')
        return dict(finding_ids=imported, child_job_ids=jobs, source_errors=errors,
                    scope='Configured-source collection; prompt is saved context, not yet semantic discovery.')

    def schedule(self):
        clock = now()
        for search in self.store.list('searches'):
            if search.get('interval_minutes') and (not search.get('next_run_at') or search['next_run_at'] <= clock):
                self.app.queue('search', search['id'])

    def run_once(self):
        # One serial writer for this graph/group. Heartbeat also protects long model calls.
        owner = uid()
        lock_name = 'pipeline:'+self.settings.group_id
        if not self.store.acquire(lock_name, owner, self.settings.lease_seconds):
            return False
        self.store.put('runtime', dict(id='worker', last_seen_at=now(), mode=self.settings.mode))
        job = None
        stop_heartbeat = threading.Event()
        def renew():
            while not stop_heartbeat.wait(max(1, self.settings.lease_seconds/3)):
                try:
                    if not self.store.acquire(lock_name, owner, self.settings.lease_seconds):
                        log.error('Pipeline lease lost')
                        return
                    if job:
                        self.store.heartbeat(job, self.settings.lease_seconds)
                except Exception:
                    log.exception('Lease renewal failed')
        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        try:
            self.schedule()
            job = self.store.claim(self.settings.lease_seconds)
            if not job:
                return False
            try:
                kind, record_id = job['kind'], job['payload']['id']
                if kind == 'process':
                    result = self.process(record_id)
                elif kind == 'evaluate':
                    result = self.evaluate(record_id, job['id'])
                elif kind == 'research':
                    result = self.research(record_id, job['id'])
                elif kind == 'search':
                    result = self.search(record_id, job['id'])
                else:
                    raise ValueError('Unknown job kind')
                self.store.finish(job, result=result)
            except Exception as exc:
                # Full provider errors may contain request/source contents. Public error is bounded.
                error = f'{type(exc).__name__}: Verarbeitung fehlgeschlagen. Konfiguration und Worker prüfen.'
                self.store.finish(job, error=error)
                self.store.event('job.error', job['id'], {'error_type': type(exc).__name__})
                log.error('Job %s failed: %s', job['id'], type(exc).__name__)
            return True
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=2)
            self.store.release(lock_name, owner)

    def run(self, stop=None):
        stop = stop or threading.Event()
        try:
            while not stop.is_set():
                if not self.run_once():
                    stop.wait(1)
        finally:
            self.bridge.close()
