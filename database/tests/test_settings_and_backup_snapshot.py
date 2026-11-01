"""2026-11-01 Codexの洗い出し3・4の再発防止。

3. 読めない settings.json を空として扱い、次の選択保存で原文（同期先など）を上書きしていた。
4. 手動バックアップ・取り込み窓を閉じたときのバックアップが本体DBを直接読み、書き出しの途中で
   別の接続が台を消すと、台も削除印も入っていないバックアップになった。
"""
import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import error_log  # noqa: E402
from core import (SETTINGS_NAME, Store, backup_from_snapshot, export_backup, import_backup,  # noqa: E402
                  load_settings, save_settings, snapshot_dir, snapshot_store)

ROW = dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine='合成試験', rack=537, games=3000, bb=10, rb=5)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        error_log.forget()
        self.addCleanup(error_log.forget)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.path = self.folder / SETTINGS_NAME

    def log(self):
        log = self.folder / 'errors.log'
        return [line.split('\t')[1] for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []

    def test_broken_settings_are_kept_before_saving_again(self):
        broken = '{"sync_dir": "合成の同期先",'
        self.path.write_text(broken, encoding='utf-8')
        self.assertEqual(load_settings(self.folder), {})
        save_settings(self.folder, last_day='2026-10-14')
        self.assertEqual(load_settings(self.folder), {'last_day': '2026-10-14'})
        [kept] = self.folder.glob(SETTINGS_NAME + '.broken-*')
        self.assertEqual(kept.read_text(encoding='utf-8'), broken, '原文をそのまま残す')
        self.assertEqual(self.log(), ['settings.broken'])
        save_settings(self.folder, last_store='saiwaichou')  # 直った後は普段どおり
        self.assertEqual(len(list(self.folder.glob(SETTINGS_NAME + '.broken-*'))), 1)
        self.assertEqual(load_settings(self.folder), {'last_day': '2026-10-14', 'last_store': 'saiwaichou'})

    def test_non_utf8_and_non_object_settings_count_as_broken(self):
        for raw in (b'\xff\xfe{"a": 1}', '["sync_dir"]'.encode('utf-8')):
            with self.subTest(raw=raw):
                for old in self.folder.glob(SETTINGS_NAME + '.broken-*'):
                    old.unlink()
                self.path.write_bytes(raw)
                save_settings(self.folder, last_day='2026-10-14')
                [kept] = self.folder.glob(SETTINGS_NAME + '.broken-*')
                self.assertEqual(kept.read_bytes(), raw)

    def test_settings_that_cannot_be_opened_are_not_overwritten(self):
        good = json.dumps({'sync_dir': '合成の同期先'}, ensure_ascii=False)
        self.path.write_text(good, encoding='utf-8')
        real = Path.read_text

        def locked(path, *args, **kwargs):
            if path.name == SETTINGS_NAME:
                raise PermissionError('同期ソフトが使用中（模擬）')
            return real(path, *args, **kwargs)

        with mock.patch.object(Path, 'read_text', locked):
            self.assertEqual(save_settings(self.folder, last_day='2026-10-14'), {'last_day': '2026-10-14'})
        self.assertEqual(self.path.read_text(encoding='utf-8'), good, '開けないだけの正しい原文を消さない')
        self.assertEqual(list(self.folder.glob(SETTINGS_NAME + '.broken-*')), [])
        self.assertEqual(self.log(), ['settings.locked'])

    def test_first_save_and_normal_merge_write_nothing_else(self):
        save_settings(self.folder, sync_dir='合成の同期先')
        save_settings(self.folder, last_day='2026-10-14')
        self.assertEqual(load_settings(self.folder), {'sync_dir': '合成の同期先', 'last_day': '2026-10-14'})
        self.assertEqual(list(self.folder.glob(SETTINGS_NAME + '.broken-*')), [])
        self.assertEqual(self.log(), [])


class SnapshotBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.db_path = self.folder / 'database.sqlite3'
        with closing(Store(self.db_path, recording=False)) as db:
            db.save([ROW], log_candidates=False)

    def export_while_another_connection_deletes(self, target):
        """削除印を読んだ後・台を読む前に、別の接続が537番を消す（Codexの再現と同じ順番）。"""
        with closing(Store(self.db_path, recording=False)) as writer, snapshot_store(self.db_path) as reader:
            original = reader.history_edits_raw

            def concurrent_delete():
                writer.delete(ROW['store'], ROW['day'], ROW['machine'], ROW['rack'])
                return original()

            with mock.patch.object(reader, 'history_edits_raw', side_effect=concurrent_delete):
                export_backup(reader, target)
            self.assertEqual(len(writer.record_deletions()), 1, '削除そのものは本体に入っている')

    def test_backup_is_the_state_before_the_concurrent_delete(self):
        target = self.folder / 'manual.json'
        self.export_while_another_connection_deletes(target)
        doc = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual([r['rack'] for r in doc['records']], [537], '写した時点（削除前）の完全な組')
        self.assertEqual(doc['record_deletions'], [])
        # 次の書き出しは削除後の完全な組（台なし・削除印あり）になる。
        later = self.folder / 'later.json'
        with snapshot_store(self.db_path) as db:
            export_backup(db, later)
        doc = json.loads(later.read_text(encoding='utf-8'))
        self.assertEqual(doc['records'], [])
        self.assertEqual(len(doc['record_deletions']), 1)
        with closing(Store(self.folder / 'peer.sqlite3', recording=False)) as peer:
            peer.save([ROW], log_candidates=False)
            import_backup(peer, later)
            self.assertEqual(peer.rows(), [], '削除印で取り込み先からも消える')

    def test_snapshot_does_not_change_the_main_database(self):
        before = self.db_path.read_bytes()
        with snapshot_store(self.db_path) as db:
            self.assertNotEqual(Path(db.path).resolve(), self.db_path.resolve())
            db.delete(ROW['store'], ROW['day'], ROW['machine'], ROW['rack'])
        self.assertEqual(self.db_path.read_bytes(), before)
        with closing(Store(self.db_path, recording=False)) as db:
            self.assertEqual(len(db.rows()), 1)

    def test_backup_after_the_window_closes_uses_the_snapshot(self):
        with mock.patch('core.auto_backup', wraps=__import__('core').auto_backup) as auto:
            backup_from_snapshot(self.db_path, self.folder)
        store = auto.call_args.args[0]
        self.assertNotEqual(Path(store.path).resolve(), self.db_path.resolve(), '写しから書く')
        self.assertIs(auto.call_args.kwargs['import_shared'], False, '共有編集は本体へ先に取り込む')
        [snapshot] = snapshot_dir(self.folder).glob('database-backup-*.json')
        self.assertEqual(len(json.loads(snapshot.read_text(encoding='utf-8'))['records']), 1)


if __name__ == '__main__':
    unittest.main()
