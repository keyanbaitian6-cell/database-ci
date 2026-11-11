"""日次学習で、P-STATIONの名前の変わり目を同じ機種として数える（2026-11-12 利用者「vivy同じものとして数えて」）。"""
import unittest

import daily_learning as d
from daily_learning_names import PSCUBE_RENAMES, learning_machine

PS = 'pscube:c740601:20'
OLD, NEW = 'L Vivy', 'L Vivy -Fluorite Eye’s Song-'


def row(day, rack, machine, store=PS, win=True):
    return dict(day=day, rack=rack, store=store, rate='20' if store == PS else '', machine=machine,
                games=4000, bb=20, rb=10, jo_net=100 if win else -100)


def days(first, n):
    return [d.shift(first, i) for i in range(n)]


class LearningNameTests(unittest.TestCase):
    def test_only_pstation_renames_and_star_stays_separate(self):
        self.assertEqual(learning_machine(PS, OLD), NEW)
        self.assertEqual(learning_machine(PS, 'ﾏｲｼﾞｬｸﾞﾗｰVI'), 'SマイジャグラーVI')
        self.assertEqual(learning_machine(PS, 'ﾏｲｼﾞｬｸﾞﾗｰV'), 'ﾏｲｼﾞｬｸﾞﾗｰV')          # 名前の変わらなかった機種
        self.assertEqual(learning_machine('saiwaichou', OLD), OLD)                     # 長町南・幸町には当てない
        # ★はバラエティの別の台（2026-11-12 利用者「違うものとしよう」）。外さない。
        self.assertEqual(learning_machine('saiwaichou', '★L東京喰種CT'), '★L東京喰種CT')
        self.assertEqual(len(PSCUBE_RENAMES), 16)
        self.assertFalse(set(PSCUBE_RENAMES) & set(PSCUBE_RENAMES.values()))            # 1回で新しい名前になる

    def test_renamed_racks_share_history_outcomes_and_model(self):
        # 11/6 に名前が変わった2台。古い名前の日の結果と、変わり目の翌日の結果も学習に入る。
        rows = []
        for i, day in enumerate(days('2026-09-01', 70)):
            for rack in (1213, 1215):
                rows.append(row(day, rack, OLD if day < '2026-11-06' else NEW, win=(i + rack) % 3 != 0))
        history = d.History(rows)
        last_old = next(r for r in history.rows if r['day'] == '2026-11-05' and r['rack'] == 1213)
        self.assertIsNotNone(history.get('2026-11-06', d.identity(last_old)))         # 変わり目をまたいで翌日の結果を引ける
        today = next(r for r in history.rows if r['day'] == '2026-11-09' and r['rack'] == 1213)
        x = dict(zip(d.FEATURES, history.features(today)))
        self.assertEqual(x['coverage28'], 1.0)                                          # 名前の変わり目で過去が途切れない
        models = d.train(history, '2026-11-16')
        self.assertEqual(list(models), [(PS, '20', NEW)])
        # 9/2〜11/8 の結果の68日。古い名前の日と、変わり目（11/5の台→11/6の結果）を含む。分かれていたら新しい名前は2日だけ。
        self.assertEqual(models[(PS, '20', NEW)]['days'], 68)
        pool = [r for r in history.rows if r['day'] == '2026-11-09']
        self.assertEqual(len(d.rank_pool(pool, history, models)), 2)

    def test_real_machine_change_still_restarts_history(self):
        # 名前の表に無い入れ替え（別の機種）は、今までどおり別の機種として数え直す。
        rows = [row(day, 1, 'L東京喰種' if day < '2026-11-06' else NEW) for day in days('2026-10-20', 20)]
        history = d.History(rows)
        today = next(r for r in history.rows if r['day'] == '2026-11-08')
        x = dict(zip(d.FEATURES, history.features(today)))
        self.assertAlmostEqual(x['coverage28'], 3 / 28)
        self.assertIsNone(history.get('2026-11-06', ('pscube:c740601:20', '20', 'L東京喰種', 1)))

    def test_same_day_under_both_names_keeps_new_name_and_exact_duplicates_still_fail(self):
        rows = [row('2026-11-05', 1213, OLD, win=False), row('2026-11-05', 1213, NEW, win=True)]
        for order in (rows, rows[::-1]):
            history = d.History(order)
            kept = history.get('2026-11-05', (PS, '20', OLD, 1213))
            self.assertEqual(kept['machine'], NEW)
            self.assertEqual(len(history.by_id[(PS, '20', NEW, 1213)]), 1)
        with self.assertRaises(ValueError):
            d.History([row('2026-11-05', 1213, NEW), row('2026-11-05', 1213, NEW)])


if __name__ == '__main__':
    unittest.main()
