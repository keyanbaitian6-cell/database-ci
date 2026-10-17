"""幸町のジャグラー・ハナハナの翌日候補を予想の式で並べる（2026-10-17、NEXT_DAY_MODEL_PLAN_20261017.md）。
Android `test/normal_next_day_model_test.dart` と同じ試験用の記録・同じ期待値（fixtures/normal_next_day_rows.json）。"""
import json
import tempfile
import unittest
from pathlib import Path

from core import (Store, candidate_method_version, next_day_evidence, next_day_sort_key,
                  normal_model_applies, provisional_next_day_candidates)
import normal_next_day_model as m

FIXTURE = Path(__file__).with_name('fixtures') / 'normal_next_day_rows.json'
MACHINE = 'SマイジャグラーVKD'


class NormalNextDayModelTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Store(Path(self.folder.name) / 'db.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save(self.doc['rows'])

    def test_only_saiwaichou_juggler_and_hanahana(self):
        self.assertTrue(normal_model_applies('saiwaichou', 'SマイジャグラーVKD'))
        self.assertTrue(normal_model_applies('saiwaichou', 'SキングハナハナSP−30'))
        self.assertFalse(normal_model_applies('nagamachiminami', 'SマイジャグラーVKD'))
        self.assertFalse(normal_model_applies('saiwaichou', 'L ゴッドイーター'))
        self.assertEqual(candidate_method_version('saiwaichou', MACHINE), m.METHOD_VERSION)
        self.assertEqual(candidate_method_version('nagamachiminami', MACHINE), '2026-10-07')
        self.assertEqual(candidate_method_version('saiwaichou', 'L ゴッドイーター'), '2026-10-07')

    def test_candidates_and_scores_match_the_shared_fixture(self):
        # Android も同じ期待値で確かめる。式・材料を変えたら、期待値を作り直してから両方を直す。
        for expected in self.doc['expected']:
            day = expected['day']
            result = provisional_next_day_candidates(self.db, day, MACHINE, 'saiwaichou')
            self.assertEqual([int(c['row']['rack']) for c in result['candidates']], expected['candidates'], day)
            per_rack = m.history_values(self.db._machine_rows(MACHINE, 'saiwaichou'), day)
            for row in self.db.rows(day, MACHINE, 'saiwaichou'):
                e = next_day_evidence(self.db, row)
                if e['raw_index'] is None:
                    continue
                score = round(m.score(m.features(per_rack, row, e['raw_index'])), 9)
                self.assertAlmostEqual(score, expected['scores'][str(row['rack'])], places=9, msg=(day, row['rack']))

    def test_same_racks_and_count_only_the_order_changes(self):
        # 候補に入りうる台（今の指数が出せる台）と台数は今の選び方と同じ。並べる順だけが式の点。
        changed = False
        for expected in self.doc['expected']:
            day = expected['day']
            result = provisional_next_day_candidates(self.db, day, MACHINE, 'saiwaichou')
            eligible = [dict(row=r, **e) for r in self.db.rows(day, MACHINE, 'saiwaichou')
                        if (e := next_day_evidence(self.db, r))['raw_index'] is not None]
            self.assertEqual(result['eligible'], len(eligible))
            self.assertEqual(len(result['candidates']), result['count'])
            old = [int(e['row']['rack']) for e in sorted(eligible, key=next_day_sort_key)[:result['count']]]
            changed |= old != expected['candidates']
            scores = [c['model_score'] for c in result['candidates']]
            self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(changed)  # 試験用の記録で、今の選び方と違う台を選ぶ日がある

    def test_features_follow_the_validated_definitions(self):
        per_rack = m.history_values(self.db._machine_rows(MACHINE, 'saiwaichou'), '2026-09-20')
        row = next(r for r in self.db.rows('2026-09-20', MACHINE, 'saiwaichou') if int(r['rack']) == 707)
        f = m.features(per_rack, row, 50.0)
        self.assertEqual(f['v0'], 0.0)
        self.assertEqual(f['new_rack'], 0.0)
        self.assertEqual(f['long_play'], float(row['games'] >= 7000))
        # 入れ替えで9/13から入った台：その前の日は数えない。
        self.assertTrue(all(d >= '2026-09-13' for d, *_ in per_rack[707]))
        first = next(r for r in self.db.rows('2026-09-13', MACHINE, 'saiwaichou') if int(r['rack']) == 707)
        self.assertEqual(m.features(m.history_values(self.db._machine_rows(MACHINE, 'saiwaichou'), '2026-09-13'),
                                    first, 50.0)['new_rack'], 1.0)

    def test_machine_page_explains_the_order(self):
        from core import report
        page = Path(report(self.db, '2026-09-20', MACHINE, self.folder.name, 'saiwaichou')[0]).read_text(encoding='utf-8')
        self.assertIn('予想の式で見積もった上位の台', page)
        self.assertIn('14か月分（2025年9月〜2026年10月）から作った予想の式', page)
        self.assertNotIn('過去に当たりが周りの台より軽かった台です', page)


if __name__ == '__main__':
    unittest.main()
