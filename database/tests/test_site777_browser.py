"""サイトセブンをスマホとして開くブラウザ（site777_browser.py、2026-11-07）。サイトには接続しない。"""
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import site777_browser  # noqa: E402


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self


class FakeCore:
    def __init__(self, default):
        self.NewWindowRequested = FakeEvent()
        self.NewWindowRequested += default
        self.NavigationStarting = FakeEvent()
        self.NavigationCompleted = FakeEvent()
        self.devtools = []
        self.scripts = []

    def CallDevToolsProtocolMethodAsync(self, name, params):
        self.devtools.append((name, json.loads(params)))

    def AddScriptToExecuteOnDocumentCreatedAsync(self, script):
        self.scripts.append(script)


class FakeArgs:
    def __init__(self, uri):
        self.Uri = uri
        self.handled = False
        self.cancelled = False
        self.IsRedirected = False

    def set_Handled(self, value):
        self.handled = value

    def set_Cancel(self, value):
        self.cancelled = value


class Site777BrowserTest(unittest.TestCase):
    def test_redirect_and_document_are_blocked_without_reading_request_headers(self):
        browser=SimpleNamespace(on_new_window_request=lambda *args:None)
        core=FakeCore(browser.on_new_window_request)
        core.WebResourceRequested=FakeEvent()
        filters=[]
        core.AddWebResourceRequestedFilter=lambda *args:filters.append(args)
        core.Environment=SimpleNamespace(CreateWebResourceResponse=lambda stream,status,reason,headers:status)
        window=SimpleNamespace(native=SimpleNamespace(webview=SimpleNamespace(CoreWebView2=core),browser=browser))
        good='https://m.site777.jp/f/D4300.do?pmc=04034001&urt=2000'
        bad=good.replace('04034001','23170004')
        site777_browser.keep_popups_here(window,navigation_guard=lambda raw,redirected:raw==good,
            document_guard=lambda raw:raw==good,document_context='Document')
        self.assertEqual(filters,[('https://m.site777.jp/f/*','Document')])
        args=FakeArgs(bad);args.IsRedirected=True
        core.NavigationStarting.handlers[0](core,args)
        self.assertTrue(args.cancelled)
        allowed=FakeArgs(good)
        core.NavigationStarting.handlers[0](core,allowed)
        self.assertFalse(allowed.cancelled)
        request=SimpleNamespace(Request=SimpleNamespace(Uri=bad),Response=None)
        core.WebResourceRequested.handlers[0](core,request)
        self.assertEqual(request.Response,403)

    def test_it_presents_itself_as_android_chrome_on_a_phone(self):
        ua = site777_browser.ANDROID_USER_AGENT
        self.assertIn('Linux; Android', ua)
        self.assertIn('Mobile Safari/', ua)
        self.assertNotIn('Windows', ua)
        width, height = site777_browser.WINDOW_SIZE
        self.assertLess(width, height)
        # 開いたらクレジットカード会員のログイン画面（利用者が指定したアドレス、2026-11-07）。
        self.assertEqual(site777_browser.START_URL,
                         'https://m.site777.jp/f/P0300.do?skskb=3&skver=2&returnUrl=%2FF0900.do%3Fcksc%3Dc%26latc%3D1')

    def test_login_is_kept_in_its_own_folder_under_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = site777_browser.webview_storage(tmp)
            self.assertTrue(folder.is_dir())
            self.assertEqual(folder.name, 'site777-webview')
            self.assertEqual(folder.parent, Path(tmp).resolve())

    def test_new_window_links_open_in_this_window_not_the_normal_browser(self):
        opened_outside = []
        navigated = []

        class Browser:
            def on_new_window_request(self, sender, args):
                opened_outside.append(args.Uri)

        browser = Browser()
        core = FakeCore(browser.on_new_window_request)

        class Control:
            CoreWebView2 = core
            CoreWebView2InitializationCompleted = FakeEvent()

        class Native:
            webview = Control()

        Native.browser = browser

        class Window:
            native = Native()

        site777_browser.keep_popups_here(Window())
        self.assertEqual(len(core.NewWindowRequested.handlers), 1)
        # スマホとしての見え方（タッチ・Client Hints）と、ページの中で新しい窓をこの窓にする処理
        sent = dict(core.devtools)
        self.assertEqual(sent['Emulation.setUserAgentOverride']['userAgentMetadata']['platform'], 'Android')
        self.assertTrue(sent['Emulation.setUserAgentOverride']['userAgentMetadata']['mobile'])
        self.assertTrue(sent['Emulation.setTouchEmulationEnabled']['enabled'])
        self.assertEqual(sent['Emulation.setEmitTouchEventsForMouse'], {'enabled': True, 'configuration': 'mobile'})
        self.assertEqual(core.scripts, [site777_browser.PAGE_SCRIPT])
        for part in ("el.target = '_self'", 'HTMLFormElement.prototype.submit', 'window.open = function'):
            self.assertIn(part, site777_browser.PAGE_SCRIPT)

        class Sender:
            def Navigate(self, uri):
                navigated.append(uri)

        args = FakeArgs('https://m.site777.jp/f/D0300.do')
        for handler in core.NewWindowRequested.handlers:
            handler(Sender(), args)
        self.assertTrue(args.handled)
        self.assertEqual(navigated, ['https://m.site777.jp/f/D0300.do'])
        self.assertEqual(opened_outside, [])

    def test_the_log_keeps_where_but_not_the_values_in_urls(self):
        self.assertEqual(site777_browser.safe_url('https://m.site777.jp/f/D0300.do?pmc=123&sid=abcdef#x'),
                         'https://m.site777.jp/f/D0300.do?pmc&sid#…')
        self.assertEqual(site777_browser.safe_url('b.html'), 'b.html')
        with tempfile.TemporaryDirectory() as tmp:
            log = site777_browser.DiagnosticLog(tmp)
            site777_browser.Bridge(log).note(json.dumps({'kind': 'click', 'href': '/f/D0400.do?dai=1235', 'tag': 'A'}))
            site777_browser.Bridge(log).note('not json')
            lines = log.path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual((row['kind'], row['href'], row['tag']), ('click', '/f/D0400.do?dai', 'A'))
            self.assertEqual(log.path.parent.name, 'logs')

    def test_the_home_button_opens_it_with_the_same_python(self):
        import app
        command, folder = app.site777_browser_command()
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(Path(command[1]).name, 'site777_browser.py')
        self.assertTrue(Path(command[1]).is_file())
        self.assertEqual(Path(command[2]).name, 'data')
        self.assertEqual(folder, Path(app.__file__).resolve().parent)
        source = Path(app.__file__).read_text(encoding='utf-8')
        self.assertIn("text='サイトセブンを開く（スマホ会員）'", source)


if __name__ == '__main__':
    unittest.main()
