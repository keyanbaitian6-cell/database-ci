"""日次学習の点検（PCの窓、2026-11-14 利用者「やってみよう」）。

直近14晩について、予測を保存できたかと、その予測に使った前日データで符号が決まらない台（判定不能）の数を出す。
予測と固定した入力だけを読み、成績（outcomes・decisions）は開かない。"""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import daily_learning as d
import daily_learning_runtime as runtime
from daily_learning_view import checkup_view

STORE = 'nagamachiminami'


def rows_for(day, known=4, unknown=1, idle=2, store=STORE):
    """有効で差枚のある台・有効で差枚もグラフも無い台・0Gの台（有効でない）。"""
    out, rack = [], 1
    for _ in range(known):
        out.append({'store': store, 'day': day, 'machine': 'A', 'rack': rack, 'games': 3000, 'jo_net': 500 - rack * 200})
        rack += 1
    for _ in range(unknown):
        out.append({'store': store, 'day': day, 'machine': 'A', 'rack': rack, 'games': 2500})
        rack += 1
    for _ in range(idle):
        out.append({'store': store, 'day': day, 'machine': 'A', 'rack': rack, 'games': 0})
        rack += 1
    return out


def at(stamp):
    return datetime.fromisoformat(stamp + '+09:00')


class CheckupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = d.Journal(Path(self.temp.name) / 'journal.sqlite3')
        with self.journal.db:
            self.journal.state('start', '2026-11-11')
        # 11/11・11/13 は保存、11/12 は保存できなかった晩。入力には前の日も入れる（前日の分だけを数える）。
        for target, day, unknown in (('2026-11-11', '2026-11-10', 1), ('2026-11-13', '2026-11-12', 3)):
            rows = rows_for(runtime.shift(day, -1), unknown=0) + rows_for(day, unknown=unknown)
            self.assertTrue(self.journal.freeze(target, {'groups': [], 'input_day': day}, rows, at(target + 'T00:30:00'), store=STORE))

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def test_saved_missed_before_and_counts_of_the_previous_day(self):
        result = runtime.checkup(self.journal, at('2026-11-13T12:00:00'))
        cells = {c['target']: c for c in result['stores'][STORE]}
        self.assertEqual(len(result['stores'][STORE]), 14)
        self.assertEqual(result['stores'][STORE][-1]['target'], '2026-11-13')
        self.assertEqual(cells['2026-11-10']['state'], 'before')
        self.assertEqual(cells['2026-11-11'], {'target': '2026-11-11', 'state': 'saved', 'racks': 5, 'unknown': 1})
        self.assertEqual(cells['2026-11-12']['state'], 'missed')
        self.assertEqual(cells['2026-11-13'], {'target': '2026-11-13', 'state': 'saved', 'racks': 7, 'unknown': 3})
        # 予測の無いほかの店は、始めたあとの晩がすべて×。
        self.assertEqual([c['state'] for c in result['stores']['saiwaichou']][-3:], ['missed'] * 3)

    def test_tonight_is_pending_while_the_save_window_is_open(self):
        result = runtime.checkup(self.journal, at('2026-11-13T23:45:00'))
        cells = result['stores'][STORE]
        self.assertEqual(cells[-1], {'target': '2026-11-14', 'state': 'pending'})
        self.assertEqual(cells[-2]['state'], 'saved')

    def test_never_opens_outcomes_or_decisions_and_counts_once(self):
        original = self.journal.get
        seen = []

        def guarded(table, key):
            self.assertNotIn(table, ('outcomes', 'decisions'))
            seen.append(table)
            return original(table, key)
        with mock.patch.object(self.journal, 'get', side_effect=guarded):
            runtime.checkup(self.journal, at('2026-11-13T12:00:00'))
            first = seen.count('inputs')
            seen.clear()
            runtime.checkup(self.journal, at('2026-11-13T12:00:00'))
        self.assertGreater(first, 0)
        self.assertEqual(seen.count('inputs'), 0)     # 2回目は state の控えを使う

    def test_reads_only_the_newest_chunk_not_all_days(self):
        prediction = self.journal.get('predictions', '2026-11-13|' + STORE)
        with mock.patch.object(self.journal, 'get', wraps=self.journal.get) as spy:
            rows = runtime.input_day_rows(self.journal, prediction, '2026-11-12')
        self.assertEqual({r['day'] for r in rows}, {'2026-11-12'})
        self.assertEqual(sum(1 for c in spy.call_args_list if c.args[0] == 'inputs'), 1)
        self.assertEqual(runtime.input_day_rows(self.journal, prediction, '2026-10-01'), [])

    def test_export_has_checkup_and_survives_a_checkup_failure(self):
        data_dir = Path(self.temp.name)
        doc = runtime.export(self.journal, data_dir, '状態', at('2026-11-13T12:00:00'))
        self.assertEqual(doc['checkup']['latest'], '2026-11-13')
        self.assertIn('checkup', json.loads((data_dir / runtime.FILE_NAME).read_text(encoding='utf-8')))
        with mock.patch.object(runtime, 'checkup', side_effect=ValueError('壊れた')):
            doc = runtime.export(self.journal, data_dir, '状態', at('2026-11-13T12:00:00'))
        self.assertNotIn('checkup', doc)
        self.assertIn('壊れた', doc['checkup_error'])
        self.assertEqual(doc['status'], '状態')

    def test_view_summary_marks_and_rates(self):
        doc = {'checkup': runtime.checkup(self.journal, at('2026-11-13T12:00:00'))}
        view = checkup_view(doc, STORE)
        self.assertEqual(view['nights'], 14)
        self.assertEqual([c['mark'] for c in view['cells']][-4:], ['—', '○', '×', '○'])
        self.assertEqual([c['rate'] for c in view['cells']][-3:], ['20%', '', '43%'])
        self.assertEqual(view['cells'][-1]['day'], '11/13')
        self.assertEqual(view['summary'], '保存 2/3晩　判定不能 33%（有効な台 12台のうち 4台）')
        self.assertEqual(view['missed'], ['2026-11-12'])
        # 点検が無い・形が違う・別の店舗が無いときは出さない（窓は「次の実行後に出ます」）。
        self.assertIsNone(checkup_view({}, STORE))
        self.assertIsNone(checkup_view({'checkup': {'stores': {STORE: [{'target': '2026-11-13', 'state': 'x'}]}}}, STORE))
        self.assertIsNone(checkup_view({'checkup': 'x'}, STORE))


if __name__ == '__main__':
    unittest.main()
