"""Opt-in Windows WebView2 Cookie/retry regression, localhost and temporary DBs.

Run with the PC Python runtime: python tests/smoke_cookie_retry.py.
Each production session runs in a new process, using its real persistent profile.
No site requests, user profiles, CAPTCHA, or user records are used.
"""
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(site, phase, folder, base, recovery):
    import webview
    import browser_import as meruhen
    import pscube_import as pscube
    from pscube_connection import BrowserConnection

    module = meruhen if site == 'meruhen' else pscube
    allowed = lambda url: urlparse(url or '').netloc in {urlparse(base).netloc, urlparse(recovery).netloc}
    connections = []
    events = []
    def diagnostic_url(url):
        p = urlparse(str(url))
        return '<local error HTML>' if p.scheme == 'data' else p.scheme + '://' + p.netloc + p.path

    def connection(root, **options):
        options['page_allowed'] = allowed
        c = BrowserConnection(root, **options)
        original_start, original_http = c.start, c.http_error
        def start(*args):
            events.append(['start', diagnostic_url(args[0]), *args[1:]])
            return original_start(*args)
        def http(*args):
            result = original_http(*args)
            events.append(['http', diagnostic_url(args[0]), *args[1:], result, diagnostic_url(c.url)])
            return result
        c.start, c.http_error = start, http
        connections.append(c)
        return c

    module.BrowserConnection = connection
    meruhen.is_allowed_url = allowed
    pscube.site_url = lambda url: url if allowed(url) else (_ for _ in ()).throw(ValueError('local only'))
    suffix = ('/saiwaichou/standgraph/?rack_no=710&target_date=2026-10-01'
              if site == 'meruhen' else '/cgi-bin/nc-v06-001.php?cd_dai=710')
    url = base + suffix
    meruhen.DEFAULT_START = url
    pscube.ROOT_URL = base + '/'
    refs, observed = {}, {}
    original_create = webview.create_window

    def create(title, ignored_url, **options):
        refs['bridge'] = options['js_api']
        refs['window'] = original_create('database LOCAL Cookie/retry test', url, **options)
        def forbid_external():
            def starting(sender, args):
                uri = str(args.Uri)
                error_document = connections and connections[0].showing_error and uri == connections[0].error_document_url
                if uri != 'about:blank' and not error_document and not allowed(uri):
                    args.Cancel = True
                    observed['blocked_external'] = diagnostic_url(args.Uri)
            refs['guard'] = starting
            refs['window'].native.webview.NavigationStarting += starting
        refs['window'].events.before_show += forbid_external
        return refs['window']

    webview.create_window = create

    def wait(predicate, label, timeout=15):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(.05)
        raise AssertionError(label)

    def worker():
        try:
            wait(lambda: 'window' in refs and refs['window'].events.loaded.is_set(), 'first load')
            window, bridge = refs['window'], refs['bridge']
            js = window.evaluate_js
            wait(lambda: js('!!window.pywebview?.api?.retry_page'), 'JS API ready')
            c = connections[0]
            auto = lambda: bridge.get_auto_capture() if site == 'meruhen' else bridge.pilot.state()
            if phase == 'write':
                js("document.cookie='retained=" + site + ";path=/;max-age=86400';localStorage.setItem('retained','" + site + "')")
                observed['passed'] = 'persistent Cookie/localStorage written'
                return
            assert site in js('document.cookie'), 'Cookie lost after process restart'
            assert js("localStorage.getItem('retained')") == site
            js("location.hash='20261001'")
            wait(lambda: window.get_current_url().endswith('#20261001'), 'selected fragment')
            before = js('window.requestNumber')
            # Use the actual bridge and native Reload path; synchronous before_load
            # must complete even with the auto scheduler running.
            bridge.retry_page()
            wait(lambda: (lambda n: isinstance(n, (int, float)) and n > before)(js('window.requestNumber')), 'same URL really reloads')
            assert window.get_current_url() == url + '#20261001'
            assert js("localStorage.getItem('retained')") == site
            assert site in js('document.cookie')
            assert not auto()['enabled']
            # Native admission guard during an already admitted review/save.
            lock = None if site == 'meruhen' else bridge._capture_lock
            if site == 'meruhen':
                class Review:
                    def poll(self):
                        return None
                bridge._children.append(Review())
            else:
                lock.acquire()
            try:
                try:
                    bridge.retry_page()
                except ValueError:
                    pass
                else:
                    raise AssertionError('retry accepted while saving')
            finally:
                if site == 'meruhen':
                    bridge._children.clear()
                else:
                    lock.release()
            # A real localhost HTTP rejection retains its own consent document.
            js("fetch('/control?status=403')")
            wait(lambda: js('window.controlDone'), '403 control')
            bridge.retry_page()
            try:
                wait(lambda: c.failure and c.failure['kind'] == 'HTTP', 'native HTTP403 detected')
            except AssertionError:
                observed['connection'] = {'url': diagnostic_url(c.url), 'history': c.history, 'revision': c.revision,
                                          'failure': c.failure, 'events': events}
                raise
            wait(lambda: js("!!document.getElementById('local-consent')"), 'site consent retained')
            assert not auto()['enabled']
            assert not c.showing_error
            js("window.controlDone=false;fetch('/control?status=200').then(()=>window.controlDone=true)")
            wait(lambda: js('window.controlDone'), '200 control')
            before = js('window.requestNumber')
            bridge.retry_page()
            wait(lambda: c.failure is None and (lambda n: isinstance(n, (int, float)) and n > before)(js('window.requestNumber')) and js("!!document.getElementById('local-ok')"), 'HTTP retry recovery')
            # A real connection refusal on localhost; start the same endpoint
            # afterward so the error document's actual button can recover.
            window.load_url(recovery + suffix + '#20261001')
            wait(lambda: c.showing_error, 'native network error page')
            wait(lambda: js("!!document.getElementById('retry') && !document.getElementById('retry').disabled"), 'error retry button')
            # Ask the original local server to start the recovery listener.
            import urllib.request
            urllib.request.urlopen(base + '/recover', timeout=3).close()
            js("document.getElementById('retry').click()")
            wait(lambda: c.failure is None and not c.showing_error and js("!!document.getElementById('local-ok')"), 'connection retry recovery')
            assert window.get_current_url() == recovery + suffix + '#20261001'
            window.load_url(url + '#20261001')
            wait(lambda: window.get_current_url() == url + '#20261001' and window.events.loaded.is_set(), 'original origin restored')
            assert site in js('document.cookie')
            assert js("localStorage.getItem('retained')") == site
            observed['passed'] = 'restart persistence, same URL reload, fragment, save guard, HTTP consent, native connection failure/retry, auto OFF'
        except Exception:
            import traceback
            observed['events'] = events
            if connections:
                observed['state'] = {'url': diagnostic_url(connections[0].url), 'failure': connections[0].failure,
                                     'showing_error': connections[0].showing_error}
            observed['error'] = traceback.format_exc()
        finally:
            refs['window'].destroy()

    threading.Thread(target=worker, daemon=True).start()
    folder = Path(folder)
    db_path = folder / 'data' / ('database.sqlite3' if site == 'meruhen' else 'pscube.sqlite3')
    module.run_session(db_path, folder / ('reports' if site == 'meruhen' else 'viewer.json'))
    print(json.dumps(observed, ensure_ascii=False), flush=True)
    assert 'error' not in observed, observed


def parent():
    from core import Store
    from pscube_import import PscubeStore
    state = {'status': 200, 'requests': 0}
    listeners = []
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        recovery_port = reserve.getsockname()[1]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/control'):
                state['status'] = 403 if '403' in self.path else 200
                body = b'ok'
                status = 200
            elif self.path == '/recover':
                recovery_server = ThreadingHTTPServer(('127.0.0.1', recovery_port), Handler)
                listeners.append(recovery_server)
                threading.Thread(target=recovery_server.serve_forever, daemon=True).start()
                body, status = b'ok', 200
            else:
                state['requests'] += 1
                status = state['status']
                marker = 'local-consent' if status == 403 else 'local-ok'
                body = (f'<!doctype html><meta charset="utf-8"><p id="{marker}">LOCAL TEST</p>'
                        f'<script>window.requestNumber={state["requests"]};window.controlDone=false;'
                        'const oldFetch=window.fetch;window.fetch=(...args)=>oldFetch(...args).then(r=>{window.controlDone=true;return r})</script>').encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Security-Policy', "default-src 'self' 'unsafe-inline' 'unsafe-eval'; img-src 'none'; frame-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    recovery = 'http://127.0.0.1:' + str(recovery_port)
    try:
        with tempfile.TemporaryDirectory(prefix='tmp-cookie-retry-', dir=ROOT) as folder:
            data = Path(folder) / 'data'
            data.mkdir()
            db = Store(data / 'database.sqlite3')
            db.save([dict(store='saiwaichou', machine='Dummy', rack=710, day='2026-10-01', kind_code=21, games=3000, bb=10, rb=5, max_hold=500)])
            db.close()
            PscubeStore(data / 'pscube.sqlite3').close()
            originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.glob('*.sqlite3')}
            for site in ('meruhen', 'pscube'):
                for phase in ('write', 'read'):
                    state['status'] = 200
                    subprocess.run([sys.executable, __file__, '--child', site, phase, folder, base, recovery], cwd=ROOT, timeout=65, check=True)
                for listener in listeners:
                    listener.shutdown()
                    listener.server_close()
                listeners.clear()
            assert (data / 'meruhen-webview').is_dir() and (data / 'pscube-webview').is_dir()
            assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in originals.items()), 'retry changed database files'
            print('PASS: both production WebView2 profiles, all retry checks, unchanged temporary SQLite files')
    finally:
        server.shutdown()
        server.server_close()
        for listener in listeners:
            listener.shutdown()
            listener.server_close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(*sys.argv[2:])
    else:
        parent()
