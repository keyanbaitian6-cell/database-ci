"""Exercise the real Tk close protocol with temporary data and output workers."""
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import core
from core import Store, save_settings
from output_worker import OutputWorker


class AppShutdownTests(unittest.TestCase):
    def check_close(self, running_output):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            data = folder / 'data'
            save_settings(data, auto_sync_on_start=False)
            entered, release = threading.Event(), threading.Event()
            errors, callbacks, roots, workers = [], [], [], []
            original_tk = tk.Tk

            def output(**flags):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError('test did not release output')
                return {'timings': {'backup': 0.01}}

            def make_worker(run):
                worker = OutputWorker(output)
                workers.append(worker)
                return worker

            def make_root():
                root = original_tk()
                root.withdraw()
                roots.append(root)
                original_loop = root.mainloop
                root.report_callback_exception = lambda *args: errors.append(args)

                def loop():
                    worker = workers[0]
                    if running_output:
                        worker.request(backup=True, done=lambda result: callbacks.append(result))
                        self.assertTrue(entered.wait(1))
                        worker.request(history=True, done=lambda result: callbacks.append(result))

                    def close():
                        root.tk.call(root.protocol('WM_DELETE_WINDOW'))
                        if running_output:
                            # Repeated close requests must not discard pending output.
                            root.tk.call(root.protocol('WM_DELETE_WINDOW'))

                    def finish_output():
                        try:
                            self.assertTrue(root.winfo_exists(), 'window waits for output')
                            self.assertTrue(worker.closing, 'close reaches worker.finish')
                            # Existing widgets must receive a valid class binding.
                            tags = root.winfo_children()[0].bindtags()
                            self.assertTrue(root.bind_class(tags[0], '<ButtonPress>'))
                            self.assertTrue(root.bind_class(tags[0], '<KeyPress>'))
                        except Exception as error:
                            errors.append(error)
                        finally:
                            release.set()

                    def watchdog():
                        errors.append('shutdown timed out')
                        release.set()
                        root.destroy()

                    root.after(0, close)
                    if running_output:
                        root.after(100, finish_output)
                    root.after(2000, watchdog)
                    original_loop()

                root.mainloop = loop
                return root

            try:
                with patch.object(app, 'ROOT', folder), patch.object(app, 'DATA_DIR', data), patch('daily_learning_runtime.run_due', return_value=(False, None)), \
                        patch.object(app.tk, 'Tk', make_root), patch.object(app, 'OutputWorker', make_worker):
                    app.main()
                self.assertEqual(errors, [])
                self.assertTrue(workers[0].finished)
                self.assertEqual(len(callbacks), 2 if running_output else 0)
                if callbacks:
                    self.assertIsNone(callbacks[0].error)
            finally:
                release.set()
                for worker in workers:
                    worker.finish()
                    if worker.thread:
                        worker.thread.join(3)
                for root in roots:
                    try:
                        root.destroy()
                    except tk.TclError:
                        pass

    def test_close_idle_window_finishes_without_tk_errors(self):
        self.check_close(False)

    def test_close_waits_for_output_and_delivers_completion(self):
        self.check_close(True)

    def test_close_during_history_page_stops_it_and_still_writes_backup(self):
        """2026-10-17 利用者「終了処理に時間がかかるね。さっき15秒くらい、いま10秒」。×のあと、
        「過去の記録」（PC内のページ。開くときに必ず作り直す）の作り直しが終わるまで待っていた
        （試験用の38,500件で13.3秒）。閉じる途中はそれをやめ、バックアップ・閲覧用ファイルは最後まで書く。"""
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            data, sync = folder / 'data', folder / 'sync'
            sync.mkdir()
            store = Store(data / 'database.sqlite3')
            store.save([dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine=f'試験{n}', rack=500 + n,
                             games=3000, bb=10, rb=5) for n in range(12)])
            store.close()
            save_settings(data, auto_sync_on_start=False, sync_dir=str(sync))
            original_tk, original_scored = tk.Tk, core.scored_rows
            entered = threading.Event()
            errors, roots, workers, timing = [], [], [], {}

            def slow_scored(*args, **kwargs):
                # 1機種0.4秒：最後まで作ると約5秒（実データ規模の10秒以上の代わり）。
                entered.set()
                time.sleep(0.4)
                return original_scored(*args, **kwargs)

            def make_worker(run):
                worker = OutputWorker(run)
                workers.append(worker)
                return worker

            def make_root():
                root = original_tk()
                root.withdraw()
                roots.append(root)
                root.report_callback_exception = lambda *args: errors.append(args)
                original_loop, original_destroy = root.mainloop, root.destroy

                def destroy():
                    timing.setdefault('destroyed', time.monotonic())
                    original_destroy()
                root.destroy = destroy

                def loop():
                    workers[0].request(history=True, backup=True)

                    def close_when_history_runs():
                        if not entered.is_set():
                            root.after(10, close_when_history_runs)
                            return
                        timing['closed'] = time.monotonic()
                        root.tk.call(root.protocol('WM_DELETE_WINDOW'))

                    def watchdog():
                        errors.append('shutdown timed out')
                        root.destroy()

                    root.after(0, close_when_history_runs)
                    root.after(15000, watchdog)
                    original_loop()

                root.mainloop = loop
                return root

            try:
                with patch.object(app, 'ROOT', folder), patch.object(app, 'DATA_DIR', data), patch('daily_learning_runtime.run_due', return_value=(False, None)),                         patch.object(app.tk, 'Tk', make_root), patch.object(app, 'OutputWorker', make_worker),                         patch.object(core, 'scored_rows', slow_scored):
                    app.main()
                self.assertEqual(errors, [])
                self.assertTrue(workers[0].finished)
                waited = timing['destroyed'] - timing['closed']
                self.assertLess(waited, 2.5, f'close waited {waited:.2f}s for the history page')
                self.assertFalse((folder / 'reports' / 'database-history.html').exists())
                backup = json.loads((sync / core.AUTO_BACKUP_NAME).read_text(encoding='utf-8'))
                self.assertEqual(len(backup['records']), 12, 'backup is written in full before the window closes')
                self.assertTrue((sync / core.VIEWER_FILE_NAME).exists())
            finally:
                for worker in workers:
                    worker.finish()
                    if worker.thread:
                        worker.thread.join(15)
                for root in roots:
                    try:
                        root.destroy()
                    except tk.TclError:
                        pass
