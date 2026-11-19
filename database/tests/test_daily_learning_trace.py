"""日次学習の実行の記録（run.log）と、PC本体を閉じるときの待ち方（2026-11-20）。

11/20 7:08 の実行が長町南を保存したあと止まり、×で閉じたとき3分の待ちを過ぎて途中で切られた（幸町・P-STATIONは
保存されず、状態のファイルも書かれなかった）。どこで止まったかが分からなかったので、実行の各段階の時刻をファイルに残し、
閉じるときは3分を過ぎても黙って切らずに選ばせる。"""
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_learning as d
import daily_learning_runtime as runtime
import daily_learning_ui as ui


def row(day, store):
    return dict(store=store, day=day, machine='試験機', rack=1, games=3000, bb=10, rb=5)


class RunTraceTest(unittest.TestCase):
    def test_each_stage_of_a_run_is_written_with_the_store_and_the_result(self):
        at = datetime.fromisoformat

        def fake_load(data_dir, target, sources=('meruhen', 'pscube')):
            return [row(d.shift(target, -1), s) for s in runtime.STORES], {'records': [], 'machines': []}

        def fake_build(rows, pscube, target, journal, node=None, history_rows=None):
            if rows[0]['store'] == runtime.STORES[2]:
                raise RuntimeError('計算できません')
            group = dict(key='k', store=rows[0]['store'], name='試験機', current=[], learned=[], selected=[],
                         active='current', trained=False, status='学習データ不足・従来方式', pool=[])
            return dict(input_day=d.shift(target, -1), groups=[group], models={}, source_sha256={})

        waiting = runtime.STORES[1]
        with tempfile.TemporaryDirectory() as temp, patch.object(runtime, 'load_inputs', side_effect=fake_load), \
                patch.object(runtime, 'ready', side_effect=lambda rows, shown, stores, low: ['前日データが不足しています']
                             if stores == (waiting,) else []), \
                patch.object(runtime, 'build_prediction', side_effect=fake_build):
            runtime.run(Path(temp), clock=lambda: at('2026-11-20T07:08:00+09:00'), sync=False)
            log = (Path(temp) / 'daily-learning' / runtime.TRACE_NAME).read_text(encoding='utf-8')
        lines = [line.split('\t', 1)[1] for line in log.splitlines()]
        names = [runtime.STORE_NAMES[s] for s in runtime.STORES]
        self.assertEqual(lines[0], '依頼を受けました（鍵を待ちます）')
        self.assertEqual(lines[1], '開始：対象 2026-11-20')
        self.assertTrue(lines[2].startswith('原本を読みました：meruhen・pscube'), lines[2])
        # 店ごとに「確かめる→計算する→保存した」。取り込み待ちの店はその理由、失敗した店はその内容。
        self.assertIn(f'{names[0]}：データを確かめます', lines)
        self.assertIn(f'{names[0]}：予測を計算します', lines)
        self.assertIn(f'{names[0]}：固定保存しました', lines)
        self.assertIn(f'{names[1]}：取り込み待ち：前日データが不足しています', lines)
        self.assertNotIn(f'{names[1]}：予測を計算します', lines)
        self.assertIn(f'{names[2]}：予測を計算します', lines)
        self.assertTrue(any(line.startswith(f'{names[2]}：処理失敗') for line in lines), lines)
        self.assertTrue(lines[-1].startswith('終了：'), lines[-1])
        # 止まった場所が分かる順：計算を始めた行のあとに、保存・失敗の行が続く。
        self.assertLess(lines.index(f'{names[0]}：予測を計算します'), lines.index(f'{names[0]}：固定保存しました'))
        self.assertTrue(all('\t' in line for line in log.splitlines()), '各行に時刻')

    def test_the_log_is_trimmed_and_a_write_failure_never_stops_the_run(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(runtime, 'TRACE_KEEP', 5):
                for i in range(20):
                    runtime.trace(Path(temp), 'x' * 150 + str(i))
            lines = (Path(temp) / 'daily-learning' / runtime.TRACE_NAME).read_text(encoding='utf-8').splitlines()
            self.assertLessEqual(len(lines), 5 + 5, '長くなったら古い行から捨てる')
            self.assertTrue(lines[-1].endswith('19'))
            # 書けない場所（ファイルの位置にフォルダーがある）でも例外を出さない。
            blocked = Path(temp) / 'blocked'
            (blocked / 'daily-learning' / runtime.TRACE_NAME).mkdir(parents=True)
            runtime.trace(blocked, '書けない')


class CloseWaitTest(unittest.TestCase):
    def test_close_waits_three_minutes_then_asks_instead_of_cutting_the_save(self):
        asked = []
        ask_yes = lambda: asked.append('はい') or True
        ask_no = lambda: asked.append('いいえ') or False
        limit = 100 + ui.CLOSE_WAIT_SECONDS
        self.assertEqual(ui.close_wait(False, 50, limit, ask_yes), (True, limit), '終わっていれば、すぐ閉じる')
        self.assertEqual(ui.close_wait(True, 200, limit, ask_yes), (False, limit), '3分までは聞かずに待つ')
        self.assertEqual(asked, [])
        self.assertEqual(ui.close_wait(True, limit, limit, ask_yes), (False, limit + ui.CLOSE_WAIT_SECONDS), '「はい」：もう3分')
        self.assertEqual(ui.close_wait(True, limit + 5, limit + ui.CLOSE_WAIT_SECONDS, ask_yes),
                         (False, limit + ui.CLOSE_WAIT_SECONDS), '延ばした3分の間は聞かない')
        self.assertEqual(ui.close_wait(True, limit, limit, ask_no), (True, limit), '「いいえ」：閉じる')
        self.assertEqual(asked, ['はい', 'いいえ'])

    def test_the_pc_app_uses_the_choice_when_closing(self):
        source = (Path(runtime.__file__).parent / 'app.py').read_text(encoding='utf-8')
        close = source[source.index('def close_app'):source.index("root.protocol('WM_DELETE_WINDOW', close_app)")]
        self.assertIn('daily_learning_ui.close_wait(daily_worker.running', close)
        self.assertIn('messagebox.askyesno', close)
        self.assertNotIn('time.monotonic() < limit', close, '期限を過ぎたら黙って閉じる古い待ち方に戻さない')


if __name__ == '__main__':
    unittest.main()
