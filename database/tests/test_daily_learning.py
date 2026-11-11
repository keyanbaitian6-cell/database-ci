import copy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import daily_learning as d
import daily_learning_runtime as runtime


def row(day='2026-11-10', rack=1, win=True, store='nagamachiminami', machine='試験機'):
    return dict(day=day, rack=rack, store=store, machine=machine, games=4000, bb=20, rb=10,
                max_hold=2000, jo_net=100 if win else -100,
                graph_measurement=dict(baseline_y=50, end_y=25 if win else 75, peak_y=20, trough_y=80))


class LearningTests(unittest.TestCase):
    def test_missing_zero_and_source(self):
        r = row()
        self.assertEqual(d.outcome(r), 1)
        r['jo_net'] = 0
        self.assertEqual(d.outcome(r), 0)
        r.pop('jo_net')
        r.pop('graph_measurement')
        self.assertIsNone(d.outcome(r))
        r['games'] = 0
        self.assertIsNone(d.outcome(r))
        r = row(store='pscube:c740601:20') | {'source_site': 'anaslo'}
        self.assertIsNone(d.outcome(r))

    def test_graph_tolerance_and_my_not_net(self):
        r = row()
        r.pop('jo_net')
        r['graph_measurement']['end_y'] = 49
        self.assertIsNone(d.outcome(r))
        r.pop('graph_measurement')
        r['my'] = 10000
        self.assertIsNone(d.outcome(r))

    def training_rows(self):
        return [row(d.shift('2026-08-01', i), rack, (i + rack) % 3 == 0)
                for i in range(100) for rack in range(1, 7)]

    def test_training_all_racks_and_future_independence(self):
        rows = self.training_rows()
        before = copy.deepcopy(rows)
        model = d.train(d.History(rows), '2026-10-10')
        changed = [r | {'jo_net': 9999} if r['day'] > '2026-10-02' else r for r in rows]
        self.assertEqual(model, d.train(d.History(changed), '2026-10-10'))
        key = d.identity(rows[0])[:3]
        self.assertEqual(model[key]['n'], 62 * 6)
        self.assertEqual(rows, before)

    def test_store_isolation_and_missing_models(self):
        rows = self.training_rows()
        other = [r | {'store': 'saiwaichou', 'jo_net': 999} for r in rows]
        a = d.train(d.History(rows), '2026-11-10')
        b = d.train(d.History(rows + other), '2026-11-10')
        self.assertEqual(a[d.identity(rows[0])[:3]], b[d.identity(rows[0])[:3]])
        self.assertIsNone(d.rank_pool([row(machine='新機種')], d.History(rows), a))

    def test_machine_change_resets_history(self):
        old = row('2026-11-01')
        changed = row('2026-11-05', machine='別機種')
        new = row('2026-11-10', win=False)
        a = d.History([old, changed, new]).features(new)
        b = d.History([changed, new]).features(new)
        self.assertEqual(a, b)

    def test_exact_next_calendar_day_not_next_record(self):
        rows = [row('2026-10-01'), row('2026-10-03')]
        self.assertEqual(d.train(d.History(rows), '2026-11-10'), {})

    def test_fixed_period_adoption(self):
        days = [dict(day=d.shift('2026-01-01', i), current=.2, learned=.8,
                     missing_current=0., missing_learned=0., n_current=10, n_learned=10) for i in range(84)]
        result = d.comparison(days, .025)
        self.assertTrue(result['adopt'])
        self.assertAlmostEqual(result['p'], 1 / 4096)
        self.assertFalse(d.comparison(days[:30], .025)['adopt'])
        self.assertFalse(d.comparison([x | {'missing_learned': .1} for x in days], .025)['adopt'])
        self.assertFalse(d.comparison([x | {'learned': .2} for x in days], .025)['adopt'])

    def test_cutoff_and_immutable_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                now = datetime.fromisoformat('2026-11-11T07:59:59+09:00')
                self.assertTrue(j.freeze('2026-11-11', {'groups': []}, [row()], now))
                self.assertFalse(j.freeze('2026-11-11', {'groups': ['changed']}, [], now))
                self.assertEqual(j.get('predictions', '2026-11-11')['groups'], [])
                with self.assertRaises(sqlite3.IntegrityError):
                    j.db.execute("UPDATE predictions SET body='{}'")
                j.db.rollback()
                with self.assertRaises(ValueError):
                    j.freeze('2026-11-11', {}, [], datetime.fromisoformat('2026-11-11T08:00:00+09:00'))
                with self.assertRaises(ValueError):
                    j.freeze('2026-11-10', {}, [], now)
            finally:
                j.close()

    def test_read_only_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.db'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE days(payload TEXT)')
            db.execute('INSERT INTO days VALUES (?)', (json.dumps(row()),))
            db.commit()
            db.close()
            before = path.read_bytes()
            self.assertEqual(runtime.read_database(path, 'days'), [row()])
            self.assertEqual(path.read_bytes(), before)

    def test_baseline_same_candidates_and_pool(self):
        rows = [row(d.shift('2026-11-01', i), rack, rack % 2 == 0) for i in range(10) for rack in range(1, 9)]
        groups = runtime.baseline_groups(rows, {'records': [], 'machines': []}, '2026-11-10')
        current = runtime.core.provisional_next_day_candidates(runtime.MemoryStore(rows), '2026-11-10', '試験機')
        self.assertEqual(groups[0]['current'], [d.identity(v['row']) for v in current['candidates']])
        self.assertEqual(len(groups[0]['pool']), 8)
        self.assertEqual(len(groups[0]['current']), 2)

    def test_one_store_ready_independently(self):
        rows = [row()]
        self.assertEqual(runtime.ready(rows, '2026-11-11', ('nagamachiminami',)), [])
        self.assertTrue(runtime.ready(rows, '2026-11-11', ('saiwaichou',)))

    def test_failed_freeze_rolls_back_input(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                original = j.append
                def failing(table, key, body):
                    if table == 'predictions':
                        raise OSError('模擬保存失敗')
                    return original(table, key, body)
                with patch.object(j, 'append', side_effect=failing), self.assertRaises(OSError):
                    j.freeze('2026-11-11', {}, [row()], datetime.fromisoformat('2026-11-11T07:00:00+09:00'))
                self.assertEqual(j.db.execute('SELECT COUNT(*) FROM inputs').fetchone()[0], 0)
                self.assertEqual(j.db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0], 0)
            finally:
                j.close()

    def test_adoption_once_rollback_and_no_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            key = 'group'
            def add(first, count, learned):
                with j.db:
                    for i in range(count):
                        day = d.shift(first, i)
                        g = dict(key=key, day=day, trained=True, current=.4, learned=learned,
                                 missing_current=0., missing_learned=0., n_current=10, n_learned=10)
                        j.append('outcomes', day, {'groups': [g]})
            try:
                with j.db:
                    j.state('start', '2026-01-01')
                add('2026-01-01', 84, .8)
                now = d.shift('2026-01-01', 92)
                runtime.decisions(j, now)
                self.assertEqual(j.get('state', 'method:' + key)['active'], 'learned')
                first = j.get('decisions', 'adoption:1')
                runtime.decisions(j, now)
                self.assertEqual(j.get('decisions', 'adoption:1'), first)
                add(now, 28, .1)
                later = d.shift(now, 36)
                runtime.decisions(j, later)
                self.assertEqual(j.get('state', 'method:' + key), {'active': 'current', 'since': later})
                runtime.decisions(j, later)
                self.assertEqual(j.get('state', 'method:' + key)['active'], 'current')
            finally:
                j.close()

    def test_result_labels_keep_non_candidates_and_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                ids = [list(d.identity(row(rack=i))) for i in range(1, 5)]
                group = dict(key='group', trained=True, pool=[{'id': k} for k in ids],
                             current=ids[:2], learned=ids[2:])
                now = datetime.fromisoformat('2026-11-11T07:00:00+09:00')
                j.freeze('2026-11-11', {'groups': [group]}, [], now, store='nagamachiminami')
                rows = [row('2026-11-11', i) for i in (1, 3, 4)]
                runtime.record_outcomes(j, rows, '2026-11-18')
                self.assertIsNone(j.get('outcomes', '2026-11-11|nagamachiminami'))
                runtime.record_outcomes(j, rows, '2026-11-19')
                value = j.get('outcomes', '2026-11-11|nagamachiminami')['groups'][0]
                self.assertEqual(len(value['labels']), 4)
                self.assertEqual(value['missing_current'], .5)
                self.assertEqual(value['current'], 1)
                runtime.record_outcomes(j, [], '2026-11-20')
                self.assertEqual(j.get('outcomes', '2026-11-11|nagamachiminami')['groups'][0], value)
            finally:
                j.close()

    def test_same_day_per_store_and_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'journal.sqlite3'
            j = d.Journal(path)
            now = datetime.fromisoformat('2026-11-11T07:00:00+09:00')
            try:
                for store in runtime.STORES:
                    self.assertTrue(j.freeze('2026-11-11', {'groups': []}, [], now, store=store))
                self.assertEqual(j.db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0], 3)
            finally:
                j.close()
            j = d.Journal(path)
            try:
                self.assertFalse(j.freeze('2026-11-11', {}, [], now, store=runtime.STORES[0]))
            finally:
                j.close()


if __name__ == '__main__':
    unittest.main()
