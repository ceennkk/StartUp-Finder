"""Persistent jobs, lease renewal, retries and incremental ingestion."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import logging
import json
import threading
import time
import html
import re
import unicodedata
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5
from .candidates import materialize
from .clients import GraphBridge, OpenAIDecisionRelevance, OpenAIModels
from .fetching import collect, fetch, text_from_html
from .graph import Finding
from .ranking import (CRITERIA_VERSION, FUNDING_CLASSIFICATION_VERSION,
                      is_current_assessment, score_assessment)
from .store import now, uid

log = logging.getLogger(__name__)


def _quote_key(value):
    value = unicodedata.normalize('NFKC', html.unescape(value or '')).casefold()
    return ' '.join(value.split())


def _url_key(value):
    parsed = urlparse(value or '')
    return (parsed.hostname or '').casefold(), parsed.path.rstrip('/'), parsed.query


class Worker:
    def __init__(self, app, bridge=None, models=None):
        self.app, self.store, self.settings = app, app.store, app.settings
        self.bridge = bridge or GraphBridge(self.settings)
        self.models = models or OpenAIModels(self.settings)
        self._next_adapter_sync = 0.0
        self._next_assessment_sweep = 0.0

    def screen_relevance(self, finding):
        """Use Decisions for the gate and require a source quote before graph ingestion."""
        import asyncio
        import hashlib
        import json
        external_id = finding.get('external_id') or finding['id']
        decision_context = finding.get('decision_context') or finding['text']
        context_hash = hashlib.sha256(json.dumps(decision_context, ensure_ascii=False).encode()).hexdigest()
        cached = self.store.get('graph_relevance', external_id)
        if cached and cached.get('context_hash') == context_hash:
            relevant = bool(cached.get('relevant'))
            finding.update(candidate_relevance_checked=True,
                candidate_relevance={key: cached.get(key) for key in
                    ('candidate_name', 'evidence_type', 'evidence_quote', 'reason', 'model')})
            if not relevant:
                finding.update(status='excluded_irrelevant', updated_at=now())
            self.store.put('findings', finding)
            return relevant

        gate = OpenAIDecisionRelevance(self.settings, max_concurrency=1)
        loop = asyncio.new_event_loop()
        try:
            decisions = loop.run_until_complete(gate.classify_all([[{
                'external_id': external_id, 'decision_context': decision_context}]]))
        finally:
            loop.run_until_complete(gate.close())
            loop.close()
        decision = decisions[0][0]
        if decision['relevant']:
            context = finding.get('relevance_context') or {
                'source': finding.get('source_id', ''), 'record_type': 'finding',
                'title': finding['title'],
                'content': {'source_text': finding['text']},
            }
            checked = self.models.classify_candidate_relevance([{
                'id': external_id, 'context': context}])[0]
            decision.update(relevant=checked['relevant'],
                evidence_type=checked['evidence_type'], candidate_name=checked['candidate_name'],
                evidence_quote=checked['evidence_quote'], reason=checked['reason'],
                validator_model=checked['model'])
        else:
            decision.update(evidence_type='irrelevant', candidate_name='', evidence_quote='')
        decision.update(id=external_id, finding_id=finding['id'], context_hash=context_hash,
                        source_name=finding.get('source_id', ''),
                        status='relevant' if decision['relevant'] else 'excluded', updated_at=now())
        self.store.put('graph_relevance', decision)
        finding.update(candidate_relevance_checked=True,
            candidate_relevance={key: decision.get(key) for key in
                ('candidate_name', 'evidence_type', 'evidence_quote', 'reason', 'model')},
            updated_at=now())
        if not decision['relevant']:
            finding.update(status='excluded_irrelevant', candidate_ids=[])
        self.store.put('findings', finding)
        return bool(decision['relevant'])

    def process(self, finding_id):
        finding = self.app.require('findings', finding_id)
        if finding['status'] == 'processed':
            return dict(candidate_ids=finding.get('candidate_ids', []), unchanged=True)
        if finding.get('status') in ('excluded_irrelevant', 'excluded_no_startup_entity'):
            return dict(candidate_ids=[], excluded=True, reason='candidate_relevance')
        if not finding.get('candidate_relevance_checked'):
            if not self.screen_relevance(finding):
                return dict(candidate_ids=[], excluded=True, reason='candidate_relevance')
            finding = self.app.require('findings', finding_id)
        receipt = finding.get('graph_receipt')
        if not receipt:
            value = Finding.from_dict({**finding, 'id': finding['external_id']})
            wrapped = SimpleNamespace(**value.__dict__, episode_id=value.episode_id)
            receipt = self.bridge.ingest(wrapped)
            finding.update(graph_receipt=receipt, status='graph_processed', updated_at=now())
            self.store.put('findings', finding)
        ids = materialize(self.app, finding, receipt, graph_group_id=self.settings.group_id)
        return dict(candidate_ids=ids, episode_id=receipt['episode_id'])

    def evaluate(self, candidate_id, job_id):
        assessment_id = f'assessment:{job_id}'
        existing = self.store.get('assessments', assessment_id)
        if existing:
            return {'assessment_id': existing['id'], 'unchanged': True}
        detail = self.app.candidate_detail(candidate_id)
        current_assessment = detail.get('assessment')
        if is_current_assessment(current_assessment, detail.get('profile_version')):
            return {'assessment_id': current_assessment['id'], 'unchanged': True}
        profile = {key: value for key, value in detail.items()
                   if key not in ('assessment', 'assessment_stale', 'research_runs', 'notes')}
        financing_evidence_ids = set(profile.get('funding_evidence_ids') or [])
        evaluation_profile = {key: value for key, value in profile.items()
            if key not in ('finance', 'eligibility', 'funding_status', 'funding_type', 'funding_summary',
                           'funding_evidence_ids', 'funding_classification_version')}
        evaluation_profile['evidence'] = [item for item in profile['evidence']
            if item.get('id') not in financing_evidence_ids]
        if 'signals' in evaluation_profile:
            evaluation_profile['signals'] = [item for item in profile['signals']
                if item.get('kind') != 'funding']
        if isinstance(evaluation_profile.get('research_profile'), dict):
            research_profile = dict(evaluation_profile['research_profile'])
            research_profile['claims'] = [claim for claim in research_profile.get('claims', [])
                if claim.get('field') not in ('funding', 'funding_round')]
            evaluation_profile['research_profile'] = research_profile
        reused = bool(current_assessment and
                      current_assessment.get('profile_version') == profile.get('profile_version'))
        if reused:
            # A scoring-policy change needs no new LLM call: append a new score
            # while preserving the existing evidence-backed assessment.
            result = json.loads(json.dumps(current_assessment))
        else:
            result = self.models.evaluate(evaluation_profile)
            # Validate citation IDs even for custom model implementations.
            allowed = {e['id'] for e in evaluation_profile['evidence']}
            citations = result['evidence_ids'] + [i for criterion in result['criteria'] for i in criterion['evidence_ids']]
            if not set(citations) <= allowed:
                raise ValueError('Unknown evidence IDs in assessment')
        result.update(id=assessment_id, candidate_id=candidate_id, profile_version=profile['profile_version'],
                      criteria_version=CRITERIA_VERSION,
                      created_at=now(), profile_snapshot=profile)
        equity_assessment = self._equity_assessment(candidate_id, profile)
        eligibility_assessment = self._eligibility_assessment(candidate_id, profile)
        score_assessment(result, profile.get('funding_status'),
                         profile.get('funding_type'), equity_assessment, eligibility_assessment)
        if equity_assessment is not None:
            result['equity_assessment'] = equity_assessment
        if eligibility_assessment is not None:
            result['eligibility_assessment'] = eligibility_assessment
        self.store.put('assessments', result)
        self.store.event('candidate.reranked' if reused else 'candidate.evaluated', candidate_id,
                         {'assessment_id': result['id']})
        return {'assessment_id': result['id'], 'profile_version': profile['profile_version'],
                'model_reused': reused}

    @staticmethod
    def _equity_assessment(candidate_id, profile):
        """Re-validate the stored finance snapshot before it affects ranking."""
        finance = profile.get('finance')
        if not finance:
            return None
        if finance.get('candidate_id') != candidate_id:
            raise ValueError('Finance snapshot belongs to another candidate')
        from app.finance.assessment import assess_equity
        assessed = assess_equity(
            candidate_id=candidate_id,
            as_of=date.fromisoformat(finance['as_of']),
            findings=finance.get('findings', []),
            events=finance.get('events', []),
            coverage=finance.get('coverage'),
        )
        return assessed.model_dump(mode='json')

    @staticmethod
    def _eligibility_assessment(candidate_id, profile):
        """Recompute the validated eligibility result from its stored input."""
        snapshot = profile.get('eligibility')
        if not snapshot:
            return None
        if snapshot.get('candidate_id') != candidate_id:
            raise ValueError('Eligibility snapshot belongs to another candidate')
        from app.htgf.assessment import assess
        return assess(snapshot['assessment_input'])

    def research(self, candidate_id, job_id, requested_profile_version=None):
        record_id = f'research:{job_id}'
        existing = self.store.get('research_runs', record_id)
        if existing:
            return existing
        candidate = self.app.candidate_detail(candidate_id)
        if requested_profile_version is not None and requested_profile_version != candidate.get('profile_version'):
            return {'id': record_id, 'candidate_id': candidate_id, 'status': 'stale_profile_skipped',
                    'requested_profile_version': requested_profile_version,
                    'current_profile_version': candidate.get('profile_version')}
        candidate_record = self.store.get('candidates', candidate_id)
        if (candidate_record.get('enrichment_status') == 'completed'
                and candidate_record.get('enrichment_profile_version') == candidate_record.get('profile_version')
                and candidate_record.get('funding_classification_version') == FUNDING_CLASSIFICATION_VERSION):
            return {'id': record_id, 'candidate_id': candidate_id, 'status': 'already_current'}
        candidate_record['enrichment_status'] = 'running'
        self.store.put('candidates', candidate_record)
        result = self.models.research(candidate)
        result.update(id=record_id, candidate_id=candidate_id, created_at=now(),
                      imported_finding_ids=[], fetch_errors=[], verified_claims=[])
        fetched_sources = {}
        for source in result['sources'][:8]:
            try:
                host = urlparse(source['url']).hostname
                body = fetch(source['url'], [host])
                original_text = text_from_html(body)
                source_id = 'research:'+host
                if not self.store.get('sources', source_id):
                    self.store.put('sources', dict(id=source_id, name=host, url=source['url'], kind='manual',
                        allowed_hosts=[host], enabled=False, created_at=now(), updated_at=now()))
                finding = self.app.import_finding(dict(source_id='research:'+host,
                    url=source['url'], title=source['title'], text=original_text[:200000]))
                fetched_sources[_url_key(source['url'])] = dict(
                    source=source, finding=finding, text=original_text)
                result['imported_finding_ids'].append(finding['id'])
                if finding.get('status') not in ('processed', 'excluded_irrelevant'):
                    self.app.queue('process', finding['id'])
            except Exception as exc:
                result['fetch_errors'].append(dict(url=source['url'], error=type(exc).__name__))

        valid_source_keys = {_url_key(source['url']) for source in result['sources']}
        for claim in result.get('claims', []):
            if _url_key(claim.get('source_url')) not in valid_source_keys:
                continue
            fetched = fetched_sources.get(_url_key(claim.get('source_url')))
            quote = claim.get('evidence_quote', '').strip()
            if not fetched or len(quote) < 12 or _quote_key(quote) not in _quote_key(fetched['text']):
                continue
            claim['evidence_quote'] = quote
            claim['finding_id'] = fetched['finding']['id']
            claim['source_title'] = fetched['source']['title']
            claim['evidence_id'] = str(uuid5(NAMESPACE_URL,
                f'{candidate_id}:{record_id}:{claim["field"]}:{claim["source_url"]}:{quote}'))
            claim['verified'] = True
            result['verified_claims'].append(claim)

        funding_claims = [claim for claim in result['verified_claims']
                         if claim['field'] in ('funding', 'funding_round')]
        requested_status = result.get('funding_status', 'unclear')
        if requested_status == 'confirmed' and funding_claims:
            funding_status = 'confirmed'
            funding_summary = '; '.join(dict.fromkeys(claim['value'] for claim in funding_claims))
        elif requested_status == 'not_found' and len(fetched_sources) >= 3:
            funding_status = 'not_found'
            funding_summary = ('In den recherchierten öffentlichen Quellen wurde kein '
                'Finanzierungsnachweis gefunden. Das belegt nicht, dass keine Finanzierung besteht.')
        else:
            funding_status = 'unclear'
            funding_summary = ('Der Finanzierungsstatus ließ sich aus den verfügbaren '
                'öffentlichen Quellen nicht sicher bestimmen.')

        funding_natures = {claim.get('funding_nature', 'unclear') for claim in funding_claims}
        if funding_status == 'not_found':
            funding_type = 'not_applicable'
        elif funding_status != 'confirmed' or not funding_claims:
            funding_type = 'unclear'
        elif 'dilutive' in funding_natures or 'mixed' in funding_natures:
            funding_type = ('mixed' if 'non_dilutive' in funding_natures or 'mixed' in funding_natures
                            else 'dilutive')
        elif 'unclear' in funding_natures:
            funding_type = 'unclear'
        elif funding_natures == {'non_dilutive'}:
            funding_type = 'non_dilutive'
        else:
            funding_type = 'unclear'

        summary_lines = [f'Finanzierung: {funding_summary}', f'Finanzierungsart: {funding_type}']
        if result['verified_claims']:
            summary_lines.append('Belegte Recherchefunde:')
            summary_lines.extend(f"- {claim['field']}: {claim['value']}" for claim in result['verified_claims'][:8])
        else:
            summary_lines.append('Keine Modellangaben konnten durch wörtliche Zitate der abgerufenen Originalseiten bestätigt werden.')
        result['summary'] = '\n'.join(summary_lines)
        result['funding_status'] = funding_status
        result['funding_type'] = funding_type
        result['funding_classification_version'] = FUNDING_CLASSIFICATION_VERSION
        result['funding_summary'] = funding_summary
        result['source_fetch_count'] = len(fetched_sources)

        with self.store.transaction() as connection:
            current = self.app.require('candidates', candidate_id, connection)
            previous_version = current.get('profile_version', 0)
            for claim in result['verified_claims']:
                source = fetched_sources[_url_key(claim['source_url'])]
                self.store.put('evidence', dict(id=claim['evidence_id'], candidate_id=candidate_id,
                    finding_id=claim['finding_id'], episode_id=None, url=claim['source_url'],
                    title=claim['source_title'], quote=claim['evidence_quote'], kind='exact_quote',
                    attribution='Zitat wurde im abgerufenen Originaltext gefunden; Recherchemodell ordnete es diesem Feld zu.',
                    published_at=None, fetched_at=now(), created_at=now()), connection)
            profile = dict(current.get('research_profile') or {})
            profile.update(claims=result['verified_claims'], funding_status=funding_status,
                funding_type=funding_type,
                funding_classification_version=FUNDING_CLASSIFICATION_VERSION,
                funding_summary=funding_summary, sources=result['sources'], updated_at=now())
            current['research_profile'] = profile
            current['funding_status'] = funding_status
            current['funding_type'] = funding_type
            current['funding_classification_version'] = FUNDING_CLASSIFICATION_VERSION
            current['funding_summary'] = funding_summary
            current['funding_evidence_ids'] = [claim['evidence_id'] for claim in funding_claims]
            current['enrichment_status'] = 'completed'
            current['last_researched_at'] = now()
            for claim in result['verified_claims']:
                field, value = claim['field'], claim['value']
                if field in ('description', 'product') and value:
                    if not current.get('description'):
                        current['description'] = value
                elif field == 'website' and value.startswith(('http://', 'https://')):
                    current['website'] = value
                elif field == 'location' and value and not current.get('location'):
                    current['location'] = value
                elif field == 'team' and value:
                    current['people'] = sorted(set(current.get('people', []) + [value]))
                if field in ('funding', 'funding_round'):
                    signal_id = str(uuid5(NAMESPACE_URL, f'{claim["evidence_id"]}:funding'))
                    signal = dict(id=signal_id, kind='funding', label=value,
                        evidence_id=claim['evidence_id'], date=None, verification='quote_verified_web_research')
                    current['signals'] = list({item['id']: item for item in
                        current.get('signals', []) + [signal]}.values())
            if current != self.app.require('candidates', candidate_id, connection):
                current['profile_version'] = previous_version + 1
                current['updated_at'] = now()
            current['enrichment_profile_version'] = current['profile_version']
            self.store.put('candidates', current, connection)
            if current['profile_version'] != previous_version:
                self.store.enqueue('evaluate', {'id': candidate_id},
                    f'evaluate:{candidate_id}:{current["profile_version"]}', connection)
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
        # Collector adapters write raw source_records. Periodically bridge new
        # and changed records into the normal process queue; the worker then
        # delegates graph extraction and identity resolution to Graphiti/LLMs.
        if self.store.postgres and time.monotonic() >= self._next_adapter_sync:
            self._next_adapter_sync = time.monotonic() + 60
            try:
                from .adapter_bridge import import_adapter_records
                result = import_adapter_records(self.app, limit=1000)
                log.info("Adapter source sync: read=%d queued=%d skipped=%d errors=%d",
                         result['read'], result['imported'], result['skipped'], len(result['errors']))
            except Exception as exc:
                log.warning("Adapter source sync failed: %s", type(exc).__name__)
        clock = now()
        for search in self.store.list('searches'):
            if search.get('interval_minutes') and (not search.get('next_run_at') or search['next_run_at'] <= clock):
                self.app.queue('search', search['id'])

        # Backfill missing and stale assessments for every candidate, including
        # profiles that existed before automatic evaluation was introduced.
        # The normal queue deduplicates active work; a fresh sweep also retries
        # candidates whose previous evaluation job exhausted its retries.
        if time.monotonic() >= self._next_assessment_sweep:
            self._next_assessment_sweep = time.monotonic() + 60
            for candidate in self.app.list_candidates({}):
                enrichment_status = candidate.get('enrichment_status')
                research_due = (enrichment_status in (None, 'pending', 'not_researched', 'failed')
                    or candidate.get('funding_classification_version') != FUNDING_CLASSIFICATION_VERSION
                    or (enrichment_status == 'completed'
                        and candidate.get('enrichment_profile_version') != candidate.get('profile_version')))
                if research_due:
                    self.app.queue('research', candidate['id'])
                    current = self.store.get('candidates', candidate['id'])
                    if current and current.get('enrichment_status') not in ('running', 'queued'):
                        current.update(enrichment_status='queued',
                            enrichment_requested_profile_version=current.get('profile_version'))
                        self.store.put('candidates', current)
                if not is_current_assessment(candidate.get('assessment'), candidate.get('profile_version')):
                    self.app.queue('evaluate', candidate['id'])

    def run_once(self):
        # One serial writer for this graph/group. Heartbeat also protects long model calls.
        owner = uid()
        lock_name = 'pipeline:'+self.settings.group_id
        if not self.store.acquire(lock_name, owner, self.settings.lease_seconds):
            return False
        self.store.put('runtime', dict(id='worker', last_seen_at=now(), mode='live'))
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
                    result = self.research(record_id, job['id'], job['payload'].get('profile_version'))
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
                if job['kind'] == 'research':
                    candidate = self.store.get('candidates', job['payload']['id'])
                    if candidate:
                        candidate.update(enrichment_status='failed', enrichment_error=type(exc).__name__,
                                         updated_at=now())
                        self.store.put('candidates', candidate)
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
