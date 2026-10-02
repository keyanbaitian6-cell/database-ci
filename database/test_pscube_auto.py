import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from auto_capture import AutoCapture
from pscube_import import AutoPilot, PscubeRandomCapture

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
        self.pilot = AutoPilot(self.window, PROBE, saving=lambda: self.saving,
                               auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))

    def wait(self, seconds=10):
        self.clock.now += seconds

    def message(self):
        return self.pilot.state()['message']

    def test_default_pilot_uses_the_pscube_range(self):
        pilot = AutoPilot(self.window, PROBE)
        self.assertEqual(pilot.state()['seconds'], 6.5)
        self.assertIsInstance(pilot.auto, PscubeRandomCapture)
        with self.assertRaises(ValueError):
            pilot.configure(True, 4.5)

    def test_random_interval_all_choices_and_wait_does_not_redraw(self):
        choices = iter(range(30001))
        def draw(bound):
            self.assertEqual(bound, 30001)
            return next(choices)
        auto = PscubeRandomCapture(clock=self.clock, draw=draw)
        auto.configure(True, 5)
        actual = [auto.state()['seconds']]
        for _ in range(30000):
            auto.loaded()
            actual.append(auto.state()['seconds'])
        self.assertEqual(len(set(actual)), 30001)
        self.assertEqual((actual[0], actual[-1]), (5, 8))
        self.assertEqual(actual[12345], 6.2345)
        self.clock.now += 7.9999
        self.assertIsNone(auto.due())
        self.clock.now += .0001
        self.assertIsNotNone(auto.due())
        self.assertEqual(auto.state()['seconds'], 8)

    def test_random_wait_redraws_on_pause_and_busy_and_off_stops(self):
        draw = mock.Mock(side_effect=[0, 12345, 30000, 1])
        auto = PscubeRandomCapture(clock=self.clock, draw=draw)
        auto.configure(True, 6.5)
        auto.pause('保存待ち')
        self.assertEqual(auto.state()['seconds'], 6.2345)
        self.assertIsNone(auto.due(busy=True))
        self.assertEqual(auto.state()['seconds'], 8)
        auto.configure(False, 8)
        self.clock.now += 100
        self.assertIsNone(auto.due())
        self.assertEqual(draw.call_count, 4)

    def test_starts_off_and_never_looks_at_the_page_while_off(self):
        self.assertFalse(self.pilot.state()['enabled'])
        self.assertEqual(self.pilot.state()['seconds'], 10)
        self.wait(10)
        self.pilot.tick()
        self.assertEqual(self.window.calls, [])

    def test_waits_the_interval_then_waits_on_pages_that_are_not_ready(self):
        self.pilot.configure(True, 7.1)
        self.pilot.tick()
        self.assertEqual(self.window.calls, [], '間隔が経つまでは見ない')
        self.clock.now = 107.0
        self.pilot.tick()
        self.assertEqual(self.window.calls, [], '7.0秒ではまだ開始しない')
        self.clock.now = 107.1
        self.window.probe = {'ready': False, 'reason': '台別7日分の表示待ち（人間確認・同意の画面なら手動で操作してください）'}
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe'])
        self.assertIn('人間確認', self.message())
        self.assertTrue(self.pilot.state()['enabled'], '確認画面でもONのまま')

    def test_ready_page_starts_one_capture_and_waits_for_it(self):
        self.pilot.configure(True, 5)
        self.window.probe = page('A')
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe', 'start'])
        self.assertIn('取り込み中', self.message())
        self.wait(10)
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe', 'start'], '取り込み中は次を始めない')

    def test_saved_page_is_not_captured_twice_and_the_next_page_continues(self):
        self.pilot.configure(True, 5)
        self.window.probe = page('A')
        self.wait(5)
        self.pilot.tick()
        self.pilot.finished(result={'next_url': 'B', 'remaining': 3, 'kind': '全台一覧'})
        self.assertIn('残り3件', self.message())
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 1)
        self.assertIn('重複保存しません', self.message())
        self.pilot.loaded()
        self.window.probe = page('B', '台別7日分')
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 1, '新しいページも間隔を待つ')
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 2)

    def test_three_failures_on_one_page_stop_retrying_until_off_and_on(self):
        self.pilot.configure(True, 5)
        self.window.probe = page('A')
        for attempt in range(1, 4):
            self.wait(5)
            self.pilot.tick()
            self.pilot.finished(error='表示は32台、設置台数は33台です。')
            self.assertIn(f'{attempt}回目', self.message())
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 3)
        self.assertIn('3回失敗', self.message())
        self.pilot.configure(False, 5)
        self.pilot.configure(True, 5)
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 4)

    def test_turns_itself_off_when_nothing_is_left(self):
        self.pilot.configure(True, 5)
        self.window.probe = page('A', '台別7日分')
        self.wait(5)
        self.pilot.tick()
        self.pilot.finished(result={'next_url': None, 'remaining': 0, 'kind': '台別7日分'})
        self.assertFalse(self.pilot.state()['enabled'])
        self.assertIn('すべて取り込みました', self.message())
        self.assertFalse(self.window.rendered[-1]['enabled'], '画面にもOFFを表示')

    def test_saving_or_busy_page_holds_the_next_attempt(self):
        self.pilot.configure(True, 5)
        self.saving = True
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls, [], '手動の保存中は見ない')
        self.saving = False
        self.window.probe = {**page('A'), 'busy': True}
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe'])
        self.assertIn('完了待ち', self.message())

    def test_off_before_the_capture_starts_wins(self):
        self.pilot.configure(True, 5)
        self.window.probe = page('A')
        self.wait(5)
        token = self.pilot.auto.due()
        self.pilot.configure(False, 5)
        self.assertFalse(self.pilot.auto.run_current(token, lambda: self.fail('OFFの後に始めてはいけない')))

    def test_a_capture_lost_by_navigation_does_not_block_the_next_page(self):
        self.pilot.configure(True, 5)
        self.window.probe = page('A')
        self.wait(5)
        self.pilot.tick()
        self.pilot.loaded()  # ページが移り、読み取り中のスクリプトは消えた
        self.window.probe = page('B')
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 2)

    def test_manual_capture_results_do_not_count_as_auto(self):
        self.pilot.finished(error='x')
        self.pilot.finished(result={'next_url': None, 'remaining': 0, 'kind': '台別7日分'})
        self.assertEqual(self.pilot.failures, {})
        self.assertEqual(self.pilot.done, set())
        self.assertFalse(self.pilot.state()['enabled'])

    def test_page_refusing_to_start_is_retried_later(self):
        self.pilot.configure(True, 5)
        self.window.probe = page('A')
        self.window.start_result = False
        self.wait(5)
        self.pilot.tick()
        self.assertIsNone(self.pilot.pending)
        self.window.start_result = True
        self.wait(5)
        self.pilot.tick()
        self.assertEqual(self.pilot.pending, 'A')

    def test_stops_when_the_site_keeps_showing_no_data_but_not_on_challenge_pages(self):
        self.pilot.configure(True, 10)
        self.window.probe = {'ready': False, 'missing': True, 'reason': '全台一覧の表示待ち'}
        for _ in range(6):
            self.wait(10)
            self.pilot.tick()
            self.assertTrue(self.pilot.state()['enabled'], '1分たつまでは待つ')
        self.wait(10)
        self.pilot.tick()
        self.assertFalse(self.pilot.state()['enabled'])
        self.assertIn('止められた可能性', self.message())
        self.assertIn('Cookieを消さずに', self.message(), '止まったときに記録を消さない復旧を案内する')
        self.assertFalse(self.window.rendered[-1]['enabled'])

    def test_challenge_pages_and_recovered_pages_do_not_count_toward_stopping(self):
        self.pilot.configure(True, 10)
        for i in range(12):
            if i % 4 == 3:
                self.window.probe = page(f'P{i}')
            elif i % 2:
                self.window.probe = {'ready': False, 'challenge': True, 'reason': '人間確認・同意の画面（手動で操作してください）'}
            else:
                self.window.probe = {'ready': False, 'missing': True, 'reason': '表示待ち'}
            self.wait(10)
            self.pilot.tick()
            self.pilot.finished(result={'next_url': 'x', 'remaining': 1, 'kind': '全台一覧'}) if self.pilot.pending else None
        self.assertTrue(self.pilot.state()['enabled'], '確認画面の間・表示が戻った後は止めない')
        self.window.probe = {'ready': False, 'challenge': True, 'reason': '人間確認・同意の画面（手動で操作してください）'}
        for _ in range(10):
            self.wait(10)
            self.pilot.tick()
        self.assertTrue(self.pilot.state()['enabled'], '確認画面ではずっと待つ')
        self.assertIn('人間確認', self.message())

    def test_no_query_while_a_page_is_loading(self):
        # 読み込み中に問い合わせると、読み込みが終わるまで待たされる（2026-10-02 実測）。
        self.pilot.configure(True, 10)
        self.window.probe = page('A')
        self.pilot.loading()
        self.wait(30)
        self.pilot.tick()
        self.assertEqual(self.window.calls, [])
        self.pilot.loaded()
        self.wait(10)
        self.pilot.tick()
        self.assertEqual(self.window.calls, ['probe', 'start'])

    def test_a_query_without_answer_gives_up_and_retries_later(self):
        import threading, time
        release = threading.Event()
        slow = FakeWindow()
        slow.probe = page('A')

        def evaluate(script):
            if script == PROBE and not release.is_set():
                release.wait(2)
                return None
            return slow(script)
        pilot = AutoPilot(evaluate, PROBE, auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10),
                          eval_timeout=0.05)
        pilot.configure(True, 10)
        self.wait(10)
        started = time.monotonic()
        pilot.tick()
        self.assertLess(time.monotonic() - started, 1.0, '返事を待ち続けない')
        self.assertIsNone(pilot.pending)
        release.set()
        self.wait(10)
        pilot.tick()
        self.assertEqual(pilot.pending, 'A', '次の機会にやり直す')

    def test_saving_completion_is_not_blocked_while_the_page_is_being_asked(self):
        import threading
        self.pilot.configure(True, 10)
        self.window.probe = page('A')
        self.wait(10)
        self.pilot.tick()
        finished = threading.Event()
        original = self.window.__call__

        def probe_with_concurrent_save(script):
            if script == PROBE:
                worker = threading.Thread(target=lambda: (self.pilot.finished(result={'next_url': 'B', 'remaining': 1, 'kind': '全台一覧'}), finished.set()))
                worker.start()
                worker.join(1)
            return original(script)
        self.pilot.evaluate = probe_with_concurrent_save
        self.pilot.loaded()
        self.wait(10)
        self.pilot.tick()
        self.assertTrue(finished.is_set(), '問い合わせ中でも保存完了の処理は進む')

    def test_a_capture_that_never_finishes_is_released_after_90_seconds(self):
        self.pilot.configure(True, 10)
        self.window.probe = page('A')
        self.wait(10)
        self.pilot.tick()
        self.assertEqual(self.pilot.pending, 'A')
        self.wait(60)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 1, '90秒までは待つ')
        self.wait(40)
        self.pilot.tick()
        self.assertIn('やり直します', self.message())
        self.assertEqual(self.pilot.failures, {'A': 1})
        self.wait(10)
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), 2)

    def test_interval_is_5_to_60_seconds_for_pscube(self):
        for bad in (4.9, 60.1, True, float('nan')):
            with self.assertRaises(ValueError):
                self.pilot.configure(True, bad)
        self.assertEqual(self.pilot.configure(False, 5)['seconds'], 5)
        self.assertEqual(self.pilot.configure(False, 60)['seconds'], 60)


class ResetSiteTests(unittest.TestCase):
    """「サイトの記録を消してやり直す」：Cookie・保存データを消して最初のページへ。記録は消さない。"""

    def setUp(self):
        import pscube_import
        self.pi = pscube_import
        self.clock = Clock()
        self.page = FakeWindow()
        self.pilot = AutoPilot(self.page, PROBE, auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))
        self.actions = []
        self.window = types.SimpleNamespace(clear_cookies=lambda: self.actions.append('cookies'),
                                            load_url=lambda url: self.actions.append(('load', url)))
        evaluate = self.page.__call__
        self.page_scripts = []
        self.pilot.evaluate = lambda script: (self.page_scripts.append(script), evaluate(script))[1]

    def test_clears_cookies_and_page_storage_turns_auto_off_and_reopens_the_first_page(self):
        self.pilot.configure(True, 20)
        self.pilot.missing.extend([1, 2, 3])
        self.pilot.done.add('A')
        self.pilot.failures['B'] = 3
        message = self.pi.reset_site(self.window, self.pilot, saving=lambda: False)
        self.assertEqual(self.actions, ['cookies', ('load', self.pi.ROOT_URL)])
        self.assertIn(self.pi.RESET_SITE_SCRIPT, self.page_scripts)
        state = self.pilot.state()
        self.assertFalse(state['enabled'], '消したあとは自動取り込みをOFFにする（人間確認を手でするため）')
        self.assertEqual(state['seconds'], 20)
        self.assertEqual((self.pilot.missing, self.pilot.done, self.pilot.failures), ([], set(), {}))
        self.assertIn('取り込んだ記録はそのまま', message)
        self.assertEqual(state['message'], message)

    def test_refuses_while_saving_and_changes_nothing(self):
        self.pilot.configure(True, 20)
        with self.assertRaises(ValueError):
            self.pi.reset_site(self.window, self.pilot, saving=lambda: True)
        self.assertEqual(self.actions, [])
        self.assertTrue(self.pilot.state()['enabled'])

    def test_page_script_only_touches_browser_storage(self):
        script = self.pi.RESET_SITE_SCRIPT
        for word in ('localStorage.clear()', 'sessionStorage.clear()', 'indexedDB.deleteDatabase', 'caches.delete'):
            self.assertIn(word, script)
        self.assertNotIn('pywebview.api', script)

    def test_card_has_the_reset_button_with_a_confirmation(self):
        overlay = self.pi.overlay_script('CAPTURE', self.pi.ROOT_URL)
        self.assertIn("reset.id = 'database-pscube-reset'", overlay)
        self.assertIn('サイトの記録を消してやり直す', overlay)
        self.assertIn('confirm(', overlay)
        self.assertIn('window.pywebview.api.reset_site()', overlay)


class Handlers:
    def __init__(self):
        self.items = []

    def __iadd__(self, handler):
        self.items.append(handler)
        return self


class SessionStartTests(unittest.TestCase):
    def test_window_keeps_cookies_in_the_data_folder_instead_of_private_mode(self):
        import pscube_import
        started = {}
        window = types.SimpleNamespace(events=types.SimpleNamespace(before_load=Handlers(), loaded=Handlers(), closed=Handlers()),
                                       evaluate_js=lambda script: None, get_current_url=lambda: pscube_import.ROOT_URL)
        fake = types.SimpleNamespace(create_window=lambda *a, **k: window,
                                     start=lambda **kwargs: (started.update(kwargs), [h() for h in window.events.closed.items]))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {'webview': fake}):
            db = Path(tmp) / 'data' / 'pscube.sqlite3'
            pscube_import.run_session(db, Path(tmp) / 'data' / 'pscube-viewer.json')
            self.assertEqual(started['gui'], 'edgechromium')
            self.assertIs(started['private_mode'], False, 'シークレットモードではCookieが残らない')
            self.assertEqual(Path(started['storage_path']), (Path(tmp) / 'data' / 'pscube-webview').resolve())
            self.assertTrue(Path(started['storage_path']).is_dir())


if __name__ == '__main__':
    unittest.main()
