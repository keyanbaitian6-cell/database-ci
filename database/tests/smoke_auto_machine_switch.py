"""Two-machine WebView2 auto-capture regression with localhost pages and a temporary DB.

The second machine's row deliberately ignores a synthetic click. The app must
keep the saved day and open its table instead of remaining on the list.
Run: .runtime/Scripts/python.exe tests/smoke_auto_machine_switch.py
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
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DAY = '2026-09-30'
LIST = '/saiwaichou/rack_info_kt/?kind_code=21'


def localize(base):
    import browser_import as bi
    import collector
    collector.HOST = '127.0.0.1'
    bi.is_allowed_url = lambda url: url.startswith(base + '/')
    bi.machine_list_url = lambda store, day: base + LIST + '#database_next_machine=1&database_day=' + day
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
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if '/standlist_slot/' in url.path:
                machine = query.get('machine_name', [''])[0]
                if query.get('target_date') != [DAY]:
                    content = '<p>該当する台情報がありません</p>'
                else:
                    rack = 711 if machine == 'Dummy2' else 710
                    graph = f'/saiwaichou/standgraph/?rack_no={rack}&target_date={DAY}'
                    content = ('<table><tr>' + ''.join('<th>' + h + '</th>' for h in
                        ['台番号', 'BB', 'RB', '総回転数', '合成確率', '前日最終スタート', '最大持玉']) +
                        f'</tr><tr><td><a href="{graph}">{rack}</a></td>' +
                        '<td>10</td><td>5</td><td>3000</td><td>1/200</td><td>0</td><td>500</td></tr></table>')
            elif '/standgraph/' in url.path:
                content = '''<svg class="today" viewBox="0 0 300 150" width="300" height="150">
                  <g class="path-slump"><path d="M0 75 L30 70 L60 80 L90 65 L120 55 L150 70 L180 60 L210 50 L240 45 L270 40 L300 35"/></g>
                  <g class="back-line-middle"><line y1="75"/></g>
                  <text class="info_soukaiten">3000</text><text class="info_big">10</text>
                  <text class="info_reg">5</text><text class="info_max_mochidama">500</text></svg>'''
            else:
                first = f'/saiwaichou/standlist_slot/?kind_code=21&machine_name=Dummy&target_date={DAY}'
                content = ('<table><tr><th>機種名</th><th>台数</th></tr>' +
                    f'<tr class="teram2-link-block" onclick="location.href=\'{first}\'">' +
                    '<td><span class="wrap-machine-name">Dummy</span></td><td>1台</td></tr>' +
                    '<tr class="teram2-link-block" onclick="window.__dummySecondClicks=(window.__dummySecondClicks||0)+1">' +
                    '<td><span class="wrap-machine-name">Dummy2</span></td><td>1台</td></tr></table>')
            body = ('<!doctype html><meta charset="utf-8"><title>database LOCAL TWO MACHINES</title>'
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
    observed = {}
    refs = {'saves': []}

    def bridge_factory(*args, **kwargs):
        bridge = original_bridge(*args, **kwargs)
        bridge._script_path = str(Path(__file__).resolve())
        original_spawn = bridge._spawn_unlocked
        def save(kind, raw):
            refs['saves'].append(kind)
            original_spawn(kind, raw)
        bridge._spawn_unlocked = save
        refs['bridge'] = bridge
        return bridge

    def create(title, url, **kwargs):
        window = original_create('database LOCAL TWO MACHINES (auto-closes)',
            base + LIST + '#database_next_machine=1&database_day=' + DAY, **kwargs)
        refs['window'] = window
        return window

    bi._Bridge = bridge_factory
    webview.create_window = create

    def wait(check, label, timeout=35):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if check():
                return
            time.sleep(.05)
        raise AssertionError(label)

    def both_saved():
        store = Store(db_path)
        try:
            return all((lambda rows: len(rows) == 1 and graph_done(rows[0]))(
                store.rows(DAY, machine, 'saiwaichou')) for machine in ('Dummy', 'Dummy2'))
        finally:
            store.close()

    def worker():
        try:
            wait(lambda: 'window' in refs and refs['bridge']._overlay_ready.is_set(), 'overlay ready')
            window, bridge = refs['window'], refs['bridge']
            js = window.evaluate_js
            wait(lambda: js("!!document.querySelector('#database-auto-toggle') && !document.querySelector('#database-auto-toggle').disabled"), 'button ready')
            js("document.querySelector('#database-auto-interval').value='0.1'; document.querySelector('#database-auto-toggle').click()")
            wait(lambda: bridge.get_auto_capture()['enabled'], 'ON')
            window.minimize()
            wait(lambda: str(window.native.WindowState) == 'Minimized', 'minimized')
            wait(lambda: (js('window.__dummySecondClicks || 0') or 0) >= 1, 'second machine row was clicked')
            js("document.querySelector('#database-auto-toggle').click()")
            wait(lambda: not bridge.get_auto_capture()['enabled'], 'OFF before delayed fallback')
            time.sleep(3.4)
            assert '/rack_info_kt/' in window.get_current_url()
            assert not any('/standlist_slot/' in path and 'machine_name=Dummy2' in path for path in requests)
            js("document.querySelector('#database-auto-toggle').click()")
            wait(lambda: bridge.get_auto_capture()['enabled'], 'ON again')
            wait(both_saved, 'two different machines saved automatically', timeout=45)
            wait(lambda: '/rack_info_kt/' in window.get_current_url(), 'returned to machine list')
            assert bridge.get_auto_capture()['enabled']
            assert str(window.native.WindowState) == 'Minimized'
            assert refs['saves'] == ['table', 'graph', 'table', 'graph'], refs['saves']
            assert any('/standlist_slot/' in path and 'machine_name=Dummy2' in path and 'target_date=' + DAY in path for path in requests)
            observed['passed'] = 'minimized: OFF canceled delayed move; ON resumed; two machines saved despite second row click failure; ON retained'
            observed['saves'] = refs['saves']
            observed['requests'] = requests
        except Exception:
            import traceback
            observed['error'] = traceback.format_exc()
            observed['requests'] = requests
        finally:
            if 'bridge' in refs:
                refs['bridge'].set_auto_capture(False, .1)
                time.sleep(.2)
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
        with tempfile.TemporaryDirectory(prefix='tmp-auto-machine-', dir=ROOT) as folder:
            subprocess.run([sys.executable, __file__, '--child', folder], cwd=ROOT, timeout=90, check=True)
