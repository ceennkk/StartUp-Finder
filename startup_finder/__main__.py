"""Run the production API, worker, or initialize its PostgreSQL store."""
import argparse
from dataclasses import replace
import logging
from .config import Settings
from .domain import Application
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('serve', 'worker', 'init-db', 'sync-adapters', 'rebuild-graph'))
    parser.add_argument('--port', type=int)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--source', help='Only import one collector source name')
    parser.add_argument('--record-type', help='Only import one adapter record type')
    parser.add_argument('--group-id', default='startup_finder_de_ontology_v1',
                        help='New isolated Graphiti group for a staged ontology rebuild')
    parser.add_argument('--dry-run', action='store_true', help='Map records without creating Finder findings or jobs')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    if args.port is not None:
        settings = replace(settings, port=args.port)
    store = Store(settings.database_url)
    store.initialize()
    app = Application(store, settings)
    if args.command == 'init-db':
        print('Database initialized')
        return
    if args.command == 'sync-adapters':
        from .adapter_bridge import import_adapter_records
        import json
        print(json.dumps(import_adapter_records(app, args.limit, args.source, args.record_type, args.dry_run), ensure_ascii=False))
        return
    if args.command == 'rebuild-graph':
        from .rebuild import rebuild_graph
        import json
        print(json.dumps(rebuild_graph(app, args.group_id), ensure_ascii=False))
        return
    from .worker import Worker
    if args.command == 'worker':
        try:
            Worker(app).run()
        except KeyboardInterrupt:
            pass
        return
    from .api import make_server
    server = make_server(app)
    print(f'Startup Finder production API: http://{settings.host}:{settings.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
