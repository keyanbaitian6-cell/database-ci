"""未取り込み中にWebで記録した印は、当日データを取り込んだ後にPCへ反映する。"""
import json
import tempfile
import unittest
from pathlib import Path
from core import Store, SHARED_RAINBOW_NAME, pull_shared_rainbow


class PendingRainbowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = Store(self.root / 'database.sqlite3')
        self.addCleanup(self.db.close)

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
