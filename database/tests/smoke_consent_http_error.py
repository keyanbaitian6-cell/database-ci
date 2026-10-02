"""Opt-in Windows check (python tests/smoke_consent_http_error.py). Real WebView2 event order for a top-level auth/consent navigation that returns an HTTP error.

Local only: 127.0.0.1 pseudo pages, a temporary WebView2 profile, no user DB/Cookies, no site access.
Uses the production BrowserConnection / install_webview2_handlers / present_connection_failure.
"""
import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webview  # noqa: E402
from pscube_connection import BrowserConnection, install_webview2_handlers, present_connection_failure  # noqa: E402

SHOP = '/dedamajyoho-P-townDMMpachi/c740601/'
ALLOWED_PATHS = {SHOP, SHOP + 'cgi-bin/nc-v03-001.php', SHOP + 'cgi-bin/nc-v05-011.php', SHOP + 'cgi-bin/nc-v06-001.php'}
PAGES = {
    SHOP: (200, '<h1>ROOT</h1>'),
    SHOP + 'cgi-bin/nc-v06-001.php': (403, '<p>ALLOWED-403 約款に同意して <button>同意</button></p>'),
    SHOP + 'agree.php': (403, '<p>CONSENT-403 約款に同意して <button>同意する</button></p>'),
    '/auth/check': (403, '<p>AUTH-403 ロボットでないことを確認 <button>確認</button></p>'),
    SHOP + 'cgi-bin/nc-v05-011.php': (302, SHOP + 'agree.php'),  # allowed page redirected to consent
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        status, body = PAGES.get(path, (404, 'NOT FOUND'))
        if status == 302:
            self.send_response(302)
            self.send_header('Location', body)
            self.end_headers()
            return
        data = f'<!doctype html><meta charset="utf-8"><body>{body}</body>'.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}'


def allowed(url):
    p = urlparse(url or '')
    return p.netloc == urlparse(base).netloc and p.path in ALLOWED_PATHS


connection = BrowserConnection(base + SHOP, page_allowed=allowed)
events, results = [], []
window = webview.create_window('LOCAL WebView2 consent probe', base + SHOP, width=640, height=420)
handlers = []


def failed():
    with connection.lock:
        revision = connection.revision
        events.append(['failed', connection.failure and connection.failure['kind']])
    threading.Thread(target=lambda: events.append(['present', present_connection_failure(window, connection, revision)]),
                     daemon=True).start()


def before_show():
    handlers.extend(install_webview2_handlers(window, connection, failed))
    control = window.native.webview

    def started(s, a):
        events.append(['NavigationStarting', str(a.Uri)[:60], a.NavigationId, bool(a.IsRedirected)])

    def completed(s, a):
        events.append(['NavigationCompleted', a.NavigationId, bool(a.IsSuccess), str(a.WebErrorStatus)])

    def ready(s, a):
        def response(s2, a2):
            if a2.Response is not None:
                events.append(['ResponseReceived', str(a2.Request.Uri)[:60], a2.Response.StatusCode])
        handlers.append(response)
        s.CoreWebView2.WebResourceResponseReceived += response

    handlers.extend([started, completed, ready])
    control.NavigationStarting += started
    control.NavigationCompleted += completed
    control.CoreWebView2InitializationCompleted += ready


window.events.before_show += before_show


def scenario():
    time.sleep(4)
    for label, path in [('allowed page 403', SHOP + 'cgi-bin/nc-v06-001.php?cd_dai=1'),
                        ('consent page (same host, not allowed) 403', SHOP + 'agree.php'),
                        ('auth page (other path) 403', '/auth/check'),
                        ('allowed page 302 -> consent 403', SHOP + 'cgi-bin/nc-v05-011.php?cd_ps=2')]:
        events.append(['--', label])
        mark = len(events)
        window.load_url(base + SHOP)
        time.sleep(2.5)
        events.append(['-- go', label])
        window.load_url(base + path)
        time.sleep(4)
        body = window.evaluate_js('document.body ? document.body.innerText : ""') or ''
        with connection.lock:
            results.append({'case': label, 'failure_kind': connection.failure and connection.failure['kind'],
                            'showing_app_error_page': connection.showing_error,
                            'body': body[:60].replace('\n', ' '),
                            'events': events[mark:]})
    window.destroy()


profile = tempfile.mkdtemp(prefix='wv2-consent-probe-')
webview.start(scenario, gui='edgechromium', private_mode=True, storage_path=profile)
server.shutdown()
for r in results:
    print(r['case'], '| failure:', r['failure_kind'], '| app error page:', r['showing_app_error_page'])
by_case = {r['case']: r for r in results}
assert by_case['allowed page 403']['failure_kind'] == 'HTTP' and not by_case['allowed page 403']['showing_app_error_page']
assert by_case['allowed page 403']['body'].startswith('ALLOWED-403'), by_case['allowed page 403']['body']
for case, prefix in [('consent page (same host, not allowed) 403', 'CONSENT-403'), ('auth page (other path) 403', 'AUTH-403'),
                     ('allowed page 302 -> consent 403', 'CONSENT-403')]:
    r = by_case[case]
    assert r['failure_kind'] is None and not r['showing_app_error_page'], r
    assert r['body'].startswith(prefix), r['body']
print('PASS: consent/auth HTTP error documents stay visible; target-page HTTP 403 still stops auto capture')
