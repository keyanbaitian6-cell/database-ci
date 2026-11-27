"""閲覧ページの答え合わせ用の「当時の翌日候補」（2026-11-04、core.saved_answer_candidates）。"""
import json
import tempfile
import unittest
from pathlib import Path

from core import VARIETY_GROUP_NAME, Store, export_viewer, saved_answer_candidates


def snapshot(store, day, machine, taken_at, racks):
    return dict(store=store, day=day, machine=machine, taken_at=taken_at, total=8, eligible=8,
                candidates=[dict(rack=rack, index=index, days=5) for rack, index in racks])


class SavedAnswerCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.db = Store(self.folder / 'database.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save([dict(store='nagamachiminami', kind_code=21, day='2026-11-03', machine='北斗',
                           rack=1, games=3000, bb=12, rb=6)])

    def add(self, *snapshots):
        self.db.add_candidate_snapshots(list(snapshots))

    def test_uses_the_latest_record_before_8am_of_the_next_day_per_machine(self):
        self.add(
            snapshot('nagamachiminami', '2026-11-03', '北斗', '2026-11-03T22:00:00+09:00', [(5, 61.0)]),
            snapshot('nagamachiminami', '2026-11-03', '北斗', '2026-11-04T07:30:00+09:00', [(7, 63.456)]),
            # 締切（11/4 8:00）より後の取り込み直し：使わない（後から分かったことを混ぜない）。
            snapshot('nagamachiminami', '2026-11-03', '北斗', '2026-11-04T08:00:01+09:00', [(9, 70.0)]),
            snapshot('nagamachiminami', '2026-11-03', VARIETY_GROUP_NAME, '2026-11-03T23:00:00+09:00', [(31, 55.0)]),
            snapshot('saiwaichou', '2026-11-03', '番長', '2026-11-04T07:59:59+09:00', [(12, 58.0)]),
            snapshot('saiwaichou', '2026-11-01', '番長', '2026-11-02T01:00:00+09:00', [(3, 52.0)]),
        )
        self.assertEqual(saved_answer_candidates(self.db, '2026-11-02'), {
            'nagamachiminami|2026-11-03': [[31, 55.0, 1], [7, 63.46, 0]],
            'saiwaichou|2026-11-03': [[12, 58.0, 0]],
        })

    def test_deduplicates_same_rack_across_snapshots_and_skips_hidden_machines(self):
        self.add(
            # 同じ台番号15が通常機種とバラエティの両方に出た場合は、時刻が新しい1件だけ残す。
            snapshot('nagamachiminami', '2026-11-03', '北斗', '2026-11-03T22:00:00+09:00', [(15, 60.0)]),
            snapshot('nagamachiminami', '2026-11-03', VARIETY_GROUP_NAME, '2026-11-04T06:00:00+09:00', [(15, 62.5)]),
            # 非表示機種（幸町の聖闘士星矢 海皇覚醒）は答え合わせ候補から除外する。
            snapshot('saiwaichou', '2026-11-03', '聖闘士星矢 海皇覚醒', '2026-11-04T05:00:00+09:00', [(1279, 66.0)]),
        )
        self.assertEqual(saved_answer_candidates(self.db, '2026-11-02'), {
            'nagamachiminami|2026-11-03': [[15, 62.5, 1]],
        })

    def test_the_viewer_file_carries_them_in_its_header(self):
        self.add(snapshot('nagamachiminami', '2026-11-02', '北斗', '2026-11-03T00:30:00+09:00', [(1, 60.0)]))
        export_viewer(self.db, self.folder / 'v.json')
        doc = json.loads((self.folder / 'v.json').read_text(encoding='utf-8'))
        self.assertEqual(doc['answer_candidates'], {'nagamachiminami|2026-11-02': [[1, 60.0, 0]]},
                         '閲覧の範囲の最初の日（11/3）の前の日の候補も載せる（11/3の答え合わせに使う）')

    def test_no_saved_candidates_leaves_the_header_as_before(self):
        export_viewer(self.db, self.folder / 'v.json')
        doc = json.loads((self.folder / 'v.json').read_text(encoding='utf-8'))
        self.assertNotIn('answer_candidates', doc)


if __name__ == '__main__':
    unittest.main()
