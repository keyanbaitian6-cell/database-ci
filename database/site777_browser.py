"""サイトセブン（m.site777.jp）を、Androidのスマホとして開くブラウザ（2026-11-07）。

利用者はスマホ会員で、PC会員は別の契約になる。PC版の画面からスマホ会員のまま見るため、
端末の名乗り（User-Agent）をAndroidのChromeにして、スマホ向けのページを開く。
ログインは利用者が自分で入力する。Cookieは data/site777-webview に残し、次からはログイン済みで開く。

今は「見るだけ」のブラウザ。データの読み取り・保存はしない（取り込みは、台データのページの形を
確かめてから足す）。サイトへの自動のアクセス（巡回・再読み込み）もしない。

2026-11-07 追記：ログイン・機種一覧・グラフは開けたが「台番が押せない」（利用者）。
- スマホとしての見え方をそろえる：タッチの画面として振る舞い、マウスのクリックをタッチとして送る。
  名乗りの Client Hints（Sec-CH-UA-Platform など）も Android・mobile にする（DevTools の Emulation）。
- 新しい窓・別の枠を狙うリンクやフォームを、この窓で開く（フォームの送信内容を落とさないため、
  ページの中で target を _self に変える。window.open もこの窓の移動にする）。
- 押したもの・開こうとしたページを data/logs/site777-browser.log に残す（Cookie・入力値・URLの値は残さない）。
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

START_URL = 'https://m.site777.jp/'
# 利用者のスマホ（Galaxy A25 SM-A253C、Android 16、Chrome 156.0.8078.79）に合わせる。Chromeは
# User-Agent では端末名・Androidの版を「Android 10; K」に固定して送る（簡略化）ので、それに合わせる。
CHROME_VERSION = '156.0.8078.79'
ANDROID_USER_AGENT = ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/156.0.0.0 Mobile Safari/537.36')
USER_AGENT_METADATA = {
    'brands': [{'brand': 'Chromium', 'version': '156'}, {'brand': 'Google Chrome', 'version': '156'},
               {'brand': 'Not?A_Brand', 'version': '99'}],
    'fullVersion': CHROME_VERSION, 'platform': 'Android', 'platformVersion': '16.0.0',
    'architecture': '', 'model': 'SM-A253C', 'mobile': True,
}
# スマホの画面に近い幅（CSSの画素）。縦長にする。
WINDOW_SIZE = (430, 900)
TITLE = 'サイトセブン（スマホとして表示）'
LOG_LIMIT = 1024 * 1024


def emulation_commands():
    """WebView2 の DevTools に送る命令（名前, 引数）。スマホのChromeと同じ見え方にする。"""
    return [
        ('Emulation.setUserAgentOverride', {'userAgent': ANDROID_USER_AGENT, 'platform': 'Linux armv8l',
                                            'acceptLanguage': 'ja-JP', 'userAgentMetadata': USER_AGENT_METADATA}),
        ('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5}),
        ('Emulation.setEmitTouchEventsForMouse', {'enabled': True, 'configuration': 'mobile'}),
    ]


# ページが作られるたびに、サイトのスクリプトより先に実行する。
PAGE_SCRIPT = r'''(() => {
  if (window.__site777Browser) return;
  window.__site777Browser = true;
  const send = (kind, data) => {
    try { if (window.pywebview && window.pywebview.api) window.pywebview.api.note(JSON.stringify({kind, ...data})); } catch (_) {}
  };
  const here = (el) => { if (el && el.target && el.target !== '_self') { el.target = '_self'; return true; } return false; };
  const describe = (el) => el ? {
    tag: el.tagName, href: el.getAttribute('href') || '', target: el.getAttribute('target') || '',
    onclick: (el.getAttribute('onclick') || '').slice(0, 200),
    attrs: Array.from(el.attributes || []).map(a => a.name).join(' '),
    text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40)
  } : {};
  document.addEventListener('click', (e) => {
    const t = e.target && e.target.closest ? e.target : null;
    const el = t && (t.closest('a,area,button,input,label,[onclick],[role=button]') || t);
    const moved = here(t && t.closest('a[target],area[target]')) || here(t && t.closest('form'));
    send('click', {...describe(el), retargeted: moved});
    setTimeout(() => send('click_after', {prevented: e.defaultPrevented}), 0);
  }, true);
  document.addEventListener('submit', (e) => {
    const f = e.target;
    send('submit', {action: f.getAttribute('action') || '', method: f.method || '', target: f.getAttribute('target') || '', retargeted: here(f)});
  }, true);
  const submit = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function () {
    send('form_submit', {action: this.getAttribute('action') || '', method: this.method || '', target: this.getAttribute('target') || '', retargeted: here(this)});
    return submit.apply(this, arguments);
  };
  const open = window.open;
  window.open = function (url) {
    send('window_open', {href: String(url || '')});
    if (url) { location.assign(url); return window; }
    return open.apply(this, arguments);
  };
})();'''


def safe_url(url) -> str:
    """記録に残すURL。ログインの番号などが入りうる値は落とし、場所と項目名だけにする。"""
    try:
        parts = urlsplit(str(url or ''))
    except ValueError:
        return '?'
    keys = [key for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    text = f'{parts.scheme}://{parts.netloc}{parts.path}' if parts.scheme else parts.path
    return text + ('?' + '&'.join(keys) if keys else '') + ('#…' if parts.fragment else '')


class DiagnosticLog:
    def __init__(self, data_dir):
        self.path = Path(data_dir).resolve() / 'logs' / 'site777-browser.log'
        self.lock = threading.Lock()

    def write(self, kind, **data):
        if 'href' in data:
            data['href'] = safe_url(data['href'])
        line = json.dumps({'at': datetime.now().isoformat(timespec='seconds'), 'kind': kind, **data},
                          ensure_ascii=False)
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > LOG_LIMIT:
                    self.path.replace(self.path.with_suffix('.log.1'))
                with self.path.open('a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except OSError:
                pass


class Bridge:
    """ページから window.pywebview.api.note(...) で呼ばれる。"""

    def __init__(self, log):
        self._log = log

    def note(self, payload):
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            return
        if isinstance(data, dict):
            kind = str(data.pop('kind', 'page'))
            self._log.write(kind, **{k: v for k, v in data.items() if k != 'at'})


def webview_storage(data_dir) -> Path:
    """サイトセブンのCookie・ログインを残す場所（data の中、Gitには入らない）。
    P’s CUBE（pscube-webview）・アナスロとは分ける。"""
    folder = Path(data_dir).resolve() / 'site777-webview'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def keep_popups_here(window, log=None):
    """スマホとしての見え方をそろえ、新しい窓を開くリンクを普段のブラウザ（ログインしていない、
    PCとして名乗る）ではなくこの窓で開く。pywebview は先に自分の処理（普段のブラウザで開く）を
    登録するので、それを外してから足す（anaslo_browser_host.install_handlers と同じ理由）。"""
    control = window.native.webview
    note = log.write if log else (lambda *a, **k: None)

    def popup(sender, args):
        # ページの中の処理（PAGE_SCRIPT）で拾えなかった新しい窓。URLだけでこの窓を移動する。
        args.set_Handled(True)
        note('new_window', href=str(args.Uri))
        sender.Navigate(str(args.Uri))

    def starting(sender, args):
        note('navigate', href=str(args.Uri))

    def completed(sender, args):
        note('loaded', ok=bool(args.IsSuccess), status=getattr(args, 'HttpStatusCode', None))

    def attach(core):
        for name, params in emulation_commands():
            core.CallDevToolsProtocolMethodAsync(name, json.dumps(params))
        core.AddScriptToExecuteOnDocumentCreatedAsync(PAGE_SCRIPT)
        core.NewWindowRequested -= window.native.browser.on_new_window_request
        core.NewWindowRequested += popup
        core.NavigationStarting += starting
        core.NavigationCompleted += completed

    def initialized(sender, args):
        if args.IsSuccess:
            attach(sender.CoreWebView2)

    if control.CoreWebView2 is None:
        control.CoreWebView2InitializationCompleted += initialized
    else:
        attach(control.CoreWebView2)
    return [popup, initialized, starting, completed]  # 呼び出し側で参照を保持し、途中で消されないようにする


def run(data_dir, start_url=START_URL):
    import webview

    log = DiagnosticLog(data_dir)
    window = webview.create_window(TITLE, start_url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                                   js_api=Bridge(log))
    handlers = []

    def install():
        try:
            handlers.extend(keep_popups_here(window, log))
        except Exception as error:  # noqa: BLE001 - 表示は続ける。何が効かないかを残す
            log.write('setup_failed', error=str(error)[:200])

    if hasattr(window.events, 'before_show'):
        window.events.before_show += install
    log.write('start')
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
