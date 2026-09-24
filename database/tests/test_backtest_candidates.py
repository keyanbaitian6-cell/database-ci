import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest_candidates import collect, permutation_p, summarize  # noqa: E402


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


if __name__ == '__main__':
    unittest.main()
