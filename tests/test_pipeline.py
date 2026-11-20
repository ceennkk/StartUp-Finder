from dataclasses import replace
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from startup_finder.api import dispatch, make_server
from startup_finder.clients import OpenAIModels
from startup_finder.config import Settings
from startup_finder.domain import Application
from startup_finder.fetching import validate_public_url, text_from_html
from startup_finder.store import Store, now
from startup_finder.ranking import score_assessment
from startup_finder.worker import Worker


class TestGraphBridge:
    def __init__(self, settings):
        self.settings = settings

    def ingest(self, finding):
        return {
            'episode_id': finding.episode_id(self.settings.group_id),
            'nodes': [{
                'id': 'venture:example', 'name': 'Example Ventures',
                'labels': ['StartupVenture'], 'attributes': {
                    'description': 'Industrial energy monitoring', 'country': 'DE',
                    'people': ['Alex Example'],
                },
            }],
            'edges': [{
                'id': 'edge:example', 'source': 'person:alex', 'target': 'venture:example',
                'fact': 'Alex Example arbeitet an Example Ventures', 'episode_ids': [finding.episode_id(self.settings.group_id)],
            }],
        }


class TestModels:
    def evaluate(self, profile):
        evidence_ids = [e['id'] for e in profile['evidence']]
        criteria = [dict(key=key, label=key, rating='unknown', rationale='Nicht belegt.', evidence_ids=[])
                    for key in ('founding_intent', 'technical_substance', 'customer_problem', 'demand')]
        return dict(summary='Review erforderlich.', strengths=[], concerns=[],
                    open_questions=profile['open_questions'], evidence_ids=evidence_ids, criteria=criteria,
                    model='isolated-test-double')

    def research(self, candidate):
        return {'summary': 'Keine zusätzlichen Quellen gefunden.', 'sources': []}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(database_url='sqlite:///'+self.temp.name+'/pipeline-test.db', group_id='pipeline-test')
        self.store = Store(self.settings.database_url)
        self.store.initialize()
        self.app = Application(self.store, self.settings)
        self.bridge = TestGraphBridge(self.settings)
        self.worker = Worker(self.app, bridge=self.bridge, models=TestModels())
        self.source = self.app.create_source({'name': 'Research feed', 'url': 'https://example.org/feed', 'kind': 'manual'})

    def tearDown(self):
        self.temp.cleanup()

    def drain(self):
        for _ in range(30):
            if not self.worker.run_once():
                return
        self.fail('Queue did not drain')

    def add_finding(self, external_id='example-1', title='Example venture update', text='The team develops an industrial energy monitoring product.'):
        return self.app.import_finding(dict(source_id=self.source['id'], external_id=external_id,
            url=f'https://example.org/{external_id}', title=title, text=text))

    def queue_processing(self, finding):
        self.app.queue('process', finding['id'])
        self.drain()

    def test_end_to_end_and_ingestion_idempotency(self):
        finding = self.add_finding()
        self.queue_processing(finding)
        candidates = self.store.list('candidates')
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(self.store.list('assessments')), 1)
        self.assertTrue(all('assessment' not in a['profile_snapshot'] for a in self.store.list('assessments')))
        self.assertTrue(all(job['status'] == 'succeeded' for job in self.store.jobs()))
        self.assertNotIn('is_demo', candidates[0])
        self.app.import_finding(dict(source_id=self.source['id'], external_id='example-1',
            url='https://example.org/example-1', title='Example venture update',
            text='The team develops an industrial energy monitoring product.'))
        self.assertEqual(len(self.store.list('findings')), 1)
        self.assertEqual(len(self.store.list('evidence')), 1)

    def test_changed_source_updates_identity_preserves_user_actions(self):
        self.queue_processing(self.add_finding())
        candidate = self.store.list('candidates')[0]
        self.app.patch_candidate(candidate['id'], {'status': 'shortlisted'})
        self.app.add_note(candidate['id'], {'text': 'Prüfen'})
        finding = self.add_finding('example-2', 'New update', 'The team added a pilot customer and product update.')
        self.app.queue('process', finding['id'])
        self.worker.run_once()
        detail = self.app.candidate_detail(candidate['id'])
        self.assertEqual(detail['profile_version'], 2)
        self.assertTrue(detail['assessment_stale'])
        self.assertEqual(detail['status'], 'shortlisted')
        self.assertEqual(len(detail['notes']), 1)
        self.drain()
        detail = self.app.candidate_detail(candidate['id'])
        self.assertFalse(detail['assessment_stale'])
        self.assertEqual(len(detail['evidence']), 2)

    def test_retry_reuses_successful_graph_receipt(self):
        finding = self.add_finding()
        self.app.queue('process', finding['id'])
        with patch.object(self.bridge, 'ingest', wraps=self.bridge.ingest) as ingest:
            with patch('startup_finder.worker.materialize', side_effect=ValueError('temporary')):
                self.worker.run_once()
            receipt_finding = next(f for f in self.store.list('findings') if f['graph_receipt'])
            self.assertEqual(receipt_finding['status'], 'graph_processed')
            with self.store.transaction() as c:
                self.store.sql(c, "UPDATE jobs SET available_at=0 WHERE status='queued'")
            self.drain()
            self.assertEqual(ingest.call_count, 1)  # once per source finding, not once per retry
        self.assertEqual(len(self.store.list('candidates')), 1)

    def test_job_claim_is_exclusive_and_lease_can_recover(self):
        self.store.enqueue('evaluate', {'id': 'candidate'})
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.store.claim(30))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        claimed = [r for r in results if r]
        self.assertEqual(len(claimed), 1)
        with self.store.transaction() as c:
            self.store.sql(c, 'UPDATE jobs SET lease_until=0')
        recovered = self.store.claim(30)
        self.assertEqual(recovered['id'], claimed[0]['id'])
        self.assertEqual(recovered['attempts'], 2)
        self.store.finish(claimed[0], result={'stale': True})
        self.assertEqual(self.store.jobs(recovered['id'])['status'], 'running')

    def test_source_collection_and_search_jobs(self):
        self.add_finding()
        search = self.app.create_search({'prompt': 'Industrial energy monitoring', 'source_ids': [self.source['id']], 'interval_minutes': 15})
        self.assertNotIn('region', search)
        self.app.queue('search', search['id'])
        self.drain()
        updated = self.store.get('searches', search['id'])
        self.assertEqual(len(updated['finding_ids']), 1)
        self.assertIsNotNone(updated['next_run_at'])
        self.assertEqual(self.store.jobs(updated['last_job_id'])['status'], 'succeeded')

    def test_research_and_notes(self):
        self.queue_processing(self.add_finding())
        candidate = self.store.list('candidates')[0]
        job = self.app.queue('research', candidate['id'])
        self.drain()
        self.assertEqual(self.store.jobs(job['id'])['status'], 'succeeded')
        detail = self.app.candidate_detail(candidate['id'])
        self.assertEqual(len(detail['research_runs']), 1)
        self.assertNotIn('is_demo', detail['research_runs'][0])

    def test_api_validation_and_pagination(self):
        self.queue_processing(self.add_finding('example-1'))
        self.queue_processing(self.add_finding('example-2', 'Second update', 'A second team update.'))
        status, result = dispatch(self.app, 'GET', '/api/candidates', {'limit': '2'}, {})
        self.assertEqual(status, 200)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['total'], 1)
        with self.assertRaises(ValueError):
            dispatch(self.app, 'GET', '/api/candidates', {'limit': '9999'}, {})
        with self.assertRaises(ValueError):
            self.app.create_source({'name':'bad', 'url':'file:///etc/passwd'})
        with self.assertRaises(ValueError):
            self.app.create_search({'prompt':'test', 'interval_minutes':1})

    def test_model_cannot_cite_unknown_evidence(self):
        self.queue_processing(self.add_finding())
        profile = self.app.candidate_detail(self.store.list('candidates')[0]['id'])
        valid = self.worker.models.evaluate(profile)
        valid['evidence_ids'] = ['fabricated']
        live = OpenAIModels(self.settings)
        with patch.object(live, 'request', return_value={'output':[{'content':[{'type':'output_text','text':json.dumps(valid)}]}]}):
            with self.assertRaises(ValueError):
                live.evaluate(profile)

    def test_live_health_does_not_claim_graph_connectivity(self):
        status, result = dispatch(self.app, 'GET', '/api/health', {}, {})
        self.assertEqual(result['graph_status'], 'not_probed')

    def test_outside_germany_is_in_default_feed(self):
        self.queue_processing(self.add_finding())
        candidate = self.store.list('candidates')[0]
        candidate['germany_status'] = 'outside_germany'
        self.store.put('candidates', candidate)
        self.assertEqual(len(self.app.list_candidates({})), 1)
        self.assertEqual(len(self.app.list_candidates({'germany_status':'outside_germany'})), 1)

    def test_assessment_score_is_deterministic_and_requires_evidence_coverage(self):
        criteria = [dict(key=key, rating=rating, evidence_ids=['e1'] if rating != 'unknown' else [])
                    for key, rating in [('founding_intent', 'strong'), ('technical_substance', 'moderate'),
                                        ('customer_problem', 'strong'), ('demand', 'unknown')]]
        scored = score_assessment({'criteria': criteria})
        self.assertEqual(scored['score'], 89)
        self.assertEqual(scored['scored_criteria'], 3)
        self.assertEqual(scored['priority'], 'high')
        sparse = score_assessment({'criteria': [dict(c, rating='unknown', evidence_ids=[]) for c in criteria]})
        self.assertIsNone(sparse['score'])
        self.assertEqual(sparse['priority'], 'insufficient_data')

    def test_list_uses_current_numeric_score_and_puts_unscored_last(self):
        self.queue_processing(self.add_finding())
        candidate = self.store.list('candidates')[0]
        other = dict(candidate, id='venture:scored', graph_node_id='venture:scored', name='A scored venture')
        self.store.put('candidates', other)
        self.store.put('assessments', dict(id='assessment:scored', candidate_id=other['id'],
            profile_version=other['profile_version'], criteria_version='sourcing-rank-v1',
            score=89, scored_criteria=3, priority='high', created_at=now()))
        rows = self.app.list_candidates({})
        self.assertTrue(rows[0]['assessment_rankable'])
        self.assertEqual(rows[0]['id'], other['id'])
        self.assertFalse(rows[1]['assessment_rankable'])
        self.assertEqual(rows[1]['assessment']['priority'], 'insufficient_data')

    def test_http_auth_production_capabilities_and_cors(self):
        settings = replace(self.settings, port=0, api_token='test-secret')
        server = make_server(Application(self.store, settings))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:'+str(server.server_port)
        try:
            with self.assertRaises(urllib.error.HTTPError) as failure:
                urllib.request.urlopen(base+'/api/candidates')
            self.assertEqual(failure.exception.code, 401)
            req = urllib.request.Request(base+'/api/capabilities', headers={
                'Authorization':'Bearer test-secret', 'Origin':'http://localhost:3000'})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'http://localhost:3000')
                capabilities = json.load(response)
                self.assertEqual(capabilities['mode'], 'live')
            with self.assertRaises(urllib.error.HTTPError) as removed:
                urllib.request.urlopen(urllib.request.Request(base+'/api/demo/seed', data=b'{}', headers={
                    'Authorization':'Bearer test-secret', 'Content-Type':'application/json'}))
            self.assertEqual(removed.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_fetch_rejects_private_hosts_and_strips_scripts(self):
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',80))]):
            with self.assertRaises(ValueError):
                validate_public_url('http://internal.test', ['internal.test'])
        with self.assertRaises(ValueError):
            validate_public_url('http://other.test', ['allowed.test'])
        self.assertEqual(text_from_html('<nav>Menu</nav><p>Team</p><script>ignore()</script>'), 'Team')


if __name__ == '__main__':
    unittest.main()
