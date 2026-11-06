"""実WebView2＋ローカル合成ページで資料保存を確認。実サイト・実DBは使わない。"""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import traceback

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import site777_browser as browser
import site777_samples as samples
import webview


def main():
    bitmap = Image.new('RGB', (250, 180), '#181e18')
    draw = ImageDraw.Draw(bitmap)
    draw.line([(10, 90), (240, 90)], fill='white')
    draw.line([(10, 90), (40, 85), (90, 110), (150, 70)], fill='yellow', width=2)
    stream = BytesIO()
    bitmap.save(stream, 'PNG')
    png = base64.b64encode(stream.getvalue()).decode('ascii')
    html = ('''<!doctype html><meta charset=utf-8><link rel=icon href="data:,">
      <h1>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館（手元の合成ページ）</h1>
      <table><tr><th>台番</th><th>累計ゲーム</th><th>BB回数</th><th>RB回数</th><th>最高出玉</th><th>ART回数</th></tr>
      <tr><td>1286</td><td>2574</td><td>8</td><td>5</td><td>530</td><td>--</td></tr></table>
      <input type=hidden value=PRIVATE_DUMMY><textarea>PRIVATE_DUMMY</textarea>
      <script type="application/json">PRIVATE_SCRIPT_DUMMY</script><noscript>PRIVATE_SCRIPT_DUMMY</noscript>
      <img src="data:image/png;base64,''' + png + '">').encode('utf-8')
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; img-src data:; connect-src 'none'")
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='site777-local-') as tmp:
        log = browser.DiagnosticLog(tmp)
        window = webview.create_window('サイトセブン資料保存・ローカル試験（自動終了）',
                                       f'http://127.0.0.1:{server.server_port}/', width=560, height=800,
                                       js_api=browser.Bridge(log))
        handlers = []
        result = {}

        def install():
            handlers.extend(browser.keep_popups_here(window, log))

        def loaded():
            try:
                initial = list(requests)
                for _ in range(3):
                    payload = window.evaluate_js(samples.SNAPSHOT_JS)
                    assert payload, '資料を読み取れません: ' + str(window.evaluate_js('document.body.innerText.slice(0, 160)'))
                    assert 'PRIVATE_DUMMY' not in payload['html'], '入力値が残っています'
                    assert 'PRIVATE_SCRIPT_DUMMY' not in payload['html'], '解析に不要なスクリプトが残っています'
                    assert len(payload['images']) == 1 and payload['images'][0]['png'].startswith('data:image/png;base64,')
                    # 保存のドメイン制限だけ、合成データのメタデータで合わせる。本体の制限は変更しない。
                    payload['url'] = 'https://m.site777.jp/f/D3300.do?pmc=04034001&urt=2000&mdc=123&dtdd=0'
                    assert samples.save_sample(tmp, payload).is_file()
                assert requests == initial == ['/'], '読み取りによって追加の要求が発生しました'
                window.evaluate_js("document.body.insertAdjacentHTML('beforeend', '<input type=password>')")
                assert window.evaluate_js(samples.SNAPSHOT_JS) is None, '認証ページが除外されていません'
                result.update(ok=True, samples=3, requests=len(requests), images=1, auth_excluded=True)
            except Exception:
                result.update(ok=False, error=traceback.format_exc())
            finally:
                window.destroy()

        window.events.before_show += install
        window.events.loaded += loaded
        webview.start(gui='edgechromium', private_mode=True, user_agent=browser.ANDROID_USER_AGENT,
                      storage_path=str(Path(tmp) / 'webview'))
        server.shutdown()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
