"""Meruhen PC: 日付指定取り込み（取り込み日）と、機種を上から／下から数える向き。"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from browser_import import DIRECTIONS, _Bridge, recent_days, with_target_date
from core import Store

HOST = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'


def row(rack, machine='甲機', day='2026-10-03'):
    return dict(store='nagamachiminami', kind_code=21, day=day, machine=machine, rack=rack,
                games=3500, bb=20, rb=10, max_hold=2000)


class DaySelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.bridge = _Bridge(self.folder / 'test.db', self.folder, 'x')
        self.machines = [dict(name=name, url=f'{HOST}/standlist_slot?kind_code=21&machine_name={name}', count=3)
                         for name in ('甲機', '乙機', '丙機')]

    def ask(self, **extra):
        payload = dict(store='nagamachiminami', machines=self.machines, **extra)
        return json.loads(self.bridge.next_unimported_machine(json.dumps(payload)))

    def test_business_days_change_at_2am(self):
        days = recent_days(datetime(2026, 10, 4, 1, 59))
        self.assertEqual((days[0], days[1], days[-1], len(days)), ('2026-10-03', '2026-10-02', '2026-09-27', 7))
        self.assertEqual(recent_days(datetime(2026, 10, 4, 2, 0))[0], '2026-10-04')

    def test_target_date_is_added_without_touching_the_name_encoding(self):
        url = f'{HOST}/standlist_slot/?kind_code=21&machine_name=L%2520%25E7%2594%25B2'
        self.assertEqual(with_target_date(url, '2026-10-03'), url + '&target_date=2026-10-03')
        self.assertEqual(with_target_date(url + '&target_date=2026-10-04', '2026-10-03'), url + '&target_date=2026-10-03')
        self.assertEqual(with_target_date(url + '#x', '2026-10-03'), url + '&target_date=2026-10-03#x')

    def test_direction_and_day_are_validated_and_locked_while_on(self):
        today, yesterday = recent_days()[:2]
        state = self.bridge.get_auto_capture()
        self.assertEqual((state['target_day'], state['direction'], state['days'][:2]), (None, 'top', [today, yesterday]))
        with self.assertRaises(ValueError):
            self.bridge.set_target_day('2026-01-01')
        with self.assertRaises(ValueError):
            self.bridge.set_target_day(None, 'sideways')
        state = self.bridge.set_target_day(yesterday, 'bottom')
        self.assertEqual((state['target_day'], state['direction']), (yesterday, 'bottom'))
        self.assertIsNone(self.bridge.set_target_day('')['target_day'])
        state = self.bridge.set_auto_capture(True, 3.5, yesterday, 'bottom')
        self.assertEqual((state['enabled'], state['target_day'], state['direction']), (True, yesterday, 'bottom'))
        with self.assertRaises(ValueError):
            self.bridge.set_target_day('')
        self.bridge.set_auto_capture(False, 3.5)
        self.assertEqual(self.bridge.get_auto_capture()['target_day'], yesterday, 'OFFにしても選んだ日は残る')
        self.assertEqual(DIRECTIONS, ('top', 'bottom'))

    def test_next_machine_comes_from_the_chosen_end_with_the_chosen_day(self):
        yesterday = recent_days()[1]
        # 指定なし：従来どおり一覧の上から、サイトの行を押して開く（URLは作らない）。
        first = self.ask(day=yesterday)
        self.assertEqual((first['machine'], first['reason'], first.get('direct')), ('甲機', 'table', False))
        self.assertNotIn('target_date', first['url'])
        # 下から：一覧の最後の機種。日付を指定すると、日付つきのURLを直接開く。
        self.bridge.set_target_day(yesterday, 'bottom')
        last = self.ask(day='2026-01-01')   # ページの日付ではなく、選んだ日を使う
        self.assertEqual((last['machine'], last['direct']), ('丙機', True))
        self.assertTrue(last['url'].endswith(f'&target_date={yesterday}'), last['url'])
        # 上から：一覧の最初の機種。
        self.bridge.set_target_day(None, 'top')
        self.assertEqual(self.ask()['machine'], '甲機', '日付がページに無くても、選んだ日で進む（日付の確認に別の機種を開かない）')

    def test_bottom_also_picks_the_first_machine_from_the_bottom_when_the_day_is_unknown(self):
        """指定なし・機種一覧に日付が無いとき（日付を確かめるために最初の機種を開く）も、下からなら一覧の下から。"""
        self.assertEqual(self.ask()['machine'], '甲機')
        self.assertEqual(self.ask()['reason'], 'need_day')
        self.bridge.set_target_day(None, 'bottom')
        first = self.ask()
        self.assertEqual((first['machine'], first['reason']), ('丙機', 'need_day'))

    def test_resumes_the_chosen_day_after_the_site_default_moved_on(self):
        yesterday, today = recent_days()[1], recent_days()[0]
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250, end_x=4, end_y=150)
        db = Store(self.folder / 'test.db')
        db.save([dict(row(rack=r, machine='甲機', day=yesterday), graph_measurement=graph,
                      detail_url=f'{HOST}/standgraph/?rack_no={r}&target_date={yesterday}') for r in (1, 2, 3)])
        db.close()
        self.bridge.set_target_day(yesterday, 'top')
        # ページ（日付が変わったあとのサイトの表示）は今日だが、昨日の分の続きを探す：甲機は済み、次は乙機。
        result = self.ask(day=today)
        self.assertEqual((result['machine'], result['direct']), ('乙機', True))
        self.assertIn(f'target_date={yesterday}', result['url'])

    def test_manual_import_goes_to_the_machine_after_the_finished_one(self):
        """手動のとき：機種が済んだら、一覧の上から探し直さず、その機種の次へ進む。"""
        day = '2026-10-03'
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250, end_x=4, end_y=150)
        db = Store(self.folder / 'test.db')
        # 乙機だけ済んでいる。甲機（一覧の上）は取りこぼし、丙機は未取込。
        db.save([dict(row(rack=r, machine='乙機', day=day), graph_measurement=graph,
                      detail_url=f'{HOST}/standgraph/?rack_no={r}&target_date={day}') for r in (1, 2, 3)])
        db.close()
        self.assertEqual(self.ask(day=day)['machine'], '甲機', '印が無ければ、これまでどおり一覧の上から')
        after = self.ask(day=day, after='乙機')
        self.assertEqual(after['machine'], '丙機', '乙機の次へ（上の取りこぼしへ戻らない）')
        self.assertNotIn('最後まで来た', after['message'])
        # 一覧の最後の機種のあとは、取りこぼしを探して最初へ戻る（そう知らせる）。
        wrapped = self.ask(day=day, after='丙機')
        self.assertEqual(wrapped['machine'], '甲機')
        self.assertIn('最後まで来たので、一覧の最初から', wrapped['message'])
        # 下からの向きなら、一覧の下→上の並びでの「次」。
        self.bridge.set_target_day(None, 'bottom')
        self.assertEqual(self.ask(day=day, after='丙機')['machine'], '甲機', '丙機の次（下から数えて）は乙機＝済みなので甲機')
        self.assertEqual(self.ask(day=day, after='不明な機種')['machine'], '丙機', '知らない機種名の印は無視して、これまでどおり')

    def test_the_list_url_carries_the_finished_machine(self):
        from browser_import import machine_list_url
        url = machine_list_url('nagamachiminami', '2026-10-03', after='L無職転生　NM')
        self.assertTrue(url.endswith('&database_after=L%E7%84%A1%E8%81%B7%E8%BB%A2%E7%94%9F%E3%80%80NM'), url)
        self.assertNotIn('database_after', machine_list_url('nagamachiminami', '2026-10-03'))

    def test_a_page_for_another_day_is_not_saved(self):
        yesterday, today = recent_days()[1], recent_days()[0]
        self.bridge.set_target_day(yesterday)
        self.bridge._window = mock.Mock()
        self.bridge._window.get_current_url.return_value = f'{HOST}/standlist_slot?kind_code=21&machine_name=x&target_date={today}'
        shown = json.dumps(dict(store='nagamachiminami', target_date=today, machine='甲機'))
        checked = json.loads(self.bridge._checked(shown))
        self.assertIn(f'取り込み日は{yesterday}ですが、表示中は{today}', checked['error'])
        self.bridge._window.get_current_url.return_value = f'{HOST}/standlist_slot?kind_code=21&machine_name=x&target_date={yesterday}'
        same = json.dumps(dict(store='nagamachiminami', target_date=yesterday, machine='甲機'))
        self.assertNotIn('error', json.loads(self.bridge._checked(same)))
        self.bridge.set_target_day('')
        self.bridge._window.get_current_url.return_value = f'{HOST}/standlist_slot?kind_code=21&machine_name=x&target_date={today}'
        self.assertNotIn('error', json.loads(self.bridge._checked(shown)), '指定なしなら、どの日でもこれまでどおり')


if __name__ == '__main__':
    unittest.main()
