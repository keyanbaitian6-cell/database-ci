"""マウスの戻る・進むを実WebView2とローカルページだけで確認する。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import ctypes
import struct
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import site777_browser as browser
import site777_history as history
import webview


def main():
    manual = '--manual' in sys.argv
    watchdog = threading.Timer(180 if manual else 35, lambda: (print('ローカル試験が時間切れになりました', flush=True), os._exit(2)))
    watchdog.daemon = True
    watchdog.start()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            following = '/b' if self.path == '/a' else '/c'
            instruction = ('<p style="background:#fff2b0;padding:14px">この白い画面内にマウスを置き、'
                           '側面の「戻る」ボタンを1回押してください。実サイトには接続していません。</p>'
                           if manual and self.path == '/c' else '')
            body = ('<!doctype html><meta charset=utf-8><link rel=icon href="data:,">'
                    '<h1>マウス履歴・ローカル試験</h1><p>' + self.path + '</p>'
                    + instruction +
                    '<script>document.addEventListener("touchend",()=>sessionStorage.setItem("touches",'
                    'String(Number(sessionStorage.getItem("touches")||0)+1)));</script>'
                    '<a id=next href=' + following + '>次の試しページへ</a>').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    result, handlers = {}, []
    ready = threading.Event()
    with tempfile.TemporaryDirectory(prefix='site777-history-') as tmp:
        log = browser.DiagnosticLog(tmp)
        window = webview.create_window('サイトセブン履歴・ローカル試験（自動終了）', base + '/a',
                                       width=560, height=800, js_api=browser.Bridge(log))

        def install():
            handlers.extend(browser.keep_popups_here(window, log))
            if '--baseline' not in sys.argv:
                handlers.extend(history.install(window, log))

        def wait_for(check, message, seconds=6):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if check():
                    return
                time.sleep(.05)
            raise AssertionError(message)

        def exercise():
            from System import Func, Object

            def cdp(method, params):
                def send():
                    window.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(params))
                    return None
                window.native.Invoke(Func[Object](send))

            def press(button, buttons, x=40, y=140):
                cdp('Input.dispatchMouseEvent', dict(type='mousePressed', x=x, y=y, button=button, buttons=buttons, clickCount=1))
                cdp('Input.dispatchMouseEvent', dict(type='mouseReleased', x=x, y=y, button=button, buttons=0, clickCount=1))

            def raw_release(flags):
                receiver = handlers[-2]
                packet = bytearray(48)
                struct.pack_into('<H', packet, 28, flags)
                original = receiver.receive
                received = []
                def dispatch(_):
                    received.append(True)
                    return history.navigate(window.native.webview,
                        history.button_direction(history.raw_mouse_flags(packet, 24)), log)
                receiver.receive = dispatch
                try:
                    send = ctypes.WinDLL('user32').SendMessageW
                    send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
                    send.restype = ctypes.c_ssize_t
                    # この試験が作った窓へだけ模擬パケットを配送。実デバイス・他の窓へ入力を送らない。
                    send(int(window.native.Handle.ToInt64()), history.WM_INPUT, 0, 0)
                    assert received, '窓の入力処理が呼ばれません'
                finally:
                    receiver.receive = original

            try:
                assert ready.wait(15), '最初のページが開きません'
                print('最初のページを表示', flush=True)
                if '--without-touch-mouse' in sys.argv:
                    cdp('Emulation.setEmitTouchEventsForMouse', {'enabled': False, 'configuration': 'mobile'})
                point = window.evaluate_js("(() => {const r=document.querySelector('#next').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()")
                press('left', 1, **point)
                wait_for(lambda: window.get_current_url() == base + '/b', '左クリックで移動できません')
                wait_for(lambda: bool(window.evaluate_js("document.querySelector('#next')")), '次ページ未完了')
                if '--without-touch-mouse' not in sys.argv:
                    assert window.evaluate_js("Number(sessionStorage.getItem('touches'))") >= 1, 'タッチ操作が失われています'
                point = window.evaluate_js("(() => {const r=document.querySelector('#next').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()")
                press('left', 1, **point)
                wait_for(lambda: window.get_current_url() == base + '/c', '3ページ目へ移動できません')
                time.sleep(.3)
                if manual:
                    print('実マウスの戻る入力を待っています（この試験窓だけ）', flush=True)
                    wait_for(lambda: window.get_current_url() == base + '/b', '実マウスで戻りませんでした', 100)
                    result.update(ok=True, physical_mouse_back=True, touch_click=True)
                    return
                press('back', 8)
                if '--baseline' not in sys.argv:
                    raw_release(0x0080)  # 公式のRI_MOUSE_BUTTON_4_UP。実装の定数は参照しない。
                wait_for(lambda: window.get_current_url() == base + '/b', '戻るが1段だけ動きません')
                time.sleep(.3)
                press('forward', 16)
                if '--baseline' not in sys.argv:
                    raw_release(0x0200)  # 公式のRI_MOUSE_BUTTON_5_UP。
                wait_for(lambda: window.get_current_url() == base + '/c', '進むが1段だけ動きません')
                result.update(ok=True, back=True, forward=True, touch_click=True,
                              raw_input_dispatch='--baseline' not in sys.argv, physical_mouse='未確認')
            except Exception:
                entries = [json.loads(line) for line in log.path.read_text(encoding='utf-8').splitlines()]
                result.update(ok=False, error=traceback.format_exc(),
                              input_events=[r for r in entries if r.get('kind', '').startswith('mouse_history')])
            finally:
                window.destroy()

        window.events.before_show += install
        window.events.loaded += ready.set
        webview.start(exercise, gui='edgechromium', private_mode=True,
                      user_agent=browser.ANDROID_USER_AGENT, storage_path=str(Path(tmp) / 'webview'))
    server.shutdown()
    watchdog.cancel()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
