"""Run an offline end-to-end check without changing the user's demo database."""
from tempfile import TemporaryDirectory
from startup_finder.config import Settings
from startup_finder.demo import seed
from startup_finder.domain import Application
from startup_finder.store import Store
from startup_finder.worker import Worker

with TemporaryDirectory() as directory:
    settings = Settings(database_url='sqlite:///'+directory+'/smoke.db')
    store = Store(settings.database_url)
    store.initialize()
    app = Application(store, settings)
    seed(app)
    worker = Worker(app)
    while worker.run_once():
        pass
    candidates = store.list('candidates')
    assert len(candidates) == 3
    assert len(store.list('assessments')) == 3
    assert all(job['status'] == 'succeeded' for job in store.jobs())
    candidate = candidates[0]
    app.patch_candidate(candidate['id'], {'status': 'shortlisted'})
    app.add_note(candidate['id'], {'text': 'Smoke test'})
    app.queue('research', candidate['id'])
    while worker.run_once():
        pass
    assert app.candidate_detail(candidate['id'])['research_runs']
    print('PASS: import → graph fixtures → candidates → assessments → shortlist → notes → research')
