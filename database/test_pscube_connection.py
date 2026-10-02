import tempfile
import types
import unittest
from pathlib import Path

from auto_capture import AutoCapture
from pscube_connection import BrowserConnection, allowed_page, error_page, install_webview2_handlers, retry_page
from pscube_import import AutoPilot, ROOT_URL, PscubeStore
from test_pscube_auto import FakeWindow, Clock, Handlers, PROBE

RACK = ROOT_URL + 'cgi-bin/nc-v06-001.php?cd_dai=1526#20261001'


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.c = BrowserConnection(ROOT_URL)
        self.c.start(RACK, 1)
        self.clock = Clock()
        self.page = FakeWindow()
        self.pilot = AutoPilot(self.page, PROBE, auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))

    def test_dns_failure_stops_auto_and_cannot_be_enabled_on_error_document(self):
        self.pilot.configure(True, 10)
        self.assertTrue(self.c.navigation_completed(1, False, 'HostNameNotResolved'))
        self.pilot.connection_failed(self.c.failure['message'])
        self.assertFalse(self.pilot.state()['enabled'])
        self.pilot.loaded()
        self.pilot.configure(True, 10)
        self.clock.now += 100
        self.pilot.tick()
        self.assertFalse(self.pilot.state()['enabled'])
        self.assertEqual(self.page.calls, [])
        self.assertIn('DNS', self.pilot.state()['message'])

    def test_http_error_for_data_not_ads_captcha_or_another_rack(self):
        for url in ['https://ads.example/a.php','https://hcaptcha.com/check',
                    ROOT_URL + 'cgi-bin/ad.php', RACK.replace('1526', '1527'), ROOT_URL]:
            self.assertFalse(self.c.http_error(url, 403))
        self.assertTrue(self.c.http_error(RACK.split('#')[0] + '&action=graph', 403))
        self.assertIn('403', self.c.failure['message'])
        self.assertFalse(self.c.navigation_completed(1, True, 'Unknown'))
        self.assertIsNotNone(self.c.failure)

    def test_stale_completion_and_cancel_are_ignored(self):
        self.c.start(RACK.replace('1526', '1527'), 2)
        self.assertFalse(self.c.navigation_completed(1, False, 'HostNameNotResolved'))
        self.assertFalse(self.c.navigation_completed(2, False, 'OperationCanceled'))
        self.assertIsNone(self.c.failure)

    def test_error_page_keeps_failure_and_escapes_report_without_tokens(self):
        self.c.http_error(RACK.split('#')[0] + '&token=secret', 403)
        self.c.failure['message'] += '<script>bad()</script>'
        content = error_page(self.c)
        self.assertNotIn('<script>bad()', content)
        self.assertNotIn('token=secret', content)
        self.assertIn('もう一度開く', content)
        self.c.showing_error = True
        self.c.start('about:blank', 2)
        self.assertEqual(self.c.url, RACK)
        self.assertIsNotNone(self.c.failure)
        self.assertFalse(self.c.navigation_completed(2, False, 'Unknown'))

    def test_manual_retry_keeps_db_cookies_and_reopens_original_url_once(self):
        calls = []
        window = types.SimpleNamespace(load_url=lambda url: calls.append(('load', url)),
                                       clear_cookies=lambda: self.fail('must not clear Cookies'))
        self.c.navigation_completed(1, False, 'HostNameNotResolved')
        self.pilot.configure(True, 10)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pscube.sqlite3'
            db = PscubeStore(path)
            db.db.execute("INSERT INTO state VALUES ('test','retained')")
            db.db.commit()
            before = path.read_bytes()
            retry_page(window, self.pilot, self.c, saving=lambda: False)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(db.db.execute("SELECT value FROM state WHERE key='test'").fetchone()[0], 'retained')
            db.close()
        self.assertEqual(calls, [('load', RACK)])
        self.assertFalse(self.pilot.state()['enabled'])
        self.assertIsNone(self.c.failure)
        self.assertEqual(len(self.c.history), 1)
        self.assertTrue(self.pilot.loading_page)

    def test_retry_while_saving_changes_nothing_and_unknown_url_falls_back_to_root(self):
        calls = []
        window = types.SimpleNamespace(load_url=calls.append)
        self.pilot.configure(True, 10)
        with self.assertRaises(ValueError):
            retry_page(window, self.pilot, self.c, saving=lambda: True)
        self.assertEqual(calls, [])
        self.assertTrue(self.pilot.state()['enabled'])
        self.c.start('https://other.example/')
        retry_page(window, self.pilot, self.c, saving=lambda: False)
        self.assertEqual(calls, [ROOT_URL])

    def test_reports_are_bounded_and_scope_rejects_other_stores(self):
        for i in range(10):
            self.c.start(RACK, i)
            self.c.http_error(RACK, 500)
        self.assertEqual(len(self.c.history), 8)
        for url in ['about:blank','http://www.pscube.jp/',ROOT_URL.replace('c740601','c123456'),
                    ROOT_URL.replace('www.pscube.jp','user:pass@www.pscube.jp'),ROOT_URL.replace('.jp/','.jp:443/')]:
            self.assertFalse(allowed_page(url))

    def test_native_handlers_attach_before_initialization_and_capture_response(self):
        core = types.SimpleNamespace(NavigationStarting=Handlers(), NavigationCompleted=Handlers(),
                                     WebResourceResponseReceived=Handlers())
        control = types.SimpleNamespace(CoreWebView2=None, CoreWebView2InitializationCompleted=Handlers(),
                                        NavigationStarting=core.NavigationStarting, NavigationCompleted=core.NavigationCompleted)
        window = types.SimpleNamespace(native=types.SimpleNamespace(webview=control))
        failed = []
        started = []
        refs = install_webview2_handlers(window, self.c, lambda: failed.append(True), lambda: started.append(True))
        self.assertEqual(len(refs), 4)
        control.NavigationStarting.items[0](control, types.SimpleNamespace(Uri=ROOT_URL, NavigationId=1))
        self.assertEqual(self.c.url, ROOT_URL)
        started.clear()
        control.CoreWebView2 = core
        control.CoreWebView2InitializationCompleted.items[0](control, types.SimpleNamespace(IsSuccess=True))
        core.NavigationStarting.items[0](core, types.SimpleNamespace(Uri=RACK, NavigationId=3))
        self.assertEqual(started, [True])
        core.WebResourceResponseReceived.items[0](core, types.SimpleNamespace(Request=types.SimpleNamespace(Uri=RACK), Response=types.SimpleNamespace(StatusCode=403)))
        self.assertEqual(failed, [True])
        core.NavigationCompleted.items[0](core, types.SimpleNamespace(NavigationId=2,IsSuccess=False,WebErrorStatus='HostNameNotResolved'))
        self.assertEqual(failed, [True], 'old navigation cannot change current error')


if __name__ == '__main__':
    unittest.main()
