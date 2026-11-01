import gc
import itertools
import importlib.util
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from test_anaslo_download import client, html, link
from anaslo_download import Result

CONVERTER = Path(__file__).resolve().parents[2] / 'html_converter'
if str(CONVERTER) not in sys.path:
    sys.path.append(str(CONVERTER))
from download_dialog import DownloadDialog


class DialogTests(unittest.TestCase):
    # Tkは作ったスレッド（メインスレッド）で片付ける。循環参照のまま残すと、後の試験の別スレッドでGCが走ったときに
    # 「Tcl_AsyncDelete: async handler deleted by the wrong thread」でプロセスごと落ちる（2026-10-18）。
    @classmethod
    def tearDownClass(cls):
        gc.collect()  # 最後の試験のTkを、次の試験へ移る前に片付ける

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        gc.collect()  # 前の試験のTkをここで片付ける（この試験は別スレッドで取得を動かす）
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.used = []
        self.dialog = DownloadDialog(self.root, lambda paths: self.used.extend(paths))
        self.dialog.withdraw()
        self.dialog.method.set('direct')
        self.dialog.folder.set(str(self.folder / 'downloads'))
        self.index = self.folder / 'index.html'
        self.index.write_text(f'<a href="{link("2026-09-15").url}">A</a><a href="{link("2026-09-16").url}">B</a>', encoding='utf-8')
        self.dialog.saved_index.set(str(self.index))
        self.dialog.local.set(True)
        self.dialog.start_day.set('2026-09-15')
        self.dialog.end_day.set('2026-09-15')

    def finish(self):
        deadline = time.monotonic() + 5
        while self.dialog.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.assertFalse(self.dialog.busy)

    def poll_once(self):
        # Manual polling in a test replaces the scheduled callback.
        self.dialog.after_cancel(self.dialog.after_id)
        self.dialog.poll()

    def test_offline_scan_worker_download_and_handoff_only_selected_day(self):
        engine, opener = client([html()])
        self.dialog.client = engine
        self.dialog.scan()
        self.finish()
        self.assertEqual([r.day for r in self.dialog.links], ['2026-09-15'])
        self.assertEqual(opener.calls, [])
        self.dialog.start()
        self.finish()
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(len(self.dialog.paths), 1)
        self.dialog.use()
        self.assertEqual(len(self.used), 1)
        self.assertIn('2026-09-15', self.used[0].name)

    def test_changed_range_requires_new_preview(self):
        engine, opener = client([])
        self.dialog.client = engine
        self.dialog.scan()
        self.finish()
        self.dialog.end_day.set('2026-09-16')
        self.dialog.start()
        self.assertEqual(opener.calls, [])
        self.assertIsNone(self.dialog.scan_key)
        self.assertEqual(str(self.dialog.start_button['state']), 'disabled')

    def test_blank_dates_do_not_start_a_worker(self):
        self.dialog.start_day.set('')
        with patch('download_dialog.messagebox.showerror') as error, patch.object(self.dialog, 'launch') as launch:
            self.dialog.scan()
            self.assertTrue(error.called)
            launch.assert_not_called()

    def test_browser_stop_reason_is_shown_and_logged(self):
        self.dialog.events.put(('download', Result(stopped='ブラウザが閉じられました。')))
        with patch('download_dialog.messagebox.showwarning') as warning:
            self.poll_once()
        warning.assert_called_once()
        self.assertIn('ブラウザが閉じられました。', self.dialog.log.get('1.0', 'end'))
        self.assertFalse(self.dialog.busy)

    def test_scan_error_is_visible_but_user_stop_has_no_warning(self):
        self.dialog.events.put(('error', '起動エラー'))
        with patch('download_dialog.messagebox.showwarning') as warning:
            self.poll_once()
            warning.assert_called_once()
        self.dialog.cancel.set()
        self.dialog.events.put(('download', Result(stopped='利用者が停止しました。')))
        with patch('download_dialog.messagebox.showwarning') as warning:
            self.poll_once()
            warning.assert_not_called()

    def test_zero_dates_has_explicit_warning_and_listing_range(self):
        self.dialog.start_day.set('2026-08-01')
        self.dialog.end_day.set('2026-08-31')
        with patch('download_dialog.messagebox.showwarning') as warning:
            self.dialog.scan()
            self.finish()
        warning.assert_called_once()
        self.assertIn('対象0日', self.dialog.status.get())
        self.assertIn('2026-09-15〜2026-09-16', self.dialog.log.get('1.0', 'end'))

    def test_browser_index_session_is_reused_for_daily_download(self):
        from anaslo_browser import BrowserClient
        from test_anaslo_browser import FakeSession
        self.dialog.local.set(False)
        self.dialog.method.set('browser')
        raw = ('<h1>P-STATION&amp;IIスロット館 データ一覧</h1>'
               f'<a href="{link("2026-09-15").url}">9/15</a>'
               '<script>const captchaEnabled = false;</script>').encode('utf-8')
        session = FakeSession([raw, html()])
        engines = []
        # 時計を読むたびに100秒進める（間隔は読み終えた時刻から数えるので、本当に待たないように）。
        ticks = itertools.count()
        def factory(profile, **kwargs):
            engine = BrowserClient(profile, session_factory=lambda p: session,
                                   clock=lambda: 100.0 * next(ticks), **kwargs)
            engines.append(engine)
            return engine
        self.dialog.browser_factory = factory
        with patch('download_dialog.messagebox.showwarning') as warning:
            self.dialog.scan()
            self.finish()
        warning.assert_not_called()
        self.assertFalse(session.closed)
        self.assertEqual(len(self.dialog.table.get_children()), 1)
        self.assertIn('対象1日', self.dialog.status.get())
        self.assertTrue(self.dialog.browser_idle_after)
        self.dialog.start()
        self.finish()
        self.assertEqual(len(engines), 1)
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(session.closed)
        self.assertIsNone(self.dialog.browser_idle_after)
        self.assertIsNone(self.dialog.scan_key)
        self.assertEqual(len(self.dialog.paths), 1)

    def test_kept_browser_expires_and_requires_preview_again(self):
        from unittest.mock import Mock
        engine = Mock()
        self.dialog.browser_engine = engine
        self.dialog.scan_key = self.dialog.key()
        self.dialog.links = [link('2026-09-15')]
        self.dialog.expire_browser()
        self.dialog.browser_cleanup.join(1)
        engine.close.assert_called_once()
        self.assertIsNone(self.dialog.browser_engine)
        self.assertIsNone(self.dialog.scan_key)
        self.assertEqual(str(self.dialog.start_button['state']), 'disabled')

    def test_input_change_closes_kept_browser(self):
        from unittest.mock import Mock
        engine = Mock()
        self.dialog.browser_engine = engine
        self.dialog.start_day.set('2026-09-16')
        self.dialog.browser_cleanup.join(1)
        engine.close.assert_called_once()
        self.assertIsNone(self.dialog.browser_engine)

    def test_unrecognized_index_is_not_silent_zero_dates(self):
        self.index.write_text('<html><h1>unexpected page</h1></html>', encoding='utf-8')
        with patch('download_dialog.messagebox.showwarning') as warning, patch('download_dialog.LOGGER'):
            self.dialog.scan()
            self.finish()
        warning.assert_called_once()
        self.assertIn('日別リンクを確認できません', self.dialog.status.get())

    def test_ui_exception_reports_reason_and_keeps_poll_scheduled(self):
        self.dialog.events.put(('scan', (self.dialog.key(), [link('2026-09-15')])))
        with patch.object(self.dialog.table, 'insert', side_effect=tk.TclError('test UI error')), patch('download_dialog.messagebox.showwarning') as warning, patch('download_dialog.LOGGER') as logger:
            self.poll_once()
        warning.assert_called_once()
        logger.exception.assert_called_once()
        self.assertIn('test UI error', self.dialog.status.get())
        self.assertFalse(self.dialog.busy)
        self.assertTrue(self.dialog.after_id)

    def test_existing_converter_load_path_connection(self):
        spec = importlib.util.spec_from_file_location('converter_ui_test', CONVERTER / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        converter = ui.Converter(self.root)
        converter.aliases = {}
        path = self.folder / '2026-09-15.html'
        path.write_bytes(html())
        with patch('anaslo_converter.read_catalog', return_value=[]):
            converter.load_paths([path])
        self.assertEqual(converter.target.hall.key, 'p-station')
        self.assertEqual(len(converter.names), 1)
        self.assertEqual(converter.staging['days'][0]['day'], '2026-09-15')
        # This check only reads/analyzes; it does not save alias tables or JSON.
        self.assertFalse((self.folder / 'downloads').exists())

    def test_month_of_data_has_short_default_json_filename(self):
        spec = importlib.util.spec_from_file_location('converter_filename_test', CONVERTER / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        converter = ui.Converter(self.root)
        converter.staging = {'days': [{'day': (date(2026, 8, 1) + timedelta(days=i)).isoformat()} for i in range(31)]}
        with patch('anaslo_converter.read_catalog', return_value=[]):
            converter.target = ui.PscubeTarget(self.folder)
        with patch.object(converter.target, 'make_backup', return_value={'records': []}), patch.object(ui.filedialog, 'asksaveasfilename', return_value='') as choose:
            converter.save()
        filename = choose.call_args.kwargs['initialfile']
        self.assertEqual(filename, 'pscube-backup-anaslo-20260801-20260831.json')
        (self.folder / filename).write_text('{}', encoding='utf-8')

    def test_wait_is_kept_across_browser_operations_and_method_change(self):
        from anaslo_browser import BrowserClient
        from test_anaslo_browser import FakeSession
        engine, opener = client([html()])
        self.dialog.client = engine
        self.addCleanup(setattr, self.dialog, 'cancel', self.dialog.cancel)
        self.dialog.cancel = engine.cancel
        def factory(profile, **kwargs):
            return BrowserClient(profile, session_factory=lambda p: FakeSession([html()]),
                                 clock=engine.clock, jitter=lambda: 6, **kwargs)
        self.dialog.browser_factory = factory
        for _ in range(2):
            self.dialog.with_client(lambda e: e.get(link('2026-09-15').url), 'browser')
        self.dialog.with_client(lambda e: e.get(link('2026-09-15').url), 'direct')
        self.assertEqual(engine.cancel.waits, [0, 6, 6])

    def test_reopening_download_dialog_keeps_pacing(self):
        spec = importlib.util.spec_from_file_location('converter_pacing_test', CONVERTER / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        converter = ui.Converter(self.root)
        converter.download_pacing.next_request = 123.0
        with patch('download_dialog.DownloadDialog') as create:
            converter.open_download()
            converter.open_download()
        for call in create.call_args_list:
            self.assertIs(call.kwargs['pacing'], converter.download_pacing)
            self.assertEqual(call.kwargs['pacing'].next_request, 123.0)


if __name__ == '__main__':
    unittest.main()
