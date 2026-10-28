"""検証先の障害・途中取消・確定時刻を本体の保存から切り離す。"""
from contextlib import closing
import gc
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import input_versions as iv
from core import Store
from test_input_versions import KEY, ROW


def setUpModule():
    # 転送を別スレッドで動かす試験。前の試験のTkはメインスレッドで先に片付ける（test_input_versions.setUpModule と同じ理由）。
    gc.collect()


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.patch=patch.object(iv,'_schedule');self.patch.start();self.addCleanup(self.patch.stop)
        self.store=Store(self.root/'db.sqlite3');self.addCleanup(self.store.close)
    def rows(self):return self.store.db.execute('SELECT * FROM iv_outbox ORDER BY id').fetchall()
    def test_target_lock_never_blocks_save_and_pending_survives(self):
        iv.flush(self.store.path)
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            self.store.save([ROW])
            self.assertEqual(len(self.store.rows()),1)
            with self.assertRaises(sqlite3.OperationalError):iv.flush(self.store.path)
            self.assertTrue(self.rows())
        iv.flush(self.store.path);self.assertEqual(self.rows(),[])
    def test_commit_between_transfer_batches_keeps_confirmation_and_reconstruction(self):
        from datetime import datetime, timedelta
        iv.flush(self.store.path)
        self.store.save([ROW])
        original = iv._receipt_digest
        inserted = False
        def commit_during_transfer(text):
            nonlocal inserted
            if not inserted:
                inserted = True
                newer = dict(ROW, rack=ROW['rack']+1, games=4300)
                self.store.db.execute('INSERT INTO days VALUES(?,?,?,?,?)',
                    (newer['store'], newer['day'], newer['machine'], newer['rack'], json.dumps(newer)))
                # 保存側のcommit直後、確定時刻を補う処理より先に転送側が進む。
                sqlite3.Connection.commit(self.store.db)
            return original(text)
        with patch.object(iv, '_receipt_digest', side_effect=commit_during_transfer):
            iv.flush(self.store.path)
        self.store.db._confirmed()
        iv.flush(self.store.path)
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM iv_receipts WHERE confirmed_at IS NULL').fetchone()[0], 0)
        self.assertEqual(self.rows(), [])
        values=iv.as_of(self.root/iv.FILE_NAME, 'meruhen', datetime.now().astimezone()+timedelta(seconds=1))
        self.assertEqual(sorted(r['games'] for r in values.values()), [ROW['games'], 4300])

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
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db:
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
            with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0],0)
            with closing(sqlite3.connect(Path(directory)/iv.FILE_NAME)) as db:self.assertEqual(db.execute("SELECT count(*) FROM versions WHERE kind='write'").fetchone()[0],1)
    def test_resume_rebases_current_state_without_filling_the_gap(self):
        from datetime import datetime,timedelta
        self.store.save([ROW]);iv.flush(self.store.path)
        with self.store.db:self.store.db.execute('UPDATE iv_control SET paused_at=?',('2026-10-25T00:00:00+09:00',))
        self.store.save([dict(ROW,games=4500)])
        self.store.close()
        iv.resume_recording(self.store.path)
        values=iv.as_of(self.root/iv.FILE_NAME,'meruhen',datetime.now().astimezone()+timedelta(seconds=1))
        self.assertEqual(next(iter(values.values()))['games'],4500)
    def test_receipts_keep_a_hash_not_a_second_copy_of_the_content(self):
        self.store.save([dict(ROW,memo='x'*2000)]);iv.flush(self.store.path)
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db:
            self.assertEqual({r[0] for r in db.execute('SELECT length(digest) FROM iv_receipts')},{64})
    def test_receipts_written_as_full_text_still_match_a_resend(self):
        # 2026-10-26の初版は受領に内容の写しを残した。実DBにその形の受領と未削除の待ち行がある。
        self.store.save([ROW]);pending=self.rows();iv.flush(self.store.path)
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db, db:
            for seq,key,day,at,confirmed,kind,value in pending:
                db.execute('UPDATE iv_receipts SET digest=? WHERE seq=?',(json.dumps(['meruhen',key,day,at,confirmed,kind,value],ensure_ascii=False),seq))
        with self.store.db:self.store.db.executemany('INSERT INTO iv_outbox VALUES(?,?,?,?,?,?,?)',pending)
        iv.flush(self.store.path)
        self.assertEqual(self.rows(),[])
    def test_received_but_not_yet_removed_rows_are_not_reported_as_unsent(self):
        from datetime import datetime,timedelta
        self.store.save([ROW]);pending=self.rows();iv.flush(self.store.path)
        # 検証先の確定後、本体から消す前に止まった状態。
        with self.store.db:self.store.db.executemany('INSERT INTO iv_outbox VALUES(?,?,?,?,?,?,?)',pending)
        (self.root/'Thumbs.db').write_bytes(b'not a database')
        cutoff=datetime.now().astimezone()+timedelta(seconds=1)
        self.assertEqual(next(iter(iv.as_of(self.root/iv.FILE_NAME,'meruhen',cutoff).values()))['games'],ROW['games'])
        self.store.save([dict(ROW,games=4100)])
        with self.assertRaisesRegex(ValueError,'未転送'):
            iv.as_of(self.root/iv.FILE_NAME,'meruhen',datetime.now().astimezone()+timedelta(seconds=1))

    def test_database_copy_in_the_same_folder_is_not_a_second_recording(self):
        # fix_anaslo_saved.py --apply は data に database.pre-anaslo-fix-*.sqlite3 を複製する。控えは本体と同じ識別子を持つ。
        from datetime import datetime,timedelta
        self.store.save([ROW]);iv.flush(self.store.path)
        with closing(sqlite3.connect(self.root/'db.pre-anaslo-fix-20261026-180000.sqlite3')) as copy:self.store.db.backup(copy)
        self.store.save([dict(ROW,games=4100)]);self.store.save([dict(ROW,games=4200)])
        lines=iv.recording_status_lines(self.root)
        self.assertEqual(lines,['長町南・幸町の検証記録：転送待ち2件'])
        iv.flush(self.store.path)
        self.assertEqual(iv.recording_status_lines(self.root),['長町南・幸町の検証記録：転送待ち0件'])
        values=iv.as_of(self.root/iv.FILE_NAME,'meruhen',datetime.now().astimezone()+timedelta(seconds=1))
        self.assertEqual(next(iter(values.values()))['games'],4200)

class CompletenessTests(unittest.TestCase):
    """2026-10-29：as_of() が検証DB単体のコピーや、途中の受領・版が欠けた履歴を完全な入力として返していた。"""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.patch=patch.object(iv,'_schedule');self.patch.start();self.addCleanup(self.patch.stop)
        self.store=Store(self.root/'db.sqlite3');self.addCleanup(self.store.close)
        for rack in (537,538,539):self.store.save([dict(ROW,rack=rack)])
        iv.flush(self.store.path)
    def cutoff(self):
        from datetime import datetime,timedelta
        return datetime.now().astimezone()+timedelta(seconds=1)
    def racks(self,path=None):
        return sorted(r['rack'] for r in iv.as_of(path or self.root/iv.FILE_NAME,'meruhen',self.cutoff()).values())
    def middle(self):
        # 途中（2番目）の書き込みの受領番号と版の番号。最終番号の受領は残る。
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db:
            return db.execute("SELECT r.seq,r.version_id FROM iv_receipts r JOIN versions v ON v.id=r.version_id WHERE v.kind='write' ORDER BY r.seq LIMIT 1 OFFSET 1").fetchone()
    def test_complete_history_is_returned(self):
        self.assertEqual(self.racks(),[537,538,539])
    def test_verification_copy_without_its_main_database_is_not_complete(self):
        # 本体には未転送の変更がある。検証DBだけを別フォルダーへ写すと、それを照合できない。
        import shutil
        self.store.save([dict(ROW,rack=537,games=3500)])
        with tempfile.TemporaryDirectory() as other:
            shutil.copy(self.root/iv.FILE_NAME,Path(other)/iv.FILE_NAME)
            with self.assertRaisesRegex(ValueError,'本体DBが無く'):self.racks(Path(other)/iv.FILE_NAME)
        with self.assertRaisesRegex(ValueError,'未転送'):self.racks()
    def test_main_database_of_another_source_does_not_count(self):
        with self.assertRaisesRegex(ValueError,'本体DBが無く'):iv.as_of(self.root/iv.FILE_NAME,'pscube',self.cutoff())
    def test_missing_middle_receipt_and_version_is_detected(self):
        seq,version=self.middle()
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db,db:
            db.execute('DELETE FROM versions WHERE id=?',(version,));db.execute('DELETE FROM iv_receipts WHERE seq=?',(seq,))
        with self.assertRaisesRegex(ValueError,'途中の受領'):self.racks()
    def test_missing_version_row_with_its_receipt_left_is_detected(self):
        _seq,version=self.middle()
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db,db:db.execute('DELETE FROM versions WHERE id=?',(version,))
        with self.assertRaisesRegex(ValueError,'版が失われ'):self.racks()
    def test_missing_first_receipts_are_detected(self):
        # 基準点（reset）から先頭の受領がまとめて欠けた場合も、残りの番号は続いているので個数だけでは分からない。
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db,db:
            first=db.execute('SELECT min(seq) FROM iv_receipts').fetchone()[0]
            db.execute('DELETE FROM versions WHERE id IN (SELECT version_id FROM iv_receipts WHERE seq=?)',(first,))
            db.execute('DELETE FROM iv_receipts WHERE seq=?',(first,))
        with self.assertRaisesRegex(ValueError,'途中の受領'):self.racks()
    def test_version_not_traceable_to_the_main_database_is_detected(self):
        # 受領の無い版（旧形式の直接追記と同じ形）が基準点より後に混ざっている。
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db,db:
            db.execute("INSERT INTO versions(source,key,day,saved_at,kind,content) VALUES('meruhen','x','2026-10-14','2026-10-26T00:00:00+09:00','write','{\"rack\":1}')")
        with self.assertRaisesRegex(ValueError,'照合できない'):self.racks()
    def test_old_direct_rows_before_the_baseline_are_still_accepted(self):
        # 2026-10-25〜26の初版は受領なしで直接追記した。その後の基準点（reset）より前にだけあり、結果に入らない。
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with closing(sqlite3.connect(root/iv.FILE_NAME)) as db,db:
                db.execute('CREATE TABLE versions (id INTEGER PRIMARY KEY, source TEXT NOT NULL,key TEXT NOT NULL,day TEXT,saved_at TEXT NOT NULL,kind TEXT NOT NULL,content TEXT)')
                db.execute("INSERT INTO versions(source,key,day,saved_at,kind,content) VALUES('meruhen','old','2026-10-14','2026-10-25T20:31:51+09:00','baseline','{\"rack\":1}')")
            with closing(Store(root/'db.sqlite3')) as store:
                store.save([ROW]);iv.flush(store.path)
                self.assertEqual(sorted(iv.as_of(root/iv.FILE_NAME,'meruhen',self.cutoff())),[KEY])
    def test_cutoff_before_any_baseline_is_not_complete(self):
        with self.assertRaisesRegex(ValueError,'基準点が無く'):
            iv.as_of(self.root/iv.FILE_NAME,'meruhen','2026-10-01T08:00:00+09:00')


class HeldTransferTests(unittest.TestCase):
    """PC版は操作ごとに接続を閉じる。起動中は閉じた後も送り切る（2026-10-26、実DBで基準点5.7万件が残った）。"""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'db.sqlite3'
        with patch.object(iv,'_schedule'):
            with closing(Store(self.path,recording=False)) as store:
                with store.db:
                    store.db.executemany('INSERT INTO days VALUES(?,?,?,?,?)',[(ROW['store'],ROW['day'],ROW['machine'],rack,json.dumps(dict(ROW,rack=rack))) for rack in range(3*iv.BATCH)])
            # 記録の開始（全件基準点）と保存。ここでは送らずに閉じる。
            store=Store(self.path);store.save([dict(ROW,rack=1,games=4000)]);store.close()
    def pending(self):
        with closing(sqlite3.connect(self.path)) as db:return db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0]
    def until_sent(self,seconds=15):
        import time
        deadline=time.monotonic()+seconds
        while self.pending() and time.monotonic()<deadline:time.sleep(.05)
        return self.pending()
    def test_held_path_sends_what_closed_connections_left_without_another_save(self):
        self.assertGreater(self.pending(),3*iv.BATCH)
        iv.hold(self.path);self.addCleanup(iv.release,self.path)
        self.assertEqual(self.until_sent(),0)
        # 閉じた接続の後の保存も、保持している間は次の操作を待たずに送る。
        store=Store(self.path);store.save([dict(ROW,rack=2,games=4200)]);store.close()
        self.assertEqual(self.until_sent(),0)
        with closing(sqlite3.connect(self.root/iv.FILE_NAME)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM versions WHERE kind='write'").fetchone()[0],2)
    def test_busy_main_database_is_retried_instead_of_waiting_for_the_next_save(self):
        real=iv.flush;calls=[]
        def busy_once(path,**options):
            calls.append(path)
            if len(calls)==1:raise sqlite3.OperationalError('database is locked')
            return real(path,**options)
        with patch.object(iv,'RETRY_SECONDS',.05),patch.object(iv,'flush',side_effect=busy_once):
            iv.hold(self.path)
            try:self.assertEqual(self.until_sent(),0)
            finally:iv.release(self.path)
        self.assertGreaterEqual(len(calls),2)
        self.assertNotIn(iv._key(self.path),iv.state())
    def test_release_stops_the_transfer_and_lets_go_of_the_files(self):
        iv.hold(self.path);iv.release(self.path)
        self.assertNotIn(iv._key(self.path),iv._workers)
        # Windowsでも消せる（転送が接続を持ったままにならない）。
        (self.root/iv.FILE_NAME).unlink(missing_ok=True);self.path.unlink()


class LargeHistoryTests(unittest.TestCase):
    def test_as_of_reads_receipts_once_instead_of_per_version(self):
        # 受領と版をSQLで結合すると、版1件ごとに受領を全件読む（2026-10-26、実データの版16.7万件で終わらなかった）。
        import time
        from datetime import datetime,timedelta
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/iv.FILE_NAME;count=30000;at='2026-10-26T12:00:00+09:00'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE versions (id INTEGER PRIMARY KEY, source TEXT NOT NULL,key TEXT NOT NULL,day TEXT,saved_at TEXT NOT NULL,kind TEXT NOT NULL,content TEXT)')
                db.execute('CREATE TABLE iv_receipts (identity TEXT, seq INTEGER, digest TEXT NOT NULL, confirmed_at TEXT, version_id INTEGER, PRIMARY KEY(identity,seq))')
                # 2026-10-25の初版が作った索引。実データにあり、これがあると結合が受領の全件読みになる。
                db.execute('CREATE INDEX versions_key ON versions(source, key, id)')
                db.execute('CREATE INDEX versions_day ON versions(source, day)')
                # 実データと同じく、識別子の最初の番号は基準点（reset）。
                db.execute("INSERT INTO versions VALUES(1,'meruhen','',NULL,?,'reset',NULL)",(at,))
                db.executemany('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',[(i,'meruhen',f'k{i}','2026-10-26',at,'baseline','{"games":1}') for i in range(2,count+2)])
                db.executemany('INSERT INTO iv_receipts VALUES(?,?,?,?,?)',[('a',i,'0'*64,at,i) for i in range(1,count+2)])
            # 照合する本体（転送済みで待ち行なし）。
            with closing(sqlite3.connect(Path(directory)/'db.sqlite3')) as db,db:
                db.execute('CREATE TABLE iv_control (singleton INTEGER PRIMARY KEY, identity TEXT NOT NULL, source TEXT NOT NULL, paused_at TEXT, pending_bytes INTEGER NOT NULL DEFAULT 0, delivered_seq INTEGER NOT NULL DEFAULT 0)')
                db.execute('CREATE TABLE iv_outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, day TEXT, saved_at TEXT NOT NULL, confirmed_at TEXT, kind TEXT NOT NULL, content TEXT)')
                db.execute("INSERT INTO iv_control VALUES(1,'a','meruhen',NULL,0,?)",(count+1,))
                db.execute("INSERT INTO sqlite_sequence VALUES('iv_outbox',?)",(count+1,))
            started=time.monotonic()
            values=iv.as_of(path,'meruhen',datetime.fromisoformat(at)+timedelta(seconds=1))
            self.assertEqual(len(values),count)
            self.assertLess(time.monotonic()-started,5)


class LeftoverTkTests(unittest.TestCase):
    def test_module_setup_collects_leftover_tk_on_the_main_thread(self):
        import threading,tkinter as tk,weakref
        import test_input_versions
        enabled=gc.isenabled();gc.disable()
        try:
            gc.collect();freed=[]
            try:root=tk.Tk()
            except tk.TclError as error:self.skipTest(f'画面が無い環境：{error}')
            root.withdraw();root.destroy()
            root.cycle=root  # 循環参照：GCでしか片付かない
            weakref.finalize(root,lambda:freed.append(threading.current_thread().name))
            del root
            self.assertEqual(freed,[])
            test_input_versions.setUpModule();self.assertEqual(freed,[threading.main_thread().name])
            # この試験モジュールも、始める前に同じように片付ける。
            self.assertIn('gc',setUpModule.__code__.co_names)
        finally:
            if enabled:gc.enable()


class ThreadOnlyWhileHeldTests(unittest.TestCase):
    def test_saving_without_a_hold_never_starts_a_thread(self):
        # 試験・スクリプトなど保持していないプロセスでは転送のスレッドを起こさない（CI 40293353918 の再発防止）。
        import threading
        before={t.ident for t in threading.enumerate()}
        with tempfile.TemporaryDirectory() as directory:
            with closing(Store(Path(directory)/'db.sqlite3')) as store:
                store.save([ROW]);store.save([dict(ROW,games=4100)])
                started=[t.name for t in threading.enumerate() if t.ident not in before]
                self.assertEqual(started,[])
                self.assertGreater(store.db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0],0)
            iv.wait(directory)  # 診断・試験用の明示的な転送
            with closing(sqlite3.connect(Path(directory)/'db.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0],0)
    def test_held_path_sends_saves_from_another_process_on_the_next_check(self):
        import os,subprocess,sys,time
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'data.sqlite3'
            with closing(Store(path)) as store:store.save([ROW])
            with patch.object(iv,'POLL_SECONDS',.1):
                iv.hold(path)
                try:
                    code="from pathlib import Path;from core import Store;import json,sys\ns=Store(Path(sys.argv[1]));s.save([json.loads(sys.argv[2])]);s.close()"
                    subprocess.run([sys.executable,'-c',code,str(path),json.dumps(dict(ROW,games=4300))],env={**os.environ,'PYTHONPATH':str(Path(iv.__file__).parent)},check=True)
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        with closing(sqlite3.connect(path)) as db:
                            if not db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0]:break
                        time.sleep(.05)
                finally:iv.release(path)
            with closing(sqlite3.connect(Path(directory)/iv.FILE_NAME)) as db:
                self.assertIn('4300',db.execute("SELECT content FROM versions WHERE kind='write' ORDER BY id DESC LIMIT 1").fetchone()[0])
