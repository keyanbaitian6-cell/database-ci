"""P’s CUBE（PC）：取り込み日の日付タブが無い機種（新台・入れ替え）を、自動取り込みが飛ばして次の機種へ進む試験（2026-10-22）。

以前は、自動取り込みが「表示中の日（サイトが選んだ最新のタブ）が取り込み日と違う」ので読み取りの前に待ち続け、保存側（Store）の
飛ばす処理まで届かなかった。判定（pscube_auto_probe.js）と読み取り（pscube_capture.js）の出力は、模擬ページで実際に動かした結果
（`database_android/test/fixtures/pscube_absent_tab_auto.json`。`tool/test_pscube_absent_tab_auto.mjs` が今の生成JSと一致するか確かめる）。
`AutoPilot.tick`（判定→決定→取り込み開始）→ `submit_capture`（取り込み画面の保存と同じ処理、一時DB）→ `finished` → 次のURL、を通す。
Android（`test/pscube_auto_absent_tab_test.dart`）も同じ出力で確かめる。実サイトには接続しない。
"""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from auto_capture import AutoCapture
from pscube_import import ABSENT_DAYS_KEY, AutoPilot, PscubeStore, _machine_key, submit_capture
from test_pscube_auto import PROBE, Clock, FakeWindow

FIXTURE = Path(__file__).resolve().parent.parent / 'database_android' / 'test' / 'fixtures' / 'pscube_absent_tab_auto.json'
SCENES = {s['name']: s for s in json.loads(FIXTURE.read_text(encoding='utf-8'))['scenes']}
# 取り込み日に選べる直近7日を、模擬ページの日付（10/19が今の営業日）に固定する（試験を流す日に左右されない）。
RECENT = [(date(2026, 10, 19) - timedelta(days=i)).isoformat() for i in range(7)]
NEW_KEY = _machine_key({'store': 'c740601', 'rate': '20', 'machine': 'L新台'})


class AbsentTabAutoTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('pscube_import.recent_business_days', return_value=RECENT)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fresh()

    def fresh(self):
        """一時DBと自動取り込みを作り直す（場面ごとに前の場面の状態を持ち越さない）。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / 'pscube.sqlite3'
        self.export = Path(tmp.name) / 'pscube-viewer.json'
        self.clock = Clock()
        self.window = FakeWindow()
        self.pilot = AutoPilot(self.window, PROBE, auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))

    def start(self, day):
        """「上から取り込む」（取り込み日つき）。取り込み画面のカードと同じ呼び出し。"""
        self.assertTrue(self.pilot.configure(True, 10, day, 'top')['enabled'])

    def tick(self, scene):
        """ページの読み込み完了 → 間隔を待つ → 判定。取り込みを始めたら True。"""
        self.pilot.loaded()
        self.window.probe = scene['probe']
        self.clock.now += 10
        before = self.window.calls.count('start')
        self.pilot.tick()
        return self.window.calls.count('start') > before

    def save(self, scene):
        """ページ内の読み取りの結果を保存する（取り込み画面の `submit_page` と同じ：保存 → finished）。"""
        try:
            result = submit_capture(self.db, self.export, self.pilot, json.dumps(scene['capture']), scene['url'])
        except Exception as error:
            self.pilot.finished(error=str(error))
            raise
        self.pilot.finished(result=result)
        return result

    def stored(self):
        """保存されている記録（機種, 台, 日）と、日単位の「タブなし」の印。"""
        store = PscubeStore(self.db)
        try:
            records = sorted((json.loads(r[0])['machine'], json.loads(r[0])['rack'], json.loads(r[0])['day'])
                             for r in store.db.execute('SELECT payload FROM records'))
            row = store.db.execute('SELECT value FROM state WHERE key=?', (ABSENT_DAYS_KEY,)).fetchone()
            return records, sorted(map(tuple, json.loads(row[0]))) if row else []
        finally:
            store.close()

    def test_a_missing_day_tab_reaches_the_store_skip_and_the_next_machine_is_saved(self):
        for name in ('only_newer_tab', 'gap_in_tabs'):
            with self.subTest(name):
                self.fresh()
                scene, index, following = SCENES[name], SCENES['index'], SCENES['next_machine']
                self.start('2026-10-18')
                # 機種一覧 → 取り込み日のタブで、一覧の最初の機種（新台）を開く。
                self.assertTrue(self.tick(index))
                self.assertEqual(self.pilot.state()['message'], 'ON・取り込み中（機種一覧）')
                first = self.save(index)
                self.assertEqual(first['next_url'].split('#')[0], scene['url'].split('#')[0])
                self.assertTrue(first['next_url'].endswith('#0;0;20261018;0;cd_dai;1;0;0'))
                # 新台の全台一覧：サイトは10/19を選ぶ。待たずに読み取りを始める。
                self.assertTrue(self.tick(scene), self.pilot.state()['message'])
                self.assertIn('10/18の日付タブが無い機種か確かめています', self.pilot.state()['message'])
                result = self.save(scene)
                self.assertEqual(result['saved'], 0)
                self.assertIn('L新台は10/18の日付タブがサイトにありません', result['skipped'])
                self.assertIn('保存せずに飛ばしました', self.pilot.state()['message'])
                self.assertEqual(result['next_url'], following['url'], '次の機種を10/18のタブで開く')
                self.assertEqual(result['remaining'], 1)
                self.assertEqual(self.stored(), ([], [(NEW_KEY, '2026-10-18')]), '保存0件・その機種のその日だけ印')
                self.assertTrue(self.pilot.state()['enabled'], '自動取り込みは続く')
                # 同じページに戻っても、二度は読み取らない。
                self.assertFalse(self.tick(scene))
                # 次の機種：10/18のタブで保存し、台別ページへ進む。
                self.assertTrue(self.tick(following))
                self.assertEqual(self.pilot.state()['message'], 'ON・取り込み中（全台一覧）')
                saved = self.save(following)
                self.assertEqual(saved['saved'], 1)
                self.assertEqual(saved['next_url'], following['capture']['records'][0]['detail_url'])
                self.assertEqual(self.stored()[0], [('ﾏｲｼﾞｬｸﾞﾗｰV', 2001, '2026-10-18')])
                self.assertEqual(self.stored()[1], [(NEW_KEY, '2026-10-18')], '別の機種の保存では印を外さない')

    def test_other_pages_wait_and_never_skip_or_save(self):
        cases = {
            'target_tab_not_selected': '全台一覧の日付タブを10/18に合わせてください',
            'target_newer_than_tabs': '全台一覧の日付タブを10/19に合わせてください',
            'no_tabs': '全台一覧の表示待ち',
            'challenge': '人間確認・同意の画面',
            'rack_other_day': 'このページを10/18に合わせてください',
        }
        for name, message in cases.items():
            with self.subTest(name):
                self.fresh()
                scene = SCENES[name]
                store = PscubeStore(self.db)
                store.import_page(SCENES['index']['capture'], SCENES['index']['url'])
                store.close()
                self.start(scene['target_day'])
                self.assertFalse(self.tick(scene), '読み取りを始めない')
                self.assertIn(message, self.pilot.state()['message'])
                self.assertTrue(self.pilot.state()['enabled'], '待つだけ。止めない')
                self.assertEqual(self.stored(), ([], []))
                # 手で「未取得を取り込む」を押しても、保存側が理由を出して止め、印も付けない。
                if 'capture' in scene:
                    with self.assertRaises(ValueError):
                        submit_capture(self.db, self.export, self.pilot, json.dumps(scene['capture']), scene['url'])
                    self.assertEqual(self.stored(), ([], []))


if __name__ == '__main__':
    unittest.main()
