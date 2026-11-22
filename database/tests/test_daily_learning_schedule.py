"""日次学習をいつ動かすか（daily_learning_runtime.run_due、2026-11-14）。

11/13夜、メルヘンの取り込み窓が朝まで開いたままで「最後の窓が閉じたら」「窓が開いていなければ7:30に」のどちらも
動かず、PC本体を閉じて11/14の予測が保存されなかった（利用者「取り込みが終了したら勝手にやってくれるはずなのに
なぜかうまくいってない」）。取り込みが終わったかを、窓ではなく原本DBの書き込みで判断する。
"""
from contextlib import closing
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_learning_runtime as runtime  # noqa: E402
from daily_learning import JST  # noqa: E402

NIGHT = datetime(2026, 11, 14, 0, 30, tzinfo=JST)     # 対象日は 11/14
TARGET = '2026-11-14'


class RunDueTest(unittest.TestCase):
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

    def save(self, *stores):
        folder = self.root / 'daily-learning'
        folder.mkdir(exist_ok=True)
        with closing(sqlite3.connect(folder / 'journal.sqlite3')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS predictions (key TEXT PRIMARY KEY, body BLOB)')
            for store in stores:
                db.execute('INSERT OR REPLACE INTO predictions VALUES (?, ?)', (f'{TARGET}|{store}', b'{}'))

    def due(self, now=NIGHT, last=None, **kwargs):
        return runtime.run_due(self.root, now, last, **kwargs)

    def test_runs_once_the_capture_has_been_quiet_for_ten_minutes_even_with_windows_open(self):
        self.touch('meruhen', minutes_ago=3)                       # メルヘンを取り込み中
        self.touch('pscube', minutes_ago=3)
        self.assertFalse(self.due()[0], '書き込みから10分たつまで待つ')
        self.touch('meruhen', minutes_ago=11)
        self.touch('pscube', minutes_ago=11)
        due, mark = self.due()
        self.assertTrue(due)
        # 同じ原本でもう一度は動かさない（「取り込み待ち」の晩に5分ごとに読み直さない）。
        self.assertEqual(self.due(last=mark), (False, mark))
        # 取り込みを足したら（原本が変わったら）、また10分待ってから動かす。
        self.touch('meruhen', minutes_ago=2)
        self.assertFalse(self.due(last=mark)[0])
        self.touch('meruhen', minutes_ago=10.5)
        self.assertTrue(self.due(last=mark)[0])

    def test_one_recently_written_database_does_not_make_the_other_database_wait(self):
        # 1つの原本DBが10分以内に書かれていても、10分以上静穏な別の原本の店は先に動かす。
        self.touch('meruhen', minutes_ago=15)
        self.touch('pscube', minutes_ago=2)
        due, mark = self.due()
        self.assertTrue(due, '静穏なメルヘンを先に動かす')
        self.assertEqual(set(mark[1]), {'meruhen'}, '書き込み中のpscubeはまだ印に入れない')
        self.save('nagamachiminami', 'saiwaichou')
        # pscube がまだ10分たっていない間は待つ。
        self.assertFalse(self.due(last=mark)[0])
        # pscube が最後の書き込みから10分たったら、追加の書き込みが無くても動く。
        self.touch('pscube', minutes_ago=11)
        due2, mark2 = self.due(last=mark)
        self.assertTrue(due2)
        self.assertEqual(set(mark2[1]), {'meruhen', 'pscube'})

    def test_adding_only_low_games_record_for_site777_triggers_rerun_after_quiet(self):
        # サイトセブンで500G未満の控え（site777-staging/日付-low.json）だけが追加・更新され、
        # pscube.sqlite3 の更新時刻が変わらないときも、10分静穏後に再実行する。
        due, mark = self.due()
        self.assertTrue(due)
        self.save('nagamachiminami', 'saiwaichou')                 # P-STATION だけ90%未満で取り込み待ちだったとする
        self.assertFalse(self.due(last=mark)[0])
        staging = self.root / 'site777-staging'
        staging.mkdir(exist_ok=True)
        low_file = staging / '2026-11-13-low.json'
        low_file.write_text('{"123": [101, 102]}', encoding='utf-8')
        recent = NIGHT.timestamp() - 2 * 60
        os.utime(low_file, (recent, recent))
        self.assertFalse(self.due(last=mark)[0], '控えの書き込みから10分たつまでは待つ')
        quiet_stamp = NIGHT.timestamp() - 11 * 60
        os.utime(low_file, (quiet_stamp, quiet_stamp))
        due2, mark2 = self.due(last=mark)
        self.assertTrue(due2, 'pscube.sqlite3 が変わらなくても low.json の追加で再実行する')
        self.assertFalse(self.due(last=mark2)[0], '同じ控えでは繰り返さない')

    def test_transient_failure_is_retried_before_cutoff_while_waiting_for_capture_is_not(self):
        # 一時的な失敗（DBの鍵など）は原本DBの更新時刻が変わらなくても8:00前に再試行し、
        # データ不足の「取り込み待ち」は5分ごとに読み直さない。
        import json
        due, mark = self.due()
        self.assertTrue(due)
        # 1. 長町南・幸町が「取り込み待ち」、P-STATION が「処理失敗（原本DBを読めません…）」だったとき
        status = ('長町南：取り込み待ち：長町南の前日データが不足しています／'
                  '幸町：取り込み待ち：幸町の前日データが不足しています／'
                  'P-STATION：処理失敗（原本DBを読めません（database is locked）。取り込み中なら、終わったあとに読み直します）。従来方式を使用してください')
        (self.root / runtime.FILE_NAME).write_text(
            json.dumps({'updated_at': NIGHT.isoformat(), 'status': status}, ensure_ascii=False), encoding='utf-8')
        due2, mark2 = self.due(last=mark)
        self.assertTrue(due2, '処理失敗の P-STATION は同じ原本でも再試行する')
        # app.py の daily_tick が使う clear_failed_mark でも、処理失敗の pscube だけ印が消え、取り込み待ちの meruhen は残る。
        cleared = runtime.clear_failed_mark(mark, status)
        self.assertEqual(set(cleared[1]), {'meruhen'})
        # 2. 再試行の結果、P-STATION も「取り込み待ち」に変わったら、同じ原本ではもう読み直さない。
        waiting_only = ('長町南：取り込み待ち：長町南の前日データが不足しています／'
                        '幸町：取り込み待ち：幸町の前日データが不足しています／'
                        'P-STATION：取り込み待ち：P-STATIONの前日データが不足しています')
        (self.root / runtime.FILE_NAME).write_text(
            json.dumps({'updated_at': NIGHT.isoformat(), 'status': waiting_only}, ensure_ascii=False), encoding='utf-8')
        self.assertFalse(self.due(last=mark2)[0], '取り込み待ちでは5分ごとに読み直さない')
        self.assertEqual(runtime.clear_failed_mark(mark2, waiting_only), mark2)
        # 3. 記録DBの鍵などで export の前に「失敗で終了」したときも、8:00前なら再試行し、8:00以降は動かさない。
        runtime.trace(self.root, '失敗で終了：OperationalError: database is locked', now=NIGHT)
        self.assertTrue(self.due(last=mark2)[0])
        after_cutoff = datetime(2026, 11, 14, 8, 0, tzinfo=JST)
        self.assertFalse(self.due(now=after_cutoff, last=mark2)[0], '8:00以降は再試行しない')

    def test_only_unsaved_stores_and_their_own_database_count(self):
        self.save('nagamachiminami', 'saiwaichou')
        self.touch('meruhen', minutes_ago=1)                       # メルヘンは保存済みなので、書かれていても関係ない
        due, mark = self.due()
        self.assertTrue(due)
        self.assertEqual(set(mark[1]), {'pscube'})
        self.save('pscube:c740601:20')
        self.assertFalse(self.due()[0], '全部保存したら動かさない')

    def test_a_partial_save_does_not_rerun_the_same_inputs(self):
        due, mark = self.due()
        self.assertTrue(due)
        self.save('nagamachiminami', 'saiwaichou')                 # P-STATION だけ取り込み待ちで残った
        self.assertFalse(self.due(last=mark)[0])

    def test_outside_the_saving_hours_it_never_runs(self):
        for now in (datetime(2026, 11, 14, 8, 0, tzinfo=JST), datetime(2026, 11, 14, 23, 29, tzinfo=JST),
                    datetime(2026, 11, 14, 12, 0, tzinfo=JST)):
            with self.subTest(now=now):
                self.assertFalse(self.due(now=now)[0])
        start = datetime(2026, 11, 13, 23, 30, tzinfo=JST)
        self.touch('meruhen', minutes_ago=30, now=start)
        self.touch('pscube', minutes_ago=30, now=start)
        self.assertTrue(self.due(now=start)[0], '23:30から（対象日は翌日）')

    def test_closing_the_app_does_not_wait_for_ten_minutes(self):
        self.touch('meruhen', minutes_ago=1)
        self.touch('pscube', minutes_ago=1)
        self.assertFalse(self.due()[0])
        due, mark = self.due(on_close=True)
        self.assertTrue(due, 'PC本体を閉じる＝取り込みは終わった、とみる')
        self.assertFalse(self.due(last=mark, on_close=True)[0], '同じ原本で試したばかりなら、閉じるときも動かさない')

    def test_a_missing_or_unreadable_journal_counts_every_store_as_unsaved(self):
        self.assertEqual(runtime.unsaved_stores(self.root, TARGET), list(runtime.STORES))
        (self.root / 'daily-learning').mkdir()
        (self.root / 'daily-learning' / 'journal.sqlite3').write_bytes(b'not a database')
        self.assertEqual(runtime.unsaved_stores(self.root, TARGET), list(runtime.STORES))

    def test_the_pc_app_wires_the_check_into_the_tick_startup_window_close_and_closing(self):
        source = (Path(runtime.__file__).parent / 'app.py').read_text(encoding='utf-8')
        tick = source[source.index('def daily_tick'):source.index('def daily_on_start')]
        self.assertIn('run_due(DATA_DIR', tick)
        self.assertIn('clear_failed_mark(daily_last[0]', tick)
        self.assertNotIn('capture_open', tick, '取り込み窓が開いていても、原本DBで判断する')
        self.assertNotIn('now.hour in (7, 23)', tick)
        close = source[source.index('def close_app'):source.index("root.protocol('WM_DELETE_WINDOW', close_app)")]
        self.assertIn('on_close=True', close)
        self.assertIn('daily_worker.start()', close)

    def test_run_with_quiet_skips_stores_whose_source_db_is_still_being_written(self):
        # 1つの原本DB（meruhen）が静穏で、もう1つ（pscube）が書き込み中（10分未満）のとき、
        # quiet 指定の run は書き込み中の原本を開かず、その店の予測も判定・固定保存しない。
        from unittest.mock import patch
        self.touch('meruhen', minutes_ago=15)
        self.touch('pscube', minutes_ago=2)
        loaded_sources = []
        built_stores = []

        def fake_load(data_dir, target, sources=('meruhen', 'pscube')):
            loaded_sources.append(tuple(sources))
            rows = []
            if 'meruhen' in sources:
                rows += [{'store': 'nagamachiminami', 'day': '2026-11-13', 'rack': 1, 'machine': 'M', 'games': 3000},
                         {'store': 'saiwaichou', 'day': '2026-11-13', 'rack': 1, 'machine': 'M', 'games': 3000}]
            if 'pscube' in sources:
                rows += [{'store': 'pscube:c740601:20', 'day': '2026-11-13', 'rack': 1, 'machine': 'M', 'games': 3000}]
            return rows, {'records': [], 'machines': []}

        def fake_build(store_rows, ps, target, journal, node, history_rows=None):
            store = store_rows[0]['store']
            built_stores.append(store)
            return {'target': target, 'input_day': '2026-11-13', 'version': 'test',
                    'groups': [{'store': store, 'name': 'M', 'active': 'current', 'status': 'current',
                                'selected': [1], 'current': [1], 'learned': [1]}]}

        with patch.object(runtime, 'load_inputs', side_effect=fake_load), \
                patch.object(runtime, 'ready', return_value=[]), \
                patch.object(runtime, 'build_prediction', side_effect=fake_build):
            doc = runtime.run(self.root, clock=lambda: NIGHT, sync=False, quiet=runtime.QUIET_SECONDS)
        self.assertEqual(loaded_sources, [('meruhen',)], '書き込み中のpscube原本は開かない')
        self.assertEqual(built_stores, ['nagamachiminami', 'saiwaichou'], '静穏なメルヘン2店だけを保存する')
        self.assertEqual(runtime.unsaved_stores(self.root, TARGET), ['pscube:c740601:20'])
        self.assertIn('P-STATION：取り込み中のため待機', doc['status'])

    def test_sync_export_failure_retries_export_only_without_recomputing(self):
        # 同期先（Googleドライブ）への書き出しに失敗したとき、全店舗が保存済みであっても
        # 次の確認で予測を再計算せず（原本DBも開かず）書き出しだけを再試行する。
        import json
        from unittest.mock import patch
        from daily_learning import Journal
        j = Journal(self.root / 'daily-learning' / 'journal.sqlite3')
        try:
            for store in runtime.STORES:
                j.freeze(TARGET, {'target': TARGET, 'input_day': '2026-11-13', 'version': 'test',
                                  'groups': [{'store': store, 'name': 'M', 'active': 'current', 'status': 'current',
                                              'selected': [1], 'current': [1], 'learned': [1]}]},
                         {'rows': []}, NIGHT, store=store)
        finally:
            j.close()
        missing_sync = self.root / 'drive-sync'
        with patch('core.resolve_sync_dir', return_value=missing_sync):
            doc = runtime.run(self.root, clock=lambda: NIGHT, sync=True)
        self.assertIn('同期先へ書けません', doc['status'])
        self.assertFalse((missing_sync / runtime.FILE_NAME).exists())
        self.assertTrue(runtime.needs_sync_retry(self.root))
        # 同期先フォルダーが復活したら、原本DBを開かずに書き出しだけ再試行して成功する
        missing_sync.mkdir()
        with patch('core.resolve_sync_dir', return_value=missing_sync), \
                patch.object(runtime, 'load_inputs', side_effect=AssertionError('原本を開いてはいけない')), \
                patch.object(runtime, 'build_prediction', side_effect=AssertionError('再計算してはいけない')):
            msg = runtime.retry_sync_export(self.root, clock=lambda: NIGHT)
        self.assertIsNotNone(msg)
        self.assertTrue((missing_sync / runtime.FILE_NAME).is_file())
        synced = json.loads((missing_sync / runtime.FILE_NAME).read_text(encoding='utf-8'))
        local = json.loads((self.root / runtime.FILE_NAME).read_text(encoding='utf-8'))
        self.assertNotIn('同期先へ書けません', synced['status'])
        self.assertNotIn('同期先へ書けません', local['status'])
        self.assertFalse(runtime.needs_sync_retry(self.root))


if __name__ == '__main__':
    unittest.main()
