"""P's CUBE connection errors, independent of Cookies and captured SQLite data."""
from __future__ import annotations

import html
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

HOST = 'www.pscube.jp'
SHOP_PATH = '/dedamajyoho-P-townDMMpachi/c740601/'
PAGE_NAMES = {'nc-v03-001.php', 'nc-v05-011.php', 'nc-v06-001.php'}


def allowed_page(url):
    p = urlparse(url or '')
    return (p.scheme == 'https' and p.netloc == HOST and not p.username and not p.password
            and (p.path == SHOP_PATH or any(p.path == SHOP_PATH + 'cgi-bin/' + n for n in PAGE_NAMES)))


class BrowserConnection:
    def __init__(self, root):
        self.url = root
        self.navigation_id = None
        self.failure = None
        self.history = []
        self.revision = 0
        self.showing_error = False
        self.lock = threading.RLock()

    def start(self, url, navigation_id=None):
        with self.lock:
            # The application's error page is about:blank, not a site request.
            if self.showing_error and url == 'about:blank':
                return
            self.url = str(url)
            self.navigation_id = navigation_id
            self.failure = None
            self.showing_error = False
            self.revision += 1

    def http_error(self, url, status):
        with self.lock:
            if status < 400 or not allowed_page(self.url) or not allowed_page(url):
                return False
            target, request = urlparse(self.url), urlparse(url)
            if target.path != request.path:
                return False
            a, b = parse_qs(target.query), parse_qs(request.query)
            if any(a.get(k) != b.get(k) for k in ('cd_ps', 'cd_dai', 'bai', 'nmk_kisyu')):
                return False
            message = ('サイトがページ・データへのアクセスを拒否しました（HTTP 403）。'
                       if status == 403 else f'ページ・データを読み込めませんでした（HTTP {status}）。')
            self._fail('HTTP', status, url, message + '自動取り込みを止めました。Cookie削除で直るとは限りません。')
            return True

    def navigation_completed(self, navigation_id, success, error):
        with self.lock:
            if self.showing_error or navigation_id != self.navigation_id or success:
                return False
            if str(error) in ('OperationCanceled', 'ConnectionAborted'):
                return False  # replacing a document is not a new site failure
            dns = str(error) == 'HostNameNotResolved'
            message = ('接続先の名前を確認できませんでした（DNSエラー）。'
                       if dns else 'ページの通信に失敗しました。')
            self._fail('通信', str(error), self.url,
                       message + '自動取り込みを止めました。Cookieを消さずに「もう一度開く」を試してください。')
            return True

    def _fail(self, kind, code, url, message):
        p = urlparse(url)
        report = (datetime.now(timezone.utc).isoformat() + f' {kind} {code}\n'
                  + f'{p.scheme}://{p.netloc}{p.path}')
        self.failure = {'message': message, 'report': report}
        self.history = (self.history + [report])[-8:]


def retry_page(window, pilot, connection, saving):
    if saving():
        raise ValueError('保存中です。保存が終わってから押してください。')
    with connection.lock:
        target = connection.url
        if not allowed_page(target):
            target = 'https://' + HOST + SHOP_PATH
    pilot.configure(False, pilot.state()['seconds'])
    pilot.connection_started()
    connection.start(target)
    window.load_url(target)
    return True


def stop_navigation(window):
    native = getattr(window, 'native', None)
    if native is None:
        return False
    # clear_cookies and navigation are serialized on the WinForms UI thread.
    from System import Action
    native.Invoke(Action(lambda: native.webview.CoreWebView2.Stop()))
    return True


def error_page(connection):
    with connection.lock:
        message = html.escape(connection.failure['message'])
        report = html.escape('\n\n'.join(connection.history))
    return '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>P’s CUBE 通信エラー</title>
<style>body{font:16px sans-serif;background:#f5f7fa;color:#24384d;margin:32px;line-height:1.6}
button{font-size:16px;padding:12px;border-radius:8px;border:1px solid #b8c5d8;background:white;color:#24384d}
pre{white-space:pre-wrap;word-break:break-word;font-size:12px}</style>
<h2>P’s CUBEのページを開けませんでした</h2><p>''' + message + '''</p>
<p>取り込んだ記録とCookieは保持しています。</p>
<button id="retry" disabled>もう一度開く</button>
<details><summary>通信エラーの記録</summary><pre>''' + report + '''</pre></details>
<p id="status"></p><script>
const button=document.getElementById('retry');
const enable=()=>{button.disabled=false};
if(window.pywebview?.api) enable(); else window.addEventListener('pywebviewready',enable);
button.onclick=async()=>{button.disabled=true;try{await window.pywebview.api.retry_page()}
catch(_){document.getElementById('status').textContent='開き直せませんでした。通信状態を確認してください。';button.disabled=false}};
</script></html>'''


def install_webview2_handlers(window, connection, failed, on_start=lambda: None):
    """Called on WinForms before_show, before the first site navigation.

    Native callbacks never wait for evaluate_js on the UI thread. Keep handler
    references alive for pythonnet, and do not change headers/UA/DNS or Cookies.
    """
    control = window.native.webview
    handlers = []

    def started(sender, args):
        connection.start(str(args.Uri), args.NavigationId)
        if not connection.showing_error:
            on_start()

    def completed(sender, args):
        if connection.navigation_completed(args.NavigationId, args.IsSuccess, str(args.WebErrorStatus)):
            failed()

    def ready(sender, args):
        if args.IsSuccess:
            sender.CoreWebView2.WebResourceResponseReceived += response

    def response(sender, args):
        if args.Response is not None and connection.http_error(str(args.Request.Uri), args.Response.StatusCode):
            failed()

    handlers.extend([started, completed, ready, response])
    # Observe navigation before CoreWebView2 initialization starts the first load.
    control.NavigationStarting += started
    control.NavigationCompleted += completed
    core = control.CoreWebView2
    if core is None:
        control.CoreWebView2InitializationCompleted += ready
    else:
        core.WebResourceResponseReceived += response
    return handlers
