"""Explicit --smoke-local diagnostics for packaged Windows apps.

Uses a new temporary directory and an inline page, never the default databases
or site profiles. Normal application entry points do not call this module.
"""
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


def _pscube_direction_walk(module, bridge, folder):
    """凍結版の中のコードで「下から取り込む」→ 保存 → 次のページ を最後まで（合成のページ、実サイトには繋がない）。

    開始ボタンと同じ `set_auto_capture(True, 秒, '', 'bottom')` のあと、保存のたびに返る次のURLを開いたことにして
    続け、機種が一覧の下から（C→B→A）取られ、途中で上からに戻らないことを確かめる（2026-10-06）。
    """
    from urllib.parse import quote
    root, day = module.ROOT_URL, module.recent_business_days()[1]
    index = root + 'cgi-bin/nc-v03-001.php?cd_ps=2'
    names = ('A', 'B', 'C')
    table = {n: root + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu={quote(n)}' for n in names}
    rack_of = {n: 100 + i for i, n in enumerate(names)}

    def machine(n, listed):
        return {'store': 'c740601', 'rate': '20', 'machine': n, 'expected_count': 1 if listed else None, 'url': table[n]}

    def record(n, on):
        return {'store': 'c740601', 'rate': '20', 'machine': n, 'rack': rack_of[n], 'day': on, 'bb': 3, 'rb': 1,
                'at_art': 0, 'games': 2000, 'my': 100, 'observed_at': f'{day}T23:12:00+09:00',
                'detail_url': root + f'cgi-bin/nc-v06-001.php?cd_dai={rack_of[n]}#{on.replace("-", "")}',
                'graph': {'kind': 'overview', 'zero_y': 10, 'points': [[0, 10], [1, 8]]}}

    def page(url):
        data = {'format': 'pscube-viewer', 'version': 1, 'source_url': url, 'machines': [], 'records': []}
        if url == index:
            data['machines'] = [machine(n, True) for n in names]
            return data, '一覧'
        if url in table.values():
            n = next(k for k, v in table.items() if v == url)
            data.update(machines=[machine(n, False)], records=[record(n, day)])
            return data, n + '表'
        n = next(k for k, r in rack_of.items() if f'cd_dai={r}#' in url)
        start = module.date.fromisoformat(day)
        data.update(machines=[machine(n, False)],
                    records=[record(n, (start - module.timedelta(days=i)).isoformat()) for i in range(7)])
        return data, str(rack_of[n])

    db, export = folder / 'data' / 'direction.sqlite3', folder / 'data' / 'direction.json'
    pilot = bridge.pilot
    state = bridge.set_auto_capture(True, 20, '', 'bottom')
    assert state['enabled'] and state['direction'] == 'bottom', state
    visited, url = [], index
    try:
        for _ in range(12):
            data, name = page(url)
            visited.append(name)
            saved = module.submit_capture(db, export, pilot, data, url)
            pilot.finished(result=saved)
            assert saved['direction'] == 'bottom' == pilot.direction, saved
            url = saved['next_url']
            if url is None:
                break
    finally:
        bridge.set_auto_capture(False, 20)
    assert visited == ['一覧', 'C表', '102', 'B表', '101', 'A表', '100'], visited
    return visited


def run(module, kind, output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {'kind': kind, 'frozen': bool(getattr(sys, 'frozen', False))}
    try:
        # WebView2 may flush its disposable profile after the window closes.
        # A locked test file can remain here; never force-close user browsers.
        with tempfile.TemporaryDirectory(prefix='tmp-exe-smoke-', dir=output.parent,
                                         ignore_cleanup_errors=True) as folder:
            folder = Path(folder)
            (folder / 'data').mkdir()
            if kind == 'main':
                result['normal_runtime_root'] = str(module.ROOT.resolve())
                module.ROOT, module.DATA_DIR = folder, folder / 'data'
                children = []
                original_popen, original_tk = subprocess.Popen, module.tk.Tk

                def launch(command, **options):
                    assert Path(command[1]).parent == folder / 'data', command
                    exe = Path(command[0])
                    assert exe.is_file(), exe
                    child_output = output.with_name(exe.stem + '-smoke.json')
                    children.append((original_popen([str(exe), '--smoke-local', str(child_output)],
                                                    cwd=options['cwd']), child_output))
                    result.setdefault('helper_commands', []).append(command)
                    return children[-1][0]

                def create():
                    root = original_tk()
                    def exercise():
                        try:
                            widgets = []
                            def walk(widget):
                                widgets.append(widget)
                                for child in widget.winfo_children():
                                    walk(child)
                            walk(root)
                            gradient = next(w for w in widgets if isinstance(w, module.GradientButton))
                            gradient.command()
                            button = next(w for w in widgets if isinstance(w, module.ttk.Button)
                                          and w.cget('text') == 'P’s CUBE（スロット）を取り込む')
                            button.invoke()
                            result['main_window'] = root.title()
                            assert len(children) == 2, children
                        except Exception as error:
                            result['error'] = repr(error)
                        finally:
                            root.destroy()
                    root.after(600, exercise)
                    return root

                subprocess.Popen, module.tk.Tk = launch, create
                try:
                    module.main()
                finally:
                    subprocess.Popen, module.tk.Tk = original_popen, original_tk
                for process, child_output in children:
                    try:
                        assert process.wait(timeout=35) == 0, child_output
                        child_result = json.loads(child_output.read_text(encoding='utf-8'))
                        assert child_result.get('passed'), child_result
                        result.setdefault('helpers', []).append(child_result)
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
            else:
                import webview
                original_create = webview.create_window
                windows = []
                content = ('<!doctype html><meta http-equiv="Content-Security-Policy" '
                           'content="default-src \'none\'; script-src \'unsafe-inline\' \'unsafe-eval\'">'
                           '<h2>database LOCAL packaged WebView2 test</h2>')
                if kind == 'meruhen':
                    module.is_allowed_url = lambda url: str(url).startswith('about:blank')
                def create(title, ignored_url, **options):
                    window = original_create('database LOCAL packaged test', html=content, **options)
                    windows.append(window)
                    def loaded():
                        try:
                            from System import Action
                            api = window.evaluate_js('Object.keys(window.pywebview.api)')
                            assert 'retry_page' in api, api
                            native = []
                            window.native.Invoke(Action(lambda: native.append(
                                str(window.native.webview.CoreWebView2.Environment.BrowserVersionString))))
                            result.update(api=api, webview2_version=native[0])
                            if kind == 'pscube':
                                # Exercise the packaged card on this inline page only.
                                window.evaluate_js(module.overlay_script(
                                    module.CAPTURE.read_text(encoding='utf-8'), module.ROOT_URL))
                                state = options['js_api'].set_auto_capture(True, 20)
                                window.evaluate_js('window.__pscubeRenderAuto(' + json.dumps(state) + ')')
                                ui = window.evaluate_js('({label: document.querySelector("#database-pscube-card label").innerText, disabled: document.getElementById("database-pscube-interval").disabled, value: Number(document.getElementById("database-pscube-interval").value)})')
                                assert 15 <= state['seconds'] <= 25, state
                                assert ui['disabled'] and ui['value'] == state['seconds'], ui
                                assert '15〜25秒ランダム' in ui['label'], ui
                                options['js_api'].set_auto_capture(False, state['seconds'])
                                result['random_interval'] = ui
                                result['direction_walk'] = _pscube_direction_walk(module, options['js_api'], folder)
                        except Exception as error:
                            result['error'] = repr(error)
                        finally:
                            threading.Timer(.5, window.destroy).start()
                    window.events.loaded += loaded
                    return window
                webview.create_window = create
                try:
                    module.run_session(folder / 'data' / (kind + '.sqlite3'), folder / 'reports' if kind == 'meruhen' else folder / 'viewer.json')
                finally:
                    webview.create_window = original_create
                assert result.get('webview2_version'), result
            assert 'error' not in result, result
        result['passed'] = True
    except Exception:
        import traceback
        result['error'] = traceback.format_exc()
        result['passed'] = False
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if not result.get('passed'):
        raise SystemExit(1)
