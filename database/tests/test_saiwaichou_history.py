from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import Store, auto_backup, export_backup, import_backup, pull_shared_history, save_settings
from event_history_data import (FILE_NAME, SAIWAI_STORE, STORE, VARIETY_KEY, auto_faces, auto_grades,
    clean_edits, empty_edits, gap_end, grade_gap, load_base, machine_day_nets, materialize, merge_edits,
    net_grade, saiwaichou_base, validate_envelope, variety_week_lineup)

MONDAY = '2026-10-19'


def variety(names=(('機種A', 1), ('機種B', 2))):
    edits = empty_edits()
    edits['weeks'] = [dict(store=SAIWAI_STORE, type='バラエティ', week=MONDAY,
        lineup_day=MONDAY, machines=[dict(name=n, record_name=n, count=c) for n, c in names],
        removed=False, updated_at='2026-10-22T00:00:00Z')]
    return edits


def grade(name='機種A', value='優', at='2026-10-22T00:00:00Z'):
    return dict(store=SAIWAI_STORE, type='バラエティ', week=MONDAY, machine=name,
                day=MONDAY, value=value, updated_at=at, device='pc')


def row(name, rack, net=None, location=SAIWAI_STORE, **kwargs):
    return dict(store=location, kind_code=21, day=MONDAY, machine=name, rack=rack,
        games=1000, bb=4, rb=2, max_hold=100,
        **({} if net is None else {'jo_net': net}), **kwargs)


class SaiwaichouHistoryTests(unittest.TestCase):
    def test_common_fixture_keeps_same_name_and_week_separate_by_store(self):
        doc = json.loads((Path(__file__).resolve().parents[2] / 'database_android/test/fixtures/saiwaichou_history_cases.json').read_text(encoding='utf-8'))
        nested = doc[VARIETY_KEY]
        weeks, rejected = materialize(nested['base'], nested)
        self.assertEqual(rejected, doc['expected']['rejected'])
        self.assertEqual([m['results'] for m in weeks[0]['machines']], doc['expected']['results'])
        self.assertEqual(materialize(doc['base'], doc)[0][0]['machines'][0]['results'][0], '😍')

    def test_grade_boundaries_and_missing_values(self):
        for value, expected in [(-1, None), (0, '良'), (2499, '良'), (2500, '優'), (2501, '優'),
                                (None, None), (True, None), (float('nan'), None), (float('inf'), None)]:
            with self.subTest(value=value):
                self.assertEqual(net_grade(value), expected)

    def test_lineup_uses_saiwaichou_one_or_two_racks_only(self):
        rows = [row('機種A', 1), row('機種B', 2), row('機種B', 3),
                *[row('3台機種', n) for n in (4, 5, 6)], row('別店舗', 99, location=STORE)]
        day, machines, doubtful = variety_week_lineup(rows, MONDAY, SAIWAI_STORE)
        self.assertEqual(day, MONDAY)
        self.assertEqual([(m['name'], m['count']) for m in machines], [('機種A', 1), ('機種B', 2)])
        self.assertEqual(doubtful, [])

    def test_all_racks_and_zero_net_are_required_and_other_store_is_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder) / 'db.sqlite3')
            try:
                db.save([row('機種A', 1, 2500), row('機種A', 1, 90000, location=STORE),
                         row('機種B', 2, 4000), row('機種B', 3, -4000),
                         row('欠損', 4, 5000), row('欠損', 5), row('台数不足', 6, 8000)])
                nets = machine_day_nets(db, MONDAY, MONDAY, SAIWAI_STORE,
                                       {'機種A': 1, '機種B': 2, '欠損': 2, '台数不足': 2})
                self.assertEqual(nets, {(MONDAY, '機種A'): 2500, (MONDAY, '機種B'): 0})
                week = materialize(saiwaichou_base(), variety())[0][0]
                week['machines'][0]['results'][0] = '良'  # 手入力を残す。
                cells, skipped = auto_faces(week, nets, {MONDAY: {'機種A', '機種B'}}, ['優', '良'],
                                            only_day=MONDAY, classify=net_grade)
                self.assertEqual(cells, [('機種B', MONDAY, '良')])
                self.assertEqual(skipped, 0)
            finally:
                db.close()

    def test_nested_history_survives_nagamachi_edits_and_older_backups(self):
        base = load_base()
        initial = dict(empty_edits(), **{VARIETY_KEY: variety()})
        initial[VARIETY_KEY]['cells'] = [grade()]
        saved, *_ = merge_edits(empty_edits(), initial, base)
        w = base['weeks'][0]
        change = dict(empty_edits(), cells=[dict(store=STORE, type=w['type'], week=w['from'],
            machine=w['machines'][0]['name'], day=w['from'], value='😍',
            updated_at='2026-10-22T00:00:00Z', device='pc')])
        saved, *_ = merge_edits(saved, change, base)
        after, *_ = merge_edits(saved, empty_edits(), base)  # 旧版に幸町が無くても消えない。
        self.assertEqual(after[VARIETY_KEY], saved[VARIETY_KEY])
        self.assertEqual(materialize(base, after)[0][-1]['from'], materialize(base, saved)[0][-1]['from'])
        self.assertEqual(after['cells'][0]['value'], '😍')
        incoming = dict(empty_edits(), **{VARIETY_KEY: dict(variety(), cells=[grade(value='良', at='2026-10-21T00:00:00Z')])})
        merged, *_ = merge_edits(after, incoming, base)
        self.assertEqual(merged[VARIETY_KEY]['cells'][0]['value'], '優')

    def test_rejects_faces_other_store_and_three_rack_definitions(self):
        edits = variety()
        edits['cells'] = [grade(), grade('機種B', '😀'), dict(grade(), store=STORE)]
        clean, bad = clean_edits(edits, saiwaichou_base())
        self.assertEqual(bad, 2)
        self.assertEqual([c['value'] for c in clean['cells']], ['優'])
        bad_week = variety((('3台機種', 3),))
        self.assertEqual(clean_edits(bad_week, saiwaichou_base())[1], 1)
        nested = dict(empty_edits(), **{VARIETY_KEY: dict(empty_edits(), **{VARIETY_KEY: empty_edits()})})
        with self.assertRaises(ValueError):
            validate_envelope(nested)

    def test_backup_round_trip_and_shared_document_preserve_both_stores(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); a, b = Store(root / 'a.db'), Store(root / 'b.db')
            try:
                edits = variety(); edits['cells'] = [grade(), grade('機種B', '良')]
                a.merge_history_edits(dict(empty_edits(), **{VARIETY_KEY: edits}))
                export_backup(a, root / 'backup.json')
                plan = import_backup(b, root / 'backup.json')
                self.assertEqual(plan['history_added'], 3)
                self.assertEqual(a.history_edits_raw(), b.history_edits_raw())
                sync = root / 'sync'; sync.mkdir(); save_settings(root, sync_dir=str(sync))
                auto_backup(b, root, strict=True)
                doc = json.loads((sync / FILE_NAME).read_text(encoding='utf-8'))
                self.assertEqual(doc['base']['store'], STORE)
                self.assertEqual(doc[VARIETY_KEY]['base'], saiwaichou_base())
                weeks = materialize(doc[VARIETY_KEY]['base'], doc[VARIETY_KEY])[0]
                self.assertEqual([m['results'][0] for m in weeks[0]['machines']], ['優', '良'])
                # 共有側から幸町を編集する経路は作らない。
                (sync / 'database-event-history-shared.json').write_text(json.dumps(dict(empty_edits(), **{VARIETY_KEY: edits})))
                before = b.history_edits_raw()
                with self.assertRaises(ValueError):
                    pull_shared_history(b, sync)
                self.assertEqual(b.history_edits_raw(), before)
            finally:
                a.close(); b.close()

    def test_auto_grades_need_all_racks_and_keep_manual_cells(self):
        week = materialize(saiwaichou_base(), variety())[0][0]
        week['machines'][0]['results'][0] = '良'  # 手入力が優先し、自動の値を出さない。
        days = [(date.fromisoformat(MONDAY) + timedelta(days=i)).isoformat() for i in range(7)]
        names = {d: {'機種A', '機種B'} for d in days}
        totals = {(days[0], '機種A'): (5000, 1), (days[0], '機種B'): (2500, 2), (days[1], '機種B'): (3000, 1),
                  (days[2], '機種B'): (-1, 2), (days[3], '機種B'): (0, 2), (days[4], '機種B'): (None, 2),
                  (days[5], '機種A'): (2499, 1)}
        self.assertEqual(auto_grades(week, totals, names), {
            ('機種B', days[0]): '優', ('機種B', days[3]): '良', ('機種A', days[5]): '良'})
        del names[days[3]]  # その日の記録が無ければ出さない。
        self.assertNotIn(('機種B', days[3]), auto_grades(week, totals, names))

    def test_gap_is_five_days_before_today_without_more_than_800(self):
        weeks = materialize(saiwaichou_base(), variety())[0]
        item = weeks[0]['machines'][0]
        names = {f'2026-10-{d}': {'機種A', '機種B'} for d in range(12, 26)}
        end = '2026-10-23'
        gap = lambda totals, w=weeks: grade_gap(w, item, end, totals, names)
        self.assertTrue(gap({}), '記録なし・差枚不明は超えていないと数える')
        self.assertFalse(gap({('2026-10-19', '機種A'): (801, 1)}), '5日目の+801枚')
        self.assertTrue(gap({('2026-10-23', '機種A'): (800, 1)}), '+800枚ちょうどは超えていない')
        self.assertTrue(gap({('2026-10-18', '機種A'): (9000, 1)}), '6日前は対象外')
        self.assertTrue(gap({('2026-10-24', '機種A'): (9000, 1)}), '最終日より後は対象外')
        self.assertTrue(gap({('2026-10-23', '機種A'): (9000, 2)}), '台数が週表と違う合計は使わない')
        manual = materialize(saiwaichou_base(), dict(variety(), cells=[grade(value='優')]))[0]
        self.assertFalse(gap({}, manual), '手入力の優は超えた日と数える')
        manual = materialize(saiwaichou_base(), dict(variety(), cells=[grade(value='良')]))[0]
        self.assertTrue(gap({}, manual))
        # 前週にまたがる5日間も見る。
        self.assertFalse(grade_gap(weeks, item, '2026-10-20', {('2026-10-16', '機種A'): (801, 1)}, names))
        self.assertFalse(grade_gap(weeks, item, None, {}, names), '記録のない週は赤くしない')
        self.assertEqual(gap_end('2026-10-29', date(2026, 10, 29)), '2026-10-28', '今日は含めない')
        self.assertEqual(gap_end('2026-10-25', date(2026, 10, 29)), '2026-10-25')
        self.assertIsNone(gap_end(None, date(2026, 10, 29)))

    def test_pc_shows_auto_grades_manual_override_and_gap_without_buttons(self):
        import tkinter as tk
        from tkinter import ttk
        from event_history import open_event_history

        def children(parent):
            for w in parent.winfo_children():
                yield w
                yield from children(w)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'gui.db'; db = Store(path)
            try:
                db.save([row('機種A', 1, 2500), row('機種B', 2, 4000), row('機種B', 3, -4000),
                         *[row('3台機種', n, 8000) for n in (4, 5, 6)], row('別店舗', 99, 90000, location=STORE)])
            finally:
                db.close()

            def saved():
                db = Store(path)
                try:
                    return db.history_edits_raw()
                finally:
                    db.close()
            root = tk.Tk(); root.withdraw(); picked = []
            try:
                with patch('event_history_data.today_jst', return_value=date(2026, 10, 21)):
                    window = open_event_history(root, lambda n, d: picked.append((n, d)), db_path=path, location=SAIWAI_STORE)
                    def button(text):
                        return next(w for w in children(window) if isinstance(w, ttk.Button) and w.cget('text') == text)
                    def labels():
                        return [w.cget('text') for w in children(window) if isinstance(w, ttk.Label)]
                    def red():
                        return [w.cget('text') for w in children(window) if isinstance(w, ttk.Label) and str(w.cget('foreground')) == '#b91c1c']
                    with patch('event_history.simpledialog.askstring', return_value=MONDAY), \
                            patch('event_history.messagebox.askyesno', return_value=True):
                        button('バラエティの週表を作成').invoke()
                    self.assertFalse(any(isinstance(w, ttk.Button) and '差枚で優・良を入れる' in w.cget('text') for w in children(window)))
                    self.assertEqual(saved()[VARIETY_KEY]['cells'], [], '自動の優・良は保存しない')
                    self.assertEqual(labels().count('優'), 1)
                    self.assertEqual(labels().count('良'), 1)
                    # 最終記録日10/19まで5日：機種Aは+2500枚、機種Bは0枚で赤字。
                    self.assertEqual([t.split()[0] for t in red() if '台' in t], ['機種B'])
                    selector = next(w for w in children(window) if isinstance(w, ttk.Combobox) and tuple(w.cget('values')) == ('自動', '優', '良'))
                    self.assertEqual(selector.get(), '自動')
                    selector.set('良'); selector.event_generate('<<ComboboxSelected>>')
                    self.assertEqual({c['machine']: c['value'] for c in saved()[VARIETY_KEY]['cells']}, {'機種A': '良'})
                    self.assertEqual(labels().count('優'), 0, '手入力した日は自動の値を出さない')
                    self.assertEqual(saved()['cells'], [])
                    selector = next(w for w in children(window) if isinstance(w, ttk.Combobox) and w.get() == '良')
                    selector.set('自動'); selector.event_generate('<<ComboboxSelected>>')
                    self.assertEqual({c['machine']: c['value'] for c in saved()[VARIETY_KEY]['cells']}, {'機種A': ''}, '「自動」は空欄として保存')
                    self.assertEqual(labels().count('優'), 1)
                    selectors = [w for w in children(window) if isinstance(w, ttk.Combobox) and tuple(w.cget('values')) == ('自動', '優', '良')]
                    selectors[7].set('優'); selectors[7].event_generate('<<ComboboxSelected>>')  # 機種Bの月曜
                    self.assertEqual([t for t in red() if '台' in t], [], '手入力の優は+800枚を超えた日と数える')
                    button('→').invoke()
                    self.assertEqual(picked, [('機種A', MONDAY)])
                nagamachi = open_event_history(root, lambda *_: None, db_path=path)
                self.assertFalse(any(isinstance(w, ttk.Button) and '差枚で優・良を入れる' in w.cget('text') for w in children(nagamachi)))
                self.assertTrue(any(isinstance(w, ttk.Button) and w.cget('text') == 'この日の差枚で顔文字を入れる' for w in children(nagamachi)))
            finally:
                root.destroy()
