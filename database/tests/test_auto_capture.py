import json
import unittest
import threading
from unittest.mock import Mock

from auto_capture import AutoCapture
from browser_import import _Bridge, BROWSER_URLS


class AutoCaptureTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.auto = AutoCapture(lambda: self.now)

    def start(self, seconds=0.1):
        self.auto.configure(True, seconds)
        self.now += seconds
        return self.auto.due()

    def test_starts_off_and_restart_does_not_restore_on(self):
        self.assertFalse(self.auto.state()['enabled'])
        self.start()
        self.assertFalse(AutoCapture().state()['enabled'])

    def test_all_45_intervals(self):
        for tenth in range(1, 46):
            seconds = tenth / 10
            self.auto.configure(True, seconds)
            self.assertIsNone(self.auto.due())
            self.now += seconds + 0.00001
            self.assertIsNotNone(self.auto.due())

    def test_invalid_interval(self):
        for value in (0, -1, 4.6, float('nan'), float('inf'), True, 'bad'):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                self.auto.configure(True, value)
        self.assertFalse(self.auto.state()['enabled'])

    def test_pause_keeps_on_and_resumes(self):
        generation = self.start()
        self.auto.pause('確認画面待ち', generation)
        self.assertTrue(self.auto.state()['enabled'])
        self.assertIsNone(self.auto.due())
        self.now += 1
        action = Mock(return_value=True)
        self.assertTrue(self.auto.submit(self.auto.due(), 'rack1', action))
        action.assert_called_once()

    def test_repeated_page_waits_without_switching_off(self):
        generation = self.start()
        action = Mock(return_value=True)
        self.assertTrue(self.auto.submit(generation, 'rack1', action))
        self.assertFalse(self.auto.submit(generation, 'rack1', action))
        self.assertTrue(self.auto.state()['enabled'])
        action.assert_called_once()

    def test_off_cancels_extraction_already_in_flight(self):
        generation = self.start()
        self.auto.configure(False, 0.1)
        action = Mock(return_value=True)
        self.assertFalse(self.auto.submit(generation, 'rack1', action))
        action.assert_not_called()

    def test_navigation_keeps_on_but_invalidates_old_extraction(self):
        generation = self.start()
        self.auto.loaded()
        action = Mock(return_value=True)
        self.assertFalse(self.auto.submit(generation, 'old', action))
        self.now += 1
        self.assertTrue(self.auto.submit(self.auto.due(), 'new', action))
        self.assertTrue(self.auto.state()['enabled'])

    def test_busy_waits_until_process_done_then_interval(self):
        self.start()
        self.assertIsNone(self.auto.due(busy=True))
        self.assertIsNone(self.auto.due(busy=False))
        self.now += 1
        self.assertIsNotNone(self.auto.due())

    def test_failed_admission_can_retry_same_page(self):
        generation = self.start()
        self.assertFalse(self.auto.submit(generation, 'rack1', lambda: False))
        self.now += 1
        self.assertTrue(self.auto.submit(self.auto.due(), 'rack1', lambda: True))

    def test_old_error_does_not_replace_new_run_status(self):
        generation = self.start()
        self.auto.configure(False, 0.1)
        self.auto.pause('old error', generation)
        self.assertNotEqual(self.auto.state()['message'], 'old error')


class BridgeAutoCaptureTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.bridge = _Bridge('unused.db', 'unused-reports', 'unused.py')
        self.bridge._auto = AutoCapture(lambda: self.now)
        self.bridge._window = Mock()
        self.bridge._spawn = Mock(return_value=True)
        self.url = BROWSER_URLS['saiwaichou'].replace('rack_info', 'rack') + '?rack_no=710&target_date=2026-09-30'
        self.bridge._window.get_current_url.return_value = self.url
        self.probe = dict(kind='graph', url=self.url, raw=json.dumps(dict(
            store='saiwaichou', rack=710, target_date='2026-09-30', source_url=self.url)))
        self.bridge._window.evaluate_js.side_effect = lambda script: self.probe if '__databaseAutoProbe' in script else True
        self.bridge._loaded()
        self.bridge.set_auto_capture(True, 0.1)
        self.now = 1.0

    def test_graph_submitted_once(self):
        self.bridge._auto_tick()
        self.now += 1
        self.bridge._auto_tick()
        self.bridge._spawn.assert_called_once_with('graph', self.probe['raw'])
        self.assertTrue(self.bridge.get_auto_capture()['enabled'])

    def test_japanese_machine_name_url_forms_count_as_the_same_page(self):
        # WebView2 は日本語を戻した形、ページは%の形でURLを返す（2026-10-01 実測）。
        decoded = BROWSER_URLS['saiwaichou'].replace('rack_info_kt', 'standlist_slot') + \
            '?kind_code=21&machine_name=L ｽﾏｽﾛ化物語 KH&target_date=2026-10-01'
        from urllib.parse import quote
        encoded = decoded.split('machine_name=')[0] + 'machine_name=' + quote('L ｽﾏｽﾛ化物語 KH') + '&target_date=2026-10-01'
        self.bridge._window.get_current_url.return_value = decoded
        self.probe = dict(kind='table', url=encoded, raw=json.dumps(dict(
            store='saiwaichou', machine='L ｽﾏｽﾛ化物語 KH', target_date='2026-10-01', source_url=encoded)))
        self.bridge._auto_tick()
        self.bridge._spawn.assert_called_once_with('table', self.probe['raw'])
        self.assertNotIn('ページ切り替え待ち', self.bridge.get_auto_capture()['message'])

    def test_a_really_different_page_still_waits(self):
        self.probe = dict(self.probe, url=self.url.replace('rack_no=710', 'rack_no=711'))
        self.bridge._auto_tick()
        self.bridge._spawn.assert_not_called()
        self.assertIn('ページ切り替え待ち', self.bridge.get_auto_capture()['message'])

    def test_challenge_waits_then_resumes_without_off(self):
        valid = self.probe
        self.probe = dict(error='確認画面で待機')
        self.bridge._auto_tick()
        self.bridge._spawn.assert_not_called()
        self.assertTrue(self.bridge.get_auto_capture()['enabled'])
        self.probe = valid
        self.now += 1
        self.bridge._auto_tick()
        self.bridge._spawn.assert_called_once()

    def test_machine_list_dispatch_is_guarded_and_keeps_on(self):
        self.probe = dict(kind='machines', url=self.url)
        self.bridge._auto_tick()
        self.now += 1
        self.bridge._auto_tick()
        scripts = [call.args[0] for call in self.bridge._window.evaluate_js.call_args_list]
        self.assertEqual(sum(s.startswith('window.__databaseAutoMoveMachine(') for s in scripts), 2)
        self.assertTrue(self.bridge.get_auto_capture()['enabled'])
        self.bridge._loaded()
        self.now += 1
        self.bridge._auto_tick()
        scripts = [call.args[0] for call in self.bridge._window.evaluate_js.call_args_list]
        self.assertEqual(sum(s.startswith('window.__databaseAutoMoveMachine(') for s in scripts), 3)

    def test_delayed_machine_commit_after_off_or_navigation_is_cancelled(self):
        for action in (lambda: self.bridge.set_auto_capture(False, 0.1), self.bridge._loading):
            self.bridge.set_auto_capture(True, 0.1)
            revision = self.bridge.get_auto_capture()['revision']
            action()
            self.bridge._window.evaluate_js.reset_mock()
            self.assertFalse(self.bridge.commit_auto_move(revision))
            self.bridge._window.evaluate_js.assert_not_called()

    def test_delayed_machine_commit_is_allowed_only_for_current_run(self):
        revision = self.bridge.get_auto_capture()['revision']
        self.assertTrue(self.bridge.commit_auto_move(revision))
        self.bridge._window.evaluate_js.assert_called_with(
            'window.__databaseFinishMachine && window.__databaseFinishMachine()')

    def test_off_cancels_save_completion_navigation(self):
        revision = self.bridge.get_auto_capture()['revision']
        self.bridge._pending_advance = ({'next_url': self.url}, revision,
                                        self.bridge._auto_session, self.url)
        self.bridge.set_auto_capture(False, 0.1)
        self.bridge._window.evaluate_js.reset_mock()
        self.bridge._poll_advance()
        self.bridge._window.evaluate_js.assert_not_called()
        self.assertIsNone(self.bridge._pending_advance)

    def test_challenge_defers_save_completion_navigation_then_resumes(self):
        revision = self.bridge.get_auto_capture()['revision']
        self.bridge._pending_advance = ({'next_url': self.url}, revision,
                                        self.bridge._auto_session, self.url)
        self.bridge._window.evaluate_js.side_effect = None
        self.bridge._window.evaluate_js.return_value = False
        self.bridge._poll_advance()
        self.assertIsNotNone(self.bridge._pending_advance)
        self.assertTrue(self.bridge.get_auto_capture()['enabled'])
        self.bridge._window.evaluate_js.return_value = True
        self.bridge._poll_advance()
        self.assertIsNone(self.bridge._pending_advance)

    def test_save_continues_after_same_page_reload(self):
        revision = self.bridge.get_auto_capture()['revision']
        self.bridge._pending_advance = ({'next_url': self.url}, revision,
                                        self.bridge._auto_session, self.url)
        self.bridge._loading()
        self.bridge._poll_advance()
        self.assertIsNotNone(self.bridge._pending_advance)
        self.bridge._loaded()
        self.bridge._window.evaluate_js.side_effect = None
        self.bridge._window.evaluate_js.return_value = True
        self.bridge._poll_advance()
        self.assertIsNone(self.bridge._pending_advance)
        self.assertTrue(any('__databaseAutoAdvance' in call.args[0]
                            for call in self.bridge._window.evaluate_js.call_args_list))

    def test_save_continues_after_challenge_returns_to_source(self):
        revision = self.bridge.get_auto_capture()['revision']
        self.bridge._pending_advance = ({'next_url': self.url}, revision,
                                        self.bridge._auto_session, self.url)
        self.bridge._window.get_current_url.return_value = self.url + '&challenge=1'
        self.bridge._window.evaluate_js.side_effect = lambda script: (
            {'error': 'ON・確認画面で待機中'} if '__databaseAutoWaitReason' in script else True)
        self.bridge._poll_advance()
        self.assertIsNotNone(self.bridge._pending_advance)
        self.bridge._window.get_current_url.return_value = self.url
        self.bridge._loaded()
        self.bridge._poll_advance()
        self.assertIsNone(self.bridge._pending_advance)

    def test_old_save_cannot_move_after_off_then_on(self):
        revision = self.bridge.get_auto_capture()['revision']
        self.bridge._pending_advance = ({'next_url': self.url}, revision,
                                        self.bridge._auto_session, self.url)
        self.bridge.set_auto_capture(False, 0.1)
        self.bridge.set_auto_capture(True, 0.1)
        self.bridge._window.evaluate_js.reset_mock()
        self.bridge._poll_advance()
        self.assertIsNone(self.bridge._pending_advance)
        self.bridge._window.evaluate_js.assert_not_called()

    def test_old_save_cannot_override_a_different_page(self):
        revision = self.bridge.get_auto_capture()['revision']
        self.bridge._pending_advance = ({'next_url': self.url}, revision,
                                        self.bridge._auto_session, self.url)
        self.bridge._window.get_current_url.return_value = self.url.replace('rack_no=710', 'rack_no=711')
        self.bridge._window.evaluate_js.side_effect = lambda script: None
        self.bridge._poll_advance()
        self.assertIsNone(self.bridge._pending_advance)
        self.assertFalse(any('__databaseAutoAdvance' in call.args[0]
                             for call in self.bridge._window.evaluate_js.call_args_list))

    def test_signal_paths_are_unique_to_browser(self):
        other = _Bridge('unused.db', 'unused-reports', 'unused.py')
        self.assertNotEqual(other._signal_path, self.bridge._signal_path)

    def test_off_does_not_reenable_legacy_movement_on_new_document(self):
        self.bridge.set_auto_capture(False, 0.1)
        self.bridge._loaded()
        self.assertFalse(self.bridge.get_auto_capture()['manual_continuation'])

    def test_manual_and_auto_race_start_only_one_save(self):
        bridge = _Bridge('unused.db', 'unused-reports', 'unused.py')
        bridge.set_auto_capture(True, 0.1)
        generation = bridge.get_auto_capture()['revision']
        bridge._spawn_unlocked = Mock(side_effect=lambda *args: bridge._children.append(
            Mock(poll=Mock(return_value=None))))
        barrier = threading.Barrier(2)
        def run(automatic):
            barrier.wait()
            if automatic:
                bridge._auto.submit(generation, 'page', lambda: bridge._spawn('graph', '{}'))
            else:
                bridge._spawn('graph', '{}')
        threads = [threading.Thread(target=run, args=(automatic,), daemon=True) for automatic in (True, False)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive(), 'save admission deadlock')
        bridge._spawn_unlocked.assert_called_once()

    def test_repaired_payload_on_same_page_can_resume(self):
        self.bridge._auto_tick()
        payload = json.loads(self.probe['raw'])
        payload['games'] = 1234
        self.probe['raw'] = json.dumps(payload)
        self.now += 1
        self.bridge._auto_tick()
        self.assertEqual(self.bridge._spawn.call_count, 2)

    def test_disallowed_url_does_not_invoke_capture(self):
        self.bridge._window.get_current_url.return_value = 'https://example.com/'
        self.bridge._auto_tick()
        self.bridge._spawn.assert_not_called()
        self.assertTrue(self.bridge.get_auto_capture()['enabled'])

    def test_navigation_or_busy_process_prevents_capture(self):
        self.bridge._loading()
        self.bridge._auto_tick()
        self.bridge._spawn.assert_not_called()
        self.bridge._loaded()
        self.now += 1
        self.bridge._children = [Mock(poll=Mock(return_value=None))]
        self.bridge._auto_tick()
        self.bridge._spawn.assert_not_called()

    def test_off_during_probe_prevents_spawn(self):
        def evaluate(script):
            if '__databaseAutoProbe' in script:
                self.bridge.set_auto_capture(False, 0.1)
                return self.probe
            return True
        self.bridge._window.evaluate_js.side_effect = evaluate
        self.bridge._auto_tick()
        self.bridge._spawn.assert_not_called()

    def test_spawn_guard_prevents_overlapping_manual_submission(self):
        bridge = _Bridge('unused.db', 'unused-reports', 'unused.py')
        bridge._children = [Mock(poll=Mock(return_value=None))]
        bridge._spawn_unlocked = Mock()
        self.assertFalse(bridge._spawn('graph', '{}'))
        bridge._spawn_unlocked.assert_not_called()

    def test_invalid_extracted_day_waits_without_off(self):
        self.probe['raw'] = json.dumps(dict(store='saiwaichou', target_date='not-a-date'))
        self.bridge._auto_tick()
        self.bridge._spawn.assert_not_called()
        self.assertTrue(self.bridge.get_auto_capture()['enabled'])


if __name__ == '__main__':
    unittest.main()
