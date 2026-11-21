"""Application services shared by HTTP handlers and background workers."""
import json
import hashlib
import logging
import threading
from datetime import date
from urllib.parse import urlparse
from .graph import Finding
from .ranking import is_current_assessment, is_current_rank
from .store import now, uid

log = logging.getLogger(__name__)


class NotFound(Exception):
    pass


class ChatUnavailable(Exception):
    pass


LEGACY_GRAPH_GROUP = 'startup_finder_de'


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
        self._chat_lock = threading.Lock()
        self._chat_graph = None
        self._chat_model = None

    def require(self, kind, record_id, connection=None):
        record = self.store.get(kind, record_id, connection)
        if not record:
            raise NotFound(f'{kind} record not found')
        return record

    def capabilities(self):
        return dict(mode='live',
            database='postgresql', graph_provider='graphiti',
            decision_provider=self.settings.decision_provider,
            features=['sources', 'findings', 'graph', 'candidates', 'research', 'assessments', 'finance_review',
                      'shortlist', 'notes', 'searches', 'jobs', 'retry', 'events', 'scheduling', 'grounded_chat'],
            adapters=['html', 'rss', 'manual'], live_research=True,
            deployment_note='Loopback development may omit API token; remote binds require one. No multi-tenant authorization.')

    def create_source(self, data):
        url = http_url(text(data, 'url', 2000))
        kind = data.get('kind', 'html')
        if kind not in ('html', 'rss', 'manual'):
            raise ValueError('kind must be html, rss or manual')
        return self.store.put('sources', dict(id=uid(), name=text(data, 'name', 200), url=url,
            kind=kind, enabled=True, allowed_hosts=[urlparse(url).hostname.lower()],
            created_at=now(), updated_at=now()))

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
            status='new', graph_receipt=None, created_at=now(), updated_at=now())
        if isinstance(data.get('decision_context'), str):
            record['decision_context'] = data['decision_context']
        if isinstance(data.get('relevance_context'), dict):
            record['relevance_context'] = data['relevance_context']
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
        snapshot_id = candidate.get('finance_snapshot_id')
        candidate['finance'] = (self.store.get('finance_assessments', snapshot_id)
                                if snapshot_id else None)
        eligibility_id = candidate.get('eligibility_snapshot_id')
        candidate['eligibility'] = (self.store.get('eligibility_assessments', eligibility_id)
                                    if eligibility_id else None)
        candidate['evidence'] = [e for e in self.store.list('evidence') if e['candidate_id'] == record_id]
        candidate['notes'] = sorted([n for n in self.store.list('notes') if n['candidate_id'] == record_id], key=lambda n:n['created_at'])
        assessments = sorted([a for a in self.store.list('assessments') if a['candidate_id'] == record_id], key=lambda a:a['created_at'], reverse=True)
        candidate['assessment'] = assessments[0] if assessments else None
        candidate['assessment_stale'] = bool(assessments and assessments[0]['profile_version'] != candidate['profile_version'])
        candidate['assessment_current'] = is_current_assessment(candidate['assessment'], candidate['profile_version'])
        candidate['assessment_rankable'] = is_current_rank(candidate['assessment'],
            candidate['assessment'].get('profile_version') if candidate['assessment'] else None,
            candidate['profile_version'])
        candidate['research_runs'] = sorted([r for r in self.store.list('research_runs') if r['candidate_id'] == record_id], key=lambda r:r['created_at'], reverse=True)
        return candidate

    def candidate_finance(self, record_id):
        candidate = self.require('candidates', record_id)
        snapshots = [row for row in self.store.list('finance_assessments')
                     if row.get('candidate_id') == record_id]
        snapshots.sort(key=lambda row: (row.get('created_at', ''), row['id']), reverse=True)
        current = next((row for row in snapshots
                        if row['id'] == candidate.get('finance_snapshot_id')), None)
        history = [{key: row.get(key) for key in
                    ('id', 'as_of', 'equity_assessment', 'reviewers', 'created_at')}
                   for row in snapshots]
        return {'candidate_id': record_id, 'current': current, 'history': history}

    def save_candidate_finance(self, record_id, data):
        """Persist a validated, append-only finance snapshot and queue re-ranking."""
        if set(data) - {'as_of', 'events', 'findings', 'coverage'}:
            raise ValueError('Allowed fields: as_of, events, findings, coverage')
        if not isinstance(data.get('as_of'), str):
            raise ValueError('as_of must be an ISO date')
        as_of = date.fromisoformat(data['as_of'])
        raw_events, raw_findings = data.get('events', []), data.get('findings', [])
        if not isinstance(raw_events, list) or not isinstance(raw_findings, list):
            raise ValueError('events and findings must be arrays')
        from app.finance.models import EquityFinding, FinancialSupportEvent, SearchCoverage
        events = [FinancialSupportEvent.model_validate(item) for item in raw_events]
        findings = [EquityFinding.model_validate(item) for item in raw_findings]
        coverage = (SearchCoverage.model_validate(data['coverage'])
                    if data.get('coverage') is not None else None)
        from app.finance.assessment import assess_equity
        assessed = assess_equity(record_id, as_of, findings, events, coverage)
        normalized = {
            'as_of': as_of.isoformat(),
            'events': [item.model_dump(mode='json') for item in events],
            'findings': [item.model_dump(mode='json') for item in findings],
            'coverage': coverage.model_dump(mode='json') if coverage else None,
        }
        content_hash = hashlib.sha256(json.dumps(
            normalized, sort_keys=True, ensure_ascii=False, separators=(',', ':')
        ).encode()).hexdigest()
        reviewers = sorted({item.review.reviewer for item in findings if item.review})
        if coverage:
            reviewers = sorted(set(reviewers) | {coverage.review.reviewer})
        snapshot = dict(
            id=uid(), candidate_id=record_id, as_of=as_of.isoformat(),
            events=normalized['events'], findings=normalized['findings'],
            coverage=normalized['coverage'],
            equity_assessment=assessed.model_dump(mode='json'),
            reviewers=reviewers, content_hash=content_hash, created_at=now(),
        )
        with self.store.transaction() as connection:
            candidate = self.require('candidates', record_id, connection)
            current_id = candidate.get('finance_snapshot_id')
            current = self.store.get('finance_assessments', current_id, connection) if current_id else None
            if current and current.get('content_hash') == content_hash:
                return {'finance': current, 'job': None, 'unchanged': True}
            snapshot['version'] = (current.get('version', 0) if current else 0) + 1
            self.store.put('finance_assessments', snapshot, connection)
            previous_profile_version = candidate.get('profile_version', 0)
            candidate.update(finance_snapshot_id=snapshot['id'],
                profile_version=previous_profile_version + 1, updated_at=now())
            self.store.put('candidates', candidate, connection)
            self.store.event('candidate.finance_updated', record_id, {
                'finance_snapshot_id': snapshot['id'],
                'equity_status': assessed.status.value,
                'reviewers': reviewers,
            }, connection)
            job = self.store.enqueue('evaluate', {'id': record_id},
                f'evaluate:{record_id}:{candidate["profile_version"]}', connection)
        return {'finance': snapshot, 'job': job, 'unchanged': False}

    def candidate_eligibility(self, record_id):
        candidate = self.require('candidates', record_id)
        snapshots = [row for row in self.store.list('eligibility_assessments')
                     if row.get('candidate_id') == record_id]
        snapshots.sort(key=lambda row: (row.get('created_at', ''), row['id']), reverse=True)
        current = next((row for row in snapshots
                        if row['id'] == candidate.get('eligibility_snapshot_id')), None)
        history = [{key: row.get(key) for key in
                    ('id', 'version', 'assessment_date', 'reviewer', 'assessment_result', 'created_at')}
                   for row in snapshots]
        return {'candidate_id': record_id, 'current': current, 'history': history}

    def save_candidate_eligibility(self, record_id, data):
        """Validate and persist an evidence-backed HTGF eligibility snapshot."""
        allowed = {'assessment_date', 'technology', 'company_age', 'germany', 'reviewer'}
        if set(data) != allowed:
            raise ValueError('Required fields: assessment_date, technology, company_age, germany, reviewer')
        reviewer = data.get('reviewer')
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200:
            raise ValueError('reviewer must be a nonempty label, maximum 200 characters')
        with self.store.transaction() as connection:
            candidate = self.require('candidates', record_id, connection)
            assessment_input = {
                'candidate_id': record_id,
                'name': candidate['name'],
                'assessment_date': data['assessment_date'],
                'technology': data['technology'],
                'company_age': data['company_age'],
                'germany': data['germany'],
            }
            from app.htgf.assessment import assess
            assessment_result = assess(assessment_input)
            normalized = {'assessment_input': assessment_input, 'reviewer': reviewer.strip()}
            content_hash = hashlib.sha256(json.dumps(
                normalized, sort_keys=True, ensure_ascii=False, separators=(',', ':')
            ).encode()).hexdigest()
            current_id = candidate.get('eligibility_snapshot_id')
            current = self.store.get('eligibility_assessments', current_id, connection) if current_id else None
            if current and current.get('content_hash') == content_hash:
                return {'eligibility': current, 'job': None, 'unchanged': True}
            snapshot = dict(
                id=uid(), candidate_id=record_id,
                version=(current.get('version', 0) if current else 0) + 1,
                assessment_input=assessment_input, assessment_date=data['assessment_date'],
                assessment_result=assessment_result, reviewer=reviewer.strip(),
                content_hash=content_hash, created_at=now(),
            )
            self.store.put('eligibility_assessments', snapshot, connection)
            candidate.update(eligibility_snapshot_id=snapshot['id'],
                profile_version=candidate.get('profile_version', 0) + 1, updated_at=now())
            self.store.put('candidates', candidate, connection)
            self.store.event('candidate.eligibility_updated', record_id, {
                'eligibility_snapshot_id': snapshot['id'],
                'eligibility_status': assessment_result['htgf_eligibility_status'],
                'reviewer': reviewer.strip(),
            }, connection)
            job = self.store.enqueue('evaluate', {'id': record_id},
                f'evaluate:{record_id}:{candidate["profile_version"]}', connection)
        return {'eligibility': snapshot, 'job': job, 'unchanged': False}

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
        return self.store.put('searches', dict(id=uid(), prompt=prompt, source_ids=ids,
            interval_minutes=interval, next_run_at=None, last_job_id=None, created_at=now(), updated_at=now()))

    def list_candidates(self, query):
        rows = [candidate for candidate in self.store.list('candidates')
                if candidate.get('graph_group_id', LEGACY_GRAPH_GROUP) == self.settings.group_id]
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
            row['assessment_current'] = is_current_assessment(row['assessment'], row['profile_version'])
            row['assessment_rankable'] = is_current_rank(row['assessment'],
                row['assessment'].get('profile_version') if row['assessment'] else None,
                row['profile_version'])
        if query.get('priority'):
            rows = [r for r in rows if r['assessment_current'] and r['assessment']['priority'] == query['priority']]
        rows.sort(key=lambda r: (0 if r['assessment_rankable'] else 1 if r['assessment_current'] else 2,
            -(r['assessment']['score'] or 0) if r['assessment_rankable'] else 0,
            r['name'].casefold()))
        return rows

    def graph(self):
        nodes = [node for node in self.store.list('graph_nodes')
                 if node.get('group_id', LEGACY_GRAPH_GROUP) == self.settings.group_id]
        edges = [edge for edge in self.store.list('graph_edges')
                 if edge.get('group_id', LEGACY_GRAPH_GROUP) == self.settings.group_id]
        return dict(nodes=nodes, edges=edges, mode='live', is_materialized_view=True,
                    source='graphiti_projection')

    def answer_question(self, question, language='en', history=None, candidate_id=None):
        if not isinstance(question, str) or not question.strip() or len(question) > 1200:
            raise ValueError('question must contain 1..1200 characters')
        if language not in ('en', 'de'):
            raise ValueError('language must be en or de')
        if candidate_id is not None and (not isinstance(candidate_id, str) or len(candidate_id) > 100):
            raise ValueError('candidate_id must be a string of at most 100 characters')
        history = [] if history is None else history
        if not isinstance(history, list) or len(history) > 8:
            raise ValueError('history must contain at most 8 turns')
        clean_history = []
        for turn in history:
            if (not isinstance(turn, dict) or turn.get('role') not in ('user', 'assistant')
                    or not isinstance(turn.get('content'), str) or not turn['content'].strip()
                    or len(turn['content']) > 1200):
                raise ValueError('history turns require role and content')
            clean_history.append({'role': turn['role'], 'content': turn['content'].strip()})
        with self._chat_lock:
            try:
                from .clients import GraphBridge, OpenAIModels
                if self._chat_graph is None:
                    self._chat_graph = GraphBridge(self.settings)
                    self._chat_model = OpenAIModels(self.settings)
            except Exception as exc:
                log.error('Candidate chat provider initialization failed (%s)', type(exc).__name__)
                raise ChatUnavailable('Chat providers are unavailable') from None
            try:
                selected_name = self.require('candidates', candidate_id)['name'] if candidate_id else None

                def graph_tool(arguments):
                    query = arguments.get('query', '')
                    if not isinstance(query, str) or not query.strip() or len(query) > 500:
                        raise ValueError('Graph search query must contain 1..500 characters')
                    retrieval_query = f'{selected_name}. {query}' if selected_name else query
                    try:
                        result_edges = self._chat_graph.search(retrieval_query[:700])
                    except Exception as exc:
                        log.error('Candidate chat graph retrieval failed (%s)', type(exc).__name__)
                        raise
                    projection = self.graph()
                    nodes = {node['id']: node for node in projection['nodes']}
                    facts, citations = [], []
                    for edge in result_edges[:10]:
                        edge_id = str(getattr(edge, 'uuid', '') or '')
                        fact = str(getattr(edge, 'fact', '') or '').strip()[:1000]
                        if not edge_id or not fact:
                            continue
                        source_id = str(getattr(edge, 'source_node_uuid', '') or '')
                        target_id = str(getattr(edge, 'target_node_uuid', '') or '')
                        source = nodes.get(source_id, {}).get('name', source_id)
                        target = nodes.get(target_id, {}).get('name', target_id)
                        relation = str(getattr(edge, 'name', '') or 'related to')
                        citation = dict(id=f'graph:{edge_id}', kind='Knowledge graph',
                            title=f'{source} · {relation} · {target}', quote=fact,
                            url=None, candidate_id=None)
                        citations.append(citation)
                        facts.append(dict(source=source, relation=relation, target=target,
                                          fact=fact, citation_id=citation['id']))
                    return {'data': {'facts': facts}, 'citations': citations}

                def candidate_tool(arguments):
                    query = arguments.get('query', '')
                    limit = arguments.get('limit', 6)
                    if not isinstance(query, str) or len(query) > 500:
                        raise ValueError('Candidate search query is invalid')
                    if type(limit) is not int or limit < 1 or limit > 10:
                        raise ValueError('Candidate search limit must be 1..10')
                    rows = self.list_candidates({})
                    if query.strip():
                        terms = query.casefold().split()
                        matched = [row for row in rows if all(term in ' '.join((
                            row.get('name', ''), row.get('description', ''), row.get('location', ''),
                            ' '.join(row.get('people') or [])
                        )).casefold() for term in terms)]
                    else:
                        matched = rows
                    if selected_name:
                        selected = [row for row in rows if row['id'] == candidate_id]
                        matched = selected + [row for row in matched if row['id'] != candidate_id]
                    matched = matched[:limit]
                    profiles, citations = [], []
                    for row in matched:
                        assessment = row.get('assessment') or {}
                        citation = dict(id=f'profile:{row["id"]}', kind='Candidate profile',
                            title=row['name'], quote=(row.get('description') or f'Candidate profile for {row["name"]}.')[:1000],
                            url=row.get('website') or None, candidate_id=row['id'])
                        citations.append(citation)
                        profiles.append({
                            'name': row['name'], 'description': row.get('description'),
                            'location': row.get('location'), 'website': row.get('website'),
                            'people': (row.get('people') or [])[:10],
                            'funding_status': row.get('funding_status'),
                            'funding_summary': row.get('funding_summary'),
                            'score': assessment.get('score') if row.get('assessment_rankable') else None,
                            'assessment_summary': assessment.get('summary') if row.get('assessment_current') else None,
                            'criteria': [{'key': item.get('key'), 'rating': item.get('rating'),
                                          'rationale': item.get('rationale'),
                                          'evidence_ids': (item.get('evidence_ids') or [])[:4]}
                                         for item in (assessment.get('criteria') or [])[:4]]
                                        if row.get('assessment_current') else [],
                            'citation_id': citation['id'],
                        })
                        try:
                            detail = self.candidate_detail(row['id'])
                        except NotFound:
                            continue
                        for item in detail.get('evidence', [])[:3]:
                            if not item.get('quote'):
                                continue
                            evidence = dict(id=f'evidence:{item["id"]}', kind='Source evidence',
                                title=item.get('title') or row['name'], quote=item['quote'][:1200],
                                url=item.get('url'), candidate_id=row['id'])
                            citations.append(evidence)
                            profiles[-1].setdefault('evidence', []).append({
                                'title': evidence['title'], 'quote': evidence['quote'],
                                'citation_id': evidence['id']})
                    return {'data': {'candidates': profiles}, 'citations': citations}

                tools = [
                    {'type': 'function', 'name': 'search_knowledge_graph',
                     'description': 'Search Neo4j via Graphiti for sourced facts and relationships between ventures, people, and organizations.',
                     'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                                    'required': ['query'], 'additionalProperties': False}, 'strict': True},
                    {'type': 'function', 'name': 'search_candidate_profiles',
                     'description': 'Search saved PostgreSQL candidate profiles, current rankings, funding research, people, and original source evidence.',
                     'parameters': {'type': 'object', 'properties': {
                         'query': {'type': 'string'}, 'limit': {'type': 'integer'}},
                         'required': ['query', 'limit'], 'additionalProperties': False}, 'strict': True},
                ]

                def execute_tool(name, arguments):
                    if name == 'search_knowledge_graph':
                        return graph_tool(arguments)
                    if name == 'search_candidate_profiles':
                        return candidate_tool(arguments)
                    raise ValueError('Unsupported tool')

                return self._chat_model.answer_with_tools(question.strip(), language,
                    clean_history, tools, execute_tool)
            except Exception as exc:
                log.error('Candidate chat answer generation failed (%s)', type(exc).__name__)
                raise ChatUnavailable('Grounded answer generation is unavailable') from None
