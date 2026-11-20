"""係数固定対照の新台・欠測・期限・営業前の同時保存を一時DBで確認する。"""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import daily_learning as d
import daily_learning_fixed as fixed
import daily_learning_runtime as runtime

STORE = fixed.STORES[0]


class FixedControlTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'journal.sqlite3'
        self.j = d.Journal(self.path)
        self.addCleanup(self.j.close)

    def emit(self, target, machine, slope, own=True, common=True, method='same', store=STORE):
        rows = [dict(store=store, day=d.shift(target, -1), machine=machine, rack=i, games=i * 100)
                for i in (1, 2)]
        groups = [dict(store=store, rate='', name=machine, pool=rows, current=[d.identity(rows[0])])]
        models = {}
        if common:
            models[store, '', d.STORE_MODEL] = dict(weights=[0.] * 7 + [slope] + [0.] * 4)
        if own:
            models[store, '', machine] = dict(weights=[0.] * 7 + [-slope] + [0.] * 2)
        with (patch.object(runtime, 'baseline_groups', return_value=groups),
              patch.object(runtime, 'train', return_value=models),
              patch.object(runtime, 'method_signature', return_value=method)):
            p = runtime.build_prediction(rows, {}, target, self.j)
        now = datetime.fromisoformat(target + 'T07:59:00+09:00')
        self.j.freeze(target, p, rows, now, store=store)
        return self.j.get('predictions', target + '|' + store)

    def test_anchor_and_new_machine_match_both_kinds_without_changing_operational_picks(self):
        day = fixed.FIRST
        first = self.emit(day, 'A', 1)
        key = first['groups'][0]['key']
        pair = first[fixed.STUDY]['pairs'][key]
        self.assertEqual(pair['fixed'], pair['updated'])
        second = self.emit(d.shift(day, 1), '新', -1)
        group = second['groups'][0]
        pair = second[fixed.STUDY]['pairs'][group['key']]
        self.assertEqual((pair['kind'], pair['fixed'][0][-1], pair['updated'][0][-1]), ('store', 2, 1))
        self.assertEqual((group['model'], group['learned'][0][-1], group['selected']), ('machine', 2, group['current']))
        again = self.emit(day, 'A', -1)
        self.assertEqual(first, again)
        later = self.emit(d.shift(day, 3), 'A', -1)[fixed.STUDY]
        self.assertEqual(later['anchor'], day)
        self.assertEqual((later['pairs'][key]['fixed'][0][-1], later['pairs'][key]['updated'][0][-1]), (1, 2))

    def test_store_isolation_version_change_dates_and_absent_models(self):
        self.assertNotIn(fixed.STUDY, self.emit(d.shift(fixed.FIRST, -1), 'A', 1))
        self.emit(fixed.FIRST, 'A', 1, common=False)
        new = self.emit(d.shift(fixed.FIRST, 1), '新', 1)
        self.assertIn('reason', next(iter(new[fixed.STUDY]['pairs'].values())))
        changed = self.emit(d.shift(fixed.FIRST, 2), 'A', 1, method='changed')[fixed.STUDY]
        self.assertIn('reason', changed)
        other = self.emit(d.shift(fixed.FIRST, 2), 'A', 1, store=fixed.STORES[1])
        self.assertEqual(other[fixed.STUDY]['anchor'], d.shift(fixed.FIRST, 2))
        self.assertNotIn(fixed.STUDY, self.emit(d.shift(fixed.LAST, 1), 'A', 1))

    def test_deadline_without_opening_db_and_evaluation_with_mature_missing_and_paired_labels(self):
        def clock(day):
            return datetime.fromisoformat(day + 'T07:00:00+09:00')
        with patch.object(fixed, 'datetime') as now:
            now.now.return_value = clock(d.shift(fixed.EVALUATE_ON, -1))
            with self.assertRaisesRegex(ValueError, fixed.EVALUATE_ON):
                fixed.evaluate(self.path.parent / 'missing.sqlite3')
            now.now.return_value = clock(fixed.EVALUATE_ON)
            for i, slope in enumerate((1, -1, -1)):
                day = d.shift(fixed.FIRST, i)
                p = self.emit(day, 'A', slope)
                with self.assertRaisesRegex(ValueError, '成熟結果'):
                    fixed.evaluate(self.path)
                g = p['groups'][0]
                labels = {d.encoded(r['id']): (None if i == 2 else int(r['id'][-1] == 2)) for r in g['pool']}
                with self.j.db:
                    self.j.append('outcomes', day + '|' + STORE, dict(groups=[dict(key=g['key'], labels=labels)]))
            result = fixed.evaluate(self.path)[STORE]
            self.assertEqual(result['comparison']['n'], 2)
            self.assertAlmostEqual(result['comparison']['difference'], .5)
            self.assertFalse(result['update_benefit_supported'])
            self.assertEqual(result['missing_predictions'], 109)
            self.assertFalse(self.j.get('state', 'store:' + STORE))
            self.assertEqual(fixed.evaluate(self.path)[fixed.STORES[2]], {'available_from': fixed.PS_EVALUATE_ON})
            now.now.return_value = clock(fixed.PS_EVALUATE_ON)
            self.assertEqual(fixed.evaluate(self.path)[fixed.STORES[2]]['missing_predictions'], 112)

    def test_normal_runtime_saves_control_with_prediction_and_keeps_it_out_of_export(self):
        day = fixed.FIRST
        rows = [dict(store=STORE, day=d.shift(day, -1), machine='A', rack=i, games=1000) for i in (1, 2)]
        groups = [dict(store=STORE, rate='', name='A', pool=rows, current=[d.identity(rows[0])])]
        model = {(STORE, '', 'A'): dict(weights=[0.] * 10)}
        root = self.path.parent / 'pc'
        root.mkdir()
        now = datetime.fromisoformat(day + 'T07:00:00+09:00')
        with (patch.object(runtime, 'load_inputs', return_value=(rows, {'records': [], 'machines': []})),
              patch.object(runtime, 'ready', side_effect=lambda rows, day, stores, low: [] if stores == (STORE,) else ['待ち']),
              patch.object(runtime, 'skipped_low_racks', return_value={}),
              patch.object(runtime, 'baseline_groups', return_value=groups), patch.object(runtime, 'train', return_value=model)):
            doc = runtime.run(root, clock=lambda: now, sync=False)
            self.assertNotIn(fixed.STUDY, d.encoded(doc))
            runtime.run(root, clock=lambda: now, sync=False)
        journal = d.Journal(root / 'daily-learning/journal.sqlite3', readonly=True)
        self.addCleanup(journal.close)
        self.assertEqual(journal.db.execute('SELECT count(*) FROM predictions').fetchone()[0], 1)
        p = journal.get('predictions', day + '|' + STORE)
        self.assertEqual(p[fixed.STUDY]['anchor'], day)
        self.assertEqual(next(iter(p[fixed.STUDY]['pairs'].values()))['fixed'], p['groups'][0]['learned'])
