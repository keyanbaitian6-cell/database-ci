import csv
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest_candidate_scores import evaluation_groups, join_scores  # noqa: E402


def source_csv(rows, *, rack=False):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['日付', '機種名'] + (['台番号'] if rack else []) +
                    ['採点結果', 'G数', '最大持ち球', 'B', 'R'])
    writer.writerows(rows)
    path = Mock()
    path.open.return_value = io.StringIO(stream.getvalue())
    return path


class CandidateScoreBacktestTest(unittest.TestCase):
    def test_only_unique_csv_and_backup_fingerprints_are_joined(self):
        rows = [
            dict(store='a', day='2026-09-23', machine='M', rack=1,
                 games=1000, max_hold=500, bb=5, rb=2),
            dict(store='a', day='2026-09-23', machine='M', rack=2,
                 games=2000, max_hold=300, bb=8, rb=1),
            dict(store='a', day='2026-09-23', machine='M', rack=3,
                 games=2000, max_hold=300, bb=8, rb=1),
        ]
        source = source_csv([
            ['2026-09-23', 'M', '暫定 62.5点', 1000, 500, 5, 2],
            ['2026-09-23', 'M', '参考 80.0点', 2000, 300, 8, 1],
        ])
        matched, csv_count = join_scores(rows, source)
        self.assertEqual(csv_count, 2)
        self.assertEqual(matched, {('a', '2026-09-23', 'M', 1): 62.5})

    def test_duplicate_csv_fingerprint_is_not_guessed_from_row_order(self):
        rows = [dict(store='a', day='2026-09-23', machine='M', rack=1,
                     games=1000, max_hold=None, bb=5, rb=2)]
        source = source_csv([
            ['2026-09-23', 'M', '暫定 62.5点', 1000, '', 5, 2],
            ['2026-09-23', 'M', '暫定 62.5点', 1000, '', 5, 2],
        ])
        matched, _ = join_scores(rows, source)
        self.assertEqual(matched, {})

    def test_new_csv_rack_column_resolves_identical_numbers(self):
        rows = [
            dict(store='a', day='2026-09-23', machine='M', rack=rack,
                 games=1000, max_hold=500, bb=5, rb=2)
            for rack in (1, 2)
        ]
        source = source_csv([
            ['2026-09-23', 'M', 1, '暫定 62.5点', 1000, 500, 5, 2],
            ['2026-09-23', 'M', 2, '暫定 48.0点', 1000, 500, 5, 2],
        ], rack=True)
        matched, _ = join_scores(rows, source)
        self.assertEqual(matched, {
            ('a', '2026-09-23', 'M', 1): 62.5,
            ('a', '2026-09-23', 'M', 2): 48.0,
        })

    def test_late_imports_do_not_enter_capture_aware_predictions(self):
        rows = [
            dict(store='a', day=f'2026-09-{day:02d}', machine='M', rack=rack,
                 games=1000, max_hold=500, bb=5 + rack, rb=2,
                 captured_at='2026-09-20T12:00:00+09:00')
            for day in range(10, 14) for rack in range(1, 5)
        ]
        self.assertTrue(evaluation_groups(rows, {}))
        self.assertEqual(evaluation_groups(rows, {}, cutoff_hour=0), [])


if __name__ == '__main__':
    unittest.main()
