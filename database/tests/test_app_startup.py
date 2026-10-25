"""起動中に開いていないタブの履歴を読まない。隔離DB・非表示Tkで検証する。"""
import os
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from core import Store, export_backup, load_settings, save_settings


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

    def test_startup_imports_each_new_store_backup_and_sync_tab_scrolls_to_the_import_button(self):
        # 2026-10-25 利用者報告：店舗ごとに書き出した2本のうち新しい1本しか読まれず、
        # 手で読み込む「バックアップを読み込む」も窓の下に隠れて押せなかった。
        with tempfile.TemporaryDirectory() as folder:
            root_path = Path(folder)
            data, sync = root_path / 'data', root_path / 'sync'
            sync.mkdir()
            Store(data / 'database.sqlite3').close()
            def backup(name, store, mtime):
                source = Store(root_path / f'{store}.sqlite3')
                source.save([dict(store=store, kind_code=21, day='2026-10-24', machine='テスト', rack=50,
                                  games=3000, bb=10, rb=5, max_hold=1000)])
                path = sync / name
                export_backup(source, path)
                source.close()
                os.utime(path, (mtime, mtime))
                return path
            old = backup('database-backup-android-20261022-160927.json', 'saiwaichou', 1_790_000_000)
            backup('database-backup-android-20261025-071058.json', 'nagamachiminami', 1_790_000_100)
            newest = backup('database-backup-android-20261025-093930.json', 'saiwaichou', 1_790_000_200)
            save_settings(data, sync_dir=str(sync), last_synced=dict(name=old.name, mtime=1_790_000_000))
            original_tk = tk.Tk
            roots = []

            def make_root():
                root = original_tk()
                roots.append(root)
                root.geometry('920x620')
                def mainloop():
                    # 起動時の取り込みは root.after(400, …) で予約される。それより後の目印まで処理を進める。
                    passed = []
                    root.after(450, lambda: passed.append(True))
                    while not passed:
                        root.update()
                        time.sleep(0.01)
                    notebook = next(w for frame in root.winfo_children() for w in frame.winfo_children()
                                    if isinstance(w, ttk.Notebook))
                    tab = next(t for t in notebook.tabs() if 'バックアップ' in notebook.tab(t, 'text'))
                    notebook.select(tab)
                    root.update()
                    page = root.nametowidget(tab)
                    canvas = next(w for w in page.winfo_children() if isinstance(w, tk.Canvas))
                    def find(widget):
                        for child in widget.winfo_children():
                            if isinstance(child, ttk.Button) and child.cget('text') == 'バックアップを読み込む':
                                return child
                            found = find(child)
                            if found is not None:
                                return found
                    button = find(page)
                    self.assertIsNotNone(button)
                    canvas.yview_moveto(1.0)
                    root.update()
                    top = button.winfo_rooty() - canvas.winfo_rooty()
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(top + button.winfo_height(), canvas.winfo_height())
                root.mainloop = mainloop
                return root

            try:
                with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), \
                     patch.object(app.tk, 'Tk', make_root):
                    app.main()
            finally:
                for root in roots:
                    root.destroy()
            db = Store(data / 'database.sqlite3')
            try:
                stores = {r[0] for r in db.db.execute('SELECT DISTINCT store FROM days')}
            finally:
                db.close()
            self.assertEqual(stores, {'saiwaichou', 'nagamachiminami'})
            self.assertEqual(load_settings(data)['last_synced']['name'], newest.name)


if __name__ == '__main__':
    unittest.main()
