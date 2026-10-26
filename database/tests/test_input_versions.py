"""保存した記録の版（input_versions.py）。翌日候補の店舗別案を現行と並べて比べるための記録。"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import input_versions
from core import Store
from pscube_import import PscubeStore

ROW = dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine='試験', rack=537,
           games=3000, bb=10, rb=5, captured_at='2026-10-14T23:00:00+09:00')
KEY = 'saiwaichou\t2026-10-14\t試験\t537'


def versions(root):
    input_versions.wait(root)
    with closing(sqlite3.connect(root / input_versions.FILE_NAME)) as db:
        return db.execute("SELECT source, key, day, kind, content FROM versions WHERE key<>'' ORDER BY id").fetchall()


def later(seconds=1):
    return (datetime.now().astimezone() + timedelta(seconds=seconds)).isoformat()


class MeruhenVersionTests(unittest.TestCase):
    def test_only_changed_content_is_added_and_as_of_follows_the_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(Store(root / 'db.sqlite3')) as store:
                store.save([ROW])
                # 取り直して時刻だけ変わった行は版にしない。
                store.save([dict(ROW, captured_at='2026-10-14T23:30:00+09:00')])
                first = versions(root)
                self.assertEqual([(s, k, d, kind) for s, k, d, kind, _ in first],
                                 [('meruhen', KEY, '2026-10-14', 'write')])
                before_change = later(0)
                store.save([dict(ROW, games=3500, captured_at='2026-10-14T23:45:00+09:00')])
                after_change = later(0)
                store.delete(ROW['store'], ROW['day'], ROW['machine'], ROW['rack'])
            kinds = [kind for *_rest, kind, _content in versions(root)]
            self.assertEqual(kinds, ['write', 'write', 'delete'])
            input_versions.wait(root)
            path = root / input_versions.FILE_NAME
            self.assertEqual(input_versions.as_of(path, 'meruhen', before_change)[KEY]['games'], 3000)
            self.assertEqual(input_versions.as_of(path, 'meruhen', after_change)[KEY]['games'], 3500)
            self.assertNotIn(KEY, input_versions.as_of(path, 'meruhen', later()))
            self.assertNotIn('captured_at', json.loads(versions(root)[0][4]))
            with self.assertRaises(ValueError):
                input_versions.as_of(path, 'meruhen', '2026-10-15T02:00:00')

    def test_existing_rows_become_one_baseline_and_preview_image_is_left_out(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = dict(end_x=10, end_y=20, curve=[[0, 1]], preview_image='data:image/png;base64,AAAA')
            with closing(Store(root / 'db.sqlite3')) as store:
                store.save([dict(ROW, graph_measurement=graph)])
            input_versions.wait(root)
            # 検証先を失った状態を新しい完全な履歴と扱わない。
            # この試験では保存済み行からの新規基準点の作成を模擬する。
            with closing(sqlite3.connect(root / 'db.sqlite3')) as raw:
                raw.execute('DROP TABLE iv_outbox');raw.execute('DROP TABLE iv_control')
            (root / input_versions.FILE_NAME).unlink()
            for _ in range(2):
                Store(root / 'db.sqlite3').close()
            rows = versions(root)
            self.assertEqual([(k, kind) for _s, k, _d, kind, _c in rows], [(KEY, 'baseline')])
            saved = json.loads(rows[0][4])['graph_measurement']
            self.assertNotIn('preview_image', saved)
            self.assertEqual(saved['curve'], [[0, 1]])

    def test_restore_and_group_delete_are_recorded_and_other_connections_too(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(Store(root / 'db.sqlite3')) as first, closing(Store(root / 'db.sqlite3')) as second:
                first.save([ROW])
                second.restore_payloads([((ROW['store'], ROW['day'], ROW['machine'], ROW['rack']),
                                          dict(ROW, games=4000))])
                second.delete_group(ROW['day'])
            self.assertEqual([kind for *_r, kind, _c in versions(root)], ['write', 'write', 'delete'])
            self.assertEqual(json.loads(versions(root)[1][4])['games'], 4000)

    def test_failure_to_prepare_never_blocks_opening_or_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / input_versions.FILE_NAME).mkdir()  # 開けない場所
            with closing(Store(root / 'db.sqlite3')) as store:
                store.save([ROW])
                self.assertEqual(len(store.rows()), 1)
                input_versions.wait(root)
                self.assertTrue(input_versions.state())
                self.assertGreater(store.db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0],0)


class PscubeVersionTests(unittest.TestCase):
    def test_records_are_versioned_with_their_day(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = dict(store='c740601', rate='20', day='2026-10-24', machine='試験', rack=101,
                          games=2000, bb=3, rb=2, at_art=0, my=500, observed_at='2026-10-24T22:00:00+09:00')
            store = PscubeStore(root / 'pscube.sqlite3')
            try:
                with store.db:
                    store.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', ('k1', json.dumps(record)))
                    store.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)',
                                     ('k1', json.dumps(dict(record, observed_at='2026-10-24T22:30:00+09:00'))))
                    store.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', ('k1', json.dumps(dict(record, my=800))))
            finally:
                store.close()
            rows = versions(root)
            self.assertEqual([(s, k, d, kind) for s, k, d, kind, _ in rows],
                             [('pscube', 'k1', '2026-10-24', 'write')] * 2)
            self.assertEqual(input_versions.as_of(root / input_versions.FILE_NAME, 'pscube', later())['k1']['my'], 800)

    def test_both_stores_share_one_file_with_separate_baselines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(Store(root / 'database.sqlite3')) as store:
                store.save([ROW])
            PscubeStore(root / 'pscube.sqlite3').close()
            input_versions.wait(root)
            with closing(sqlite3.connect(root / input_versions.FILE_NAME)) as db:
                marks = db.execute("SELECT source FROM versions WHERE key='' AND kind='baseline' ORDER BY source").fetchall()
            self.assertEqual(marks, [('meruhen',), ('pscube',)])


if __name__ == '__main__':
    unittest.main()
