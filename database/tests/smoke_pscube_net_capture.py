"""Opt-in Windows check: the real PC P's CUBE window saves net medals (python tests/smoke_pscube_net_capture.py).

Runs the production run_session in real WebView2 with a temporary DB and profile. Every
request is answered inside WebView2 (WebResourceRequested, filter '*'): P's CUBE URLs from local
pseudo pages, anything else with 403. The window starts on about:blank and opens the pseudo site only
after the filter is in place, so nothing reaches the real site. No user DB, Cookies or backups are used. Checks the full auto path
(index -> table -> rack with the extra source-graph request) and that a refused source-graph
request still saves the rack with net medals left empty.
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402
import pscube_import  # noqa: E402

SHOP = '/dedamajyoho-P-townDMMpachi/c740601/'
BASE = 'https://www.pscube.jp' + SHOP + 'cgi-bin/'
INDEX = BASE + 'nc-v03-001.php?cd_ps=2'
TABLE = BASE + 'nc-v05-011.php?cd_ps=2&bai=20'
RACK = BASE + 'nc-v06-001.php?cd_dai=1120#20261001'
DAYS = [f'202609{d:02d}' for d in range(25, 31)] + ['20261001']
JQUERY = '''<script>
window.api = {apikey: 'local-key', token: {_i: 'local-i', _t: 'local-t'}};
window.jQuery = {ajax(options) {
  const done = [], fail = [], xhr = new XMLHttpRequest();
  const query = new URLSearchParams(options.data).toString();
  xhr.open('GET', options.url + '?' + query);
  xhr.timeout = options.timeout || 0;
  xhr.onload = () => xhr.status < 400 ? done.forEach(f => f(JSON.parse(xhr.responseText))) : fail.forEach(f => f(xhr));
  xhr.onerror = xhr.ontimeout = () => fail.forEach(f => f(xhr));
  xhr.send();
  const request = {done(f) { done.push(f); return request; }, fail(f) { fail.push(f); return request; }};
  return request;
}};
</script>'''
CARD = ('<li id="li-1120"><a href="' + RACK + '">1120</a><table>' + ''.join(
    f'<tr data-key="{k}"><td>{k}</td><td>{v}</td></tr>' for k, v in
    {'toku1-count': 3, 'toku5-count': 1, 'toku4-count': 0, 'sum_game': 600, 'sadama_s': 120}.items())
    + '</table><div id="ca-1120"><svg><path stroke="#f0e448" stroke-width="2" d="M0,10 L10,2 M0,0 L0,0"/>'
    '<path stroke="#ffffff" stroke-width="0" d="M0,10 L10,10"/></svg></div></li>')
PAGES = {
    SHOP + 'cgi-bin/nc-v03-001.php': '<ul id="ulKI"><li><a class="btn-ki" href="' + TABLE + '"><span class="nc-label">試験機種</span>'
                                     '<span class="nc-lower">1台</span></a></li></ul>',
    SHOP + 'cgi-bin/nc-v05-011.php': "<title>P'sCUBE｜試験機種</title><h1>SLOT</h1><li data-ymd=\"20261001\" class=\"selected\">本日</li>"
                                     '<ul>' + CARD + '</ul>',
    SHOP + 'cgi-bin/nc-v06-001.php': "<title>P'sCUBE｜試験機種</title>" + JQUERY + '<h1>SLOT</h1><h2>台番号 1120</h2><a href="' + TABLE
                                     + '">機種データ</a><table><tr>' + ''.join(
        '<td class="column"><div>' + ''.join(f'<div>{v}</div>' for v in [f'{i}日前' if i else '本日', 3, 1, 0, '1/150', 600, 120, 20])
        + '</div></td>' for i in range(7)) + '</tr></table>' + ''.join(
        f'<ul id="CHART-{DAYS[6 - i]}"><li><div id="svg{i}"><svg><path class="amcharts-graph-stroke" d="M0,10 L10,1 M0,0 L0,0"/>'
        '<path class="amcharts-axis-zero-grid" d="M0,10 L10,10"/></svg></div></li></ul>' for i in range(7)),
}
# Graph.src: day i (oldest first) goes from 1000 to 1000 + 100*i - 50; 2026-10-01 is the 1120 example (+14,118).
GRAPH = {'datas': {'g': [{'YMD_biz': int(d), 'xField': f'out-{i}', 'yField': f'value-{i}'} for i, d in enumerate(DAYS)],
                   'p': [p for i in range(6) for p in ({f'out-{i}': 0, f'value-{i}': 1000}, {f'out-{i}': 5, f'value-{i}': 1000 + 100 * i - 50})]
                   + [{'out-6': 0, 'value-6': 7092}, {'out-6': 5, 'value-6': 21210}]}}
EXPECTED = {f'{d[:4]}-{d[4:6]}-{d[6:]}': (100 * i - 50 if i < 6 else 14118) for i, d in enumerate(DAYS)}


def run(case, workdir):
    graph_status = 200 if case == 'ok' else 403
    db = Path(workdir) / 'data' / 'pscube.sqlite3'
    db.parent.mkdir(parents=True)
    seen = {'requests': [], 'graph_query': None}
    original_create = webview.create_window
    refs = {}

    def create(title, url, **options):
        window = original_create(title, 'about:blank', **options)
        refs['window'] = window
        handlers = []

        def before_show():
            control = window.native.webview

            def ready(sender, args):
                from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
                from System.IO import MemoryStream
                from System.Text import Encoding
                core = sender.CoreWebView2

                def requested(s, a):
                    uri = urlparse(str(a.Request.Uri))
                    seen['requests'].append(uri.netloc + uri.path)
                    if uri.netloc != 'www.pscube.jp':
                        status, body, kind = 403, 'blocked in the local test', 'text/plain'
                    elif uri.path.endswith('nc-m06-003.php'):
                        seen['graph_query'] = uri.query
                        status, body, kind = graph_status, json.dumps({'Graph': {'src': GRAPH}}), 'application/json'
                    elif uri.path in PAGES:
                        status, body, kind = 200, '<!doctype html><html><head><meta charset="utf-8"></head><body>' + PAGES[uri.path] + '</body></html>', 'text/html; charset=utf-8'
                    else:
                        status, body, kind = 404, 'not found', 'text/plain'
                    try:
                        stream = MemoryStream(Encoding.UTF8.GetBytes(body))
                        a.Response = core.Environment.CreateWebResourceResponse(stream, status, 'OK' if status == 200 else 'X', f'Content-Type: {kind}')
                    except Exception as error:
                        seen.setdefault('errors', []).append(repr(error)[:300])

                handlers.append(requested)
                core.AddWebResourceRequestedFilter('*', CoreWebView2WebResourceContext.All)
                seen['filter'] = True
                core.WebResourceRequested += requested

            def completed(sender, args):
                seen.setdefault('completed', []).append([bool(args.IsSuccess), str(args.WebErrorStatus), str(sender.Source)[-40:]])
            handlers.extend([ready, completed])
            control.CoreWebView2InitializationCompleted += ready
            control.NavigationCompleted += completed

        window.events.before_show += before_show
        refs['handlers'] = handlers
        return window

    webview.create_window = create
    result = {}

    def scenario():
        while 'window' not in refs:
            time.sleep(0.2)
        window = refs['window']
        while not seen.get('filter'):
            time.sleep(0.2)
        time.sleep(1)
        window.load_url(INDEX)
        deadline = time.time() + 90
        window_state = None
        while time.time() < deadline:
            time.sleep(1)
            try:
                window_state = window.evaluate_js('JSON.stringify({card: !!document.getElementById("database-pscube-card"), '
                                                  'auto: document.getElementById("database-pscube-auto")?.textContent, '
                                                  'button: document.getElementById("database-pscube-capture")?.textContent, '
                                                  'status: document.getElementById("database-pscube-auto-status")?.textContent, url: location.href})')
            except Exception as error:
                result['last_error'] = repr(error)[:300]
                continue
            state = json.loads(window_state or '{}')
            if state.get('card') and 'OFF' in (state.get('auto') or '') and not result.get('started'):
                window.evaluate_js('document.getElementById("database-pscube-auto").click()')
                result['started'] = True
            if result.get('started') and '台別7日分を保存' in (state.get('button') or ''):
                result['button'] = state['button']
                result['status'] = state.get('status')
                break
        result['last_state'] = window_state
        window.destroy()

    threading.Thread(target=scenario, daemon=True).start()
    pscube_import.run_session(db, Path(workdir) / 'data' / 'pscube-viewer.json')
    webview.create_window = original_create
    try:
        rows = [json.loads(r[0]) for r in sqlite3.connect(db).execute('SELECT payload FROM records')]
    except sqlite3.OperationalError:
        rows = []
    result['requests'] = seen['requests'][:30]
    result['handler_errors'] = seen.get('errors', [])[:3]
    result['completed'] = seen.get('completed', [])[:6]
    result['loaded_set'] = refs['window'].events.loaded.is_set()
    result['nets'] = {r['day']: r.get('net_medals') for r in rows}
    result['my'] = {r['day']: r['my'] for r in rows}
    result['graph_query'] = seen['graph_query']
    result['outside'] = sorted({p for p in seen['requests'] if not p.startswith('www.pscube.jp' + SHOP)})
    return result


if __name__ == '__main__':
    case = sys.argv[1] if len(sys.argv) > 1 else None
    if case:
        sys.stdout.reconfigure(encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='pscube-net-smoke-', ignore_cleanup_errors=True) as tmp:
            print(json.dumps(run(case, tmp), ensure_ascii=False))
        sys.exit(0)
    import subprocess
    outputs = {}
    for name in ('ok', 'refused'):
        done = subprocess.run([sys.executable, __file__, name], capture_output=True, text=True, encoding='utf-8', timeout=180)
        line = [x for x in done.stdout.splitlines() if x.startswith('{')]
        assert line, (name, done.stdout[-2000:], done.stderr[-2000:])
        outputs[name] = json.loads(line[-1])
    ok, refused = outputs['ok'], outputs['refused']
    assert ok['nets'] == EXPECTED, ok
    assert set(ok['my'].values()) == {120}, ok['my']
    assert 'cd_dai=1120' in ok['graph_query'] and 'YMD_biz=20261001' in ok['graph_query'] and 'apikey=local-key' in ok['graph_query'], ok
    assert '差枚は未取得' not in ok['button'], ok
    assert len(refused['nets']) == 7 and all(v is None for v in refused['nets'].values()), refused
    assert '差枚は未取得' in refused['button'] and 'HTTP 403' in refused['button'], refused
    print('PASS: real WebView2 auto capture saved exact net medals (MY unchanged); a refused source graph still saved the rack with net empty')
