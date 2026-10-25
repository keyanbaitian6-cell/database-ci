"""AndroidのP’s CUBEの当日分（Apps Script経由）を、PC版が起動中に自動で読み込む判定（2026-10-26）。"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import pscube_import
from pscube_import import PscubeStore, android_sync_due, android_sync_files
from test_pscube_sync import SHOP, machine, record


def day_backup(m, records):
    """Androidが送る当日分：その日の記録と、記録に対応する機種だけの普通のバックアップ。"""
    return {'format': 'pscube-viewer', 'version': 1, 'kind': 'backup', 'source': 'android',
            'exported_at': '2026-10-26T23:50:00+09:00', 'machines': [m], 'records': records,
            'rack_captures': []}


class AndroidSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sync = Path(self.tmp.name) / 'drive'
        self.sync.mkdir()

    def write(self, name, payload='{}', mtime=1000.0):
        path = self.sync / name
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        os.utime(path, (mtime, mtime))
        return path

    def test_only_android_files_in_update_order(self):
        self.write('pscube-day-android-2026-10-26.json', mtime=3000)
        self.write('pscube-backup-android-20261026-001933.json', mtime=2000)
        for other in ('pscube-backup-auto.json', 'pscube-viewer-drive.json', 'pscube-backup-cloud.json',
                      'pscube-events-shared.json', 'pscube-day-android-2026-10-26.json.tmp',
                      'pscube-day-android-latest.json', 'database-backup-auto.json'):
            self.write(other, mtime=5000)
        self.assertEqual([name for name, _m, _p in android_sync_files(self.sync)],
                         ['pscube-backup-android-20261026-001933.json', 'pscube-day-android-2026-10-26.json'])

    def test_first_use_marks_existing_files_read_then_reads_new_or_changed_versions(self):
        self.write('pscube-backup-android-20261026-001933.json', mtime=2000)
        files = android_sync_files(self.sync)
        due, initial = android_sync_due(files, None, now=9000)
        self.assertEqual(due, [])
        self.assertEqual(initial, {'pscube-backup-android-20261026-001933.json': 2000})
        # 当日分が届く・同じ日の当日分が上書きされる（更新時刻が変わる）と読む。
        self.write('pscube-day-android-2026-10-26.json', mtime=3000)
        due, initial = android_sync_due(android_sync_files(self.sync), dict(initial), now=9000)
        self.assertIsNone(initial)
        self.assertEqual([n for n, _m, _p in due], ['pscube-day-android-2026-10-26.json'])
        seen = {'pscube-backup-android-20261026-001933.json': 2000, 'pscube-day-android-2026-10-26.json': 3000}
        self.assertEqual(android_sync_due(android_sync_files(self.sync), seen, now=9000)[0], [])
        self.write('pscube-day-android-2026-10-26.json', mtime=4000)
        self.assertEqual([n for n, _m, _p in android_sync_due(android_sync_files(self.sync), seen, now=9000)[0]],
                         ['pscube-day-android-2026-10-26.json'])

    def test_file_just_written_by_drive_waits_for_the_next_check(self):
        self.write('pscube-day-android-2026-10-26.json', mtime=9000 - pscube_import.ANDROID_SYNC_SETTLE_SECONDS + 1)
        self.assertEqual(android_sync_due(android_sync_files(self.sync), {}, now=9000)[0], [])
        self.assertEqual(len(android_sync_due(android_sync_files(self.sync), {}, now=9000 + 1)[0]), 1)

    def test_day_only_backup_merges_without_touching_other_days(self):
        m = machine()
        with tempfile.TemporaryDirectory() as directory:
            store = PscubeStore(Path(directory) / 'pscube.sqlite3')
            try:
                old = record(m, 1, '2026-10-25', games=4000)
                store.import_backup(day_backup(m, [old]))
                day = [record(m, 1, '2026-10-26', games=3000), record(m, 2, '2026-10-26', games=2500)]
                summary = store.import_backup(self.write('pscube-day-android-2026-10-26.json', day_backup(m, day)))
                self.assertEqual((summary['added'], summary['updated']), (2, 0))
                saved = {json.loads(p)['day'] + '/' + str(json.loads(p)['rack']): json.loads(p)['games']
                         for (p,) in store.db.execute('SELECT payload FROM records')}
                self.assertEqual(saved, {'2026-10-25/1': 4000, '2026-10-26/1': 3000, '2026-10-26/2': 2500})
                # 同じ当日分をもう一度読んでも増えない。
                again = store.import_backup(self.sync / 'pscube-day-android-2026-10-26.json')
                self.assertEqual((again['added'], again['unchanged']), (0, 2))
            finally:
                store.close()
        self.assertEqual(m['store'], SHOP)


if __name__ == '__main__':
    unittest.main()
