import unittest
from core import next_day_evidence, next_day_focus, next_day_sort_key, provisional_next_day_candidates, next_day_reason
from backtest_candidates import Rows


def rows():
    return [dict(store='nagamachiminami', day=f'2026-09-{d:02}', machine='通常機種', rack=r,
                 games=6000, bb=80 if r == 1 else 10+r, rb=0, max_hold=19000 if r == 1 else 1000,
                 graph_measurement=dict(baseline_y=200, peak_y=100, trough_y=200, end_y=100))
            for d in range(1, 11) for r in range(1, 9)]


class FocusTest(unittest.TestCase):
    def test_inclusive_cutoff_and_missing_score(self):
        data = Rows(rows())
        e = next_day_evidence(data, data.rows('2026-09-10', '通常機種', 'nagamachiminami')[0])
        self.assertTrue(e['today_used'])
        self.assertGreaterEqual(e['stability_z'], 1.96)
        self.assertTrue(next_day_focus(e, 87.9))
        self.assertTrue(next_day_focus(e, None))
        self.assertFalse(next_day_focus(e, 88))
        self.assertFalse(next_day_focus(e, 100))

    def test_strong_rack_stays_as_long_trend(self):
        picks = provisional_next_day_candidates(Rows(rows()), '2026-09-10', '通常機種')['candidates']
        first = next(c for c in picks if c['row']['rack'] == 1)
        self.assertGreaterEqual(first['today_score'], 88)
        self.assertFalse(first['focus'])
        self.assertIn('88点以上', next_day_reason(first))

    def test_ties_prefer_evidence_days_then_recency(self):
        def item(rack, n, last, raw=55):
            return dict(row=dict(rack=rack), days=n, latest_used=last, raw_index=raw)
        self.assertLess(next_day_sort_key(item(8, 4, '2026-09-09')), next_day_sort_key(item(1, 3, '2026-09-10')))
        self.assertLess(next_day_sort_key(item(8, 4, '2026-09-10')), next_day_sort_key(item(1, 4, '2026-09-09')))
        self.assertLess(next_day_sort_key(item(8, 4, '2026-09-10', 55.002)), next_day_sort_key(item(1, 4, '2026-09-10', 55.001)))

    def test_ties_prefer_more_games_on_the_day_first(self):
        def item(rack, games, n=4, last='2026-09-10'):
            return dict(row=dict(rack=rack, games=games), days=n, latest_used=last, raw_index=55)
        # 回転数が多い台は、使った日数・最新の使用日・台番号より先に上へ。
        self.assertLess(next_day_sort_key(item(8, 6000, n=3, last='2026-09-09')), next_day_sort_key(item(1, 5000)))
        self.assertLess(next_day_sort_key(item(1, 5000)), next_day_sort_key(item(8, 5000)))
        # 指数が違えば回転数は見ない。
        self.assertLess(next_day_sort_key(dict(item(8, 1000), raw_index=55.1)), next_day_sort_key(item(1, 9000)))

    def test_today_unused_and_future_is_ignored(self):
        base = rows()
        target = next(r for r in base if r['day'] == '2026-09-10' and r['rack'] == 1)
        target.update(games=0, bb=0)
        e = next_day_evidence(Rows(base), target)
        future = dict(target, day='2026-09-11', games=6000, bb=80)
        self.assertEqual(e, next_day_evidence(Rows(base + [future]), target))
        self.assertFalse(e['today_used'])
        self.assertFalse(next_day_focus(e, None))


if __name__ == '__main__':
    unittest.main()
