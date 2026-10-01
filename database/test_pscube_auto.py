import json
import unittest

from auto_capture import AutoCapture
from pscube_import import AutoPilot

PROBE = 'PROBE'
START = 'window.__pscubeStartCapture ? window.__pscubeStartCapture() : false'


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeWindow:
    """evaluate_js の代わり：判定の結果を返し、取り込みの開始と画面への表示を記録する。"""

    def __init__(self):
        self.probe = {'ready': False, 'reason': '表示待ち', 'busy': False}
        self.start_result = True
        self.calls = []
        self.rendered = []

    def __call__(self, script):
        if script == PROBE:
            self.calls.append('probe')
            return json.dumps(self.probe)
        if script == START:
            self.calls.append('start')
            return self.start_result
        if script.startswith('window.__pscubeRenderAuto'):
            self.rendered.append(json.loads(script[script.index('(') + 1:-1]))
        return None


def page(signature, kind='全台一覧'):
    return {'ready': True, 'kind': kind, 'signature': signature, 'busy': False}


class AutoPilotTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.window = FakeWindow()
        self.saving = False
        self.pilot = AutoPilot(self.window, PROBE, saving=lambda: self.saving, auto=AutoCapture(clock=self.clock))

    def wait(self, seconds=3.5):
        self.clock.now += seconds

    def message(self):
        return self.pilot.state()['message']

    def test_starts_off_and_never_looks_at_the_page_while_off(self):
        self.assertFalse(self.pilot.state()['enabled'])
        self.assertEqual(self.pilot.state()['seconds'], 3.5)
        self.wait(10)
        self.pilot.tick()
        self.assertEqual(self.window.calls, [])

    def test_waits_the_interval_then_waits_on_pages_that_are_not_ready(self):
        self.pilot.configure(True, 3.5)
        self.pilot.tick()
        self.assertEqual(self.window.calls, [], '間隔が経つまでは見ない')
        self.wait()
        self.window.probe = {'ready': False, 'reason': '台別7日分の表示待ち（人間確認・同意の画面なら手動で操作してください）'}
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe'])
        self.assertIn('人間確認', self.message())
        self.assertTrue(self.pilot.state()['enabled'], '確認画面でもONのまま')

    def test_ready_page_starts_one_capture_and_waits_for_it(self):
        self.pilot.configure(True, 1.0)
        self.window.probe = page('A')
        self.wait(1)
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe', 'start'])
        self.assertIn('取り込み中', self.message())
        self.wait(10)
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe', 'start'], '取り込み中は次を始めない')

    def test_saved_page_is_not_captured_twice_and_the_next_page_continues(self):
        self.pilot.configure(True, 1.0)
        self.window.probe = page('A')
        self.wait(1)
        self.pilot.tick()
        self.pilot.finished(result={'next_url': 'B', 'remaining': 3, 'kind': '全台一覧'})
        self.assertIn('残り3件', self.message())
        self.wait(1)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 1)
        self.assertIn('重複保存しません', self.message())
        self.pilot.loaded()
        self.window.probe = page('B', '台別7日分')
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 1, '新しいページも間隔を待つ')
        self.wait(1)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 2)

    def test_three_failures_on_one_page_stop_retrying_until_off_and_on(self):
        self.pilot.configure(True, 0.5)
        self.window.probe = page('A')
        for attempt in range(1, 4):
            self.wait(0.5)
            self.pilot.tick()
            self.pilot.finished(error='表示は32台、設置台数は33台です。')
            self.assertIn(f'{attempt}回目', self.message())
        self.wait(0.5)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 3)
        self.assertIn('3回失敗', self.message())
        self.pilot.configure(False, 0.5)
        self.pilot.configure(True, 0.5)
        self.wait(0.5)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 4)

    def test_turns_itself_off_when_nothing_is_left(self):
        self.pilot.configure(True, 1.0)
        self.window.probe = page('A', '台別7日分')
        self.wait(1)
        self.pilot.tick()
        self.pilot.finished(result={'next_url': None, 'remaining': 0, 'kind': '台別7日分'})
        self.assertFalse(self.pilot.state()['enabled'])
        self.assertIn('すべて取り込みました', self.message())
        self.assertFalse(self.window.rendered[-1]['enabled'], '画面にもOFFを表示')

    def test_saving_or_busy_page_holds_the_next_attempt(self):
        self.pilot.configure(True, 1.0)
        self.saving = True
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls, [], '手動の保存中は見ない')
        self.saving = False
        self.window.probe = {**page('A'), 'busy': True}
        self.wait(1)
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe'])
        self.assertIn('完了待ち', self.message())

    def test_off_before_the_capture_starts_wins(self):
        self.pilot.configure(True, 1.0)
        self.window.probe = page('A')
        self.wait(1)
        token = self.pilot.auto.due()
        self.pilot.configure(False, 1.0)
        self.assertFalse(self.pilot.auto.run_current(token, lambda: self.fail('OFFの後に始めてはいけない')))

    def test_a_capture_lost_by_navigation_does_not_block_the_next_page(self):
        self.pilot.configure(True, 1.0)
        self.window.probe = page('A')
        self.wait(1)
        self.pilot.tick()
        self.pilot.loaded()  # ページが移り、読み取り中のスクリプトは消えた
        self.window.probe = page('B')
        self.wait(1)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 2)

    def test_manual_capture_results_do_not_count_as_auto(self):
        self.pilot.finished(error='x')
        self.pilot.finished(result={'next_url': None, 'remaining': 0, 'kind': '台別7日分'})
        self.assertEqual(self.pilot.failures, {})
        self.assertEqual(self.pilot.done, set())
        self.assertFalse(self.pilot.state()['enabled'])

    def test_page_refusing_to_start_is_retried_later(self):
        self.pilot.configure(True, 1.0)
        self.window.probe = page('A')
        self.window.start_result = False
        self.wait(1)
        self.pilot.tick()
        self.assertIsNone(self.pilot.pending)
        self.window.start_result = True
        self.wait(1)
        self.pilot.tick()
        self.assertEqual(self.pilot.pending, 'A')

    def test_interval_limits_follow_meruhen(self):
        for bad in (0.0, 4.6, True, float('nan')):
            with self.assertRaises(ValueError):
                self.pilot.configure(True, bad)
        self.assertEqual(self.pilot.configure(False, 0.1)['seconds'], 0.1)
        self.assertEqual(self.pilot.configure(False, 4.5)['seconds'], 4.5)


if __name__ == '__main__':
    unittest.main()
