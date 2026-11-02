"""新台の点数（2026-11-03 利用者「新台については比較せず出しても良いのでは？」→「同じ日の他の台と比べる」）。

画面に出す点数だけ、過去30日に記録の無い機種は同じ日の同じ機種のほかの台と比べる（v13）。翌日候補・固定済みの
検証に使う点数（same_day を渡さない）は v12 のまま。PC・Androidの一致は test_scoring_parity.py。"""
import tempfile
import unittest
from pathlib import Path

from core import NEW_MACHINE_SCORING_VERSION, VERSION, Store, new_machine_peers, score, scored_rows

STORE = 'nagamachiminami'


def row(rack, day, games, hits, machine='新台', **extra):
    return dict(store=STORE, kind_code=21, day=day, machine=machine, rack=rack, games=games,
                bb=hits, rb=0, max_hold=1000 + hits * 50, **extra)


class NewMachineScoringTests(unittest.TestCase):
    def test_first_day_racks_are_compared_with_each_other_on_screen_only(self):
        day = [row(1, '2026-11-02', 2100, 45), row(2, '2026-11-02', 3800, 30), row(3, '2026-11-02', 3900, 20),
               row(4, '2026-11-02', 4000, 25)]
        best, worst = day[0], day[2]
        before = score(best, day)
        self.assertEqual((before['hits'], before['max_hold']), (None, None), '今までどおり：当たり・持玉は中立で補う')
        self.assertEqual(before['version'], VERSION)
        shown = score(best, day, same_day=day)
        self.assertEqual(shown['version'], NEW_MACHINE_SCORING_VERSION)
        self.assertEqual(shown['reference_count'], 3, '自分以外の3台')
        self.assertGreater(shown['hits'], 30, '同じ日でいちばん当たりが軽い')
        self.assertLess(score(worst, day, same_day=day)['hits'], 30, 'いちばん重い台は中立より下')
        self.assertIn('新台（過去30日の記録なし）：同じ日の同じ機種3台と比べた点', shown['reasons'])
        self.assertTrue(shown['provisional'], '1日分なので暫定')

    def test_a_machine_with_history_is_not_new_even_without_comparable_racks(self):
        past = row(1, '2026-10-30', 600, 5)   # 回転数の幅（半分〜2倍）から外れる過去の記録
        today = [row(1, '2026-11-02', 5000, 40), row(2, '2026-11-02', 5200, 30)]
        self.assertEqual(new_machine_peers(today[0], [past, *today], today), [])
        self.assertIsNone(score(today[0], [past, *today], same_day=today)['hits'], 'v12のまま中立で補う')
        # 30日より前の記録は数えない（入れ替えで戻ってきた機種も新台）。回転数0の記録も数えない。
        old = row(1, '2026-09-20', 5000, 40)
        idle = row(1, '2026-11-01', 0, 0)
        self.assertEqual(len(new_machine_peers(today[0], [old, idle, *today], today)), 1)

    def test_scored_rows_uses_the_same_day_racks(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder) / 'database.sqlite3')
            try:
                db.save([row(1, '2026-11-02', 2100, 45), row(2, '2026-11-02', 3800, 30),
                         row(3, '2026-11-02', 3900, 20)])
                shown = {r['rack']: r['score'] for r in scored_rows(db, '2026-11-02', '新台', STORE)}
            finally:
                db.close()
        self.assertEqual(shown[1]['version'], NEW_MACHINE_SCORING_VERSION)
        self.assertGreater(shown[1]['total'], shown[3]['total'])


if __name__ == '__main__':
    unittest.main()
