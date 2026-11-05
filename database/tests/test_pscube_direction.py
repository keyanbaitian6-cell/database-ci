"""P’s CUBE（PC）：「上から／下から取り込む」の向きが、開始から何ページ進んでも変わらないことの試験。

2026-10-06、利用者「下から取り込むと、最初は下側なのに、次のページから上側の順に変わる」。
向きを直接呼ぶ試験だけでは足りないため、開始ボタンと同じ呼び出し（`AutoPilot.configure`）から、
自動の判定（`tick`）→ 保存（`submit_capture`、取り込み画面の保存と同じ処理）→ 保存結果の次のURLを開く、を
最後のページまで繰り返し、毎回の行き先を確かめる。合成の機種一覧 [A, B, C, D]、各2台（実サイト・実データは使わない）。
"""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from auto_capture import AutoCapture
from pscube_import import AutoPilot, PscubeStore, ROOT_URL, recent_business_days, submit_capture
from test_pscube_auto import PROBE, Clock, FakeWindow

INDEX = ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2'
NAMES = ('A', 'B', 'C', 'D')
RACKS = {'A': (101, 102), 'B': (201, 202), 'C': (301, 302), 'D': (401, 402)}


def table_url(name):
    return ROOT_URL + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu={quote(name)}'


def label(url):
    """URLを試験の読みやすい名前に：'一覧'・'A表'・'101'・None（終わり）。"""
    if url is None:
        return None
    if 'nc-v03-001' in url:
        return '一覧'
    if 'nc-v05-011' in url:
        # 取り込み日を指定しているときは、その日のタブで開く#以降が付く（table_url_for_day）。
        return next(n for n in NAMES if table_url(n) == url.split('#')[0]) + '表'
    return url.split('cd_dai=')[1].split('#')[0]


def order(names, top_first=True):
    """機種の並び順に、表→台番号の小さい順。期待する行き先の列。"""
    seq = []
    for name in names if top_first else reversed(names):
        seq += [name + '表'] + [str(r) for r in RACKS[name]]
    return seq


class Site:
    """合成のP’s CUBE：URLから、取り込みスクリプトが返すのと同じ形のページを作る。"""

    def __init__(self, day, time='23:12'):
        self.day, self.time = day, time
        self.no_hits = set()

    def machine(self, name, listed=True):
        return {'store': 'c740601', 'rate': '20', 'machine': name,
                'expected_count': len(RACKS[name]) if listed else None, 'url': table_url(name)}

    def record(self, name, rack, day=None):
        day = day or self.day
        hits = 0 if rack in self.no_hits else 3
        return {'store': 'c740601', 'rate': '20', 'machine': name, 'rack': rack, 'day': day,
                'bb': hits, 'rb': hits and 1, 'at_art': 0, 'games': 2000, 'my': 100,
                'observed_at': f'{self.day}T{self.time}:00+09:00',
                'detail_url': ROOT_URL + f'cgi-bin/nc-v06-001.php?cd_dai={rack}#{day.replace("-", "")}',
                'graph': {'kind': 'overview', 'zero_y': 10, 'points': [[0, 10], [1, 8]]}}

    def page(self, url):
        data = {'format': 'pscube-viewer', 'version': 1, 'source_url': url, 'machines': [], 'records': []}
        kind = label(url)
        if kind == '一覧':
            data['machines'] = [self.machine(n) for n in NAMES]
        elif kind.endswith('表'):
            name = kind[:-1]
            data['machines'] = [self.machine(name, False)]
            data['records'] = [self.record(name, r) for r in RACKS[name]]
        else:
            rack = int(kind)
            name = next(n for n, racks in RACKS.items() if rack in racks)
            data['machines'] = [self.machine(name, False)]
            data['records'] = [self.record(name, rack, (date.fromisoformat(self.day) - timedelta(days=i)).isoformat())
                               for i in range(7)]
        return data


class DirectionAcrossPagesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / 'pscube.sqlite3'
        self.export = Path(tmp.name) / 'pscube-viewer.json'
        self.day = recent_business_days()[1]
        self.site = Site(self.day)
        self.clock = Clock()
        self.window = FakeWindow()
        self.pilot = AutoPilot(self.window, PROBE, auto=AutoCapture(clock=self.clock, minimum=5, maximum=60, default=10))
        # 取り込む順を確かめる試験なので、10ページごとの休憩（2026-11-06、test_pscube_auto で確かめる）は入れない。
        self.pilot.REST_EVERY_PAGES = 10 ** 6

    def seed_index(self):
        """前回の取り込みで機種一覧だけ保存済み。"""
        store = PscubeStore(self.db)
        try:
            store.import_page(self.site.page(INDEX), INDEX)
        finally:
            store.close()

    # 画面の操作（取り込み画面のカードのボタンと同じ呼び出し）
    def press_start(self, direction, day=''):
        """「上から取り込む」「下から取り込む」：set_auto_capture(true, 秒, 日付の選択, 向き)。"""
        state = self.pilot.configure(True, 10, day, direction)
        self.assertTrue(state['enabled'])
        self.assertEqual(state['direction'], direction)

    def press_auto_toggle(self, enabled):
        """「自動取り込み：ON/OFF」：向きは送らない（null）。"""
        return self.pilot.configure(enabled, 10, '', None)

    def save(self, url):
        result = submit_capture(self.db, self.export, self.pilot, self.site.page(url), url)
        self.pilot.finished(result=result)
        return result

    def auto_step(self, url):
        """1ページ：読み込み完了 → 間隔を待つ → 判定で取り込み開始 → 保存 → 次のURL。"""
        self.pilot.loaded()
        self.window.probe = {'ready': True, 'busy': False, 'signature': url, 'day': None,
                             'kind': '機種一覧' if label(url) == '一覧' else 'ページ'}
        self.clock.now += 10
        before = self.window.calls.count('start')
        self.pilot.tick()
        self.assertEqual(self.window.calls.count('start'), before + 1, f'{label(url)}の取り込みが始まらない')
        return self.save(url)

    def walk(self, start, step, limit=40):
        """保存のたびに返る次のURLを毎回記録し、最後（次が無い）まで進む。向きも毎回確かめる。"""
        visited, url = [], start
        self.visited_urls = []
        for _ in range(limit):
            visited.append(label(url))
            self.visited_urls.append(url)
            result = step(url)
            self.assertEqual(result['direction'], self.expected_direction, f'{label(url)}の保存後に向きが変わった')
            self.assertEqual(self.pilot.direction, self.expected_direction)
            url = result['next_url']
            if url is None:
                return visited
        self.fail('終わらない：' + ' → '.join(visited))

    # 自動取り込み
    def test_auto_from_the_top_goes_a_b_c_d_on_every_page(self):
        self.expected_direction = 'top'
        self.press_start('top')
        self.assertEqual(self.walk(INDEX, self.auto_step), ['一覧'] + order(NAMES))
        self.assertFalse(self.pilot.state()['enabled'], '最後まで取ったら止まる')

    def test_auto_from_the_bottom_goes_d_c_b_a_on_every_page(self):
        self.expected_direction = 'bottom'
        self.press_start('bottom')
        self.assertEqual(self.walk(INDEX, self.auto_step), ['一覧'] + order(NAMES, top_first=False))
        self.assertIn('下から', ''.join(r['message'] for r in self.window.rendered if r.get('message')),
                      '途中の状態の表示に向きが出る')
        self.assertFalse(self.pilot.state()['enabled'])
        self.assertEqual(self.pilot.direction, 'bottom', '止まったあとも向きを既定値（上から）へ戻さない')

    def test_bottom_keeps_its_order_when_targets_are_skipped(self):
        """当たり0回の台（台別ページは取らない）、今夜すでに取り終えた機種は飛ばしても、残りは下から。"""
        self.site.no_hits = {401, 202}
        # 今夜すでにC機を表・台別まで取り終えている（同じ時刻のデータ）。
        store = PscubeStore(self.db)
        store.import_page(self.site.page(INDEX), INDEX)
        for url in [table_url('C')] + [self.site.record('C', r)['detail_url'] for r in RACKS['C']]:
            store.import_page(self.site.page(url), url)
        store.close()
        self.expected_direction = 'bottom'
        self.press_start('bottom')
        self.assertEqual(self.walk(INDEX, self.auto_step), ['一覧', 'D表', '402', 'B表', '201', 'A表', '101', '102'])

    def test_bottom_keeps_its_order_after_a_failed_page_and_a_restart_with_the_auto_button(self):
        self.expected_direction = 'bottom'
        self.press_start('bottom')
        self.assertEqual(label(self.auto_step(INDEX)['next_url']), 'D表')
        # D表の保存に失敗（全台が表示されていない）→ 自動の失敗として数える。向きはそのまま。
        bad = self.site.page(table_url('D'))
        bad['records'] = bad['records'][:1]
        with self.assertRaises(ValueError):
            submit_capture(self.db, self.export, self.pilot, bad, table_url('D'))
        self.pilot.finished(error='全台を表示してください')
        self.assertEqual(self.pilot.direction, 'bottom')
        # いったんOFF→「自動取り込み」ボタンでON（向きは送られない）。下からのまま続く。
        self.press_auto_toggle(False)
        self.press_auto_toggle(True)
        self.assertEqual(self.walk(table_url('D'), self.auto_step), order(NAMES, top_first=False))

    def test_bottom_with_an_import_day_keeps_its_order(self):
        """日付指定取り込み：最初の機種（一覧の下）で基準の時刻を確かめ、そのあとも下から。"""
        self.expected_direction = 'bottom'
        self.press_start('bottom', day=self.day)
        self.assertEqual(self.pilot.target_day, self.day)
        self.assertEqual(self.walk(INDEX, self.auto_step), ['一覧'] + order(NAMES, top_first=False))
        tables = [url for url in self.visited_urls if 'nc-v05-011' in url]
        self.assertEqual(len(tables), len(NAMES))
        compact = self.day.replace('-', '')
        self.assertTrue(all(url.endswith(f'#0;0;{compact};0;cd_dai;1;0;0') for url in tables),
                        '全台一覧は取り込み日のタブで開く：' + ' '.join(tables))

    def test_bottom_from_a_table_page_in_the_middle(self):
        """一覧ではなくB機の表を開いた状態で「下から」：今のページを保存した後は、下の未取得（D）から。"""
        self.expected_direction = 'bottom'
        self.seed_index()
        self.press_start('bottom')
        self.assertEqual(self.walk(table_url('B'), self.auto_step),
                         ['B表', 'D表', '401', '402', 'C表', '301', '302', '201', '202', 'A表', '101', '102'])

    # 手動の取り込み（自動がOFFの間の「未取得を取り込む」）
    def manual_step(self, url):
        self.assertFalse(self.pilot.state()['enabled'])
        return self.save(url)

    def test_manual_after_choosing_bottom_goes_d_c_b_a(self):
        self.expected_direction = 'bottom'
        self.press_start('bottom')
        self.press_auto_toggle(False)
        self.assertEqual(self.pilot.state()['direction'], 'bottom', 'OFFにしても向きは残る（カードの枠も下から）')
        self.assertEqual(self.walk(INDEX, self.manual_step), ['一覧'] + order(NAMES, top_first=False))

    def test_manual_without_choosing_goes_from_the_top(self):
        self.expected_direction = 'top'
        self.assertEqual(self.walk(INDEX, self.manual_step), ['一覧'] + order(NAMES))

    def test_manual_bottom_from_the_middle_continues_upward_then_wraps_to_the_bottom(self):
        """手動：保存したページの次から（下からなら上の機種へ）。最後まで来たら取りこぼした下の機種へ回る。"""
        self.expected_direction = 'bottom'
        self.seed_index()
        self.press_start('bottom')
        self.press_auto_toggle(False)
        self.assertEqual(self.walk(table_url('B'), self.manual_step),
                         ['B表', '201', '202', 'A表', '101', '102', 'D表', '401', '402', 'C表', '301', '302'])

    def test_card_shows_the_direction_also_while_auto_is_off(self):
        from pscube_import import overlay_script
        card = overlay_script('CAPTURE', INDEX)
        self.assertIn("const chosen = b === (state.direction === 'bottom' ? bottomButton : topButton);", card)
        self.assertNotIn("b.style.outline = !autoEnabled ? ''", card)
        self.assertIn("startFrom('bottom')", card)
        self.assertIn('set_auto_capture(!autoEnabled, Number(seconds.value), daySelect.value, null)', card,
                      '「自動取り込み」ボタンは向きを送らない（下からのまま）')
        self.assertEqual(json.loads(json.dumps(self.pilot.state()))['direction'], 'top')


if __name__ == '__main__':
    unittest.main()
