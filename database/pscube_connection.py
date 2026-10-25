"""Scoped WebView2 errors shared by P's CUBE and Meruhen, separate from Cookies/SQLite."""
from __future__ import annotations

import base64
import html
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse

HOST = 'www.pscube.jp'
SHOP_PATH = '/dedamajyoho-P-townDMMpachi/c740601/'
PAGE_NAMES = {'nc-v03-001.php', 'nc-v05-011.php', 'nc-v06-001.php'}


def allowed_page(url):
    p = urlparse(url or '')
    return (p.scheme == 'https' and p.netloc == HOST and not p.username and not p.password
            and (p.path == SHOP_PATH or any(p.path == SHOP_PATH + 'cgi-bin/' + n for n in PAGE_NAMES)))


class BrowserConnection:
    def __init__(self, root, *, page_allowed=allowed_page, same_response=None):
        self.allowed_page = page_allowed
        self.same_response = same_response
        self.url = root
        self.navigation_id = None
        self.failure = None
        self.history = []
        self.revision = 0
        self.showing_error = False
        self.error_document_url = None
        # HTTP status (>= 400) the server returned for the current top-level
        # document, whether or not it is a target page (consent/auth pages too).
        self.document_status = None
        self.lock = threading.RLock()

    def start(self, url, navigation_id=None):
        with self.lock:
            # WebView2 may report NavigateToString as about:blank or the exact
            # data URI of our HTML. Neither is a new site request.
            if self.showing_error and url in ('about:blank', self.error_document_url):
                return
            self.url = str(url)
            self.navigation_id = navigation_id
            self.failure = None
            self.showing_error = False
            self.error_document_url = None
            self.document_status = None
            self.revision += 1

    def http_error(self, url, status):
        with self.lock:
            if status >= 400 and unquote(str(url).split('#')[0]) == unquote(self.url.split('#')[0]):
                self.document_status = status
            if status < 400 or not self.allowed_page(self.url) or not self.allowed_page(url):
                return False
            if self.same_response is not None and not self.same_response(self.url, url):
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
            # Real WebView2 reports HTTP 403 as IsSuccess=False/Unknown after
            # WebResourceResponseReceived. Its document can contain consent;
            # do not reclassify that HTTP response as a transport failure.
            if self.failure and self.failure['kind'] == 'HTTP':
                return False
            # The same IsSuccess=False/Unknown follows an HTTP error on a page
            # outside the target list, e.g. a consent or human-check page
            # reached by a top-level navigation or redirect (measured on
            # WebView2 154, 2026-10-02). The server answered: keep its
            # document for manual operation instead of an app error page.
            if self.document_status is not None:
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
        self.failure = {'message': message, 'report': report, 'kind': kind}
        self.history = (self.history + [report])[-8:]


def retry_page(window, pilot, connection, saving):
    if saving():
        raise ValueError('保存中です。保存が終わってから押してください。')
    target = retry_target(window, connection, 'https://' + HOST + SHOP_PATH)
    pilot.configure(False, pilot.state()['seconds'])
    pilot.connection_started()
    connection.start(target)
    reopen_page(window, target)
    return True


def retry_target(window, connection, fallback):
    with connection.lock:
        target = connection.url
    if not connection.allowed_page(target):
        return fallback
    try:
        current = window.get_current_url()
    except Exception:
        return target
    if (isinstance(current, str) and connection.allowed_page(current)
            and unquote(current.split('#')[0]) == unquote(target.split('#')[0])):
        return current  # Preserve a selected history day changed only in the hash.
    return target


def reopen_page(window, target):
    """Source assignment may ignore the current URL: explicitly reload/navigate."""
    native = getattr(window, 'native', None)
    if native is None:
        window.load_url(target)
        return
    from System import Action

    same_source = []
    native.Invoke(Action(lambda: same_source.append(
        unquote(str(native.webview.CoreWebView2.Source)) == unquote(target))))
    # Keep pywebview's real_url, readiness events and browser state consistent.
    window.load_url(target)
    if same_source[0]:
        native.Invoke(Action(lambda: native.webview.CoreWebView2.Reload()))


def present_connection_failure(window, connection, revision, title="P’s CUBE"):
    """Called off the UI thread. HTTP documents may contain manual CAPTCHA."""
    with connection.lock:
        if revision != connection.revision or not connection.failure or connection.showing_error:
            return False
        if connection.failure['kind'] == 'HTTP':
            return False  # Keep the site's own response visible and operable.
        connection.showing_error = True
        content = error_page(connection, title)
        connection.error_document_url = ('data:text/html;charset=utf-8;base64,'
            + base64.b64encode(content.encode('utf-8')).decode('ascii'))
    window.load_html(content)
    return True


def stop_navigation(window):
    native = getattr(window, 'native', None)
    if native is None:
        return False
    # clear_cookies and navigation are serialized on the WinForms UI thread.
    from System import Action
    native.Invoke(Action(lambda: native.webview.CoreWebView2.Stop()))
    return True


def error_page(connection, title="P’s CUBE"):
    title = html.escape(title)
    with connection.lock:
        message = html.escape(connection.failure['message'])
        report = html.escape('\n\n'.join(connection.history))
    return '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>''' + title + ''' 通信エラー</title>
<style>body{font:16px sans-serif;background:#f5f7fa;color:#24384d;margin:32px;line-height:1.6}
button{font-size:16px;padding:12px;border-radius:8px;border:1px solid #b8c5d8;background:white;color:#24384d}
pre{white-space:pre-wrap;word-break:break-word;font-size:12px}</style>
<h2>''' + title + '''のページを開けませんでした</h2><p>''' + message + '''</p>
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


# 埋め込みのYouTube（動画の枠・プレーヤーのスクリプト・サムネイル・動画本体の通信）。取り込み画面では
# 開こうとすらしない（2026-10-25 利用者「一瞬開いて見えないようにしているだけで、アクセスして開く処理も
# しているのでは」）。WebView2の通信フィルターで、サーバーへ送らずにここで空の応答を返す。
# 枠を隠すJS（browser_import.HIDE_YOUTUBE_JS）は、空になった枠の場所を詰めるために残す。
YOUTUBE_REQUEST_FILTERS = tuple(f'*://{host}/*' for host in (
    'youtube.com', '*.youtube.com', 'youtube-nocookie.com', '*.youtube-nocookie.com',
    'youtu.be', '*.ytimg.com', '*.googlevideo.com'))
_YOUTUBE_HOSTS = ('youtube.com', 'youtube-nocookie.com', 'youtu.be', 'ytimg.com', 'googlevideo.com')


def is_youtube_request(url):
    """YouTube（動画・画像・再生の通信）の宛先か。ホスト名だけで判定する（パスに youtube を含む別サイトは対象外）。"""
    try:
        host = (urlparse(str(url)).hostname or '').lower()
    except ValueError:
        return False
    return any(host == name or host.endswith('.' + name) for name in _YOUTUBE_HOSTS)


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
            attach(sender.CoreWebView2)

    def response(sender, args):
        if args.Response is not None and connection.http_error(str(args.Request.Uri), args.Response.StatusCode):
            failed()

    def youtube_request(sender, args):
        if is_youtube_request(args.Request.Uri):
            args.Response = sender.Environment.CreateWebResourceResponse(None, 204, 'No Content', '')

    def attach(core):
        core.WebResourceResponseReceived += response
        try:
            from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext as kinds
            # 古いWebView2にはAllが無い（anaslo_browser_host と同じ確認）。そのときは種類ごとに登録する。
            contexts = [kinds.All] if hasattr(kinds, 'All') else [
                getattr(kinds, name) for name in ('Document', 'Script', 'Image', 'Media', 'Fetch',
                                                  'XmlHttpRequest', 'Stylesheet', 'Font', 'Other')
                if hasattr(kinds, name)]
            for pattern in YOUTUBE_REQUEST_FILTERS:
                for context in contexts:
                    core.AddWebResourceRequestedFilter(pattern, context)
            core.WebResourceRequested += youtube_request
        except Exception:  # noqa: BLE001 -- 取り込みは止めない。枠はこれまでどおりJSで隠す
            pass

    handlers.extend([started, completed, ready, response, youtube_request])
    # Observe navigation before CoreWebView2 initialization starts the first load.
    control.NavigationStarting += started
    control.NavigationCompleted += completed
    core = control.CoreWebView2
    if core is None:
        control.CoreWebView2InitializationCompleted += ready
    else:
        attach(core)
    return handlers
