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
                                state = options['js_api'].set_auto_capture(True, 6.5)
                                window.evaluate_js('window.__pscubeRenderAuto(' + json.dumps(state) + ')')
                                ui = window.evaluate_js('({label: document.querySelector("#database-pscube-card label").innerText, disabled: document.getElementById("database-pscube-interval").disabled, value: Number(document.getElementById("database-pscube-interval").value)})')
                                assert 5 <= state['seconds'] <= 8, state
                                assert ui['disabled'] and ui['value'] == state['seconds'], ui
                                assert '5〜8秒ランダム' in ui['label'], ui
                                options['js_api'].set_auto_capture(False, state['seconds'])
                                result['random_interval'] = ui
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
