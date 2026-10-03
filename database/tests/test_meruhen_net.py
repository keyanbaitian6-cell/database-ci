import tempfile
import unittest
from pathlib import Path

from core import Store, meruhen_net_estimate, report


def measurement(heights, with_curve=True, **extra):
    """Graph measurement from heights above the zero line (SVG height 400, zero 200.5)."""
    curve = [[i * 10.0 + 0.5, 200.5 - h] for i, h in enumerate(heights)]
    ys = [y for _, y in curve]
    data = dict(baseline_y=200.5, peak_y=min(ys), trough_y=max(ys), end_y=curve[-1][1], **extra)
    if with_curve:
        data['curve'] = curve
    return data


class MeruhenNetEstimateTests(unittest.TestCase):
    """Same cases as database_android/test/meruhen_net_test.dart (the rules must match)."""

    def test_two_thousand_medal_axis_examples(self):
        self.assertEqual(meruhen_net_estimate(measurement([0, -63, 40, 147, 128]), 2376), 1422)
        self.assertEqual(meruhen_net_estimate(measurement([0, -8, 163, 97]), 1982), 1078)

    def test_axis_step_is_chosen_from_the_swing_and_the_max_holding(self):
        self.assertEqual(meruhen_net_estimate(measurement([0, 60, 30]), 400), 167)
        self.assertEqual(meruhen_net_estimate(measurement([0, 120, 40, -50]), 2900), -1111)

    def test_unknown_stays_none_and_a_flat_day_is_zero(self):
        self.assertIsNone(meruhen_net_estimate(measurement([0, 50, 20]), None))
        self.assertIsNone(meruhen_net_estimate(measurement([0, 50, 20]), 88888888))
        self.assertEqual(meruhen_net_estimate(measurement([0, 0, 0]), 0), 0)
        self.assertIsNone(meruhen_net_estimate(measurement([0, -40, -80]), 0))
        self.assertIsNone(meruhen_net_estimate(dict(baseline_y=150.5, peak_y=100, trough_y=160, end_y=120), 500))
        self.assertIsNone(meruhen_net_estimate(None, 500))

    def test_four_points_only_when_one_step_fits(self):
        known = dict(baseline_y=200.5, peak_y=200.5 - 147, trough_y=200.5 + 63, end_y=200.5 - 128,
                     peak_x=300, trough_x=100, end_x=356)
        self.assertEqual(meruhen_net_estimate(known, 2376), 1422)
        ambiguous = dict(baseline_y=200.5, peak_y=100.5, trough_y=370.5, end_y=360.5,
                         peak_x=100, trough_x=300, end_x=356)
        self.assertIsNone(meruhen_net_estimate(ambiguous, 1500))
        # Old records without x positions: the order is unknown, so the lower rise bound is start -> peak.
        no_x = dict(baseline_y=200.5, peak_y=200.5 - 147, trough_y=200.5 + 63, end_y=200.5 - 128)
        self.assertEqual(meruhen_net_estimate(no_x, 2376), 1422)


class ResultPageTests(unittest.TestCase):
    def test_result_table_shows_the_estimate_column_and_dash_when_unknown(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            base = dict(store='nagamachiminami', kind_code=21, day='2026-10-03', machine='テスト', games=8584, bb=32, rb=30)
            db.save([dict(base, rack=615, max_hold=2376, graph_measurement=measurement([0, -63, 40, 147, 128])),
                     dict(base, rack=616, max_hold=2000)])
            output, _results = report(db, '2026-10-03', 'テスト', Path(folder) / 'reports')
            text = output.read_text(encoding='utf-8')
            db.close()
        self.assertIn('<th>推定差枚</th>', text)
        self.assertIn('<td>+1,422</td>', text)
        self.assertIn('確定値ではありません', text)
        self.assertIn('<th colspan="7">表示データ</th>', text)


if __name__ == '__main__':
    unittest.main()
