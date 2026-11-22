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
    def tearDown(self):
        import gc
        gc.collect()  # Tcl_AsyncDelete 対策：破棄した Tk を別スレッドの GC へ持ち越さない

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
                    # 2026-11-01：機種一覧を足し、「結果を見る」（HTML）は利用者「端っこにおいておいて」で右端。
                    self.assertEqual([notebook.tab(t, 'text').strip() for t in notebook.tabs()],
                                     ['取り込み', '機種一覧', 'バラエティ🌈', 'バックアップ・同期', '結果を見る'])
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
                with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), patch('daily_learning_runtime.run_due', return_value=(False, None)), \
                     patch.object(app.tk, 'Tk', make_root), patch.object(app, 'build_variety_tab', side_effect=build) as builder:
                    app.main()
            finally:
                for root in roots:
                    root.destroy()

    def test_sync_banner_warns_once_when_the_drive_is_missing_and_shows_a_switch(self):
        # 2026-11-03 利用者「ドライブレター変わってるのに気づかず取り込み終えてしまった」→「自動で探して知らせる」。
        import json
        with tempfile.TemporaryDirectory() as folder:
            root_path = Path(folder)
            data = root_path / 'data'
            Store(data / 'database.sqlite3').close()
            missing = root_path / 'G' / 'database共有'
            save_settings(data, sync_dir=str(missing), sync_mark='mine', auto_sync_on_start=False)
            (data / 'backup-output-meruhen.json').write_text(json.dumps(dict(
                version=1, source='meruhen', folder=str(missing), state='unavailable', at='2026-11-03T06:39:26+09:00',
                message='同期フォルダが見つかりません。', stores=[], products={})), encoding='utf-8')
            original_tk = tk.Tk
            roots, warned = [], []

            def wait(root, ms):
                passed = []
                root.after(ms, lambda: passed.append(True))
                while not passed:
                    root.update()
                    time.sleep(0.01)

            def make_root():
                root = original_tk()
                roots.append(root)
                root.geometry('920x620+-3000+0')
                def mainloop():
                    wait(root, 3300)   # 知らせは起動の3秒後から
                    frame = root.winfo_children()[0]
                    banner = next(w for w in frame.winfo_children() if isinstance(w, tk.Frame) and not isinstance(w, ttk.Frame)
                                  and any(isinstance(c, tk.Label) for c in w.winfo_children()))
                    text = next(c for c in banner.winfo_children() if isinstance(c, tk.Label)).cget('text')
                    self.assertTrue(banner.winfo_ismapped())
                    self.assertIn('見つからず', text)
                    self.assertIn('2026-11-03 06:39', text)
                    self.assertEqual(len(warned), 1, '知らせの窓は1回')
                    # 別のドライブ文字へ切り替えた知らせ（黄色）と「わかった」。
                    (data / 'backup-output-meruhen.json').unlink()
                    save_settings(data, sync_moved=dict(old='G:/x', new='E:/x', at='2026-11-03T07:00:00+09:00'))
                    wait(root, 800)
                    text = next(c for c in banner.winfo_children() if isinstance(c, tk.Label)).cget('text')
                    self.assertIn('E:/x', text)
                    button = next(c for c in banner.winfo_children() if isinstance(c, ttk.Button))
                    self.assertEqual(button.cget('text'), 'わかった')
                    button.invoke()
                    root.update()
                    self.assertFalse(banner.winfo_ismapped())
                    self.assertIsNone(load_settings(data).get('sync_moved'))
                    self.assertEqual(len(warned), 1)
                root.mainloop = mainloop
                return root

            try:
                with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), patch('daily_learning_runtime.run_due', return_value=(False, None)), \
                     patch.object(app.tk, 'Tk', make_root), patch.object(app, 'SYNC_BANNER_INTERVAL_MS', 500), \
                     patch.object(app.messagebox, 'showwarning', side_effect=lambda *a, **k: warned.append(a)):
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
                with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), patch('daily_learning_runtime.run_due', return_value=(False, None)), \
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
