import json
import os
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pscube_import
from pscube_import import (AUTO_BACKUP_NAME, VIEWER_DRIVE_NAME, PscubeStore, ROOT_URL, _machine_key, _record_key,
                           auto_backup, is_pscube_backup, latest_pscube_backup, thin_graph)

SHOP = 'c740601'
TODAY = date(2026, 10, 1)


def machine(name='ﾏｲｼﾞｬｸﾞﾗｰV', **patch):
    return {'store': SHOP, 'rate': '20', 'machine': name, 'expected_count': 2, 'machine_type': None,
            'url': ROOT_URL + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu={name}', **patch}


def record(m, rack, day, games=3000, my=1000, graph=None, **patch):
    return {'store': SHOP, 'rate': m['rate'], 'machine': m['machine'], 'rack': rack, 'day': day, 'bb': 8, 'rb': 4,
            'at_art': 0, 'games': games, 'my': my, 'observed_at': f'{day}T12:00:00+09:00',
            'detail_url': ROOT_URL + f'cgi-bin/nc-v06-001.php?cd_dai={rack}#{day.replace("-", "")}',
            'graph': graph, **patch}


def long_graph(n=60):
    # 100から30番目の40まで上がり（最高）、そのあと127まで下がる（最低・終点）。
    return {'kind': 'daily', 'zero_y': 100.0,
            'points': [[float(i), float(100 - 2 * i if i <= 30 else 40 + (i - 30) * 3)] for i in range(n)]}


def put(store, m, records, captured=()):
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO machines VALUES (?,?)', (_machine_key(m), json.dumps(m, ensure_ascii=False)))
        for r in records:
            store.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', (_record_key(r), json.dumps(r, ensure_ascii=False)))
        for r in captured:
            store.db.execute('INSERT OR IGNORE INTO rack_captures VALUES (?)', (_record_key(r),))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.sync = self.root / 'drive'
        self.sync.mkdir()
        self.data.mkdir()
        self.export = self.data / 'pscube-viewer.json'
        self.store = PscubeStore(self.data / 'pscube.sqlite3')
        self.addCleanup(self.store.close)
        self.m = machine()
        days = [(TODAY - timedelta(days=i)).isoformat() for i in range(40)]
        self.records = [record(self.m, rack, day, graph=long_graph() if rack == 1 else None) for day in days for rack in (1, 2)]
        put(self.store, self.m, self.records, captured=[r for r in self.records if r['rack'] == 1 and r['day'] == TODAY.isoformat()])

    def use_sync_dir(self):
        (self.data / 'settings.json').write_text(json.dumps({'sync_dir': str(self.sync)}), encoding='utf-8')

    def test_auto_backup_writes_local_dated_drive_and_viewer_files_with_separate_names(self):
        self.use_sync_dir()
        (self.sync / 'database-backup-auto.json').write_text('{"keep":1}', encoding='utf-8')
        status = auto_backup(self.store, self.export, today=TODAY)
        self.assertEqual(status, 'バックアップ済み')
        names = {p.name for p in self.sync.iterdir()}
        # 同期フォルダの目印（2026-11-03、core.SYNC_MARK_NAME）も置く。
        self.assertEqual(names, {'database-backup-auto.json', AUTO_BACKUP_NAME, VIEWER_DRIVE_NAME, 'backups',
                                 'database-sync-folder.json'})
        self.assertEqual((self.sync / 'database-backup-auto.json').read_text(encoding='utf-8'), '{"keep":1}')
        self.assertEqual([p.name for p in (self.sync / 'backups').iterdir()], ['pscube-backup-2026-10-01.json'])
        full = json.loads((self.sync / AUTO_BACKUP_NAME).read_text(encoding='utf-8'))
        self.assertEqual((full['format'], full['kind'], full['source'], len(full['records'])), ('pscube-viewer', 'backup', 'pc', 80))
        self.assertRegex(full['exported_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        self.assertEqual(len(full['rack_captures']), 1)
        self.assertEqual(json.loads(self.export.read_text(encoding='utf-8'))['records'], full['records'])

    def test_without_sync_folder_only_local_copies_are_made(self):
        status = auto_backup(self.store, self.export, today=TODAY)
        self.assertIn('同期フォルダ未設定', status)
        self.assertTrue((self.data / 'backups' / 'pscube-backup-2026-10-01.json').exists())
        self.assertEqual(list(self.sync.iterdir()), [])
        self.assertFalse((self.data / VIEWER_DRIVE_NAME).exists())

    def test_old_dated_copies_are_pruned_but_meruhen_files_are_left_alone(self):
        self.use_sync_dir()
        folder = self.sync / 'backups'
        folder.mkdir()
        for name in ('pscube-backup-2026-09-24.json', 'pscube-backup-2026-09-23.json', 'database-backup-2026-01-01.json', 'pscube-backup-note.json'):
            (folder / name).write_text('{}', encoding='utf-8')
        auto_backup(self.store, self.export, today=TODAY)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ['database-backup-2026-01-01.json', 'pscube-backup-2026-09-24.json', 'pscube-backup-2026-10-01.json', 'pscube-backup-note.json'])

    def test_viewer_file_is_light_but_keeps_what_scoring_reads(self):
        self.use_sync_dir()
        auto_backup(self.store, self.export, today=TODAY)
        light = json.loads((self.sync / VIEWER_DRIVE_NAME).read_text(encoding='utf-8'))
        self.assertEqual(light['kind'], 'viewer')
        self.assertNotIn('rack_captures', light)
        self.assertEqual(len({r['day'] for r in light['records']}), 31)
        self.assertEqual(min(r['day'] for r in light['records']), (TODAY - timedelta(days=30)).isoformat())
        original = long_graph()
        graph = next(r['graph'] for r in light['records'] if r['rack'] == 1)
        self.assertLessEqual(len(graph['points']), 16)
        self.assertEqual(graph['zero_y'], original['zero_y'])
        for pick in (lambda ps: ps[0], lambda ps: ps[-1], lambda ps: min(ps, key=lambda p: p[1]), lambda ps: max(ps, key=lambda p: p[1])):
            self.assertEqual(pick(graph['points']), pick(original['points']))
        self.assertEqual(graph['points'], sorted(graph['points'], key=lambda p: p[0]))
        self.assertLess((self.sync / VIEWER_DRIVE_NAME).stat().st_size, (self.sync / AUTO_BACKUP_NAME).stat().st_size)

    def test_thin_graph_edge_cases(self):
        short = {'kind': 'overview', 'zero_y': 5, 'points': [[0, 5], [1, 4]]}
        self.assertIs(thin_graph(short), short)
        self.assertIsNone(thin_graph(None))
        spike = {'kind': 'daily', 'zero_y': 0, 'points': [[i, 7 if i == 3 else 0] for i in range(500)]}
        self.assertIn([3, 7], thin_graph(spike)['points'])
        self.assertEqual(len(thin_graph(spike)['points']), 16)

    def test_backup_failure_never_raises_and_reports(self):
        self.use_sync_dir()
        with mock.patch.object(pscube_import, 'atomic_copy', side_effect=OSError('disk full')):
            status = auto_backup(self.store, self.export, today=TODAY)
        self.assertIn('失敗', status)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 80)

    def test_backup_round_trips_into_another_store_with_capture_marks(self):
        self.use_sync_dir()
        auto_backup(self.store, self.export, today=TODAY)
        other = PscubeStore(self.root / 'other.sqlite3')
        self.addCleanup(other.close)
        summary = other.import_backup(self.sync / AUTO_BACKUP_NAME)
        self.assertEqual((summary['added'], summary['updated'], summary['unchanged']), (80, 0, 0))
        self.assertEqual(other.db.execute('SELECT COUNT(*) FROM rack_captures').fetchone()[0], 1)
        again = other.import_backup(self.sync / AUTO_BACKUP_NAME)
        self.assertEqual((again['added'], again['updated'], again['unchanged']), (0, 0, 80))
        self.assertEqual(other.export_payload()['records'], self.store.export_payload()['records'])

    def test_light_wrong_shop_and_bad_files_are_refused_without_saving(self):
        self.use_sync_dir()
        auto_backup(self.store, self.export, today=TODAY)
        other = PscubeStore(self.root / 'other.sqlite3')
        self.addCleanup(other.close)
        with self.assertRaisesRegex(ValueError, '軽いファイル'):
            other.import_backup(self.sync / VIEWER_DRIVE_NAME)
        good = json.loads((self.sync / AUTO_BACKUP_NAME).read_text(encoding='utf-8'))
        bad_shop = json.loads(json.dumps(good)); bad_shop['machines'][0]['store'] = 'c1'
        late_bad = json.loads(json.dumps(good)); late_bad['records'][-1]['rack'] = 0
        duplicate = json.loads(json.dumps(good)); duplicate['records'].append(duplicate['records'][0])
        orphan = json.loads(json.dumps(good)); orphan['machines'] = []
        stray_mark = json.loads(json.dumps(good)); stray_mark['rack_captures'] = ['["x"]']
        for payload in (bad_shop, late_bad, duplicate, orphan, stray_mark, {'format': 'database-backup', 'version': 1}, []):
            with self.assertRaises(ValueError):
                other.import_backup(payload)
        self.assertEqual(other.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 0)
        self.assertEqual(other.db.execute('SELECT COUNT(*) FROM machines').fetchone()[0], 0)

    def test_merge_never_replaces_newer_numbers_and_keeps_own_machine_type(self):
        today = TODAY.isoformat()
        newer_local = next(r for r in self.records if r['rack'] == 2 and r['day'] == today)
        put(self.store, {**self.m, 'machine_type': 'normal'}, [{**newer_local, 'games': 4000, 'observed_at': f'{today}T20:00:00+09:00'}])
        older_incoming = {'format': 'pscube-viewer', 'version': 1, 'kind': 'backup', 'machines': [{**self.m, 'machine_type': 'other'}],
                          'records': [{**newer_local, 'games': 3500, 'observed_at': f'{today}T15:00:00+09:00'}]}
        summary = self.store.import_backup(older_incoming)
        self.assertEqual(summary['kept_local'], 1)
        saved = json.loads(self.store.db.execute('SELECT payload FROM records WHERE key=?', (_record_key(newer_local),)).fetchone()[0])
        self.assertEqual(saved['games'], 4000)
        self.assertEqual(json.loads(self.store.db.execute('SELECT payload FROM machines').fetchone()[0])['machine_type'], 'normal')

    def test_newer_numbers_from_a_backup_make_the_rack_pending_again(self):
        today = TODAY.isoformat()
        mine = next(r for r in self.records if r['rack'] == 1 and r['day'] == today)
        key = _record_key(mine)
        incoming = {'format': 'pscube-viewer', 'version': 1, 'kind': 'backup', 'machines': [self.m],
                    'records': [{**mine, 'games': 3300, 'observed_at': f'{today}T22:00:00+09:00'}], 'rack_captures': []}
        summary = self.store.import_backup(incoming)
        self.assertEqual(summary['updated'], 1)
        self.assertIsNone(self.store.db.execute('SELECT key FROM rack_captures WHERE key=?', (key,)).fetchone())

    def test_old_files_without_marks_count_daily_graphs_as_captured(self):
        other = PscubeStore(self.root / 'other.sqlite3')
        self.addCleanup(other.close)
        old = {'format': 'pscube-viewer', 'version': 1, 'machines': [self.m],
               'records': [record(self.m, 1, TODAY.isoformat(), graph=long_graph()), record(self.m, 2, TODAY.isoformat())]}
        other.import_backup(old)
        self.assertEqual(other.db.execute('SELECT COUNT(*) FROM rack_captures').fetchone()[0], 1)

    def test_latest_backup_ignores_own_copy_light_file_and_meruhen_files(self):
        self.use_sync_dir()
        auto_backup(self.store, self.export, today=TODAY)
        self.assertIsNone(latest_pscube_backup(self.sync))
        android = self.sync / 'pscube-backup-android-20261001-120000.json'
        android.write_text((self.sync / AUTO_BACKUP_NAME).read_text(encoding='utf-8'), encoding='utf-8')
        (self.sync / 'database-backup-android-20261001-130000.json').write_text('{"format":"database-backup"}', encoding='utf-8')
        light_copy = self.sync / 'pscube-backup-browser-20261001-140000.json'
        light_copy.write_text((self.sync / VIEWER_DRIVE_NAME).read_text(encoding='utf-8'), encoding='utf-8')
        now = time.time()
        os.utime(android, (now - 100, now - 100))
        os.utime(light_copy, (now, now))
        self.assertEqual(latest_pscube_backup(self.sync), android)

    def test_meruhen_latest_backup_reader_never_picks_up_pscube_files(self):
        import core
        self.use_sync_dir()
        auto_backup(self.store, self.export, today=TODAY)
        (self.sync / 'pscube-backup-android-20261001-120000.json').write_text(
            (self.sync / AUTO_BACKUP_NAME).read_text(encoding='utf-8'), encoding='utf-8')
        meruhen = self.sync / 'database-backup-android-20260930-120000.json'
        meruhen.write_text(json.dumps({'format': core.BACKUP_FORMAT}), encoding='utf-8')
        os.utime(meruhen, (time.time() - 500, time.time() - 500))
        self.assertEqual(core.latest_backup_file(self.sync), meruhen)

    def test_pscube_files_are_recognised_so_the_meruhen_import_does_not_skip_them_all(self):
        self.use_sync_dir()
        auto_backup(self.store, self.export, today=TODAY)
        android = self.sync / 'pscube-backup-android-20261001-230000.json'
        android.write_text((self.sync / AUTO_BACKUP_NAME).read_text(encoding='utf-8'), encoding='utf-8')
        self.assertTrue(is_pscube_backup(android))
        meruhen = self.sync / 'database-backup-android.json'
        meruhen.write_text('{"format": "database-backup", "version": 1, "records": []}', encoding='utf-8')
        self.assertFalse(is_pscube_backup(meruhen))
        self.assertFalse(is_pscube_backup(self.sync / 'missing.json'))

    def test_days_machines_and_manual_backup_for_the_main_window(self):
        from datetime import datetime
        from pscube_import import backup_file_name, write_backup
        self.assertEqual(self.store.days()[0], TODAY.isoformat())
        self.assertEqual(len(self.store.days()), 40)
        oki = machine('沖ﾄﾞｷ!BLACK')
        put(self.store, oki, [record(oki, 9, TODAY.isoformat())])
        self.assertEqual(self.store.machines_for(TODAY.isoformat()), ['ﾏｲｼﾞｬｸﾞﾗｰV'], '沖ドキは選択肢に出さない')
        self.assertEqual(backup_file_name(datetime(2026, 10, 2, 0, 15, 0)), 'pscube-backup-pc-20261002-001500.json')
        target = write_backup(self.store, self.sync / backup_file_name())
        data = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual((data['kind'], data['source']), ('backup', 'pc'))
        self.assertEqual(latest_pscube_backup(self.sync), target, '同期フォルダの最新として読み込める')


if __name__ == '__main__':
    unittest.main()
