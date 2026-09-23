import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Store, plan_backup_import, delete_records, undo_last_save


def sample(**updates):
    return dict(dict(store='saiwaichou', kind_code=21, day='2026-09-22',
                     machine='テスト', rack=703, games=3000, bb=20, rb=5), **updates)


class BackupDuplicateTests(unittest.TestCase):
    def test_failed_deletion_preserves_previous_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder) / 'test.sqlite3')
            try:
                first, second = sample(), sample(day='2026-09-21')
                db.save([first, second])
                delete_records(db, folder, first['day'], first['store'])
                with patch.object(db, 'delete_group', side_effect=OSError('disk failure')):
                    with self.assertRaises(OSError):
                        delete_records(db, folder, second['day'], second['store'])
                undo_last_save(db, folder)
                self.assertEqual({r['day'] for r in db.rows()}, {first['day'], second['day']})
            finally:
                db.close()

    def test_conflicting_duplicate_inside_backup_is_not_silently_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder) / 'test.sqlite3')
            try:
                with self.assertRaisesRegex(ValueError, '重複'):
                    plan_backup_import(db, [sample(), sample(games=4000)])
                self.assertEqual(db.rows(), [])
            finally:
                db.close()

    def test_identical_duplicate_is_only_added_once(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder) / 'test.sqlite3')
            try:
                plan = plan_backup_import(db, [sample(), sample()])
                self.assertEqual(len(plan['new']), 1)
            finally:
                db.close()
