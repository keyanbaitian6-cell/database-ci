"""database/daily_learning_pscube.mjs の入出力JSON契約を合成データで確かめる試験（実成績は開かない）。"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import daily_learning_runtime as runtime  # noqa: E402

SCRIPT = HERE / 'daily_learning_pscube.mjs'


def synthetic_data():
    """ノーマル機1種・AT機1種（各5台×5日）の合成P-STATIONデータ。"""
    machines = [
        {'store': 'c740601', 'rate': '20', 'machine': 'マイジャグラーV', 'machine_type': 'normal'},
        {'store': 'c740601', 'rate': '20', 'machine': 'テストAT機', 'machine_type': 'other'},
        {'store': 'c740601', 'rate': '20', 'machine': '少数テスト機', 'machine_type': 'other'},
    ]
    days = ['2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05']
    records = []
    for day in days:
        for i, rack in enumerate((101, 102, 103, 104, 105)):
            records.append({
                'store': 'c740601', 'rate': '20', 'machine': 'マイジャグラーV',
                'day': day, 'rack': rack, 'games': 4000,
                'bb': 10 + i * 3, 'rb': 8 + i * 2, 'my': 1000 + i * 400,
                'graph': {'zero_y': 100, 'points': [[0, 100], [50, 60], [100, 70]]},
            })
        for i, rack in enumerate((201, 202, 203, 204, 205)):
            records.append({
                'store': 'c740601', 'rate': '20', 'machine': 'テストAT機',
                'day': day, 'rack': rack, 'games': 4000,
                'bb': 5, 'rb': 5, 'my': 1000 + i * 800,
                'graph': {'zero_y': 100, 'points': [[0, 100], [50, 50], [100, 60]]},
            })
        # 2台しかない機種は候補条件（4台以上）を満たさず出力から省かれる
        for rack in (301, 302):
            records.append({
                'store': 'c740601', 'rate': '20', 'machine': '少数テスト機',
                'day': day, 'rack': rack, 'games': 4000, 'bb': 10, 'rb': 10, 'my': 2000,
            })
    return {'machines': machines, 'records': records}, days[-1]


class DailyLearningPscubeBridgeTest(unittest.TestCase):
    def test_script_returns_expected_json_shape_for_synthetic_data(self):
        node = runtime.resolve_node()
        if not node:
            self.skipTest('node が見つからない環境です')
        data, day = synthetic_data()
        proc = subprocess.run(
            [node, str(SCRIPT)],
            input=json.dumps({'data': data, 'day': day}, ensure_ascii=False),
            capture_output=True, text=True, encoding='utf-8', check=False, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        groups = json.loads(proc.stdout)
        self.assertIsInstance(groups, list)
        self.assertEqual(len(groups), 2, '4台以上の2機種だけが返る')
        by_name = {g['name']: g for g in groups}
        self.assertEqual(set(by_name), {'マイジャグラーV', 'テストAT機'})
        for name, expected_profile, expected_racks, top_rack in (
            ('マイジャグラーV', 'normal', [101, 102, 103, 104, 105], 105),
            ('テストAT機', 'other', [201, 202, 203, 204, 205], 205),
        ):
            g = by_name[name]
            self.assertEqual(set(g.keys()), {'store', 'rate', 'name', 'profile', 'pool', 'current'})
            self.assertEqual(g['store'], 'pscube:c740601:20')
            self.assertEqual(g['rate'], '20')
            self.assertEqual(g['profile'], expected_profile)
            self.assertEqual(sorted(g['pool']), expected_racks)
            self.assertEqual(len(g['current']), 2, '5台の上位1/4切り上げ＝2台')
            self.assertEqual(g['current'][0], top_rack)

    def test_empty_machines_returns_empty_list(self):
        node = runtime.resolve_node()
        if not node:
            self.skipTest('node が見つからない環境です')
        proc = subprocess.run(
            [node, str(SCRIPT)],
            input=json.dumps({'data': {'machines': [], 'records': []}, 'day': '2026-11-05'}),
            capture_output=True, text=True, encoding='utf-8', check=False, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), [])


if __name__ == '__main__':
    unittest.main()
