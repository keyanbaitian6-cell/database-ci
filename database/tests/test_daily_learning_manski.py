"""日次学習 v5 の欠測の最悪・最良境界（2026-11-28 レビュー②）。

同じ判定不能の台が両方式の候補に入るとき、その台には両方式で同じ結果を置く。差が必ず0の日（候補が同じ）は 0〜0。
本番の journal.sqlite3 は開かない。一時ジャーナルと合成データだけを使う。"""
from datetime import datetime
import itertools
from pathlib import Path
import random
import tempfile
import unittest

import daily_learning as d
import daily_learning_runtime as runtime

STORE = 'nagamachiminami'


def rid(rack, machine='試験機', store=STORE):
    return [store, '', machine, rack]


def labeled(current, learned, key='["nagamachiminami","","試験機"]', method='m1', ids=True, machine='試験機'):
    """current・learned は [(台番号, 結果)]。結果は 1（プラス）・0（非プラス）・None（判定不能）。同じ台は同じ結果。"""
    labels = {}
    for rack, value in current + learned:
        labels[d.encoded(rid(rack, machine))] = value
    group = dict(key=key, trained=True, method=method)
    for name, items in (('current', current), ('learned', learned)):
        group.update(d.candidate_rates(name, [rid(r, machine) for r, _ in items], labels))
    group['labels'] = labels
    if ids:
        group['candidates'] = {name: [d.encoded(rid(r, machine)) for r, _ in items]
                               for name, items in (('current', current), ('learned', learned))}
    return group


def brute(groups):
    """判定不能の台に0・1を同じように置いた全通りの、日の差（組等重み・分母は候補数）の最小・最大。"""
    used = [g for g in groups if g['k_current'] and g['k_learned']]
    missing = sorted({k for g in used for k in g['candidates']['current'] + g['candidates']['learned']
                      if g['labels'][k] is None})
    values = []
    for choice in itertools.product((0, 1), repeat=len(missing)):
        fill = dict(zip(missing, choice))
        diffs = []
        for g in used:
            def share(name):
                ks = g['candidates'][name]
                return sum(fill[k] if g['labels'][k] is None else g['labels'][k] for k in ks) / len(ks)
            diffs.append(share('learned') - share('current'))
        values.append(sum(diffs) / len(diffs))
    return min(values), max(values)


class ManskiBoundTests(unittest.TestCase):
    def test_review_case_same_two_racks_is_zero(self):
        # レビューの再現：両方式とも同じ2台、片方プラス・片方判定不能。差は必ず0。旧式は −50〜＋50 ポイントだった。
        g = labeled([(1, 1), (2, None)], [(1, 1), (2, None)])
        day = d.store_day('2026-12-01', [g])
        self.assertEqual(day['manski'], d.MANSKI_OK)
        self.assertEqual((day['diff_manski_worst'], day['diff_manski_best']), (0., 0.))
        self.assertEqual(day['diff'], 0.)
        self.assertEqual((day['diff_nonplus'], day['diff_plus']), (0., 0.))   # 感度分析は今までどおり
        # 旧式の置き方（学習版の欠測を0・従来の欠測を1）では −0.5 になる（今回直した点）。
        self.assertAlmostEqual(d._share(g, 'learned', 0) - d._share(g, 'current', 1), -.5)

    def test_order_of_candidates_does_not_matter_for_identical_sets(self):
        g = labeled([(1, 1), (2, None), (3, 0)], [(3, 0), (2, None), (1, 1)])
        day = d.store_day('2026-12-01', [g])
        self.assertEqual((day['diff_manski_worst'], day['diff_manski_best']), (0., 0.))

    def test_partial_overlap_shares_the_missing_rack(self):
        # 2番（判定不能）は両方式に1回ずつ。従来は2台・学習版は1台なので、2番の重みは 1/1 − 1/2 = +0.5。
        g = labeled([(1, 1), (2, None)], [(2, None)])
        day = d.store_day('2026-12-01', [g])
        self.assertAlmostEqual(day['diff_manski_worst'], -.5)    # 2番を0：学習版0 − 従来0.5
        self.assertAlmostEqual(day['diff_manski_best'], 0.)      # 2番を1：学習版1 − 従来1
        self.assertEqual((day['diff_manski_worst'], day['diff_manski_best']), brute([g]))
        self.assertLessEqual(day['diff_manski_worst'], day['diff_nonplus'] + 1e-12)
        self.assertLessEqual(day['diff_plus'], day['diff_manski_best'] + 1e-12)

    def test_no_overlap_matches_old_assignment(self):
        # 候補が重ならなければ、方式ごとに逆の結果を置く旧式と同じ値になる。
        g = labeled([(1, 1), (2, None), (3, 0)], [(4, None), (5, 1)])
        day = d.store_day('2026-12-01', [g])
        self.assertAlmostEqual(day['diff_manski_worst'], d._share(g, 'learned', 0) - d._share(g, 'current', 1))
        self.assertAlmostEqual(day['diff_manski_best'], d._share(g, 'learned', 1) - d._share(g, 'current', 0))
        self.assertEqual((round(day['diff_manski_worst'], 12), round(day['diff_manski_best'], 12)),
                         tuple(round(v, 12) for v in brute([g])))

    def test_no_missing_bounds_equal_difference(self):
        g = labeled([(1, 1), (2, 0)], [(2, 0), (3, 1), (4, 1)])
        day = d.store_day('2026-12-01', [g])
        self.assertAlmostEqual(day['diff_manski_worst'], day['diff'])
        self.assertAlmostEqual(day['diff_manski_best'], day['diff'])

    def test_random_groups_match_brute_force(self):
        # 複数の組・候補数の違い・重なり・同じ台が2つの組に入る場合も、全通りの最小・最大と一致する。
        rng = random.Random(20261128)
        for _ in range(300):
            racks = list(range(1, 9))
            truth = {r: rng.choice((0, 1, None)) for r in racks}
            groups = []
            for n in range(rng.randint(1, 3)):
                cur = rng.sample(racks, rng.randint(1, 4))
                lea = rng.sample(racks, rng.randint(1, 4))
                groups.append(labeled([(r, truth[r]) for r in cur], [(r, truth[r]) for r in lea], key=f'g{n}'))
            day = d.store_day('2026-12-01', groups)
            low, high = brute(groups)
            self.assertAlmostEqual(day['diff_manski_worst'], low, places=12)
            self.assertAlmostEqual(day['diff_manski_best'], high, places=12)
            for name in ('diff_nonplus', 'diff_plus'):
                self.assertLessEqual(low, day[name] + 1e-12)
                self.assertLessEqual(day[name], high + 1e-12)

    def test_missing_ids_or_inconsistent_records_are_unrecoverable(self):
        old = labeled([(1, 1), (2, None)], [(1, 1), (2, None)], ids=False)
        day = d.store_day('2026-12-01', [old])
        self.assertEqual(day['manski'], d.MANSKI_UNRECOVERABLE)
        self.assertIsNone(day['diff_manski_worst'])
        self.assertEqual(day['diff'], 0.)                        # 差・感度分析はそのまま出る
        short = labeled([(1, 1), (2, None)], [(1, 1)])
        short['candidates']['current'] = short['candidates']['current'][:1]   # 候補数（k）と合わない
        self.assertEqual(d.store_day('2026-12-01', [short])['manski'], d.MANSKI_UNRECOVERABLE)
        absent = labeled([(1, 1)], [(1, 1)])
        absent['candidates']['learned'] = [d.encoded(rid(99))]   # 結果に無い台
        self.assertEqual(d.store_day('2026-12-01', [absent])['manski'], d.MANSKI_UNRECOVERABLE)
        clash_a = labeled([(1, 1)], [(2, 0)], key='a')
        clash_b = labeled([(1, None)], [(2, 0)], key='b')        # 同じ台に組ごとに違う結果
        self.assertEqual(d.store_day('2026-12-01', [clash_a, clash_b])['manski'], d.MANSKI_UNRECOVERABLE)
        self.assertEqual(d.store_day('2026-12-01', [])['manski'], d.MANSKI_NO_GROUPS)

    def test_comparison_hides_period_bound_when_any_day_unrecoverable(self):
        days = [d.store_day(d.shift('2026-12-01', i), [labeled([(1, 1), (2, None)], [(1, 1), (3, 0)])])
                for i in range(10)]
        result = d.comparison(days, .01)
        self.assertEqual(result['manski_unrecoverable_days'], 0)
        self.assertAlmostEqual(result['manski_worst_difference'], -.5)
        self.assertAlmostEqual(result['manski_best_difference'], 0.)
        legacy = d.store_day('2026-12-11', [labeled([(1, 1)], [(1, 1)], ids=False)])
        mixed = d.comparison(days + [legacy], .01)
        self.assertEqual(mixed['manski_unrecoverable_days'], 1)
        self.assertIsNone(mixed['manski_worst_difference'])
        self.assertIsNone(mixed['manski_best_difference'])

    def test_adoption_and_other_figures_unchanged_by_bounds(self):
        # 境界を計算できる記録と、台IDを外して計算できない記録で、採用の判定と他の値がまったく同じ。
        rng = random.Random(7)
        days, stripped = [], []
        for i in range(112):
            day = d.shift('2026-01-01', i)
            groups = []
            for n in range(3):
                truth = {r: (None if rng.random() < .03 else int(rng.random() < .5)) for r in range(1, 21)}
                cur = list(range(1, 11))
                lea = list(range(6, 16))
                for r in lea:
                    if truth[r] is not None and rng.random() < .3:
                        truth[r] = 1
                groups.append(labeled([(r, truth[r]) for r in cur], [(r, truth[r]) for r in lea], key=f'g{n}',
                                      machine=f'機種{n}'))
            days.append(d.store_day(day, groups))
            stripped.append(d.store_day(day, [{k: v for k, v in g.items() if k != 'candidates'} for g in groups]))
        a, b = d.comparison(days, .01), d.comparison(stripped, .01)
        bounds = {'manski_worst_difference', 'manski_best_difference', 'manski_unrecoverable_days'}
        self.assertEqual({k: v for k, v in a.items() if k not in bounds}, {k: v for k, v in b.items() if k not in bounds})
        self.assertIsNotNone(a['manski_worst_difference'])
        self.assertIsNone(b['manski_worst_difference'])
        self.assertEqual(d.rollback_needed(days[:28]), d.rollback_needed(stripped[:28]))


class JournalTests(unittest.TestCase):
    """一時ジャーナルで、新しい記録・旧形式の記録（予測から候補を戻す／戻せない）と判定を確かめる。"""

    def make_prediction(self, j, target, current, learned, pool_racks):
        group = dict(key='group', trained=True, pool=[{'id': rid(r)} for r in pool_racks],
                     current=[rid(r) for r in current], learned=[rid(r) for r in learned])
        now = datetime.fromisoformat(f'{target}T07:00:00+09:00')
        j.freeze(target, {'groups': [group]}, [], now, store=STORE)

    @staticmethod
    def row(day, rack, win):
        return dict(day=day, rack=rack, store=STORE, machine='試験機', games=4000, bb=20, rb=10,
                    max_hold=2000, jo_net=100 if win else -100,
                    graph_measurement=dict(baseline_y=50, end_y=25 if win else 75, peak_y=20, trough_y=80))

    def test_new_record_keeps_candidates_and_old_record_is_restored_from_prediction(self):
        target = '2026-11-11'
        key = f'{target}|{STORE}'
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                # 両方式とも1・2番。1番はプラス、2番は行が無い（判定不能）。
                self.make_prediction(j, target, [1, 2], [1, 2], [1, 2, 3])
                runtime.record_outcomes(j, [self.row(target, 1, True), self.row(target, 3, False)], '2026-11-19')
                record = j.get('outcomes', key)
                group = record['groups'][0]
                self.assertEqual(group['candidates'], {'current': [d.encoded(rid(1)), d.encoded(rid(2))],
                                                       'learned': [d.encoded(rid(1)), d.encoded(rid(2))]})
                self.assertIsNone(group['labels'][d.encoded(rid(2))])
                new = runtime.store_days(j, STORE, target, target)[0]
                self.assertEqual((new['manski'], new['diff_manski_worst'], new['diff_manski_best']), (d.MANSKI_OK, 0., 0.))
            finally:
                j.close()
            old = dict(record, groups=[{k: v for k, v in g.items() if k != 'candidates'} for g in record['groups']])

            # 旧形式（候補の台を持たない結果）。記録は追記専用なので、予測と旧形式の結果を別の一時ジャーナルに入れる。
            j = d.Journal(Path(temp) / 'old.sqlite3')
            try:
                self.make_prediction(j, target, [1, 2], [1, 2], [1, 2, 3])
                with j.db:
                    j.append('outcomes', key, old)
                before = j.db.execute('SELECT body, sha FROM outcomes WHERE key=?', (key,)).fetchone()
                restored = runtime.store_days(j, STORE, target, target)[0]
                self.assertEqual({k: v for k, v in restored.items() if k != 'method'},
                                 {k: v for k, v in new.items() if k != 'method'})
                # 読むだけで、記録は書き換えない。
                self.assertEqual(j.db.execute('SELECT body, sha FROM outcomes WHERE key=?', (key,)).fetchone(), before)
                self.assertNotIn('candidates', j.get('outcomes', key)['groups'][0])
            finally:
                j.close()

            # 予測が無い旧形式は、再計算不能と分かる（差・感度分析はそのまま）。
            j = d.Journal(Path(temp) / 'lost.sqlite3')
            try:
                with j.db:
                    j.append('outcomes', key, old)
                lost = runtime.store_days(j, STORE, target, target)
                self.assertEqual(lost[0]['manski'], d.MANSKI_UNRECOVERABLE)
                self.assertIsNone(lost[0]['diff_manski_worst'])
                self.assertEqual(lost[0]['diff'], new['diff'])
                self.assertEqual(lost[0]['diff_nonplus'], new['diff_nonplus'])
                result = d.comparison(lost, .01)
                self.assertEqual(result['manski_unrecoverable_days'], 1)
                self.assertIsNone(result['manski_best_difference'])
            finally:
                j.close()

            # 予測はあっても組の鍵が合わない旧形式も、再計算不能。
            j = d.Journal(Path(temp) / 'other.sqlite3')
            try:
                self.make_prediction(j, target, [1, 2], [1, 2], [1, 2, 3])
                with j.db:
                    j.append('outcomes', key, dict(old, groups=[{**g, 'key': 'other'} for g in old['groups']]))
                self.assertEqual(runtime.store_days(j, STORE, target, target)[0]['manski'], d.MANSKI_UNRECOVERABLE)
            finally:
                j.close()

    def test_old_record_partial_overlap_restored_from_prediction(self):
        # 旧形式で候補が一部だけ重なる日も、予測から戻した台で新しい記録と同じ境界になる。
        target = '2026-11-12'
        key = f'{target}|{STORE}'
        rows = [self.row(target, 1, True), self.row(target, 3, False)]
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                self.make_prediction(j, target, [1, 2], [2, 3], [1, 2, 3])
                runtime.record_outcomes(j, rows, '2026-11-20')
                record = j.get('outcomes', key)
                new = runtime.store_days(j, STORE, target, target)[0]
            finally:
                j.close()
            # 2番（判定不能）は両方式に1回ずつで重み0。1番（プラス）は従来だけ、3番（非プラス）は学習版だけ。
            self.assertEqual((new['diff_manski_worst'], new['diff_manski_best']), (-.5, -.5))
            j = d.Journal(Path(temp) / 'old.sqlite3')
            try:
                self.make_prediction(j, target, [1, 2], [2, 3], [1, 2, 3])
                with j.db:
                    j.append('outcomes', key, dict(record, groups=[{k: v for k, v in g.items() if k != 'candidates'}
                                                                   for g in record['groups']]))
                old = runtime.store_days(j, STORE, target, target)[0]
                self.assertEqual({k: v for k, v in old.items() if k != 'method'},
                                 {k: v for k, v in new.items() if k != 'method'})
            finally:
                j.close()

    def test_decisions_adopt_the_same_with_or_without_candidates(self):
        # 自動採用の判定（decisions）は、境界を計算できる記録でも、旧形式（計算できない）でも同じ。
        def run(with_ids):
            with tempfile.TemporaryDirectory() as temp:
                j = d.Journal(Path(temp) / 'journal.sqlite3')
                try:
                    rng = random.Random(11)
                    with j.db:
                        j.state('start', '2026-01-01')
                        for i in range(112):
                            day = d.shift('2026-01-01', i)
                            groups = []
                            for n in range(3):
                                truth = {r: (None if rng.random() < .01 else int(rng.random() < .3)) for r in range(1, 21)}
                                for r in range(11, 21):
                                    if truth[r] is not None and rng.random() < .6:
                                        truth[r] = 1
                                groups.append(labeled([(r, truth[r]) for r in range(1, 11)],
                                                      [(r, truth[r]) for r in range(8, 18)],
                                                      key=f'["{STORE}","","機種{n}"]', ids=with_ids,
                                                      machine=f'機種{n}'))
                            j.append('outcomes', f'{day}|{STORE}', dict(target=day, store=STORE, groups=groups))
                    runtime.decisions(j, d.shift('2026-01-01', 120))
                    return j.get('decisions', 'adoption:1')['results'][STORE], j.get('state', 'store:' + STORE)
                finally:
                    j.close()
        (a, state_a), (b, state_b) = run(True), run(False)
        bounds = {'manski_worst_difference', 'manski_best_difference', 'manski_unrecoverable_days'}
        self.assertTrue(a['adopt'])
        self.assertEqual({k: v for k, v in a.items() if k not in bounds}, {k: v for k, v in b.items() if k not in bounds})
        self.assertEqual(state_a, state_b)
        self.assertEqual(state_a['active'], 'learned')
        self.assertLessEqual(a['manski_worst_difference'], a['nonplus_difference'] + 1e-12)
        self.assertLessEqual(a['plus_difference'], a['manski_best_difference'] + 1e-12)
        self.assertEqual(b['manski_unrecoverable_days'], 112)


if __name__ == '__main__':
    unittest.main()
