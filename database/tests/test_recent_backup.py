"""Androidがふだん読み込む「直近7日分」のバックアップ（2026-10-18 利用者「アプリ版も差分処理っていけないのだろうか」
「案１で細かく読み込んでいけば問題なさそうだね」）。全期間のバックアップと同じ形で、直近の記録だけ。"""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from core import (AUTO_BACKUP_NAME, RECENT_BACKUP_DAYS, RECENT_BACKUP_NAME, Store, auto_backup,
                  import_backup, latest_backup_file, save_settings)


def row(day, rack):
    return dict(store='saiwaichou', kind_code=21, day=day, machine='SマイジャグラーVKD', rack=rack,
                games=4000, bb=15, rb=12)


class RecentBackupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / 'data'
        self.sync = self.root / 'sync'
        self.sync.mkdir()
        save_settings(self.data, sync_dir=str(self.sync))
        self.db = Store(self.data / 'database.sqlite3')
        self.addCleanup(self.db.close)
        self.days = [(date(2026, 10, 1) + timedelta(days=i)).isoformat() for i in range(20)]
        self.db.save([row(d, r) for d in self.days for r in (700, 701)])
        self.db.set_date_events([dict(store='saiwaichou', day=self.days[2], name='古いイベント'),
                                 dict(store='saiwaichou', day=self.days[-1], name='新しいイベント')])
        self.db.delete('saiwaichou', self.days[0], 'SマイジャグラーVKD', 701)   # 古い日の削除

    def test_written_next_to_the_full_backup_with_only_recent_days(self):
        auto_backup(self.db, self.data, strict=True)
        full = json.loads((self.sync / AUTO_BACKUP_NAME).read_text(encoding='utf-8'))
        recent = json.loads((self.sync / RECENT_BACKUP_NAME).read_text(encoding='utf-8'))
        since = self.days[-RECENT_BACKUP_DAYS]
        self.assertEqual(recent['since'], since)
        self.assertEqual(sorted({r['day'] for r in recent['records']}), self.days[-RECENT_BACKUP_DAYS:])
        self.assertEqual(len(recent['records']), 2 * RECENT_BACKUP_DAYS)
        self.assertEqual(len(full['records']), 2 * len(self.days) - 1)
        self.assertEqual([e['name'] for e in recent['date_events'] if e.get('name')], ['新しいイベント'])
        # 古い日の削除の印は、直近のファイルにも入る（Androidでも消えるように）。
        self.assertEqual([(m['day'], m['rack']) for m in recent['record_deletions']], [(self.days[0], 701)])

    def test_pc_does_not_read_its_own_recent_file_back(self):
        auto_backup(self.db, self.data, strict=True)
        self.assertIsNone(latest_backup_file(self.sync))

    def test_importing_the_recent_file_adds_and_never_removes(self):
        auto_backup(self.db, self.data, strict=True)
        other = Store(self.root / 'android.sqlite3')
        self.addCleanup(other.close)
        other.save([row(self.days[3], 700), row(self.days[0], 701)])
        plan = import_backup(other, self.sync / RECENT_BACKUP_NAME)
        self.assertEqual(len(plan['new']), 2 * RECENT_BACKUP_DAYS)
        days = sorted({r['day'] for r in other.rows()})
        self.assertIn(self.days[3], days)                       # 直近より前の記録は残る
        self.assertNotIn((self.days[0], 701), {(r['day'], int(r['rack'])) for r in other.rows()})  # 削除は伝わる


if __name__ == '__main__':
    unittest.main()
