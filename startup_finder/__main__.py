"""Run `python -m startup_finder demo` for a complete offline preview."""
import argparse
from dataclasses import replace
import logging
import threading
from .config import Settings
from .domain import Application
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('demo', 'serve', 'worker', 'init-db'))
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    if args.port is not None:
        settings = replace(settings, port=args.port)
    if args.command == 'demo' and settings.mode != 'demo':
        parser.error('Set APP_MODE=demo for demo preview')
    if settings.mode == 'demo' and settings.host not in ('127.0.0.1', 'localhost', '::1') and not settings.api_token:
        parser.error('Non-loopback binding requires API_TOKEN')
    store = Store(settings.database_url)
    store.initialize()
    app = Application(store, settings)
    if args.command == 'init-db':
        print('Database initialized')
        return
    from .worker import Worker
    if args.command == 'worker':
        try:
            Worker(app).run()
        except KeyboardInterrupt:
            pass
        return
    from .api import make_server
    stop = threading.Event()
    thread = None
    if args.command == 'demo':
        from .demo import seed
        seed(app)
        thread = threading.Thread(target=Worker(app).run, args=(stop,), daemon=True)
        thread.start()
    server = make_server(app)
    print(f'Startup Finder ({settings.mode}): http://{settings.host}:{settings.port}/preview', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        stop.set()
        if thread:
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
