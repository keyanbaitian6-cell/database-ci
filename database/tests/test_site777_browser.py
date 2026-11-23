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

    def test_a_failed_page_load_is_reported_to_the_session_and_logged(self):
        # 2026-11-08：読み込めなかったページ（HTTP 403・通信エラー）は、自動取り込みを止めるためセッションへ知らせる。
        browser=SimpleNamespace(on_new_window_request=lambda *args:None)
        core=FakeCore(browser.on_new_window_request)
        window=SimpleNamespace(native=SimpleNamespace(webview=SimpleNamespace(CoreWebView2=core),browser=browser))
        seen,notes=[],[]
        log=SimpleNamespace(write=lambda kind,**data:notes.append((kind,data)))
        site777_browser.keep_popups_here(window,log,navigation_done=lambda *args:seen.append(args))
        done=core.NavigationCompleted.handlers[0]
        done(core,SimpleNamespace(IsSuccess=False,HttpStatusCode=403,WebErrorStatus='Unknown'))
        done(core,SimpleNamespace(IsSuccess=True,HttpStatusCode=200))
        self.assertEqual(seen,[(False,403,'Unknown'),(True,200,None)])
        self.assertEqual(notes[0],('loaded',{'ok':False,'status':403,'error':'Unknown'}))
        # 知らせる先が失敗しても、窓の処理は止めない。
        core=FakeCore(browser.on_new_window_request)
        window.native.webview.CoreWebView2=core
        site777_browser.keep_popups_here(window,log,navigation_done=lambda *args:1/0)
        core.NavigationCompleted.handlers[0](core,SimpleNamespace(IsSuccess=True,HttpStatusCode=200))
        self.assertEqual(notes[-1][0],'navigation_done_failed')

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

    def test_the_auto_resume_reloads_with_navigate_not_load_url(self):
        # 2026-11-08：window.load_url（WebView2 の Source）は表示中と同じURLでは読み込み直さず、自動の再開が
        # 「移動中」のまま止まっていた（smoke_site777_session.py --failed-load で確認）。CoreWebView2.Navigate を使う。
        calls = []
        core = SimpleNamespace(Navigate=lambda url: calls.append(('navigate', url)))
        window = SimpleNamespace(native=SimpleNamespace(webview=SimpleNamespace(CoreWebView2=core)),
                                 load_url=lambda url: calls.append(('load_url', url)))
        ran = []
        site777_browser.reload_page(window, 'https://m.site777.jp/f/D4300.do?pmc=04034001',
                                    invoke=lambda action: (ran.append(True), action()))
        self.assertEqual((ran, calls), ([True], [('navigate', 'https://m.site777.jp/f/D4300.do?pmc=04034001')]))
        source = Path(site777_browser.__file__).read_text(encoding='utf-8')
        self.assertIn('reload_page(window, url)', source)
        self.assertNotIn('window.load_url(url)', source)

    def test_form_targets_in_the_log_keep_where_but_not_the_values(self):
        # 2026-11-08：送信先（action）は safe_url を通さず、問い合わせの値ごと残っていた。
        with tempfile.TemporaryDirectory() as tmp:
            log = site777_browser.DiagnosticLog(tmp)
            for kind in ('submit', 'form_submit'):
                site777_browser.Bridge(log).note(json.dumps({'kind': kind, 'action': 'https://m.site777.jp/f/P0250.do?hkb=0&id=123', 'method': 'post'}))
            rows = [json.loads(line) for line in log.path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['action'] for r in rows], ['https://m.site777.jp/f/P0250.do?hkb&id'] * 2)

    def test_the_log_keeps_five_older_generations(self):
        # 2026-11-08：1世代だけだと、1日に約700KB書くので2〜3日前の停止の理由（auto_off）が消えていた。
        from unittest.mock import patch
        self.assertEqual(site777_browser.LOG_GENERATIONS, 5)
        with tempfile.TemporaryDirectory() as tmp, patch.object(site777_browser, 'LOG_LIMIT', 10):
            log = site777_browser.DiagnosticLog(tmp)
            for n in range(8):
                log.write('auto_off', n=n)  # 毎回10バイトを超えるので、次に書くときに送る
            names = sorted(p.name for p in log.path.parent.iterdir())
            self.assertEqual(names, ['site777-browser.log'] + [f'site777-browser.log.{i}' for i in range(1, 6)])
            number = lambda p: json.loads(p.read_text(encoding='utf-8'))['n']
            self.assertEqual([number(log.path)] + [number(log.path.with_suffix(f'.log.{i}')) for i in range(1, 6)],
                             [7, 6, 5, 4, 3, 2], '新しい順に残し、6世代より古いものだけ消す')

    def test_window_closes_only_after_auto_capture_finished_and_saving_is_done(self):
        # 2026-11-07 利用者「取り込み終わったなら閉じる仕様にしてね」（メルヘン・P’s CUBEの close_when_finished と同じ）
        import threading
        closed=[]
        window=SimpleNamespace(destroy=lambda:closed.append(True))
        with tempfile.TemporaryDirectory() as folder:
            session=SimpleNamespace(_completed=None,_work_lock=threading.Lock())
            self.assertFalse(site777_browser.close_when_finished(session,window,folder))
            session._completed='範囲の取り込みが完了しました。'
            with session._work_lock:
                self.assertFalse(site777_browser.close_when_finished(session,window,folder),'保存の処理中は閉じない')
            self.assertEqual(closed,[])
            self.assertTrue(site777_browser.close_when_finished(session,window,folder))
            self.assertEqual(closed,[True])
            self.assertEqual(site777_browser.take_finished_message(folder),'範囲の取り込みが完了しました。')
            self.assertIsNone(site777_browser.take_finished_message(folder),'知らせは1回だけ')

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

    def test_the_window_keeps_page_timers_like_pscube(self):
        """2026-11-21：見えない2つ目の窓でグラフ待ちが毎分同じ秒にしか動いていなかった。窓を作る前に P’s CUBE と同じ
        起動設定（見えない窓の時計を間引かない・覆われても見えている扱い）を WebView2 の環境変数へ足す。"""
        import os
        from unittest import mock
        from pscube_import import BROWSER_ARGUMENTS

        class Stop(Exception):
            pass

        def create_window(*args, **kwargs):
            seen.append(os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', ''))
            raise Stop()

        seen = []
        fake = SimpleNamespace(create_window=create_window)
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(sys.modules, {'webview': fake}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', None)
            with self.assertRaises(Stop):
                site777_browser.run(folder)
        self.assertEqual(len(seen), 1)
        self.assertIn(BROWSER_ARGUMENTS, seen[0])

    def test_two_windows_keep_separate_notice_files_and_do_not_erase_each_other(self):
        # 2窓運用で窓ごとの知らせファイルを分離し、2つ目の窓を開いても1つ目の窓の知らせを消さない。
        import threading
        import app
        from site777_session import Session

        cmd1, _ = app.site777_browser_command('win1')
        self.assertEqual(cmd1[-1], 'win1')
        cmd_default, _ = app.site777_browser_command()
        self.assertEqual(len(cmd_default), 3)

        with tempfile.TemporaryDirectory() as folder:
            closed = []
            window = SimpleNamespace(destroy=lambda: closed.append(True))
            s1 = SimpleNamespace(_completed='窓1が完了', _work_lock=threading.Lock(),
                                 _backup_after_close=lambda: 'バックアップに失敗（窓1）')
            self.assertTrue(site777_browser.close_when_finished(s1, window, folder, window_id='win1'))
            site777_browser.backup_after_close(s1, folder, site777_browser.DiagnosticLog(folder), window_id='win1')
            sess1 = Session(folder, site777_browser.DiagnosticLog(folder), window_id='win1')
            sess1.pause('窓1が停止', 'navigation_failed')

            # 2つ目の窓が自分の知らせを掃除しても、1つ目の窓の知らせは消えない
            self.assertIsNone(site777_browser.take_finished_message(folder, window_id='win2'))
            self.assertIsNone(site777_browser.take_backup_message(folder, window_id='win2'))
            self.assertIsNone(site777_browser.take_stop_message(folder, window_id='win2'))

            self.assertEqual(site777_browser.take_finished_message(folder, window_id='win1'), '窓1が完了')
            self.assertIn('バックアップに失敗（窓1）', site777_browser.take_backup_message(folder, window_id='win1'))
            self.assertIn('窓1が停止', site777_browser.take_stop_message(folder, window_id='win1'))

    def test_wait_notices_are_isolated_per_window_and_checked_in_watcher(self):
        # G13（2026-11-23）：最小化中の待機知らせも窓IDごとに分離し、起動時に掃除、監視スレッドで定期確認する。
        from site777_session import Session
        with tempfile.TemporaryDirectory() as folder:
            s1 = Session(folder, site777_browser.DiagnosticLog(folder), window_id='win1')
            s1.configure(True, s1._day, direction='bottom')
            s1.note(json.dumps({'kind': 'graph_hidden', 'day': s1._day, 'page': 1}))
            self.assertIsNone(site777_browser.take_wait_message(folder, window_id='win2'))
            msg = site777_browser.take_wait_message(folder, window_id='win1')
            self.assertIsNotNone(msg)
            self.assertIn('最小化', msg)
            self.assertIn('下から', msg)
            self.assertIsNone(site777_browser.take_wait_message(folder, window_id='win1'))
        source = Path(site777_browser.__file__).read_text(encoding='utf-8')
        self.assertIn('take_wait_message(data_dir, window_id)', source)
        self.assertIn('session._check_hidden_wait()', source)

    def test_app_watch_capture_window_polls_wait_notice_while_open_and_clears_on_close(self):
        # G13（2026-11-23）：窓が開いている間に最小化の待機・再開知らせをPCアプリ本体のログ欄へ出し、
        # 例外でも監視を止めず、窓が閉じたときは未読の待機知らせをログ欄へ出さずに掃除する。
        import textwrap
        import forward_validation
        app_source = (Path(site777_browser.__file__).resolve().parent / 'app.py').read_text(encoding='utf-8')
        self.assertIn('poll_notice=lambda: site777_browser.take_wait_message(DATA_DIR, window_id)', app_source)
        start = app_source.index('    def watch_capture_window(')
        end = app_source.index('    def poll_forward_results(')
        code = textwrap.dedent(app_source[start:end])

        class FakeRoot:
            def __init__(self):
                self.after_calls = []

            def after(self, ms, func):
                self.after_calls.append((ms, func))

        class FakeLogbox:
            def __init__(self):
                self.lines = []
                self.seen = 0

            def insert(self, where, text):
                self.lines.append(text)

            def see(self, where):
                self.seen += 1

        class FakeErrors:
            def __init__(self):
                self.records = []

            def record(self, data_dir, where, error):
                self.records.append((where, type(error).__name__))

        class FakeProcess:
            def __init__(self):
                self.code = None

            def poll(self):
                return self.code

        with tempfile.TemporaryDirectory() as folder:
            root, logbox, errors = FakeRoot(), FakeLogbox(), FakeErrors()
            started_daily, pending_checks = [], []
            env = {
                'check_pending_forward': lambda: pending_checks.append(1),
                'capture_tracker': forward_validation.CaptureWindowTracker(),
                'forward_gate': forward_validation.ForwardWindowGate(),
                'forward_validation': forward_validation,
                'root': root, 'logbox': logbox, 'error_log': errors,
                'DATA_DIR': Path(folder),
                'start_daily': lambda **kw: started_daily.append(kw),
                'save_forward_after': lambda *a: None,
            }
            exec(code, env)  # noqa: S102 - app.pyのwatch_capture_windowだけを偽UIで動かす
            proc = FakeProcess()
            notices = iter(['19:00 窓が最小化されているため、グラフの読み込みを待っています',
                            RuntimeError('読取失敗'),
                            '19:05 窓が戻ったため、グラフの読み込みを続けます',
                            '19:06 閉じたあとに残っていた未読の待機知らせ'])
            consumed = []

            def poll_notice():
                item = next(notices, None)
                if isinstance(item, Exception):
                    raise item
                if item is not None:
                    consumed.append(item)
                return item

            env['watch_capture_window'](proc, 'サイトセブン', lambda: None, poll_notice=poll_notice)
            # 1回目：待機知らせがログ欄に出る
            root.after_calls.pop(0)[1]()
            self.assertEqual(logbox.lines, ['サイトセブン：19:00 窓が最小化されているため、グラフの読み込みを待っています\n'])
            self.assertEqual(len(root.after_calls), 1)
            # 2回目：読取例外が出ても記録するだけで監視ループが止まらない
            root.after_calls.pop(0)[1]()
            self.assertEqual(errors.records, [('capture.poll_notice', 'RuntimeError')])
            self.assertEqual(len(root.after_calls), 1)
            # 3回目：窓が戻った再開知らせがログ欄に出る
            root.after_calls.pop(0)[1]()
            self.assertIn('窓が戻ったため', logbox.lines[-1])
            self.assertEqual(len(root.after_calls), 1)
            # 4回目：窓が閉じたときは未読の待機知らせを掃除するが、ログ欄には出さない
            proc.code = 0
            root.after_calls.pop(0)[1]()
            self.assertEqual(consumed[-1], '19:06 閉じたあとに残っていた未読の待機知らせ')
            self.assertFalse(any('閉じたあとに残っていた' in line for line in logbox.lines))
            self.assertIn('サイトセブンの取り込み画面を閉じました。', logbox.lines[-1])
            self.assertEqual(len(started_daily), 1)
            # P-STATION の窓がすべて閉じたら、前夜の翌朝の印も確かめる（2026-11-24。時刻・印は start_pending が見る）
            self.assertEqual(len(pending_checks), 1)


if __name__ == '__main__':
    unittest.main()
