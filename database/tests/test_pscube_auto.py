import gc
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from auto_capture import AutoCapture
from pscube_import import (AutoPilot, FINISHED_NAME, PscubeRandomCapture, close_when_finished, recent_business_days,
                           take_finished_message)

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


def setUpModule():
    # この試験は問い合わせを別スレッド（pscube-eval）で動かす。前に流れた変換画面の試験のTkが循環参照で残っていると、
    # そのスレッドでGCが走ったときに片付けられ「Tcl_AsyncDelete: async handler deleted by the wrong thread」で
    # プロセスごと落ちる（2026-10-18、まとめて流したときだけ再現）。始める前にメインスレッドで片付けておく。
    gc.collect()


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
        self.assertEqual(pilot.state()['seconds'], 20)
        self.assertIsInstance(pilot.auto, PscubeRandomCapture)
        with self.assertRaises(ValueError):
            pilot.configure(True, 4.5)

    def test_random_interval_all_choices_and_wait_does_not_redraw(self):
        choices = iter(range(100001))
        def draw(bound):
            self.assertEqual(bound, 100001)
            return next(choices)
        auto = PscubeRandomCapture(clock=self.clock, draw=draw)
        auto.configure(True, 15)
        actual = [auto.state()['seconds']]
        for _ in range(100000):
            auto.loaded()
            actual.append(auto.state()['seconds'])
        self.assertEqual(len(set(actual)), 100001)
        self.assertEqual((actual[0], actual[-1]), (15, 25))
        self.assertEqual(actual[12345], 16.2345)
        self.clock.now += 24.9999
        self.assertIsNone(auto.due())
        self.clock.now += .0001
        self.assertIsNotNone(auto.due())
        self.assertEqual(auto.state()['seconds'], 25)

    def test_random_wait_redraws_on_pause_and_busy_and_off_stops(self):
        draw = mock.Mock(side_effect=[0, 12345, 100000, 1])
        auto = PscubeRandomCapture(clock=self.clock, draw=draw)
        auto.configure(True, 20)
        auto.pause('保存待ち')
        self.assertEqual(auto.state()['seconds'], 16.2345)
        self.assertIsNone(auto.due(busy=True))
        self.assertEqual(auto.state()['seconds'], 25)
        auto.configure(False, 25)
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

    def test_saved_rack_without_net_medals_says_so_and_continues(self):
        self.pilot.configure(True, 10)
        self.window.probe = page('A', '台別7日分')
        self.wait(10)
        self.pilot.tick()
        self.pilot.finished(result={'kind': '台別7日分', 'remaining': 4, 'next_url': 'x',
                                    'net_warning': '差枚は未取得：通信に失敗しました（HTTP 403）'})
        self.assertTrue(self.pilot.state()['enabled'], '差枚が取れなくても巡回は止めない')
        self.assertIn('差枚は未取得', self.message())
        self.assertIn('A', self.pilot.done)

    def test_target_day_and_direction_are_set_with_the_start_and_cleared_when_done(self):
        today, yesterday = recent_business_days()[:2]
        state = self.pilot.configure(True, 10, yesterday, 'bottom')
        self.assertEqual((state['enabled'], state['target_day'], state['direction']), (True, yesterday, 'bottom'))
        self.assertEqual(state['days'][:2], [today, yesterday])
        self.assertEqual(self.window.rendered[-1]['target_day'], yesterday)
        with self.assertRaises(ValueError):
            self.pilot.set_target('', 'top')   # ONの間は変えられない
        self.window.probe = {**page('R', '台別7日分'), 'day': yesterday}
        self.wait(10)
        self.pilot.tick()
        self.pilot.finished(result={'kind': '台別7日分', 'remaining': 0, 'next_url': None})
        state = self.pilot.state()
        self.assertEqual((state['enabled'], state['target_day']), (False, None))
        self.assertIn('分をすべて取り込みました', self.message())
        self.assertEqual(state['direction'], 'bottom', '向きは覚えておく')

    def test_target_day_validation(self):
        for bad in ('2026-01-01', 'yesterday', '2026-13-40'):
            with self.assertRaises(ValueError):
                self.pilot.set_target(bad)
        with self.assertRaises(ValueError):
            self.pilot.set_target(None, 'sideways')
        state = self.pilot.set_target(recent_business_days()[3], 'bottom')
        self.assertEqual((state['target_day'], state['direction']), (recent_business_days()[3], 'bottom'))
        self.assertIsNone(self.pilot.set_target('')['target_day'])
        self.assertEqual(self.pilot.set_target(None)['direction'], 'bottom', '省略は今の設定のまま')

    def test_a_page_for_another_day_waits_instead_of_capturing(self):
        today, yesterday = recent_business_days()[:2]
        self.pilot.configure(True, 10, yesterday)
        self.window.probe = {**page('T', '全台一覧'), 'day': today}
        self.wait(10)
        self.pilot.tick()
        self.assertNotIn('start', self.window.calls)
        self.assertIn('日付タブ', self.message())
        self.assertTrue(self.pilot.state()['enabled'], '待つだけ。止められた扱いにはしない')
        self.assertEqual(self.pilot.missing, [])
        # 日付タブを合わせると取り込む。
        self.window.probe = {**page('T', '全台一覧'), 'day': yesterday}
        self.wait(10)
        self.pilot.tick()
        self.assertIn('start', self.window.calls)
        # 指定なしなら、どの日のページでも取り込む（これまでどおり）。
        other = AutoPilot(FakeWindow(), PROBE, auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))
        other.configure(True, 10)
        other.evaluate.probe = {**page('X', '全台一覧'), 'day': today}
        self.wait(10)
        other.tick()
        self.assertIn('start', other.evaluate.calls)

    def test_only_a_table_without_the_chosen_day_tab_is_read_despite_another_selected_day(self):
        # 2026-10-22：新台は取り込み日のタブが無く、サイトは最新のタブを選ぶ。以前は日付違いとして待ち続け、保存側の
        # 飛ばす処理まで届かなかった。タブが無いと読めるときだけ読み取りへ進め、保存側が確かめる。それ以外は今までどおり待つ。
        with mock.patch('pscube_import.recent_business_days', return_value=['2026-10-19', '2026-10-18', '2026-10-17']):
            cases = [
                # (取り込み日, 表示中の日, 種類, 日付タブ, 読み取るか)
                ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-19'], True),                     # 新台：最新のタブだけ
                ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-17', '2026-10-19'], True),       # 範囲の途中が無い
                ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-18', '2026-10-19'], False),      # タブはある：合わせてもらう
                ('2026-10-19', '2026-10-18', '全台一覧', ['2026-10-17', '2026-10-18'], False),      # タブより新しい（早朝）
                ('2026-10-18', '2026-10-19', '全台一覧', [], False),                                # タブが読めない
                ('2026-10-18', '2026-10-19', '全台一覧', None, False),                              # 古い判定（タブを返さない）
                ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-19', '10/17'], False),           # 形の違う日付
                ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-20'], False),                    # 選ばれた日がタブに無い
                ('2026-10-18', '2026-10-19', '台別7日分', ['2026-10-19'], False),                   # 台別ページの日付違い
            ]
            for target, shown, kind, days, reads in cases:
                with self.subTest(target=target, kind=kind, days=days):
                    window = FakeWindow()
                    pilot = AutoPilot(window, PROBE, auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))
                    pilot.configure(True, 10, target)
                    window.probe = {**page('T', kind), 'day': shown, **({} if days is None else {'days': days})}
                    self.wait(10)
                    pilot.tick()
                    self.assertEqual('start' in window.calls, reads, pilot.state()['message'])
                    self.assertIn('日付タブが無い機種か確かめています' if reads else '合わせてください', pilot.state()['message'])
                    self.assertTrue(pilot.state()['enabled'])
            # 人間確認・読み込み中の画面は、タブが無く見えても読み取らない。
            for probe in ({'ready': False, 'challenge': True, 'reason': '人間確認・同意の画面', 'busy': False, 'days': ['2026-10-19']},
                          {'ready': False, 'missing': True, 'reason': '全台一覧の表示待ち', 'busy': False, 'days': ['2026-10-19']},
                          {**page('T'), 'day': '2026-10-19', 'days': ['2026-10-19'], 'busy': True}):
                with self.subTest(probe=probe):
                    window = FakeWindow()
                    pilot = AutoPilot(window, PROBE, auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))
                    pilot.configure(True, 10, '2026-10-18')
                    window.probe = probe
                    self.wait(10)
                    pilot.tick()
                    self.assertNotIn('start', window.calls)

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

    def test_list_can_wait_90_seconds_before_the_capture_watchdog_expires(self):
        self.pilot.configure(True, 10)
        self.window.probe = page('A')
        self.wait(10)
        self.pilot.tick()
        self.assertEqual(self.pilot.pending, 'A')
        self.wait(91)
        self.pilot.tick()
        self.assertEqual(self.pilot.pending, 'A', '一覧90秒のあと、読み取り・保存通知の余裕を残す')
        self.assertEqual(self.pilot.failures, {})
        self.wait(29)
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
    def test_manual_off_is_not_logged_twice_and_later_automatic_off_is_logged(self):
        import pscube_import
        with tempfile.TemporaryDirectory() as tmp:
            captured = {}
            window = types.SimpleNamespace(
                events=types.SimpleNamespace(before_load=Handlers(), loaded=Handlers(), closed=Handlers()),
                evaluate_js=lambda script: None, get_current_url=lambda: pscube_import.ROOT_URL)

            def create_window(*args, **kwargs):
                captured['bridge'] = kwargs['js_api']
                return window

            def start(**kwargs):
                bridge = captured['bridge']
                loop = next(call.kwargs['target'] for call in threads.call_args_list
                            if call.kwargs.get('name') == 'pscube-auto')
                transitions = iter([
                    lambda: bridge.set_auto_capture(True, 20),
                    lambda: bridge.set_auto_capture(False, 20),
                    lambda: bridge.set_auto_capture(True, 20),
                    lambda: bridge.pilot.configure(False, 20),
                ])
                with mock.patch.object(bridge.pilot, 'tick', side_effect=lambda: next(transitions)()):
                    loop()

            fake = types.SimpleNamespace(create_window=create_window, start=start)
            stop = mock.Mock()
            stop.wait.side_effect = [False, False, False, False, True]
            with mock.patch.dict(sys.modules, {'webview': fake}), \
                    mock.patch.object(pscube_import.threading, 'Thread') as threads, \
                    mock.patch.object(pscube_import.threading, 'Event', return_value=stop), \
                    mock.patch.object(pscube_import, 'close_when_finished', return_value=False), \
                    mock.patch.object(pscube_import.error_log, 'note') as note, \
                    mock.patch.object(pscube_import.error_log, 'record') as record:
                pscube_import.run_session(Path(tmp) / 'data' / 'pscube.sqlite3', Path(tmp) / 'viewer.json')
            record.assert_not_called()
            events = [(call.args[1], call.args[2]) for call in note.call_args_list]
            self.assertEqual([where for where, _ in events], [
                'pscube.auto.switch', 'pscube.auto.switch', 'pscube.auto.switch', 'pscube.auto.off'])
            self.assertTrue(events[1][1].startswith('OFF'), '手動OFFはボタンの記録だけにする')

    def test_close_check_serializes_with_saving_and_releases_lock_on_error(self):
        import pscube_import
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as tmp:
                captured = {}
                window = types.SimpleNamespace(
                    events=types.SimpleNamespace(before_load=Handlers(), loaded=Handlers(), closed=Handlers()),
                    evaluate_js=lambda script: None, get_current_url=lambda: pscube_import.ROOT_URL)

                def create_window(*args, **kwargs):
                    captured['bridge'] = kwargs['js_api']
                    return window

                def close_check(pilot, saving, *args):
                    self.assertTrue(captured['bridge']._capture_lock.locked())
                    self.assertFalse(saving())
                    if fails:
                        raise OSError('模擬終了失敗')
                    return False

                def start(**kwargs):
                    bridge = captured['bridge']
                    loop = next(call.kwargs['target'] for call in threads.call_args_list
                                if call.kwargs.get('name') == 'pscube-auto')
                    transitions = iter([bridge._capture_lock.acquire, bridge._capture_lock.release])
                    with mock.patch.object(bridge.pilot, 'tick', side_effect=lambda: next(transitions)()):
                        # 実通信やスレッドを使わず、保存中→保存終了の順で2周する。
                        loop()
                    self.assertEqual(close.call_count, 1, '保存中の周回では終了判定しない')
                    self.assertFalse(bridge._capture_lock.locked(), '例外でもロックを戻す')

                fake = types.SimpleNamespace(create_window=create_window, start=start)
                stop = mock.Mock()
                stop.wait.side_effect = [False, False, True]
                with mock.patch.dict(sys.modules, {'webview': fake}), \
                        mock.patch.object(pscube_import.threading, 'Thread') as threads, \
                        mock.patch.object(pscube_import.threading, 'Event', return_value=stop), \
                        mock.patch.object(pscube_import, 'close_when_finished', side_effect=close_check) as close:
                    pscube_import.run_session(Path(tmp) / 'data' / 'pscube.sqlite3', Path(tmp) / 'viewer.json')

    def test_manual_save_clears_auto_completion_before_parsing_even_on_failure(self):
        import pscube_import
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as tmp:
                captured = {}
                window = types.SimpleNamespace(
                    events=types.SimpleNamespace(before_load=Handlers(), loaded=Handlers(), closed=Handlers()),
                    evaluate_js=lambda script: None, get_current_url=lambda: pscube_import.ROOT_URL)

                def create_window(*args, **kwargs):
                    captured['bridge'] = kwargs['js_api']
                    return window

                def save(*args):
                    bridge = captured['bridge']
                    self.assertTrue(bridge._capture_lock.locked())
                    self.assertIsNone(bridge.pilot.completed, '解析・保存前に古い完了を解除する')
                    if fails:
                        raise ValueError('模擬保存失敗')
                    return {'next_url': 'https://www.pscube.jp/next', 'remaining': 3}

                def start(**kwargs):
                    bridge = captured['bridge']
                    bridge.pilot.completed = '前の自動取り込みが完了'
                    if fails:
                        with self.assertRaisesRegex(ValueError, '模擬保存失敗'):
                            bridge.submit_page('{}')
                    else:
                        bridge.submit_page('{}')
                    self.assertIsNone(bridge.pilot.completed)
                    self.assertFalse(bridge._capture_lock.locked())
                    for handler in window.events.closed.items:
                        handler()

                fake = types.SimpleNamespace(create_window=create_window, start=start)
                with mock.patch.dict(sys.modules, {'webview': fake}), \
                        mock.patch.object(pscube_import, 'submit_capture', side_effect=save), \
                        mock.patch.object(pscube_import.threading, 'Thread'):
                    db = Path(tmp) / 'data' / 'pscube.sqlite3'
                    pscube_import.run_session(db, Path(tmp) / 'data' / 'viewer.json')

    def test_replacement_day_failures_and_warnings_are_kept_in_errors_log(self):
        # 2026-11-01：入れ替えの日に出た失敗・警告は画面の表示が次のページで消えるので、data/errors.log に残す。
        import error_log
        import pscube_import
        error_log.forget()
        self.addCleanup(error_log.forget)
        page = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c1/cgi-bin/nc-v06-001.php?cd_dai=1085#20261102'
        with tempfile.TemporaryDirectory() as tmp:
            captured = {}
            window = types.SimpleNamespace(
                events=types.SimpleNamespace(before_load=Handlers(), loaded=Handlers(), closed=Handlers()),
                evaluate_js=lambda script: None, get_current_url=lambda: page)

            def create_window(*args, **kwargs):
                captured['bridge'] = kwargs['js_api']
                return window

            results = iter([
                ValueError('数値が未表示か不正です。'),
                {'day': '2026-11-02', 'next_url': page, 'remaining': 3, 'kind': '台別履歴（1日分）',
                 'net_warning': 'グラフの元数値が不正'},
                {'day': '2026-11-02', 'next_url': page, 'remaining': 2, 'kind': '全台一覧',
                 'skipped': '新台は11/2の日付タブがサイトにありません（新台・入れ替えの可能性）。保存せずに飛ばしました'},
                {'retry_index': True, 'next_url': page},
                {'day': '2026-11-02', 'next_url': page, 'remaining': 1, 'kind': '全台一覧（1505番台はこの日の数値なし）'},
                {'day': '2026-11-02', 'next_url': page, 'remaining': 0, 'kind': '台別7日分'},
            ])

            def save(*args):
                result = next(results)
                if isinstance(result, Exception):
                    raise result
                return result

            def start(**kwargs):
                bridge = captured['bridge']
                with self.assertRaises(ValueError):
                    bridge.submit_page('{}')
                for _ in range(5):
                    bridge.submit_page('{}')
                bridge.capture_failed('全台一覧の読み込みが終わりません')
                for handler in window.events.closed.items:
                    handler()

            fake = types.SimpleNamespace(create_window=create_window, start=start)
            with mock.patch.dict(sys.modules, {'webview': fake}), \
                    mock.patch.object(pscube_import, 'submit_capture', side_effect=save), \
                    mock.patch.object(pscube_import.threading, 'Thread'):
                pscube_import.run_session(Path(tmp) / 'data' / 'pscube.sqlite3', Path(tmp) / 'data' / 'viewer.json')
            lines = [line.split('\t') for line in
                     (Path(tmp) / 'data' / 'errors.log').read_text(encoding='utf-8').splitlines()]
        places = [line[1] for line in lines]
        self.assertEqual(places, ['pscube.save', 'pscube.net_missing', 'pscube.skipped', 'pscube.index_retry',
                                  'pscube.missing_racks', 'pscube.read'], '問題のない保存（台別7日分）は書かない')
        save_line = lines[0]
        self.assertEqual(save_line[2], f'ValueError: 数値が未表示か不正です。（{page}）')
        self.assertRegex(save_line[3], r'^test_pscube_auto\.py:\d+ save$')
        self.assertIn('グラフの元数値が不正（2026-11-02・' + page, lines[1][2])
        self.assertIn('新台・入れ替えの可能性', lines[2][2])
        self.assertIn('1505番台はこの日の数値なし', lines[4][2])
        self.assertEqual(lines[5][2], '全台一覧の読み込みが終わりません')

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


class CloseWhenFinishedTests(unittest.TestCase):
    """自動取り込みが全部終わったら取り込み窓を閉じる（2026-10-30 利用者「各取り込み終わったら停止してほしい」）。
    窓はタイマーを間引かない設定なので、サイトのページを開いたままだと取り込みのあともサイトの定期通信が続いていた。"""

    def setUp(self):
        self.clock = Clock()
        self.window = FakeWindow()
        self.saving = False
        self.pilot = AutoPilot(self.window, PROBE, saving=lambda: self.saving,
                               auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))
        self.destroyed = []
        self.browser = types.SimpleNamespace(destroy=lambda: self.destroyed.append(True))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)

    def capture(self, signature, next_url, day=None):
        if day:
            self.pilot.configure(True, 5, day)
        elif not self.pilot.state()['enabled']:
            self.pilot.configure(True, 5)
        self.window.probe = {**page(signature, '台別7日分'), **({'day': day} if day else {})}
        self.clock.now += 5
        self.pilot.tick()
        self.pilot.finished(result={'next_url': next_url, 'remaining': 0 if next_url is None else 3, 'kind': '台別7日分'})

    def close(self):
        return close_when_finished(self.pilot, lambda: self.saving, self.browser, self.data)

    def test_closes_only_after_auto_capture_took_everything(self):
        self.capture('A', 'https://www.pscube.jp/next')
        self.assertFalse(self.close(), '残りがあるうちは閉じない')
        self.capture('B', None)
        self.assertEqual(self.pilot.completed, 'すべて取り込みました（自動取り込みを停止しました）')
        self.saving = True
        self.assertFalse(self.close(), '保存中は閉じない')
        self.saving = False
        self.assertTrue(self.close())
        self.assertEqual(self.destroyed, [True])
        # 止まった理由と時刻は errors.log にも残る（2026-11-05）。
        self.assertIn('pscube.auto.stop\tすべて取り込みました', (self.data / 'errors.log').read_text(encoding='utf-8'))
        self.assertEqual(take_finished_message(self.data), 'すべて取り込みました（自動取り込みを停止しました）')
        self.assertIsNone(take_finished_message(self.data), '知らせは1回で消える')

    def test_day_message_and_restart_clears_the_finished_state(self):
        day = recent_business_days()[1]
        self.capture('C', None, day)
        self.assertIn('の分をすべて取り込みました', self.pilot.completed)
        self.pilot.configure(True, 5)
        self.assertIsNone(self.pilot.completed, 'もう一度ONにしたら閉じる理由は消える')
        self.assertFalse(self.close())

    def test_manual_capture_does_not_close(self):
        self.window.probe = page('D', '台別7日分')
        self.pilot.finished(result={'next_url': None, 'remaining': 0, 'kind': '台別7日分'})
        self.assertIsNone(self.pilot.completed)
        self.assertFalse(self.close())
        self.assertEqual(self.destroyed, [])

    def test_manual_use_after_auto_finished_keeps_window_open(self):
        for error in (None, '模擬保存失敗'):
            with self.subTest(error=error):
                self.capture('completed-before-manual', None)
                self.saving = True
                self.assertFalse(self.close())
                self.pilot.capture_started()
                self.assertIsNone(self.pilot.completed)
                self.pilot.finished(
                    result={'next_url': 'https://www.pscube.jp/next', 'remaining': 3}, error=error)
                self.saving = False
                self.assertFalse(self.close(), '手動取得が成功・失敗どちらでも古い完了で閉じない')
                self.assertEqual(self.destroyed, [])

    def test_closes_even_if_the_notice_cannot_be_written(self):
        self.capture('E', None)
        blocker = self.data / 'blocker'
        blocker.write_text('x', encoding='utf-8')  # フォルダーの代わりにファイルがあり、知らせを書けない
        self.assertTrue(close_when_finished(self.pilot, lambda: False, self.browser, blocker))
        self.assertEqual(self.destroyed, [True], 'サイトへの接続を止めるほうを優先する')

    def test_broken_or_absent_notice_reads_as_none(self):
        self.assertIsNone(take_finished_message(self.data))
        (self.data / FINISHED_NAME).write_text('{', encoding='utf-8')
        self.assertIsNone(take_finished_message(self.data))
        self.assertFalse((self.data / FINISHED_NAME).exists())


if __name__ == '__main__':
    unittest.main()
