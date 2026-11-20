from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from startup_finder.api import dispatch, make_server
from startup_finder.clients import GraphBridge, OpenAIModels
from startup_finder.config import Settings
from startup_finder.demo import seed, TEAMS
from startup_finder.domain import Application
from startup_finder.fetching import validate_public_url, text_from_html
from startup_finder.store import Store, now
from startup_finder.worker import Worker


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(database_url='sqlite:///'+self.temp.name+'/demo.db')
        self.store = Store(self.settings.database_url)
        self.store.initialize()
        self.app = Application(self.store, self.settings)
        self.worker = Worker(self.app)

    def tearDown(self):
        self.temp.cleanup()

    def drain(self):
        for _ in range(30):
            if not self.worker.run_once():
                return
        self.fail('Queue did not drain')

    def test_end_to_end_and_reseed_idempotency(self):
        seed(self.app)
        self.drain()
        candidates = self.store.list('candidates')
        self.assertEqual(len(candidates), 3)
        self.assertEqual(len(self.store.list('assessments')), 3)
        self.assertTrue(all('assessment' not in a['profile_snapshot'] for a in self.store.list('assessments')))
        self.assertTrue(all(job['status'] == 'succeeded' for job in self.store.jobs()))
        self.assertTrue(all(c['is_demo'] for c in candidates))
        seed(self.app)
        self.drain()
        self.assertEqual(len(self.store.list('candidates')), 3)
        self.assertEqual(len(self.store.list('evidence')), 3)
        self.assertTrue(all(c['profile_version'] == 1 for c in self.store.list('candidates')))

    def test_changed_source_updates_identity_preserves_user_actions(self):
        seed(self.app)
        self.drain()
        candidate = next(c for c in self.store.list('candidates') if c['name'] == 'DemoRobot')
        self.app.patch_candidate(candidate['id'], {'status': 'shortlisted'})
        self.app.add_note(candidate['id'], {'text': 'Prüfen'})
        finding = self.app.import_finding(dict(source_id='demo-source', external_id='robot',
            url=TEAMS[0]['website'], title='Neue Meldung', text=TEAMS[0]['evidence_quote']+' Weitere Entwicklung.'))
        finding.update(is_demo=True, demo_entities=[TEAMS[0]])
        self.store.put('findings', finding)
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
        seed(self.app)
        with patch.object(self.worker.bridge, 'ingest', wraps=self.worker.bridge.ingest) as ingest:
            with patch('startup_finder.worker.materialize', side_effect=ValueError('temporary')):
                self.worker.run_once()
            receipt_finding = next(f for f in self.store.list('findings') if f['graph_receipt'])
            self.assertEqual(receipt_finding['status'], 'graph_processed')
            with self.store.transaction() as c:
                self.store.sql(c, "UPDATE jobs SET available_at=0 WHERE status='queued'")
            self.drain()
            self.assertEqual(ingest.call_count, 3)  # once per original finding, not once per attempt
        self.assertEqual(len(self.store.list('candidates')), 3)

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
        seed(self.app)
        self.drain()
        search = self.app.create_search({'prompt': 'Technische Teams in Deutschland', 'interval_minutes': 15})
        self.drain()
        updated = self.store.get('searches', search['id'])
        self.assertEqual(len(updated['finding_ids']), 3)
        self.assertIsNotNone(updated['next_run_at'])
        self.assertEqual(self.store.jobs(updated['last_job_id'])['status'], 'succeeded')

    def test_arbitrary_text_never_silently_gets_demo_ai_results(self):
        seed(self.app)
        self.drain()
        finding = self.app.import_finding(dict(source_id='demo-source', url='https://example.org/unknown', title='Unbekannt', text='Random text'))
        with self.assertRaises(ValueError):
            self.worker.process(finding['id'])

    def test_research_and_notes(self):
        seed(self.app)
        self.drain()
        candidate = self.store.list('candidates')[0]
        job = self.app.queue('research', candidate['id'])
        self.drain()
        self.assertEqual(self.store.jobs(job['id'])['status'], 'succeeded')
        detail = self.app.candidate_detail(candidate['id'])
        self.assertEqual(len(detail['research_runs']), 1)
        self.assertTrue(detail['research_runs'][0]['is_demo'])

    def test_api_validation_and_pagination(self):
        seed(self.app)
        self.drain()
        status, result = dispatch(self.app, 'GET', '/api/candidates', {'limit': '2'}, {})
        self.assertEqual(status, 200)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['total'], 3)
        with self.assertRaises(ValueError):
            dispatch(self.app, 'GET', '/api/candidates', {'limit': '9999'}, {})
        with self.assertRaises(ValueError):
            self.app.create_source({'name':'bad', 'url':'file:///etc/passwd'})
        with self.assertRaises(ValueError):
            self.app.create_search({'prompt':'test', 'interval_minutes':1})

    def test_model_cannot_cite_unknown_evidence(self):
        seed(self.app)
        self.drain()
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

    def test_outside_germany_is_not_in_default_feed(self):
        seed(self.app)
        self.drain()
        candidate = self.store.list('candidates')[0]
        candidate['germany_status'] = 'outside_germany'
        self.store.put('candidates', candidate)
        self.assertEqual(len(self.app.list_candidates({})), 2)
        self.assertEqual(len(self.app.list_candidates({'germany_status':'outside_germany'})), 1)

    def test_http_auth_static_preview_and_cors(self):
        settings = replace(self.settings, port=0, api_token='test-secret')
        server = make_server(Application(self.store, settings))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(base+'/preview') as response:
                self.assertIn(b'STARTUP FINDER', response.read())
            with self.assertRaises(urllib.error.HTTPError) as failure:
                urllib.request.urlopen(base+'/api/candidates')
            self.assertEqual(failure.exception.code, 401)
            req = urllib.request.Request(base+'/api/demo/seed', data=b'{}', headers={
                'Authorization':'Bearer test-secret', 'Content-Type':'application/json', 'Origin':'http://localhost:5173'})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 201)
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'http://localhost:5173')
                self.assertEqual(len(json.load(response)['jobs']), 3)
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
