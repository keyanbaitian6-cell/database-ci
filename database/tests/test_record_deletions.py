import json
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from core import Store, export_backup, export_viewer, import_backup, restore_backup

ROW = dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine='試験', rack=537,
           games=3000, bb=10, rb=5, captured_at='2026-10-14T23:00:00+09:00')


class RecordDeletionTests(unittest.TestCase):
    def test_naive_source_timestamps_are_japan_time_and_broken_payload_can_be_deleted(self):
        from core import _record_after_deletion
        mark = dict(ROW, deleted_at='2026-10-15T03:00:00Z')
        self.assertTrue(_record_after_deletion(dict(ROW, captured_at='2026-10-15T12:01:00'), mark))
        self.assertFalse(_record_after_deletion(dict(ROW, captured_at='2026-10-15T11:59:00'), mark))
        for grouped in (False, True):
            with self.subTest(grouped=grouped), tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / 'db.sqlite3')
                try:
                    store.save([ROW])
                    with store.db: store.db.execute("UPDATE days SET payload='broken JSON'")
                    if grouped:
                        self.assertEqual(store.delete_group(ROW['day']), 1)
                    else:
                        self.assertTrue(store.delete(ROW['store'], ROW['day'], ROW['machine'], 537))
                    self.assertEqual(store.record_deletions()[0]['rack'], 537)
                finally: store.close()

    def test_last_row_deletion_is_exported_and_old_backup_cannot_resurrect_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(Store(root / 'db.sqlite3')) as store:
                store.save([ROW]); old = root / 'old.json'; export_backup(store, old)
                store.delete_group(ROW['day'])
                light = root / 'viewer.json'; export_viewer(store, light)
                payload = json.loads(light.read_text()); self.assertEqual(payload['records'], [])
                self.assertEqual(payload['record_deletions'][0]['rack'], 537)
                import_backup(store, old); self.assertEqual(store.rows(), [])
                restore_backup(store, old)
                self.assertEqual(len(store.rows()), 1)
                self.assertTrue(store.rows()[0]['record_updated_at'])

    def test_deletion_roundtrip_preserves_unrelated_rows_and_explicit_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(Store(root / 'a.db')) as a, closing(Store(root / 'b.db')) as b:
                a.save([ROW]); b.save([ROW, dict(ROW, rack=538)])
                a.delete(ROW['store'], ROW['day'], ROW['machine'], 537)
                path = root / 'deleted.json'; export_backup(a, path); import_backup(b, path)
                self.assertEqual([r['rack'] for r in b.rows()], [538])
                b.save([ROW]); export_backup(b, path); import_backup(a, path)
                self.assertEqual(sorted(r['rack'] for r in a.rows()), [537, 538])

    def test_invalid_deletion_rejects_whole_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(Store(root / 'db.sqlite3')) as store:
                path = root / 'invalid.json'
                path.write_text(json.dumps(dict(format='database-backup', version=1, records=[ROW], record_deletions=[dict(ROW, deleted_at='bad')])))
                with self.assertRaises(ValueError): import_backup(store, path)
                self.assertEqual(store.rows(), [])
