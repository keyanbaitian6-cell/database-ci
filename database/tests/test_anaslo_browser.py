from datetime import date
import gc
from pathlib import Path
import tempfile
import threading
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from anaslo_browser import BrowserClient
from anaslo_browser_host import NavigationState, install_handlers, is_embedded_document, navigate_target
from anaslo_download import AccessStopped, Stopped, download
from test_anaslo_download import FakeCancel, html, link
from test_anaslo_download_ui import CONVERTER
from calendar_picker import CalendarPicker
import tkinter as tk


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.closed = False

    def request(self, url, index, cancel, progress):
        self.calls.append((url, index))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return {'url':url, 'html':result.decode('utf-8'), 'status':200} if isinstance(result, bytes) else result

    def close(self):
        self.closed = True


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def engine(self, responses):
        clock = [0.0]
        cancel = FakeCancel(clock)
        session = FakeSession(responses)
        engine = BrowserClient(self.folder / 'profile', cancel, session_factory=lambda profile: session,
                               clock=lambda:clock[0], jitter=lambda:6)
        self.addCleanup(engine.close)
        return engine, session

    def test_automatic_next_day_uses_same_browser_and_jitter(self):
        engine, session = self.engine([html(), html(day='2026/09/16')])
        result = download([link('2026-09-15'), link('2026-09-16')], '2026-09-15', '2026-09-16', self.folder, engine)
        self.assertEqual(result.downloaded, 2)
        self.assertEqual([url for url, index in session.calls], [link('2026-09-15').url, link('2026-09-16').url])
        self.assertEqual(engine.cancel.waits, [0, 6])
        engine.close()
        self.assertTrue(session.closed)

    def test_next_page_waits_from_when_the_page_finished(self):
        # 2026-10-17 利用者「今のペースだとすぐ切られちゃうので5秒くらいあけてく」。表示に3.5秒かかっても、
        # 表示し終えてから次まで6秒（試験の揺らぎ）あける。開始から数えると2.5秒しか空かなかった。
        engine, session = self.engine([html(), html(day='2026/09/16'), html(day='2026/09/17')])
        clock = engine.cancel.clock
        request = session.request
        def slow(*args):
            clock[0] += 3.5
            return request(*args)
        session.request = slow
        days = [link('2026-09-15'), link('2026-09-16'), link('2026-09-17')]
        result = download(days, '2026-09-15', '2026-09-17', self.folder, engine)
        self.assertEqual(result.downloaded, 3)
        self.assertEqual(engine.cancel.waits, [0, 6, 6])
        # 失敗したページのあとも同じ（拒否で止まるまでの間隔を詰めない）。
        engine, session = self.engine([HTTPError(link('2026-09-15').url, 404, 'missing', None, None), html(day='2026/09/16')])
        clock = engine.cancel.clock
        request = session.request
        session.request = slow
        download(days[:2], '2026-09-15', '2026-09-16', self.folder / 'b', engine)
        self.assertEqual(engine.cancel.waits, [0, 6])

    def test_http_denial_stops_before_next_day_and_closes(self):
        for code in (401, 403, 429):
            engine, session = self.engine([{'url':link('2026-09-15').url,'html':'denied','status':code}, html(day='2026/09/16')])
            result = download([link('2026-09-15'), link('2026-09-16')], '2026-09-15', '2026-09-16', self.folder, engine)
            self.assertIn(str(code), result.stopped)
            self.assertEqual(len(session.calls), 1)
            self.assertTrue(session.closed)

    def test_404_uses_common_skip_and_proceeds_to_next_day(self):
        engine, session = self.engine([HTTPError(link('2026-09-15').url,404,'missing',None,None), html(day='2026/09/16')])
        result = download([link('2026-09-15'), link('2026-09-16')], '2026-09-15', '2026-09-16', self.folder, engine)
        self.assertEqual((result.failed, result.downloaded), (1, 1))
        self.assertEqual(len(session.calls), 2)

    def test_unexpected_url_challenge_and_bad_result_stop(self):
        for response in [None, {'url':link('2026-09-16').url,'html':'x','status':200},
                         {'url':link('2026-09-15').url,'html':'captcha','status':200},
                         {'url':'https://example.com/','html':'x','status':200}]:
            engine, session = self.engine([response])
            with self.assertRaises(AccessStopped):
                engine.get(link('2026-09-15').url)
            self.assertTrue(session.closed)

    def test_closed_browser_stops_queue(self):
        engine, session = self.engine([Stopped('closed'), html(day='2026/09/16')])
        result = download([link('2026-09-15'), link('2026-09-16')], '2026-09-15', '2026-09-16', self.folder, engine)
        self.assertTrue(result.stopped)
        self.assertEqual(len(session.calls), 1)

    def test_profile_or_start_failure_stops_without_retries(self):
        engine = BrowserClient(self.folder / 'profile', session_factory=lambda profile: (_ for _ in ()).throw(OSError('startup failure')))
        with self.assertRaises(AccessStopped):
            engine.get(link('2026-09-15').url)

    def test_cache_only_run_does_not_start_browser(self):
        (self.folder / '2026-09-15.html').write_bytes(html())
        factory = unittest.mock.Mock(side_effect=AssertionError('must not open'))
        engine = BrowserClient(self.folder / 'profile', session_factory=factory)
        result = download([link('2026-09-15')], '2026-09-15', '2026-09-15', self.folder, engine)
        self.assertEqual(result.skipped, 1)
        factory.assert_not_called()

    def test_valid_index_with_captcha_script_is_not_a_challenge(self):
        from anaslo_index import INDEX_URL
        raw = ('<h1>P-STATION&amp;IIスロット館 データ一覧</h1>'
               f'<a href="{link("2026-09-15").url}">9/15</a>'
               '<script>const captchaEnabled = false;</script>').encode('utf-8')
        engine, session = self.engine([raw])
        self.assertEqual(engine.get(INDEX_URL, index=True), raw)

    def test_valid_daily_data_with_challenge_words_in_script_is_allowed(self):
        raw = html() + b'<script>const labels = ["captcha", "cf-chl-", "verify you are human"];</script>'
        engine, session = self.engine([raw])
        self.assertEqual(engine.get(link('2026-09-15').url), raw)

    def test_real_challenge_title_still_stops_even_with_data_links(self):
        from anaslo_index import INDEX_URL
        raw = ('<title>Just a moment...</title><h1>P-STATION&amp;IIスロット館 データ一覧</h1>'
               f'<a href="{link("2026-09-15").url}">9/15</a>').encode('utf-8')
        engine, session = self.engine([raw])
        with self.assertRaises(AccessStopped):
            engine.get(INDEX_URL, index=True)

    def test_incomplete_or_wrong_target_data_does_not_override_challenge_guard(self):
        from anaslo_index import INDEX_URL
        for raw, url, index in [
            (b'<script>captcha</script>', INDEX_URL, True),
            (f'<h1>another store</h1><a href="{link("2026-09-15").url}">data</a><script>captcha</script>'.encode(), INDEX_URL, True),
            ('<h1>P-STATION&amp;IIスロット館 データ一覧</h1><script>captcha</script>'.encode(), INDEX_URL, True),
            (html(day='2026/09/16') + b'<script>captcha</script>', link('2026-09-15').url, False),
        ]:
            with self.subTest(index=index, raw=raw[:30]):
                engine, session = self.engine([raw])
                with self.assertRaises(AccessStopped):
                    engine.get(url, index=index)

    def test_direct_transport_uses_the_same_structural_guard(self):
        from test_anaslo_download import client
        raw = html() + b'<script>const captcha = false;</script>'
        engine, opener = client([raw])
        self.assertEqual(engine.get(link('2026-09-15').url), raw)
        engine, opener = client([b'<title>CAPTCHA</title>'])
        with self.assertRaises(AccessStopped):
            engine.get(link('2026-09-15').url)

    def test_range_guard_applies_to_browser_before_start(self):
        engine, session = self.engine([])
        with self.assertRaises(ValueError):
            download([link('2026-09-16')], '2026-09-15', '2026-09-15', self.folder, engine)
        self.assertEqual(session.calls, [])


class NavigationTests(unittest.TestCase):
    def test_navigation_uses_same_tab_after_initial_load_without_retry(self):
        window = unittest.mock.Mock()
        target = link('2026-09-15').url
        self.assertEqual(navigate_target(window, target, None), 'initial')
        window.load_url.assert_called_once_with(target)
        for result in ('link', 'location'):
            window.evaluate_js.return_value = result
            self.assertEqual(navigate_target(window, target, target), result)
        window.load_url.assert_called_once()
        window.evaluate_js.return_value = 'stale'
        with self.assertRaises(ValueError):
            navigate_target(window, target, target)
        window.load_url.assert_called_once()
    def test_native_frame_requests_are_allowed_but_not_whole_window_clicks(self):
        state = NavigationState()
        state.target(link('2026-09-15').url, False)
        frame = 'https://example.com/display-frame'
        self.assertFalse(state.allows_document(frame))
        state.frame_starting(frame)
        self.assertTrue(state.allows_document(frame))
        self.assertFalse(state.starting(frame, 2))
        self.assertFalse(state.allows_document(frame))
        state.target(link('2026-09-16').url, False)
        self.assertFalse(state.allows_document(frame))

    def test_images_and_other_sites_are_not_loaded(self):
        # 2026-10-17 利用者「画像、広告を読み込まない設定にしてみようか」。
        from anaslo_browser_host import blocks_resource
        site = 'https://ana-slo.com/wp-content/uploads/'
        self.assertTrue(blocks_resource(site + 'logo.png', light=True))
        self.assertTrue(blocks_resource(site + 'font.woff2', light=True))
        self.assertFalse(blocks_resource(site + 'theme.js'))
        self.assertFalse(blocks_resource('https://ana-slo.com/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1'))
        for url in ('https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js',
                    'https://securepubads.g.doubleclick.net/tag/js/gpt.js', 'https://cdn.example.net/jquery.js'):
            self.assertTrue(blocks_resource(url))
            self.assertTrue(blocks_resource(url, document=True))   # 広告の枠も
        # 人が通す確認画面と、手元の案内画面・ブラウザ内のデータは止めない。
        self.assertFalse(blocks_resource('https://challenges.cloudflare.com/turnstile/v0/api.js'))
        self.assertFalse(blocks_resource('https://challenges.cloudflare.com/x.png', light=True))
        self.assertFalse(blocks_resource('http://127.0.0.1:8123/index.html', document=True))
        self.assertFalse(blocks_resource('data:image/png;base64,AAAA', light=True))
        self.assertFalse(blocks_resource('about:blank', document=True))

    def test_handler_answers_blocked_requests_locally(self):
        class Event:
            def __init__(self):
                self.callbacks = []
            def __iadd__(self, callback):
                self.callbacks.append(callback)
                return self
            def __isub__(self, callback):
                return self
        contexts = SimpleNamespace(Document='document', Image='image', Media='media', Font='font', Script='script', All='all')
        core = SimpleNamespace(NewWindowRequested=Event(), FrameNavigationStarting=Event(),
                               WebResourceResponseReceived=Event(), WebResourceRequested=Event(),
                               AddWebResourceRequestedFilter=unittest.mock.Mock())
        control = SimpleNamespace(CoreWebView2=core, NavigationStarting=Event(), NavigationCompleted=Event())
        window = SimpleNamespace(native=SimpleNamespace(webview=control, browser=SimpleNamespace(on_new_window_request=None)))
        state = NavigationState()
        state.target(link('2026-09-15').url, False)
        with patch.dict(sys.modules, {'Microsoft.Web.WebView2.Core': SimpleNamespace(CoreWebView2WebResourceContext=contexts)}):
            install_handlers(window, state)
        core.AddWebResourceRequestedFilter.assert_any_call('*', 'all')
        sender = SimpleNamespace(Environment=SimpleNamespace(CreateWebResourceResponse=lambda *a: ('blocked', a[1])))
        def request(url, context):
            args = SimpleNamespace(Request=SimpleNamespace(Uri=url), ResourceContext=context, Response=None)
            for callback in core.WebResourceRequested.callbacks:
                callback(sender, args)
            return args.Response
        self.assertEqual(request('https://ana-slo.com/a.png', 'image'), ('blocked', 403))
        self.assertEqual(request('https://googleads.g.doubleclick.net/ad', 'script'), ('blocked', 403))
        self.assertIsNone(request('https://ana-slo.com/theme.js', 'script'))
        self.assertIsNone(request(link('2026-09-15').url, 'document'))   # 表示するページそのもの
        frame = 'https://googleads.g.doubleclick.net/frame'
        state.frame_starting(frame)
        self.assertEqual(request(frame, 'document'), ('blocked', 403))   # 広告の枠

    def test_embedded_document_is_distinguished_from_window_navigation(self):
        for destination in ('iframe', 'frame', 'document', ''):
            headers = unittest.mock.Mock()
            headers.Contains.return_value = bool(destination)
            headers.GetHeader.return_value = destination
            request = SimpleNamespace(Headers=headers)
            self.assertEqual(bool(is_embedded_document(request)), destination in ('iframe', 'frame'))

    def test_failed_navigation_with_200_is_not_ready_for_capture(self):
        state = NavigationState()
        state.target(link('2026-09-15').url, False)
        state.starting(link('2026-09-15').url, 1)
        state.completed(1, False, 200, 'OperationCanceled')
        self.assertTrue(state.error)
        self.assertEqual(state.web_error, 'OperationCanceled')

    def test_http_denial_is_preserved_for_manual_inspection(self):
        state = NavigationState()
        state.target(link('2026-09-15').url, False)
        state.starting(link('2026-09-15').url, 1)
        state.completed(1, False, 403, 'HttpStatusError')
        self.assertEqual(state.status, 403)
        self.assertEqual(state.web_error, 'HttpStatusError')
        self.assertFalse(state.error)

    def test_popup_replaces_backend_handler_before_it_can_open_external_browser(self):
        class Event:
            def __init__(self, callbacks=()):
                self.callbacks = list(callbacks)
            def __iadd__(self, callback):
                self.callbacks.append(callback)
                return self
            def __isub__(self, callback):
                self.callbacks.remove(callback)
                return self
        external_open = unittest.mock.Mock()
        core = SimpleNamespace(NewWindowRequested=Event([external_open]),
                               FrameNavigationStarting=Event(),
                               WebResourceResponseReceived=Event(), WebResourceRequested=Event(),
                               AddWebResourceRequestedFilter=unittest.mock.Mock())
        control = SimpleNamespace(CoreWebView2=core, NavigationStarting=Event(), NavigationCompleted=Event())
        window = SimpleNamespace(native=SimpleNamespace(webview=control,
                                 browser=SimpleNamespace(on_new_window_request=external_open)))
        module = SimpleNamespace(CoreWebView2WebResourceContext=SimpleNamespace(Document=0))
        with patch.dict(sys.modules, {'Microsoft.Web.WebView2.Core': module}):
            install_handlers(window, NavigationState())
        args = unittest.mock.Mock()
        for callback in core.NewWindowRequested.callbacks:
            callback(core, args)
        external_open.assert_not_called()
        args.set_Handled.assert_called_once_with(True)

    def test_wrong_day_and_domain_blocked_before_navigation(self):
        for url in (link('2026-09-16').url, 'https://example.com/'):
            state = NavigationState()
            state.target(link('2026-09-15').url, False)
            self.assertFalse(state.starting(url, 1))
            self.assertFalse(state.error)
            self.assertTrue(state.notice)

    def test_site_date_click_does_not_close_or_invalidate_loaded_index(self):
        from anaslo_index import INDEX_URL
        state = NavigationState()
        state.target(INDEX_URL, True)
        self.assertTrue(state.starting(INDEX_URL, 1))
        state.completed(1, True, 200)
        self.assertFalse(state.starting(link('2026-09-15').url, 2))
        state.completed(2, False, None)
        self.assertTrue(state.complete)
        self.assertEqual(state.status, 200)
        self.assertEqual(state.navigation, 1)
        self.assertFalse(state.error)
        self.assertTrue(state.notice)

    def test_site_next_day_click_keeps_original_target(self):
        state = NavigationState()
        state.target(link('2026-09-15').url, False)
        state.starting(link('2026-09-15').url, 1)
        state.completed(1, True, 200)
        self.assertFalse(state.starting(link('2026-09-16').url, 2))
        self.assertTrue(state.same(link('2026-09-15').url))
        self.assertFalse(state.error)
        self.assertTrue(state.complete)

    def test_status_is_top_document_only_and_stale_navigation_is_ignored(self):
        state = NavigationState()
        state.target(link('2026-09-15').url, False)
        self.assertTrue(state.starting(link('2026-09-15').url, 1))
        state.response('https://example.com/ad.js', 403)
        self.assertIsNone(state.status)
        state.response(link('2026-09-15').url, 200)
        state.completed(999, False, 403)
        self.assertFalse(state.complete)
        state.completed(1, True, 200)
        self.assertTrue(state.complete)
        self.assertEqual(state.status, 200)
        state.target(link('2026-09-16').url, False)
        self.assertIsNone(state.status)

    def test_percent_and_fragment_variants_are_same_page(self):
        state = NavigationState()
        state.target(link('2026-09-15').url, False)
        self.assertTrue(state.starting(link('2026-09-15').url.lower() + '#top', 1))


class CalendarTests(unittest.TestCase):
    # Tkは作ったスレッド（メインスレッド）で片付ける。循環参照のまま残すと、後の試験の別スレッドでGCが走ったときに
    # 「Tcl_AsyncDelete: async handler deleted by the wrong thread」でプロセスごと落ちる（2026-10-18）。
    @classmethod
    def tearDownClass(cls):
        gc.collect()  # 最後の試験のTkを、次の試験へ移る前に片付ける

    def setUp(self):
        gc.collect()  # 前の試験のTkをここで片付ける
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_pick_leap_day_and_shift_year(self):
        selected = []
        picker = CalendarPicker(self.root, '2024-02-01', selected.append)
        picker.withdraw()
        picker.shift(-2)
        self.assertEqual((picker.year, picker.month), (2023, 12))
        picker.shift(2)
        picker.pick(date(2024,2,29))
        self.assertEqual(selected, ['2024-02-29'])

    def test_cancel_does_not_change_value(self):
        selected = []
        picker = CalendarPicker(self.root, '', selected.append)
        picker.withdraw()
        picker.close()
        self.assertEqual(selected, [])

    def test_calendar_selection_invalidates_existing_preview(self):
        from download_dialog import DownloadDialog
        dialog = DownloadDialog(self.root, lambda paths:None)
        dialog.withdraw()
        dialog.scan_key = ('old',)
        dialog.choose_date(dialog.start_day)
        picker = next(w for w in dialog.winfo_children() if isinstance(w, CalendarPicker))
        picker.pick(date(2026,9,15))
        self.assertEqual(dialog.start_day.get(), '2026-09-15')
        self.assertIsNone(dialog.scan_key)
        self.assertEqual(str(dialog.start_button['state']), 'disabled')

    def test_browser_session_is_closed_on_success_and_exception(self):
        from download_dialog import DownloadDialog
        dialog = DownloadDialog(self.root, lambda paths:None)
        dialog.withdraw()
        engine = unittest.mock.Mock()
        dialog.browser_factory = unittest.mock.Mock(return_value=engine)
        self.assertEqual(dialog.with_client(lambda e:'ok', 'browser'), 'ok')
        engine.close.assert_called_once()
        engine.reset_mock()
        with self.assertRaises(ValueError):
            dialog.with_client(lambda e: (_ for _ in ()).throw(ValueError('bad')), 'browser')
        engine.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
