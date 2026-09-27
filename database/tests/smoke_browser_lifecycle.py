"""Opt-in Windows/WebView2 check: py tests/smoke_browser_lifecycle.py.

Uses an empty local page and a disposable database, never the shop or user data.
The parent bounds the test so a regression in JS API injection cannot hang CI.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(folder):
    import browser_import
    import webview
    from core import Store, save_settings

    folder = Path(folder)
    db_path = folder / 'data' / 'database.sqlite3'
    db_path.parent.mkdir()
    sync = folder / 'sync'
    sync.mkdir()
    save_settings(db_path.parent, sync_dir=str(sync))
    db = Store(db_path)
    db.save([dict(store='nagamachiminami', kind_code=21, day='2026-09-27',
                  machine='テスト', rack=1, games=3000, bb=10, rb=5,
                  max_hold=500)])
    db.close()
    original_create = webview.create_window
    observed = {}

    def create(title, url, **kwargs):
        window = original_create(title, html='<html><body>Local lifecycle test</body></html>',
                                 hidden=True, **kwargs)

        def loaded():
            try:
                observed['api'] = window.evaluate_js('Object.keys(window.pywebview.api)')
                observed['checked'] = json.loads(kwargs['js_api']._checked(json.dumps(
                    dict(store='nagamachiminami', day='2026-09-27'))))
            except Exception as exc:
                observed['error'] = repr(exc)
            finally:
                # Let other loaded handlers (the real overlay) finish first.
                threading.Timer(0.5, window.destroy).start()

        window.events.loaded += loaded
        return window

    webview.create_window = create
    browser_import.is_allowed_url = lambda url: True  # only this local test page
    browser_import.run_session(db_path, folder / 'reports')
    assert 'error' not in observed, observed
    assert 'submit_table' in observed.get('api', []), observed
    assert 'submit_graph' in observed['api'], observed
    assert all('.' not in name for name in observed['api']), observed
    viewer = json.loads((sync / 'database-viewer.json').read_text(encoding='utf-8'))
    assert len(viewer['records']) == 1
    assert any(e['day'] == '2026-09-27' and e['name'] == '超探す楽しみ'
               for e in viewer['date_events'])
    assert (sync / 'database-backup-auto.json').exists()
    print('PASS: API ready, browser closed, backup completed, event exported', flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix='tmp-browser-smoke-', dir=ROOT) as folder:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', folder],
                           cwd=ROOT, timeout=45, check=True)
