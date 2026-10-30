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


if __name__ == '__main__':
    unittest.main()
