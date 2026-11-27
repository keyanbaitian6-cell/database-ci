"""Opt-in real WebView2 test of 「メルヘン2店舗を一括取り込み」（2026-11-28）.

Run (PC only, opens real windows for a few minutes):
    database/.venv/Scripts/python.exe database/tests/smoke_meruhen_bulk.py

The PC app runs from a disposable copy of database/ with an empty data folder, so the real databases, settings,
sync folders and sites are never used. The app's real 「メルヘン2店舗を一括取り込み」 button opens six real
capture windows, three per store: top, bottom, from the 10th machine (production run_session, BulkStart, auto
capture, save subprocesses). Only the site origin is changed to a localhost fixture serving both stores (entry
page, a machine list of 12, tables, graphs, and a human-check page that reloads itself until the test marks it as
done, as a person would).

Checked: six windows in order with one shared business day and the right stores/directions; a quick double
press opens no extra window; a human check at the start of all three 幸町 windows at once (shown in the app as
「人間認証待ち」, while 長町南 keeps saving); automatic continuation after the check without pressing start;
a human check in the middle of a run; closing one window with × (shown as 中断, nothing lost, the other window
of the store finishes the rest); saved rows per store/day; the individual 「メルヘンワールドを取り込む」 still opens.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

HERE = Path(__file__).resolve()
SOURCE = HERE.parents[1]
MACHINES = {'nagamachiminami': [f'A{i:02d}' for i in range(1, 13)], 'saiwaichou': [f'B{i:02d}' for i in range(1, 13)]}
RACKS = {('nagamachiminami', m): 101 + i for i, m in enumerate(MACHINES['nagamachiminami'])}
RACKS.update({('saiwaichou', m): 201 + i for i, m in enumerate(MACHINES['saiwaichou'])})
CATEGORY = {'nagamachiminami': '1000円46枚スロット', 'saiwaichou': 'ハイスロ'}


def localize(base):
    """Production modules, only the origin moved to the localhost fixture (same idea as smoke_auto_capture.py)."""
    import browser_import as bi
    import collector
    collector.HOST = '127.0.0.1'
    stores = tuple(bi.BROWSER_URLS)

    def allowed(url):
        if not isinstance(url, str) or not url.startswith(base + '/'):
            return False
        return url[len(base) + 1:].split('/')[0].split('?')[0] in stores
    for store in stores:
        old = bi.BROWSER_URLS[store]
        bi.BROWSER_URLS[store] = base + f'/{store}/rack_info'
        bi.OVERLAY_JS = bi.OVERLAY_JS.replace(old, bi.BROWSER_URLS[store])
    bi.DEFAULT_START = bi.BROWSER_URLS['nagamachiminami']
    bi.is_allowed_url = allowed
    bi.machine_list_page = lambda store: base + f'/{store}/rack_info_kt/?kind_code=21'
    bi.machine_list_url = lambda store, day, after=None: (
        base + f'/{store}/rack_info_kt/?kind_code=21#database_next_machine=1&database_day={day}'
        + (f'&database_after={quote(after, safe="")}' if after else ''))
    return bi


def window_child(args):
    """One capture window started by the app (production command line after the script name)."""
    sys.path.insert(0, os.environ['DATABASE_TEST_COPY'])
    bi = localize(os.environ['DATABASE_TEST_BASE'])
    positional, store, bulk, slot = bi.parse_session_args(args)
    pids = Path(os.environ['DATABASE_TEST_FOLDER']) / 'pids'
    pids.mkdir(exist_ok=True)
    (pids / f'{positional[2]}.json').write_text(json.dumps({'pid': os.getpid(), 'store': store, 'bulk': bulk}),
                                                encoding='utf-8')
    original = bi._Bridge
    real_flash = bi.flash_taskbar

    def flash(title, on, pid=None):
        found = real_flash(title, on, pid)  # the real FlashWindowEx on this real window
        with (Path(os.environ['DATABASE_TEST_FOLDER']) / 'pids' / f'{positional[2]}.flash').open('a', encoding='utf-8') as out:
            out.write(json.dumps({'title': title, 'on': on, 'found': found}, ensure_ascii=False) + '\n')
        return found
    bi.flash_taskbar = flash

    def bridge(*a, **k):
        value = original(*a, **k)
        value._script_path = str(HERE)  # save subprocesses go through this script too (localized)
        return value
    bi._Bridge = bridge
    bi.run_session(Path(positional[0]), Path(positional[1]), positional[2], store=store, bulk=bulk, slot=slot)


class Site:
    """Both stores on localhost. A human check is a page that reloads itself every second until 'done'."""

    def __init__(self):
        self.lock = threading.Lock()
        self.requests = []
        self.challenge = {('entry', 'saiwaichou'): True}  # 幸町の入口：最初から人間認証
        self.armed = None   # 途中の人間認証を出す機種（次にその表が求められたら出す）

    def page(self, path_qs):
        url = urlparse(path_qs)
        store = url.path.strip('/').split('/')[0]
        query = parse_qs(url.query)
        with self.lock:
            self.requests.append(path_qs)
            if url.path.endswith('/rack_info') and self.challenge.get(('entry', store)):
                return self.human_check()
            machine = query.get('machine_name', [''])[0]
            if '/standlist_slot/' in url.path and self.armed == (store, machine):
                self.challenge[('table', store, machine)] = True
                self.armed = None
            if '/standlist_slot/' in url.path and self.challenge.get(('table', store, machine)):
                return self.human_check()
        if url.path.endswith('/rack_info'):
            return (f'<a href="/{store}/rack_info_kt/?kind_code=4">パチンコ</a><br>'
                    f'<a href="/{store}/rack_info_kt/?kind_code=21">{CATEGORY[store]}</a>')
        if url.path.endswith('/rack_info_kt/'):
            return '<table>' + ''.join(
                f'<tr><td><a href="/{store}/standlist_slot/?kind_code=21&machine_name={quote(m)}">{m}</a></td>'
                f'<td>1台</td></tr>' for m in MACHINES[store]) + '</table>'
        day = query.get('target_date', [''])[0]
        if '/standlist_slot/' in url.path:
            rack = RACKS[(store, machine)]
            content = '<table><tr>' + ''.join('<th>' + h + '</th>' for h in
                ['台番号', 'BB', 'RB', '総回転数', '合成確率', '前日最終スタート', '最大持玉'])
            content += (f'</tr><tr><td><a href="/{store}/standgraph/?rack_no={rack}&target_date={day}">{rack}</a></td>'
                        '<td>10</td><td>5</td><td>3000</td><td>1/200</td><td>0</td><td>500</td></tr></table>')
            return content
        if '/standgraph/' in url.path:
            return '''<svg class="today" viewBox="0 0 300 150" width="300" height="150">
              <g class="path-slump"><path d="M0 75 L30 70 L60 80 L90 65 L120 55 L150 70 L180 60 L210 50 L240 45 L270 40 L300 35"/></g>
              <g class="back-line-middle"><line y1="75"/></g>
              <text class="info_soukaiten">3000</text><text class="info_big">10</text>
              <text class="info_reg">5</text><text class="info_max_mochidama">500</text></svg>'''
        return 'not found'

    @staticmethod
    def human_check():
        return '<meta http-equiv="refresh" content="1"><h2>人間であることを確認しています（LOCAL TEST）</h2>'

    def done(self, key):
        with self.lock:
            self.challenge.pop(key, None)

    def table_requests(self, store):
        with self.lock:
            return [parse_qs(urlparse(r).query).get('machine_name', [''])[0] for r in self.requests
                    if r.startswith(f'/{store}/standlist_slot/')]

    def serve(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = ('<!doctype html><meta charset="utf-8"><title>database LOCAL TEST</title><body>'
                        '<h3>LOCAL DUMMY — real sites are not used</h3>' + site.page(self.path) + '</body>').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Security-Policy', "default-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                                 "connect-src 'none'; img-src 'none'; frame-src 'none'")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return 'http://127.0.0.1:' + str(server.server_port)


def app_child(folder):
    folder = Path(folder)
    copy = folder / 'app'
    shutil.copytree(SOURCE, copy, ignore=shutil.ignore_patterns(
        'tests', '.venv', '.runtime', 'data', 'reports', 'bin', '__pycache__', '*.md', 'chrome_extension'))
    (copy / 'data').mkdir()
    site = Site()
    base = site.serve()
    os.environ.update(DATABASE_TEST_BASE=base, DATABASE_TEST_COPY=str(copy), DATABASE_TEST_FOLDER=str(folder))
    sys.path.insert(0, str(copy))
    os.chdir(copy)
    import tkinter as tk
    import app
    assert Path(app.ROOT).resolve() == copy.resolve(), app.ROOT  # the real data folder is never used
    from core import Store, graph_done
    Store(app.DATA_DIR / 'database.sqlite3').close()
    import browser_import as bi
    launched = []

    def command(window_id):
        launched.append(window_id)
        return [sys.executable, str(HERE), '--window', str(app.DATA_DIR / 'database.sqlite3'),
                str(app.ROOT / 'reports'), window_id]
    app.meruhen_browser_command = command
    results = {'passed': []}
    roots = []
    original_init = tk.Tk.__init__

    def init(self, *a, **k):
        original_init(self, *a, **k)
        roots.append(self)
        self.after(1500, lambda: run_driver(self))
    tk.Tk.__init__ = init

    def widgets(widget):
        yield widget
        for child in widget.winfo_children():
            yield from widgets(child)

    def statuses():
        found = {}
        for path in (app.DATA_DIR / bi.BULK_FOLDER).glob('*.json'):
            try:
                found[path.stem] = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        return found

    def by_label(label):
        store = {'長町南': 'nagamachiminami', '幸町': 'saiwaichou'}[label.split('・')[0]]
        direction = {'上': 'top', '下': 'bottom', '10機種目から': 'tenth'}[label.split('・')[1]]
        for wid, s in statuses().items():
            if (s.get('store'), s.get('direction')) == (store, direction):
                return wid, s
        return None, {}

    def app_rows(root):
        return [w.cget('text') for w in widgets(root) if w.winfo_class() == 'TLabel'
                and str(w.cget('text')).startswith(('長町南・', '幸町・'))]

    def saved(store):
        db = Store(app.DATA_DIR / 'database.sqlite3')
        try:
            done = set()
            for machine in MACHINES[store]:
                rows = db.rows(day, machine, store)
                if rows and all(graph_done(r) for r in rows):
                    done.add(machine)
            return done
        finally:
            db.close()

    def log_text(root):
        return '\n'.join(w.get('1.0', 'end') for w in widgets(root) if w.winfo_class() == 'Text')

    day = bi.today_iso()

    def steps(root):
        def until(check, label, timeout=90):
            end = time.monotonic() + timeout
            while not check():
                if time.monotonic() > end:
                    raise AssertionError('timeout: ' + label + ' / rows=' + repr(app_rows(root))
                                         + ' / statuses=' + repr({k: (v.get('store'), v.get('direction'), v.get('state'), v.get('message')) for k, v in statuses().items()}))
                yield 300

        button = next(w for w in widgets(root) if w.winfo_class() == 'TButton' and '一括取り込み' in str(w.cget('text')))
        button.invoke()
        button.invoke()  # 連打
        yield from until(lambda: len(statuses()) == 6, 'six status files')
        yield 2000
        assert len(launched) == 6, launched
        order = [(statuses()[w]['store'], statuses()[w]['direction']) for w in launched]
        assert order == list(bi.BULK_ORDER), order
        assert {s['day'] for s in statuses().values()} == {day}, statuses()
        results['passed'].append('one press (+ a quick second press) opened exactly 6 windows (3 per store) in order, one shared day ' + day)
        # 幸町の3窓は同時に人間認証待ち。そのあいだ長町南は保存を進める。
        S = ('幸町・上', '幸町・下', '幸町・10機種目から')
        N = ('長町南・上', '長町南・10機種目から')
        yield from until(lambda: all(by_label(x)[1].get('state') == 'auth' for x in S),
                         'all three 幸町 windows waiting for the human check')
        yield from until(lambda: len(saved('nagamachiminami')) >= 1, '長町南 saves while 幸町 waits')
        rows = app_rows(root)
        assert all(any(r.startswith(x + '　人間認証待ち') for r in rows) for x in S), rows
        assert by_label('幸町・上')[1].get('state') == 'auth', '幸町 must still wait'
        results['passed'].append('all three 幸町 windows showed 人間認証待ち at once in the app while 長町南 kept saving: ' + repr(rows))
        # 1窓だけ×で閉じる（長町南・下）。中断として出て、残りは長町南・上が取る。
        wid, status = by_label('長町南・下')
        subprocess.run(['taskkill', '/PID', str(status['pid'])], capture_output=True)  # WM_CLOSE, like ×
        yield from until(lambda: any(r.startswith('長町南・下　中断') for r in app_rows(root)), '長町南・下 shown as 中断')
        results['passed'].append('closing 長町南・下 with × shown as 中断 in the app')
        # 途中の人間認証：長町南・上が次に開く機種の表で出す
        # まだどの窓も表を開いていない機種のうち、一覧の上から最初のもの（長町南・上が次に開く）
        requested = set(site.table_requests('nagamachiminami'))
        remaining = [m for m in MACHINES['nagamachiminami'] if m not in requested]
        assert remaining, 'no machine left for the mid-run check'
        site.armed = ('nagamachiminami', remaining[0])
        # 幸町の人間認証を本人が済ませた（ページが通常の画面に戻る）。開始は押し直さない。
        site.done(('entry', 'saiwaichou'))
        yield from until(lambda: all(by_label(x)[1].get('state') in ('running', 'done') for x in S),
                         '幸町 continues automatically after the check')
        results['passed'].append('幸町 windows continued after the human check without pressing start')
        for label in S:
            wid, _ = by_label(label)
            log = Path(os.environ['DATABASE_TEST_FOLDER']) / 'pids' / f'{wid}.flash'
            yield from until(lambda: log.exists() and len(log.read_text(encoding='utf-8').splitlines()) >= 2, label + ' flash log')
            events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            assert events[0]['on'] is True and events[0]['found'] is True and label in events[0]['title'], events
            assert events[1]['on'] is False, events
        results['passed'].append('taskbar flash started on the real 幸町 windows while waiting and stopped after the check')
        yield from until(lambda: any(by_label(x)[1].get('state') == 'auth' for x in N), 'human check in the middle of 長町南')
        waiting = next(x for x in N if by_label(x)[1].get('state') == 'auth')
        before = len(saved('saiwaichou'))
        yield from until(lambda: len(saved('saiwaichou')) > before, '幸町 keeps saving while 長町南 waits')
        assert any(r.startswith(waiting + '　人間認証待ち') for r in app_rows(root)), app_rows(root)
        results['passed'].append('human check in the middle of ' + waiting + ' shown in the app; 幸町 kept saving')
        site.done(('table', 'nagamachiminami', remaining[0]))
        yield from until(lambda: saved('nagamachiminami') == set(MACHINES['nagamachiminami'])
                         and saved('saiwaichou') == set(MACHINES['saiwaichou']), 'all machines of both stores saved', timeout=240)
        yield from until(lambda: sum(1 for r in app_rows(root) if r.split('　')[1:2] == ['完了']) == 5,
                         'five windows 完了', timeout=120)
        rows = app_rows(root)
        assert any(r.startswith('長町南・下　中断') for r in rows), rows
        assert all(any(r.startswith(x + '　完了') for r in rows) for x in N + S), rows
        results['passed'].append('final rows: ' + repr(rows))
        # 保存結果：店・営業日ごとに全機種、台は1台ずつ（重複なし）、上下の向き
        db = Store(app.DATA_DIR / 'database.sqlite3')
        try:
            for store in MACHINES:
                for machine in MACHINES[store]:
                    rows_ = db.rows(day, machine, store)
                    assert [int(r['rack']) for r in rows_] == [RACKS[(store, machine)]], (store, machine, rows_)
                other = 'saiwaichou' if store == 'nagamachiminami' else 'nagamachiminami'
                assert all(not db.rows(day, m, other) for m in MACHINES[store]), 'saved under the wrong store'
        finally:
            db.close()
        for store in MACHINES:
            firsts = []
            for name in site.table_requests(store):
                if name not in firsts:
                    firsts.append(name)
            assert set(firsts[:3]) == {MACHINES[store][0], MACHINES[store][-1], MACHINES[store][9]}, (store, firsts)
        results['passed'].append('saved rows match store/day for all machines; the first tables per store were the top, bottom and 10th machines')
        assert 'メルヘン（長町南・上）' in log_text(root) or '長町南・上' in log_text(root)
        # 個別の「メルヘンワールドを取り込む」もこれまでどおり開く
        before = len(launched)
        entries = len([r for r in site.requests if r.startswith('/nagamachiminami/rack_info')])
        single = next(w for w in widgets(root) if getattr(w, 'command', None) and 'GradientButton' in type(w).__name__)
        single.command()
        yield from until(lambda: len(launched) == before + 1, 'individual window launched')
        yield from until(lambda: len([r for r in site.requests if r.startswith('/nagamachiminami/rack_info')]) > entries,
                         'individual window opened 長町南')
        pid_file = Path(os.environ['DATABASE_TEST_FOLDER']) / 'pids' / f'{launched[-1]}.json'
        yield from until(pid_file.exists, 'individual pid')
        info = json.loads(pid_file.read_text(encoding='utf-8'))
        assert info['store'] is None and info['bulk'] is None, info
        assert len(statuses()) == 6  # the individual window has no bulk status
        subprocess.run(['taskkill', '/PID', str(info['pid'])], capture_output=True)
        yield from until(lambda: 'メルヘンの取り込み画面を閉じました' in log_text(root), 'individual window closed')
        results['passed'].append('individual 「メルヘンワールドを取り込む」 still opens 長町南 without bulk options')

    def run_driver(root):
        gen = steps(root)

        def tick():
            try:
                delay = next(gen)
            except StopIteration:
                finish()
                return
            except Exception:  # noqa: BLE001
                import traceback
                results['error'] = traceback.format_exc()
                finish()
                return
            root.after(delay, tick)
        root.after(100, tick)

    def finish():
        results['requests'] = len(site.requests)
        errors = app.DATA_DIR / 'errors.log'
        if errors.exists():
            results['errors_log'] = errors.read_text(encoding='utf-8')[-3000:]
        for pid_file in (Path(os.environ['DATABASE_TEST_FOLDER']) / 'pids').glob('*.json'):
            try:
                subprocess.run(['taskkill', '/F', '/PID', str(json.loads(pid_file.read_text())['pid'])], capture_output=True)
            except (OSError, ValueError):
                pass
        (folder / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
        os._exit(0)

    app.main()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].startswith('--confirm-'):
        sys.path.insert(0, os.environ['DATABASE_TEST_COPY'])
        bi = localize(os.environ['DATABASE_TEST_BASE'])
        getattr(bi, '_confirm_' + sys.argv[1].split('-')[-1])(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) > 1 and sys.argv[1] == '--window':
        window_child(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == '--app':
        app_child(sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix='tmp-bulk-smoke-', ignore_cleanup_errors=True) as folder:
            subprocess.run([sys.executable, str(HERE), '--app', folder], timeout=600)
            result = json.loads((Path(folder) / 'results.json').read_text(encoding='utf-8'))
            print(json.dumps(result, ensure_ascii=False, indent=1))
            assert 'error' not in result, result['error']
            print('SMOKE PASSED:', len(result['passed']), 'checks')
