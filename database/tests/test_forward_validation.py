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
        self.assertIn("save_forward_after('P’s CUBE', message)\n        check_after_pscube(message, since)", source)
        self.assertIn('why = forward_validation.start_pending(DATA_DIR, results.append)', source)
        self.assertIn('check_pending_forward()\n        root.after(300_000, daily_tick)', source)

    def test_evening_completion_at_2345_leaves_mark_and_runs_once_at_0005_not_0010(self):
        reports, calls = [], []

        def runner(args, **kw):
            calls.append(args)
            return Result(0, 'v1 保存しました\n')
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread, runner=runner)
        # 11/9 23:45 に自分で閉じて完了 → その場では流れず、印が残る
        why = fv.start('サイトセブン', DONE_SITE777, self.dir, reports.append, now=at(23, 45, day=9), **kw)
        self.assertIsNotNone(why)
        self.assertIn('0時〜9時', why)
        self.assertEqual(calls, [])
        self.assertEqual(reports, [])
        state_path = self.dir / fv.STATE_NAME
        self.assertTrue(state_path.is_file())
        self.assertEqual(fv._read_state(self.dir).get('pending_target'), '2026-11-10')
        # 11/10 0:05 の確認で1回流れる
        self.assertIsNone(fv.start_pending(self.dir, reports.append, now=at(0, 5, day=10), **kw))
        self.assertEqual(len(calls), 2)
        self.assertEqual(reports, ['前向き検証を自動で保存しました'])
        self.assertEqual(fv._read_state(self.dir).get('done_target'), '2026-11-10')
        self.assertTrue((self.dir / fv.LOG_NAME).is_file())
        self.assertIn('forward.auto', (self.dir / 'errors.log').read_text(encoding='utf-8'))
        # 11/10 0:10 の確認では流れない
        why_again = fv.start_pending(self.dir, reports.append, now=at(0, 10, day=10), **kw)
        self.assertIsNotNone(why_again)
        self.assertIn('すでに自動保存済み', why_again)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(reports), 1)

    def test_closed_with_x_at_2345_does_not_leave_mark_or_run(self):
        reports, calls = [], []
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread,
                  runner=lambda args, **k: (calls.append(args), Result(0))[1])
        # 23:45 に×で閉じた（message=None）または403停止 → 印は残らず、0:05 でも流れない
        self.assertIsNotNone(fv.start('サイトセブン', None, self.dir, reports.append, now=at(23, 45, day=9), **kw))
        self.assertIsNotNone(fv.start('P’s CUBE', STOP_PSCUBE, self.dir, reports.append, now=at(23, 50, day=9), **kw))
        self.assertFalse((self.dir / fv.STATE_NAME).exists())
        self.assertIsNotNone(fv.start_pending(self.dir, reports.append, now=at(0, 5, day=10), **kw))
        self.assertEqual(calls, [])
        self.assertEqual(reports, [])

    def test_pending_mark_does_not_run_at_or_after_9am_or_on_later_days(self):
        reports, calls = [], []
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread,
                  runner=lambda args, **k: (calls.append(args), Result(0))[1])
        fv.start('サイトセブン', DONE_SITE777, self.dir, reports.append, now=at(23, 45, day=9), **kw)
        # 印のある日の 9:00 以降 → 流れない
        self.assertIsNotNone(fv.start_pending(self.dir, reports.append, now=at(9, 0, day=10), **kw))
        self.assertIsNotNone(fv.start_pending(self.dir, reports.append, now=at(12, 30, day=10), **kw))
        # 翌日（11/11）の 0:05 になっても、11/10 用の古い印では流れない
        self.assertIsNotNone(fv.start_pending(self.dir, reports.append, now=at(0, 5, day=11), **kw))
        self.assertEqual(calls, [])
        self.assertEqual(reports, [])

    def test_after_app_restart_with_only_state_file_on_disk_runs_in_morning_window(self):
        # アプリを起動し直したあと（印のファイルだけがディスクにある状態） → 0〜9時なら流れる
        (self.dir / fv.STATE_NAME).write_text(
            '{"pending_target": "2026-11-10", "pending_label": "サイトセブン", "pending_at": "2026-11-09T23:45:00+09:00"}\n',
            encoding='utf-8')
        reports, calls = [], []
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread,
                  runner=lambda args, **k: (calls.append(args), Result(0))[1])
        self.assertIsNone(fv.start_pending(self.dir, reports.append, now=at(7, 15, day=10), **kw))
        self.assertEqual(len(calls), 2)
        self.assertEqual(reports, ['前向き検証を自動で保存しました'])

    def test_auto_close_at_0030_does_not_run_twice(self):
        reports, calls = [], []
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread,
                  runner=lambda args, **k: (calls.append(args), Result(0))[1])
        # ① 前夜23:45に印があっても、0:30 に取り込み完了の経路（start）で成功すれば、0:35 の印の確認（start_pending）では流れない
        fv.start('サイトセブン', DONE_SITE777, self.dir, reports.append, now=at(23, 45, day=9), **kw)
        self.assertEqual(calls, [])
        self.assertIsNone(fv.start('サイトセブン', DONE_SITE777, self.dir, reports.append, now=at(0, 30, day=10), **kw))
        self.assertEqual(len(calls), 2)
        why_pending = fv.start_pending(self.dir, reports.append, now=at(0, 35, day=10), **kw)
        self.assertIsNotNone(why_pending)
        self.assertIn('すでに自動保存済み', why_pending)
        self.assertEqual(len(calls), 2)
        # ② 取り込み完了の経路（start、0:00〜8:59に窓が自分で閉じたとき）は印や成功記録があっても止めず、毎回流す
        self.assertIsNone(fv.start('P’s CUBE', DONE_PSCUBE, self.dir, reports.append, now=at(0, 40, day=10), **kw))
        self.assertEqual(len(calls), 4)

    def test_failed_pending_run_at_0005_does_not_repeat_at_0010_and_still_runs_on_0700_capture(self):
        reports, calls = [], []
        code = [2]

        def runner(args, **kw):
            calls.append(args)
            return Result(code[0], '停止: 前日データ不足\n' if code[0] else 'v1 保存しました\n')
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread, runner=runner)
        # 前夜23:45に完了 → 印が残る
        fv.start('サイトセブン', DONE_SITE777, self.dir, reports.append, now=at(23, 45, day=9), **kw)
        # 0:05 の印からの実行（1回目）が失敗 → 成功の記録（done_target）は付かず、used_count=1 が付く
        self.assertIsNone(fv.start_pending(self.dir, reports.append, now=at(0, 5, day=10), **kw))
        self.assertEqual(len(calls), 2)
        self.assertIn('止まったものがあります', reports[-1])
        state = fv._read_state(self.dir)
        self.assertEqual(state.get('used_target'), '2026-11-10')
        self.assertEqual(state.get('used_count'), 1)
        self.assertIsNone(state.get('done_target'))
        # 0:05 が失敗したあと、9時までに1回だけ再試行できる（0:10、2回目）。ここでも失敗すると3回目は流れない
        self.assertIsNone(fv.start_pending(self.dir, reports.append, now=at(0, 10, day=10), **kw))
        self.assertEqual(len(calls), 4)
        self.assertEqual(fv._read_state(self.dir).get('used_count'), 2)
        why_0015 = fv.start_pending(self.dir, reports.append, now=at(0, 15, day=10), **kw)
        self.assertIsNotNone(why_0015)
        self.assertNotIn('すでに自動保存済み', why_0015)
        self.assertIn('すでに実行済み', why_0015)
        self.assertEqual(len(calls), 4)
        # 7:00 に取り込みが完了すると流れる（成功すれば done_target が付く）
        code[0] = 0
        self.assertIsNone(fv.start('サイトセブン', DONE_SITE777, self.dir, reports.append, now=at(7, 0, day=10), **kw))
        self.assertEqual(len(calls), 6)
        self.assertEqual(reports[-1], '前向き検証を自動で保存しました')
        self.assertEqual(fv._read_state(self.dir).get('done_target'), '2026-11-10')
        # 成功したあとは「すでに自動保存済み」が出る
        why_after = fv.start_pending(self.dir, reports.append, now=at(7, 5, day=10), **kw)
        self.assertIn('すでに自動保存済み', why_after)

    def test_failed_or_interrupted_pending_run_retries_once_before_9am_and_stops_on_success(self):
        # 1回目が途中で中断（または失敗）して done_target が無いまま used_target だけ書かれているとき、
        # 9時前なら1回だけ再試行でき、成功したらそれ以上流れない。
        (self.dir / fv.STATE_NAME).write_text(
            '{"pending_target": "2026-11-10", "used_target": "2026-11-10", "used_count": 1}\n',
            encoding='utf-8')
        reports, calls = [], []
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread,
                  runner=lambda args, **k: (calls.append(args), Result(0, 'v1 保存しました\n'))[1])
        self.assertIsNone(fv.start_pending(self.dir, reports.append, now=at(0, 10, day=10), **kw))
        self.assertEqual(len(calls), 2)
        self.assertEqual(reports, ['前向き検証を自動で保存しました'])
        self.assertEqual(fv._read_state(self.dir).get('done_target'), '2026-11-10')
        why_next = fv.start_pending(self.dir, reports.append, now=at(0, 15, day=10), **kw)
        self.assertIn('すでに自動保存済み', why_next)
        self.assertEqual(len(calls), 2)

    def test_completion_arriving_while_running_runs_once_after_first_finishes_if_before_9am(self):
        # 実行中に次の完了の知らせが届いても「すでに動いています」で捨てず、先の実行が終わったあとに締切内なら1回だけ流す。
        gate, inside = threading.Event(), threading.Event()
        calls, reports1, reports2, reports3 = [], [], [], []
        current_time = [at(8, 50, day=10)]

        def runner(args, **kw):
            calls.append(args[-1])
            if len(calls) == 1:
                inside.set()
                gate.wait(5)
            return Result(0, '保存しました\n')

        kw = dict(outputs=self.outputs, python=self.python, runner=runner, now=lambda: current_time[0])
        self.assertIsNone(fv.start('サイトセブン', DONE_SITE777, self.dir, reports1.append, **kw))
        self.assertTrue(inside.wait(5))
        # 実行中に2回完了が届いても、また×閉じ（None）が届いても、終わったあとに動くのは1回だけ
        self.assertIsNone(fv.start('サイトセブン', DONE_SITE777, self.dir, reports2.append, **kw))
        self.assertIsNone(fv.start('P’s CUBE', DONE_PSCUBE, self.dir, reports3.append, **kw))
        self.assertIsNotNone(fv.start('サイトセブン', None, self.dir, reports3.append, **kw))
        gate.set()
        for _ in range(100):
            if len(calls) >= 4 and reports1 and reports2 and reports3:
                break
            threading.Event().wait(0.02)
        self.assertEqual(calls, ['daily', 'morning', 'daily', 'morning'], '先の実行のあと1回だけ続けて流れる')
        self.assertEqual(reports1, ['前向き検証を自動で保存しました'])
        self.assertEqual(reports2, ['前向き検証を自動で保存しました'])
        self.assertEqual(reports3, ['前向き検証を自動で保存しました'])

        # 先の実行が終わった時点で9:00を過ぎていれば、控えていた分は流さない
        gate.clear()
        inside.clear()
        calls.clear()
        late_reports = []
        current_time[0] = at(8, 58, day=10)
        self.assertIsNone(fv.start('サイトセブン', DONE_SITE777, self.dir, lambda _: None, **kw))
        self.assertTrue(inside.wait(5))
        self.assertIsNone(fv.start('サイトセブン', DONE_SITE777, self.dir, late_reports.append, **kw))
        current_time[0] = at(9, 1, day=10)
        gate.set()
        for _ in range(100):
            if late_reports:
                break
            threading.Event().wait(0.02)
        self.assertEqual(calls, ['daily', 'morning'], '9時を過ぎてから終わったときは後続を流さない')
        self.assertIn('0時〜9時', late_reports[0])

    def test_state_write_failure_records_to_error_log(self):
        import error_log
        error_log.forget()
        # data_dir の中に STATE_NAME と同名のフォルダを置いて書き込みを失敗させる
        bad = self.dir / 'bad-state'
        (bad / fv.STATE_NAME).mkdir(parents=True)
        reports, calls = [], []
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread,
                  runner=lambda args, **k: (calls.append(args), Result(0))[1])
        why = fv.start('サイトセブン', DONE_SITE777, bad, reports.append, now=at(23, 45, day=9), **kw)
        self.assertIn('記録できませんでした', why)
        log = (bad / 'errors.log').read_text(encoding='utf-8')
        self.assertIn('forward.state', log)

    def test_missing_research_scripts_do_nothing(self):
        reports, calls = [], []
        kw = dict(outputs=self.dir / 'missing-outputs', python=self.python, thread=SyncThread,
                  runner=lambda args, **k: (calls.append(args), Result(0))[1])
        # 研究スクリプトが無いPCでは、23:45でも印のファイルを作らず、0:05でも何もしない
        why = fv.start('サイトセブン', DONE_SITE777, self.dir, reports.append, now=at(23, 45, day=9), **kw)
        self.assertIn('ファイルがありません', why)
        self.assertFalse((self.dir / fv.STATE_NAME).exists())
        (self.dir / fv.STATE_NAME).write_text('{"pending_target": "2026-11-10"}\n', encoding='utf-8')
        why_pending = fv.start_pending(self.dir, reports.append, now=at(0, 5, day=10), **kw)
        self.assertIn('ファイルがありません', why_pending)
        self.assertEqual(calls, [])
        self.assertEqual(reports, [])

    def test_app_shows_the_meruhen_note_when_the_meruhen_window_closes(self):
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        self.assertIn("watch_capture_window(process, 'メルヘン', meruhen_message, after_close=meruhen_forward_note)", source)
        self.assertIn('note = forward_validation.meruhen_note(DATA_DIR, since)', source)
        self.assertIn('if after_close is not None:\n                after_close()', source)

    def test_multi_window_gate_waits_for_last_window_and_cancels_on_abort(self):
        # ほかの取り込み窓が開いている間は動かさず、最後の窓が閉じたときに1回だけ判定する。
        gate = fv.ForwardWindowGate()
        gate.defer('サイトセブン', '指定日（11/09）の取り込みが完了しました。')
        self.assertTrue(gate.has_pending())
        # 2つ目の窓も完了して最後の窓が閉じたとき、まとめて1回だけ返す
        label, merged = gate.take('サイトセブン', '指定日（11/08）の取り込みが完了しました。')
        self.assertEqual(label, 'サイトセブン')
        self.assertIn('11/09', merged)
        self.assertIn('11/08', merged)
        self.assertFalse(gate.has_pending())
        # 1つ目が完了したあと2つ目のP-STATION窓が×閉じ（または停止）になったら保留を取り消す
        gate.defer('サイトセブン', '指定日（11/09）の取り込みが完了しました。')
        gate.cancel()
        self.assertIsNone(gate.flush())
        # app.py にゲートが接続されている
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        self.assertIn('ForwardWindowGate()', source)

    def test_is_running_reflects_background_execution_and_close_app_waits(self):
        gate, inside = threading.Event(), threading.Event()
        self.assertFalse(fv.is_running())

        def slow(args, **kw):
            inside.set()
            gate.wait(5)
            return Result(0)

        t = threading.Thread(target=fv.run, args=(self.plan(), self.dir), kwargs={'runner': slow, 'now': at(7)})
        t.start()
        self.assertTrue(inside.wait(5))
        self.assertTrue(fv.is_running())
        gate.set()
        t.join(5)
        self.assertFalse(fv.is_running())
        # close_app が実行中の前向き検証も close_wait で待ち、×閉じ時に自動起動はしない
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        close = source[source.index('def close_app'):source.index("root.protocol('WM_DELETE_WINDOW', close_app)")]
        self.assertIn('forward_validation.is_running()', close)
        self.assertNotIn('forward_validation.start', close)

    def test_evening_pending_only_marks_when_todays_business_day_was_captured(self):
        reports, calls = [], []
        kw = dict(outputs=self.outputs, python=self.python, thread=SyncThread,
                  runner=lambda args, **k: (calls.append(args), Result(0))[1])
        # 11/9 23:45 に過去日（11/6）だけ取り直して完了 → 印を残さない
        why_past = fv.start('サイトセブン', '指定日（11/06）の取り込みが完了しました。追加5台、既存を保持0台、グラフ不明0台。',
                            self.dir, reports.append, now=at(23, 45, day=9), **kw)
        self.assertIsNotNone(why_past)
        self.assertFalse((self.dir / fv.STATE_NAME).exists(), '過去日の取り直しでは翌朝の印を残さない')
        why_past_range = fv.start('サイトセブン', '範囲の取り込みが完了しました。11/05、11/06',
                                  self.dir, reports.append, now=at(23, 46, day=9), **kw)
        self.assertIsNotNone(why_past_range)
        self.assertFalse((self.dir / fv.STATE_NAME).exists(), '当日を含まない範囲では翌朝の印を残さない')
        # 当日（11/9）の単日完了 → 印を残す
        why_today = fv.start('サイトセブン', '指定日（11/09）の取り込みが完了しました。追加5台、既存を保持0台、グラフ不明0台。',
                             self.dir, reports.append, now=at(23, 47, day=9), **kw)
        self.assertIn('0時〜9時', why_today)
        self.assertEqual(fv._read_state(self.dir).get('pending_target'), '2026-11-10')


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
