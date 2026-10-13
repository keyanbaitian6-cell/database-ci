import json
import tempfile
import unittest
from pathlib import Path

from core import (Store, VARIETY_GROUP_NAME, NEXT_DAY_METHOD_VERSION, candidate_method_version,
                  candidate_snapshot, is_variety_row, report, variety_machines,
                  variety_next_day_candidates)


def rows(store, day='2026-10-08'):
    return [dict(store=store, kind_code=21, day=day, machine=f'{n}台機種', rack=10*n+i,
                 games=3000, bb=10, rb=5, max_hold=1500,
                 graph_measurement=dict(baseline_y=200, peak_y=100, trough_y=220, end_y=150))
            for n in range(1, 5) for i in range(n)]


class VarietyScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Store(Path(self.tmp.name) / 'test.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save(rows('saiwaichou') + rows('nagamachiminami'))

    def test_store_scope_candidates_and_records_preserved(self):
        for store, names, total in [('saiwaichou', {'1台機種', '2台機種'}, 3),
                                    ('nagamachiminami', {'1台機種', '2台機種', '3台機種'}, 6)]:
            saved = self.db.rows('2026-10-08', None, store)
            self.assertEqual(len(saved), 10, '3台機種も元の記録として残る')
            self.assertEqual(variety_machines(saved), names)
            three = next(r for r in saved if r['machine'] == '3台機種')
            self.assertEqual(is_variety_row(self.db, three), store != 'saiwaichou')
            selected = variety_next_day_candidates(self.db, '2026-10-08', store)
            self.assertEqual(selected['total'], total)
            if store == 'saiwaichou':
                self.assertTrue(all(c['row']['machine'] != '3台機種' for c in selected['candidates']))

    def test_report_and_snapshot_revision(self):
        page, results = report(self.db, '2026-10-08', '3台機種', self.tmp.name, 'saiwaichou')
        self.assertEqual(len(results), 3)
        self.assertNotIn('この機種は1〜', page.read_text(encoding='utf-8'))
        page, _ = report(self.db, '2026-10-08', '2台機種', self.tmp.name, 'saiwaichou')
        self.assertIn('この機種は1〜2台の機種', page.read_text(encoding='utf-8'))
        snapshot = candidate_snapshot(self.db, 'saiwaichou', '2026-10-08', VARIETY_GROUP_NAME)
        self.assertEqual(snapshot['method'], '2026-10-13-saiwaichou-variety-2')
        self.assertEqual(candidate_method_version('saiwaichou', '3台機種'), NEXT_DAY_METHOD_VERSION)
        self.assertEqual(candidate_method_version('nagamachiminami', VARIETY_GROUP_NAME), NEXT_DAY_METHOD_VERSION)

    def test_transition_from_two_to_three_refreshes_both_groups(self):
        before = candidate_snapshot(self.db, 'saiwaichou', '2026-10-08', VARIETY_GROUP_NAME)
        self.assertEqual(before['total'], 3)
        self.db.save([{**rows('saiwaichou')[1], 'rack': 29}])
        saved = [json.loads(s) for s in self.db.candidate_snapshots(day='2026-10-08', location='saiwaichou')]
        latest = {s['machine']: s for s in saved}
        self.assertEqual(latest[VARIETY_GROUP_NAME]['total'], 1)
        self.assertIn('2台機種', latest)
        self.assertEqual(len(self.db.rows('2026-10-08', '2台機種', 'saiwaichou')), 3)
