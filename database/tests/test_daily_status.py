"""PC本体画面の「今夜の日次学習」の1行と、5分ごとの確認が止まらないこと（2026-11-23）。

11/23 の夜は PC が起きていて、判定も「動かす」になるはずなのに日次学習が一度も始まらず、どこで止まったかの
記録も無かった。利用者「普通に取り込んだあと学習し候補を出してるかどうかを肉眼的にわかるようにしたい」。"""
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import textwrap
import threading
import tkinter as tk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_learning_runtime as runtime  # noqa: E402
from daily_learning import JST, Journal  # noqa: E402

NIGHT = datetime(2026, 11, 14, 0, 30, tzinfo=JST)     # 対象日は 11/14
TARGET = '2026-11-14'
APP = Path(__file__).resolve().parents[1] / 'app.py'


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in runtime.DB_FILES.values():
            (self.root / name).write_bytes(b'')
        self.touch('meruhen', minutes_ago=30)
        self.touch('pscube', minutes_ago=30)

    def touch(self, source, minutes_ago, now=NIGHT):
        stamp = now.timestamp() - minutes_ago * 60
        os.utime(self.root / runtime.DB_FILES[source], (stamp, stamp))

    def save(self, store, *, target=TARGET, saved_at='2026-11-14T00:28:41+09:00', racks=(1, 2, 3)):
        journal = Journal(self.root / 'daily-learning' / 'journal.sqlite3')
        try:
            journal.append('predictions', f'{target}|{store}',
                           {'target': target, 'saved_at': saved_at,
                            'groups': [{'name': 'M', 'selected': list(racks)}]})
            journal.db.commit()
        finally:
            journal.close()

    def status_doc(self, status, at='2026-11-14T00:20:00+09:00'):
        (self.root / runtime.FILE_NAME).write_text(json.dumps({'updated_at': at, 'status': status}, ensure_ascii=False),
                                                   encoding='utf-8')


class RunDueReasonTest(Folder):
    def reasons(self, now=NIGHT, last=None, **kwargs):
        got = []
        due, mark = runtime.run_due(self.root, now, last, reasons=got, **kwargs)
        self.assertEqual(len(got), 1, got)
        return due, mark, got[0]

    def test_each_decision_says_why(self):
        due, mark, why = self.reasons()
        self.assertTrue(due)
        self.assertEqual(why, 'メルヘン（長町南・幸町）・P-STATIONの原本で動かす')
        self.assertIn('前回と同じ原本', self.reasons(last=mark)[2])
        self.touch('pscube', minutes_ago=3)
        due, _, why = self.reasons(last=mark)
        self.assertFalse(due)
        self.assertIn('P-STATIONは書き込みから10分待ち', why)
        self.assertEqual(self.reasons(now=datetime(2026, 11, 14, 12, 0, tzinfo=JST))[2], '保存できる時間帯の外（23:30〜8:00）')
        self.assertIn('取り込み画面が開いている間は待つ', self.reasons(skip_sources=('meruhen', 'pscube'))[2])

    def test_saved_everywhere_and_no_reasons_list_keeps_the_old_call(self):
        for store in runtime.STORES:
            self.save(store)
        self.assertEqual(self.reasons()[2], '全店の予測は保存済み')
        self.assertEqual(runtime.run_due(self.root, NIGHT, None), (False, None))


class NightStatusTest(Folder):
    def test_saved_store_shows_time_and_candidate_count_and_the_rest_wait(self):
        self.save('pscube:c740601:20', racks=(5, 6))
        self.status_doc('長町南：取り込み待ち（前日のデータがそろっていません）／幸町：取り込み中のため待機（書き込み終了後10分で保存します）')
        text, level = runtime.night_status(self.root, NIGHT)
        self.assertEqual(level, 'wait')
        self.assertTrue(text.startswith('今夜の日次学習（11/14の予測）：'), text)
        self.assertIn('長町南 取り込み待ち', text)
        self.assertIn('幸町 取り込み中のため待機', text)
        self.assertIn('P-STATION 保存済み 00:28（候補2台）', text)

    def test_all_saved_is_ok_and_failure_is_error(self):
        for store in runtime.STORES:
            self.save(store)
        self.assertEqual(runtime.night_status(self.root, NIGHT)[1], 'ok')
        other = Folder('setUp')
        other.setUp()
        self.addCleanup(other.tmp.cleanup)
        other.status_doc('長町南：処理失敗（RuntimeError）／幸町：取り込み待ち')
        text, level = runtime.night_status(other.root, NIGHT)
        self.assertEqual(level, 'error')
        self.assertIn('長町南 処理失敗', text)

    def test_after_eight_an_unsaved_store_is_an_error_and_a_full_save_is_idle(self):
        noon = datetime(2026, 11, 14, 12, 0, tzinfo=JST)
        text, level = runtime.night_status(self.root, noon)
        self.assertEqual(level, 'error', '8時までに保存されなかった')
        self.assertIn('8時で締切', text)
        self.assertIn('長町南 未保存', text)
        for store in runtime.STORES:
            self.save(store)
        self.assertEqual(runtime.night_status(self.root, noon)[1], 'idle')

    def test_an_old_status_from_another_night_is_not_reused(self):
        self.status_doc('長町南：処理失敗', at='2026-11-13T00:20:00+09:00')
        text, level = runtime.night_status(self.root, NIGHT)
        self.assertEqual(level, 'wait')
        self.assertIn('長町南 まだ', text)

    def test_status_only_opens_the_predictions_table(self):
        source = Path(runtime.__file__).read_text(encoding='utf-8')
        body = source[source.index('def night_status'):source.index('def method_signature')]
        self.assertIn("journal.get('predictions'", body)
        for table in ('outcomes', 'decisions'):
            self.assertNotIn(table, body, '成績の表は開かない')


class FakeRoot:
    def __init__(self):
        self.after_calls = []

    def after(self, ms, func):
        self.after_calls.append((ms, func))


class FakeLabel:
    def __init__(self):
        self.text, self.background = '', ''

    def configure(self, text=None, background=None):
        self.text, self.background = text, background


class FakeErrors:
    def __init__(self):
        self.records = []

    def record(self, directory, where, error, **kwargs):
        self.records.append((where, type(error).__name__))


class FakeWorker:
    def __init__(self):
        self.results = queue.Queue()
        self.running = False
        self.starts = []

    def start(self, **kwargs):
        self.starts.append(kwargs)
        return True


def tick_functions(data_dir, *, check_pending_forward):
    """app.py の main() の中の daily_tick まわりを取り出し、偽の画面・部品で動かす。"""
    source = APP.read_text(encoding='utf-8')
    start = source.index('    daily_tick_note = [None, None]')
    end = source.index('    def daily_on_start')
    code = textwrap.dedent(source[start:end])
    env = {
        'closing': [False], 'root': FakeRoot(), 'error_log': FakeErrors(), 'DATA_DIR': Path(data_dir),
        'daily_worker': FakeWorker(), 'daily_last': [None], 'sync_retry_running': [False],
        'told': [], 'daily_status': FakeLabel(), 'tk': tk, 'datetime': datetime, 'threading': threading,
        'check_pending_forward': check_pending_forward,
    }
    env['tell'] = env['told'].append
    exec(code, env)  # noqa: S102 - 試験用にアプリの関数を取り出すだけ
    return env


class DailyTickTest(Folder):
    def run_log(self):
        path = self.root / 'daily-learning' / runtime.TRACE_NAME
        return path.read_text(encoding='utf-8').splitlines() if path.exists() else []

    def test_an_exception_inside_the_check_still_books_the_next_check_and_is_recorded(self):
        def broken():
            raise RuntimeError('壊れた')
        env = tick_functions(self.root, check_pending_forward=broken)
        env['daily_tick']()
        self.assertEqual([ms for ms, _ in env['root'].after_calls], [300_000], '例外でも次の5分を予約する')
        self.assertIs(env['root'].after_calls[0][1], env['daily_tick'])
        self.assertIn(('daily.tick', 'RuntimeError'), env['error_log'].records)
        self.assertIn('定期確認でエラー（RuntimeError。errors.log）', env['daily_status'].text)
        self.assertIn('最後の確認', env['daily_status'].text)

    def test_the_decision_is_written_once_until_it_changes_and_the_screen_shows_the_night(self):
        env = tick_functions(self.root, check_pending_forward=lambda: None)
        for store in runtime.STORES:
            self.save(store, target=runtime.prediction_target(datetime.now(JST)) or TARGET)
        env['daily_tick']()
        env['daily_tick']()
        notes = [line for line in self.run_log() if '定期確認：' in line]
        self.assertEqual(len(notes), 1, notes)
        self.assertIn('待ちます', notes[0])
        self.assertEqual(len(env['root'].after_calls), 2)
        self.assertIn('日次学習', env['daily_status'].text)
        self.assertEqual(env['daily_worker'].starts, [])

    def test_closing_stops_the_loop(self):
        env = tick_functions(self.root, check_pending_forward=lambda: None)
        env['closing'][0] = True
        env['daily_tick']()
        self.assertEqual(env['root'].after_calls, [])

    def test_finished_results_reach_the_screen_within_the_short_poll(self):
        env = tick_functions(self.root, check_pending_forward=lambda: None)
        env['daily_worker'].results.put('P-STATION：11/14の事前予測を固定保存しました')
        env['daily_results_poll']()
        self.assertEqual(env['told'], ['P-STATION：11/14の事前予測を固定保存しました\n'])
        self.assertEqual(env['root'].after_calls[-1][0], 10_000)
        self.assertIn('日次学習', env['daily_status'].text)


class AppWiringTest(unittest.TestCase):
    def test_app_start_close_and_deferral_are_written_to_the_run_log(self):
        source = APP.read_text(encoding='utf-8')
        self.assertIn("trace(DATA_DIR, f'PCアプリを起動しました（版 {source_version()}）')", source)
        self.assertIn("trace(DATA_DIR, 'PCアプリを閉じます')", source)
        self.assertIn("trace(self.data_dir, '依頼を受けました（実行中のため、終わったあとにもう一度動かします）')", source)
        self.assertIn('root.after(10_000, daily_results_poll)', source)
        self.assertIn("daily_status.pack(fill='x', pady=(0, 10))", source)

    def test_source_version_reads_the_branch_head_without_git(self):
        import app
        with tempfile.TemporaryDirectory() as name:
            top = Path(name)
            (top / '.git' / 'refs' / 'heads').mkdir(parents=True)
            (top / '.git' / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
            (top / '.git' / 'refs' / 'heads' / 'main').write_text('abcdef1234567\n', encoding='utf-8')
            self.assertEqual(app.source_version(top / 'database'), 'abcdef1')
            (top / '.git' / 'refs' / 'heads' / 'main').unlink()
            (top / '.git' / 'packed-refs').write_text('# pack\n1234567890abc refs/heads/main\n', encoding='utf-8')
            self.assertEqual(app.source_version(top / 'database'), '1234567')
        self.assertEqual(app.source_version(Path(tempfile.gettempdir()) / 'no-such' / 'database'), '不明')


if __name__ == '__main__':
    unittest.main()
