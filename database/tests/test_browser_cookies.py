import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import browser_import as browser
from pscube_connection import error_page
from pscube_import import webview_storage as pscube_storage


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, callback):
        self.handlers.append(callback)
        return self


class CookieSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'data' / 'database.sqlite3'
        self.path.parent.mkdir()
        self.path.write_bytes(b'retained records')
        self.bridge = browser._Bridge(self.path, self.path.parent, 'browser_import.py')
        self.window = mock.Mock()
        self.window.get_current_url.return_value = browser.DEFAULT_START
        self.bridge._window = self.window

    def test_profiles_persist_and_are_separate_from_pscube_and_sqlite(self):
        profile = browser.webview_storage(self.path)
        marker = profile / 'test-cookie'
        marker.write_text('retained')
        self.assertEqual(browser.webview_storage(self.path), profile)
        self.assertEqual(marker.read_text(), 'retained')
        self.assertNotEqual(profile, pscube_storage(self.path))
        self.assertEqual(self.path.read_bytes(), b'retained records')

    def test_retry_preserves_cookie_db_and_original_store_day(self):
        url = browser.BROWSER_URLS['saiwaichou'] + '?machine_name=Test&target_date=2026-10-01#day'
        self.bridge._connection.start(url, 1)
        self.bridge._connection.navigation_completed(1, False, 'HostNameNotResolved')
        self.bridge._pending_advance = ('stale', None, None, None)
        self.bridge._signal_path.write_text(json.dumps({'next_url':browser.DEFAULT_START}))
        self.addCleanup(lambda: self.bridge._signal_path.unlink(missing_ok=True))
        self.bridge.retry_page()
        self.assertFalse(self.bridge._signal_path.exists())
        self.assertFalse(self.bridge._poll_advance())
        self.window.load_url.assert_called_once_with(url)
        self.window.clear_cookies.assert_not_called()
        self.window.evaluate_js.assert_not_called()
        self.assertFalse(self.bridge.get_auto_capture()['enabled'])
        self.assertIsNone(self.bridge._pending_advance)
        self.assertIsNone(self.bridge._connection.failure)
        self.assertEqual(self.path.read_bytes(), b'retained records')

    def test_retry_during_review_changes_nothing(self):
        self.bridge.set_auto_capture(True, 1)
        self.bridge._children = [types.SimpleNamespace(poll=lambda: None)]
        with self.assertRaises(ValueError):
            self.bridge.retry_page()
        self.window.load_url.assert_not_called()
        self.assertTrue(self.bridge.get_auto_capture()['enabled'])

    def test_failure_blocks_auto_and_capture_but_ads_and_other_days_do_not(self):
        c = self.bridge._connection
        url = browser.BROWSER_URLS['saiwaichou'] + '?target_date=2026-10-01'
        c.start(url, 2)
        for other in [browser.DEFAULT_START, url.replace('10-01', '09-30'), 'https://ads.example/']:
            self.assertFalse(c.http_error(other, 403))
        self.assertTrue(c.http_error(url, 403))
        self.bridge._pending_advance = ({'next_url': browser.DEFAULT_START}, None, None, None)
        self.assertFalse(self.bridge._poll_advance())
        self.window.evaluate_js.assert_not_called()
        self.assertFalse(self.bridge._spawn('table', '{}'))
        self.assertFalse(self.bridge.set_auto_capture(True, 1)['enabled'])
        self.assertIn('403', json.loads(self.bridge._checked('{}'))['error'])
        self.window.get_current_url.side_effect = RuntimeError('no current page')
        self.assertIn('403', json.loads(self.bridge._checked('{}'))['error'])
        self.assertIn('メルヘン', error_page(c, title='メルヘン'))
        self.assertNotIn('P’s CUBEのページ', error_page(c, title='メルヘン'))

    def test_actual_session_passes_persistent_options_to_pywebview(self):
        window = mock.MagicMock()
        fake = types.SimpleNamespace(create_window=mock.Mock(return_value=window), start=mock.Mock())
        with mock.patch.dict('sys.modules', webview=fake), mock.patch.object(browser, '_desktop_rect', return_value=None), mock.patch.object(browser, 'backup_after_session'):
            browser.run_session(self.path, self.path.parent)
        options = fake.start.call_args.kwargs
        self.assertFalse(options['private_mode'])
        self.assertEqual(Path(options['storage_path']), browser.webview_storage(self.path))
        self.assertEqual(options['gui'], 'edgechromium')
        window.clear_cookies.assert_not_called()

    def test_native_failure_stops_auto_and_shows_retry_without_ui_js_wait(self):
        window = mock.Mock()
        window.events = types.SimpleNamespace(**{name: Event() for name in
            ['moved', 'resized', 'before_load', 'before_show', 'closed', 'loaded']})
        core = types.SimpleNamespace(WebResourceResponseReceived=Event())
        control = types.SimpleNamespace(CoreWebView2=core, NavigationStarting=Event(), NavigationCompleted=Event())
        window.native = types.SimpleNamespace(webview=control)
        shown = threading.Event()
        window.load_html.side_effect = lambda _: shown.set()
        fake = types.SimpleNamespace(create_window=mock.Mock(return_value=window))

        def start(**options):
            bridge = fake.create_window.call_args.kwargs['js_api']
            bridge.set_auto_capture(True, 1)
            window.events.before_show.handlers[0]()
            control.NavigationStarting.handlers[0](control,
                types.SimpleNamespace(Uri=browser.DEFAULT_START, NavigationId=1))
            core.WebResourceResponseReceived.handlers[0](core,
                types.SimpleNamespace(Request=types.SimpleNamespace(Uri=browser.DEFAULT_START),
                                      Response=types.SimpleNamespace(StatusCode=403)))
            self.assertTrue(shown.wait(2), 'the error page is shown off the native callback thread')
            self.assertFalse(bridge.get_auto_capture()['enabled'])
            self.assertIn('メルヘン', window.load_html.call_args.args[0])
            self.assertIn('HTTP 403', window.load_html.call_args.args[0])
            window.evaluate_js.assert_not_called()
            window.clear_cookies.assert_not_called()

        fake.start = start
        with mock.patch.dict('sys.modules', webview=fake), mock.patch.object(browser, '_desktop_rect', return_value=None), mock.patch.object(browser, 'backup_after_session'):
            browser.run_session(self.path, self.path.parent)
