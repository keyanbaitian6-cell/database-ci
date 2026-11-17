"""PCの店の入れ方のふり返り（2026-11-18 利用者「PCでも表示させてほしい」）。閲覧ページと同じ数字にする。"""
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import tkinter as tk
import unittest

import core
import store_pattern as sp
import store_pattern_ui as ui

FIXTURE = Path(__file__).resolve().parents[2] / 'database_android/test/fixtures/store_pattern_cases.json'
STORE, DAY = 'nagamachiminami', '2026-11-14'


def rack(number, plus, machine='A', day=DAY, games=3000, known=True):
    row = dict(store=STORE, day=day, machine=machine, rack=number, games=games, bb=5, rb=5)
    if known:
        row['jo_net'] = 500 if plus else -500
    return row


def texts(parent):
    for w in parent.winfo_children():
        if isinstance(w, tk.Label):
            yield str(w.cget('text'))
        yield from texts(w)


class StorePatternTest(unittest.TestCase):
    def test_hypergeometric_and_comparisons(self):
        rows = [rack(i, True, 'A') for i in range(1, 4)] + [rack(i, i <= 5, 'B') for i in range(4, 11)]
        r = sp.store_pattern_day(STORE, DAY, rows, core.rack_won)
        a = next(g for g in r['machines'] if g['label'] == 'A')
        self.assertAlmostEqual(a['p'], 10 / 120, places=12)
        self.assertAlmostEqual(a['adjusted'], 20 / 120, places=12)
        self.assertEqual(a['chance'], sp.SOMETIMES)
        self.assertEqual((r['total'], r['plus'], r['usable']), (10, 5, True))

    def test_run_and_gap_and_same_every_time(self):
        rows = [rack(i, 103 <= i <= 107) for i in range(101, 113)]
        r = sp.store_pattern_day(STORE, DAY, rows, core.rack_won)
        self.assertEqual(r['run']['racks'], [103, 104, 105, 106, 107])
        self.assertTrue(.003 <= r['run']['p'] <= .03)
        self.assertEqual(sp.store_pattern_day(STORE, DAY, rows, core.rack_won)['run']['p'], r['run']['p'])
        self.assertIn('並び：103〜107番（5台）', r['highlights'])

    def test_days_with_few_known_racks_are_not_judged(self):
        # アナスロで補った日のように、プラスかどうか分かる台が稼働した台の7割に届かない日は判定しない。
        rows = [rack(i, i % 3 == 0, known=i % 2 == 0) for i in range(1, 41)]
        r = sp.store_pattern_day(STORE, DAY, rows, core.rack_won)
        self.assertEqual((r['total'], r['played']), (20, 40))
        self.assertFalse(r['usable'])
        self.assertEqual(r['highlights'], [])
        low = [rack(i, i % 2 == 0, games=500) for i in range(1, 30)] + [rack(100 + i, i % 2 == 0) for i in range(12)]
        self.assertEqual(sp.store_pattern_day(STORE, DAY, low, core.rack_won)['played'], 12, '500G以下は稼働に数えない')

    def test_half_width_machine_names_are_shown_full_width(self):
        self.assertEqual(sp.fold_half_width_kana('ﾏｲｼﾞｬｸﾞﾗｰV'), 'マイジャグラーV')
        self.assertEqual(sp.fold_half_width_kana('Lｽﾛｯﾄ ｿｰﾄﾞｱｰﾄ･ｵﾝﾗｲﾝB2'), 'Lスロット ソードアート･オンラインB2')

    def test_shared_cases_match_the_viewer(self):
        # 閲覧ページ（Dart）の試験も同じデータで同じ値を確かめる。ここではPCの計算が正解のまま変わっていないか。
        doc = json.loads(FIXTURE.read_text(encoding='utf-8'))
        for case in doc['cases']:
            won = sp.pscube_won if case['store'].startswith('pscube:') else core.rack_won
            r = sp.store_pattern_day(case['store'], case['day'], case['rows'], won)
            e = case['expected']
            self.assertEqual([r['plus'], r['total'], r['played'], r['excluded'], r['usable']],
                             [e['plus'], e['total'], e['played'], e['excluded'], e['usable']], case['day'])
            self.assertEqual([[g['label'], g['plus'], g['total'], g['compared'], g['chance']] for g in r['machines']],
                             [[x[0], x[1], x[2], x[3], x[5]] for x in e['machines']])
            self.assertEqual(r['highlights'], e['highlights'])
            self.assertEqual(None if r['run'] is None else [r['run']['racks'], r['run']['p']],
                             None if e['run'] is None else e['run'][:2])

    def test_pc_window_shows_both_stores_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            db = core.Store(data / 'database.sqlite3')
            try:
                rows = [dict(rack(i, 103 <= i <= 107, 'ﾏｲｼﾞｬｸﾞﾗｰV' if i < 107 else 'B'), kind_code=21, max_hold=100)
                        for i in range(101, 113)]
                rows += [dict(rack(i, i % 2 == 0, day='2026-11-13'), kind_code=21, max_hold=100) for i in range(101, 113)]
                db.save(rows)
                db.set_date_event(STORE, DAY, '4台構成')
            finally:
                db.close()
            ps = sqlite3.connect(data / 'pscube.sqlite3')
            ps.execute('CREATE TABLE records (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            ps.execute('CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            for i in range(12):
                payload = dict(store='c740601', rate='20', day=DAY, machine='ｱｲﾑｼﾞｬｸﾞﾗｰ', rack=1001 + i, games=2000,
                               bb=3, rb=3, net_medals=300 if i < 6 else -300, source_site='site777')
                ps.execute('INSERT INTO records VALUES(?,?)', (str(i), json.dumps(payload, ensure_ascii=False)))
            ps.commit(); ps.close()
            root = tk.Tk(); root.withdraw()
            try:
                window = ui.show(root, data)
                window.withdraw()

                def settle():
                    # 履歴は1日ずつ計算するので、終わるまで進める。
                    for _ in range(200):
                        root.update()
                        if not any('計算中' in t for t in texts(window)):
                            break
                        time.sleep(.02)

                settle()
                shown = '\n'.join(texts(window))
                self.assertIn('長町南　11/14（土）', shown)
                self.assertIn('イベント：4台構成', shown)
                self.assertIn('いちばん長い並び：103〜107番（5台）', shown)
                self.assertIn('マイジャグラーV', shown)
                self.assertNotIn('ﾏｲｼﾞｬｸﾞﾗｰ', shown, '半角カナの機種名は全角で出す')
                self.assertIn('11/13（金）', shown, '日ごとの履歴')
                stores = [w for w in window.winfo_children() for w in w.winfo_children()
                          if str(w.winfo_class()) == 'TCombobox']
                stores[0].current(2); stores[0].event_generate('<<ComboboxSelected>>')
                settle()
                shown = '\n'.join(texts(window))
                self.assertIn('P-STATION　11/14（土）', shown)
                self.assertIn('判定に使った台 12台・プラス 6台', shown)
                window.destroy()
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
