"""実WebView2：取り込み窓を最小化している間、サイトセブンのグラフ待ちは止まらず、窓を戻すと続く（2026-11-21）。

サイトのグラフ一覧は、グラフの img に仮の画像（graph-back.png）を入れておき、画面に半分以上見えたとき
（IntersectionObserver、しきい値0.5。サイトの f/contents/js/lazy-load.js と同じ作り）に本物へ差し替える。
最小化するとページが見えない扱い（visibilityState hidden）になり、差し替えが起きない。前は12秒で
「グラフが出ない」と数え、読み込み直し3回のあとグラフなしで保存していた。

localhost の模擬ページだけを使う。外部サイト・実DBには接続しない。手で流す試験（ゲートでは流さない）：
  database\\.venv\\Scripts\\python.exe database\\tests\\smoke_site777_minimized.py
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pscube_import import keep_page_timers  # noqa: E402

# サイトの lazy-load.js と同じ動き（2026-11-21、取り込み窓のキャッシュに残っていたものを読んで同じ作りにした）。
LAZY = '''
function loadVisibleLazyImages(th){const lazyImages=document.querySelectorAll('img.lazy-load');
const observer=new IntersectionObserver((entries,observer)=>{entries.forEach(entry=>{if(entry.isIntersecting){
const img=entry.target;const d=img.getAttribute('data-src');if(d){img.setAttribute('src',d);img.removeAttribute('data-src');}
observer.unobserve(img);}});},{threshold:th});lazyImages.forEach(img=>observer.observe(img));}
document.addEventListener("DOMContentLoaded",function(){loadVisibleLazyImages(0.5);});
'''


def png(color):
    stream = BytesIO()
    Image.new('RGB', (260, 226), color).save(stream, 'PNG')
    return stream.getvalue()


def page():
    return ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">'
            f'<script>{LAZY}</script><div style="height:160px">header</div>'
            '<div class=lite-graph><div class=graph-box><span>[1205]</span>'
            '<img class="lazy-load" src="/f/contents/images/sp/graph-back.png" '
            'data-src="/chart/RequestSPDedamaTransitionChartForPortal.do?rack=1205"></div></div>').encode()


def main():
    keep_page_timers()   # 本番の取り込み窓（site777_browser.run）と同じ起動設定
    import webview
    requests, result = [], {'ok': False}
    chart, back = png('#ff0'), png('#222')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            body, kind = ((chart, 'image/png') if self.path.startswith('/chart/') else
                          (back, 'image/png') if self.path.endswith('.png') else (page(), 'text/html; charset=utf-8'))
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    capture = (ROOT / 'assets' / 'site777_capture.js').read_text(encoding='utf-8')
    watchdog = threading.Timer(90, lambda: os._exit(2))
    watchdog.daemon = True
    watchdog.start()

    def probe(window):
        return json.loads(window.evaluate_js('JSON.stringify({vis:document.visibilityState,done:window.__done||null,'
                                             'seen:window.__seen||[]})'))

    def wait(check, what, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return
            time.sleep(0.25)
        raise AssertionError(f'{what} が {timeout} 秒で起きません')

    def run(window):
        try:
            time.sleep(1.5)
            window.minimize()
            wait(lambda: str(window.native.WindowState) == 'Minimized', '最小化')
            requests.clear()
            window.load_url(f'{base}/f/D4300.do?pan=1')
            wait(lambda: any(p.startswith('/f/D4300.do') for p in requests), 'ページの読み込み')
            time.sleep(1)
            window.evaluate_js(capture + ';window.__site777GraphWaitMs=1500;window.__seen=[];'
                               'databaseSite777.prepare(()=>false,null,h=>window.__seen.push(h))'
                               '.then(()=>{window.__done="ok"},e=>{window.__done="error:"+e.message});')
            time.sleep(6)   # 待ち時間（1.5秒）の4倍
            hidden = probe(window)
            assert hidden['vis'] == 'hidden', hidden
            assert hidden['done'] is None, f'最小化の間に止まった：{hidden}'
            assert hidden['seen'] == [True], hidden
            assert not any(p.startswith('/chart/') for p in requests), '最小化の間はサイトの遅延読み込みが動かない'
            result['while_minimized'] = hidden
            window.restore()
            wait(lambda: probe(window)['done'] is not None, '窓を戻したあとの続き')
            shown = probe(window)
            assert shown['done'] == 'ok', shown
            assert shown['seen'] == [True, False], shown
            assert sum(p.startswith('/chart/') for p in requests) == 1, requests
            assert sum(p.startswith('/f/D4300.do') for p in requests) == 1, '読み込み直していない'
            result.update(ok=True, after_restore=shown, chart_requests=1)
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            print(json.dumps(result, ensure_ascii=False), flush=True)
            os._exit(0 if result['ok'] else 1)

    window = webview.create_window('site777 minimized smoke', f'{base}/blank', width=430, height=900)
    webview.start(run, window, gui='edgechromium', private_mode=True)


if __name__ == '__main__':
    main()
