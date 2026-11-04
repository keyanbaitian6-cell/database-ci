"""機種一覧のタブ（PC、2026-11-01 利用者「今バラエティを表示しているような作りで見たい」「バラエティ以外の他の機種を
一覧でだしつつ、機種だけみたいときは（プルダウン）で切り替えられるように」）。"""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from core import STORE_NAMES, Store
from machine_list import ALL_MACHINES, SORTS, _now, build_machine_list_tab, machine_list_rows, rack_suffix

STORE = 'nagamachiminami'
DAY = '2026-10-10'


def row(rack, machine, games=3000, day=DAY, **extra):
    return dict(store=STORE, kind_code=21, day=day, machine=machine, rack=rack,
                games=games, bb=10, rb=5, max_hold=1500, **extra)


class MachineListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'database.sqlite3'
        db = Store(self.path)
        db.save([row(1, '主力', 5000), row(2, '主力', 800), row(3, '主力', 3000), row(4, '主力', 3000),
                 row(10, 'あ機種', 7000), row(11, 'あ機種', 100), row(12, 'あ機種', 2500), row(13, 'あ機種', 0),
                 # バラエティ（1〜3台の機種）はバラエティ🌈のタブにあるので入れない。
                 row(50, 'ハナハナ', 9000), row(51, 'ハナハナ', 9000)])
        db.close()

    def open_tab(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1200x700+-3000+0')   # 画面の外に出す（試験中に利用者の画面に出さない）
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        changed = []
        build_machine_list_tab(frame, self.path, lambda: changed.append('mark'), STORE, run=_now)
        root.update()
        return root, frame, frame.machine_list_table, changed

    def test_rows_leave_out_variety_and_carry_scores(self):
        rows = machine_list_rows(self.path, STORE, DAY)
        self.assertEqual([r['rack'] for r in rows], [1, 2, 3, 4, 10, 11, 12, 13])
        self.assertTrue(all('total' in r and 'setting' in r and 'mark' in r for r in rows))

    def test_machine_pulldown_and_headings_sort_like_the_variety_tab(self):
        root, frame, table, _changed = self.open_tab()

        def racks():
            return [int(table.item(iid, 'values')[1].split()[0]) for iid in table.get_children()]

        def click(column):
            x, y, width, _height = table.bbox(table.get_children()[0], column)
            x, y = x + width // 2, y // 2
            self.assertEqual(table.identify_region(x, y), 'heading')
            table.event_generate('<ButtonPress-1>', x=x, y=y)
            table.event_generate('<ButtonRelease-1>', x=x, y=y)
            root.update()

        self.assertEqual(racks(), [1, 2, 3, 4, 10, 11, 12, 13])
        click('games')
        self.assertEqual(racks(), [10, 1, 3, 4, 12, 2, 11, 13], '同じ回転数は台番順')
        self.assertEqual(table.heading('games', 'text'), '回転数 ▼')
        click('games')
        self.assertEqual(racks(), [13, 11, 2, 12, 3, 4, 1, 10])
        self.assertEqual(table.heading('games', 'text'), '回転数 ▲')
        click('machine')
        self.assertEqual(racks()[:4], [10, 11, 12, 13], 'あ機種が先頭')
        self.assertEqual(table.heading('games', 'text'), '回転数', '選んでいない見出しに印を付けない')
        click('total')
        self.assertEqual(table.heading('total', 'text'), '合計点 ▼')
        click('net')
        self.assertEqual(table.heading('net', 'text'), '推定差枚 ▼')
        # 機種のプルダウン：すべて＋その日の機種（バラエティは無い）。選ぶとその機種だけ、並べ方はそのまま。
        combo = next(w for w in frame.winfo_children()[2].winfo_children()
                     if isinstance(w, ttk.Combobox) and ALL_MACHINES in w.cget('values'))
        self.assertEqual(list(combo.cget('values')), [ALL_MACHINES, 'あ機種', '主力'])
        frame.machine_list_vars['sort'].set('回転数の多い順')
        frame.machine_list_vars['machine'].set('主力')
        root.update()
        self.assertEqual(racks(), [1, 3, 4, 2])
        frame.machine_list_vars['machine'].set(ALL_MACHINES)
        root.update()
        self.assertEqual(len(racks()), 8)

    def test_numbers_missing_go_last_both_ways(self):
        rows = [dict(rack=1, total=None, net=None, games=None), dict(rack=2, total=70.0, net=-300, games=10),
                dict(rack=3, total=40.0, net=500, games=0)]
        self.assertEqual([r['rack'] for r in sorted(rows, key=SORTS['合計点の高い順'])], [2, 3, 1])
        self.assertEqual([r['rack'] for r in sorted(rows, key=SORTS['合計点の低い順'])], [3, 2, 1])
        self.assertEqual([r['rack'] for r in sorted(rows, key=SORTS['差枚の多い順'])], [3, 2, 1])
        self.assertEqual([r['rack'] for r in sorted(rows, key=SORTS['回転数の少ない順'])], [3, 2, 1])

    def test_rainbow_column_toggles_and_saves(self):
        root, _frame, table, changed = self.open_tab()
        first = table.get_children()[0]
        self.assertEqual(table.item(first, 'values')[1], '1')
        x, y, w, h = table.bbox(first, '#1')
        table.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
        root.update()
        self.assertEqual(table.item(first, 'values')[0], '🌈')
        db = Store(self.path)
        try:
            payload = json.loads(db.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND rack=1',
                                               (STORE, DAY)).fetchone()[0])
        finally:
            db.close()
        self.assertIs(payload['rainbow'], True, 'その場で保存する')
        self.assertEqual(changed, ['mark'], '押したときは保存と印だけ（作り直しはまとめて）')
        # ほかの列を押しても付け外ししない。
        x, y, w, h = table.bbox(first, '#3')
        table.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
        root.update()
        self.assertEqual(table.item(first, 'values')[0], '🌈')

    def test_implausible_rack_shows_abnormal_and_sorts_last(self):
        db = Store(self.path)
        try:
            db.save([row(5, '主力', 88888888)])
        finally:
            db.close()
        rows = {r['rack']: r for r in machine_list_rows(self.path, STORE, DAY)}
        self.assertTrue(rows[5]['bad'])
        self.assertIsNone(rows[5]['games'])
        root, frame, table, _changed = self.open_tab()
        frame.machine_list_vars['sort'].set('回転数の多い順')
        root.update()
        last = table.get_children()[-1]
        self.assertEqual(table.item(last, 'values')[1], '5')
        self.assertEqual(table.item(last, 'values')[3], '異常')

    def test_deferred_tab_reads_nothing_until_opened(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        frame = ttk.Frame(root)
        with patch('machine_list.Store', side_effect=AssertionError('まだDBを開かない')):
            refresh = build_machine_list_tab(frame, self.path, lambda: None, STORE, defer_load=True, run=_now)
            root.update_idletasks()
        self.assertEqual(frame.machine_list_table.get_children(), ())
        refresh()
        self.assertEqual(len(frame.machine_list_table.get_children()), 8)


    def test_pscube_store_lists_all_machines_without_scores(self):
        # 2026-11-02 利用者「P-STATIONの分がないのはなぜ？」→「点数なしで足す」。
        import pscube_import
        pscube_path = Path(self.tmp.name) / 'pscube.sqlite3'
        store = pscube_import.PscubeStore(pscube_path, recording=False)
        records = [dict(store='c740601', rate='20', machine='ジャグラー', rack=rack, day='2026-11-01', games=games,
                        bb=10, rb=5, at_art=0, my=800, net_medals=net)
                   for rack, games, net in ((101, 4000, 500), (102, 7000, None), (103, 900, -300))]
        records += [dict(store='c740601', rate='20', machine='北斗', rack=201, day='2026-11-01', games=3000, bb=1, rb=0,
                         at_art=3, my=1500, net_medals=1200),
                    dict(store='c740601', rate='20', machine='沖ドキ！', rack=301, day='2026-11-01', games=5000, bb=1, rb=0,
                         at_art=0, my=100, net_medals=0),
                    dict(store='c740601', rate='20', machine='ジャグラー', rack=101, day='2026-10-31', games=1, bb=0, rb=0,
                         at_art=0, my=0, net_medals=0)]
        with store.db:
            for i, r in enumerate(records):
                store.db.execute('INSERT INTO records VALUES (?,?)', (str(i), json.dumps(r, ensure_ascii=False)))
        store.close()
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1200x700+-3000+0')
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        build_machine_list_tab(frame, self.path, lambda: None, STORE, run=_now, pscube=(pscube_path, 'P’s CUBE（スロット）'))
        frame.machine_list_vars['store'].set('P’s CUBE（スロット）')
        root.update()
        table = frame.machine_list_table
        self.assertEqual(frame.machine_list_vars['day'].get(), '2026-11-01', '最新の日')
        rows = [table.item(iid, 'values') for iid in table.get_children()]
        self.assertEqual([r[1] for r in rows], ['101', '102', '103', '201'], '沖ドキは除く。台数の少ない機種も入れる')
        self.assertEqual(rows[0][2], 'ジャグラー')
        self.assertEqual(rows[0][6], '+500')
        self.assertEqual(rows[0][7], '800', 'MYの列')
        self.assertEqual((rows[0][0], rows[0][8], rows[0][9]), ('—', '—', '—'), '🌈・設定候補・合計点は出さない')
        self.assertIn('my', table['displaycolumns'])
        self.assertEqual(table.heading('net', 'text'), '差枚')
        frame.machine_list_vars['sort'].set('差枚の多い順')
        root.update()
        self.assertEqual([table.item(i, 'values')[1] for i in table.get_children()], ['201', '101', '103', '102'],
                         '差枚の無い台は最後')
        # 🌈の列を押しても何もしない（P’s CUBEには付けない）。
        first = table.get_children()[0]
        x, y, w, h = table.bbox(first, '#1')
        table.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
        root.update()
        self.assertEqual(table.item(first, 'values')[0], '—')
        # メルヘンの店へ戻すと、MYの列は隠れ、見出しは推定差枚。
        frame.machine_list_vars['store'].set(STORE_NAMES[STORE])
        root.update()
        self.assertNotIn('my', table['displaycolumns'])
        self.assertTrue(table.heading('net', 'text').startswith('推定差枚'))


class SuffixMarkTests(unittest.TestCase):
    """台番の末尾の印（2026-11-05 利用者「差枚一覧で選んだ末尾を、機種一覧でも追えるようにする」）。"""

    def test_rack_suffix(self):
        self.assertEqual([rack_suffix(r) for r in (7, 17, 120, 1203)], [7, 7, 0, 3])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'database.sqlite3'
        db = Store(self.path)
        # 長町南は3台以下の機種がバラエティ（この一覧に入らない）ので、どちらも4台以上。
        db.save([row(1, '主力'), row(3, '主力'), row(5, '主力'), row(13, '主力'), row(23, '主力'),
                 row(10, 'あ機種'), row(12, 'あ機種'), row(14, 'あ機種'), row(33, 'あ機種'),
                 *(row(rack, '主力', day='2026-10-09') for rack in (1, 2, 4, 13))])
        db.close()

    def open_tab(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1200x800+-3000+0')   # 画面の外に出す（試験中に利用者の画面に出さない）
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        build_machine_list_tab(frame, self.path, lambda: None, STORE, run=_now)
        root.update()
        return root, frame, frame.machine_list_table

    def test_suffix_marks_follow_machine_choice_and_clear_on_day_change(self):
        root, frame, table = self.open_tab()
        variables = frame.machine_list_vars

        def marked():
            return [table.item(i, 'values')[1] for i in table.get_children() if '末' in table.item(i, 'values')[1]]

        self.assertEqual(marked(), [])
        self.assertFalse(frame.machine_list_clear.winfo_ismapped())
        variables['suffix'].set('3')
        root.update()
        self.assertEqual(marked(), ['3 末3', '13 末3', '23 末3', '33 末3'])
        self.assertEqual(frame.machine_list_clear.cget('text'), '末尾3 ×')
        self.assertTrue(frame.machine_list_clear.winfo_ismapped())
        # 機種を1つにしても残す（台は全部出したまま）。
        variables['machine'].set('主力')
        root.update()
        self.assertEqual([table.item(i, 'values')[1].split()[0] for i in table.get_children()], ['1', '3', '5', '13', '23'])
        self.assertEqual(marked(), ['3 末3', '13 末3', '23 末3'])
        # 「末尾3 ×」で解除。
        frame.machine_list_clear.invoke()
        root.update()
        self.assertEqual(variables['suffix'].get(), 'なし')
        self.assertEqual(marked(), [])
        self.assertFalse(frame.machine_list_clear.winfo_ismapped())
        # 日付を変えると解除。元の日に戻しても解除のまま。
        variables['suffix'].set('3')
        root.update()
        variables['day'].set('2026-10-09')
        root.update()
        self.assertEqual(variables['suffix'].get(), 'なし')
        self.assertEqual(marked(), [])
        variables['day'].set(DAY)
        root.update()
        self.assertEqual(marked(), [])


if __name__ == '__main__':
    unittest.main()
