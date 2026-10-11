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
        build_variety_tab(frame, self.path, changed.append, STORE)
        root.update()
        table = next(w for w in frame.winfo_children()[-1].winfo_children() if isinstance(w, ttk.Treeview))
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
        self.assertEqual(changed, [], 'バックアップの作り直しは少し待ってまとめて')
        # ほかの列を押しても付け外ししない。
        x, y, w, h = table.bbox(first, '#3')
        table.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
        root.update()
        self.assertEqual(table.item(first, 'values')[0], '🌈')


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
