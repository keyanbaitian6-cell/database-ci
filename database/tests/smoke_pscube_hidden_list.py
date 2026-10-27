"""Opt-in WebView2 regression: a minimized capture window still reads the whole P's CUBE table.

ローカルのインラインページと一時プロファイルだけを使う（実サイト・実DBには触れない）。2026-10-28、PC版で
全台一覧が6台のまま「一覧の読み込みが時間切れ」→3回で待機になった件の再発確認。サイトの続きの読み込み
（jquery.inview：250msごとに最後の台が画面内か調べ、位置は scroll の通知で取り直す）を模した一覧を、
窓を最小化してから SCROLL_SCRIPT で読む。Chromium が見えない窓の時計を強く抑えるまでの猶予（既定5分）は
試験用に10秒へ縮める。比べのため、取り込み窓の起動設定（keep_page_timers）が無い場合も流す（止まる見込み）。
使い方: python tests/smoke_pscube_hidden_list.py
"""
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GRACE = '--enable-features=IntensiveWakeUpThrottling:grace_period_seconds/10'
HIDDEN_SECONDS = 40
TOTAL = 24

SITE = '''(() => {
  let offset = null;
  window.addEventListener('scroll', () => { offset = null; });
  const ul = document.getElementById('ulKI');
  const add = n => { for (let k = 0; k < n && ul.children.length < TOTAL; k++) {
    const li = document.createElement('li'); li.id = 'li-' + (ul.children.length + 1); li.style.height = '110px'; ul.append(li); } };
  add(6);
  setInterval(() => {
    const last = ul.lastElementChild;
    offset = offset ?? pageYOffset;
    const top = last.getBoundingClientRect().top + pageYOffset;
    const inView = top + last.offsetHeight > offset && top < offset + innerHeight;
    if (last.dataset.inview === String(inView)) return;
    last.dataset.inview = String(inView);
    if (inView) setTimeout(() => add(6), 10);
  }, 250);
})()'''.replace('TOTAL', str(TOTAL))


def child(folder, fixed):
    import webview
    from pscube_import import SCROLL_SCRIPT, keep_page_timers

    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = GRACE
    if fixed:
        keep_page_timers()
    observed = {}

    class Api:
        def done(self, value):
            observed.update(value)
            threading.Timer(.3, window.destroy).start()
            return True

    html = ('<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'script-src \'unsafe-inline\' \'unsafe-eval\'; style-src \'unsafe-inline\'">'
            '<body style="margin:0"><div style="height:420px">header</div>'
            '<ul id="ulKI" style="margin:0;padding:0;list-style:none"></ul><div style="height:1800px">footer</div></body>')
    script = '''(async () => {
      const info = () => ({count: document.querySelectorAll('li').length, visibility: document.visibilityState});
      try { const expectedCount = TOTAL; await SCROLL; await window.pywebview.api.done({ok: true, ...info()}); }
      catch (error) { await window.pywebview.api.done({error: String(error), ...info()}); }
    })()'''.replace('SCROLL', SCROLL_SCRIPT).replace('TOTAL', str(TOTAL))
    window = webview.create_window('LOCAL Pscube hidden list regression', html=html, js_api=Api(), width=1050, height=780)

    def loaded():
        window.evaluate_js(SITE)
        window.minimize()
        time.sleep(HIDDEN_SECONDS)        # Python側で数える（取り込みの自動の時計と同じ）
        started = time.monotonic()
        window.evaluate_js(script)
        observed.setdefault('started', started)

    window.events.loaded += loaded
    watchdog = threading.Timer(HIDDEN_SECONDS + 150, window.destroy)
    watchdog.start()
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=str(Path(folder) / 'profile'))
    finally:
        watchdog.cancel()
    print(json.dumps(observed, ensure_ascii=False))


def run(fixed):
    with tempfile.TemporaryDirectory(prefix='tmp-pscube-hidden-', dir=ROOT, ignore_cleanup_errors=True) as folder:
        out = subprocess.run([sys.executable, __file__, '--child', folder, '1' if fixed else '0'],
                             check=True, timeout=HIDDEN_SECONDS + 200, capture_output=True, text=True, encoding='utf-8')
        return json.loads(out.stdout.strip().splitlines()[-1])


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--child':
        child(sys.argv[2], sys.argv[3] == '1')
    else:
        fixed = run(True)
        assert fixed.get('ok') and fixed.get('count') == TOTAL, fixed
        control = run(False)
        print('PASS: minimized WebView2 reads', fixed['count'], 'of', TOTAL, 'cards with keep_page_timers',
              f"(visibility={fixed.get('visibility')});",
              'without it:', 'stopped at ' + str(control.get('count')) if not control.get('ok') or control.get('count') != TOTAL
              else 'also completed (control did not reproduce)')
