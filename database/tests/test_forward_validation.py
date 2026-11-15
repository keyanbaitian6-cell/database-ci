"""取り込みが最後まで終わって窓が自分で閉じたときだけ、P-STATIONの前向き検証を自動で保存する（2026-11-09 利用者）。"""
import contextlib
import datetime as dt
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import forward_validation as fv  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
DONE_PSCUBE = 'すべて取り込みました（自動取り込みを停止しました）'
STOP_PSCUBE = '自動取り込みを止めました（通信エラー：HTTP 403）。サイトのページは閉じました。時間を空けてから、Cookieを消さずに取り込み窓を開き直してください'
DONE_SITE777 = '範囲の取り込みが完了しました。11/8、11/9'


def at(hh, mm=0, ss=0, day=10):
    return dt.datetime(2026, 11, day, hh, mm, ss, tzinfo=JST)


class Result:
    def __init__(self, code, out=''):
        self.returncode, self.stdout, self.stderr = code, out.encode('utf-8'), b''


class SyncThread:
    def __init__(self, target, name, daemon):
        self.target = target

    def start(self):
        self.target()


class ForwardValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.outputs = self.dir / 'outputs'
        self.v1 = self.outputs / 'pstation-forward-20261108'
        self.v2 = self.outputs / 'pstation-forward-20261110'
        self.v1.mkdir(parents=True)
        self.v2.mkdir(parents=True)
        self.python = Path(sys.executable)
        self.write_scripts(0, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def write_scripts(self, v1_code, v2_code):
        (self.v1 / 'forward.py').write_text(f"print('v1 保存しました')\nraise SystemExit({v1_code})\n", encoding='utf-8')
        (self.v2 / 'forward2.py').write_text(
            "import sys\nprint('当日の予測' if %d == 0 else '停止: 初回対象日（2026-11-10）より前です。', file=sys.stdout if %d == 0 else sys.stderr)\n"
            "raise SystemExit(%d)\n" % (v2_code, v2_code, v2_code), encoding='utf-8')

    def plan(self):
        return fv.steps(self.outputs, self.python)

    def test_time_window_is_jst_midnight_to_before_nine(self):
        self.assertFalse(fv.in_window(at(23, 59, 59, day=9)))
        self.assertTrue(fv.in_window(at(0)))
        self.assertTrue(fv.in_window(at(8, 59, 59)))
        self.assertFalse(fv.in_window(at(9)))
        # PCの地域設定ではなく日本時間で決める（UTCの23:59は日本時間の8:59）
        self.assertTrue(fv.in_window(dt.datetime(2026, 11, 9, 23, 59, tzinfo=dt.timezone.utc)))
        self.assertFalse(fv.in_window(dt.datetime(2026, 11, 10, 0, 0, tzinfo=dt.timezone.utc)))
        with self.assertRaises(ValueError):
            fv.in_window(dt.datetime(2026, 11, 10, 1))

    def test_only_finished_captures_count(self):
        self.assertTrue(fv.finished('サイトセブン', DONE_SITE777))
        self.assertFalse(fv.finished('サイトセブン', None))       # ×で閉じた・途中で止まった（知らせなし）
        self.assertTrue(fv.finished('P’s CUBE', DONE_PSCUBE))
        self.assertTrue(fv.finished('P’s CUBE', '11/8の分をすべて取り込みました（自動取り込みを停止しました）'))
        self.assertFalse(fv.finished('P’s CUBE', STOP_PSCUBE))   # 403などで止まって閉じた
        self.assertFalse(fv.finished('P’s CUBE', None))
        self.assertFalse(fv.finished('メルヘン', '取り込みました'))  # P-STATION以外の取り込みでは動かさない

    def test_steps_match_the_morning_cmd(self):
        plan = self.plan()
        self.assertEqual([name for name, _, _ in plan], ['v1', 'v2'])      # 書き出し先の設定が無ければ書き出さない
        (self.v1 / 'viewer-sync-dir.txt').write_text('X:\\drive', encoding='utf-8')
        plan = self.plan()
        self.assertEqual([name for name, _, _ in plan], ['v1', 'export', 'v2'])
        self.assertEqual(plan[0][1][-2:], [str(self.v1 / 'forward.py'), 'daily'])
        self.assertEqual(plan[2][1][-2:], [str(self.v2 / 'forward2.py'), 'morning'])
        self.assertIn('--out-dir-file', plan[1][1])
        self.assertTrue(all(args[:4] == [str(self.python), '-B', '-X', 'utf8'] for _, args, _ in plan))
        (self.v2 / 'forward2.py').unlink()
        self.assertIn('forward2.py', fv.steps(self.outputs, self.python))

    def test_decide_reasons(self):
        self.assertIsNone(fv.decide('サイトセブン', DONE_SITE777, at(0, 30), self.plan()))
        self.assertIn('最後まで', fv.decide('P’s CUBE', STOP_PSCUBE, at(7), self.plan()))
        self.assertIn('0時〜9時', fv.decide('サイトセブン', DONE_SITE777, at(23, 50, day=9), self.plan()))
        self.assertIn('ファイルがありません', fv.decide('サイトセブン', DONE_SITE777, at(7), fv.steps(self.dir / 'none', self.python)))

    def test_real_scripts_success_and_stop_and_log(self):
        done, text = fv.run(self.plan(), self.dir, now=at(7))
        self.assertTrue(done, text)
        self.assertEqual(text, '前向き検証を自動で保存しました')
        self.write_scripts(0, 2)
        done, text = fv.run(self.plan(), self.dir, now=at(7))
        self.assertFalse(done)
        self.assertIn('停止: 初回対象日（2026-11-10）より前です。', text)    # 日本語の出力が崩れない
        log = (self.dir / fv.LOG_NAME).read_text(encoding='utf-8')
        self.assertIn('v1 保存しました', log)
        self.assertIn('--- v2 終了コード 2', log)
        self.assertIn('forward.auto', (self.dir / 'errors.log').read_text(encoding='utf-8'))

    def test_v1_failure_skips_export_but_still_runs_v2(self):
        (self.v1 / 'viewer-sync-dir.txt').write_text('X:\\drive', encoding='utf-8')
        calls = []

        def runner(args, **kw):
            calls.append(args)
            self.assertIs(kw['stdin'], subprocess.DEVNULL)
            return Result(2 if args[-1] == 'daily' else 0, '停止: v1の例\n' if args[-1] == 'daily' else '')
        done, text = fv.run(self.plan(), self.dir, runner=runner, now=at(7))
        self.assertFalse(done)
        self.assertEqual([a[-1] for a in calls], ['daily', 'morning'])
        self.assertIn('停止: v1の例', text)

    def test_runner_failure_does_not_raise(self):
        def broken(args, **kw):
            raise subprocess.TimeoutExpired(args, 600)
        done, text = fv.run(self.plan(), self.dir, runner=broken, now=at(7))
        self.assertFalse(done)
        self.assertIn('v1=-1', text)

    def test_never_two_at_once(self):
        gate, inside = threading.Event(), threading.Event()

        def slow(args, **kw):
            inside.set()
            gate.wait(5)
            return Result(0)
        t = threading.Thread(target=fv.run, args=(self.plan(), self.dir), kwargs={'runner': slow, 'now': at(7)})
        t.start()
        inside.wait(5)
        done, text = fv.run(self.plan(), self.dir, runner=lambda a, **k: Result(0), now=at(7))
        gate.set()
        t.join(5)
        self.assertFalse(done)
        self.assertIn('すでに動いています', text)

    def test_start_runs_in_background_only_when_allowed(self):
        reports, calls = [], []

        def runner(args, **kw):
            calls.append(args)
            return Result(0)
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread, runner=runner)
        self.assertIsNone(fv.start('サイトセブン', DONE_SITE777, self.dir, reports.append, now=at(0, 40), **kw))
        self.assertEqual(reports, ['前向き検証を自動で保存しました'])
        self.assertEqual(len(calls), 2)
        for label, message, now in [('サイトセブン', None, at(7)), ('P’s CUBE', STOP_PSCUBE, at(7)),
                                    ('P’s CUBE', DONE_PSCUBE, at(9)), ('サイトセブン', DONE_SITE777, at(23, day=9))]:
            self.assertIsNotNone(fv.start(label, message, self.dir, reports.append, now=now, **kw))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(reports), 1)

    def test_default_paths_are_outside_the_repository(self):
        self.assertEqual(fv.outputs_dir().name, 'outputs')
        self.assertEqual(fv.outputs_dir().parent, Path(fv.__file__).resolve().parents[2])

    def test_app_wires_both_capture_windows(self):
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        self.assertIn("after_auto=lambda message: save_forward_after('サイトセブン', message)", source)
        self.assertIn("after_auto=lambda message: after_pscube(message, since)", source)
        self.assertIn("save_forward_after('P’s CUBE', message)\n        sleep_after_pscube(message, since)", source)

    def test_app_shows_the_meruhen_note_when_the_meruhen_window_closes(self):
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        self.assertIn("watch_capture_window(process, 'メルヘン', meruhen_message, after_close=meruhen_forward_note)", source)
        self.assertIn('note = forward_validation.meruhen_note(DATA_DIR, since)', source)
        self.assertIn('if after_close is not None:\n                after_close()', source)


class MeruhenNoteTest(unittest.TestCase):
    """メルヘンの取り込み窓が閉じたら、店舗別の候補比較の記録の様子を1行出す（2026-11-16 利用者「メルヘンも出すようにして」）。"""

    def setUp(self):
        import sqlite3
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        with contextlib.closing(sqlite3.connect(self.dir / 'database.sqlite3')) as db, db:
            db.execute('CREATE TABLE days (store TEXT, day TEXT, machine TEXT, rack INTEGER, payload TEXT, PRIMARY KEY(store,day,machine,rack))')
            db.execute('CREATE TABLE iv_outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, day TEXT, saved_at TEXT NOT NULL, confirmed_at TEXT, kind TEXT NOT NULL, content TEXT)')
            for store, rack in (('nagamachiminami', 1), ('nagamachiminami', 2), ('saiwaichou', 7)):
                db.execute("INSERT INTO days VALUES(?, '2026-11-15', 'A', ?, '{}')", (store, rack))
        with contextlib.closing(sqlite3.connect(self.dir / 'input_versions.sqlite3')) as db, db:
            db.execute('CREATE TABLE versions (id INTEGER PRIMARY KEY, source TEXT NOT NULL, key TEXT NOT NULL, day TEXT, saved_at TEXT NOT NULL, kind TEXT NOT NULL, content TEXT)')

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, table, store, rack, saved, source='meruhen'):
        import sqlite3
        key = f'{store}\t2026-11-15\tA\t{rack}'
        with contextlib.closing(sqlite3.connect(self.dir / table[0])) as db, db:
            if table[1] == 'versions':
                db.execute("INSERT INTO versions(source,key,day,saved_at,kind) VALUES(?,?,'2026-11-15',?,'write')", (source, key, saved))
            else:
                db.execute("INSERT INTO iv_outbox(key,day,saved_at,kind) VALUES(?,'2026-11-15',?,'write')", (key, saved))

    LOG, OUTBOX = ('input_versions.sqlite3', 'versions'), ('database.sqlite3', 'iv_outbox')

    def test_counts_racks_recorded_before_the_8am_cutoff_from_the_log_and_the_pending_rows(self):
        self.put(self.LOG, 'nagamachiminami', 1, '2026-11-15T23:36:30.874548+09:00')
        self.put(self.LOG, 'nagamachiminami', 1, '2026-11-16T00:01:00.000000+09:00')   # 同じ台の2回目は1台
        self.put(self.OUTBOX, 'nagamachiminami', 2, '2026-11-15T23:40:00.000000+09:00')  # まだ転送前の行も数える
        self.put(self.LOG, 'saiwaichou', 7, '2026-11-15T23:50:00.000000+09:00')
        self.put(self.LOG, 'saiwaichou', 7, '2026-11-15T23:50:00.000000+09:00', source='pscube')  # P’s CUBEの記録は見ない
        note = fv.meruhen_note(self.dir, '2026-11-15T23:30:00+09:00', at(0, 30, day=16))
        self.assertEqual(note, '前向き検証（メルヘン・店舗別の候補比較）：11/15分：長町南 2/2台・幸町 1/1台（締切（11/16 8:00）より前に記録）')

    def test_after_the_cutoff_only_racks_recorded_in_time_count(self):
        self.put(self.LOG, 'nagamachiminami', 1, '2026-11-16T07:59:59.000000+09:00')
        self.put(self.LOG, 'nagamachiminami', 2, '2026-11-16T08:00:00.000000+09:00')
        note = fv.meruhen_note(self.dir, '2026-11-16T07:00:00+09:00', at(8, 5, day=16))
        self.assertEqual(note, '前向き検証（メルヘン・店舗別の候補比較）：11/15分：長町南 1/2台・幸町 0/1台（締切（11/16 8:00）までに記録した台だけが比較に入ります）')

    def test_nothing_recorded_while_the_window_was_open_shows_nothing(self):
        self.put(self.LOG, 'nagamachiminami', 1, '2026-11-15T23:36:30+09:00')
        self.assertIsNone(fv.meruhen_note(self.dir, '2026-11-16T01:00:00+09:00', at(1, 5, day=16)))

    def test_missing_files_show_nothing(self):
        self.assertIsNone(fv.meruhen_note(self.dir / 'none', '2026-11-16T01:00:00+09:00', at(1, 5, day=16)))


if __name__ == '__main__':
    unittest.main()
