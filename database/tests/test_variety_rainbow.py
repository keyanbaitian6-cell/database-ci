"""バラエティの🌈のタブ（PC、2026-10-11 利用者「バラエティの機種一覧をpcで表示させて、この🌈マークをつけられる
ようにもしてほしい。そのタブかページを作って」「機種一覧名はとりあえず最新の機種一覧からとって表示させておけば
いいよ。入れ替えとかで変わったらその都度書き換えて」）。仕様は ../RAINBOW.md。"""
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from core import Store
from variety_rainbow import SORTS, build_variety_tab, variety_rows

STORE = 'nagamachiminami'


def row(rack, machine, day, games=3000, **extra):
    return dict(store=STORE, kind_code=21, day=day, machine=machine, rack=rack,
                games=games, bb=10, rb=5, max_hold=1500, **extra)


class VarietyRainbowTests(unittest.TestCase):
    def setUp(self):
        import gc
        self.addCleanup(gc.collect)  # Tcl_AsyncDelete 対策（root.destroy のあとにメインスレッドで回収）
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

    def test_deferred_tab_leaves_history_unread_until_opened(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        frame = ttk.Frame(root)
        with patch('variety_rainbow.Store', side_effect=AssertionError('まだDBを開かない')):
            refresh = build_variety_tab(frame, self.path, lambda: None, STORE, defer_load=True)
            root.update_idletasks()
        self.assertEqual(frame.variety_cells, {})
        refresh()  # PC本体で🌈タブを開くときと同じ呼び出し。
        self.assertTrue(frame.variety_cells)
        db = Store(self.path)
        try:
            db.set_rainbow(STORE, '2026-10-10', 50, True)
        finally:
            db.close()
        refresh()  # 再度開いたときも最新の保存済み🌈を反映する。
        cell = frame.variety_cells[(50, '2026-10-10')]
        self.assertIn('🌈', cell.cget('text'))

    def test_games_and_other_headings_sort_the_list(self):
        # 2026-11-01 利用者「回転数とかでもソートできるようにしておいてほしい」。台番・機種・最終🌈も見出しで。
        db = Store(self.path)
        try:
            db.save([row(60, '新バラエティ', '2026-10-10', games=7000), row(62, 'あ機種', '2026-10-10', games=0)])
            before = db.db.execute('SELECT store,day,machine,rack,payload FROM days ORDER BY store,day,machine,rack').fetchall()
        finally:
            db.close()
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1100x700+-3000+0')
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        build_variety_tab(frame, self.path, lambda: None, STORE)
        frame.variety_mode.set('list')
        root.update()
        table = next(w for child in frame.winfo_children() for w in child.winfo_children() if isinstance(w, ttk.Treeview))

        def racks():
            return [int(table.item(iid, 'values')[1]) for iid in table.get_children()]

        def click(column):
            x, y, width, _height = table.bbox(table.get_children()[0], column)
            x, y = x + width // 2, y // 2
            self.assertEqual(table.identify_region(x, y), 'heading')
            table.event_generate('<ButtonPress-1>', x=x, y=y)
            table.event_generate('<ButtonRelease-1>', x=x, y=y)
            root.update()

        click('games')  # 50=5000・51=800・60=7000・61=3000・62=0
        self.assertEqual(racks(), [60, 50, 61, 51, 62])
        self.assertEqual(table.heading('games', 'text'), '回転数 ▼')
        self.assertEqual(table.heading('net', 'text'), '推定差枚', '選んでいない見出しに印を付けない')
        click('games')
        self.assertEqual(racks(), [62, 51, 61, 50, 60])
        self.assertEqual(table.heading('games', 'text'), '回転数 ▲')
        # 本日の未取得（回転数なし）は、多い順・少ない順のどちらでも最後。
        unknown = [dict(rack=1, games=None), dict(rack=2, games=100), dict(rack=3, games=0)]
        self.assertEqual([r['rack'] for r in sorted(unknown, key=SORTS['回転数の多い順'])], [2, 3, 1])
        self.assertEqual([r['rack'] for r in sorted(unknown, key=SORTS['回転数の少ない順'])], [3, 2, 1])
        click('machine')
        self.assertEqual(table.heading('machine', 'text'), '機種 ▲')
        self.assertEqual(racks()[0], 62, 'あ機種が先頭')
        click('rack')
        self.assertEqual(racks(), [50, 51, 60, 61, 62])
        self.assertEqual(table.heading('rack', 'text'), '台番 ▲')
        self.assertEqual(table.heading('games', 'text'), '回転数')
        click('last')
        self.assertEqual(table.heading('last', 'text'), '最終🌈 ▲')
        db = Store(self.path)
        try:
            after = db.db.execute('SELECT store,day,machine,rack,payload FROM days ORDER BY store,day,machine,rack').fetchall()
            self.assertEqual(after, before, '並べ替えで保存済みの数値・印を変えない')
        finally:
            db.close()

    def test_net_heading_toggles_numeric_order_with_unknown_last(self):
        db = Store(self.path)
        try:
            db.save([row(50, 'ハナハナ', '2026-10-10', jo_net=12000),
                     row(51, 'ハナハナ', '2026-10-10', jo_net=-800),
                     row(60, '新バラエティ', '2026-10-10', jo_net=0),
                     row(62, '同差枚', '2026-10-10', jo_net=12000)])
            before = db.db.execute('SELECT store,day,machine,rack,payload FROM days ORDER BY store,day,machine,rack').fetchall()
        finally:
            db.close()
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1100x700+-3000+0')
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        changed = []
        build_variety_tab(frame, self.path, lambda: changed.append(1), STORE)
        frame.variety_mode.set('list')
        root.update()
        table = next(w for child in frame.winfo_children() for w in child.winfo_children() if isinstance(w, ttk.Treeview))

        def racks():
            return [int(table.item(iid, 'values')[1]) for iid in table.get_children()]

        def click_net_heading():
            x, y, width, _height = table.bbox(table.get_children()[0], 'net')
            x, y = x + width // 2, y // 2
            self.assertEqual(table.identify_region(x, y), 'heading')
            table.event_generate('<ButtonPress-1>', x=x, y=y)
            table.event_generate('<ButtonRelease-1>', x=x, y=y)
            root.update()

        self.assertEqual(racks(), [50, 51, 60, 61, 62])
        click_net_heading()
        self.assertEqual(racks(), [50, 62, 60, 51, 61])
        self.assertEqual(table.heading('net', 'text'), '推定差枚 ▼')
        click_net_heading()
        self.assertEqual(racks(), [51, 60, 50, 62, 61])
        self.assertEqual(table.heading('net', 'text'), '推定差枚 ▲')
        # 別の日へ切り替え、戻っても選んだ並べ方で新しい行を表示する。
        frame.variety_day.set('2026-10-09')
        frame.variety_day.set('2026-10-10')
        root.update()
        self.assertEqual(racks(), [51, 60, 50, 62, 61])
        self.assertEqual(changed, [], '見出しの操作では🌈を保存しない')
        db = Store(self.path)
        try:
            after = db.db.execute('SELECT store,day,machine,rack,payload FROM days ORDER BY store,day,machine,rack').fetchall()
            self.assertEqual(after, before, '並べ替えで保存済みの数値・印を変えない')
        finally:
            db.close()

        # 並べ替えた後の🌈クリックも、表示している台番号にだけ保存する。
        first = table.get_children()[0]
        self.assertEqual(int(table.item(first, 'values')[1]), 51)
        x, y, width, height = table.bbox(first, '#1')
        table.event_generate('<Button-1>', x=x + width // 2, y=y + height // 2)
        root.update()
        db = Store(self.path)
        try:
            self.assertEqual(db.rainbow_racks(STORE, '2026-10-10'), [51])
        finally:
            db.close()
        self.assertEqual(changed, [1])

    def test_today_grid_and_list_can_mark_without_creating_numeric_records(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1100x700+-3000+0')
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        changed = []
        with patch('variety_rainbow.today_jst', return_value='2026-10-11'):
            refresh = build_variety_tab(frame, self.path, lambda: changed.append(1), STORE)
            frame.variety_today_button.invoke()
            root.update()
            self.assertEqual(frame.variety_day.get(), '2026-10-11')
            cell = frame.variety_cells[(50, '2026-10-11')]
            self.assertEqual(cell.cget('text'), '＋')
            cell.event_generate('<Button-1>', x=5, y=5)
            root.update()
            self.assertEqual(cell.cget('text'), '🌈')
            refresh()
            self.assertEqual(frame.variety_cells[(50, '2026-10-11')].cget('text'), '🌈')
            frame.variety_mode.set('list')
            root.update()
            table = next(w for child in frame.winfo_children() for w in child.winfo_children() if isinstance(w, ttk.Treeview))
            first = table.get_children()[0]
            self.assertEqual(table.item(first, 'values')[3:6], ('—', '—', '—'))
            x, y, w, h = table.bbox(first, '#1')
            table.event_generate('<Button-1>', x=x + w // 2, y=y + h // 2)
            root.update()
            self.assertEqual(table.item(first, 'values')[0], '＋')
            db = Store(self.path)
            try:
                self.assertEqual(db.days_for(STORE), ['2026-10-10', '2026-10-09'])
                self.assertEqual(db.rainbow_racks(STORE, '2026-10-11'), [])
                self.assertFalse(db.pending_rainbow_marks(STORE, '2026-10-11')[0]['on'])
            finally:
                db.close()
            self.assertEqual(changed, [1, 1])

    def test_today_rollover_refreshes_without_marking_the_previous_day(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1100x700+-3000+0')
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True)
        with patch('variety_rainbow.today_jst', return_value='2026-10-11') as today:
            build_variety_tab(frame, self.path, lambda: self.fail('日付確認前に保存した'), STORE)
            frame.variety_today_button.invoke()
            root.update()
            today.return_value = '2026-10-12'
            with patch('variety_rainbow.messagebox.showinfo') as info:
                frame.variety_cells[(50, '2026-10-11')].event_generate('<Button-1>', x=5, y=5)
                root.update()
            info.assert_called_once()
            self.assertEqual(frame.variety_day.get(), '2026-10-12')
            db = Store(self.path)
            try:
                self.assertEqual(db.pending_rainbow_marks(), [])
            finally:
                db.close()

    def test_yesterdays_pending_mark_stays_visible_without_numeric_data(self):
        from variety_rainbow import rotation_cells
        db = Store(self.path)
        try:
            db.set_rainbow(STORE, '2026-10-11', 50, True, allow_missing=True)
        finally:
            db.close()
        with patch('variety_rainbow.today_jst', return_value='2026-10-12'):
            cells = rotation_cells(self.path, STORE, ['2026-10-11', '2026-10-12'])
            self.assertTrue(cells['2026-10-11'][50]['rainbow'])
            self.assertFalse(cells['2026-10-11'][50]['editable'])
            rows = {r['rack']: r for r in variety_rows(self.path, STORE, '2026-10-11')}
            self.assertTrue(rows[50]['rainbow'])
            self.assertIsNone(rows[50]['games'])
            self.assertEqual(rows[50]['rainbow_count'], 2)

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
