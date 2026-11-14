"""未取り込み🌈・起動時の自動取り込みの再発防止（2026-10-14 独立レビュー）。

* PC本体と取り込みブラウザは別プロセスで同じDBへ書く。印の控え（app_state の一覧全体）を
  ロックの外で読んでから書き戻すと、その間に別の接続が足した印を消していた。
* 閲覧用ファイル（Webの入力）に未取り込みの印を入れない。Webへは数値の取り込み後（RAINBOW.md）。
* 表示しない機種だけの行がある台の印を、行も控えも無いまま捨てない。
* 自動取り込みは、成功したバックアップだけを「取り込み済み」として覚える。
"""
import json
import os
import sqlite3
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from core import Store, export_backup, export_viewer, latest_backup_file, load_settings, save_settings

DAY = '2026-10-14'
RECORD = dict(store='saiwaichou', day=DAY, machine='テスト機種', rack=1201,
              kind_code=21, games=4000, bb=20, rb=10, max_hold=2000)


class ConcurrentPendingMarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'database.sqlite3'
        first = Store(self.path)
        first.close()

    def interleave(self, writer, other_action):
        """[writer] が印の控えを読んだ直後に、別の接続で [other_action] を走らせる。

        正しい実装では writer が書き込みロックを持っているので、other は writer の確定を待ち、
        確定後の控えに足す。待つ間 writer は続けられるよう、別スレッドで動かして最大1秒だけ待つ。"""
        errors = []

        def run_other():
            other = Store(self.path)
            try:
                other_action(other)
            except Exception as error:   # 試験で原因を見えるようにする
                errors.append(error)
            finally:
                other.close()

        original = Store.pending_rainbow_marks
        started = []

        def hooked(store, *args, **kwargs):
            result = original(store, *args, **kwargs)
            if store is writer and not started:
                thread = threading.Thread(target=run_other)
                started.append(thread)
                thread.start()
                thread.join(1.0)
            return result
        return hooked, started, errors

    def finish(self, started, errors):
        for thread in started:
            thread.join(10)
        self.assertEqual(errors, [])

    def test_capture_save_does_not_drop_a_mark_added_meanwhile_by_another_process(self):
        main = Store(self.path)
        self.addCleanup(main.close)
        main.set_rainbow('saiwaichou', DAY, 1201, True, at='2026-10-14T04:00:00Z', allow_missing=True)
        capture = Store(self.path)
        self.addCleanup(capture.close)
        hooked, started, errors = self.interleave(
            capture, lambda other: other.set_rainbow('saiwaichou', DAY, 1202, True,
                                                     at='2026-10-14T04:05:00Z', allow_missing=True))
        with patch.object(Store, 'pending_rainbow_marks', hooked):
            capture.save([RECORD])
        self.finish(started, errors)
        check = Store(self.path)
        self.addCleanup(check.close)
        self.assertEqual([m['rack'] for m in check.pending_rainbow_marks()], [1202])
        self.assertEqual(check.rainbow_racks('saiwaichou', DAY), [1201, 1202])

    def test_two_processes_marking_different_racks_keep_both_marks(self):
        first = Store(self.path)
        self.addCleanup(first.close)
        hooked, started, errors = self.interleave(
            first, lambda other: other.set_rainbow('saiwaichou', DAY, 1202, True,
                                                   at='2026-10-14T04:05:00Z', allow_missing=True))
        with patch.object(Store, 'pending_rainbow_marks', hooked):
            first.set_rainbow('saiwaichou', DAY, 1201, True, at='2026-10-14T04:00:00Z', allow_missing=True)
        self.finish(started, errors)
        check = Store(self.path)
        self.addCleanup(check.close)
        self.assertEqual(sorted(m['rack'] for m in check.pending_rainbow_marks()), [1201, 1202])

    def test_failed_save_still_rolls_back_rows_and_marks_together(self):
        db = Store(self.path)
        self.addCleanup(db.close)
        db.set_rainbow('saiwaichou', DAY, 1201, True, at='2026-10-14T04:00:00Z', allow_missing=True)
        with self.assertRaises(ValueError):
            db.save([RECORD, {**RECORD, 'rack': 1202, 'day': 'bad'}])
        self.assertFalse(db.db.in_transaction)
        self.assertEqual([m['rack'] for m in db.pending_rainbow_marks()], [1201])
        self.assertEqual(db.days_for('saiwaichou'), [])
        # 同じ接続で続けて書ける（ロックを持ち続けない）。
        other = Store(self.path)
        self.addCleanup(other.close)
        other.set_rainbow('saiwaichou', DAY, 1203, True, at='2026-10-14T04:10:00Z', allow_missing=True)


class PendingMarkScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = Store(self.root / 'database.sqlite3')
        self.addCleanup(self.db.close)

    def test_viewer_file_for_the_web_has_no_unimported_marks_but_the_backup_has(self):
        self.db.save([dict(RECORD, day='2026-10-13')])
        self.db.set_rainbow('saiwaichou', DAY, 1201, True, at='2026-10-14T04:00:00Z', allow_missing=True)
        viewer = self.root / 'viewer.json'
        export_viewer(self.db, viewer)
        self.assertNotIn('rainbow_marks', json.loads(viewer.read_text(encoding='utf-8')))
        backup = self.root / 'backup.json'
        export_backup(self.db, backup)
        self.assertEqual([m['rack'] for m in json.loads(backup.read_text(encoding='utf-8'))['rainbow_marks']], [1201])

    def test_mark_on_a_rack_with_only_a_hidden_machine_is_kept_pending(self):
        hidden = dict(RECORD, machine='聖闘士星矢海皇覚醒')
        self.db.save([hidden])   # 表示しない機種は保存しない
        self.db.db.execute('INSERT INTO days VALUES(?,?,?,?,?)',
                           ('saiwaichou', DAY, hidden['machine'], 1201, json.dumps(hidden, ensure_ascii=False)))
        self.db.db.commit()
        self.db.set_rainbow('saiwaichou', DAY, 1201, True, at='2026-10-14T04:00:00Z', allow_missing=True)
        self.assertEqual([m['rack'] for m in self.db.pending_rainbow_marks()], [1201])
        self.assertEqual(self.db.rainbow_racks('saiwaichou', DAY), [1201])
        self.db.save([RECORD])
        self.assertEqual(self.db.pending_rainbow_marks(), [])
        self.assertEqual(self.db.rainbow_racks('saiwaichou', DAY), [1201])


class ObservationPruneTests(unittest.TestCase):
    def test_old_observation_cleanup_uses_an_index_instead_of_reading_every_line(self):
        # 1行ごとの古い行の削除が全件を読み、新しいバックアップ551行の取り込みで約21秒止まっていた。
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder) / 'database.sqlite3')
            try:
                plan = ' '.join(str(row) for row in db.db.execute(
                    'EXPLAIN QUERY PLAN DELETE FROM observations WHERE captured_at < ?', ('2026-09-14',)))
                self.assertIn('observations_captured_at', plan)
                db.db.execute("INSERT INTO observations(captured_at,payload) VALUES('2000-01-01T00:00:00+09:00','{}')")
                db.db.commit()
                db.save([RECORD])
                kept = [r[0] for r in db.db.execute('SELECT captured_at FROM observations')]
                self.assertEqual(len(kept), 1)
                self.assertFalse(kept[0].startswith('2000-'))
            finally:
                db.close()


class BackupSearchTests(unittest.TestCase):
    def test_older_backups_are_not_auto_picked_when_the_imported_one_is_gone(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            older = folder / 'older.json'
            older.write_text('{"format":"database-backup","records":[]}', encoding='utf-8')
            os.utime(older, (1_000_000, 1_000_000))
            seen = dict(name='deleted-newest.json', mtime=2_000_000.0)
            self.assertIsNone(latest_backup_file(folder, seen=seen))
            # 手動の「最新を読み込む」（seen なし）は今までどおり見つける。
            self.assertEqual(latest_backup_file(folder), older)

    def test_a_file_removed_during_the_search_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            keep = folder / 'keep.json'
            keep.write_text('{"format":"database-backup","records":[]}', encoding='utf-8')
            gone = folder / 'gone.json'
            gone.write_text('{"format":"database-backup","records":[]}', encoding='utf-8')
            original = Path.stat

            def flaky(path, *args, **kwargs):
                if path.name == 'gone.json':
                    raise FileNotFoundError(path)
                return original(path, *args, **kwargs)
            with patch.object(Path, 'stat', flaky):
                self.assertEqual(latest_backup_file(folder), keep)


class AutoSyncTests(unittest.TestCase):
    def run_app(self, root_path, data):
        original_tk = tk.Tk
        roots = []

        def make_root():
            root = original_tk()
            roots.append(root)
            root.withdraw()

            def mainloop():
                end = time.monotonic() + 1.5
                while time.monotonic() < end:
                    root.update()
                    time.sleep(0.02)
            root.mainloop = mainloop
            return root
        errors, infos = [], []
        try:
            with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), patch('daily_learning_runtime.run_due', return_value=(False, None)), \
                 patch.object(app.tk, 'Tk', make_root), \
                 patch.object(app.messagebox, 'showerror', lambda *a, **k: errors.append(a)), \
                 patch.object(app.messagebox, 'showinfo', lambda *a, **k: infos.append(a)):
                app.main()
        finally:
            for root in roots:
                root.destroy()
        return errors

    def test_failed_import_is_not_remembered_and_a_good_one_is(self):
        with tempfile.TemporaryDirectory() as folder:
            root_path = Path(folder)
            data = root_path / 'data'
            sync = root_path / 'sync'
            sync.mkdir()
            Store(data / 'database.sqlite3').close()
            backup = sync / 'database-backup-android-20261014-120000.json'
            # 形式名は合っているが中身が不正（自動検索は通り、取り込みで失敗する）。
            backup.write_text(json.dumps(dict(format='database-backup', version=1, records=[],
                                              rainbow_marks=[{'store': 'bad'}])), encoding='utf-8')
            save_settings(data, auto_sync_on_start=True, sync_dir=str(sync))
            errors = self.run_app(root_path, data)
            self.assertEqual(len(errors), 1)
            self.assertNotIn('last_synced', load_settings(data))
            backup.write_text(json.dumps(dict(format='database-backup', version=1, records=[RECORD])),
                              encoding='utf-8')
            mtime = backup.stat().st_mtime
            self.assertEqual(self.run_app(root_path, data), [])
            self.assertEqual(load_settings(data).get('last_synced'), dict(name=backup.name, mtime=mtime))
            check = Store(data / 'database.sqlite3')
            try:
                self.assertEqual(check.days_for('saiwaichou'), [DAY])
            finally:
                check.close()


if __name__ == '__main__':
    unittest.main()
