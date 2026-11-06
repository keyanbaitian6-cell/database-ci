"""Opt-in real WebView2 test, localhost fixtures and disposable DB only.

Run: .runtime/Scripts/python.exe tests/smoke_auto_capture.py
The child uses production run_session, extraction, timer, save subprocesses and
navigation. Only origins, fixtures and a deliberately delayed DB query change.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DAY = '2026-09-30'
LIST = '/saiwaichou/rack_info_kt/?kind_code=21'
TABLE = '/saiwaichou/standlist_slot/?kind_code=21&machine_name=Dummy&target_date=' + DAY
GRAPH = '/saiwaichou/standgraph/?rack_no=710&target_date=' + DAY


def localize(base):
    import browser_import as bi
    import collector
    collector.HOST = '127.0.0.1'
    bi.is_allowed_url = lambda url: url.startswith(base + '/')
    bi.machine_list_url = lambda store, day, after=None: base + LIST + '#database_next_machine=1&database_day=' + day
    return bi


def child(folder):
    import webview
    from core import Store, graph_done

    folder = Path(folder)
    db_path = folder / 'data' / 'dummy.sqlite3'
    db_path.parent.mkdir()
    Store(db_path).close()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if '/standlist_slot/' in self.path:
                content = '<table><tr>' + ''.join('<th>' + h + '</th>' for h in
                    ['台番号', 'BB', 'RB', '総回転数', '合成確率', '前日最終スタート', '最大持玉'])
                content += '</tr><tr><td><a href="' + GRAPH + '">710</a></td>'
                content += '<td>10</td><td>5</td><td>3000</td><td>1/200</td><td>0</td><td>500</td></tr></table>'
            elif '/standgraph/' in self.path:
                content = '''<svg class="today" viewBox="0 0 300 150" width="300" height="150">
                  <g class="path-slump"><path d="M0 75 L30 70 L60 80 L90 65 L120 55 L150 70 L180 60 L210 50 L240 45 L270 40 L300 35"/></g>
                  <g class="back-line-middle"><line y1="75"/></g>
                  <text class="info_soukaiten">3000</text><text class="info_big">10</text>
                  <text class="info_reg">5</text><text class="info_max_mochidama">500</text></svg>'''
            else:
                content = '<table><tr><td><a href="' + TABLE + '">Dummy</a></td><td>1台</td></tr></table>'
            body = ('<!doctype html><meta charset="utf-8"><title>database LOCAL TEST</title>'
                    '<body><h3>LOCAL DUMMY — real sites are not used</h3>' + content + '</body>').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Security-Policy', "default-src 'self' 'unsafe-inline' 'unsafe-eval'; connect-src 'none'; img-src 'none'; frame-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    os.environ['DATABASE_TEST_BASE'] = base
    bi = localize(base)
    for url in bi.BROWSER_URLS.values():
        bi.OVERLAY_JS = bi.OVERLAY_JS.replace(url, base + LIST)
    original_create, original_bridge = webview.create_window, bi._Bridge
    held, release = threading.Event(), threading.Event()
    observed = {'passed': []}
    refs = {}

    def bridge_factory(*args, **kwargs):
        bridge = original_bridge(*args, **kwargs)
        bridge._script_path = str(Path(__file__).resolve())
        original_next = bridge.next_unimported_machine
        refs['bridge'] = bridge
        refs['hold'] = True
        refs['queries'] = 0
        refs['saves'] = []
        original_spawn = bridge._spawn_unlocked

        def save(kind, raw):
            refs['saves'].append(kind)
            original_spawn(kind, raw)

        bridge._spawn_unlocked = save

        def delayed(raw):
            refs['queries'] += 1
            if refs['hold']:
                held.set()
                assert release.wait(15), 'test release timed out'
            return original_next(raw)

        bridge.next_unimported_machine = delayed
        return bridge

    def create(title, url, **kwargs):
        window = original_create('database LOCAL TEST (auto-closes)', base + LIST +
            '#database_next_machine=1&database_day=' + DAY, **kwargs)
        refs['window'] = window
        refs['cover'] = original_create('database LOCAL TEST cover',
            html='<h2>Local test cover window</h2>', hidden=True, on_top=True,
            x=kwargs['x'], y=kwargs['y'], width=650, height=550)
        return window

    bi._Bridge = bridge_factory
    webview.create_window = create

    def wait(check, label, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if check():
                return
            time.sleep(.05)
        raise AssertionError(label)

    def worker():
        try:
            wait(lambda: 'window' in refs and refs['bridge']._overlay_ready.is_set(), 'overlay ready')
            window, bridge = refs['window'], refs['bridge']
            js = window.evaluate_js
            wait(lambda: js("!!document.querySelector('#database-auto-toggle') && !document.querySelector('#database-auto-toggle').disabled"), 'button ready')
            assert not bridge.get_auto_capture()['enabled']
            assert bridge.get_auto_capture()['seconds'] == 3.5
            # Legacy hash continuation is held. Turning ON must invalidate it;
            # the scheduler must not launch a second simultaneous query.
            assert held.wait(5)
            js("document.querySelector('#database-auto-interval').value='0.1'; document.querySelector('#database-auto-toggle').click()")
            wait(lambda: bridge.get_auto_capture()['enabled'], 'ON')
            time.sleep(.4)
            assert refs['queries'] == 1, refs['queries']
            js("document.querySelector('#database-auto-toggle').click()")
            wait(lambda: not bridge.get_auto_capture()['enabled'], 'OFF')
            release.set()
            time.sleep(.5)
            assert '/rack_info_kt/' in window.get_current_url()
            assert not bridge._children
            observed['passed'].append('legacy/auto query deduplication and OFF cancels awaited result')
            # Delayed automatic selection independently of the legacy path.
            held.clear(); release.clear()
            js("document.querySelector('#database-auto-toggle').click()")
            assert held.wait(5)
            js("document.querySelector('#database-auto-toggle').click()")
            wait(lambda: not bridge.get_auto_capture()['enabled'], 'second OFF')
            release.set(); refs['hold'] = False
            time.sleep(.5)
            assert '/rack_info_kt/' in window.get_current_url()
            observed['passed'].append('OFF cancels automatic awaited selection')
            queries = refs['queries']
            js('location.reload()')
            time.sleep(.7)
            wait(lambda: bridge._overlay_ready.is_set(), 'OFF reload ready')
            assert refs['queries'] == queries and not bridge.get_auto_capture()['enabled']
            observed['passed'].append('OFF reload does not revive legacy hash continuation')
            for width, height in ((360, 300), (573, 495)):
                window.resize(width, height)
                time.sleep(.3)
                bounds = js("(() => { const b=document.querySelector('#database-auto-toggle').getBoundingClientRect(); const c=document.querySelector('#database-overlay'); return {x:b.x,y:b.y,right:b.right,bottom:b.bottom,w:innerWidth,h:innerHeight,scroll:c.scrollHeight>c.clientHeight}; })()")
                assert bounds['x'] >= 0 and bounds['y'] >= 0 and bounds['right'] <= bounds['w'] and bounds['bottom'] <= bounds['h'], bounds
                observed.setdefault('bounds', []).append(bounds)
            observed['passed'].append('stop button fits 360x300 and 573x495 windows at saved scale 1.6')
            # Do not click a challenge. The test removes its own dummy element.
            js("document.body.insertAdjacentHTML('beforeend', '<dialog open id=challenge>確認ダイアログ</dialog>'); document.querySelector('#database-auto-toggle').click()")
            wait(lambda: bridge.get_auto_capture()['enabled'], 'challenge ON')
            time.sleep(.5)
            assert not bridge._children and '/rack_info_kt/' in window.get_current_url()
            assert '確認' in bridge.get_auto_capture()['message']
            window.minimize()
            wait(lambda: str(window.native.WindowState) == 'Minimized', 'real OS minimize')
            observed['minimized_state'] = str(window.native.WindowState)
            js("document.querySelector('#challenge').remove()")

            def saved():
                db = Store(db_path)
                try:
                    rows = db.rows(DAY, 'Dummy', 'saiwaichou')
                    return len(rows) == 1 and graph_done(rows[0])
                finally:
                    db.close()

            wait(saved, 'table and graph saved while minimized', timeout=25)
            wait(lambda: '/rack_info_kt/' in window.get_current_url(), 'continued back to machine list')
            assert str(window.native.WindowState) == 'Minimized'
            assert bridge.get_auto_capture()['enabled']
            observed['passed'].append('challenge waits ON; real minimized WebView2 resumes, saves table + graph, returns to list ON')
            # OFF prevents new subprocesses. Two saves were needed, table/graph.
            bridge.set_auto_capture(False, .1)
            time.sleep(.4)
            window.restore()
            wait(lambda: str(window.native.WindowState) == 'Normal', 'restored')
            assert not bridge.get_auto_capture()['enabled']
            assert not original_bridge(db_path, folder / 'reports', __file__).get_auto_capture()['enabled']
            observed['passed'].append('OFF retained; fresh browser controller starts OFF')
            assert refs['saves'] == ['table', 'graph'], refs['saves']
            # Revisit the table as a deliberate second run with another test
            # window covering the real WebView2. All records remain temporary.
            js('location.href = ' + json.dumps(base + TABLE))
            wait(lambda: '/standlist_slot/' in window.get_current_url() and bridge._overlay_ready.is_set(), 'covered table ready')
            refs['cover'].show()
            from System import Action
            def cover_target():
                refs['cover'].native.Bounds = window.native.Bounds
                refs['cover'].native.Activate()
            refs['cover'].native.Invoke(Action(cover_target))
            wait(lambda: bool(refs['cover'].native.Visible) and bool(refs['cover'].native.TopMost)
                 and refs['cover'].native.Bounds.Contains(window.native.Bounds), 'window fully covered')
            js("document.querySelector('#database-auto-toggle').click()")
            wait(lambda: len(refs['saves']) == 3, 'capture behind cover')
            wait(lambda: '/rack_info_kt/' in window.get_current_url(), 'save finished behind cover')
            assert str(window.native.WindowState) == 'Normal' and not window.native.TopMost
            assert refs['cover'].native.Bounds.Contains(window.native.Bounds)
            assert bridge.get_auto_capture()['enabled']
            observed['passed'].append('capture + save + navigation with another window covering WebView2')
            observed['saves'] = refs['saves']
            bridge.set_auto_capture(False, .1)
            observed['requests'] = requests
        except Exception:
            import traceback
            observed['error'] = traceback.format_exc()
            observed['requests'] = requests
            if 'bridge' in refs:
                observed['connection_failure'] = refs['bridge']._connection.failure
            log_path = db_path.parent / 'errors.log'
            if log_path.exists():
                observed['fixture_errors'] = log_path.read_text(encoding='utf-8')
        finally:
            release.set()
            if 'cover' in refs:
                refs['cover'].destroy()
            if 'window' in refs:
                refs['window'].destroy()

    threading.Thread(target=worker, daemon=True).start()
    bi.run_session(db_path, folder / 'reports')
    server.shutdown()
    print(json.dumps(observed, ensure_ascii=False, indent=2), flush=True)
    assert 'error' not in observed, observed.get('error')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].startswith('--confirm-'):
        bi = localize(os.environ['DATABASE_TEST_BASE'])
        getattr(bi, '_confirm_' + sys.argv[1].split('-')[-1])(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix='tmp-auto-smoke-', dir=ROOT) as folder:
            subprocess.run([sys.executable, __file__, '--child', folder], cwd=ROOT, timeout=80, check=True)
