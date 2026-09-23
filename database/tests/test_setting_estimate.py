import unittest

from setting_estimate import candidate_label, estimate_setting, model_for_machine


class SettingEstimateTests(unittest.TestCase):
    def test_saved_machine_names_match_distinct_manufacturer_tables(self):
        names = {
            'SマイジャグラーVKD': 'my_juggler_v',
            'SネオアイムジャグラーEX−KK': 'neo_im_juggler',
            'Sハナハナホウオウ〜天翔〜EX−30': 'houou_tensho',
            'SキングハナハナSP−30': 'king_2023',
            'SｷﾝｸﾞﾊﾅﾊﾅSP-30': 'king_2023',
            'SBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅVPA-30': 'new_king_v',
            'Sドラゴンハナハナ〜閃光〜SP−30': 'dragon_senko',
        }
        for name, expected in names.items():
            with self.subTest(name=name):
                self.assertEqual(model_for_machine(name), expected)
        self.assertIsNone(model_for_machine('アイムジャグラーEX'))
        self.assertIsNone(model_for_machine('マイジャグラーⅥ'))
        self.assertIsNone(model_for_machine('キングハナハナ-30'))
        self.assertIsNone(model_for_machine('SBニューキングハナハナVIPA-30'))
        self.assertIsNone(model_for_machine('SマイジャグラーVXKD'))
        self.assertIsNone(model_for_machine('SネオアイムジャグラーEX2−KK'))

    def test_bb_rb_are_separate_and_low_games_show_uncertainty(self):
        row = {'machine': 'SマイジャグラーVKD', 'games': 10000, 'bb': 44, 'rb': 43}
        high = estimate_setting(row)
        self.assertEqual(high['setting'], '6')
        self.assertEqual(high['support'], 51.2)
        self.assertEqual(high['range80'], ['4', '5', '6'])
        self.assertIn('6', high['range80'])
        self.assertEqual(candidate_label(high), 'BB/RB候補 4・5・6')
        low = estimate_setting({**row, 'games': 100, 'bb': 0, 'rb': 0})
        self.assertGreater(len(low['range80']), len(high['range80']))
        self.assertEqual(low['range80'], ['1', '2', '3', '4', '5', '6'])
        self.assertEqual(candidate_label(low), 'BB/RBでは絞り込めず')
        self.assertNotEqual(
            estimate_setting({**row, 'bb': 44, 'rb': 20})['support'],
            high['support'],
        )

    def test_setting_v_and_invalid_values(self):
        row = {'machine': 'SBニューキングハナハナVPA−30', 'games': 20000,
               'bb': 79, 'rb': 54, 'confirmed_setting': '6'}
        estimate = estimate_setting(row)
        self.assertEqual(estimate['setting'], 'V')
        self.assertEqual(estimate['support'], 46.9)
        self.assertEqual(estimate['range80'], ['3', '4', 'V'])
        self.assertEqual(candidate_label(estimate), 'BB/RB候補 3・4・V')
        self.assertEqual(row['confirmed_setting'], '6')
        self.assertIsNone(estimate_setting({**row, 'games': 0}))
        self.assertIsNone(estimate_setting({**row, 'games': 10}))
        self.assertIsNone(estimate_setting({**row, 'bb': -1}))


if __name__ == '__main__':
    unittest.main()
