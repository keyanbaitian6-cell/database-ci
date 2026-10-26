"""検証先の障害・途中取消・確定時刻を本体の保存から切り離す。"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import input_versions as iv
from core import Store
from test_input_versions import ROW

class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.patch=patch.object(iv,'_schedule');self.patch.start();self.addCleanup(self.patch.stop)
        self.store=Store(self.root/'db.sqlite3');self.addCleanup(self.store.close)
    def rows(self):return self.store.db.execute('SELECT * FROM iv_outbox ORDER BY id').fetchall()
    def test_target_lock_never_blocks_save_and_pending_survives(self):
        iv.flush(self.store.path)
        with sqlite3.connect(self.root/iv.FILE_NAME) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            self.store.save([ROW])
            self.assertEqual(len(self.store.rows()),1)
            with self.assertRaises(sqlite3.OperationalError):iv.flush(self.store.path)
            self.assertTrue(self.rows())
        iv.flush(self.store.path);self.assertEqual(self.rows(),[])
    def test_rollback_removes_pending_and_numeric_change(self):
        before=self.rows()
        with self.assertRaises(RuntimeError):
            with self.store.db:
                self.store.db.execute('INSERT INTO days VALUES(?,?,?,?,?)',(ROW['store'],ROW['day'],ROW['machine'],ROW['rack'],json.dumps(ROW)))
                raise RuntimeError('取消')
        self.assertEqual(self.rows(),before);self.assertEqual(self.store.rows(),[])
    def test_retry_after_target_commit_does_not_duplicate(self):
        self.store.save([ROW]);pending=self.rows();iv.flush(self.store.path)
        with self.store.db:
            self.store.db.executemany('INSERT INTO iv_outbox VALUES(?,?,?,?,?,?,?)',pending)
        iv.flush(self.store.path)
        with sqlite3.connect(self.root/iv.FILE_NAME) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM versions WHERE key<>''").fetchone()[0],1)
    def test_conflicting_same_sequence_does_not_replace_history(self):
        self.store.save([ROW]);pending=self.rows();iv.flush(self.store.path)
        row=list(pending[-1]);row[-1]='{"games":999}'
        with self.store.db:self.store.db.execute('INSERT INTO iv_outbox VALUES(?,?,?,?,?,?,?)',row)
        with self.assertRaises(ValueError):iv.flush(self.store.path)
        self.assertTrue(self.rows())
    def test_transaction_crossing_cutoff_is_not_used_as_pre_cutoff(self):
        clock=['2026-10-26T01:59:59+09:00']
        with patch.object(iv,'_now',side_effect=lambda:clock[0]):
            # UDFは呼び出し時にモジュールの時刻を参照する。
            self.store.db.create_function('iv_now',0,lambda:iv._now())
            with self.store.db:
                self.store.db.execute('INSERT INTO days VALUES(?,?,?,?,?)',(ROW['store'],ROW['day'],ROW['machine'],ROW['rack'],json.dumps(ROW)))
                clock[0]='2026-10-26T02:00:02+09:00'
        iv.flush(self.store.path)
        with self.assertRaisesRegex(ValueError,'保存確定'):
            iv.as_of(self.root/iv.FILE_NAME,'meruhen','2026-10-26T02:00:00+09:00')
    def test_output_copy_never_creates_recording_tables(self):
        with tempfile.TemporaryDirectory() as other:
            store=Store(Path(other)/'copy.db',recording=False)
            try:
                store.save([ROW])
                self.assertIsNone(store.db.execute("SELECT name FROM sqlite_master WHERE name='iv_outbox'").fetchone())
            finally:store.close()
    def test_missing_confirmed_target_is_not_recreated_as_complete(self):
        self.store.save([ROW]);iv.flush(self.store.path)
        (self.root/iv.FILE_NAME).unlink()
        self.store.save([dict(ROW,games=4000)])
        with self.assertRaisesRegex(ValueError,'確定済み'):iv.flush(self.store.path)
        self.assertEqual(self.store.rows()[0]['games'],4000)
        self.assertTrue(self.store.db.execute('SELECT paused_at FROM iv_control').fetchone()[0])
    def test_renaming_key_removes_old_key_from_reconstruction(self):
        self.store.save([ROW])
        with self.store.db:
            self.store.db.execute('UPDATE days SET machine=?,payload=?',('変更後',json.dumps(dict(ROW,machine='変更後'))))
        iv.flush(self.store.path)
        from datetime import datetime,timedelta
        values=iv.as_of(self.root/iv.FILE_NAME,'meruhen',datetime.now().astimezone()+timedelta(seconds=1))
        self.assertEqual([r['machine'] for r in values.values()],['変更後'])
    def test_capacity_pause_keeps_business_saves_and_existing_pending(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(iv,'MAX_PENDING_BYTES',1):
            store=Store(Path(directory)/'data.sqlite3')
            try:
                store.save([dict(ROW,rack=i) for i in range(5)])
                self.assertEqual(len(store.rows()),5)
                self.assertTrue(store.db.execute('SELECT paused_at FROM iv_control').fetchone()[0])
                self.assertGreater(store.db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0],0)
            finally:store.close()
    def test_process_exit_after_commit_keeps_transferable_pending(self):
        import os,subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            code="from unittest.mock import patch;from pathlib import Path;from core import Store;import input_versions as iv,json,sys,os\nwith patch.object(iv,'_schedule'):\n s=Store(Path(sys.argv[1])/'data.sqlite3');s.save([json.loads(sys.argv[2])]);os._exit(0)"
            subprocess.run([sys.executable,'-c',code,directory,json.dumps(ROW)],env={**os.environ,'PYTHONPATH':str(Path(iv.__file__).parent)},check=True)
            path=Path(directory)/'data.sqlite3'
            iv.flush(path)
            with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0],0)
            with sqlite3.connect(Path(directory)/iv.FILE_NAME) as db:self.assertEqual(db.execute("SELECT count(*) FROM versions WHERE kind='write'").fetchone()[0],1)
    def test_resume_rebases_current_state_without_filling_the_gap(self):
        from datetime import datetime,timedelta
        self.store.save([ROW]);iv.flush(self.store.path)
        with self.store.db:self.store.db.execute('UPDATE iv_control SET paused_at=?',('2026-10-25T00:00:00+09:00',))
        self.store.save([dict(ROW,games=4500)])
        self.store.close()
        iv.resume_recording(self.store.path)
        values=iv.as_of(self.root/iv.FILE_NAME,'meruhen',datetime.now().astimezone()+timedelta(seconds=1))
        self.assertEqual(next(iter(values.values()))['games'],4500)
