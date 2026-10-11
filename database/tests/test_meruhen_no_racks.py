"""Meruhen PC：サイトが機種の表の代わりに「該当する台情報が見つかりませんでした」を出す機種は、
その日は飛ばして次の機種へ進む（2026-10-11 利用者「その仕様に両方作り替えて」）。

長町南の10/10、下から取り込む途中で Sハイパーラッシュ SLC8 の表が「台情報なし」になり、
アプリはその機種を「未取込」として案内し続けて先へ進めなかった。Android版は
`test/meruhen_no_racks_test.dart`、画面のJSは `tool/test_meruhen_no_racks_browser.mjs`。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

from browser_import import NO_RACKS_PATTERN, _Bridge, no_racks_notice, recent_days

HOST = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
DAY = '2026-10-10'


class NoRacksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.bridge = _Bridge(self.folder / 'test.db', self.folder, 'x')
        self.machines = [dict(name=name, url=f'{HOST}/standlist_slot?kind_code=21&machine_name={name}', count=1)
                         for name in ('S武装神姫PF', 'SﾊｲﾊﾟｰﾗｯｼｭSLC8', 'S押忍!番長ZERO PC1')]

    def ask(self, **extra):
        payload = {'store': 'nagamachiminami', 'day': DAY, 'machines': self.machines, **extra}
        return json.loads(self.bridge.next_unimported_machine(json.dumps(payload)))

    def skip(self, **extra):
        payload = {'store': 'nagamachiminami', 'day': DAY, 'machine': 'SﾊｲﾊﾟｰﾗｯｼｭSLC8', 'rack': None, **extra}
        return json.loads(self.bridge.skip_machine_without_racks(json.dumps(payload, ensure_ascii=False)))

    def test_the_site_wording(self):
        for text in ('個別台情報一覧\n該当する台情報が見つかりませんでした。', '該当する台情報がありません'):
            self.assertTrue(NO_RACKS_PATTERN.search(text), text)
        self.assertFalse(NO_RACKS_PATTERN.search('台番号 BB RB 総回転数'))
        self.assertEqual(no_racks_notice(DAY, 'SﾊｲﾊﾟｰﾗｯｼｭSLC8'),
                         '10/10のSﾊｲﾊﾟｰﾗｯｼｭSLC8は、サイトに台情報がありません（該当する台情報が見つかりませんでした）。'
                         'この日は飛ばして、次の機種へ進みます。')

    def test_the_machine_is_skipped_for_that_day_only(self):
        self.bridge.set_target_day(recent_days()[0], 'bottom')
        self.bridge.set_target_day('', None)
        self.assertEqual(self.ask()['machine'], 'S押忍!番長ZERO PC1', '下から：一番下の機種')
        # 一番下の機種は済んだとして、次（ハイパーラッシュ）の表が「台情報なし」だった。
        result = self.skip()
        self.assertIn('database_next_machine=1', result['url'])
        self.assertIn(f'database_day={DAY}', result['url'])
        self.assertEqual(unquote(result['url'].split('database_after=')[1]), 'SﾊｲﾊﾟｰﾗｯｼｭSLC8',
                         '手動なら、戻った一覧でこの機種の次から探す')
        self.assertIn('この日は飛ばして', result['message'])
        nxt = self.ask(after='SﾊｲﾊﾟｰﾗｯｼｭSLC8')
        self.assertEqual(nxt['machine'], 'S武装神姫PF', '飛ばした機種の次へ進む')
        # 自動（印なし）でも、一覧を最初から見直しても、その日は戻らない。
        self.machines = self.machines[1:]          # 武装神姫は済んだとして一覧から外す
        self.assertNotEqual(self.ask().get('machine'), 'SﾊｲﾊﾟｰﾗｯｼｭSLC8')
        self.assertEqual(self.ask(after='S押忍!番長ZERO PC1').get('machine'), 'S押忍!番長ZERO PC1',
                         '取りこぼしを見直しても、飛ばした機種には戻らない')
        # 別の日は飛ばさない（その日のデータが無いだけ）。
        self.bridge.set_target_day(None, 'top')
        self.assertEqual(self.ask(day='2026-10-09')['machine'], 'SﾊｲﾊﾟｰﾗｯｼｭSLC8')
        # 開き直せば（新しい画面）もう一度見る：サイトが一時的に空を返しただけなら取り込める。
        fresh = _Bridge(self.folder / 'test.db', self.folder, 'x')
        payload = dict(store='nagamachiminami', day=DAY, machines=self.machines)
        self.assertEqual(json.loads(fresh.next_unimported_machine(json.dumps(payload)))['machine'], 'SﾊｲﾊﾟｰﾗｯｼｭSLC8')

    def test_spacing_and_width_do_not_matter(self):
        self.skip(machine='Sﾊｲﾊﾟｰﾗｯｼｭ SLC8')
        self.machines = [m for m in self.machines if m['name'] == 'SﾊｲﾊﾟｰﾗｯｼｭSLC8']
        self.assertEqual(self.ask()['reason'], 'all_done')

    def test_unknown_pages_are_not_skipped(self):
        for bad in (dict(store='other'), dict(day='2026-02-30'), dict(day=None), dict(machine='')):
            result = self.skip(**bad)
            self.assertIsNone(result['url'], bad)
            self.assertIn('飛ばせませんでした', result['message'])
        self.assertEqual(self.bridge._no_racks, set())
        self.assertEqual(json.loads(self.bridge.skip_machine_without_racks('x'))['url'], None)

    def test_manual_skip_continues_from_the_list_and_auto_does_not_set_manual_continuation(self):
        self.bridge._manual_continuation = False
        self.skip()
        self.assertTrue(self.bridge._manual_continuation, '手動：戻った一覧で次の機種を探す')
        self.bridge.set_auto_capture(True, 3.5)
        self.skip(machine='S武装神姫PF')
        self.assertFalse(self.bridge._manual_continuation, '自動：移動は自動取り込みが受け持つ')

    def test_auto_capture_skips_and_returns_to_the_list(self):
        """自動取り込み：確認（probe）が「台情報なし」なら保存せず、機種一覧へ戻る。"""
        self.bridge.set_auto_capture(True, 3.5)
        window = mock.Mock()
        page = f'{HOST}/standlist_slot/?kind_code=21&machine_name=x&target_date={DAY}'
        window.get_current_url.return_value = page
        probe = dict(kind='no_racks', url=page, store='nagamachiminami', day=DAY,
                     machine='SﾊｲﾊﾟｰﾗｯｼｭSLC8', rack=None)
        scripts = []

        def evaluate(script):
            scripts.append(script)
            return probe if 'AutoProbe' in script else True
        window.evaluate_js.side_effect = evaluate
        self.bridge._window = window
        self.bridge._overlay_ready.set()
        self.bridge._auto._deadline = 0
        with mock.patch.object(self.bridge, '_spawn') as spawn:
            self.bridge._auto_tick()
        spawn.assert_not_called()
        advance = [s for s in scripts if '__databaseAutoAdvance(' in s]
        self.assertEqual(len(advance), 1, scripts)
        self.assertIn('rack_info_kt', advance[0])
        self.assertIn(('nagamachiminami', DAY, 'SﾊｲﾊﾟｰﾗｯｼｭSLC8'), self.bridge._no_racks)
        self.assertIn('この日は飛ばして', self.bridge.get_auto_capture()['message'])


if __name__ == '__main__':
    unittest.main()
