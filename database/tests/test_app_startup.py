"""起動中に開いていないタブの履歴を読まない。隔離DB・非表示Tkで検証する。"""
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from core import Store, save_settings


class AppStartupTests(unittest.TestCase):
    def test_variety_is_built_only_on_first_open_and_refreshed_on_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            root_path = Path(folder)
            data = root_path / 'data'
            db = Store(data / 'database.sqlite3')
            db.save([dict(store='nagamachiminami', kind_code=21, day='2026-10-10',
                          machine='テスト', rack=50, games=3000, bb=10, rb=5, max_hold=1000)])
            db.close()
            save_settings(data, auto_sync_on_start=False, sync_dir='')
            original_tk = tk.Tk
            original_builder = app.build_variety_tab
            roots = []
            refreshes = []

            def build(*args, **kwargs):
                refresh = original_builder(*args, **kwargs)
                def call():
                    refreshes.append(1)
                    refresh()
                return call

            def make_root():
                root = original_tk()
                roots.append(root)
                root.withdraw()
                def mainloop():
                    root.update()
                    builder.assert_not_called()
                    notebook = next(w for frame in root.winfo_children() for w in frame.winfo_children()
                                    if isinstance(w, ttk.Notebook))
                    tab = next(t for t in notebook.tabs() if 'バラエティ' in notebook.tab(t, 'text'))
                    notebook.select(tab)
                    root.update()
                    builder.assert_called_once()
                    self.assertEqual(refreshes, [1])
                    notebook.select(notebook.tabs()[0])
                    root.update()
                    notebook.select(tab)
                    root.update()
                    builder.assert_called_once()
                    self.assertEqual(refreshes, [1, 1])
                root.mainloop = mainloop
                return root

            try:
                with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), \
                     patch.object(app.tk, 'Tk', make_root), patch.object(app, 'build_variety_tab', side_effect=build) as builder:
                    app.main()
            finally:
                for root in roots:
                    root.destroy()


if __name__ == '__main__':
    unittest.main()
