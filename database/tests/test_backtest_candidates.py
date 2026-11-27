import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest_candidates import (  # noqa: E402
    block_bootstrap_ci,
    block_flip_p,
    collect,
    day_gaps,
    hit_rank,
    load_csv,
    oe_ratio,
    permutation_p,
    plus_outcome,
    plus_summary,
    summarize,
)


def sample(strong_racks, seed, days=40, racks=12):
    """One machine. Racks in ``strong_racks`` hit about 30% lighter every day."""
    rng = random.Random(seed)
    rows = []
    start = date(2026, 8, 1)
    for d in range(days):
        day = (start + timedelta(days=d)).isoformat()
        for rack in range(1, racks + 1):
            games = rng.randint(2500, 7000)
            rate = 1 / (170 if rack in strong_racks else 220)
            hits = sum(rng.random() < rate for _ in range(games))
            bb = hits * 2 // 3
            rows.append(dict(store='nagamachiminami', day=day, machine='M', rack=rack,
                             games=games, bb=bb, rb=hits - bb, total=None))
    return rows


class BacktestCandidatesTest(unittest.TestCase):
    def test_finds_racks_that_really_are_lighter(self):
        entries = collect(sample({1, 2, 3}, seed=1))
        gap, p = permutation_p(entries, 'next_rank', trials=500)
        self.assertGreater(gap, 10)
        self.assertLess(p, .01)

    def test_no_signal_when_every_rack_is_the_same(self):
        # 1回だけだと20回に1回は偶然 p<0.05 になる（それが正しい振る舞い）。
        # 何回か平均して、差が0のまわりに集まることを確かめる。
        gaps = [permutation_p(collect(sample(set(), seed=s, days=30)), 'next_rank', trials=50)[0]
                for s in range(100, 108)]
        self.assertLess(abs(sum(gaps) / len(gaps)), 3)

    def test_uses_only_days_up_to_the_candidate_day(self):
        rows = sample({1, 2, 3}, seed=3, days=10)
        before = collect(rows)
        # Changing the future (after the last candidate day) must not change
        # which racks were candidates or their index.
        last = max(r['day'] for r in rows)
        future = [dict(r, bb=0, rb=0) if r['day'] == last else r for r in rows]
        after = collect(future)
        strip = lambda es: [(e['day'], e['rack'], e['index'], e['candidate']) for e in es]
        self.assertEqual(strip(before), strip(after))

    def test_summary_runs_without_candidates(self):
        lines = []
        summarize([], trials=10, out=lines.append)
        self.assertTrue(any('比べられません' in line for line in lines))

    def test_rejects_compact_android_csv_with_clear_guidance(self):
        path = Path(__file__).resolve().parent / 'fixtures' / 'compact_android.csv'
        with self.assertRaisesRegex(ValueError, 'バックアップJSON（--json）'):
            load_csv(path)

    def test_hit_rank_and_plus_outcome_exclude_implausible_and_handle_zero_hits(self):
        r1 = dict(games=3000, bb=15, rb=10)
        r2 = dict(games=3000, bb=10, rb=10)
        r3 = dict(games=3000, bb=5, rb=10)
        bogus = dict(games=3000, bb=888, rb=10)
        self.assertIsNone(hit_rank(bogus, [r1, r2, r3, bogus]))
        self.assertEqual(hit_rank(r1, [r1, r2, r3, bogus]), hit_rank(r1, [r1, r2, r3]))
        self.assertEqual(plus_outcome(dict(games=3000, bb=10, rb=5, jo_net=100)), 1)
        self.assertEqual(plus_outcome(dict(games=3000, bb=10, rb=5, jo_net=0)), 0)
        self.assertEqual(plus_outcome(dict(games=3000, bb=10, rb=5, graph_measurement={'baseline_y': 100, 'end_y': 80})), 1)
        self.assertIsNone(plus_outcome(dict(games=3000, bb=10, rb=5, graph_measurement={'baseline_y': 100, 'end_y': 99.5})))
        self.assertEqual(plus_outcome(dict(games=900, bb=0, rb=0)), 0)
        self.assertIsNone(plus_outcome(dict(games=0, bb=0, rb=0)))

    def test_block_stats_oe_ratio_manski_bounds_and_cutoff(self):
        rows = sample({1, 2, 3}, seed=2, days=35)
        for r in rows:
            r['captured_at'] = f"{r['day']}T23:30:00+09:00"
            r['jo_net'] = 500 if (r['rack'] in {1, 2, 3} and int(r['day'][-2:]) % 3 != 0) else (-300 if r['rack'] > 3 else None)
        # 1件だけ締切（翌日8時）超過の記録と非表示機種を混ぜる。
        late_day = '2026-08-10'
        for r in rows:
            if r['day'] == late_day and r['rack'] == 1:
                r['captured_at'] = '2026-08-11T09:00:00+09:00'
        rows.append(dict(rows[0], store='saiwaichou', machine='聖闘士星矢 海皇覚醒', rack=1279))

        entries = collect(rows, cutoff_hour=8)
        self.assertFalse(any(e['machine'] == '聖闘士星矢 海皇覚醒' for e in entries))
        self.assertFalse(any(e['day'] == late_day and e['rack'] == 1 for e in entries))

        diffs = day_gaps(entries, 'next_rank')
        m7, p7, b7 = block_flip_p(diffs, block_days=7)
        ci7 = block_bootstrap_ci(diffs, block_days=7, rounds=1000)
        self.assertGreater(m7, 5)
        self.assertLess(p7, 0.1)
        self.assertGreaterEqual(b7, 4)
        self.assertLess(ci7[0], ci7[1])

        oe = oe_ratio(entries)
        self.assertGreater(oe['ratio'], 1.05)

        ps = plus_summary(entries)
        self.assertLessEqual(ps['manski_worst'], ps['both_zero'] + 1e-12)
        self.assertLessEqual(ps['manski_worst'], ps['both_one'] + 1e-12)
        self.assertLessEqual(ps['both_zero'], ps['manski_best'] + 1e-12)
        self.assertLessEqual(ps['both_one'], ps['manski_best'] + 1e-12)


if __name__ == '__main__':
    unittest.main()
