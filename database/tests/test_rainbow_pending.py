"""未取り込み中にWebで記録した印は、当日データを取り込んだ後にPCへ反映する。"""
import json
import tempfile
import unittest
from pathlib import Path
from core import Store, SHARED_RAINBOW_NAME, pull_shared_rainbow, export_backup, import_backup


class PendingRainbowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = Store(self.root / 'database.sqlite3')
        self.addCleanup(self.db.close)

    def test_pc_mark_is_saved_without_numbers_and_survives_import_and_recapture(self):
        db = self.db
        db.set_rainbow('saiwaichou', '2026-10-14', 1201, True,
                       at='2026-10-14T04:00:00Z', allow_missing=True)
        self.assertEqual(db.db.execute('SELECT COUNT(*) FROM days').fetchone()[0], 0)
        self.assertEqual(db.rainbow_racks('saiwaichou', '2026-10-14'), [1201])
        self.assertEqual(db.rainbow_counts('saiwaichou', '2026-10-01', '2026-10-14'), {1201: 1})
        self.assertEqual(db.last_rainbow_days('saiwaichou', '2026-10-15'), {1201: '2026-10-14'})
        reopened = Store(self.root / 'database.sqlite3')
        self.addCleanup(reopened.close)
        self.assertTrue(reopened.pending_rainbow_marks()[0]['on'])
        record = dict(store='saiwaichou', day='2026-10-14', machine='テスト機種', rack=1201,
                      kind_code=21, games=4000, bb=20, rb=10, max_hold=2000)
        db.save([record])
        self.assertEqual(db.pending_rainbow_marks(), [])
        self.assertEqual(db.rainbow_racks('saiwaichou', '2026-10-14'), [1201])
        db.save([{**record, 'games': 4500}])
        self.assertEqual(db.rainbow_racks('saiwaichou', '2026-10-14'), [1201])
        self.assertEqual(db.rainbow_counts('saiwaichou', '2026-10-01', '2026-10-14'), {1201: 1})

    def test_pc_pending_removal_and_portable_backup_keep_timestamp_precedence(self):
        db = self.db
        db.set_rainbow('saiwaichou', '2026-10-14', 1201, True,
                       at='2026-10-14T04:00:00Z', allow_missing=True)
        db.set_rainbow('saiwaichou', '2026-10-14', 1201, False,
                       at='2026-10-14T05:00:00Z', allow_missing=True)
        backup = self.root / 'pending.json'
        export_backup(db, backup, location='saiwaichou', day='2026-10-14')
        other = Store(self.root / 'restored.sqlite3')
        self.addCleanup(other.close)
        self.assertEqual(import_backup(other, backup)['rainbow_added'], 1)
        self.assertEqual(import_backup(other, backup)['rainbow_added'], 0)
        self.assertFalse(other.pending_rainbow_marks()[0]['on'])
        record = dict(store='saiwaichou', day='2026-10-14', machine='テスト機種', rack=1201,
                      kind_code=21, games=4000, bb=20, rb=10, max_hold=2000,
                      rainbow=True, rainbow_at='2026-10-14T04:30:00Z')
        other.save([record])
        self.assertEqual(other.rainbow_racks('saiwaichou', '2026-10-14'), [])
        # 別PCに既に数値があっても、後から復元した印を反映する。
        third = Store(self.root / 'existing.sqlite3')
        self.addCleanup(third.close)
        third.save([record])
        import_backup(third, backup)
        self.assertEqual(third.rainbow_racks('saiwaichou', '2026-10-14'), [])
        self.assertEqual(third.pending_rainbow_marks(), [])
        other.save([{**record, 'rainbow_at': '2026-10-14T06:00:00Z'}])
        self.assertEqual(other.rainbow_racks('saiwaichou', '2026-10-14'), [1201])

    def test_invalid_or_corrupt_pending_marks_never_replace_saved_state(self):
        db = self.db
        db.set_rainbow('saiwaichou', '2026-10-14', 1201, True, allow_missing=True)
        before = db.state('pending_rainbow_marks')
        backup = self.root / 'bad.json'
        backup.write_text(json.dumps(dict(format='database-backup', version=1, records=[],
                                         rainbow_marks=[{'store': 'bad'}])), encoding='utf-8')
        with self.assertRaises(ValueError):
            import_backup(db, backup)
        self.assertEqual(db.state('pending_rainbow_marks'), before)
        db.db.execute("UPDATE app_state SET value='{broken' WHERE state_key='pending_rainbow_marks'")
        db.db.commit()
        with self.assertRaises(ValueError):
            db.set_rainbow('saiwaichou', '2026-10-14', 1202, True, allow_missing=True)
        self.assertEqual(db.state('pending_rainbow_marks'), '{broken')

    def test_failed_numeric_import_rolls_back_and_keeps_pending_marks(self):
        db = self.db
        db.set_rainbow('saiwaichou', '2026-10-14', 1201, True, allow_missing=True)
        before = db.pending_rainbow_marks()
        record = dict(store='saiwaichou', day='2026-10-14', machine='テスト機種', rack=1201,
                      kind_code=21, games=4000, bb=20, rb=10, max_hold=2000)
        with self.assertRaises(ValueError):
            db.save([record, {**record, 'day': 'not-a-day'}])
        self.assertEqual(db.pending_rainbow_marks(), before)
        self.assertEqual(db.days_for('saiwaichou'), [])
        db.save([record, {**record, 'machine': '別の機種名'}])
        saved = db.rows('2026-10-14', store='saiwaichou')
        self.assertEqual(len(saved), 2)
        self.assertTrue(all(r.get('rainbow') for r in saved))
        self.assertEqual(db.pending_rainbow_marks(), [])

    def test_manual_removal_is_newer_even_if_the_pc_clock_moves_back(self):
        self.db.set_rainbow('saiwaichou', '2026-10-14', 1201, True,
                            at='2099-10-14T05:00:00+09:00', allow_missing=True)
        self.db.set_rainbow('saiwaichou', '2026-10-14', 1201, False, allow_missing=True)
        mark = self.db.pending_rainbow_marks()[0]
        self.assertFalse(mark['on'])
        self.assertGreater(mark['updated_at'], '2099-10-14T05:00:00+09:00')

    def test_pending_mark_survives_until_import_and_recapture(self):
        root = self.root
        db = self.db
        shared = root / SHARED_RAINBOW_NAME
        mark = dict(store='saiwaichou', day='2026-10-14', rack=1201,
                    on=True, updated_at='2026-10-14T04:00:00Z')
        shared.write_text(json.dumps({'format': 'database-rainbow', 'marks': [mark]}), encoding='utf-8')
        before = shared.read_bytes()
        self.assertEqual(pull_shared_rainbow(db, root), 0)
        self.assertEqual(shared.read_bytes(), before)
        self.assertEqual(db.db.execute('SELECT COUNT(*) FROM days').fetchone()[0], 0)
        row = dict(store='saiwaichou', day='2026-10-14', machine='テスト機種', rack=1201,
                   kind_code=21, games=4000, bb=20, rb=10, max_hold=2000)
        db.save([row])
        self.assertEqual(pull_shared_rainbow(db, root), 1)
        self.assertEqual(db.rainbow_racks('saiwaichou', '2026-10-14'), [1201])
        db.save([{**row, 'games': 5000}])
        self.assertEqual(db.rainbow_racks('saiwaichou', '2026-10-14'), [1201])
        mark.update(on=False, updated_at='2026-10-14T05:00:00Z')
        shared.write_text(json.dumps({'format': 'database-rainbow', 'marks': [mark]}), encoding='utf-8')
        self.assertEqual(pull_shared_rainbow(db, root), 1)
        self.assertEqual(db.rainbow_racks('saiwaichou', '2026-10-14'), [])
