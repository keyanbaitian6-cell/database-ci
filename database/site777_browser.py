"""サイトセブン（m.site777.jp）を、Androidのスマホとして開くブラウザ（2026-11-07）。

利用者はスマホ会員で、PC会員は別の契約になる。PC版の画面からスマホ会員のまま見るため、
端末の名乗り（User-Agent）をAndroidのChromeにして、スマホ向けのページを開く。
ログインは利用者が自分で入力する。Cookieは data/site777-webview に残し、次からはログイン済みで開く。

今は「見るだけ」のブラウザ。データの読み取り・保存はしない（取り込みは、台データのページの形を
確かめてから足す）。サイトへの自動のアクセス（巡回・再読み込み）もしない。
"""
from __future__ import annotations

import sys
from pathlib import Path

START_URL = 'https://m.site777.jp/'
# 利用者のスマホ（Galaxy A25、Chrome 156）と同じ形。Chromeは端末名・Androidの版を
# 「Android 10; K」に固定して送る（User-Agentの簡略化）ので、それに合わせる。
ANDROID_USER_AGENT = ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/156.0.0.0 Mobile Safari/537.36')
# スマホの画面に近い幅（CSSの画素）。縦長にする。
WINDOW_SIZE = (430, 900)
TITLE = 'サイトセブン（スマホとして表示）'


def webview_storage(data_dir) -> Path:
    """サイトセブンのCookie・ログインを残す場所（data の中、Gitには入らない）。
    P’s CUBE（pscube-webview）・アナスロとは分ける。"""
    folder = Path(data_dir).resolve() / 'site777-webview'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def keep_popups_here(window):
    """新しい窓を開くリンクを、普段のブラウザ（ログインしていない、PCとして名乗る）ではなく
    この窓で開く。pywebview は先に自分の処理（普段のブラウザで開く）を登録するので、
    それを外してから足す（anaslo_browser_host.install_handlers と同じ理由）。"""
    control = window.native.webview

    def popup(sender, args):
        args.set_Handled(True)
        sender.Navigate(str(args.Uri))

    def attach(core):
        core.NewWindowRequested -= window.native.browser.on_new_window_request
        core.NewWindowRequested += popup

    def initialized(sender, args):
        if args.IsSuccess:
            attach(sender.CoreWebView2)

    if control.CoreWebView2 is None:
        control.CoreWebView2InitializationCompleted += initialized
    else:
        attach(control.CoreWebView2)
    return [popup, initialized]  # 呼び出し側で参照を保持し、途中で消されないようにする


def run(data_dir, start_url=START_URL):
    import webview

    window = webview.create_window(TITLE, start_url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1])
    handlers = []

    def install():
        try:
            handlers.extend(keep_popups_here(window))
        except Exception as error:  # noqa: BLE001 - 新しい窓の扱いだけが変わらない。表示は続ける
            print(f'新しい窓をこの窓で開く設定ができませんでした：{error}', file=sys.stderr)

    if hasattr(window.events, 'before_show'):
        window.events.before_show += install
    # pywebview の初期設定はシークレットモード（閉じるとCookieが消える）なので、
    # private_mode=False と専用の保存先でログインを残す。
    webview.start(gui='edgechromium', private_mode=False, user_agent=ANDROID_USER_AGENT,
                  storage_path=str(webview_storage(data_dir)))


def runtime_root():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else runtime_root() / 'data')
