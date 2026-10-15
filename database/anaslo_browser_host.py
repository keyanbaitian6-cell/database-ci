"""WebView2 child process. All commands come from a local private Pipe.

No js_api is exposed to the website. CAPTCHA/consent is always a human action.
"""
import threading
import time
from urllib.parse import urlsplit, unquote

from anaslo_index import canonical_url
from anaslo_download import MAX_BYTES, reject_access_check


def is_embedded_document(request):
    headers = request.Headers
    return (headers.Contains('Sec-Fetch-Dest') and
            str(headers.GetHeader('Sec-Fetch-Dest')).lower() in ('iframe', 'frame'))


def document_identity(url):
    parts = urlsplit(url)
    return (parts.scheme.lower(), parts.netloc.lower(), unquote(parts.path), parts.query)


class NavigationState:
    def __init__(self):
        self.lock = threading.RLock()
        self.expected = None
        self.index = False
        self.navigation = None
        self.status = None
        self.complete = False
        self.error = ''
        self.notice = ''
        self.web_error = ''
        self.frames = set()
        self.blocked_windows = set()

    def target(self, url, index):
        with self.lock:
            self.expected = canonical_url(url, index=index)
            self.index = index
            self.navigation = None
            self.status = None
            self.complete = False
            self.error = ''
            self.notice = ''
            self.web_error = ''
            self.frames.clear()
            self.blocked_windows.clear()

    def same(self, url):
        try:
            return canonical_url(url, index=self.index) == self.expected
        except (ValueError, UnicodeError):
            return False

    def starting(self, url, identity):
        with self.lock:
            if self.expected is None and (url in ('about:blank', 'about:blank#') or urlsplit(url).hostname in ('127.0.0.1', 'localhost')):
                return True
            if not self.same(url):
                # A cancelled click must not terminate the capture session or
                # invalidate the document that is still displayed.
                self.notice = 'サイト内リンクへの移動を止めました。日付は取得画面の指定期間で選び、上部「取得」→「表示を確認して自動取得を開始」を押してください。'
                self.blocked_windows.add(document_identity(url))
                return False
            self.navigation = identity
            self.status = None
            self.complete = False
            return True

    def response(self, url, status):
        with self.lock:
            if self.expected and self.same(url):
                self.status = int(status)

    def frame_starting(self, url):
        with self.lock:
            self.frames.add(document_identity(url))

    def allows_document(self, url):
        with self.lock:
            identity = document_identity(url)
            return (self.expected is None or self.same(url) or
                    (identity in self.frames and identity not in self.blocked_windows))

    def completed(self, identity, success, status=None, web_error=''):
        with self.lock:
            if identity != self.navigation or self.navigation is None:
                return
            if status and int(status) >= 100:
                self.status = int(status)
            self.complete = True
            self.web_error = str(web_error)
            if not success and (self.status is None or self.status == 200):
                self.error = 'ブラウザのページ読み込みに失敗しました。' + (f' ({web_error})' if web_error else '')


def install_handlers(window, state):
    from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
    control = window.native.webview
    handlers = []

    def starting(sender, args):
        if not state.starting(str(args.Uri), args.NavigationId):
            args.set_Cancel(True)

    def completed(sender, args):
        state.completed(args.NavigationId, args.IsSuccess, getattr(args, 'HttpStatusCode', None),
                        getattr(args, 'WebErrorStatus', ''))

    def response(sender, args):
        if args.Response is not None and not is_embedded_document(args.Request):
            state.response(str(args.Request.Uri), args.Response.StatusCode)

    def popup(sender, args):
        args.set_Handled(True)

    def frame_starting(sender, args):
        state.frame_starting(str(args.Uri))

    def document_request(sender, args):
        if args.ResourceContext != CoreWebView2WebResourceContext.Document:
            return
        # Sec-Fetch-Dest can still be absent at WebResourceRequested time.
        # Use native frame navigation events to identify embedded documents.
        allowed = state.allows_document(str(args.Request.Uri))
        if not allowed:
            # Navigation cancellation alone can race with a document request.
            # Respond locally so a disallowed click never reaches the server.
            args.Response = sender.Environment.CreateWebResourceResponse(
                None, 403, 'Blocked', 'Content-Type: text/plain; charset=utf-8')

    def attach(core):
        core.WebResourceResponseReceived += response
        core.FrameNavigationStarting += frame_starting
        # pywebview registers its handler before ours. It opens the system
        # browser before our Handled flag can take effect, so replace it.
        core.NewWindowRequested -= window.native.browser.on_new_window_request
        core.NewWindowRequested += popup
        core.AddWebResourceRequestedFilter('*', CoreWebView2WebResourceContext.Document)
        core.WebResourceRequested += document_request

    def initialized(sender, args):
        if args.IsSuccess:
            attach(sender.CoreWebView2)
        else:
            state.error = 'WebView2の初期化に失敗しました。'

    handlers.extend([starting, completed, response, popup, initialized, document_request, frame_starting])
    control.NavigationStarting += starting
    control.NavigationCompleted += completed
    if control.CoreWebView2 is None:
        control.CoreWebView2InitializationCompleted += initialized
    else:
        attach(control.CoreWebView2)
    return handlers


def run_host(connection, profile):
    import webview
    from webview.menu import Menu, MenuAction
    state = NavigationState()
    closed = threading.Event()
    confirmed = threading.Event()
    handlers = []
    approved = False
    shell = '<html lang="ja"><meta charset="utf-8"><body><p>指定したページを表示します。</p><p>表示後、上部メニュー「取得」から「表示を確認して自動取得を開始」を選んでください。</p></body></html>'
    window = webview.create_window('アナスロ HTML取得：表示確認待ち', html=shell, width=1100, height=800)

    def confirm():
        with state.lock:
            ready = state.complete and state.status == 200 and not state.error
        if ready:
            confirmed.set()
        else:
            with state.lock:
                state.notice = f'まだ取得できません：HTTP {state.status or "未確認"}、読み込み完了={state.complete}。ページの表示・認証を確認してください。'
            window.set_title(f'HTTP {state.status or "未確認"}：ページの表示・認証を確認してください')

    def install():
        try:
            handlers.extend(install_handlers(window, state))
        except Exception:
            state.error = 'WebView2の通信状態を確認できないため停止しました。'

    window.events.before_show += install
    window.events.closed += closed.set

    def send(kind, **data):
        connection.send({'kind': kind, **data})

    def capture(url, index):
        nonlocal approved
        if state.error:
            raise ValueError(state.error)
        state.target(url, index)
        confirmed.clear()
        window.load_url(url)
        if not approved:
            send('progress', text='ブラウザで表示を確認し、上部「取得」→「表示を確認して自動取得を開始」を選んでください。')
        deadline = time.monotonic() + (300 if not approved else 45)
        last_state = None
        while not closed.wait(0.25) and time.monotonic() < deadline:
            # A close request interrupts both manual confirmation and load waits.
            if connection.poll():
                command = connection.recv()
                if command.get('kind') == 'close':
                    window.destroy()
                    return False
                raise ValueError('同時に複数ページを要求できません。')
            with state.lock:
                error, complete, status = state.error, state.complete, state.status
                notice, state.notice = state.notice, ''
                diagnostic = (complete, status, state.web_error)
            if diagnostic != last_state:
                last_state = diagnostic
                send('progress', text=f'ページ状態：HTTP {status or "未確認"}、読み込み完了={complete}、WebView2={diagnostic[2] or "待機中"}')
                if complete and status != 200:
                    window.set_title(f'HTTP {status or "未確認"}：取得待機中／表示・認証を確認してください')
            if notice:
                send('progress', text=notice)
            if error:
                raise ValueError(error)
            if complete and status is not None and status >= 400 and status not in (401, 403, 429):
                send('http_error', status=status, text=f'HTTP {status}：この日付は保存しませんでした。')
                return True
            if approved and complete and status != 200:
                raise ValueError(f'HTTP {status or "不明"}：自動取得を停止しました。')
            # The first page can be inspected by the person; no CAPTCHA is solved in code.
            if not complete or status != 200 or (not approved and not confirmed.is_set()):
                continue
            snapshot = window.evaluate_js('''(() => {
              const html = document.documentElement.outerHTML;
              if (new TextEncoder().encode(html).length > 16777216)
                return JSON.stringify({too_large:true});
              return JSON.stringify({url:location.href,ready:document.readyState,html});
            })()''')
            import json
            snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
            if isinstance(snapshot, dict) and snapshot.get('too_large'):
                raise ValueError('HTMLが上限16MiBを超えています。')
            if not isinstance(snapshot, dict) or snapshot.get('ready') != 'complete':
                continue
            if canonical_url(snapshot.get('url', ''), index=index) != url:
                raise ValueError('表示中のページが取得対象と一致しません。')
            text = snapshot.get('html', '')
            if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
                raise ValueError('HTMLを取得できないか、上限16MiBを超えています。')
            reject_access_check(text.encode('utf-8'), url, index=index)
            with state.lock:
                if not state.complete or state.status != 200 or state.error:
                    continue
            approved = True
            window.set_title('アナスロ HTML自動取得：停止するにはこの窓を閉じてください')
            send('snapshot', url=snapshot['url'], html=text, status=200)
            return True
        if not closed.is_set():
            raise ValueError('ブラウザの表示・確認待ち時間を超えました。')
        return False

    def serve():
        try:
            while not closed.is_set():
                if not connection.poll(0.1):
                    continue
                command = connection.recv()
                if command.get('kind') == 'close':
                    break
                if command.get('kind') != 'get':
                    raise ValueError('ブラウザへの要求が不正です。')
                index = command.get('index') is True
                url = canonical_url(command.get('url', ''), index=index)
                if not capture(url, index):
                    break
        except (EOFError, OSError):
            pass
        except Exception as exc:
            try:
                send('error', text=str(exc))
            except (EOFError, OSError):
                pass
        finally:
            if not closed.is_set():
                window.destroy()

    try:
        webview.start(serve, gui='edgechromium', private_mode=False, storage_path=profile,
                      menu=[Menu('取得', [MenuAction('表示を確認して自動取得を開始', confirm),
                                          MenuAction('停止して閉じる', window.destroy)])])
    except Exception as exc:
        try:
            send('error', text='取得ブラウザを起動できませんでした：' + str(exc))
        except (EOFError, OSError):
            pass
    finally:
        closed.set()
        connection.close()
