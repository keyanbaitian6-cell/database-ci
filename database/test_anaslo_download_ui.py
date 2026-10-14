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

CONVERTER = Path(__file__).resolve().parents[1] / 'html_converter'
if str(CONVERTER) not in sys.path:
    sys.path.append(str(CONVERTER))
from download_dialog import DownloadDialog


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
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

    def test_existing_converter_load_path_connection(self):
        spec = importlib.util.spec_from_file_location('converter_ui_test', CONVERTER / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        converter = ui.Converter(self.root)
        converter.aliases = {}
        path = self.folder / '2026-09-15.html'
        path.write_bytes(html())
        with patch.object(ui, 'read_catalog', return_value=[]):
            converter.load_paths([path])
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
        with patch.object(ui, 'make_backup', return_value={'records': []}), patch.object(ui.filedialog, 'asksaveasfilename', return_value='') as choose:
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
