"""Small JSON HTTP API for the production workflow.

For public deployments put a TLS reverse proxy in front; this is a team prototype,
not a multi-tenant application server. Non-loopback bindings require a bearer token.
"""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from urllib.parse import parse_qs, urlparse
from .domain import NotFound
from .store import now

log = logging.getLogger(__name__)


def page(items, query):
    limit, offset = int(query.get('limit', 50)), int(query.get('offset', 0))
    if limit < 1 or limit > 200 or offset < 0:
        raise ValueError('limit must be 1..200; offset >= 0')
    return {'items': items[offset:offset+limit], 'total': len(items)}


def dispatch(app, method, path, query, data):
    store = app.store
    parts = path.strip('/').split('/')
    if method == 'GET' and path == '/api/health':
        store.list('runtime')
        worker = store.get('runtime', 'worker')
        return 200, dict(status='ok', mode='live', database='ok', worker=worker,
                         graph_status='not_probed', model_status='not_probed')
    if method == 'GET' and path == '/api/capabilities':
        return 200, app.capabilities()
    list_kinds = {'sources', 'findings', 'searches', 'events'}
    if len(parts) == 2 and parts[0] == 'api' and parts[1] in list_kinds and method == 'GET':
        rows = store.list(parts[1])
        if parts[1] == 'findings':
            rows = [row for row in rows if not str(row.get('status', '')).startswith('excluded_')]
            rows = [{key: value for key, value in row.items()
                     if key not in ('decision_context', 'relevance_context')} for row in rows]
        for key in ('source_id', 'status', 'entity_id'):
            if query.get(key):
                rows = [r for r in rows if r.get(key) == query[key]]
        if query.get('q'):
            term = query['q'].casefold()
            rows = [r for r in rows if term in json.dumps(r, ensure_ascii=False).casefold()]
        rows.sort(key=lambda r:r.get('created_at', ''), reverse=True)
        return 200, page(rows, query)
    if path == '/api/sources' and method == 'POST':
        return 201, app.create_source(data)
    if path == '/api/findings' and method == 'POST':
        return 201, app.import_finding(data)
    if path == '/api/searches' and method == 'POST':
        return 201, app.create_search(data)
    if path == '/api/candidates' and method == 'GET':
        return 200, page(app.list_candidates(query), query)
    if path == '/api/jobs' and method == 'GET':
        rows = store.jobs()
        for key in ('status', 'kind'):
            if query.get(key):
                rows = [r for r in rows if r[key] == query[key]]
        return 200, page(rows, query)
    if path == '/api/graph' and method == 'GET':
        return 200, app.graph()
    if len(parts) >= 3 and parts[0] == 'api':
        kind, record_id = parts[1:3]
        if kind == 'jobs':
            job = store.jobs(record_id)
            if not job:
                raise NotFound('Job not found')
            if method == 'GET' and len(parts) == 3:
                return 200, job
            if method == 'POST' and parts[3:] == ['retry']:
                return 202, {'job': store.retry(record_id)}
        if kind in ('findings', 'sources', 'searches') and method == 'GET' and len(parts) == 3:
            record = app.require(kind, record_id)
            if kind == 'findings':
                record = {key: value for key, value in record.items()
                          if key not in ('decision_context', 'relevance_context')}
            return 200, record
        if kind == 'sources' and method == 'PATCH' and len(parts) == 3:
            if set(data) != {'enabled'} or type(data['enabled']) is not bool:
                raise ValueError('Only boolean enabled can be patched')
            with store.transaction() as c:
                source = app.require(kind, record_id, c)
                source.update(enabled=data['enabled'], updated_at=now())
                store.put(kind, source, c)
            return 200, source
        actions = {('findings', 'process'): 'process', ('searches', 'run'): 'search',
                   ('candidates', 'research'): 'research', ('candidates', 'evaluate'): 'evaluate'}
        if method == 'POST' and len(parts) == 4 and (kind, parts[3]) in actions:
            return 202, {'job': app.queue(actions[(kind, parts[3])], record_id)}
        if kind == 'candidates':
            if len(parts) == 3:
                if method == 'GET':
                    return 200, app.candidate_detail(record_id)
                if method == 'PATCH':
                    return 200, app.patch_candidate(record_id, data)
            if method == 'POST' and parts[3:] == ['notes']:
                return 201, app.add_note(record_id, data)
    raise NotFound('Route not found')


def make_server(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Request URLs may contain personal data. Keep logs to status only.
            log.debug('HTTP request completed')

        def send(self, status, payload, mime='application/json; charset=utf-8'):
            body = json.dumps(payload, ensure_ascii=False).encode() if mime.startswith('application/json') else payload
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            origin = self.headers.get('Origin')
            if origin in app.settings.cors_origins:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Methods', 'GET,POST,PATCH,OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type,Authorization')
            self.end_headers()
            self.wfile.write(body)

        def handle_request(self):
            parsed = urlparse(self.path)
            if self.command == 'OPTIONS':
                return self.send(200, {})
            expected = app.settings.api_token
            if expected and not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+expected):
                return self.send(401, {'detail': 'Bearer token required'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 1_000_000:
                    return self.send(413, {'detail': 'Request body exceeds limit'})
                raw = self.rfile.read(length)
                data = json.loads(raw) if raw else {}
                if not isinstance(data, dict):
                    raise ValueError('JSON object required')
                query = {key: value[-1] for key, value in parse_qs(parsed.query).items()}
                status, result = dispatch(app, self.command, parsed.path, query, data)
                self.send(status, result)
            except NotFound as exc:
                self.send(404, {'detail': str(exc)})
            except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
                self.send(422, {'detail': str(exc)[:300]})
            except Exception:
                log.exception('API request failed')
                self.send(500, {'detail': 'Internal error; inspect server logs'})

        do_GET = do_POST = do_PATCH = do_OPTIONS = handle_request

    return ThreadingHTTPServer((app.settings.host, app.settings.port), Handler)
