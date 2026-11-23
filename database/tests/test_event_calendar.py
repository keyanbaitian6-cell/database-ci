"""イベントカレンダー（EVENT_CALENDAR.md、2026-10-07）：入力時刻・新しい方が上書き・消した印。"""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import (Store, date_event_in_advance, export_backup, export_viewer, import_backup,
                  merge_date_events, read_backup_file)
from event_calendar import LATE_MARK, cell_text, month_weeks, range_days, shift_month

JST = timezone(timedelta(hours=9))


def at(text):
    return datetime.fromisoformat(text)


class EventCalendarStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Store(Path(self.tmp.name) / 'database.sqlite3')
        self.addCleanup(self.db.close)

    def event(self, day, location='nagamachiminami', removed=False):
        return next((e for e in self.db.date_events(location=location, day=day, include_removed=removed)), None)

    def test_entering_stamps_the_time_and_future_days_are_allowed(self):
        self.db.set_date_event('saiwaichou', '2026-12-31', ' 華の日 ', now=at('2026-10-07T22:00:00+09:00'))
        saved = self.event('2026-12-31', 'saiwaichou')
        self.assertEqual(saved['name'], '華の日')
        self.assertEqual(saved['updated_at'], '2026-10-07T22:00:00.000+09:00')

    def test_same_name_keeps_the_old_time_and_a_change_moves_forward(self):
        self.db.set_date_event('nagamachiminami', '2026-10-10', '半列', now=at('2026-10-07T22:00:00+09:00'))
        self.db.set_date_event('nagamachiminami', '2026-10-10', '半列', now=at('2026-10-11T12:00:00+09:00'))
        self.assertEqual(self.event('2026-10-10')['updated_at'], '2026-10-07T22:00:00.000+09:00')
        # 時計が戻っていても、前の時刻より後にする。
        self.db.set_date_event('nagamachiminami', '2026-10-10', '4台構成', now=at('2026-10-07T21:00:00+09:00'))
        self.assertEqual(self.event('2026-10-10')['updated_at'], '2026-10-07T22:00:00.001+09:00')

    def test_removing_leaves_a_mark_that_screens_do_not_show(self):
        self.db.set_date_event('nagamachiminami', '2026-10-10', '半列', now=at('2026-10-07T22:00:00+09:00'))
        self.db.set_date_event('nagamachiminami', '2026-10-10', None, now=at('2026-10-08T09:00:00+09:00'))
        self.assertIsNone(self.event('2026-10-10'))
        mark = self.event('2026-10-10', removed=True)
        self.assertEqual((mark['name'], mark['updated_at']), (None, '2026-10-08T09:00:00.000+09:00'))
        # 何も無い日を「イベントなし」にしても、印は作らない。
        self.db.set_date_event('nagamachiminami', '2026-10-20', None)
        self.assertIsNone(self.event('2026-10-20', removed=True))

    def test_a_range_is_written_once_for_every_day(self):
        days = range_days(date(2026, 10, 14), date(2026, 10, 12))
        self.assertEqual(days, ['2026-10-12', '2026-10-13', '2026-10-14'])
        self.db.set_date_event_days('nagamachiminami', days, '4台構成', now=at('2026-10-07T22:00:00+09:00'))
        self.assertEqual([e['day'] for e in self.db.date_events(location='nagamachiminami')
                          if e['day'] >= '2026-10-12'], days)

    def test_untimed_events_from_before_the_calendar_still_load(self):
        # 2026-10-07より前のイベント（INITIAL_DATE_EVENTS など）は時刻なしのまま読める。
        self.assertEqual(self.event('2026-09-14')['name'], '4台構成')
        self.assertNotIn('updated_at', self.event('2026-09-14'))

    def test_the_names_list_has_the_defaults_then_the_names_in_use(self):
        self.db.set_date_event('nagamachiminami', '2026-10-10', 'コンパス導入')
        names = self.db.date_event_names('nagamachiminami')
        self.assertEqual(names[:5], ['超探す楽しみ', '半列', '4台構成', 'バラエティ', '華の日'])
        self.assertIn('コンパス導入', names)


class MergeTests(unittest.TestCase):
    def ev(self, name, when=None, day='2026-10-10'):
        event = dict(store='nagamachiminami', day=day, name=name)
        if when:
            event['updated_at'] = when
        return event

    def test_the_newer_entry_wins_and_a_tie_goes_to_the_incoming_one(self):
        merged, changed, _ = merge_date_events([self.ev('A', '2026-10-07T22:00:00+09:00')],
                                               [self.ev('B', '2026-10-07T13:00:01Z')])
        self.assertEqual((merged[0]['name'], changed), ('B', 1))
        merged, changed, _ = merge_date_events([self.ev('A', '2026-10-07T22:00:00+09:00')],
                                               [self.ev('B', '2026-10-07T12:59:59Z')])
        self.assertEqual((merged[0]['name'], changed), ('A', 0))
        merged, _, _ = merge_date_events([self.ev('A', '2026-10-07T22:00:00+09:00')],
                                         [self.ev('B', '2026-10-07T13:00:00Z')])
        self.assertEqual(merged[0]['name'], 'B')

    def test_a_timed_entry_beats_an_untimed_one_in_either_order(self):
        self.assertEqual(merge_date_events([self.ev('古い')], [self.ev('新', '2026-10-07T22:00:00+09:00')])[0][0]['name'], '新')
        self.assertEqual(merge_date_events([self.ev('新', '2026-10-07T22:00:00+09:00')], [self.ev('古い')])[0][0]['name'], '新')

    def test_untimed_on_both_sides_keeps_the_stored_one_and_counts_a_conflict(self):
        merged, changed, conflicts = merge_date_events([self.ev('A')], [self.ev('B')])
        self.assertEqual((merged[0]['name'], changed, conflicts), ('A', 0, 1))

    def test_a_removal_mark_is_not_undone_by_an_older_backup(self):
        mark = self.ev(None, '2026-10-08T09:00:00+09:00')
        merged, changed, _ = merge_date_events([mark], [self.ev('半列'), self.ev('半列', '2026-10-07T22:00:00+09:00')])
        self.assertEqual((merged[0]['name'], changed), (None, 0))


class InAdvanceTests(unittest.TestCase):
    def test_entered_before_three_oclock_of_the_day_counts_as_in_advance(self):
        # 営業日の切り替えは3時（2026-10-26に2時から変更）。その日の3時より前の入力が「事前」。
        def ev(when):
            return dict(store='saiwaichou', day='2026-10-10', name='華の日', updated_at=when)
        self.assertTrue(date_event_in_advance(ev('2026-10-09T23:00:00+09:00')))
        self.assertTrue(date_event_in_advance(ev('2026-10-10T02:30:00+09:00')))
        self.assertTrue(date_event_in_advance(ev('2026-10-10T02:59:59+09:00')))
        self.assertTrue(date_event_in_advance(ev('2026-10-09T17:59:59Z')))
        self.assertFalse(date_event_in_advance(ev('2026-10-10T03:00:00+09:00')))
        self.assertFalse(date_event_in_advance(ev('2026-10-09T18:00:00Z')))
        self.assertFalse(date_event_in_advance(ev('2026-10-11T10:00:00+09:00')))
        self.assertFalse(date_event_in_advance(dict(store='saiwaichou', day='2026-10-10', name='華の日')))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.db = Store(self.folder / 'database.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save([dict(store='nagamachiminami', kind_code=21, day='2026-10-06', machine='試験機種',
                           rack=1, games=3000, bb=12, rb=6)])

    def test_backups_and_the_viewer_file_carry_future_events_and_marks(self):
        self.db.set_date_event('nagamachiminami', '2026-10-20', '半列', now=at('2026-10-07T22:00:00+09:00'))
        self.db.set_date_event('nagamachiminami', '2026-09-14', None, now=at('2026-10-07T22:01:00+09:00'))
        export_backup(self.db, self.folder / 'b.json')
        events = json.loads((self.folder / 'b.json').read_text(encoding='utf-8'))['date_events']
        self.assertIn(dict(store='nagamachiminami', day='2026-10-20', name='半列',
                           updated_at='2026-10-07T22:00:00.000+09:00'), events)
        self.assertIn(dict(store='nagamachiminami', day='2026-09-14', name=None,
                           updated_at='2026-10-07T22:01:00.000+09:00'), events)
        export_viewer(self.db, self.folder / 'v.json')
        viewer = json.loads((self.folder / 'v.json').read_text(encoding='utf-8'))['date_events']
        self.assertIn('2026-10-20', [e['day'] for e in viewer])

    def test_an_events_only_file_from_the_viewer_is_merged(self):
        self.db.set_date_event('saiwaichou', '2026-10-10', '仮', now=at('2026-10-07T20:00:00+09:00'))
        path = self.folder / 'database-backup-browser-events-20261007-221000.json'
        path.write_text(json.dumps(dict(format='database-backup', version=1, source='browser', records=[],
                                        date_events=[dict(store='saiwaichou', day='2026-10-10', name='華の日',
                                                          updated_at='2026-10-07T13:10:00.000Z'),
                                                     dict(store='nagamachiminami', day='2026-09-15', name=None,
                                                          updated_at='2026-10-07T13:10:00.000Z')])),
                        encoding='utf-8')
        self.assertEqual(read_backup_file(path), ([], []))
        plan = import_backup(self.db, path)
        self.assertEqual((plan['events_added'], plan['event_conflicts']), (2, 0))
        self.assertEqual(self.db.date_events(location='saiwaichou', day='2026-10-10')[0]['name'], '華の日')
        self.assertEqual(self.db.date_events(location='nagamachiminami', day='2026-09-15'), [])

    def test_an_unreadable_time_or_an_untimed_removal_is_rejected(self):
        for event in (dict(store='saiwaichou', day='2026-10-10', name='華の日', updated_at='昨日'),
                      dict(store='saiwaichou', day='2026-10-10', name=None)):
            path = self.folder / 'bad.json'
            path.write_text(json.dumps(dict(format='database-backup', version=1, records=[], date_events=[event])),
                            encoding='utf-8')
            with self.assertRaises(ValueError):
                import_backup(self.db, path)


class CalendarHelperTests(unittest.TestCase):
    def test_weeks_start_on_sunday_and_other_months_are_blank(self):
        weeks = month_weeks(2026, 10)
        self.assertEqual(weeks[0][:4], [None, None, None, None])
        self.assertEqual(weeks[0][4], date(2026, 10, 1))
        self.assertEqual(shift_month(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(shift_month(date(2026, 1, 1), -1), date(2025, 12, 1))

    def test_a_late_or_untimed_event_gets_the_mark(self):
        day = date(2026, 10, 10)
        early = dict(store='saiwaichou', day='2026-10-10', name='華の日', updated_at='2026-10-09T22:00:00+09:00')
        late = dict(early, updated_at='2026-10-10T12:00:00+09:00')
        self.assertEqual(cell_text(day, None), '10')
        self.assertEqual(cell_text(day, early), '10\n華の日')
        self.assertEqual(cell_text(day, late), '10\n華の日' + LATE_MARK)
        self.assertEqual(cell_text(day, dict(store='saiwaichou', day='2026-10-10', name='華の日')), '10\n華の日' + LATE_MARK)



class PscubeCalendarTests(unittest.TestCase):
    """P’s CUBEのイベントカレンダー（2026-10-08）。店舗の全貸玉に同じ名前を付ける。"""

    def setUp(self):
        from pscube_import import PscubeStore, ROOT_URL
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'pscube.sqlite3'
        self.store = PscubeStore(self.path)
        self.addCleanup(self.store.close)
        url = ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2'
        machines = [{'store': 'c740601', 'rate': rate, 'machine': name, 'expected_count': 1,
                     'url': ROOT_URL + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai={rate}&nmk_kisyu={name}'}
                    for name, rate in (('L東京喰種', '20'), ('ﾏｲｼﾞｬｸﾞﾗｰV', '20'), ('ﾏｲｼﾞｬｸﾞﾗｰV', '5'))]
        self.store.import_page({'format': 'pscube-viewer', 'version': 1, 'source_url': url,
                                'machines': machines, 'records': []}, url)

    def test_calendar_decodes_only_requested_days_and_preserves_rates(self):
        import json
        from unittest.mock import patch
        from event_calendar import PscubeEvents
        for day in ['2026-09-30', '2026-10-01', '2026-10-31', '2026-11-01']:
            for rate in ['5', '20']:
                row = dict(store='c740601', day=day, rate=rate, rack=1,
                           machine='試験機種', games=3000, bb=10, rb=5,
                           net_medals=100 if rate == '20' else -50)
                self.store.db.execute('INSERT INTO records VALUES (?,?)',
                                      (day + rate, json.dumps(row)))
        self.store.db.commit()
        original = json.loads
        decoded_days = []
        def decode(text, *args, **kwargs):
            value = original(text, *args, **kwargs)
            if isinstance(value, dict) and 'net_medals' in value:
                decoded_days.append(value['day'])
            return value
        with patch('event_calendar.json.loads', side_effect=decode):
            nets = PscubeEvents(self.path).nets('pscube', '2026-10-01', '2026-10-31')
            self.assertEqual(set(decoded_days), {'2026-10-01', '2026-10-31'})
            self.assertEqual(len(decoded_days), 4)
            decoded_days.clear()
            rows = PscubeEvents(self.path).day_records('pscube', '2026-10-31')
            self.assertEqual(decoded_days, ['2026-10-31'] * 2)
        self.assertEqual(set(nets), {'2026-10-01', '2026-10-31'})
        self.assertEqual([r['net'] for r in rows], [-50, 100])
        self.assertEqual([r['machine'] for r in rows], ['5スロ 試験機種', '20スロ 試験機種'])

    def test_future_days_and_a_range_get_every_rate(self):
        self.store.set_date_event_days(['2026-10-20', '2026-10-21'], '周年', now=at('2026-10-08T12:00:00+09:00'))
        events = [e for e in self.store.date_events() if e['day'] == '2026-10-21']
        self.assertEqual(sorted(e['rate'] for e in events), ['20', '5'])
        self.assertEqual({e['updated_at'] for e in events}, {'2026-10-08T03:00:00.000Z'})
        self.assertEqual(self.store.date_event_entries()['2026-10-20']['name'], '周年')

    def test_same_name_keeps_the_time_and_removing_nothing_leaves_no_mark(self):
        self.store.set_date_event('2026-10-20', '周年', now=at('2026-10-08T12:00:00+09:00'))
        self.store.set_date_event('2026-10-20', '周年', now=at('2026-10-20T12:00:00+09:00'))
        entry = self.store.date_event_entries()['2026-10-20']
        self.assertTrue(date_event_in_advance(dict(entry, store='saiwaichou')))
        self.store.set_date_event('2026-10-25', None)
        self.assertEqual([e for e in self.store.date_events() if e['day'] == '2026-10-25'], [])
        self.store.set_date_event('2026-10-20', None, now=at('2026-10-21T12:00:00+09:00'))
        self.assertNotIn('2026-10-20', self.store.date_event_entries())

    def test_the_calendar_backend_saves_and_runs_the_backup_hook(self):
        from event_calendar import PscubeEvents
        called = []
        # 保存は今の時刻で記録されるので、ずっと先の日を使う（2026-10-30にした日付は、その日の3時を過ぎると
        # 「前もって登録」でなくなり＊が付いて失敗した、2026-10-30）。
        events = PscubeEvents(self.path, lambda store: called.append(store.date_event_for('2099-10-30')))
        self.assertEqual(events.title, 'イベントカレンダー（P-STATION）')
        self.assertEqual(events.stores, {'pscube': 'P-STATION'})
        events.save('pscube', ['2099-10-30'], '末尾イベ')
        entries, names = events.load('pscube')
        self.assertEqual((entries['2099-10-30']['name'], names, called), ('末尾イベ', ['末尾イベ'], ['末尾イベ']))
        self.assertEqual(cell_text(date(2099, 10, 30), entries['2099-10-30']), '30\n末尾イベ')



class SharedCalendarTests(unittest.TestCase):
    """共有カレンダー（2026-10-08）：同期フォルダの共有ファイルを取り込む。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.db = Store(self.folder / 'database.sqlite3')
        self.addCleanup(self.db.close)

    def write(self, name, events):
        (self.folder / name).write_text(json.dumps(dict(format='database-events', version=1, events=events),
                                                   ensure_ascii=False), encoding='utf-8')

    def test_newer_shared_entries_come_in_and_older_ones_do_not(self):
        from core import SHARED_EVENTS_NAME, pull_shared_events
        self.assertEqual(pull_shared_events(self.db, self.folder), 0, 'no file yet')
        self.db.set_date_event('saiwaichou', '2026-10-20', 'PCで入力', now=at('2026-10-08T12:00:00+09:00'))
        self.write(SHARED_EVENTS_NAME, [
            dict(store='saiwaichou', day='2026-10-20', name='古い', updated_at='2026-10-08T02:00:00.000Z'),
            dict(store='saiwaichou', day='2026-10-21', name='iPhoneで入力', updated_at='2026-10-08T04:00:00.000Z'),
            dict(store='nagamachiminami', day='2026-09-14', name=None, updated_at='2026-10-08T04:00:00.000Z'),
            dict(store='nagamachiminami', day='2026-10-22', name='時刻なしは取らない'),
        ])
        self.assertEqual(pull_shared_events(self.db, self.folder), 2)
        self.assertEqual(self.db.date_events(location='saiwaichou', day='2026-10-20')[0]['name'], 'PCで入力')
        self.assertEqual(self.db.date_events(location='saiwaichou', day='2026-10-21')[0]['name'], 'iPhoneで入力')
        self.assertEqual(self.db.date_events(location='nagamachiminami', day='2026-09-14'), [])
        self.assertEqual(self.db.date_events(location='nagamachiminami', day='2026-10-22'), [])
        self.assertEqual(pull_shared_events(self.db, self.folder), 0, 'nothing new the second time')

    def test_a_broken_shared_file_is_ignored(self):
        from core import SHARED_EVENTS_NAME, pull_shared_events
        (self.folder / SHARED_EVENTS_NAME).write_text('{broken', encoding='utf-8')
        self.assertEqual(pull_shared_events(self.db, self.folder), 0)
        self.assertEqual(pull_shared_events(self.db, None), 0)

    def test_pscube_shared_entries_come_in(self):
        from pscube_import import SHARED_EVENTS_NAME, PscubeStore
        store = PscubeStore(self.folder / 'pscube.sqlite3')
        self.addCleanup(store.close)
        self.write(SHARED_EVENTS_NAME, [dict(store='c740601', rate='20', day='2026-10-25', name='周年',
                                             updated_at='2026-10-08T04:00:00.000Z')])
        self.assertEqual(store.pull_shared_events(self.folder), 1)
        self.assertEqual(store.date_event_for('2026-10-25'), '周年')
        self.assertEqual(store.pull_shared_events(self.folder), 0)


if __name__ == '__main__':
    unittest.main()


def measurement(heights):
    """tests/test_meruhen_net.py と同じ形のグラフ（ゼロ線 200.5、高さはゼロ線からの差）。"""
    curve = [[i * 10.0 + 0.5, 200.5 - h] for i, h in enumerate(heights)]
    ys = [y for _, y in curve]
    return dict(baseline_y=200.5, peak_y=min(ys), trough_y=max(ys), end_y=curve[-1][1], curve=curve)


class CalendarNetTests(unittest.TestCase):
    """カレンダーの各日の総差枚（2026-10-08）。Android・閲覧ページの dailyNet と同じ数え方。"""

    def test_meruhen_adds_estimated_nets_and_skips_unknown_broken_and_placeholder_racks(self):
        from event_calendar import meruhen_day_nets, net_color, net_text, MINUS_COLOR, PLUS_COLOR
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Store(Path(tmp.name) / 'database.sqlite3')
        self.addCleanup(db.close)

        def put(store, day, rack, payload):
            db.db.execute('INSERT INTO days(store, day, machine, rack, payload) VALUES(?,?,?,?,?)',
                          (store, day, 'm', rack, payload if isinstance(payload, str) else json.dumps(payload)))
        row = dict(games=3000, bb=10, rb=5)
        put('saiwaichou', '2026-10-04', 1, dict(row, max_hold=2376, graph_measurement=measurement([0, -63, 40, 147, 128])))
        put('saiwaichou', '2026-10-04', 2, dict(row, max_hold=2900, graph_measurement=measurement([0, 120, 40, -50])))
        put('saiwaichou', '2026-10-04', 3, dict(row, max_hold=500))                     # グラフなし：数えない
        put('saiwaichou', '2026-10-04', 4, dict(row, games=88888888, max_hold=2376,
                                                 graph_measurement=measurement([0, -63, 40, 147, 128])))  # 整備中の値
        put('saiwaichou', '2026-10-04', 5, '{broken')                                 # 読めない行
        put('nagamachiminami', '2026-10-04', 1, dict(row, max_hold=2376, graph_measurement=measurement([0, 10])))
        put('saiwaichou', '2026-11-01', 1, dict(row, max_hold=2376, graph_measurement=measurement([0, -63, 40, 147, 128])))
        put('saiwaichou', '2026-10-05', 1, dict(row, max_hold=500))
        db.db.commit()
        nets = meruhen_day_nets(db, 'saiwaichou', '2026-10-01', '2026-10-31')
        self.assertEqual(sorted(nets), ['2026-10-04', '2026-10-05'])
        self.assertEqual((nets['2026-10-04']['total'], nets['2026-10-04']['captured']), (1417 - 1122, 2))
        self.assertEqual(net_text(nets['2026-10-04']), '+295')
        self.assertEqual(net_color(nets['2026-10-04']), PLUS_COLOR)
        self.assertIsNone(nets['2026-10-05']['total'], '差枚が1台も無い日は0にしない')
        self.assertEqual(net_text(nets['2026-10-05']), '')
        self.assertEqual(net_text({'total': -1500, 'needs_check': 1}), '-1,500', 'マスには※を付けない')
        self.assertEqual(net_color({'total': -1500}), MINUS_COLOR)

    def test_pscube_uses_the_site_net_and_keeps_rates_apart(self):
        from event_calendar import net_text, pscube_day_nets

        def rec(day, rate, net, **extra):
            return dict(dict(day=day, rate=rate, games=3000, bb=10, rb=5, my=1000, net_medals=net), **extra)
        records = [rec('2026-10-04', '20', 1200), rec('2026-10-04', '20', -300), rec('2026-10-04', '20', None),
                   rec('2026-10-04', '20', 5000, my=88888888), rec('2026-09-30', '20', 100)]
        nets = pscube_day_nets(records, '2026-10-01', '2026-10-31')
        self.assertEqual((nets['2026-10-04']['total'], nets['2026-10-04']['captured']), (900, 2))
        self.assertNotIn('2026-09-30', nets)
        both = pscube_day_nets(records + [rec('2026-10-04', '5', -40)], '2026-10-01', '2026-10-31')
        self.assertEqual(net_text(both['2026-10-04']).splitlines(), ['20スロ +900', '5スロ -40'])

    def test_the_pscube_backend_reads_nets_from_the_records(self):
        from event_calendar import PscubeEvents
        from pscube_import import PscubeStore
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'pscube.sqlite3'
        store = PscubeStore(path)
        store.db.execute('INSERT INTO records(key, payload) VALUES(?, ?)',
                         ('k', json.dumps(dict(store='c740601', rate='20', day='2026-10-04', games=3000, bb=10, rb=5,
                                               my=1000, net_medals=-250))))
        store.db.commit()
        store.close()
        nets = PscubeEvents(path).nets('pscube', '2026-10-01', '2026-10-31')
        self.assertEqual(nets['2026-10-04']['total'], -250)


class DaySummaryTests(unittest.TestCase):
    """日付を押したときのTOP10・強かった機種5選（2026-10-09）。Flutter calendarDaySummary の試験と同じ例。"""

    def rows(self):
        racks = [('機種A', 1, 1200, 3000), ('機種A', 2, -300, 4000), ('機種A', 3, None, 5000), ('機種A', 4, 800, 2000),
                 ('機種A', 5, 800, 2500), ('機種B', 11, 50, 9000), ('機種B', 12, 60, 8000), ('機種C', 21, 9999, 12000)]
        racks += [('機種A', i, -i, 1000) for i in range(30, 40)]
        return [dict(machine=m, rack=rack, net=net, games=games, bb=10, rb=5, needs_check=False)
                for m, rack, net, games in racks]

    def test_net_and_games_rankings_and_five_machines_by_average_games(self):
        """PCは差枚・回転数ランキングとも TOP50（2026-10-11 利用者「差枚ランキング、回転数ランキングTOP50」）。"""
        from event_calendar import DAY_TOP, day_summary
        self.assertEqual(DAY_TOP, 50)
        top, games, machines = day_summary(self.rows())
        self.assertEqual([r['rack'] for r in top[:5]], [21, 1, 5, 4, 12], '同じ差枚は回転数の多い方')
        self.assertEqual(len(top), 17, '差枚のわかった台すべて（50台まで）')
        self.assertNotIn(3, [r['rack'] for r in top], '差枚の無い台は入れない')
        self.assertEqual([r['rack'] for r in games[:5]], [21, 11, 12, 3, 2], '回転数の多い順。差枚の無い台も入れる')
        self.assertEqual(len(games), 18)
        self.assertEqual(len(day_summary(self.rows(), limit=10)[0]), 10)
        self.assertEqual([(m['machine'], m['racks'], m['average']) for m in machines],
                         [('機種B', 2, 8500), ('機種A', 15, 1767)], '1台だけの機種は入れない')

    def test_backends_return_the_racks_of_the_day_without_placeholder_numbers(self):
        from event_calendar import MeruhenEvents, PscubeEvents
        from pscube_import import PscubeStore
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Store(Path(tmp.name) / 'database.sqlite3')
        for rack, payload in ((1, dict(games=3000, bb=10, rb=5, max_hold=2376, graph_measurement=measurement([0, -63, 40, 147, 128]))),
                              (2, dict(games=88888888, bb=10, rb=5, max_hold=500)),
                              (3, dict(games=1000, bb=1, rb=1, max_hold=100))):
            db.db.execute('INSERT INTO days(store, day, machine, rack, payload) VALUES(?,?,?,?,?)',
                          ('saiwaichou', '2026-10-04', '北斗', rack, json.dumps(payload)))
        db.db.commit()
        db.close()
        rows = MeruhenEvents(Path(tmp.name) / 'database.sqlite3').day_records('saiwaichou', '2026-10-04')
        self.assertEqual([(r['rack'], r['net']) for r in rows], [(1, 1417), (3, None)])
        self.assertEqual(MeruhenEvents(Path(tmp.name) / 'database.sqlite3').day_records('saiwaichou', '2026-10-05'), [])
        path = Path(tmp.name) / 'pscube.sqlite3'
        store = PscubeStore(path)
        for key, rate, net in (('a', '20', 300), ('b', '5', -40)):
            store.db.execute('INSERT INTO records(key, payload) VALUES(?, ?)', (key, json.dumps(dict(
                store='c740601', rate=rate, day='2026-10-04', machine='ジャグラー', rack=1, games=3000, bb=10, rb=5,
                my=1000, net_medals=net))))
        store.db.commit()
        store.close()
        rows = PscubeEvents(path).day_records('pscube', '2026-10-04')
        self.assertEqual(sorted((r['machine'], r['net']) for r in rows), [('20スロ ジャグラー', 300), ('5スロ ジャグラー', -40)],
                         '貸玉が複数ある日は機種名に貸玉を付けて分ける')
