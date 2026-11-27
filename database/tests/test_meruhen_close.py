"""Meruhen PC：自動取り込みが全部終わったら取り込み窓を閉じる（2026-10-30 利用者「各取り込み終わったら停止してほしい」）。

それまでは機種一覧で「未取り込みなし」になっても自動取り込みがONのまま、窓もサイトのページを開いたままだった。
"""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from browser_import import FINISHED_NAME, _Bridge, close_when_finished, take_finished_message

ALL_DONE = json.dumps({'url': None, 'reason': 'all_done', 'message': '未取り込みの機種・グラフはありません。'}, ensure_ascii=False)
NEXT = json.dumps({'url': 'https://meruhenworld.pt.teramoba2.com/nagamachiminami/standlist_slot?kind_code=21',
                   'reason': 'table', 'machine': '甲機', 'message': '次：甲機'}, ensure_ascii=False)


class CloseWhenFinishedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.bridge = _Bridge(self.folder / 'test.db', self.folder, 'x')
        self.destroyed = []
        self.window = types.SimpleNamespace(destroy=lambda: self.destroyed.append(True))
        self.answer = ALL_DONE
        patcher = mock.patch.object(_Bridge, '_next_unimported_machine', lambda bridge, raw: self.answer)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, auto):
        return json.loads(self.bridge.next_unimported_machine(json.dumps({'store': 'nagamachiminami', 'machines': [], 'auto': auto})))

    def close(self):
        return close_when_finished(self.bridge, self.window, self.folder)

    def test_auto_capture_that_found_nothing_left_turns_off_and_closes(self):
        self.bridge.set_auto_capture(True, 3.5)
        self.assertEqual(self.ask(True)['reason'], 'all_done', '画面へ返す結果は変えない')
        self.assertFalse(self.bridge.get_auto_capture()['enabled'])
        self.assertIn('自動取り込みを停止しました', self.bridge.get_auto_capture()['message'])
        self.assertTrue(self.close())
        self.assertEqual(self.destroyed, [True])
        self.assertEqual(take_finished_message(self.folder), '未取り込みの機種・グラフはありません。（自動取り込みを停止しました）')
        self.assertIsNone(take_finished_message(self.folder), '知らせは1回で消える')

    def test_manual_next_or_auto_off_or_remaining_machines_do_not_close(self):
        self.bridge.set_auto_capture(True, 3.5)
        self.ask(False)                       # 手動の「次へ」
        self.answer = NEXT
        self.ask(True)                        # まだ残っている
        self.assertTrue(self.bridge.get_auto_capture()['enabled'])
        self.bridge.set_auto_capture(False, 3.5)
        self.answer = ALL_DONE
        self.ask(True)                        # 自動取り込みがOFFのあと
        self.assertIsNone(self.bridge._completed)
        self.assertFalse(self.close())
        self.assertEqual(self.destroyed, [])
        self.assertFalse((self.folder / FINISHED_NAME).exists())

    def test_waits_for_running_saves_and_restart_clears_the_reason(self):
        self.bridge.set_auto_capture(True, 3.5)
        self.ask(True)
        running = types.SimpleNamespace(poll=lambda: None)
        self.bridge._children = [running]
        self.assertFalse(self.close(), '保存の処理が動いている間は閉じない')
        self.bridge._children = []
        self.bridge._pending_advance = ({'message': '保存しました'}, None, None, None)
        self.assertFalse(self.close(), '保存結果の反映待ちの間は閉じない')
        self.bridge._pending_advance = None
        self.bridge.set_auto_capture(True, 3.5)
        self.assertIsNone(self.bridge._completed, 'もう一度ONにしたら閉じる理由は消える')
        self.assertFalse(self.close())
        self.assertEqual(self.destroyed, [])

    def test_manual_use_after_auto_finished_keeps_the_window_open(self):
        """自動の完了時に保存の処理が残っていて、その間に手動で使い始めたら、あとで窓を閉じない（2026-10-31）。"""
        running = types.SimpleNamespace(poll=lambda: None)
        self.bridge.set_auto_capture(True, 3.5)
        self.ask(True)
        self.bridge._children = [running]
        self.assertFalse(self.close())
        self.ask(False)                       # 手動の「次へ」
        self.bridge._children = []
        self.assertFalse(self.close(), '手動の「次へ」のあとは閉じない')

        self.bridge.set_auto_capture(True, 3.5)
        self.ask(True)
        self.bridge._children = [running]
        started = []
        with mock.patch('subprocess.Popen', lambda *args, **kwargs: started.append(args) or running):
            self.bridge._spawn_unlocked('table', '{}')  # 手動の保存を始める
        self.assertEqual(len(started), 1)
        self.bridge._children = []
        self.assertFalse(self.close(), '手動の保存が終わっても閉じない')
        self.assertEqual(self.destroyed, [])
        self.assertFalse((self.folder / FINISHED_NAME).exists())


class TwoWindowNoticeTests(unittest.TestCase):
    """メルヘンの取り込み窓を2つ同時に開いても、完了の知らせが窓ごとに分かれる（2026-11-24 利用者「窓ごとに知らせるようにして」）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def finish(self, window_id, message):
        bridge = _Bridge(self.folder / 'test.db', self.folder, 'x')
        bridge._completed = message
        window = types.SimpleNamespace(destroy=lambda: None)
        self.assertTrue(close_when_finished(bridge, window, self.folder, window_id))

    def test_each_window_reads_only_its_own_notice(self):
        import browser_import
        self.finish('aaa111', '上から：未取り込みの機種・グラフはありません。（自動取り込みを停止しました）')
        self.finish('bbb222', '下から：未取り込みの機種・グラフはありません。（自動取り込みを停止しました）')
        self.assertNotEqual(browser_import.finished_path(self.folder, 'aaa111'), browser_import.finished_path(self.folder, 'bbb222'))
        # 下からの窓（後に開いた窓）の後処理が先に走っても、上からの窓の知らせを取らない
        self.assertTrue(take_finished_message(self.folder, 'bbb222').startswith('下から'))
        self.assertIsNone(take_finished_message(self.folder, 'bbb222'))
        self.assertTrue(take_finished_message(self.folder, 'aaa111').startswith('上から'))
        # 窓IDなし（従来の1つのファイル）とは混ざらない
        self.assertIsNone(take_finished_message(self.folder))
        self.assertFalse((self.folder / FINISHED_NAME).exists())

    def test_bad_window_id_falls_back_to_the_shared_file(self):
        import browser_import
        self.assertEqual(browser_import.finished_path(self.folder, '../x'), self.folder / FINISHED_NAME)
        self.assertEqual(browser_import.finished_path(self.folder, None), self.folder / FINISHED_NAME)

    def test_app_and_window_pass_the_window_id(self):
        import browser_import
        app = (Path(browser_import.__file__).resolve().parent / 'app.py').read_text(encoding='utf-8')
        block = app[app.index('    def open_browser_import():'):app.index("watch_capture_window(process, 'メルヘン'")]
        self.assertIn('window_id = uuid.uuid4().hex[:12]', block)
        # 起動コマンドは個別・一括で共通の meruhen_browser_command に切り出した（2026-11-28）
        self.assertIn('command = meruhen_browser_command(window_id)', block)
        command = app[app.index('def meruhen_browser_command(window_id):'):app.index('def source_version(')]
        self.assertEqual(command.count("str(ROOT / 'reports'), window_id]"), 2, 'ソース起動・exe起動の両方で渡す')
        self.assertIn('browser_import.take_finished_message(DATA_DIR, window_id)', block)
        source = Path(browser_import.__file__).read_text(encoding='utf-8')
        session = source[source.index('def run_session('):source.index('def backup_after_session(')]
        # 窓を開いたときに消すのは同じ窓IDの古い知らせだけ（2つ目の窓が1つ目の未読の知らせを消さない）
        self.assertIn('data_dir = Path(db_path).parent', session)
        self.assertIn('take_finished_message(data_dir, window_id)', session)
        self.assertIn('close_when_finished(bridge, window, Path(db_path).parent, window_id)', session)
        self.assertIn('run_session(db_arg, reports_arg, positional[2] if len(positional) > 2 else None,', source)


class MeruhenDbWaitTests(unittest.TestCase):
    """メルヘンの取り込み窓と保存の処理は、本体DBの書き込み・写しを10秒待つ（2026-11-24 利用者「保存の待ちは10秒」）。"""

    def test_every_store_in_the_meruhen_window_waits_ten_seconds(self):
        import re
        import browser_import
        self.assertEqual(browser_import.MERUHEN_DB_WAIT, 10.0)
        source = Path(browser_import.__file__).read_text(encoding='utf-8')
        opens = re.findall(r'\bStore\(([^)]*)\)', source)
        self.assertGreaterEqual(len(opens), 10)
        self.assertTrue(all('timeout=MERUHEN_DB_WAIT' in args for args in opens), opens)

    def test_store_timeout_waits_for_another_writer(self):
        import sqlite3
        import threading
        import time
        from core import Store
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as tmp:
            path = Path(tmp) / 'database.sqlite3'
            Store(path, recording=False).close()
            holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            holder.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError):
                Store(path, recording=False, timeout=0.2)   # 待ちが短いと、ほかの書き込み中は開けない
            release = threading.Timer(0.8, lambda: holder.execute('COMMIT'))
            release.start()
            started = time.monotonic()
            try:
                store = Store(path, recording=False, timeout=5.0)   # 待ちが長ければ、相手が終わるのを待って開ける
                store.close()
            finally:
                release.join()
                holder.close()
            self.assertGreaterEqual(time.monotonic() - started, 0.5)


if __name__ == '__main__':
    unittest.main()
