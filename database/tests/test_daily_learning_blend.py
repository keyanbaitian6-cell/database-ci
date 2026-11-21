"""幸町の学習版（2026-11-21）：店舗共通の点と機種専用の点を、専用係数の学習量で混ぜる。
式は ../outputs/daily-blend-20261121/計画.md で結果を見る前に固定した。ほかの店舗・バラエティは変えない。"""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import daily_learning as d
import daily_learning_fixed as fixed
import daily_learning_runtime as runtime

SAI, NAGA = 'saiwaichou', 'nagamachiminami'
INPUT_DAY, TARGET = '2026-11-09', '2026-11-10'


def row(day, rack, machine, win=True, store=SAI, games=4000):
    return dict(day=day, rack=rack, store=store, machine=machine, games=games, bb=20, rb=10, max_hold=2000,
                jo_net=100 if win else -100,
                graph_measurement=dict(baseline_y=50, end_y=25 if win else 75, peak_y=20, trough_y=80))


def win(i, rack):
    return (i * 7 + rack * 3) % 5 < 2


def store_rows(store=SAI):
    """2026-08-01〜11-09。機種A（6台）、11/5に入れ替えた新台N（4台）、バラエティV1（1台）・V2（2台）。"""
    rows = []
    for i in range(101):
        day = d.shift('2026-08-01', i)
        rows += [row(day, rack, 'A', win(i, rack), store) for rack in range(1, 7)]
        rows += [row(day, rack, 'Old' if day < '2026-11-05' else 'N', win(i, rack), store) for rack in range(101, 105)]
        rows += [row(day, 201, 'V1', win(i, 201), store)] + [row(day, r, 'V2', win(i, r), store) for r in (202, 203)]
    return rows


def groups_of(rows, store=SAI):
    daily = [r for r in rows if r['day'] == INPUT_DAY and r['store'] == store]
    pick = lambda names: [r for r in daily if r['machine'] in names]
    return [dict(store=store, rate='', name='A', pool=pick(('A',)), current=[d.identity(r) for r in pick(('A',))][:2]),
            dict(store=store, rate='', name='N', pool=pick(('N',)), current=[d.identity(r) for r in pick(('N',))][:1]),
            dict(store=store, rate='', name='バラエティ', pool=pick(('V1', 'V2')), current=[d.identity(pick(('V1',))[0])])]


class NoState:
    @staticmethod
    def get(table, key):
        return None


class WeightTests(unittest.TestCase):
    def test_weight_follows_the_fixed_formula(self):
        self.assertEqual(d.mix_weight(None), 0.)
        self.assertEqual(d.mix_weight(dict(n=100, days=20)), .5)                 # 今の下限ちょうどで半々
        self.assertAlmostEqual(d.mix_weight(dict(n=400, days=40)), 40 / 60)      # 日数の少ないほうで決まる
        self.assertAlmostEqual(d.mix_weight(dict(n=120, days=180)), 120 / 220)   # 件数の少ないほうで決まる
        self.assertAlmostEqual(d.mix_weight(dict(n=3600, days=180)), .9)

    def test_scores_are_mixed_not_coefficients_and_ties_keep_rack_order(self):
        rows = [row(INPUT_DAY, r, 'A', games=g) for r, g in ((1, 1000), (2, 3000), (3, 2000))]
        h = d.History(rows)
        common = dict(weights=[0.] * 7 + [1.] + [0.] * 4)            # 回転数が多いほど上（12個の特徴）
        own = dict(weights=[0.] * 7 + [-1.] + [0.] * 2, n=100, days=20)  # 回転数が少ないほど上（10個）
        only_common = {(SAI, '', d.STORE_MODEL): common}
        self.assertEqual([r['rack'] for r in d.rank_blend(rows, h, only_common, SAI)], [2, 3, 1])
        # w=0.5 で点が打ち消し合い全台同点 → 台の識別子の順（rank_pool と同じ決まり）
        both = only_common | {(SAI, '', 'A'): own}
        self.assertEqual([r['rack'] for r in d.rank_blend(rows, h, both, SAI)], [1, 2, 3])
        stronger = only_common | {(SAI, '', 'A'): own | dict(n=900, days=180)}
        self.assertEqual([r['rack'] for r in d.rank_blend(rows, h, stronger, SAI)], [1, 3, 2])
        self.assertIsNone(d.rank_blend(rows, h, {(SAI, '', 'A'): own}, SAI))
        self.assertEqual(d.blend_weights(rows, both, SAI), {'A': .5})
        self.assertEqual(len(h.model_features(rows[0], 'blend')), 12)
        self.assertEqual(h.model_features(rows[0], 'blend'), h.model_features(rows[0], 'store'))


class RuntimeTests(unittest.TestCase):
    def build(self, rows, store=SAI, models=None):
        groups = groups_of(rows, store)
        with patch.object(runtime, 'baseline_groups', return_value=groups):
            if models is None:
                return runtime.build_prediction(rows, {'records': [], 'machines': []}, TARGET, NoState()), groups
            with patch.object(runtime, 'train', return_value=models):
                return runtime.build_prediction(rows, {'records': [], 'machines': []}, TARGET, NoState()), groups

    def test_saiwaichou_uses_blend_except_variety(self):
        rows = store_rows()
        prediction, groups = self.build(rows)
        by = {g['name']: g for g in prediction['groups']}
        self.assertEqual({n: g['model'] for n, g in by.items()}, {'A': 'blend', 'N': 'blend', 'バラエティ': 'variety'})
        history = d.History(rows)
        models = d.train(history, TARGET)
        self.assertIn((SAI, '', 'A'), models)
        self.assertNotIn((SAI, '', 'N'), models)      # 新台は専用係数がまだ無い → 共通だけ（w=0）
        self.assertEqual(by['N']['mix'], {'N': 0.})
        self.assertEqual(by['A']['mix'], {'A': d.mix_weight(models[(SAI, '', 'A')])})
        self.assertNotIn('mix', by['バラエティ'])
        expected = d.rank_blend(groups[0]['pool'], history, models, SAI)
        self.assertEqual(by['A']['learned'], [list(d.identity(r)) for r in expected[:2]])
        common = d.rank_by(groups[1]['pool'], history, models[(SAI, '', d.STORE_MODEL)], 'store')
        self.assertEqual(by['N']['learned'], [list(d.identity(common[0]))])
        variety = d.rank_by(groups[2]['pool'], history, models[(SAI, '', d.VARIETY_MODEL)], 'variety')
        self.assertEqual(by['バラエティ']['learned'], [list(d.identity(variety[0]))])
        self.assertEqual({n: len(g['pool'][0]['features']) for n, g in by.items()}, {'A': 12, 'N': 12, 'バラエティ': 11})
        # 採用前なので画面の候補は従来のまま
        self.assertTrue(all(g['selected'] == g['current'] and g['active'] == 'current' for g in prediction['groups']))

    def test_other_store_is_unchanged(self):
        rows = store_rows(NAGA)
        prediction, groups = self.build(rows, NAGA)
        by = {g['name']: g for g in prediction['groups']}
        self.assertEqual({n: g['model'] for n, g in by.items()}, {'A': 'machine', 'N': 'store', 'バラエティ': 'variety'})
        self.assertTrue(all('mix' not in g for g in prediction['groups']))
        self.assertNotIn(d.BLEND_VERSION, prediction['methods'][NAGA])
        self.assertEqual(runtime.method_signature(NAGA).split('|')[0], d.VERSION)
        # P-STATIONは混合を使わない。版の印は分析用JSONのゼロ線の修正（2026-11-21）だけ。
        self.assertEqual(runtime.method_signature('pscube:c740601:20').split('|')[0],
                         d.VERSION + '+' + runtime.daily_learning_archive.ZERO_FIX)
        self.assertEqual(runtime.method_signature(SAI).split('|')[0], d.VERSION + '+' + d.BLEND_VERSION)
        # 従来候補の版の部分（「|」より後ろ）は今までと同じ
        with patch.object(d, 'BLEND_STORES', ()), patch.object(runtime, 'BLEND_STORES', ()):
            before = runtime.method_signature(SAI)
        self.assertEqual(runtime.method_signature(SAI).split('|')[1:], before.split('|')[1:])
        self.assertEqual(before.split('|')[0], d.VERSION)

    def test_shortage_without_common_model_falls_back_and_without_models_keeps_current(self):
        rows = store_rows()
        models = d.train(d.History(rows), TARGET)
        no_common = {k: v for k, v in models.items() if k[2] != d.STORE_MODEL}
        prediction, _ = self.build(rows, models=no_common)
        by = {g['name']: g for g in prediction['groups']}
        self.assertEqual((by['A']['model'], by['N']['model']), ('machine', None))     # Aは専用だけ、Nは順位なし
        self.assertEqual(by['N']['learned'], by['N']['current'])
        prediction, _ = self.build(rows, models={})
        self.assertTrue(all(not g['trained'] and g['learned'] == g['current'] for g in prediction['groups']))

    def test_repeat_freeze_and_old_records_stay_apart(self):
        rows = store_rows()
        prediction, _ = self.build(rows)
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                now = datetime.fromisoformat(TARGET + 'T07:00:00+09:00')
                self.assertTrue(j.freeze(TARGET, prediction, rows, now, store=SAI))
                self.assertFalse(j.freeze(TARGET, prediction, rows, now, store=SAI))
                saved = j.get('predictions', TARGET + '|' + SAI)
                self.assertEqual(saved['groups'], prediction['groups'])
                # 旧方式の日と新方式の日：判定は期間の最後の版の日だけ（旧方式の成績と混ざらない）。
                old = dict(day='2026-11-20', method=d.VERSION + '|x', diff=.1)
                new = dict(day='2026-11-22', method=runtime.method_signature(SAI), diff=-.1)
                method, used = runtime.latest_method([old, new])
                self.assertEqual((method, used), (new['method'], [new]))
            finally:
                j.close()


class FixedControlTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.j = d.Journal(Path(folder.name) / 'journal.sqlite3')
        self.addCleanup(self.j.close)

    def emit(self, target, models, method='blend-v'):
        rows = [row(d.shift(target, -1), rack, m, games=g)
                for rack, m, g in ((1, 'A', 1000), (2, 'A', 3000), (3, 'A', 2000), (11, '新', 1000), (12, '新', 3000))]
        groups = [dict(store=SAI, rate='', name='A', pool=rows[:3], current=[d.identity(rows[0])]),
                  dict(store=SAI, rate='', name='新', pool=rows[3:], current=[d.identity(rows[3])])]
        with (patch.object(runtime, 'baseline_groups', return_value=groups),
              patch.object(runtime, 'train', return_value=models),
              patch.object(runtime, 'method_signature', return_value=method)):
            p = runtime.build_prediction(rows, {}, target, self.j)
        self.j.freeze(target, p, rows, datetime.fromisoformat(target + 'T07:59:00+09:00'), store=SAI)
        return self.j.get('predictions', target + '|' + SAI)

    def test_anchor_new_machine_and_version_change(self):
        common = dict(weights=[0.] * 7 + [1.] + [0.] * 4)
        first = self.emit(fixed.FIRST, {(SAI, '', d.STORE_MODEL): common,
                                        (SAI, '', 'A'): dict(weights=[0.] * 7 + [-1.] + [0.] * 2, n=900, days=180)})
        pairs = first[fixed.STUDY]['pairs']
        self.assertTrue(all(p['kind'] == 'blend' and p['fixed'] == p['updated'] for p in pairs.values()))
        # 2日目：Aの専用係数が逆向きに更新され、新台にも専用係数ができた（w=0.5）。
        later = {(SAI, '', d.STORE_MODEL): common,
                 (SAI, '', 'A'): dict(weights=[0.] * 7 + [1.] + [0.] * 2, n=900, days=180),
                 (SAI, '', '新'): dict(weights=[0.] * 7 + [-3.] + [0.] * 2, n=100, days=20)}
        second = self.emit(d.shift(fixed.FIRST, 1), later)
        by = {g['name']: g for g in second['groups']}
        pairs = second[fixed.STUDY]['pairs']
        self.assertEqual(second[fixed.STUDY]['anchor'], fixed.FIRST)
        a, new = pairs[by['A']['key']], pairs[by['新']['key']]
        self.assertEqual((a['fixed'][0][-1], a['updated'][0][-1]), (1, 2))   # 固定は開始日の係数のまま
        # 新台：固定版は開始日の混合比（専用係数なし → w=0、共通だけ）、更新版はその日の混合（w=0.5）。
        self.assertEqual(by['新']['mix'], {'新': .5})
        self.assertEqual((new['fixed'][0][-1], new['updated'][0][-1]), (12, 11))
        self.assertEqual(new['updated'], by['新']['learned'])
        changed = self.emit(d.shift(fixed.FIRST, 2), later, method='other')[fixed.STUDY]
        self.assertEqual(changed['reason'], '開始時と方式の版が異なる')


if __name__ == '__main__':
    unittest.main()
