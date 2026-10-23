"""実際のPC画面で、フォルダ指定・再出力・完了通知を確認する。"""
import tempfile
import threading
import time
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app
from backup_status import read_status
from core import Store, save_settings, VIEWER_FILE_NAME
from output_worker import OutputWorker


class SharedOutputUiTests(unittest.TestCase):
    def test_selecting_folder_waits_for_completion_and_update_button_reuses_saved_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root_path = Path(directory)
            data, shared = root_path / 'data', root_path / 'shared'
            shared.mkdir()
            save_settings(data, sync_dir=str(shared), auto_sync_on_start=False)
            with closing(Store(data / 'database.sqlite3')) as store:
                store.save([dict(store=place, kind_code=21, day='2026-10-22', machine='試験',
                                 rack=rack, games=3000, bb=10, rb=5)
                            for place, rack in [('saiwaichou', 537), ('nagamachiminami', 101)]])
            entered, release = threading.Event(), threading.Event()
            roots, workers, failures = [], [], []
            real_tk, real_refresh = tk.Tk, app.refresh_outputs
            def worker(run):
                result = OutputWorker(run); workers.append(result)
                return result
            def delayed(*args, **kwargs):
                entered.set(); release.wait(4)
                return real_refresh(*args, **kwargs)
            def make_root():
                root = real_tk(); root.withdraw(); roots.append(root)
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                def pump(predicate):
                    deadline = time.monotonic() + 3
                    while not predicate() and time.monotonic() < deadline:
                        root.update(); time.sleep(0.01)
                    self.assertTrue(predicate())
                def loop():
                    buttons = {str(w.cget('text')): w for w in descendants(root) if w.winfo_class() == 'TButton'}
                    log = next(w for w in descendants(root) if isinstance(w, tk.Text))
                    update = buttons['共有用ファイルを更新']
                    buttons['同期フォルダを指定'].invoke()
                    self.assertTrue(entered.wait(1))
                    root.update()
                    self.assertIn('更新を受け付けました', log.get('1.0', 'end'))
                    self.assertNotIn('書き出しました', log.get('1.0', 'end'))
                    self.assertNotIn('出力更新が完了', log.get('1.0', 'end'))
                    self.assertTrue(update.instate(['disabled']))
                    self.assertFalse((shared / VIEWER_FILE_NAME).exists())
                    buttons['更新状況の詳細'].invoke()
                    details = next(w for w in descendants(root) if isinstance(w, tk.Text) and w is not log)
                    self.assertIn('以下は前回までの結果', details.get('1.0', 'end'))
                    self.assertEqual(str(details.cget('state')), 'disabled')
                    release.set()
                    pump(lambda: not update.instate(['disabled']))
                    self.assertEqual(read_status(data, 'meruhen')['state'], 'success')
                    self.assertIn('出力更新が完了', log.get('1.0', 'end'))
                    reload = next(w for w in descendants(root) if w.winfo_class() == 'TButton' and str(w.cget('text')) == '状況を読み直す')
                    reload.invoke()
                    self.assertIn('長町南：最新の記録日 2026-10-22', details.get('1.0', 'end'))
                    self.assertIn('幸町：最新の記録日 2026-10-22', details.get('1.0', 'end'))
                    details.winfo_toplevel().destroy()
                    first = read_status(data, 'meruhen')['at']
                    update.invoke()
                    pump(lambda: not update.instate(['disabled']))
                    self.assertNotEqual(read_status(data, 'meruhen')['at'], first)
                    with closing(Store(data / 'database.sqlite3')) as store:
                        self.assertEqual(len(store.rows()), 2, '再取り込みなしで同じ記録を出す')
                    self.assertFalse((data / 'pscube.sqlite3').exists(), '存在しない別サイトのDBを作らない')
                root.mainloop = loop
                return root
            try:
                with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), \
                     patch.object(app.tk, 'Tk', make_root), patch.object(app, 'OutputWorker', worker), \
                     patch.object(app, 'refresh_outputs', delayed), \
                     patch.object(app.filedialog, 'askdirectory', return_value=str(shared)), \
                     patch.object(app.subprocess, 'Popen', side_effect=AssertionError('取り込みを起動しない')), \
                     patch.object(app.messagebox, 'showerror', side_effect=lambda *args, **kw: failures.append(args)):
                    app.main()
                self.assertEqual(failures, [])
            finally:
                release.set()
                for w in workers:
                    w.finish()
                    if w.thread: w.thread.join(4)
                for root in roots: root.destroy()
