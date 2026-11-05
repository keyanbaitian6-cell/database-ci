"""PCのスリープの扱い（2026-11-06 利用者「取り込み中はスリープ禁止」「取り込み後問題なかったか確認し、5分後にスリーブ」）。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import power  # noqa: E402
import pscube_import  # noqa: E402


class PowerTests(unittest.TestCase):
    def test_keep_awake_sets_and_clears_the_system_required_flag(self):
        kernel = mock.Mock()
        kernel.SetThreadExecutionState.return_value = 0x80000000
        self.assertTrue(power.keep_awake(True, kernel32=kernel))
        self.assertTrue(power.keep_awake(False, kernel32=kernel))
        self.assertEqual([c.args[0] for c in kernel.SetThreadExecutionState.call_args_list],
                         [0x80000001, 0x80000000], 'ONの間は ES_CONTINUOUS|ES_SYSTEM_REQUIRED、解くときは ES_CONTINUOUS だけ')

    def test_sleep_is_sleep_not_hibernate_and_not_forced(self):
        powrprof = mock.Mock()
        powrprof.SetSuspendState.return_value = 1
        self.assertTrue(power.sleep_now(powrprof=powrprof))
        powrprof.SetSuspendState.assert_called_once_with(False, False, False)
        self.assertEqual(power.SLEEP_DELAY_SECONDS, 300, '5分後')

    def test_capture_problems_reads_only_this_session_and_needs_a_complete_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'errors.log').write_text('\n'.join([
                '2026-11-06T05:00:00+09:00\tpscube.save\t前の窓の失敗\t',
                '2026-11-06T06:10:00+09:00\tpscube.net_missing\t差枚は未取得\t',
                '2026-11-06T06:20:00+09:00\tpscube.net_missing\t差枚は未取得\t',
                '2026-11-06T06:30:00+09:00\tpscube.auto.rest\t休憩\t',
                '2026-11-06T06:40:00+09:00\tmeruhen.save.graph\t別のサイト\t',
            ]) + '\n', encoding='utf-8')
            since = '2026-11-06T06:00:00+09:00'
            self.assertEqual(pscube_import.capture_problems(tmp, 'すべて取り込みました（自動取り込みを停止しました）', since),
                             ['差枚が未取得の台 2件'])
            self.assertEqual(pscube_import.capture_problems(tmp, '11/5の分をすべて取り込みました（自動取り込みを停止しました）',
                                                            '2026-11-06T07:00:00+09:00'), [], '問題なし')
            stopped = pscube_import.capture_problems(tmp, '自動取り込みを止めました（通信エラー：HTTP 403）', '2026-11-06T07:00:00+09:00')
            self.assertEqual(len(stopped), 1)
            self.assertTrue(stopped[0].startswith('最後まで取り込めていません'))


if __name__ == '__main__':
    unittest.main()
