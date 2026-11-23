"""メルヘンの閲覧用の書き出しを店ごとに分ける（2026-11-23 利用者「店ごとに分ける」）。

Googleの同期は PC の閲覧用の入力を1ファイル48MiBまでしか読めず、両店60日の1ファイル（database-viewer.json）が
約49.6MB（上限まで約0.69MB）になった。同期フォルダへは、店ごとのファイル（その店の台と削除の印）と、見出しだけの
database-viewer.json（イベント・当時の翌日候補・日ごとのまとめ・分けた店の一覧）を書く。Googleの同期スクリプトは、
店のファイルを読むとき、その店の台だけを入れ替える（tool/test_meruhen_cloud_sync.mjs で確かめる）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core  # noqa: E402
from backup_status import read_status  # noqa: E402
from core import (VIEWER_FILE_NAME, VIEWER_STORE_FILE_NAMES, Store, _backup_candidates, auto_backup,  # noqa: E402
                  save_settings)

DAY = '2026-11-20'


def row(store, rack, day=DAY):
    return dict(store=store, kind_code=21, day=day, machine='試験', rack=rack, games=3000, bb=10, rb=5)


def doc(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class ViewerSplitExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        root = Path(self.tmp.name)
        self.data, self.sync = root / 'data', root / 'sync'
        self.data.mkdir(); self.sync.mkdir()
        save_settings(self.data, sync_dir=str(self.sync))
        self.db = Store(self.data / 'database.sqlite3')
        self.db.save([row('saiwaichou', 537), row('saiwaichou', 538), row('nagamachiminami', 101)])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_each_store_file_has_only_its_store_and_the_header_file_has_no_racks(self):
        auto_backup(self.db, self.data, strict=True)
        saiwai = doc(self.sync / VIEWER_STORE_FILE_NAMES['saiwaichou'])
        naga = doc(self.sync / VIEWER_STORE_FILE_NAMES['nagamachiminami'])
        self.assertEqual(saiwai['stores'], ['saiwaichou'])
        self.assertEqual(sorted(r['rack'] for r in saiwai['records']), [537, 538])
        self.assertEqual({r['store'] for r in saiwai['records']}, {'saiwaichou'})
        self.assertEqual([r['rack'] for r in naga['records']], [101])
        for part in (saiwai, naga):
            self.assertEqual(part['source'], 'pc-viewer')
            self.assertNotIn('date_events', part, 'イベントは見出しのファイルだけに入れる')
            self.assertNotIn('split_stores', part)
        header = doc(self.sync / VIEWER_FILE_NAME)
        self.assertEqual(header['records'], [])
        self.assertEqual(sorted(header['split_stores']), ['nagamachiminami', 'saiwaichou'])
        self.assertIn('date_events', header)
        self.assertNotIn('record_deletions', header, '削除の印は店のファイルに入れる')
        self.assertEqual(read_status(self.data, 'meruhen')['state'], 'success')

    def test_deletion_marks_go_to_the_file_of_their_store(self):
        marks = [dict(store='saiwaichou', day=DAY, machine='試験', rack=999, deleted_at='2026-11-21T00:00:00+09:00'),
                 dict(store='nagamachiminami', day=DAY, machine='試験', rack=998, deleted_at='2026-11-21T00:00:00+09:00')]
        with mock.patch.object(Store, 'record_deletions',
                               lambda self, location=None, day=None: [m for m in marks if location in (None, m['store'])]):
            auto_backup(self.db, self.data, strict=True)
        self.assertEqual([m['rack'] for m in doc(self.sync / VIEWER_STORE_FILE_NAMES['saiwaichou'])['record_deletions']], [999])
        self.assertEqual([m['rack'] for m in doc(self.sync / VIEWER_STORE_FILE_NAMES['nagamachiminami'])['record_deletions']], [998])

    def test_a_store_file_over_the_google_limit_is_reported_but_still_written(self):
        with mock.patch.object(core, 'VIEWER_GOOGLE_LIMIT', 10):
            auto_backup(self.db, self.data)
        status = read_status(self.data, 'meruhen')
        self.assertEqual(status['state'], 'partial')
        self.assertIn('48MiBを超えました', status['message'])
        self.assertIn('スーパーメルヘンワールド幸町', status['message'])
        self.assertTrue((self.sync / VIEWER_STORE_FILE_NAMES['saiwaichou']).exists())

    def test_the_store_files_are_not_picked_up_as_backups_to_import(self):
        auto_backup(self.db, self.data, strict=True)
        names = {path.name for _, path in _backup_candidates(self.sync)}
        for name in (VIEWER_FILE_NAME, *VIEWER_STORE_FILE_NAMES.values()):
            self.assertNotIn(name, names)


if __name__ == '__main__':
    unittest.main()
