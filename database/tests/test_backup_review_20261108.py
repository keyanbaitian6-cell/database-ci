"""2026-11-08 保存とバックアップのレビュー（4件）の再発確認。

1. 古いDBの写しからの出力が、新しいバックアップを上書きする
2. 読めない台を含む全期間バックアップが、正常な控えを置き換えて「成功」になる
3. パチンコの共有用JSONは、同期フォルダへの複製が途中で失敗すると前回分まで壊れる
4. メルヘンの全件削除後、Android用の直近7日分だけ削除前の内容が残る
"""
import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from datetime import date
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backup_status import issue_ticket, output_lock, read_status  # noqa: E402
from core import (AUTO_BACKUP_NAME, RECENT_BACKUP_NAME, RESCUE_BACKUP_NAME, VIEWER_FILE_NAME,  # noqa: E402
                  Store, auto_backup, import_backup, save_settings, snapshot_backup, snapshot_dir,
                  snapshot_store)

FIXTURES = Path(__file__).parent / 'fixtures'
DAY = '2026-10-22'


def row(rack, day=DAY):
    return dict(store='saiwaichou', kind_code=21, day=day, machine='試験', rack=rack, games=3000, bb=10, rb=5)


def records_in(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))['records']


class ReviewCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data, self.sync = self.root / 'data', self.root / 'sync'
        self.sync.mkdir()
        save_settings(self.data, sync_dir=str(self.sync))
        self.db_path = self.data / 'database.sqlite3'
        self.db = Store(self.db_path)
        self.addCleanup(self.db.close)


class StaleSnapshotTests(ReviewCase):
    """1. 先に取った写しが後から書き終えても、新しい出力を古い内容で置き換えない。"""

    def test_an_older_snapshot_finishing_last_does_not_overwrite_the_newer_backup(self):
        self.db.save([row(537)])
        order = (self.data, 'meruhen')
        with snapshot_store(self.db_path, order=order) as older:
            self.db.save([row(538)])
            with snapshot_store(self.db_path, order=order) as newer:
                auto_backup(newer, self.data, strict=True)
            written = {name: (self.sync / name).read_bytes()
                       for name in (AUTO_BACKUP_NAME, RECENT_BACKUP_NAME, VIEWER_FILE_NAME)}
            auto_backup(older, self.data, strict=True)   # 書き終わりの順が入れ替わった
        for name, before in written.items():
            self.assertEqual((self.sync / name).read_bytes(), before, name)
            self.assertEqual(len(records_in(self.sync / name)), 2, name)
        self.assertEqual(read_status(self.data, 'meruhen')['state'], 'success')

    def test_a_save_from_the_live_database_is_newer_than_any_earlier_snapshot(self):
        self.db.save([row(537)])
        with snapshot_store(self.db_path, order=(self.data, 'meruhen')) as older:
            self.db.save([row(538)])
            auto_backup(self.db, self.data, strict=True)   # 削除・取り消しなどの本体からの出力
            auto_backup(older, self.data, strict=True)
        self.assertEqual(len(records_in(self.sync / AUTO_BACKUP_NAME)), 2)
        # その後の写しは、また普通に書ける
        self.db.save([row(539)])
        with snapshot_store(self.db_path, order=(self.data, 'meruhen')) as later:
            auto_backup(later, self.data, strict=True)
        self.assertEqual(len(records_in(self.sync / AUTO_BACKUP_NAME)), 3)

    def test_the_lock_is_exclusive_and_a_wait_can_time_out(self):
        with output_lock(self.data, 'meruhen'):
            with self.assertRaises(OSError):
                with output_lock(self.data, 'meruhen', timeout=0):
                    pass
            with output_lock(self.data, 'pscube', timeout=0):   # 書き出し元が違えば待たない
                pass
        with output_lock(self.data, 'meruhen', timeout=0):     # 外したら取れる
            pass

    def test_pscube_skips_an_older_snapshot(self):
        import pscube_import
        with closing(pscube_import.PscubeStore(self.data / 'pscube.sqlite3')) as store:
            with output_lock(self.data, 'pscube'):
                old_ticket = issue_ticket(self.data, 'pscube')
            self.assertEqual(pscube_import.auto_backup(store, self.data / 'pscube-viewer.json'), 'バックアップ済み')
            before = (self.sync / pscube_import.AUTO_BACKUP_NAME).read_bytes()
            store.output_ticket = old_ticket
            message = pscube_import.auto_backup(store, self.data / 'pscube-viewer.json')
        self.assertIn('より新しい時点の書き出しが先に済んでいます', message)
        self.assertNotIn('失敗', message)
        self.assertEqual((self.sync / pscube_import.AUTO_BACKUP_NAME).read_bytes(), before)

    def test_the_output_worker_numbers_its_snapshot(self):
        # 出力ワーカー（PC版の自動出力）の写しにも番号が付き、本体からの新しい出力の後なら書かない。
        import output_worker
        self.db.save([row(537)])
        real = auto_backup
        seen = []

        def later_live_save_then_output(store, data_dir, **options):
            seen.append(getattr(store, 'output_ticket', None))
            self.db.save([row(538)])
            real(self.db, self.data, strict=True)        # 写しの後に本体から書いた
            return real(store, data_dir, **options)       # 写しの出力は書かずに戻る

        with mock.patch('core.auto_backup', side_effect=later_live_save_then_output):
            output_worker.refresh_outputs(self.db_path, self.data, self.root / 'reports', backup=True)
        self.assertIsNotNone(seen[0])
        self.assertEqual(len(records_in(self.sync / AUTO_BACKUP_NAME)), 2)


class UnreadableRecordTests(ReviewCase):
    """2. 読めない台があるときは、正常な控えを残して救出用を別名で書き、知らせる。"""

    def test_unreadable_rows_keep_the_last_good_backups_and_write_a_rescue_file(self):
        self.db.save([row(537), row(538)])
        auto_backup(self.db, self.data, strict=True)
        dated = date.today().isoformat()
        kept = [self.sync / AUTO_BACKUP_NAME, self.sync / RECENT_BACKUP_NAME,
                snapshot_dir(self.data) / f'database-backup-{dated}.json']
        before = {path: path.read_bytes() for path in kept}
        with self.db.db:
            self.db.db.execute('UPDATE days SET payload=? WHERE rack=?', ('{broken', 538))
        notices = []
        auto_backup(self.db, self.data, strict=True, notices=notices)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data, path.name)   # 正常な前回のまま
        rescue = snapshot_dir(self.data) / RESCUE_BACKUP_NAME
        document = json.loads(rescue.read_text(encoding='utf-8'))
        self.assertEqual(document['recovery_required'], 1)
        self.assertEqual(sum('unreadable_record' in r for r in document['records']), 1)
        status = read_status(self.data, 'meruhen')
        self.assertEqual(status['state'], 'partial')
        self.assertIn('読めない記録が1件', status['message'])
        self.assertIn('viewer', status['completed'])               # 閲覧用は読める台で更新する
        self.assertNotIn('backup', status['completed'])
        self.assertTrue(any('読めない記録が1件' in n for n in notices))
        with closing(Store(self.root / 'other.sqlite3')) as other:
            with self.assertRaises(ValueError):                     # 救出用は通常の読み込みに使えない
                import_backup(other, rescue)
        # 直れば、また普通に書く
        self.db.save([row(538)])
        auto_backup(self.db, self.data, strict=True)
        self.assertEqual(read_status(self.data, 'meruhen')['state'], 'success')
        self.assertEqual(len(records_in(self.sync / AUTO_BACKUP_NAME)), 2)

    def test_a_plain_export_still_wraps_the_row_without_the_rescue_mark(self):
        # 手動の書き出し（app.py）は今までどおり。救出用の印は自動出力の救出用ファイルだけに付く。
        from core import export_backup
        self.db.save([row(537)])
        with self.db.db:
            self.db.db.execute('INSERT INTO days VALUES(?,?,?,?,?)', ('saiwaichou', DAY, '試験', 538, '{broken'))
        stats = {}
        out = self.root / 'manual.json'
        self.assertEqual(export_backup(self.db, out, stats=stats), 2)
        self.assertEqual(stats['unreadable'], 1)
        self.assertNotIn('recovery_required', json.loads(out.read_text(encoding='utf-8')))


class PachinkoSharedCopyTests(unittest.TestCase):
    """3. 共有用JSONの複製が途中で失敗しても、同期フォルダの前回分を壊さず、保存の一言で知らせる。"""

    def test_interrupted_shared_copy_keeps_the_previous_file_and_says_so(self):
        import pachinko

        def table_payload(rows=None):   # test_pachinko.py と同じ形の台一覧
            rows = rows or [['80', '12', '1/222.8', '2673'], ['81', '4', '1/677.5', '2710'], ['82', '0', '-', '615']]
            link = 'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?rack_no={}&target_date=2026-10-10'
            return dict(store='saiwaichou', machine='e東京喰種MW', target_date='2026-10-10', kind_code='1',
                        matrix=[pachinko.PACHI_HEADERS] + rows, links=[link.format(r[0]) for r in rows],
                        source_url='https://meruhenworld.pt.teramoba2.com/saiwaichou/dai_list_pachi')

        tmp =tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        sync = folder / 'sync'
        sync.mkdir()
        save_settings(folder, sync_dir=str(sync))
        slot_db = folder / 'database.sqlite3'
        message, _ = pachinko.save_table(table_payload(), slot_db)
        self.assertNotIn('書き出し', message)
        previous = (sync / pachinko.EXPORT_NAME).read_bytes()

        def interrupt(source, out):
            out.write(source.read(24))
            raise OSError('interrupted')

        with mock.patch('file_io.shutil.copyfileobj', side_effect=interrupt):
            message, _ = pachinko.save_table(table_payload([['83', '7', '1/300.0', '2100']]), slot_db)
        self.assertIn('1台を保存しました', message)
        self.assertIn(f'同期フォルダの {pachinko.EXPORT_NAME} は前回のまま', message)
        self.assertEqual((sync / pachinko.EXPORT_NAME).read_bytes(), previous)
        json.loads(previous.decode('utf-8'))
        local = json.loads((folder / pachinko.EXPORT_NAME).read_text(encoding='utf-8'))
        self.assertEqual(len(local['records']), 4)                 # ローカルの書き出しと台の保存は済んでいる
        self.assertEqual([p.name for p in sync.iterdir() if p.name.endswith('.tmp')], [])   # 書きかけは残らない


class DeleteAllTests(ReviewCase):
    """4. 最後の台まで消しても、直近7日分を削除印付きの空のファイルで書き直す。"""

    def test_deleting_the_last_rack_rewrites_the_recent_backup(self):
        self.db.save([row(537)])
        auto_backup(self.db, self.data, strict=True)
        self.assertEqual(len(records_in(self.sync / RECENT_BACKUP_NAME)), 1)
        self.db.delete('saiwaichou', DAY, '試験', 537)
        auto_backup(self.db, self.data, strict=True)
        for name in (AUTO_BACKUP_NAME, RECENT_BACKUP_NAME):
            document = json.loads((self.sync / name).read_text(encoding='utf-8'))
            self.assertEqual(document['records'], [], name)
            self.assertEqual([(m['day'], m['rack']) for m in document['record_deletions']], [(DAY, 537)], name)
        self.assertIn('recent', read_status(self.data, 'meruhen')['completed'])
        # Androidの試験（database_android/test/recent_backup_test.dart）が読む見本と同じ形。
        written = json.loads((self.sync / RECENT_BACKUP_NAME).read_text(encoding='utf-8'))
        sample = json.loads((FIXTURES / 'recent_backup_after_delete_all.json').read_text(encoding='utf-8'))
        def shape(document):
            return {k: v for k, v in document.items() if k not in ('exported_at', 'since')}
        for document in (written, sample):
            for mark in document['record_deletions']:
                mark.pop('deleted_at', None)
        self.assertEqual(shape(written), shape(sample))
        self.assertEqual(sample['records'], [])


if __name__ == '__main__':
    unittest.main()
