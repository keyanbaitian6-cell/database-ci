"""保存した記録の版（input_versions.py）。翌日候補の店舗別案を現行と並べて比べるための記録。"""
import gc
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import input_versions
from core import Store
from pscube_import import PscubeStore

ROW = dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine='試験', rack=537,
           games=3000, bb=10, rb=5, captured_at='2026-10-14T23:00:00+09:00')
KEY = 'saiwaichou\t2026-10-14\t試験\t537'


def setUpModule():
    # この試験は検証記録の転送を別スレッドで動かす。前の試験のTkが循環参照のまま残っていると、そのスレッドで
    # GCが走ったときに片付けられ「Tcl_AsyncDelete: async handler deleted by the wrong thread」でプロセスごと
    # 落ちる（2026-10-26 CI 40293353918、Python 3.12。test_tk_threads.py と同じ問題）。始める前にメインスレッドで片付ける。
    gc.collect()


def versions(root):
    input_versions.wait(root)
    with closing(sqlite3.connect(root / input_versions.FILE_NAME)) as db:
        return db.execute("SELECT source, key, day, kind, content FROM versions WHERE key<>'' ORDER BY id").fetchall()


def later(seconds=1):
    return (datetime.now().astimezone() + timedelta(seconds=seconds)).isoformat()


class RecordingOn:
    """記録は2026-11-26にやめた（input_versions.RECORDING が False）。記録の仕組みの試験だけ、setUp から後片づけまでを
    記録ありで流す。run() を包むので、test_sqlite_fixture_cleanup のように TestSuite で直接流しても効く。"""
    def run(self, result=None):
        with patch.object(input_versions, 'RECORDING', True):
            return super().run(result)


class RecordingStoppedTests(unittest.TestCase):
    """2026-11-26 利用者「消してもいいなら消していいよ」「おねがい」：記録をやめた後は、本体を開いて保存しても
    記録の表・転送待ち・検証DBを作らず、転送のスレッドも起こさず、状態表示に「検証記録」を出さない。"""
    def test_recording_is_stopped_by_default(self):
        self.assertFalse(input_versions.RECORDING)

    def test_saving_creates_no_recording_tables_file_or_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(Store(root / 'database.sqlite3')) as store:
                store.save([ROW])
                store.save([dict(ROW, games=3500)])
            pscube = PscubeStore(root / 'pscube.sqlite3')
            try:
                with pscube.db:
                    pscube.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', ('k1', json.dumps(dict(store='c740601', rate='20', day='2026-10-24', machine='試験', rack=101, games=2000, bb=3, rb=2, my=500))))
            finally:
                pscube.close()
            for name in ('database.sqlite3', 'pscube.sqlite3'):
                with closing(sqlite3.connect(root / name)) as db:
                    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertFalse(tables & {'iv_control', 'iv_outbox', 'iv_heads'}, name)
            input_versions.hold(root / 'database.sqlite3')
            try:
                self.assertNotIn(input_versions._key(root / 'database.sqlite3'), input_versions._workers)
            finally:
                input_versions.release(root / 'database.sqlite3')
            input_versions.wait(root)
            self.assertFalse((root / input_versions.FILE_NAME).exists())
            self.assertEqual(input_versions.recording_status_lines(root), [])

    def test_leftover_recording_tables_are_not_sent_again(self):
        """記録していたころの本体（転送待ちが残っている）を開いても、検証DBを作り直さない。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(input_versions, 'RECORDING', True), patch.object(input_versions, '_schedule'):
                with closing(Store(root / 'database.sqlite3')) as store:
                    store.save([ROW])
            with closing(sqlite3.connect(root / 'database.sqlite3')) as db:
                self.assertGreater(db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0], 0)
            with closing(Store(root / 'database.sqlite3')) as store:
                store.save([dict(ROW, games=4000)])
            input_versions.hold(root / 'database.sqlite3')
            input_versions.release(root / 'database.sqlite3')
            self.assertFalse((root / input_versions.FILE_NAME).exists())
            self.assertEqual(input_versions.recording_status_lines(root), [])


class MeruhenVersionTests(RecordingOn, unittest.TestCase):
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


class PscubeVersionTests(RecordingOn, unittest.TestCase):
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
