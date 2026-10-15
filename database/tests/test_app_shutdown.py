"""Exercise the real Tk close protocol with temporary data and output workers."""
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from core import save_settings
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
                with patch.object(app, 'ROOT', folder), patch.object(app, 'DATA_DIR', data), \
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
