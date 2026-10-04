import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from datetime import datetime

from pscube_import import PscubeStore, ROOT_URL, business_day, installation_count, recent_business_days


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

    def test_business_day_changes_at_2am_japan_time(self):
        self.assertEqual(business_day(datetime(2026, 10, 4, 1, 59)), '2026-10-03')
        self.assertEqual(business_day(datetime(2026, 10, 4, 2, 0)), '2026-10-04')
        self.assertEqual(business_day(datetime(2026, 10, 4, 23, 30)), '2026-10-04')
        days = recent_business_days(datetime(2026, 10, 4, 1, 0))
        self.assertEqual((days[0], days[1], days[-1], len(days)), ('2026-10-03', '2026-10-02', '2026-09-27', 7))

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
        self.assertEqual(again['next_url'], self.machines[1]['url'])
        bottom = self.store.import_page(self.page(self.index_url, self.machines), self.index_url, expected_day=yesterday, direction='bottom', fresh_since=known)
        self.assertEqual(bottom['next_url'], self.machines[1]['url'])
        # 基準の時刻がまだ無い（今回まだ1ページも保存していない）ときは、決めた向きの最初の機種で基準を確かめる。
        fresh = self.store.import_page(self.page(self.index_url, self.machines), self.index_url, expected_day=yesterday, direction='bottom')
        self.assertEqual(fresh['next_url'], self.machines[-1]['url'])

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
        end = datetime.fromisoformat('2026-10-02T02:00:00+09:00').timestamp()
        self.assertEqual(stale_cutoff('2026-10-01', '2026-10-03T09:00:00+09:00'), end, '終わった日は翌日の午前2時で頭打ち')
        self.assertEqual(stale_cutoff('2026-10-01', '2026-10-01T23:12:00+09:00'),
                         datetime.fromisoformat('2026-10-01T23:12:00+09:00').timestamp())
        self.assertIsNone(stale_cutoff('2026-10-01', None))

    def test_installation_count_uses_the_current_machine_without_writing(self):
        self.machines[0]['expected_count'] = 31
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
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

    def test_nonconsecutive_days_and_wrong_rack_reject_before_writing(self):
        machine, record, payload = self.seed_rack()
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

    def test_bad_graph_rejects_whole_page_and_keeps_existing_export(self):
        machine, record, _ = self.seed_rack()
        target = self.store.export_viewer(Path(self.tmp.name) / 'viewer.json')
        before = target.read_bytes()
        record['graph']['points'] = [[0, 10], [1, float('nan')]]
        with self.assertRaisesRegex(ValueError, '座標'):
            self.store.import_page(self.page(machine['url'], [machine], [record]), machine['url'])
        self.store.export_viewer(target)
        self.assertEqual(target.read_bytes(), before)

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
