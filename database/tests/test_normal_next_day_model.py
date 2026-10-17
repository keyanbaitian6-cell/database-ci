"""幸町のジャグラー・ハナハナの翌日候補を予想の式で並べる（2026-10-17、改訂 2026-10-18。NEXT_DAY_MODEL_PLAN_20261017.md）。
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

    def test_only_saiwaichou_juggler_and_hanahana_from_the_start_day(self):
        self.assertTrue(normal_model_applies('saiwaichou', MACHINE, '2026-10-17'))
        self.assertFalse(normal_model_applies('saiwaichou', MACHINE, '2026-10-16'))  # 過去の日は今までの選び方
        self.assertTrue(normal_model_applies('saiwaichou', 'SキングハナハナSP−30', '2026-11-01'))
        self.assertFalse(normal_model_applies('nagamachiminami', MACHINE, '2026-11-01'))
        self.assertFalse(normal_model_applies('saiwaichou', 'L ゴッドイーター', '2026-11-01'))
        self.assertEqual(candidate_method_version('saiwaichou', MACHINE, '2026-10-17'), m.METHOD_VERSION)
        self.assertEqual(candidate_method_version('saiwaichou', MACHINE, '2026-10-16'), '2026-10-07')
        self.assertEqual(candidate_method_version('nagamachiminami', MACHINE, '2026-10-17'), '2026-10-07')

    def test_candidates_and_scores_match_the_shared_fixture(self):
        # Android も同じ期待値で確かめる。式・材料を変えたら、期待値を作り直してから両方を直す。
        self.assertTrue(any(e['model'] for e in self.doc['expected']))
        self.assertTrue(any(not e['model'] for e in self.doc['expected']))
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

    def test_before_the_start_day_the_old_order_is_kept(self):
        changed = False
        for expected in self.doc['expected']:
            day = expected['day']
            result = provisional_next_day_candidates(self.db, day, MACHINE, 'saiwaichou')
            eligible = [dict(row=r, **e) for r in self.db.rows(day, MACHINE, 'saiwaichou')
                        if (e := next_day_evidence(self.db, r))['raw_index'] is not None]
            self.assertEqual(result['eligible'], len(eligible))
            old = [int(e['row']['rack']) for e in sorted(eligible, key=next_day_sort_key)[:result['count']]]
            if not expected['model']:
                self.assertEqual(old, expected['candidates'], day)   # 過去の日は今までの選び方のまま
                self.assertTrue(all('model_score' not in c for c in result['candidates']))
            else:
                scores = [c['model_score'] for c in result['candidates']]
                self.assertEqual(scores, sorted(scores, reverse=True))
                changed |= old != expected['candidates']
        self.assertTrue(changed)  # 式の日には、今までの選び方と違う台を選ぶ日がある

    def test_long_habit_uses_only_the_last_60_days(self):
        # 検証と実際のアプリで履歴の長さをそろえる（2026-10-18 Codex の指摘）。61日以上前の日は数えない。
        def old_day(day):
            # 700番台だけ当たりがとても良い日（順位が付く4台）。
            return [dict(self.doc['rows'][0], day=day, rack=rack, games=8000, bb=60 if rack == 700 else 20,
                         rb=50 if rack == 700 else 15) for rack in (700, 701, 702, 703)]
        target = next(r for r in self.doc['rows'] if r['day'] == '2026-10-20' and r['rack'] == 700)
        base = m.features(m.history_values(self.doc['rows'], '2026-10-20'), target, 50.0)['s_long']
        far = m.features(m.history_values(old_day('2026-08-20') + self.doc['rows'], '2026-10-20'), target, 50.0)['s_long']
        near = m.features(m.history_values(old_day('2026-08-25') + self.doc['rows'], '2026-10-20'), target, 50.0)['s_long']
        self.assertEqual(far, base)      # 61日前：数えない
        self.assertGreater(near, base)   # 56日前：数える

    def test_new_rack_and_machine_page(self):
        from core import report
        per_rack = m.history_values(self.db._machine_rows(MACHINE, 'saiwaichou'), '2026-10-19')
        first = next(r for r in self.db.rows('2026-10-19', MACHINE, 'saiwaichou') if int(r['rack']) == 707)
        self.assertEqual(m.features(per_rack, first, 50.0)['new_rack'], 1.0)
        page = Path(report(self.db, '2026-10-20', MACHINE, self.folder.name, 'saiwaichou')[0]).read_text(encoding='utf-8')
        self.assertIn('予想の式で見積もった上位の台', page)
        self.assertIn('直近60日', page)
        before = Path(report(self.db, '2026-10-10', MACHINE, self.folder.name, 'saiwaichou')[0]).read_text(encoding='utf-8')
        self.assertIn('過去に当たりが周りの台より軽かった台です', before)


if __name__ == '__main__':
    unittest.main()
