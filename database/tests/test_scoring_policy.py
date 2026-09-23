"""Policy invariants, independent of the UI and production database."""
import unittest
from core import score, round_score


def sample(**changes):
    return dict(dict(store='saiwaichou', machine='M', day='2026-09-20',
                     rack=1, games=3000, bb=60, rb=30, max_hold=3000,
                     graph_measurement=dict(baseline_y=200, peak_y=100,
                                            trough_y=250, end_y=100)), **changes)


def references(days=3, per_day=10):
    return [sample(day=f'2026-09-{19-d:02}', rack=i, bb=30, rb=15,
                   max_hold=1000) for d in range(days) for i in range(per_day)]


class PolicyTests(unittest.TestCase):
    def test_half_up_rounding_agrees_with_android(self):
        self.assertEqual(round_score(62.25), 62.3)

    def test_hand_calculated_shrinkage(self):
        # v9: 掛け算ではなく相乗平均。
        # weight = (3000/4500 * 30/50 * 3/6)^(1/3) = .2^(1/3) = .584804; rank=1。
        # 当たり = 60*(.5 + .584804*.5) = 47.5441
        # 持玉 = 20*(.5 + .584804*.5) = 15.8480（枚数による点 20*3000/19000 = 3.16 より大きいので順位側）
        # 合計 = 47.5441 + 15.8480 + 10 + 10 = 83.392 → 83.4
        result = score(sample(), references())
        self.assertAlmostEqual(result['hits'], 47.5441064292772)
        self.assertAlmostEqual(result['max_hold'], 15.848035476425734)
        self.assertEqual(result['total'], 83.4)
        self.assertEqual(result['reference_days'], 3)
        self.assertEqual(result['coverage'], 100)
        self.assertFalse(result['provisional'])

    def test_future_other_store_model_old_and_exposure_are_excluded(self):
        refs = references()
        expected = score(sample(), refs)
        contaminants = [sample(day='2026-09-21'), sample(day='2026-09-20'),
                        sample(day='2026-08-20'), sample(day='2026-09-19', store='nagamachiminami'),
                        sample(day='2026-09-19', machine='other'),
                        sample(day='2026-09-19', games=499), sample(day='2026-09-19', games=7000)]
        self.assertEqual(expected, score(sample(), refs + contaminants))

    def test_sample_size_and_distinct_days_reduce_extremes(self):
        small = score(sample(), references(1, 1))
        one_day = score(sample(), references(1, 30))
        three_days = score(sample(), references(3, 10))
        self.assertLess(small['hits'], one_day['hits'])
        self.assertLess(one_day['hits'], three_days['hits'])

    def test_missing_hold_does_not_increase_other_weights(self):
        # 47.5441 + 10 + 10 = 67.544 に、欠けた持玉20点の半分を足して 77.5。
        full = score(sample(), references())
        missing = score(sample(max_hold=None), references())
        self.assertEqual(missing['hits'], full['hits'])
        self.assertEqual(missing['total'], 77.5)
        self.assertEqual((missing['missing_low'], missing['missing_high']), (67.5, 87.5))
        self.assertEqual(missing['coverage'], 80)
        self.assertTrue(missing['provisional'])

    def test_complete_hold_earns_full_marks_and_never_lowers_a_rank(self):
        # コンプリート上限（19,000枚）まで出た台は、比較相手が少なくても持玉は満点。
        complete = score(sample(max_hold=19000), references())
        self.assertEqual(complete['max_hold'], 20)
        self.assertEqual(score(sample(max_hold=25000), references())['max_hold'], 20)
        # 枚数が少ない台は、順位による点のまま（枚数による点では下げない）。
        low = score(sample(max_hold=1000), references(), )
        ranked_only = 20 * (0.5 + (3000 / 4500 * 30 / 50 * 3 / 6) ** (1 / 3) * (0.5 - 0.5))
        self.assertAlmostEqual(low['max_hold'], ranked_only)
        self.assertGreater(low['max_hold'], 20 * 1000 / 19000)

    def test_zero_games_has_no_score_and_negative_counts_are_rejected(self):
        self.assertIsNone(score(sample(games=0), references())['total'])
        self.assertIsNone(score(sample(bb=-1), references())['total'])

    def test_corrected_points_override_stale_raw_curve(self):
        r = sample(graph=dict(path='M0,200 L1,300', baseline=200))
        self.assertEqual(score(r, references())['positive'], 10)

    def test_growth_in_games_alone_never_earns_points(self):
        a = score(sample(games=3000, bb=30, rb=15, max_hold=1000), references())
        b = score(sample(games=6000, bb=60, rb=30, max_hold=1000), references())
        self.assertEqual(a['total'], b['total'])  # identical rates, ties at midpoint
        self.assertEqual(a['games'], 0)

    def test_near_zero_graph_keeps_a_missing_range(self):
        # 47.5441 + 15.8480 = 63.392 に、欠けた終点・維持20点の半分を足して 73.4。
        r = sample(graph_measurement=dict(baseline_y=200, peak_y=100, end_y=199.5))
        result = score(r, references())
        self.assertEqual(result['coverage'], 80)
        self.assertEqual(result['total'], 73.4)
        self.assertEqual((result['missing_low'], result['missing_high']), (63.4, 83.4))
