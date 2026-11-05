import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path

from datetime import datetime

from pscube_import import BROWSER_ARGUMENTS, PscubeIndexRetry, PscubeStore, ROOT_URL, business_day, keep_page_timers, installation_count, recent_business_days, same_page, table_url_for_day


class PscubeImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = PscubeStore(Path(self.tmp.name) / 'pscube.sqlite3')
        self.addCleanup(self.store.close)
        self.day = '2026-10-01'
        self.index_url = ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2'
        self.machines = [
            {'store': 'c740601', 'rate': '20', 'machine': name,
             'expected_count': 1,
             'url': ROOT_URL + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu={name}'}
            for name in ('L東京喰種', 'ﾏｲｼﾞｬｸﾞﾗｰV')
        ]

    def page(self, url, machines, records=()):
        return {'format': 'pscube-viewer', 'version': 1, 'source_url': url,
                'machines': machines, 'records': list(records)}

    def record(self, machine, rack, day=None):
        day = day or self.day
        return {'store': 'c740601', 'rate': '20', 'machine': machine['machine'],
                'rack': rack, 'day': day, 'bb': 13, 'rb': 5, 'at_art': 0,
                'games': 1854, 'my': 1921, 'observed_at': '2026-10-01T12:00:00+09:00',
                'detail_url': ROOT_URL + f'cgi-bin/nc-v06-001.php?cd_dai={rack}#{day.replace("-", "")}',
                'graph': {'kind': 'overview', 'zero_y': 10, 'points': [[0, 10], [1, 8]]}}

    def test_capture_window_keeps_page_timers_when_hidden(self):
        # 2026-10-28：見えない窓で時計が抑えられ、全台一覧が6台のまま時間切れになった。起動設定に足す。
        environ = {}
        keep_page_timers(environ)
        arguments = environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']
        for flag in ('IntensiveWakeUpThrottling', 'CalculateNativeWinOcclusion', 'ElasticOverscroll',
                     '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                     '--disable-backgrounding-occluded-windows'):
            self.assertIn(flag, arguments)
        keep_page_timers(environ)
        self.assertEqual(environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'], arguments, '2回目で重ねない')
        environ = {'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS': '--lang=ja'}
        keep_page_timers(environ)
        self.assertEqual(environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'], '--lang=ja ' + BROWSER_ARGUMENTS)

    def test_business_day_changes_at_3am_japan_time(self):
        # 2026-10-26に2時から3時へ。
        self.assertEqual(business_day(datetime(2026, 10, 4, 2, 59)), '2026-10-03')
        self.assertEqual(business_day(datetime(2026, 10, 4, 3, 0)), '2026-10-04')
        self.assertEqual(business_day(datetime(2026, 10, 4, 23, 30)), '2026-10-04')
        days = recent_business_days(datetime(2026, 10, 4, 1, 0))
        self.assertEqual((days[0], days[1], days[-1], len(days)), ('2026-10-03', '2026-10-02', '2026-09-27', 7))

    def test_auto_confirms_decreased_index_after_reopening(self):
        machines = [{**self.machines[0], 'machine': f'L機種{n}',
                     'url': ROOT_URL + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=L機種{n}'}
                    for n in range(5)]
        self.store.import_page(self.page(self.index_url, machines), self.index_url)
        previous = self.store._state('active_machine_keys')
        reduced = machines[:3]
        with self.assertRaises(PscubeIndexRetry) as first:
            self.store.import_page(self.page(self.index_url, reduced), self.index_url)
        self.assertEqual(self.store._state('active_machine_keys'), previous)
        # 入れ替えの日に読み切れなかった一覧は、前の集合と異なるので再確認する。
        changed = machines[:2] + [{**machines[0], 'machine': 'L新台',
                                   'url': ROOT_URL + 'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=L新台'}]
        self.store.index_confirmation = first.exception.keys
        with self.assertRaises(PscubeIndexRetry) as second:
            self.store.import_page(self.page(self.index_url, changed), self.index_url)
        self.assertEqual(self.store._state('active_machine_keys'), previous)
        self.store.index_confirmation = second.exception.keys
        self.store.import_page(self.page(self.index_url, list(reversed(changed))), self.index_url)
        self.assertEqual(len(json.loads(self.store._state('active_machine_keys'))), 3)
        # 撤去だけでも最初は保存せず、再確認後に保存する。
        with self.assertRaises(PscubeIndexRetry) as third:
            self.store.import_page(self.page(self.index_url, changed[:2]), self.index_url)
        self.assertEqual(len(json.loads(self.store._state('active_machine_keys'))), 3)
        self.store.index_confirmation = third.exception.keys
        self.store.import_page(self.page(self.index_url, changed[:2]), self.index_url)
        self.assertEqual(len(json.loads(self.store._state('active_machine_keys'))), 2)

    def test_auto_retry_survives_store_reopen_and_counts_toward_the_page_limit(self):
        from auto_capture import AutoCapture
        from pscube_import import AutoPilot, submit_capture
        from test_pscube_auto import Clock, FakeWindow, PROBE
        clock = Clock()
        pilot = AutoPilot(FakeWindow(), PROBE,
                          auto=AutoCapture(clock=clock, minimum=5, maximum=60, default=10))
        pilot.configure(True, 10)
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        before = self.store._state('active_machine_keys')
        reduced = self.page(self.index_url, self.machines[:1])
        with patch('pscube_import.auto_backup', return_value='backup') as backup:
            pilot.pending = 'index'
            retry = submit_capture(self.store.path, Path(self.tmp.name) / 'viewer.json',
                                   pilot, reduced, self.index_url)
            pilot.finished(result=retry)
            self.assertTrue(retry['retry_index'])
            self.assertEqual(retry['next_url'], self.index_url)
            self.assertEqual(self.store._state('active_machine_keys'), before)
            # 再確認も同じページの失敗に数える（開き直しは3回まで）。保存できたら数えをやめる。
            self.assertEqual(pilot.failures.get('index', 0), 1)
            self.assertNotEqual(retry.get('reload'), False)
            backup.assert_not_called()
            # 読み込み完了の通知が無ければ、同じ内容でも再確認とは扱わない。
            retry_again = submit_capture(self.store.path, Path(self.tmp.name) / 'viewer.json',
                                         pilot, reduced, self.index_url)
            self.assertTrue(retry_again['retry_index'])
            self.assertEqual(self.store._state('active_machine_keys'), before)
            pilot.loaded()
            pilot.pending = 'index'
            saved = submit_capture(self.store.path, Path(self.tmp.name) / 'viewer.json',
                                   pilot, reduced, self.index_url)
            pilot.finished(result=saved)
            self.assertNotIn('retry_index', saved)
            self.assertEqual(len(json.loads(self.store._state('active_machine_keys'))), 1)
            self.assertNotIn('index', pilot.failures)
            backup.assert_called_once()

    def test_index_retry_does_not_reload_after_stop_or_connection_failure(self):
        from auto_capture import AutoCapture
        from pscube_import import AutoPilot
        from test_pscube_auto import Clock, FakeWindow, PROBE
        for stop in ('off', 'connection'):
            with self.subTest(stop=stop):
                pilot = AutoPilot(FakeWindow(), PROBE,
                                  auto=AutoCapture(clock=Clock(), minimum=5, maximum=60, default=10))
                pilot.configure(True, 10)
                pilot.pending = 'index'
                pilot.index_confirmation = {'machine'}
                pilot.index_confirmation_page = 0
                if stop == 'off':
                    pilot.configure(False, 10)
                else:
                    pilot.connection_failed('通信エラー')
                self.assertIsNone(pilot.index_confirmation)
                # 停止直後に保存処理から返った古い再確認の結果も、再読み込みさせない。
                pilot.index_confirmation = {'late-result'}
                result = {'retry_index': True, 'next_url': self.index_url}
                pilot.finished(result=result)
                self.assertFalse(result['reload'])
                self.assertIsNone(pilot.index_confirmation)
                self.assertIsNone(pilot.index_confirmation_page)

    def test_auto_stops_reopening_an_index_that_differs_every_time(self):
        # 開き直すたびに違う減った一覧が返り続けても、一晩じゅう開き直さない（3回で止めて待機）。
        from auto_capture import AutoCapture
        from pscube_import import AutoPilot, submit_capture
        from test_pscube_auto import Clock, FakeWindow, PROBE
        machines = [{**self.machines[0], 'machine': f'L機種{n}',
                     'url': ROOT_URL + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=L機種{n}'}
                    for n in range(6)]
        pilot = AutoPilot(FakeWindow(), PROBE,
                          auto=AutoCapture(clock=Clock(), minimum=5, maximum=60, default=10))
        pilot.configure(True, 10)
        self.store.import_page(self.page(self.index_url, machines), self.index_url)
        before = self.store._state('active_machine_keys')
        results = []
        with patch('pscube_import.auto_backup', return_value='backup') as backup:
            for size in (2, 3, 4):
                pilot.pending = 'index'
                result = submit_capture(self.store.path, Path(self.tmp.name) / 'viewer.json',
                                        pilot, self.page(self.index_url, machines[:size]), self.index_url)
                pilot.finished(result=result)
                pilot.loaded()
                results.append(result)
        self.assertTrue(all(r['retry_index'] for r in results))
        self.assertEqual([r.get('reload', True) for r in results], [True, True, False])
        self.assertEqual(pilot.failures['index'], AutoPilot.MAX_FAILURES)
        self.assertEqual(self.store._state('active_machine_keys'), before)
        backup.assert_not_called()

    def test_auto_never_accepts_an_index_far_below_the_usual_machine_count(self):
        # 2026-11-03 利用者「pscubeまた完了したとかいってるのに全機種読み込めてないな」：11/1は19機種・11/2は38機種
        # （いつもは59機種）。途中で止まった一覧が開き直しても同じに返り、「同じなら受け付ける」で保存されていた。
        from auto_capture import AutoCapture
        from pscube_import import AutoPilot, submit_capture
        from test_pscube_auto import Clock, FakeWindow, PROBE
        machines = [{**self.machines[0], 'machine': f'L機種{n}',
                     'url': ROOT_URL + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=L機種{n}'}
                    for n in range(10)]
        # 10機種そろった日の記録（いつもの機種数＝10）と、途中までの日（3機種）。
        with self.store.db:
            for i, m in enumerate(machines):
                for day in ('2026-10-02',) + (('2026-10-03',) if i < 3 else ()):
                    r = dict(store=m['store'], rate=m['rate'], machine=m['machine'], rack=100 + i, day=day)
                    self.store.db.execute('INSERT INTO records VALUES (?,?)',
                                          (json.dumps([m['store'], m['rate'], m['machine'], 100 + i, day]),
                                           json.dumps(r, ensure_ascii=False)))
        self.assertEqual(self.store._usual_machine_count(), 10)
        pilot = AutoPilot(FakeWindow(), PROBE, auto=AutoCapture(clock=Clock(), minimum=5, maximum=60, default=10))
        pilot.configure(True, 10)
        self.store.import_page(self.page(self.index_url, machines), self.index_url)
        before = self.store._state('active_machine_keys')
        results = []
        with patch('pscube_import.auto_backup', return_value='backup') as backup:
            for _ in range(3):   # 同じ7機種の一覧が3回返る
                pilot.pending = 'index'
                result = submit_capture(self.store.path, Path(self.tmp.name) / 'viewer.json',
                                        pilot, self.page(self.index_url, machines[:7]), self.index_url)
                pilot.finished(result=result)
                pilot.loaded()
                results.append(result)
        self.assertTrue(all(r['retry_index'] and r['short'] == [7, 10] for r in results))
        self.assertEqual([r.get('reload', True) for r in results], [True, True, False])
        self.assertEqual(self.store._state('active_machine_keys'), before, '途中の一覧で機種の並びを上書きしない')
        self.assertIn('途中までしか読めていません（いつもの10機種に対して7機種）', pilot.auto.state()['message'])
        self.assertIsNone(pilot.completed, '「すべて取り込みました」にしない')
        backup.assert_not_called()
        # 8割（8機種）なら今までどおり、開き直して同じなら受け付ける。手動は受け付ける。
        with self.assertRaises(PscubeIndexRetry) as retry:
            self.store.import_page(self.page(self.index_url, machines[:8]), self.index_url)
        self.assertIsNone(retry.exception.usual)
        self.store.index_confirmation = retry.exception.keys
        self.store.import_page(self.page(self.index_url, machines[:8]), self.index_url)
        self.assertEqual(len(json.loads(self.store._state('active_machine_keys'))), 8)
        self.store.import_page(self.page(self.index_url, machines[:7]), self.index_url, manual=True)
        self.assertEqual(len(json.loads(self.store._state('active_machine_keys'))), 7)

    def test_direction_picks_the_machine_from_the_top_or_the_bottom_of_the_list(self):
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        first, last = self.machines[0]['url'], self.machines[-1]['url']
        self.assertEqual(self.store.next_target(self.day, 'top')[0], first)
        self.assertEqual(self.store.next_target(self.day, 'bottom')[0], last)
        top = PscubeStore(Path(self.tmp.name) / 'top.sqlite3')
        bottom = PscubeStore(Path(self.tmp.name) / 'bottom.sqlite3')
        self.addCleanup(top.close)
        self.addCleanup(bottom.close)
        self.assertEqual(top.import_page(self.page(self.index_url, self.machines), self.index_url, direction='top')['next_url'], first)
        self.assertEqual(bottom.import_page(self.page(self.index_url, self.machines), self.index_url, direction='bottom')['next_url'], last)
        with self.assertRaises(ValueError):
            top.import_page(self.page(self.index_url, self.machines), self.index_url, direction='sideways')

    def test_expected_day_refuses_other_days_and_resumes_from_the_first_pending_page(self):
        yesterday, today = '2026-10-03', '2026-10-04'
        machine = self.machines[0]
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        # 日付が変わったあと、サイトの表示は新しい日。取り込み日（昨日）を指定していると保存しない。
        table_today = self.page(machine['url'], [dict(machine, expected_count=None)], [self.record(machine, 1526, today)])
        with self.assertRaisesRegex(ValueError, '取り込み日は2026-10-03ですが、表示中は2026-10-04'):
            self.store.import_page(table_today, machine['url'], expected_day=yesterday)
        self.assertEqual(self.store.days(), [], '保存されていない')
        # 昨日の日付タブに合わせれば保存できる。次は昨日の台別ページ。
        record = self.record(machine, 1526, yesterday)
        table = self.page(machine['url'], [dict(machine, expected_count=None)], [record])
        result = self.store.import_page(table, machine['url'], expected_day=yesterday)
        self.assertEqual(result['next_url'], record['detail_url'])
        # 台別ページ：ハッシュの日が取り込み日と違えば保存しない。
        history = [self.record(machine, 1526, (datetime.fromisoformat(yesterday) - __import__('datetime').timedelta(days=i)).date().isoformat()) for i in range(7)]
        rack = self.page(record['detail_url'], [dict(machine, expected_count=None)], history)
        with self.assertRaises(ValueError):
            self.store.import_page(rack, record['detail_url'], expected_day=today)
        self.store.import_page(rack, record['detail_url'], expected_day=yesterday)
        # 機種一覧を取り直しても、取り込み日とその日の基準の時刻が決まっていれば、最初の機種へ戻らず、昨日の未取得の先頭へ進む。
        known = {yesterday: '2026-10-01T12:00:00+09:00'}
        again = self.store.import_page(self.page(self.index_url, self.machines), self.index_url, expected_day=yesterday, fresh_since=known)
        self.assertEqual(again['next_url'], self.machines[1]['url'] + '#0;0;20261003;0;cd_dai;1;0;0')
        bottom = self.store.import_page(self.page(self.index_url, self.machines), self.index_url, expected_day=yesterday, direction='bottom', fresh_since=known)
        self.assertEqual(bottom['next_url'], self.machines[1]['url'] + '#0;0;20261003;0;cd_dai;1;0;0')
        # 基準の時刻がまだ無い（今回まだ1ページも保存していない）ときは、決めた向きの最初の機種で基準を確かめる。
        fresh = self.store.import_page(self.page(self.index_url, self.machines), self.index_url, expected_day=yesterday, direction='bottom')
        self.assertEqual(fresh['next_url'], self.machines[-1]['url'] + '#0;0;20261003;0;cd_dai;1;0;0')

    def test_machine_without_the_chosen_day_tab_is_skipped_only_for_that_day(self):
        # 2026-10-19 入れ替えの日に前日（10/18）を指定すると、新台は10/19のタブしか無く、サイトは10/19を選ぶ。
        # 以前は「対象のP’s CUBEページではありません」で止まり、新台が未取得の先頭に残り続けた。
        yesterday, today = '2026-10-18', '2026-10-19'
        new, old = self.machines
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        # WebViewの住所は機種名の%が保存したリンクと違う形（ここでは二重）で、#以降はサイトが選んだ10/19。
        shown = new['url'].replace('L東京喰種', 'L%25E6%259D%25B1%25E4%25BA%25AC%25E5%2596%25B0%25E7%25A8%25AE') + '#3;0;20261019;0;cd_dai;1;0;664'
        page = {'error': '1526番台の台別ページへのリンクがありません。', 'source_url': shown, 'available_days': [today]}
        result = self.store.import_page(json.dumps(page), shown, expected_day=yesterday)
        self.assertEqual(result['saved'], 0)
        self.assertIn('L東京喰種は10/18の日付タブがサイトにありません（タブ：10/19', result['skipped'])
        self.assertEqual(result['next_url'], old['url'] + '#0;0;20261018;0;cd_dai;1;0;0')
        self.assertEqual(self.store.days(), [], '何も保存しない')
        self.assertEqual(self.store.next_target(yesterday), (old['url'], 1), '10/18の未取得から外れる')
        self.assertEqual(self.store.next_target(today)[1], 2, 'ほかの日は今までどおり')
        reopened = PscubeStore(Path(self.tmp.name) / 'pscube.sqlite3')
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.next_target(yesterday)[1], 1, '開き直しても覚えている')
        # 飛ばさない場合：取り込み日のタブがある／タブより新しい日（早朝でタブがまだ出ていない）は、今までどおり理由を出して止める。
        for tabs, day in (([yesterday, today], yesterday), (['2026-10-12', yesterday], today)):
            with self.subTest(tabs=tabs, day=day), self.assertRaisesRegex(ValueError, '台別ページへのリンクがありません'):
                self.store.import_page(json.dumps(dict(page, available_days=tabs)), shown, expected_day=day)
        # 保存した機種一覧に無い機種は、飛ばさずに理由を出す。
        unknown = ROOT_URL + 'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=X#3;0;20261019;0;cd_dai;1;0;0'
        with self.assertRaisesRegex(ValueError, '日付タブがこの機種にありません（タブ：10/19）'):
            self.store.import_page(json.dumps(dict(page, source_url=unknown)), unknown, expected_day=yesterday)

    def test_racks_added_later_are_left_out_of_a_past_day_table(self):
        # 増台（4台→6台）の翌日に前日を取り込む：過去の日の全台一覧にも今の6台が並び、増えた2台はその日の
        # 数値もリンクも無い（2026-10-19 利用者「前の日の台数が出てくることはない」）。0で埋めず、残り4台を保存する。
        yesterday, today = '2026-10-18', '2026-10-19'
        machine = dict(self.machines[0], expected_count=6)
        self.store.import_page(self.page(self.index_url, [machine]), self.index_url)
        records = [self.record(machine, rack, yesterday) for rack in (1, 2, 3, 4)]
        table = dict(self.page(machine['url'], [dict(machine, expected_count=None)], records),
                     missing_racks=[5, 6], available_days=[yesterday, today])
        result = self.store.import_page(table, machine['url'], expected_day=yesterday)
        self.assertEqual(result['saved'], 4)
        self.assertEqual(result['kind'], '全台一覧（5・6番台はこの日の数値なし）')
        self.assertEqual(result['next_url'], records[0]['detail_url'], '全台一覧は済み。次は台別ページ')
        reopened = PscubeStore(Path(self.tmp.name) / 'pscube.sqlite3')
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.next_target(yesterday), (records[0]['detail_url'], 4), '開き直しても一覧を取り直さない')
        # 今動いている日（タブの最新）では、数値もリンクも無い台を受け付けない（読み込み途中かもしれない）。
        today_table = dict(table, records=[self.record(machine, rack, today) for rack in (1, 2, 3, 4)])
        with self.assertRaisesRegex(ValueError, '5・6番台に数値と台別ページへのリンクがありません'):
            self.store.import_page(today_table, machine['url'], expected_day=today)
        # 台数が合わなければ、今までどおり止める。
        with self.assertRaisesRegex(ValueError, '表示は5台、設置台数は6台'):
            self.store.import_page(dict(table, missing_racks=[5]), machine['url'], expected_day=yesterday)
        # 6台そろった一覧を取り直したら、その日に無かった台の記録は消える。
        full = self.page(machine['url'], [dict(machine, expected_count=None)],
                         [self.record(machine, rack, yesterday) for rack in range(1, 7)])
        self.store.import_page(dict(full, available_days=[yesterday, today]), machine['url'], expected_day=yesterday)
        self.assertEqual(self.store._absent_racks(), {})

    # ---- 全台一覧を保存できたら「タブなし」（absent_table_days）を外す（2026-10-22） ----
    # 以前は外さず、一度「その日はタブなし」と覚えた機種・日は、あとで正しい全台一覧を保存しても未取得から外れ続けた。
    TABS = ['2026-10-17', '2026-10-18', '2026-10-19']

    def six_and_other(self, alone=False):
        six = dict(self.machines[0], expected_count=6)
        other = self.machines[1]
        self.store.import_page(self.page(self.index_url, [six] if alone else [six, other]), self.index_url)
        return six, other

    def table(self, machine, day, racks, missing=(), games=1854):
        records = [dict(self.record(machine, rack, day), games=games) for rack in racks]
        data = dict(self.page(machine['url'], [dict(machine, expected_count=None)], records), available_days=self.TABS)
        return dict(data, missing_racks=list(missing)) if missing else data

    def skip_tab(self, machine, day, store=None):
        """取り込み日のタブが無い全台一覧（サイトは10/19を選ぶ）を読んだ結果を渡し、「タブなし」を覚えさせる。"""
        url = machine['url'] + '#3;0;20261019;0;cd_dai;1;0;664'
        page = {'error': '1526番台の台別ページへのリンクがありません。', 'source_url': url, 'available_days': ['2026-10-19']}
        result = (store or self.store).import_page(json.dumps(page), url, expected_day=day)
        self.assertEqual(result['saved'], 0)

    def absent(self, store=None):
        store = store or self.store
        key = lambda m: json.loads(m)[2]   # 機種名で読みやすく
        return (sorted((key(k), d) for k, d in store._absent_days()),
                {(key(k), d): r for (k, d), r in store._absent_racks().items()})

    def rows(self, store=None):
        return sorted((r['machine'], r['rack'], r['day'], r['games']) for r in
                      (json.loads(row[0]) for row in (store or self.store).db.execute('SELECT payload FROM records')))

    def reopened(self):
        store = PscubeStore(Path(self.tmp.name) / 'pscube.sqlite3')
        self.addCleanup(store.close)
        return store

    def test_a_full_table_clears_its_own_missing_tab_and_rack_marks_and_keeps_the_others(self):
        six, other = self.six_and_other()
        name, other_name = six['machine'], other['machine']
        # 10/17・10/18は過去の日の一覧（4台＋増台2台）を保存済み。そのあと両日とも「タブなし」を覚え、別機種の10/18も覚えた。
        for day in ('2026-10-17', '2026-10-18'):
            self.store.import_page(self.table(six, day, [1, 2, 3, 4], [5, 6]), six['url'], expected_day=day)
            self.skip_tab(six, day)
        self.skip_tab(other, '2026-10-18')
        both = {(name, '2026-10-17'): [5, 6], (name, '2026-10-18'): [5, 6]}
        self.assertEqual(self.absent(), ([(name, '2026-10-17'), (name, '2026-10-18'), (other_name, '2026-10-18')], both))
        self.assertEqual(self.store.next_target('2026-10-18'), (None, 0), '10/18はどちらの機種も未取得から外れている')
        day17 = self.store.next_target('2026-10-17')
        self.assertEqual(day17, (other['url'], 1), '10/17はこの機種だけ外れ、別機種の一覧は未取得')
        # 10/18の6台そろった一覧を保存：この機種・この日の両方の印だけが外れる。
        result = self.store.import_page(self.table(six, '2026-10-18', range(1, 7), games=2000), six['url'], expected_day='2026-10-18')
        self.assertEqual((result['saved'], result['kind']), (6, '全台一覧'))
        expected = ([(name, '2026-10-17'), (other_name, '2026-10-18')], {(name, '2026-10-17'): [5, 6]})
        self.assertEqual(self.absent(), expected)
        # 6台の台別ページが未取得に戻る（別機種の10/18は外れたまま）。
        url, remaining = self.store.next_target('2026-10-18')
        self.assertEqual((url, remaining), (self.record(six, 1, '2026-10-18')['detail_url'], 6))
        self.assertEqual(self.store.next_target('2026-10-17'), day17, '10/17は変わらない')
        # 開き直しても同じ。
        again = self.reopened()
        self.assertEqual(self.absent(again), expected)
        self.assertEqual(again.next_target('2026-10-18')[1], 6)

    def test_a_past_day_table_with_racks_added_later_clears_the_missing_tab_and_keeps_the_racks(self):
        six, _ = self.six_and_other(alone=True)
        name, day = six['machine'], '2026-10-18'
        self.skip_tab(six, day)
        self.assertEqual(self.absent()[0], [(name, day)])
        # 実データ4台＋その日に無かった2台の過去の日の一覧も、正しい全台一覧として受け付ける。
        result = self.store.import_page(self.table(six, day, [1, 2, 3, 4], [5, 6]), six['url'], expected_day=day)
        self.assertEqual(result['saved'], 4)
        self.assertEqual(self.absent(), ([], {(name, day): [5, 6]}), '日の印は外れ、増台した2台は覚えたまま')
        self.assertEqual(self.store.next_target(day), (self.record(six, 1, day)['detail_url'], 4))
        self.assertEqual(self.absent(self.reopened()), ([], {(name, day): [5, 6]}))

    def test_racks_added_later_shrink_from_two_to_one_to_none(self):
        six, _ = self.six_and_other(alone=True)
        name, day = six['machine'], '2026-10-18'
        first = self.record(six, 1, day)['detail_url']
        for racks, missing, remaining in (([1, 2, 3, 4], [5, 6], 4), ([1, 2, 3, 4, 5], [6], 5), (range(1, 7), [], 6)):
            with self.subTest(missing=missing):
                result = self.store.import_page(self.table(six, day, racks, missing), six['url'], expected_day=day)
                self.assertEqual(result['next_url'], first)
                self.assertEqual(result['remaining'], remaining)
                self.assertEqual(self.absent(), ([], {(name, day): missing} if missing else {}))
                self.assertEqual(self.store.next_target(day), (first, remaining))
                self.assertEqual(self.absent(self.reopened()), self.absent())

    def test_a_refused_or_failed_table_keeps_the_records_and_both_marks(self):
        six, _ = self.six_and_other()
        name, day = six['machine'], '2026-10-18'
        self.store.import_page(self.table(six, day, [1, 2, 3, 4], [5, 6]), six['url'], expected_day=day)
        self.skip_tab(six, day)
        marks, records = self.absent(), self.rows()
        self.assertEqual(marks, ([(name, day)], {(name, day): [5, 6]}))
        no_link = {'error': '5番台の台別ページへのリンクがありません。数値が表示されてから保存してください。',
                   'source_url': six['url'], 'available_days': self.TABS}
        latest = dict(self.table(six, day, [1, 2, 3, 4], [5, 6]), available_days=['2026-10-17', day])
        refused = {
            '台数が合わない': (self.table(six, day, [1, 2, 3, 4], [5]), '表示は5台、設置台数は6台'),
            '数値があるのにリンクが無い': (json.dumps(no_link), '5番台の台別ページへのリンクがありません'),
            '最新のタブの日に数値なしの台': (latest, '5・6番台に数値と台別ページへのリンクがありません'),
            '数値のある台が無い': (dict(self.table(six, day, []), missing_racks=[1, 2, 3, 4, 5, 6]), '全台一覧を確認できません'),
        }
        for label, (payload, message) in refused.items():
            with self.subTest(label), self.assertRaisesRegex(ValueError, message):
                self.store.import_page(payload, six['url'], expected_day=day)
            self.assertEqual((self.absent(), self.rows()), (marks, records))

        # 保存の途中（印を書くところ）で失敗：記録も印も書き換えない（同じトランザクション）。
        class Failing:
            def __init__(self, db):
                self.db = db

            def execute(self, sql, params=()):
                if params and params[0] == 'absent_table_days' and sql.startswith('INSERT'):
                    raise sqlite3.OperationalError('disk I/O error')
                return self.db.execute(sql, params)

            def __enter__(self):
                return self.db.__enter__()

            def __exit__(self, *error):
                return self.db.__exit__(*error)

        real = self.store.db
        self.store.db = Failing(real)
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, 'disk I/O error'):
                self.store.import_page(self.table(six, day, range(1, 7), games=2000), six['url'], expected_day=day)
        finally:
            self.store.db = real
        self.assertEqual((self.absent(), self.rows()), (marks, records))
        self.assertEqual((self.absent(self.reopened()), self.rows(self.reopened())), (marks, records))

    def test_date_events_free_names_shared_by_backup_with_newest_winning(self):
        # P’s CUBEのイベント名（自由記入、2026-10-06）。Android pscube_store_test と同じ規則。
        from datetime import timezone
        from pscube_import import validate_date_events
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        at = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        self.store.set_date_event(self.day, ' 周年 ', now=at)
        self.store.set_date_event('2026-09-30', '末尾イベ', now=at + timedelta(minutes=1))
        self.assertEqual(self.store.date_event_for(self.day), '周年')
        self.assertEqual(self.store.date_event_names(), ['末尾イベ', '周年'], '新しく使った順')
        backup = self.store.export_payload('backup')
        self.assertEqual(backup['date_events'][0], {'store': 'c740601', 'rate': '20', 'day': self.day, 'name': '周年',
                                                    'updated_at': '2026-10-06T12:00:00.000Z'})
        self.assertNotIn('suffix_events', backup)
        self.assertEqual(self.store.export_payload('viewer')['date_events'], backup['date_events'],
                         'iPhone向けの軽いファイルにも入る')
        other = PscubeStore(Path(self.tmp.name) / 'other.sqlite3')
        self.addCleanup(other.close)
        self.assertEqual(other.import_backup(backup)['events'], 2)
        self.assertEqual(other.date_event_for('2026-09-30'), '末尾イベ')
        self.assertEqual(other.import_backup(backup)['events'], 0, '2回目は変化なし')
        # 新しく消したものは、古いバックアップで戻らない。相手の新しい名前は取り込む。
        other.set_date_event(self.day, None, now=at + timedelta(hours=1))
        other.import_backup(backup)
        self.assertIsNone(other.date_event_for(self.day))
        self.assertEqual(other.date_event_names(), ['末尾イベ'])
        self.store.set_date_event(self.day, '周年2', now=at + timedelta(hours=2))
        other.import_backup(self.store.export_payload('backup'))
        self.assertEqual(other.date_event_for(self.day), '周年2')
        # 以前の閲覧ページの末尾イベの印は「末尾イベ」として読む。
        legacy = {**self.store.export_payload('backup'), 'suffix_events': [
            {'store': 'c740601', 'rate': '20', 'day': '2026-09-29', 'enabled': True, 'updated_at': '2026-10-02T00:00:00Z'}]}
        legacy.pop('date_events')
        other.import_backup(legacy)
        self.assertEqual(other.date_event_for('2026-09-29'), '末尾イベ')
        # 形の違うもの・長すぎる名前は保存しない。記録が無ければ付けられない。
        before = other.date_events()
        with self.assertRaises(ValueError):
            other.import_backup({**backup, 'date_events': [{**backup['date_events'][0], 'name': 'x' * 61}]})
        self.assertEqual(other.date_events(), before)
        for bad in ({'day': '2026-02-30'}, {'rate': 20}, {'updated_at': 'bad'}, {'name': 'a\nb'}):
            with self.assertRaises(ValueError, msg=bad):
                validate_date_events([{**backup['date_events'][0], **bad}])
        with self.assertRaises(ValueError):
            self.store.set_date_event(self.day, 'x' * 61)
        empty = PscubeStore(Path(self.tmp.name) / 'empty.sqlite3')
        self.addCleanup(empty.close)
        with self.assertRaises(ValueError):
            empty.set_date_event(self.day, '周年')

    def test_table_url_for_day_opens_the_chosen_day_tab(self):
        # サイトは全台一覧の#以降（表示件数;位置;選んだ日付;…）で日付タブを選ぶ（2026-10-06 実サイトで確認）。
        table = self.machines[0]['url']
        self.assertEqual(table_url_for_day(table, '2026-10-05'), table + '#0;0;20261005;0;cd_dai;1;0;0')
        self.assertEqual(table_url_for_day(table + '#2;600;20261006;0;cd_dai;1;0;332', '2026-10-05'),
                         table + '#0;0;20261005;0;cd_dai;1;0;0')
        self.assertEqual(table_url_for_day(table, None), table)
        rack = self.record(self.machines[0], 1526)['detail_url']
        self.assertEqual(table_url_for_day(rack, '2026-10-05'), rack)
        self.assertEqual(table_url_for_day(self.index_url, '2026-10-05'), self.index_url)
        self.assertIsNone(table_url_for_day(None, '2026-10-05'))

    def test_rack_columns_start_at_the_site_today_and_newer_columns_are_left_out(self):
        # サイトの本日は10/02、取り込み日は10/01。読み取りは10/02（営業中）の列を除いた6日分を返す。
        machine, record, payload = self.seed_rack()
        six = [self.record(machine, 1526, (date.fromisoformat(self.day) - timedelta(days=i)).isoformat()) for i in range(6)]
        for row in six:
            row['graph'] = {'kind': 'daily', 'zero_y': 10, 'points': [[0, 10], [1, 8]]}
        rack = {**payload, 'records': six, 'history_latest_day': '2026-10-02'}
        rack.pop('missing_history_days', None)
        self.store.import_page(rack, record['detail_url'], expected_day=self.day)
        import input_versions
        input_versions.wait(self.store.path.parent)
        before = list(self.store.db.iterdump())
        old_shape = {key: value for key, value in rack.items() if key != 'history_latest_day'}
        with self.assertRaisesRegex(ValueError, '連続した7日分'):
            self.store.import_page(old_shape, record['detail_url'])
        for latest in ('2026-09-30', '2026-10-08', '10/02', 20261002):
            with self.assertRaises(ValueError, msg=latest):
                self.store.import_page({**rack, 'history_latest_day': latest}, record['detail_url'])
        with_today = {**rack, 'records': [self.record(machine, 1526, '2026-10-02')] + six[:5]}
        with self.assertRaises(ValueError):
            self.store.import_page(with_today, record['detail_url'])
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_manual_import_continues_from_the_saved_page_instead_of_the_top_of_the_list(self):
        """手動のとき：飛ばした上の機種へ戻らず、保存したページの次（同じ機種の台→次の機種）へ。最後まで来たら最初へ回る。"""
        a, b, c = [dict(m, expected_count=2) for m in (self.machines[0], self.machines[1],
                   {**self.machines[0], 'machine': 'L無職転生', 'url': self.machines[0]['url'].replace('L東京喰種', 'L無職転生')})]
        self.store.import_page(self.page(self.index_url, [a, b, c]), self.index_url)

        def history(machine, rack):
            rows = []
            for ago in range(7):
                day = (date.fromisoformat(self.day) - timedelta(days=ago)).isoformat()
                rows.append(self.record(machine, rack, day))
            return rows

        def save_table(machine, manual):
            records = [self.record(machine, 100), self.record(machine, 101)]
            page = self.page(machine['url'], [dict(machine, expected_count=None)], records)
            return self.store.import_page(page, machine['url'], manual=manual), records

        def save_rack(machine, rack, manual):
            url = self.record(machine, rack)['detail_url']
            page = self.page(url, [dict(machine, expected_count=None)], history(machine, rack))
            return self.store.import_page(page, url, manual=manual)['next_url']

        url = lambda machine, rack: self.record(machine, rack)['detail_url']
        # 甲機（一覧の一番上）は飛ばして、乙機・丙機だけを取り込む。
        result, _ = save_table(b, manual=False)
        self.assertEqual(result['next_url'], a['url'], '自動（手動でない）は、これまでどおり一覧の最初の未取得')
        result, _ = save_table(b, manual=True)
        self.assertEqual(result['next_url'], url(b, 100), '手動：保存した機種の台へ（上の甲機へ戻らない）')
        self.assertEqual(save_rack(b, 100, manual=True), url(b, 101), '手動：同じ機種の次の台番')
        self.assertEqual(save_rack(b, 101, manual=True), c['url'], '乙機が済んだら、次の機種（丙機）の表へ（上の甲機へ戻らない）')
        result, _ = save_table(c, manual=True)
        self.assertEqual(result['next_url'], url(c, 100))
        self.assertEqual(save_rack(c, 100, manual=True), url(c, 101))
        self.assertEqual(save_rack(c, 101, manual=True), a['url'], '最後の機種まで来たら、取りこぼした甲機へ回る')

    def test_numbers_saved_earlier_in_the_day_are_taken_again(self):
        """昼に取った機種を、夜の取り込みで「済み」として飛ばさない（2026-10-04、P’s CUBEで下からが上に飛んだ件）。"""
        a, b, c = [dict(m, expected_count=1) for m in (self.machines[0], self.machines[1],
                   {**self.machines[0], 'machine': 'Lうみねこ', 'url': self.machines[0]['url'].replace('L東京喰種', 'Lうみねこ')})]
        self.store.import_page(self.page(self.index_url, [a, b, c]), self.index_url)

        def at(machine, rack, time, games=1854):
            return dict(self.record(machine, rack), observed_at=f'2026-10-01T{time}:00+09:00', games=games)

        def table(machine, rack, time, games=1854, **kw):
            return self.store.import_page(self.page(machine['url'], [dict(machine, expected_count=None)], [at(machine, rack, time, games)]), machine['url'], **kw)

        def rack_page(machine, rack, time, **kw):
            url = self.record(machine, rack)['detail_url']
            rows = [dict(self.record(machine, rack, (date.fromisoformat(self.day) - timedelta(days=i)).isoformat()),
                         observed_at=f'2026-10-01T{time}:00+09:00') for i in range(7)]
            return self.store.import_page(self.page(url, [dict(machine, expected_count=None)], rows), url, **kw)

        # 昼（11:12）に3機種とも全台一覧・台別ページまで取った。
        for i, m in enumerate((a, b, c)):
            table(m, 100 + i, '11:12'); rack_page(m, 100 + i, '11:12')
        self.assertIsNone(self.store.next_target(self.day, 'bottom')[0], '基準が無ければ、これまでどおり済み')
        # 夜（23:12）に下から。最初の丙機（うみねこ）の全台一覧で基準23:12が分かり、次は乙機の全台一覧を取り直す。
        night = table(c, 102, '23:12', games=6000, direction='bottom')
        self.assertEqual(night['fresh_since'], {self.day: '2026-10-01T23:12:00+09:00'})
        self.assertEqual(night['next_url'], self.record(c, 102)['detail_url'], '数値が変わった台は台別ページも取り直す')
        after_rack = rack_page(c, 102, '23:12', direction='bottom', fresh_since=night['fresh_since'])
        self.assertEqual(after_rack['next_url'], b['url'], '昼の数値のままの乙機を飛ばさない')
        # 乙機は昼から数値が変わっていない：全台一覧を取り直せば、台別ページは取り直さない（次は甲機）。
        same = table(b, 101, '23:12', direction='bottom', fresh_since=after_rack['fresh_since'])
        self.assertEqual(same['next_url'], a['url'])
        table(a, 100, '23:12', direction='bottom', fresh_since=after_rack['fresh_since'])
        self.assertIsNone(self.store.next_target(self.day, 'bottom', fresh_since='2026-10-01T23:12:00+09:00')[0],
                          '今回取った分は、その後サイトの時刻が進んでも取り直さない（終わらなくならない）')

    def test_the_cutoff_stops_at_the_end_of_the_business_day(self):
        from pscube_import import stale_cutoff
        at = lambda text: datetime.fromisoformat(text).timestamp()
        self.assertEqual(stale_cutoff('2026-10-01', '2026-10-03T09:00:00+09:00'), at('2026-10-01T23:00:00+09:00'),
                         '終わった日は、その日の23時より後に取った分が最終（翌日の午前2時の3時間前）')
        self.assertEqual(stale_cutoff('2026-10-01', '2026-10-01T23:12:00+09:00'), at('2026-10-01T20:12:00+09:00'),
                         '基準の3時間前より前に取った分だけ取り直す')
        self.assertIsNone(stale_cutoff('2026-10-01', None))

    def test_installation_count_uses_the_current_machine_without_writing(self):
        self.machines[0]['expected_count'] = 31
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        import input_versions
        input_versions.wait(self.store.path.parent)
        before = self.store.path.read_bytes()
        self.assertEqual(installation_count(self.store.path, self.machines[0]['url'] + '#scroll=6'), 31)
        self.assertEqual(installation_count(self.store.path, self.machines[1]['url']), 1)
        reordered = self.machines[0]['url'].replace('cd_ps=2&bai=20', 'bai=20&cd_ps=2')
        self.assertEqual(installation_count(self.store.path, reordered), 31)
        self.assertIsNone(installation_count(self.store.path, self.machines[0]['url'].replace('bai=20', 'bai=5')))
        self.assertIsNone(installation_count(self.store.path, self.index_url))
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_unknown_installation_count_does_not_create_a_database(self):
        path = Path(self.tmp.name) / 'missing.sqlite3'
        self.assertIsNone(installation_count(path, self.machines[0]['url']))
        self.assertFalse(path.exists())
        self.assertIsNone(installation_count(self.store.path, self.machines[0]['url']))
        with self.assertRaises(ValueError):
            installation_count(self.store.path, self.machines[0]['url'].replace('c740601', 'c999999'))

    def test_index_table_rack_cycle_and_export(self):
        index = self.page(self.index_url, self.machines)
        first = self.store.import_page(index, self.index_url)
        self.assertEqual(first['next_url'], self.machines[0]['url'])
        for i, machine in enumerate(self.machines):
            record = self.record(machine, 1526 + i)
            table = self.page(machine['url'], [dict(machine, expected_count=None)], [record])
            result = self.store.import_page(table, machine['url'])
            self.assertEqual(result['next_url'], record['detail_url'])
            history = []
            for ago in range(7):
                day = (date.fromisoformat(self.day) - timedelta(days=ago)).isoformat()
                row = self.record(machine, 1526 + i, day)
                row['graph'] = {'kind': 'daily', 'zero_y': 10, 'points': [[0, 10], [1, 6]]} if ago == 0 else None
                history.append(row)
            rack = self.page(record['detail_url'], [dict(machine, expected_count=None)], history)
            result = self.store.import_page(rack, record['detail_url'])
            self.assertEqual(result['next_url'], self.machines[1]['url'] if i == 0 else None)
            # Re-reading a saved rack is safe and does not make it pending again.
            self.store.import_page(rack, record['detail_url'])
        export = self.store.export_viewer(Path(self.tmp.name) / 'viewer.json')
        data = json.loads(export.read_text(encoding='utf-8'))
        self.assertEqual(data['format'], 'pscube-viewer')
        self.assertEqual(len(data['records']), 14)
        self.assertEqual(data['records'][0]['my'], 1921)

    def rack_history(self, machine, rack, last_day, nets):
        rows = []
        for ago in range(7):
            day = (date.fromisoformat(last_day) - timedelta(days=ago)).isoformat()
            row = self.record(machine, rack, day)
            row['graph'] = {'kind': 'daily', 'zero_y': 10, 'points': [[0, 10], [1, 6]]}
            if day in nets:
                row['net_medals'] = nets[day]
            rows.append(row)
        return rows

    def test_net_medals_are_kept_through_table_recapture_backup_and_filled_on_the_next_day(self):
        machine = self.machines[0]
        self.store.import_page(self.page(self.index_url, [machine]), self.index_url)
        record = self.record(machine, 1120)
        table = self.page(machine['url'], [dict(machine, expected_count=None)], [record])
        self.store.import_page(table, machine['url'])
        # 差枚の元データが取れなかった台：数値・グラフは保存し、差枚は空欄（0にしない）で次へ進む。
        missing = self.page(record['detail_url'], [dict(machine, expected_count=None)],
                            self.rack_history(machine, 1120, self.day, {}))
        missing['net_warning'] = '差枚は未取得：通信に失敗しました（HTTP 403）'
        result = self.store.import_page(missing, record['detail_url'])
        self.assertEqual(result['net_warning'], missing['net_warning'])
        self.assertIsNone(result['next_url'])
        saved = {r['day']: r for r in self.store.export_payload('backup')['records']}
        self.assertEqual(len(saved), 7)
        self.assertTrue(all('net_medals' not in r or r['net_medals'] is None for r in saved.values()))
        self.assertEqual(saved[self.day]['graph']['kind'], 'daily')
        # 手動の再取り込み（同じ台別ページ）で差枚が入る。MYとは別の値。
        nets = {self.day: 14118, '2026-09-30': -250}
        retry = self.page(record['detail_url'], [dict(machine, expected_count=None)],
                          self.rack_history(machine, 1120, self.day, nets))
        self.assertNotIn('net_warning', self.store.import_page(retry, record['detail_url']))
        # 一覧の再取り込み（差枚なし・同じ数値）でも差枚は消えない。
        self.store.import_page(table, machine['url'])
        saved = {r['day']: r for r in self.store.export_payload('backup')['records']}
        self.assertEqual((saved[self.day]['net_medals'], saved[self.day]['my']), (14118, 1921))
        self.assertEqual(saved['2026-09-30']['net_medals'], -250)
        self.assertIsNone(saved['2026-09-29'].get('net_medals'))
        # 翌日の巡回でその台を開けば、前日までの空欄も埋まる（サイトにある7日分）。
        next_day = '2026-10-02'
        table2 = self.page(machine['url'], [dict(machine, expected_count=None)], [self.record(machine, 1120, next_day)])
        self.assertEqual(self.store.import_page(table2, machine['url'])['next_url'],
                         self.record(machine, 1120, next_day)['detail_url'])
        later = self.rack_history(machine, 1120, next_day, {next_day: 300, self.day: 14118, '2026-09-29': 42})
        self.store.import_page(self.page(self.record(machine, 1120, next_day)['detail_url'],
                                         [dict(machine, expected_count=None)], later),
                               self.record(machine, 1120, next_day)['detail_url'])
        saved = {r['day']: r for r in self.store.export_payload('backup')['records']}
        self.assertEqual((saved[next_day]['net_medals'], saved['2026-09-29']['net_medals']), (300, 42))
        # バックアップから別のPCへ復元しても差枚は残る。
        backup = Path(self.tmp.name) / 'pscube-backup.json'
        backup.write_text(json.dumps(self.store.export_payload('backup'), ensure_ascii=False), encoding='utf-8')
        other = PscubeStore(Path(self.tmp.name) / 'other.sqlite3')
        self.addCleanup(other.close)
        other.import_backup(backup)
        restored = {r['day']: r for r in other.export_payload('backup')['records']}
        self.assertEqual(restored[self.day]['net_medals'], 14118)
        self.assertEqual(restored['2026-09-29']['net_medals'], 42)

    def test_racks_without_any_hit_are_saved_but_their_seven_day_page_is_skipped(self):
        # 当たりが1回もない台（0回転を含む）は、数値は保存し、台別7日分は取りに行かない。
        self.machines[0]['expected_count'] = 3
        self.store.import_page(self.page(self.index_url, self.machines[:1]), self.index_url)
        hit = self.record(self.machines[0], 1526)
        zero = dict(self.record(self.machines[0], 1527), bb=0, rb=0, at_art=0, games=0, my=0)
        idle = dict(self.record(self.machines[0], 1528), bb=0, rb=0, at_art=0, games=812)
        table = self.page(self.machines[0]['url'], [dict(self.machines[0], expected_count=None)], [hit, zero, idle])
        result = self.store.import_page(table, self.machines[0]['url'])
        self.assertEqual(result['next_url'], hit['detail_url'])
        self.assertEqual(result['remaining'], 1)
        self.assertEqual(len(self.store.export_payload()['records']), 3, '数値は3台とも保存する')
        at_only = dict(idle, at_art=1)
        self.store.import_page(self.page(self.machines[0]['url'], [dict(self.machines[0], expected_count=None)], [hit, zero, dict(at_only, observed_at='2026-10-01T13:00:00+09:00')]), self.machines[0]['url'])
        self.assertEqual(self.store.next_target(self.day)[1], 2, 'AT/ARTが付いたらまた取る対象に戻る')

    def test_okidoki_machines_are_never_visited_or_saved(self):
        # メルヘンと同じ約束：沖ドキ（半角の「沖ﾄﾞｷ」、「オキドキ」も）は対象外。
        oki = {'store': 'c740601', 'rate': '20', 'machine': '沖ﾄﾞｷ!GOLD-30', 'expected_count': 1,
               'url': ROOT_URL + 'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=oki'}
        result = self.store.import_page(self.page(self.index_url, [oki, self.machines[0]]), self.index_url)
        self.assertEqual(result['remaining'], 1, '回る対象は沖ドキ以外だけ')
        self.assertEqual(self.store.next_target(self.day)[0], self.machines[0]['url'])
        table = self.page(oki['url'], [dict(oki, expected_count=None)], [self.record(oki, 1600)])
        with self.assertRaisesRegex(ValueError, '対象外'):
            self.store.import_page(table, oki['url'])
        self.assertEqual(self.store.export_payload()['records'], [])
        from pscube_import import is_excluded_machine
        for name in ('沖ドキ!DUO', 'オキドキ', 'ｵｷﾄﾞｷ!', '沖ﾄﾞｷ!BLACK'):
            self.assertTrue(is_excluded_machine(name), name)
        self.assertFalse(is_excluded_machine('ﾏｲｼﾞｬｸﾞﾗｰV'))

    def test_incomplete_table_and_mismatched_page_are_rejected(self):
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        self.machines[0]['expected_count'] = 2
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        record = self.record(self.machines[0], 1526)
        table = self.page(self.machines[0]['url'], [dict(self.machines[0], expected_count=None)], [record])
        with self.assertRaisesRegex(ValueError, '全台を表示'):
            self.store.import_page(table, self.machines[0]['url'])
        with self.assertRaisesRegex(ValueError, '表示中のページ'):
            self.store.import_page(table, self.machines[1]['url'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 0)

    def seed_rack(self):
        machine = self.machines[0]
        self.store.import_page(self.page(self.index_url, [machine]), self.index_url)
        record = self.record(machine, 1526)
        self.store.import_page(self.page(machine['url'], [machine], [record]), machine['url'])
        history = [self.record(machine, 1526, (date.fromisoformat(self.day) - timedelta(days=i)).isoformat()) for i in range(7)]
        for row in history:
            row['graph']['kind'] = 'daily'
        # Real rack pages omit cd_ps on the return-to-machine link.
        rack_machine = {**machine, 'url': machine['url'].replace('cd_ps=2&', '')}
        payload = self.page(record['detail_url'], [rack_machine], history)
        self.store.import_page(payload, record['detail_url'])
        return machine, record, payload

    def test_changed_numbers_make_captured_rack_pending_again(self):
        machine, record, _ = self.seed_rack()
        self.assertIsNone(self.store.next_target(self.day)[0])
        record.update(games=2000, observed_at='2026-10-01T13:00:00+09:00')
        result = self.store.import_page(self.page(machine['url'], [machine], [record]), machine['url'])
        self.assertEqual(result['next_url'], record['detail_url'])
        saved = json.loads(self.store.db.execute('SELECT payload FROM records WHERE payload LIKE ?', ('%2000%',)).fetchone()[0])
        self.assertEqual(saved['graph']['kind'], 'overview')

    def test_unchanged_or_older_list_keeps_detail_and_capture(self):
        machine, record, _ = self.seed_rack()
        for patch in ({'observed_at': '2026-10-01T13:00:00+09:00'}, {'games': 1000, 'observed_at': '2026-10-01T11:00:00+09:00'}):
            incoming = {**record, **patch}
            result = self.store.import_page(self.page(machine['url'], [machine], [incoming]), machine['url'])
            self.assertIsNone(result['next_url'])
        saved = json.loads(self.store.db.execute('SELECT payload FROM records ORDER BY rowid LIMIT 1').fetchone()[0])
        self.assertEqual(saved['games'], 1854)
        self.assertEqual(saved['graph']['kind'], 'daily')

    def test_same_page_ignores_list_scroll_hash_and_url_encoding_but_not_rack_day(self):
        from urllib.parse import quote
        machine = self.machines[0]
        encoded = machine['url'].replace(machine['machine'], quote(machine['machine']))
        self.assertTrue(same_page(self.index_url + '#scroll=1200', self.index_url))
        self.assertTrue(same_page(machine['url'], encoded + '#scroll=40'))
        rack = self.record(machine, 1526)['detail_url']
        self.assertTrue(same_page(rack, rack))
        self.assertFalse(same_page(rack, rack.replace('#20261001', '#20260930')))
        self.assertFalse(same_page(rack, rack.split('#')[0]))
        self.assertFalse(same_page(machine['url'], self.machines[1]['url']))
        self.assertFalse(same_page(self.index_url, None))

        # 読み取り後にサイトがスクロール位置を書き換えても、WebView2が日本語を戻した形で返しても保存する。
        self.store.import_page(self.page(self.index_url + '#scroll=1200', self.machines), self.index_url)
        self.store.import_page(self.page(encoded, [machine], [self.record(machine, 1526)]), machine['url'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 1)
        # 本当に別の機種の結果は保存しない。
        with self.assertRaisesRegex(ValueError, '読み取り結果が違います'):
            self.store.import_page(self.page(self.machines[1]['url'], [machine], [self.record(machine, 1526)]), machine['url'])

    def test_nonconsecutive_days_and_wrong_rack_reject_before_writing(self):
        machine, record, payload = self.seed_rack()
        import input_versions
        input_versions.wait(self.store.path.parent)
        before = list(self.store.db.iterdump())
        broken = json.loads(json.dumps(payload))
        broken['records'][-1] = self.record(machine, 1526, '2026-09-20')
        with self.assertRaisesRegex(ValueError, '連続した7日'):
            self.store.import_page(broken, record['detail_url'])
        url = record['detail_url'].replace('1526', '1527')
        broken = {**payload, 'source_url': url}
        with self.assertRaisesRegex(ValueError, '台番号・機種'):
            self.store.import_page(broken, url)
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_new_installation_skips_explicit_empty_days_and_keeps_old_machine_history(self):
        old = self.machines[0]
        new = self.machines[1]
        previous_day = (date.fromisoformat(self.day) - timedelta(days=1)).isoformat()
        self.store.import_page(self.page(self.index_url, [old, new]), self.index_url)
        old_record = self.record(old, 1085, previous_day)
        self.store.import_page(self.page(old['url'], [old], [old_record]), old['url'])
        # 撤去で減っただけの機種一覧は、自動では受け付けず手動で取り込む（2026-10-27）。
        self.store.import_page(self.page(self.index_url, [new]), self.index_url, manual=True)
        current = self.record(new, 1085)
        self.store.import_page(self.page(new['url'], [new], [current]), new['url'])
        missing = [(date.fromisoformat(self.day) - timedelta(days=i)).isoformat() for i in range(1, 7)]
        payload = self.page(current['detail_url'], [new], [{**current, 'net_medals': 125,
            'graph': {'kind': 'daily', 'zero_y': 10, 'points': [[0, 10], [1, 6]]}}])
        payload['missing_history_days'] = missing
        import input_versions
        input_versions.wait(self.store.path.parent)
        before = list(self.store.db.iterdump())
        for broken in (None, missing[:-1], missing + [missing[0]], [self.day, *missing[1:]],
                       ['2020-01-01', *missing[1:]], [[previous_day], *missing[1:]]):
            with self.assertRaises(ValueError):
                self.store.import_page({**payload, 'missing_history_days': broken}, current['detail_url'])
        without_marker = dict(payload)
        without_marker.pop('missing_history_days')
        with self.assertRaises(ValueError):
            self.store.import_page(without_marker, current['detail_url'])
        self.assertEqual(list(self.store.db.iterdump()), before)
        result = self.store.import_page(payload, current['detail_url'])
        self.assertEqual(result['saved'], 1)
        self.assertIsNone(self.store.next_target(self.day)[0], '空の過去日を再取得し続けない')
        exported = self.store.export_payload('backup')
        self.assertEqual(len(exported['records']), 2)
        saved_old = next(r for r in exported['records'] if r['machine'] == old['machine'])
        self.assertEqual(saved_old, old_record)
        saved_new = next(r for r in exported['records'] if r['machine'] == new['machine'])
        self.assertEqual(saved_new['day'], self.day)
        self.assertEqual(saved_new['net_medals'], 125)
        self.assertEqual(saved_new['graph']['kind'], 'daily')
        restored = PscubeStore(Path(self.tmp.name) / 'replacement.sqlite3')
        self.addCleanup(restored.close)
        restored.import_backup(exported)
        self.assertEqual(len(restored.export_payload('backup')['records']), 2)
        restored.import_page(self.page(self.index_url, [new]), self.index_url)
        self.assertIsNone(restored.next_target(self.day)[0])

    def test_bad_graph_rejects_whole_page_and_keeps_existing_export(self):
        machine, record, _ = self.seed_rack()
        target = self.store.export_viewer(Path(self.tmp.name) / 'viewer.json')
        before = target.read_bytes()
        import input_versions
        input_versions.wait(Path(self.tmp.name))
        database_before = list(self.store.db.iterdump())
        record['graph']['points'] = [[0, 10], [1, float('nan')]]
        with self.assertRaisesRegex(ValueError, '座標'):
            self.store.import_page(self.page(machine['url'], [machine], [record]), machine['url'])
        # A rejected import must preserve the existing file, without issuing a
        # new export (whose exported_at legitimately changes across seconds).
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.store.db.iterdump()), database_before)

    def test_reexport_updates_timestamp_without_changing_saved_content(self):
        self.seed_rack()
        stamps = ['2026-10-16T06:36:04+00:00', '2026-10-16T06:36:05+00:00']
        with patch('pscube_import._now_text', side_effect=stamps):
            target = self.store.export_viewer(Path(self.tmp.name) / 'viewer.json')
            before = json.loads(target.read_text(encoding='utf-8'))
            self.store.export_viewer(target)
            after = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(before.pop('exported_at'), stamps[0])
        self.assertEqual(after.pop('exported_at'), stamps[1])
        self.assertEqual(after, before)

    def test_reopen_preserves_separate_records_and_pending_status(self):
        _, _, _ = self.seed_rack()
        other = PscubeStore(Path(self.tmp.name) / 'meruhen.sqlite3')
        try:
            self.assertEqual(other.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 0)
        finally:
            other.close()
        reopened = PscubeStore(self.store.path)
        try:
            self.assertIsNone(reopened.next_target(self.day)[0])
            self.assertEqual(reopened.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 7)
        finally:
            reopened.close()


if __name__ == '__main__':
    unittest.main()
