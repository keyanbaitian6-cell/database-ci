"""バラエティの🌈のタブ（PC、2026-10-11 利用者「バラエティの機種一覧をpcで表示させて、この🌈マークをつけられる
ようにもしてほしい。そのタブかページを作って」「機種一覧名はとりあえず最新の機種一覧からとって表示させておけば
いいよ。入れ替えとかで変わったらその都度書き換えて」）。仕様は ../RAINBOW.md。"""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

from core import Store
from variety_rainbow import SORTS, build_variety_tab, variety_rows

STORE = 'nagamachiminami'


def row(rack, machine, day, games=3000, **extra):
    return dict(store=STORE, kind_code=21, day=day, machine=machine, rack=rack,
                games=games, bb=10, rb=5, max_hold=1500, **extra)


class VarietyRainbowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'database.sqlite3'
        db = Store(self.path)
        rows = []
        # 10/9：主力4台、バラエティ ハナハナ2台（50・51）、旧機種（60）。
        for day, sixty in (('2026-10-09', '旧バラエティ'), ('2026-10-10', '新バラエティ')):
            rows += [row(rack, '主力', day) for rack in (1, 2, 3, 4)]
            rows += [row(50, 'ハナハナ', day, games=5000), row(51, 'ハナハナ', day, games=800), row(60, sixty, day)]
        # 10/10 に入れ替えで入った 61 番台（10/9 は記録なし）。
        rows.append(row(61, '新バラエティ', '2026-10-10'))
        db.save(rows)
        db.set_rainbow(STORE, '2026-10-09', 50, True)
        db.close()

    def test_rows_come_from_the_latest_lineup(self):
        latest = variety_rows(self.path, STORE, '2026-10-10')
        self.assertEqual([(r['rack'], r['machine']) for r in latest],
                         [(50, 'ハナハナ'), (51, 'ハナハナ'), (60, '新バラエティ'), (61, '新バラエティ')],
                         '1〜3台の機種だけ。主力（4台）は入れない')
        fifty = latest[0]
        self.assertEqual((fifty['games'], fifty['rainbow'], fifty['prev_rainbow'], fifty['rainbow_count']),
                         (5000, False, '2026-10-09', 1))
        # 前の日を選んでも、並べる台・機種名は最新（入れ替え後）のまま。その日の数値と🌈を出す。
        older = {r['rack']: r for r in variety_rows(self.path, STORE, '2026-10-09', latest='2026-10-10')}
        self.assertEqual(list(older), [50, 51, 60, 61])
        self.assertTrue(older[50]['rainbow'])
        self.assertEqual((older[60]['machine'], older[60]['day_machine']), ('新バラエティ', '旧バラエティ'))
        self.assertEqual((older[61]['recorded'], older[61]['games']), (False, None), 'その日の記録が無い台')
        # 並べ方：最終🌈の古い順（一度も無い台が先、その日に付いた台は最後）。
        ordered = sorted(older.values(), key=SORTS['最終🌈の古い順'])
        self.assertEqual([r['rack'] for r in ordered][-1], 50)

    def test_rainbow_counts(self):
        db = Store(self.path)
        try:
            db.set_rainbow(STORE, '2026-10-10', 50, True)
            self.assertEqual(db.rainbow_counts(STORE, '2026-09-11', '2026-10-10'), {50: 2})
            self.assertEqual(db.rainbow_counts(STORE, '2026-10-10', '2026-10-10'), {50: 1})
        finally:
            db.close()

    def test_tab_toggles_with_one_click_and_saves_later(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1100x600+-3000+0')   # 画面の外に出す（試験中に利用者の画面に出さない）
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        changed = []
        build_variety_tab(frame, self.path, lambda: changed.append('mark'), STORE)
        frame.variety_mode.set('list')   # 一覧（今までの表）
        root.update()
        table = next(w for child in frame.winfo_children() for w in child.winfo_children() if isinstance(w, ttk.Treeview))
        first = table.get_children()[0]
        self.assertEqual(table.item(first, 'values')[1], '50')
        self.assertEqual(table.item(first, 'values')[0], '＋')
        x, y, w, h = table.bbox(first, '#1')
        table.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
        root.update()
        self.assertEqual(table.item(first, 'values')[0], '🌈')
        self.assertIn('rainbow', table.item(first, 'tags'))
        db = Store(self.path)
        try:
            payload = json.loads(db.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND rack=50',
                                               (STORE, '2026-10-10')).fetchone()[0])
        finally:
            db.close()
        self.assertIs(payload['rainbow'], True, 'その場で保存する')
        self.assertEqual(changed, ['mark'], '押したときは保存と印だけ（作り直しはまとめて、2026-10-12）')
        # ほかの列を押しても付け外ししない。
        x, y, w, h = table.bbox(first, '#3')
        table.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
        root.update()
        self.assertEqual(table.item(first, 'values')[0], '🌈')


    def test_grid_like_the_share_page(self):
        """PCにも共有ページと同じ表（2026-10-12 利用者「PCにも同じ表は用意しておいて」）：台×選んだ日までの7日、
        マスを押すとその日の🌈を付け外し、記録の無い日は押せない、右端は最後の🌈から何日。見せ方は覚える。"""
        from core import load_settings
        from variety_rainbow import days_since, gap_text, window_days
        self.assertEqual(window_days('2026-10-10'), ['2026-10-04', '2026-10-05', '2026-10-06', '2026-10-07',
                                                     '2026-10-08', '2026-10-09', '2026-10-10'])
        self.assertEqual([gap_text(days_since(x, '2026-10-10')) for x in ('2026-10-09', '2026-10-10', None)],
                         ['1日', '当日', 'なし'])
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1100x700+-3000+0')   # 画面の外に出す
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        changed = []
        build_variety_tab(frame, self.path, lambda: changed.append('mark'), STORE)
        root.update()
        self.assertEqual(frame.variety_mode.get(), 'grid', '初めは表')
        cells = frame.variety_cells
        self.assertEqual(cells[(50, '2026-10-09')].cget('text'), '🌈', '10/9に付いている')
        self.assertEqual(cells[(61, '2026-10-09')].cget('text'), '·', '61番台は10/9の記録が無い')
        self.assertEqual(cells[(50, '2026-10-10')].cget('highlightbackground').lower(), '#0071e3', '選んだ日は青い枠')
        # 10/10 の 51番台を押すと付く。
        cell = cells[(51, '2026-10-10')]
        cell.event_generate('<Button-1>', x=5, y=5)
        root.update()
        self.assertEqual((cell.cget('text'), cell.cget('background').lower()), ('🌈', '#fac775'))
        db = Store(self.path)
        try:
            payload = json.loads(db.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND rack=51',
                                               (STORE, '2026-10-10')).fetchone()[0])
        finally:
            db.close()
        self.assertIs(payload['rainbow'], True)
        # 記録の無いマスは押しても何もしない。
        cells[(61, '2026-10-09')].event_generate('<Button-1>', x=5, y=5)
        root.update()
        self.assertEqual(cells[(61, '2026-10-09')].cget('text'), '·')
        self.assertEqual(changed, ['mark'], '押したときは保存と印だけ（作り直しはまとめて、2026-10-12）')
        # 一覧に切り替えると覚える。
        frame.variety_mode.set('list')
        root.update()
        self.assertEqual(load_settings(self.path.parent).get('variety_mode'), 'list')


    def test_reflect_button_runs_the_rebuild_once(self):
        """「閲覧・共有ページに反映」ボタン：押すたびではなく、まとめて1回作り直す（2026-10-12 利用者「まとめてつけてから
        保存処理してほしい」）。"""
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1100x700+-3000+0')
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        marks, flushes = [], []
        pending = tk.StringVar(value='反映済み')
        build_variety_tab(frame, self.path, lambda: marks.append(1), STORE, on_flush=lambda: flushes.append(1), pending=pending)
        root.update()
        for rack in (50, 51, 60):
            frame.variety_cells[(rack, '2026-10-10')].event_generate('<Button-1>', x=5, y=5)
        root.update()
        self.assertEqual((len(marks), flushes), (3, []), '3台押しても作り直しはまだ')
        button = next(w for child in frame.winfo_children() for w in child.winfo_children()
                      if isinstance(w, ttk.Button) and str(w.cget('textvariable')) == str(pending))
        button.invoke()
        self.assertEqual(flushes, [1])


    def test_saiwaichou_uses_one_rack_machines_only(self):
        """幸町のバラエティ🌈は1台だけの機種（2026-10-12 利用者「幸町のバラエティは1台機種限定にして欲しい」）。長町南は1〜3台。"""
        from variety_rainbow import rainbow_variety_max
        db = Store(self.path)
        rows = []
        for store in ('saiwaichou', 'nagamachiminami'):
            rows += [dict(row(rack, '主力', '2026-10-10'), store=store) for rack in (1, 2, 3, 4)]
            rows += [dict(row(rack, 'ハナハナ', '2026-10-10'), store=store) for rack in (50, 51)]
            rows.append(dict(row(1201, '無職転生', '2026-10-10'), store=store))
        db.save(rows)
        db.close()
        self.assertEqual((rainbow_variety_max('saiwaichou'), rainbow_variety_max('nagamachiminami')), (1, 3))
        self.assertEqual([r['rack'] for r in variety_rows(self.path, 'saiwaichou', '2026-10-10')], [1201],
                         '幸町：2台のハナハナは入れない')
        self.assertIn(50, [r['rack'] for r in variety_rows(self.path, STORE, '2026-10-10')], '長町南：1〜3台のまま')


    def test_a_partly_captured_latest_day_does_not_shrink_the_lineup(self):
        """自己点検（2026-10-12）：長町南の10/10はサイトが落ちていて一部しか取れず、最新の日の並びだと5台になった。
        ふだんの台数の8割以上がある最新の日から並べる。"""
        from variety_rainbow import lineup_day
        db = Store(self.path)
        db.save([row(50, 'ハナハナ', '2026-10-11')])   # 1台だけ取れた日
        db.close()
        self.assertEqual(lineup_day(self.path, STORE), '2026-10-10')
        self.assertEqual([r['rack'] for r in variety_rows(self.path, STORE, '2026-10-11')], [50, 51, 60, 61],
                         '並びは記録のそろった10/10、数値は選んだ10/11')


if __name__ == '__main__':
    unittest.main()
