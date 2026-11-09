"""取り込みが最後まで終わって窓が自分で閉じたときだけ、P-STATIONの前向き検証を自動で保存する（2026-11-09 利用者）。"""
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


if __name__ == '__main__':
    unittest.main()
