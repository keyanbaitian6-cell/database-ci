"""Opt-in WebView2 delayed-list regression; inline page and temporary DB only."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(folder):
    import webview
    from pscube_import import PscubeStore, ROOT_URL, SCROLL_SCRIPT, installation_count

    folder = Path(folder)
    db_path = folder / 'fixture.sqlite3'
    url = ROOT_URL + 'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=fixture'
    db = PscubeStore(db_path)
    try:
        db.import_page({'format': 'pscube-viewer', 'version': 1,
                        'source_url': ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2',
                        'machines': [{'store': 'c740601', 'rate': '20', 'machine': 'Fixture',
                                      'expected_count': 31, 'url': url}], 'records': []},
                       ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2')
    finally:
        db.close()
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    observed = {}

    class Api:
        def get_installation_count(self):
            return installation_count(db_path, url)

        def finished(self, count):
            observed['count'] = count
            threading.Timer(.5, window.destroy).start()
            return True

        def failed(self, error):
            observed['error'] = error
            threading.Timer(.5, window.destroy).start()
            return True

    html = ('<!doctype html><meta http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; script-src \'unsafe-inline\' \'unsafe-eval\'">'
            '<ul>' + ''.join(f'<li id="li-{n}">{n}</li>' for n in range(1, 7)) + '</ul>')
    window = webview.create_window('LOCAL Pscube delayed list regression', html=html, js_api=Api())
    script = '''(async () => {
      try {
        const expectedCount = await window.pywebview.api.get_installation_count();
        let requested = false;
        window.scrollTo = () => {
          if (requested) return;
          requested = true;
          setTimeout(() => {
            for (let n = 7; n <= 31; n++) {
              const card = document.createElement('li'); card.id = 'li-' + n;
              document.querySelector('ul').append(card);
            }
          }, 3000);
        };
        await SCROLL;
        await window.pywebview.api.finished(document.querySelectorAll('li').length);
      } catch (error) { await window.pywebview.api.failed(String(error)); }
    })()'''.replace('SCROLL', SCROLL_SCRIPT)

    def loaded():
        try:
            from System import Action
            versions = []
            window.native.Invoke(Action(lambda: versions.append(
                str(window.native.webview.CoreWebView2.Environment.BrowserVersionString))))
            observed['webview2_version'] = versions[0]
            window.evaluate_js(script)
        except Exception as error:
            observed['error'] = repr(error)
            threading.Timer(.5, window.destroy).start()

    window.events.loaded += loaded
    watchdog = threading.Timer(20, window.destroy)
    watchdog.start()
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=str(folder / 'profile'))
    finally:
        watchdog.cancel()
    assert 'error' not in observed and observed.get('count') == 31, observed
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    print('PASS: WebView2', observed['webview2_version'],
          'waits for delayed 6 -> 31 cards using the read-only installation count; temporary DB unchanged')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix='tmp-pscube-list-', dir=ROOT,
                                         ignore_cleanup_errors=True) as folder:
            subprocess.run([sys.executable, __file__, '--child', folder], check=True, timeout=35)
