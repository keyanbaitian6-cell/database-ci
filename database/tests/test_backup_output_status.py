"""共有への再出力、ドライブ復旧、完了前の成功表示を防ぐための確認。"""
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backup_status import BackupStatus, read_status, status_text
from core import Store, auto_backup, save_settings, VIEWER_FILE_NAME


class BackupOutputStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data, self.shared = self.root / 'data', self.root / 'drive'
        self.shared.mkdir()
        save_settings(self.data, sync_dir=str(self.shared))

    def store(self):
        store = Store(self.data / 'database.sqlite3')
        store.save([dict(store=place, kind_code=21, day='2026-10-22', machine='試験',
                         rack=rack, games=3000, bb=10, rb=5)
                    for place, rack in [('saiwaichou', 537), ('nagamachiminami', 101)]])
        return closing(store)

    def test_success_is_recorded_only_after_copy_and_includes_both_stores(self):
        import core
        real_copy, during = core.atomic_copy, []
        def copy(source, target):
            during.append(read_status(self.data, 'meruhen').get('state'))
            return real_copy(source, target)
        with self.store() as store, patch('core.atomic_copy', side_effect=copy):
            auto_backup(store, self.data, strict=True)
        self.assertTrue(during)
        self.assertNotIn('success', during)
        status = read_status(self.data, 'meruhen')
        self.assertEqual(status['state'], 'success')
        self.assertEqual({item['name'] for item in status['stores']}, {'長町南', '幸町'})
        self.assertIn('viewer', status['completed'])
        self.assertNotIn('アップロード完了', status_text(self.data, 'meruhen', self.shared))

    def test_failed_viewer_copy_preserves_previous_success_and_completed_file(self):
        import core
        with self.store() as store:
            auto_backup(store, self.data, strict=True)
            old = read_status(self.data, 'meruhen')
            before = (self.shared / VIEWER_FILE_NAME).read_bytes()
            real_copy = core.atomic_copy
            def copy(source, target):
                if Path(target) == self.shared / VIEWER_FILE_NAME:
                    raise OSError('ドライブに書き込めません')
                return real_copy(source, target)
            with patch('core.atomic_copy', side_effect=copy):
                with self.assertRaises(OSError):
                    auto_backup(store, self.data, strict=True)
            current = read_status(self.data, 'meruhen')
            self.assertEqual(current['state'], 'failed')
            self.assertEqual(current['last_success_at'], old['last_success_at'])
            self.assertIn('ドライブに書き込めません', current['message'])
            self.assertEqual((self.shared / VIEWER_FILE_NAME).read_bytes(), before)

    def test_missing_drive_then_reexport_uses_saved_rows_without_recapture(self):
        missing = self.root / 'temporarily-offline'
        save_settings(self.data, sync_dir=str(missing))
        with self.store() as store:
            self.assertIsNone(auto_backup(store, self.data, strict=True))
            self.assertEqual(read_status(self.data, 'meruhen')['state'], 'unavailable')
            self.assertFalse(missing.exists(), '未接続の同期先を勝手に作らない')
            missing.mkdir()
            auto_backup(store, self.data, strict=True)
            records = json.loads((missing / VIEWER_FILE_NAME).read_text(encoding='utf-8'))['records']
            self.assertEqual({r['store'] for r in records}, {'saiwaichou', 'nagamachiminami'})
            self.assertEqual(read_status(self.data, 'meruhen')['state'], 'success')

    def test_non_strict_auto_capture_records_failure_instead_of_old_success(self):
        with self.store() as store:
            auto_backup(store, self.data)
            with patch('core.atomic_copy', side_effect=OSError('接続切断')):
                self.assertIsNone(auto_backup(store, self.data))
            status = read_status(self.data, 'meruhen')
            self.assertEqual(status['state'], 'failed')
            self.assertIn('接続切断', status['message'])

    def test_optional_export_error_is_partial_and_keeps_the_viewer_success(self):
        with self.store() as store, patch('core.export_recent_backup', side_effect=OSError('使用中')):
            auto_backup(store, self.data, strict=True)
        status = read_status(self.data, 'meruhen')
        self.assertEqual(status['state'], 'partial')
        self.assertIn('viewer', status['completed'])
        self.assertNotIn('recent', status['completed'])
        self.assertIn('使用中', status['message'])

    def test_new_folder_does_not_inherit_another_folders_success(self):
        status = BackupStatus(self.data, 'pscube', self.shared)
        status.done('viewer'); status.finish('success')
        another = self.root / 'other'; another.mkdir()
        self.assertIn('未確認', status_text(self.data, 'pscube', another))
        BackupStatus(self.data, 'pscube', another).finish('failed', '使用中')
        self.assertIsNone(read_status(self.data, 'pscube')['last_success_at'])

    def test_empty_database_writes_an_empty_recent_backup(self):
        # 2026-11-08 から、記録が無くても空の直近版を書く（全件削除がAndroidへ届くように。レビュー4）。
        # 書いたときだけ「書いた」と記録する点は変わらない。
        from core import RECENT_BACKUP_NAME
        with closing(Store(self.data / 'database.sqlite3')) as store:
            auto_backup(store, self.data, strict=True)
        self.assertEqual(read_status(self.data, 'meruhen')['state'], 'success')
        self.assertIn('recent', read_status(self.data, 'meruhen')['completed'])
        recent = json.loads((self.shared / RECENT_BACKUP_NAME).read_text(encoding='utf-8'))
        self.assertEqual(recent['records'], [])

    def test_pscube_auto_capture_reports_the_actual_copy_failure(self):
        import pscube_import
        with closing(pscube_import.PscubeStore(self.data / 'pscube.sqlite3')) as store:
            pscube_import.auto_backup(store, self.data / 'pscube-viewer.json')
            previous = read_status(self.data, 'pscube')
            self.assertEqual(previous['state'], 'success')
            with patch('pscube_import.atomic_copy', side_effect=OSError('接続が切れました')):
                self.assertIn('失敗', pscube_import.auto_backup(store, self.data / 'pscube-viewer.json'))
            failed = read_status(self.data, 'pscube')
            self.assertEqual(failed['state'], 'failed')
            self.assertEqual(failed['last_success_at'], previous['last_success_at'])
            self.assertIn('接続が切れました', failed['message'])

    def test_combined_reexport_still_updates_meruhen_when_pscube_source_is_broken(self):
        from output_worker import refresh_outputs
        with self.store():
            pass
        (self.data / 'pscube.sqlite3').write_bytes(b'not a database')
        with self.assertRaises(OSError):
            refresh_outputs(self.data / 'database.sqlite3', self.data, self.root / 'reports',
                            backup=True, pscube=True)
        self.assertEqual(read_status(self.data, 'meruhen')['state'], 'success')
        self.assertEqual(read_status(self.data, 'pscube')['state'], 'failed')
        self.assertTrue((self.shared / VIEWER_FILE_NAME).exists())

    def test_combined_reexport_still_updates_pscube_when_meruhen_source_is_broken(self):
        from output_worker import refresh_outputs
        from pscube_import import PscubeStore, VIEWER_DRIVE_NAME
        with closing(PscubeStore(self.data / 'pscube.sqlite3')):
            pass
        (self.data / 'database.sqlite3').write_bytes(b'not a database')
        with self.assertRaises(OSError):
            refresh_outputs(self.data / 'database.sqlite3', self.data, self.root / 'reports',
                            backup=True, pscube=True)
        self.assertEqual(read_status(self.data, 'meruhen')['state'], 'failed')
        self.assertEqual(read_status(self.data, 'pscube')['state'], 'success')
        self.assertTrue((self.shared / VIEWER_DRIVE_NAME).exists())
