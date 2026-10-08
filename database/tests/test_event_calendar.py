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
    def test_entered_before_two_oclock_of_the_day_counts_as_in_advance(self):
        def ev(when):
            return dict(store='saiwaichou', day='2026-10-10', name='華の日', updated_at=when)
        self.assertTrue(date_event_in_advance(ev('2026-10-09T23:00:00+09:00')))
        self.assertTrue(date_event_in_advance(ev('2026-10-10T01:59:59+09:00')))
        self.assertTrue(date_event_in_advance(ev('2026-10-09T16:59:59Z')))
        self.assertFalse(date_event_in_advance(ev('2026-10-10T02:00:00+09:00')))
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
        events = PscubeEvents(self.path, lambda store: called.append(store.date_event_for('2026-10-30')))
        events.save('pscube', ['2026-10-30'], '末尾イベ')
        entries, names = events.load('pscube')
        self.assertEqual((entries['2026-10-30']['name'], names, called), ('末尾イベ', ['末尾イベ'], ['末尾イベ']))
        self.assertEqual(cell_text(date(2026, 10, 30), entries['2026-10-30']), '30\n末尾イベ')


if __name__ == '__main__':
    unittest.main()
