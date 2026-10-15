"""The real Tk startup import stays responsive during background output."""
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
import app
from core import Store, export_backup, save_settings
from output_worker import OutputWorker


class AppOutputWorkerTests(unittest.TestCase):
    def test_startup_import_keeps_tk_timers_running_during_report_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root_path = Path(directory); data = root_path / 'data'; sync = root_path / 'sync'; sync.mkdir()
            source = Store(root_path / 'source.sqlite3')
            source.save([dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine='試験', rack=537, games=3000, bb=10, rb=5)])
            export_backup(source, sync / 'database-backup-test.json'); source.close()
            save_settings(data, auto_sync_on_start=True, sync_dir=str(sync))
            entered, release = threading.Event(), threading.Event()
            workers, roots, ticks, failures = [], [], [], []
            original_tk, original_output = tk.Tk, app.refresh_outputs
            def worker(run):
                result = OutputWorker(run); workers.append(result); return result
            def delayed(*args, **kwargs):
                entered.set(); release.wait(3)
                return original_output(*args, **kwargs)
            def make_root():
                root = original_tk(); root.withdraw(); roots.append(root)
                def tick():
                    ticks.append(time.monotonic())
                    root.after(10, tick)
                root.after(10, tick)
                def loop():
                    deadline = time.monotonic() + 2
                    while not entered.is_set() and time.monotonic() < deadline:
                        root.update(); time.sleep(0.005)
                    self.assertTrue(entered.is_set(), 'startup imported and queued real output')
                    count = len(ticks)
                    for _ in range(15): root.update(); time.sleep(0.005)
                    self.assertGreater(len(ticks), count, 'Tk is responsive while output is blocked')
                    release.set()
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        root.update(); time.sleep(0.005)
                        if (root_path / 'reports' / 'database-history.html').exists(): break
                    self.assertTrue((root_path / 'reports' / 'database-history.html').exists())
                root.mainloop = loop
                return root
            try:
                with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), patch.object(app.tk, 'Tk', make_root), patch.object(app, 'OutputWorker', worker), patch.object(app, 'refresh_outputs', delayed), patch.object(app.messagebox, 'showerror', side_effect=lambda *a, **k: failures.append(a)):
                    app.main()
                self.assertEqual(failures, [])
            finally:
                release.set()
                for w in workers:
                    w.finish()
                    if w.thread: w.thread.join(3)
                for root in roots: root.destroy()
