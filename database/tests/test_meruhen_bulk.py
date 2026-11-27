"""メルヘン2店舗の一括取り込み（2026-11-28）：窓の中の段取り（BulkStart）と、親画面側の4窓の起動（BulkLauncher）。"""
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

import browser_import as bi
import forward_validation
import meruhen_bulk

DAY = bi.recent_days()[1]
LIST = {s: bi.machine_list_page(s) for s in bi.BROWSER_URLS}


class FakeConnection:
    failure = None


class FakeBridge:
    def __init__(self):
        self._completed = None
        self._connection = FakeConnection()
        self._overlay_ready = threading.Event()
        self._overlay_ready.set()
        self._documents = 1
        self._pending_advance = None
        self._children = []
        self.calls = []
        self.auto = {'enabled': False, 'seconds': 3.5, 'message': '停止中', 'revision': 0}

    def set_auto_capture(self, enabled, seconds=3.5, day=None, direction=None):
        self.calls.append((enabled, seconds, day, direction))
        self.auto = dict(self.auto, enabled=enabled, message='次の取り込みを待っています')
        return dict(self.auto)

    def get_auto_capture(self):
        return dict(self.auto)

    def _render_auto(self):
        pass


class FakeWindow:
    def __init__(self, url):
        self.url = url
        self.wait = None
        self.missing = False  # 取り込みカードの判定の部品がまだ入っていないページ
        self.probe = None
        self.loads = []

    def get_current_url(self):
        return self.url

    def load_url(self, url):
        self.loads.append(url)

    def evaluate_js(self, script):
        if '__databaseAutoWaitReason' in script:
            if self.missing:
                return {'missing': True}
            return self.wait if self.wait is not None else {'ok': True}
        if '__databaseAutoProbe' in script:
            return self.probe
        return None


class BulkStartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.status = Path(self.tmp.name) / bi.BULK_FOLDER / 'w1.json'

    def starter(self, store='saiwaichou', direction='bottom'):
        return bi.BulkStart(store, DAY, direction, self.status)

    def read(self):
        return json.loads(self.status.read_text(encoding='utf-8'))

    def test_entry_page_moves_to_the_machine_list_once_per_page_then_starts_with_the_shared_day_and_direction(self):
        bridge, window, starter = FakeBridge(), FakeWindow(bi.BROWSER_URLS['saiwaichou']), self.starter()
        starter.step(bridge, window)
        starter.step(bridge, window)  # 同じページでは2回目の移動を出さない
        self.assertEqual(window.loads, [LIST['saiwaichou']])
        self.assertEqual(self.read()['state'], 'preparing')
        bridge._documents += 1
        window.url = LIST['saiwaichou']
        window.probe = {'error': 'ON・読み込み完了待ち'}
        window.wait = {'error': 'ON・読み込み完了待ち'}
        starter.step(bridge, window)
        self.assertEqual(bridge.calls, [])  # 一覧の準備ができるまでは始めない
        window.wait, window.probe = None, {'kind': 'machines', 'url': window.url}
        starter.step(bridge, window)
        self.assertEqual(bridge.calls, [(True, 3.5, DAY, 'bottom')])
        status = self.read()
        self.assertEqual((status['state'], status['label'], status['store'], status['direction'], status['day']),
                         ('running', '取り込み中', 'saiwaichou', 'bottom', DAY))
        starter.step(bridge, window)
        self.assertEqual(len(bridge.calls), 1)  # 1回だけ始める

    def test_challenge_before_start_waits_without_moving_and_continues_after_it_is_done(self):
        bridge, window, starter = FakeBridge(), FakeWindow(bi.BROWSER_URLS['nagamachiminami']), self.starter('nagamachiminami', 'top')
        flashes = []
        starter.flash = flashes.append  # タスクバーの点滅（認証待ちに入ったら点滅、抜けたら止める）
        window.wait = {'error': 'ON・確認画面で待機中。手動で確認してください。'}
        starter.step(bridge, window)
        starter.step(bridge, window)
        self.assertEqual(flashes, [True])
        self.assertEqual(self.read()['state'], 'auth')
        self.assertEqual(self.read()['label'], '人間認証待ち')
        self.assertEqual(window.loads, [])  # 認証の画面からは動かさない
        bridge._overlay_ready.clear()  # 確認画面が自分で読み込み直している間も「人間認証待ち」のまま
        starter.step(bridge, window)
        self.assertEqual(self.read()['state'], 'auth')
        bridge._overlay_ready.set()
        # 読み込み直した直後で、判定の部品がまだ無い：認証が済んだとは見なさず、動かない（模擬ページの試験で見つけた素通り）
        window.wait, window.missing = None, True
        starter.step(bridge, window)
        self.assertEqual((self.read()['state'], window.loads), ('auth', []))
        window.missing = False
        bridge._documents += 1
        window.wait = None  # 利用者が済ませて、店の画面に戻った
        starter.step(bridge, window)
        self.assertEqual(window.loads, [LIST['nagamachiminami']])
        self.assertEqual(flashes, [True, False])
        bridge._documents += 1
        window.url, window.probe = LIST['nagamachiminami'], {'kind': 'machines'}
        starter.step(bridge, window)
        self.assertEqual(bridge.calls, [(True, 3.5, DAY, 'top')])
        self.assertEqual(flashes, [True, False])

    def test_flash_failure_does_not_stop_the_window(self):
        starter = self.starter()
        starter.flash = lambda on: 1 / 0
        starter.report('auth', 'x')
        self.assertEqual(self.read()['state'], 'auth')

    def test_flash_taskbar_finds_no_window_for_an_unknown_title(self):
        self.assertFalse(bi.flash_taskbar('database ブラウザ取り込み（存在しない窓）', True))

    def test_outside_page_is_shown_as_authentication_and_other_store_is_moved_to_its_own_list(self):
        bridge, starter = FakeBridge(), self.starter('saiwaichou', 'top')
        window = FakeWindow('https://example.com/challenge')
        starter.step(bridge, window)
        self.assertEqual(self.read()['state'], 'auth')
        window = FakeWindow(LIST['nagamachiminami'])  # 別の店の一覧では始めない
        window.probe = {'kind': 'machines'}
        starter.step(bridge, window)
        self.assertEqual(bridge.calls, [])
        self.assertEqual(window.loads, [LIST['saiwaichou']])

    def test_challenge_while_running_waits_and_resumes_without_pressing_start_again(self):
        bridge, window, starter = FakeBridge(), FakeWindow(LIST['saiwaichou']), self.starter()
        window.probe = {'kind': 'machines'}
        starter.step(bridge, window)
        self.assertTrue(starter.started)
        bridge.auto['message'] = 'ON・確認画面の終了後に次へ進みます'
        starter.step(bridge, window)
        self.assertEqual(self.read()['state'], 'auth')
        window.wait = {'error': 'ON・確認画面で待機中。手動で確認してください。'}
        bridge.auto['message'] = '次の取り込みを待っています'
        starter.step(bridge, window)
        self.assertEqual(self.read()['state'], 'auth')
        # 読み込み直した直後で判定の部品がまだ無い：認証待ちのまま、移動もしない
        window.wait, window.missing = None, True
        window.url = bi.BROWSER_URLS['saiwaichou']
        starter.step(bridge, window)
        self.assertEqual((self.read()['state'], window.loads), ('auth', []))
        window.missing = False
        # 済ませたあと店の入口に戻った：同じ日・向きのまま、一覧へ戻して続ける（開始は押し直さない）
        window.wait = None
        bridge._documents += 1
        starter.step(bridge, window)
        self.assertEqual(self.read()['state'], 'running')
        self.assertEqual(window.loads, [LIST['saiwaichou']])
        self.assertEqual(bridge.calls, [(True, 3.5, DAY, 'bottom')])
        starter.step(bridge, window)
        self.assertEqual(window.loads, [LIST['saiwaichou']])  # 同じページでは1回だけ

    def test_running_window_reports_done_and_stopped(self):
        bridge, window, starter = FakeBridge(), FakeWindow(LIST['saiwaichou']), self.starter()
        window.probe = {'kind': 'machines'}
        starter.step(bridge, window)
        bridge.auto['enabled'] = False  # 利用者が窓の停止ボタンを押した
        starter.step(bridge, window)
        self.assertEqual(self.read()['state'], 'stopped')
        bridge._completed = '11/27 長町南：未取り込みの機種はありません（自動取り込みを停止しました）'
        starter.step(bridge, window)
        self.assertEqual((self.read()['state'], self.read()['message']), ('done', bridge._completed))

    def test_connection_failure_before_start_is_stopped(self):
        bridge, window, starter = FakeBridge(), FakeWindow(bi.BROWSER_URLS['saiwaichou']), self.starter()
        bridge._connection.failure = {'message': 'ページの通信に失敗しました。'}
        starter.step(bridge, window)
        self.assertEqual(self.read()['state'], 'stopped')
        self.assertEqual(window.loads, [])

    def test_real_bridge_starts_on_the_given_store_and_accepts_the_shared_day(self):
        bridge = bi._Bridge(Path(self.tmp.name) / 'db.sqlite3', Path(self.tmp.name), __file__,
                            start_url=bi.BROWSER_URLS['saiwaichou'])
        self.assertEqual(bridge._start_url, bi.BROWSER_URLS['saiwaichou'])
        state = bridge.set_auto_capture(True, 3.5, DAY, 'bottom')
        self.assertTrue(state['enabled'])
        self.assertEqual((state['target_day'], state['direction']), (DAY, 'bottom'))
        bridge.set_auto_capture(False, 3.5)


class PageAndArgsTests(unittest.TestCase):
    def test_page_kind(self):
        host = bi.BROWSER_URLS['saiwaichou'].split('/saiwaichou/')[0]
        self.assertEqual(bi.page_kind(host + '/saiwaichou/rack_info_kt/?kind_code=21', 'saiwaichou'), 'list')
        self.assertEqual(bi.page_kind(host + '/saiwaichou/rack_info_kt?kind_code=21', 'saiwaichou'), 'list')
        self.assertEqual(bi.page_kind(host + '/saiwaichou/rack_info_kt/?kind_code=4', 'saiwaichou'), 'store_page')
        self.assertEqual(bi.page_kind(host + '/saiwaichou/rack_info', 'saiwaichou'), 'store_page')
        self.assertEqual(bi.page_kind(host + '/saiwaichou/standlist_slot/?kind_code=21&machine_name=A', 'saiwaichou'), 'capture')
        self.assertEqual(bi.page_kind(host + '/saiwaichou/standgraph/?rack_no=1', 'saiwaichou'), 'capture')
        self.assertEqual(bi.page_kind(host + '/nagamachiminami/rack_info', 'saiwaichou'), 'other_store')
        self.assertEqual(bi.page_kind('https://example.com/x', 'saiwaichou'), 'outside')
        self.assertEqual(bi.page_kind('', 'saiwaichou'), 'outside')

    def test_order_for_direction(self):
        items = [f'M{i}' for i in range(1, 15)]
        self.assertEqual(bi.order_for_direction(items, 'top'), items)
        self.assertEqual(bi.order_for_direction(items, 'bottom'), items[::-1])
        # 10機種目から下へ、最後のあと先頭へ戻って残り
        self.assertEqual(bi.order_for_direction(items, 'tenth'), items[9:] + items[:9])
        self.assertEqual(bi.order_for_direction(items[:4], 'tenth'), ['M4', 'M1', 'M2', 'M3'])  # 10機種に満たない一覧は最後の機種から
        self.assertEqual(bi.order_for_direction([], 'tenth'), [])

    def test_next_machine_follows_the_tenth_direction(self):
        import tempfile as _t
        from core import Store
        folder = Path(_t.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(folder, ignore_errors=True))
        Store(folder / 'db.sqlite3').close()
        bridge = bi._Bridge(folder / 'db.sqlite3', folder, __file__)
        bridge.set_target_day(DAY, 'tenth')
        host = bi.BROWSER_URLS['saiwaichou'].split('/saiwaichou/')[0]
        machines = [{'name': f'M{i}', 'url': f'{host}/saiwaichou/standlist_slot/?kind_code=21&machine_name=M{i}', 'count': 1}
                    for i in range(1, 13)]
        result = json.loads(bridge._next_unimported_machine({'store': 'saiwaichou', 'day': DAY, 'kind_code': '21',
                                                              'machines': machines}))
        self.assertEqual(result.get('machine'), 'M10', result)

    def test_session_args(self):
        positional, store, bulk, slot = bi.parse_session_args(['db', 'rep', 'abc', '--store', 'saiwaichou',
                                                               '--day', DAY, '--direction', 'bottom', '--slot', '3'])
        self.assertEqual((positional, store, bulk, slot), (['db', 'rep', 'abc'], 'saiwaichou',
                                                           {'day': DAY, 'direction': 'bottom'}, 3))
        self.assertEqual(bi.parse_session_args(['db', 'rep', 'abc']), (['db', 'rep', 'abc'], None, None, 0))
        self.assertEqual(bi.parse_session_args(['db', 'rep', 'abc', '--store', 'saiwaichou'])[1:3], ('saiwaichou', None))
        for bad in (['--store', 'x'], ['--day', DAY], ['--store', 'saiwaichou', '--day', DAY, '--direction', 'side'],
                    ['--store', 'saiwaichou', '--day', 'x', '--direction', 'top'], ['--store']):
            with self.assertRaises(ValueError, msg=bad):
                bi.parse_session_args(bad)

    def test_bulk_windows_count_as_meruhen_capture_windows(self):
        self.assertEqual(forward_validation.window_source('メルヘン'), 'meruhen')
        self.assertEqual(forward_validation.window_source('メルヘン（幸町・下）'), 'meruhen')
        self.assertEqual(forward_validation.window_source('サイトセブン'), 'pscube')
        self.assertEqual(forward_validation.window_source('アナスロ'), 'other')

    def test_business_day_is_decided_at_3am(self):
        self.assertEqual(bi.today_iso(datetime(2026, 11, 28, 2, 59)), '2026-11-27')
        self.assertEqual(bi.today_iso(datetime(2026, 11, 28, 3, 0)), '2026-11-28')


class FakeProcess:
    def __init__(self, command):
        self.command = command
        self.code = None

    def poll(self):
        return self.code


class BulkLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.days = iter(['2026-11-27'] + ['2026-11-28'] * 5)
        self.processes = []

        def popen(command):
            process = FakeProcess(command)
            self.processes.append(process)
            return process
        self.launcher = meruhen_bulk.BulkLauncher(self.data, lambda wid: ['python', 'browser_import.py', 'db', 'rep', wid],
                                                  popen, today=lambda: next(self.days))

    def options(self, process):
        c = process.command
        return c[c.index('--store') + 1], c[c.index('--day') + 1], c[c.index('--direction') + 1], c[c.index('--slot') + 1]

    def test_one_press_opens_three_windows_per_store_in_order_with_one_shared_day(self):
        started, skipped, failed = self.launcher.launch()
        self.assertEqual((skipped, failed), ([], []))
        self.assertEqual([self.options(p) for p in self.processes], [
            ('nagamachiminami', '2026-11-27', 'top', '0'), ('nagamachiminami', '2026-11-27', 'bottom', '1'),
            ('nagamachiminami', '2026-11-27', 'tenth', '2'),
            ('saiwaichou', '2026-11-27', 'top', '3'), ('saiwaichou', '2026-11-27', 'bottom', '4'),
            ('saiwaichou', '2026-11-27', 'tenth', '5')])
        self.assertEqual([w.label for w in started], ['長町南・上', '長町南・下', '長町南・10機種目から',
                                                      '幸町・上', '幸町・下', '幸町・10機種目から'])
        self.assertEqual(len({w.window_id for w in started}), 6)
        self.assertTrue(all(p.command[4] == w.window_id for p, w in zip(self.processes, started)))

    def test_pressing_again_does_not_open_running_windows_twice(self):
        self.days = iter(['2026-11-27'] * 3)
        self.launcher.today = lambda: next(self.days)
        self.launcher.launch()
        started, skipped, _ = self.launcher.launch()
        self.assertEqual((started, skipped), ([], ['長町南・上', '長町南・下', '長町南・10機種目から',
                                                  '幸町・上', '幸町・下', '幸町・10機種目から']))
        self.assertEqual(len(self.processes), 6)
        self.processes[4].code = 0  # 幸町・下だけ閉じた
        started, skipped, _ = self.launcher.launch()
        self.assertEqual([w.label for w in started], ['幸町・下'])
        self.assertEqual(len(skipped), 5)
        self.assertEqual(len(self.processes), 7)

    def test_one_failed_launch_does_not_stop_the_others(self):
        def popen(command):
            if 'nagamachiminami' in command and 'bottom' in command:
                raise OSError('起動できません')
            process = FakeProcess(command)
            self.processes.append(process)
            return process
        self.launcher.popen = popen
        started, _, failed = self.launcher.launch()
        self.assertEqual([w.label for w in started], ['長町南・上', '長町南・10機種目から', '幸町・上', '幸町・下', '幸町・10機種目から'])
        self.assertEqual([label for label, _ in failed], ['長町南・下'])

    def test_status_lines(self):
        started, _, _ = self.launcher.launch()
        up, down, _tenth, s_up, s_down, _s_tenth = started
        self.assertEqual(up.text(self.data), ('preparing', '長町南・上　準備中（取り込み窓を開いています）'))
        bi.BulkStart('nagamachiminami', up.day, 'bottom', bi.bulk_status_path(self.data, down.window_id)).report(
            'auth', '人間認証の画面です。')
        self.assertEqual(down.text(self.data), ('auth', '長町南・下　人間認証待ち（人間認証の画面です。）'))
        # 自分で閉じた（完了の知らせあり）→完了、×で閉じた→中断
        self.processes[3].code = 0
        from file_io import write_notice
        write_notice(bi.finished_path(self.data, s_up.window_id), '完了の文')
        self.assertEqual(s_up.status(self.data), ('done', ''))
        s_up.finished = bi.take_finished_message(self.data, s_up.window_id)
        self.assertEqual(s_up.status(self.data), ('done', '完了の文'))
        self.processes[4].code = 1
        self.assertEqual(s_down.status(self.data), ('stopped', '窓が閉じられました'))
        self.assertEqual([w.label for w in self.launcher.rows()], ['長町南・上', '長町南・下', '長町南・10機種目から',
                                                                   '幸町・上', '幸町・下', '幸町・10機種目から'])


if __name__ == '__main__':
    unittest.main()
