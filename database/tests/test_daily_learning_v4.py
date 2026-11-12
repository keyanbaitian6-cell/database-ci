"""日次学習 v4（2026-11-12 夜）：新台は店舗共通の係数、バラエティはバラエティ専用の係数で学習版の順位を付ける。
機種ごとの係数・特徴は v3 と同じ。"""
import unittest
from unittest.mock import patch

import daily_learning as d
import daily_learning_runtime as runtime

STORE = 'nagamachiminami'
INPUT_DAY, TARGET = '2026-11-09', '2026-11-10'


def row(day, rack, machine, win=True, store=STORE, **extra):
    r = dict(day=day, rack=rack, store=store, machine=machine, games=4000, bb=20, rb=10, max_hold=2000,
             jo_net=100 if win else -100,
             graph_measurement=dict(baseline_y=50, end_y=25 if win else 75, peak_y=20, trough_y=80))
    if win is None:                                  # 判定できない日（差枚もグラフも無い）
        r.pop('jo_net')
        r.pop('graph_measurement')
    return r | extra


def win(i, rack):
    return (i * 7 + rack * 3) % 5 < 2


def store_rows():
    """2026-08-01〜11-09。機種A（6台）、11/5に機種Oldから入れ替えた新台N（4台）、バラエティV1（1台）・V2（2台）。"""
    rows = []
    for i in range(101):
        day = d.shift('2026-08-01', i)
        rows += [row(day, rack, 'A', win(i, rack)) for rack in range(1, 7)]
        rows += [row(day, rack, 'Old' if day < '2026-11-05' else 'N', win(i, rack)) for rack in range(101, 105)]
        rows += [row(day, 201, 'V1', win(i, 201))] + [row(day, rack, 'V2', win(i, rack)) for rack in (202, 203)]
    return rows


class FeatureTests(unittest.TestCase):
    def test_dry_streak_counts_judged_nonplus_days_back_to_last_plus(self):
        rows = [row('2026-11-01', 1, 'V', True), row('2026-11-02', 1, 'V', False), row('2026-11-03', 1, 'V', None),
                row('2026-11-04', 1, 'V', False)]
        history = d.History(rows)
        self.assertEqual(history.extras(rows[-1], 'variety'), [2 / 28])     # 判定できない11/3は飛ばす
        self.assertEqual(history.extras(rows[0], 'variety'), [0.])
        # 機種が替わったら数え直す。
        changed = rows + [row('2026-11-05', 1, '別機種', False)]
        self.assertEqual(d.History(changed).extras(changed[-1], 'variety'), [1 / 28])

    def test_fresh_marks_days_since_the_machine_came_in(self):
        rows = [row(d.shift('2026-10-01', i), 1, 'Old' if i < 10 else 'N') for i in range(40)]
        history = d.History(rows)
        by_day = {r['day']: r for r in rows}
        self.assertEqual(history.extras(by_day['2026-10-11'], 'store'), [1., 0.])    # 入った日＝1日目
        self.assertEqual(history.extras(by_day['2026-10-17'], 'store'), [1., 0.])    # 7日目
        self.assertEqual(history.extras(by_day['2026-10-18'], 'store'), [0., 1.])    # 8日目
        self.assertEqual(history.extras(by_day['2026-11-07'], 'store'), [0., 1.])    # 28日目
        self.assertEqual(history.extras(by_day['2026-11-08'], 'store'), [0., 0.])    # 29日目
        self.assertEqual(history.extras(by_day['2026-10-05'], 'store'), [0., 0.])    # データの初めより前からの台

    def test_machine_features_unchanged(self):
        rows = store_rows()
        history = d.History(rows)
        for r in rows[-20:]:
            self.assertEqual(history.model_features(r), history.features(r))
            self.assertEqual(history.features(r), history._features_by_scan(r))


class TrainTests(unittest.TestCase):
    def test_variety_rows_follow_store_limits_and_skip_archive(self):
        rows = [row('2026-11-01', 1, 'X'), row('2026-11-01', 2, 'X'), row('2026-11-01', 3, 'X'),
                row('2026-11-01', 1, 'X', store='saiwaichou'), row('2026-11-01', 2, 'X', store='saiwaichou'),
                row('2026-11-01', 3, 'X', store='saiwaichou'), row('2026-11-01', 4, 'Y', store='saiwaichou'),
                row('2026-11-01', 5, 'Z', store='saiwaichou', archive='normal-analysis'),
                row('2026-11-01', 1, 'P', store='pscube:c740601:20', rate='20')]
        found = d.variety_rows(rows)
        self.assertEqual([r['rack'] for r in rows if id(r) in found and r['store'] == STORE], [1, 2, 3])   # 長町南は3台まで
        self.assertEqual([r['machine'] for r in rows if id(r) in found and r['store'] == 'saiwaichou'], ['Y'])  # 幸町は2台まで
        self.assertFalse(any(r['store'].startswith('pscube:') for r in rows if id(r) in found))

    def test_machine_models_do_not_depend_on_new_models(self):
        rows = store_rows()
        models = d.train(d.History(rows), TARGET)
        alone = d.train(d.History([r for r in rows if r['machine'] == 'A']), TARGET)
        for key in ('weights', 'n', 'days', 'first', 'last', 'features'):
            self.assertEqual(models[(STORE, '', 'A')][key], alone[(STORE, '', 'A')][key])
        self.assertEqual(models[(STORE, '', 'A')]['kind'], 'machine')
        self.assertEqual(models[(STORE, '', d.STORE_MODEL)]['features'], d.STORE_FEATURES)
        self.assertEqual(models[(STORE, '', d.VARIETY_MODEL)]['features'], d.VARIETY_FEATURES)
        self.assertNotIn((STORE, '', 'N'), models)                       # 新台はまだ自分の係数が無い
        # バラエティの係数は V1・V2 の行だけ（93日分の結果 × 3台）。
        self.assertEqual(models[(STORE, '', d.VARIETY_MODEL)]['n'], 3 * 93)

    def test_too_few_rows_make_no_new_models(self):
        rows = [r for r in store_rows() if r['day'] >= '2026-10-25']
        models = d.train(d.History(rows), TARGET)
        self.assertEqual(models, {})


class PredictionTests(unittest.TestCase):
    def test_groups_get_the_right_model(self):
        rows = store_rows()
        daily = [r for r in rows if r['day'] == INPUT_DAY]
        groups = [dict(store=STORE, rate='', name='A', pool=[r for r in daily if r['machine'] == 'A'],
                       current=[d.identity(r) for r in daily if r['machine'] == 'A'][:2]),
                  dict(store=STORE, rate='', name='N', pool=[r for r in daily if r['machine'] == 'N'],
                       current=[d.identity(r) for r in daily if r['machine'] == 'N'][:1]),
                  dict(store=STORE, rate='', name='バラエティ', pool=[r for r in daily if r['machine'] in ('V1', 'V2')],
                       current=[d.identity(r) for r in daily if r['machine'] == 'V1'])]

        class Journal:
            @staticmethod
            def get(table, key):
                return None

        with patch.object(runtime, 'baseline_groups', return_value=groups):
            prediction = runtime.build_prediction(rows, {'records': [], 'machines': []}, TARGET, Journal())
        by_name = {g['name']: g for g in prediction['groups']}
        self.assertEqual({n: (g['trained'], g['model']) for n, g in by_name.items()},
                         {'A': (True, 'machine'), 'N': (True, 'store'), 'バラエティ': (True, 'variety')})
        self.assertEqual({n: len(g['pool'][0]['features']) for n, g in by_name.items()}, {'A': 10, 'N': 12, 'バラエティ': 11})
        history, models = d.History(rows), d.train(d.History(rows), TARGET)
        self.assertEqual(by_name['A']['learned'], [list(d.identity(r)) for r in d.rank_pool(groups[0]['pool'], history, models)[:2]])
        # バラエティは、機種ごとの係数（V2にはある）を使わず、バラエティ専用の係数だけで並べる。
        self.assertIn((STORE, '', 'V2'), models)
        expected = d.rank_by(groups[2]['pool'], history, models[(STORE, '', d.VARIETY_MODEL)], 'variety')
        self.assertEqual(by_name['バラエティ']['learned'], [list(d.identity(expected[0]))])
        # 採用前なので、画面に出す候補（selected）は従来のまま。
        self.assertTrue(all(g['active'] == 'current' and g['selected'] == g['current'] for g in prediction['groups']))
        self.assertTrue(all(g['status'] == '学習済み・将来成績を比較中' for g in prediction['groups']))


if __name__ == '__main__':
    unittest.main()
