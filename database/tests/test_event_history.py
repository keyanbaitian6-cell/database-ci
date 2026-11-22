import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import Store, export_backup, import_backup, auto_backup, save_settings
from event_history_data import (load_base, validate_base, empty_edits, merge_edits,
    materialize, saved_name, variety_week_lineup, capture_shortfall, FILE_NAME,
    net_face, auto_faces, machine_day_nets, clean_edits, saiwaichou_base)


def cell(base, value='😀', at='2026-10-19T00:00:00Z', device='android'):
    w = base['weeks'][0]
    return dict(store=base['store'], type=w['type'], week=w['from'], machine=w['machines'][0]['name'],
                day=w['from'], value=value, updated_at=at, device=device)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.base = load_base()

    def tearDown(self):
        import gc
        gc.collect()  # Tcl_AsyncDelete 対策：破棄した Tk を別スレッドの GC へ持ち越さない

    def test_capacity_rejects_growth_without_losing_saved_history_and_allows_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder)/'test.db')
            try:
                full = dict(empty_edits(), cells=[{'orphan': i} for i in range(29999)] + [cell(self.base)])
                with db.db:
                    db._write_history_edits(full)
                before = db.state('event_history_edits')
                incoming = dict(empty_edits(), cells=[dict(cell(self.base), day=self.base['weeks'][0]['to'])])
                with self.assertRaisesRegex(ValueError, '上限'):
                    db.merge_history_edits(incoming)
                self.assertEqual(db.state('event_history_edits'), before)
                self.assertNotIn('unreadable_raw', db.history_edits_raw())
                replacement = dict(empty_edits(), cells=[cell(self.base, '😍', '2026-10-20T00:00:00Z')])
                db.merge_history_edits(replacement)
                self.assertEqual(len(db.history_edits_raw()['cells']), 30000)
                self.assertEqual(db.history_edits()['cells'][0]['value'], '😍')
            finally:
                db.close()

    def test_direct_history_write_rejects_an_unreadable_envelope_before_saving(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder)/'test.db')
            try:
                before = db.state('event_history_edits')
                with self.assertRaises(ValueError):
                    with db.db:
                        db._write_history_edits(dict(empty_edits(), cells=[None] * 30001))
                self.assertEqual(db.state('event_history_edits'), before)
            finally:
                db.close()

    def test_reject_invalid_week_symbol_and_duplicate(self):
        for change in ('monday', 'symbol', 'duplicate'):
            base = copy.deepcopy(self.base)
            if change == 'monday': base['weeks'][0]['from'] = '2026-08-25'
            if change == 'symbol': base['weeks'][0]['machines'][0]['results'][0] = '任意文字列'
            if change == 'duplicate': base['weeks'].append(base['weeks'][0])
            with self.subTest(change=change), self.assertRaises(ValueError): validate_base(base)

    def test_different_cells_survive_and_blank_is_an_edit(self):
        old, fresh = empty_edits(), empty_edits()
        old['cells'] = [cell(self.base, device='pc')]
        fresh['cells'] = [cell(self.base, '', '2026-10-19T00:00:01Z')]
        merged, changed, conflicts, rejected, _ = merge_edits(old, fresh, self.base)
        self.assertEqual((changed, conflicts, rejected), (1, 1, 0))
        self.assertEqual(merged['cells'][0]['value'], '')
        next_cell = cell(self.base, '😍'); next_cell['day'] = '2026-08-25'
        fresh['cells'] = [next_cell]
        merged, *_ = merge_edits(merged, fresh, self.base)
        self.assertEqual(len(merged['cells']), 2)

    def test_older_edit_does_not_replace_newer(self):
        old, fresh = empty_edits(), empty_edits()
        old['cells'] = [cell(self.base, '', '2026-10-19T00:00:01Z', 'pc')]
        fresh['cells'] = [cell(self.base)]
        merged, changed, conflicts, _, _ = merge_edits(old, fresh, self.base)
        self.assertEqual((changed, conflicts), (0, 0))
        self.assertEqual(merged['cells'][0]['value'], '')

    def test_bad_cell_cannot_create_unknown_week_or_symbol(self):
        fresh = empty_edits(); fresh['cells'] = [cell(self.base, '<script>')]
        merged, changed, _, rejected, _ = merge_edits(empty_edits(), fresh, self.base)
        self.assertEqual((changed, rejected), (0, 1))
        self.assertFalse(merged['cells'])

    def test_machine_names_are_never_guessed(self):
        item = dict(name='L甲鉄城のカバネリ', record_name=None)
        names = {'L 甲鉄城のｶﾊﾞﾈﾘ'}
        self.assertIsNone(saved_name(item, names))
        item['record_name'] = next(iter(names))
        self.assertEqual(saved_name(item, names), item['record_name'])
        self.assertIsNone(saved_name(item, set()))

    def test_lineup_uses_first_sufficient_day_and_freezes(self):
        records = [dict(store='nagamachiminami', day=d, machine='機種A' if i < 2 else '機種B', rack=i)
                   for d,n in [('2026-10-11',10), ('2026-10-12',3), ('2026-10-13',10), ('2026-10-16',10)] for i in range(n)]
        lineup, machines, doubtful = variety_week_lineup(records, '2026-10-12')
        self.assertEqual(lineup, '2026-10-13')
        self.assertEqual(machines, [dict(name='機種A', record_name='機種A', count=2)])
        incoming = empty_edits(); incoming['weeks'] = [dict(store='nagamachiminami', type='バラエティ', week='2026-10-12',
            lineup_day=lineup, machines=machines, updated_at='2026-10-19T00:00:00Z', removed=False)]
        incoming['cells'] = [dict(cell(self.base), type='バラエティ', week='2026-10-12', machine='機種A', day='2026-10-13')]
        merged, _, _, bad, _ = merge_edits(empty_edits(), incoming, self.base)
        self.assertEqual(bad, 0)
        week = next(w for w in materialize(self.base, merged)[0] if w['type']=='バラエティ')
        self.assertEqual(week['lineup_day'], lineup)
        self.assertEqual(week['machines'][0]['results'][1], '😀')

    def test_four_rack_week_is_created_on_pc_and_shown(self):
        # 2026-11-17 利用者「PCで作れるように」：長町南の4台構成の週表をPCで作る。分類日に設置ちょうど4台の機種だけ。
        def rows(d, layout):
            out, rack = [], 1
            for name, n in layout:
                for _ in range(n):
                    out.append(dict(store='nagamachiminami', day=d, machine=name, rack=rack)); rack += 1
            return out
        usual = [('四台A', 4), ('四台B', 4), ('三台', 3), ('五台', 5), ('欠けた四台', 4)]
        records = rows('2026-11-15', usual) + rows('2026-11-16', [('四台A', 4), ('四台B', 4), ('三台', 3), ('五台', 5), ('欠けた四台', 3)])
        lineup, machines, doubtful = variety_week_lineup(records, '2026-11-16', kind='4台構成')
        self.assertEqual(lineup, '2026-11-16')
        self.assertEqual([m['name'] for m in machines], ['四台A', '四台B'])
        self.assertTrue(all(m['count'] == 4 for m in machines))
        self.assertEqual(doubtful, ['欠けた四台'], '周辺の日に4台あったのに3台以下の機種は、作る前に知らせる')
        week = dict(store='nagamachiminami', type='4台構成', week='2026-11-16', lineup_day=lineup, machines=machines,
                    updated_at='2026-11-17T00:00:00Z', removed=False)
        incoming = empty_edits(); incoming['weeks'] = [week]
        incoming['cells'] = [dict(cell(self.base), type='4台構成', week='2026-11-16', machine='四台A', day='2026-11-18')]
        merged, _, _, bad, _ = merge_edits(empty_edits(), incoming, self.base)
        self.assertEqual(bad, 0)
        shown = next(w for w in materialize(self.base, merged)[0] if w['from'] == '2026-11-16')
        self.assertEqual((shown['type'], shown['to'], shown['lineup_day']), ('4台構成', '2026-11-22', '2026-11-16'))
        self.assertEqual(shown['machines'][0]['results'][2], '😀')
        # 台数が4でない機種・同じ週の別の種類・幸町の4台構成は受け付けない。
        for bad_week in (dict(week, machines=[dict(machines[0], count=3)]),
                         dict(week, week='2026-10-05'),                     # 元データの4台構成の週と重なる
                         dict(week, week='2026-09-28')):                    # 元データの半列の週
            other = empty_edits(); other['weeks'] = [bad_week]
            self.assertEqual(clean_edits(other, self.base)[1], 1, bad_week)
        variety_then_four = empty_edits()
        variety_then_four['weeks'] = [dict(week, type='バラエティ', machines=[dict(name='三台', record_name='三台', count=3)]), week]
        cleaned, rejected = clean_edits(variety_then_four, self.base)
        self.assertEqual((len(cleaned['weeks']), rejected), (1, 1), '1週に1種類')
        saiwai = dict(saiwaichou_base()); saiwai_edits = empty_edits()
        saiwai_edits['weeks'] = [dict(week, store='saiwaichou')]
        self.assertEqual(clean_edits(saiwai_edits, saiwai)[1], 1)

    def test_backup_round_trip_and_private_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a, b = Store(root/'a.db'), Store(root/'b.db')
            try:
                incoming = empty_edits(); incoming['cells'] = [cell(self.base)]
                a.merge_history_edits(incoming)
                backup = root/'backup.json'; export_backup(a, backup)
                plan = import_backup(b, backup)
                self.assertEqual(plan['history_added'], 1)
                self.assertEqual(a.history_edits(), b.history_edits())
                sync = root/'sync'; sync.mkdir()
                save_settings(root, sync_dir=str(sync))
                auto_backup(b, root, strict=True)
                private = json.loads((sync/FILE_NAME).read_text(encoding='utf-8'))
                self.assertEqual(private['base'], self.base)
                self.assertEqual(private['cells'], b.history_edits()['cells'])
            finally:
                a.close(); b.close()

    def test_invalid_history_item_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = Store(root/'data.db')
            try:
                edits=empty_edits(); edits['cells']=[cell(self.base, '<script>')]
                backup=root/'invalid.json'
                backup.write_text(json.dumps(dict(format='database-backup',version=1,records=[],event_history_edits=edits)),encoding='utf-8')
                plan=import_backup(db,backup)
                self.assertEqual(plan['history_rejected'],1)
                self.assertEqual(db.history_edits(),empty_edits())
            finally: db.close()

    def test_pc_blank_cell_opens_same_day_and_dropdown_saves(self):
        import tkinter as tk
        from tkinter import ttk
        from event_history import open_event_history
        with tempfile.TemporaryDirectory() as temp:
            root_path = Path(temp)
            base = dict(version=2,store='nagamachiminami',symbols=['😀','😍'],weeks=[
                dict(type='4台構成', **{'from':'2026-10-05','to':'2026-10-11'},
                     machines=[dict(name='テスト機種',record_name=None,count=4,results=['']*7)])])
            # 保存処理は通常の基準JSONで検証するため、実際の基準にある機種名を使う。
            base['weeks'][0]['machines'][0]['name'] = self.base['weeks'][-1]['machines'][0]['name']
            base['symbols'] = self.base['symbols']
            source = root_path/'history.json'; source.write_text(json.dumps(base),encoding='utf-8')
            path=root_path/'fixture.db'; db=Store(path)
            try:
                db.save([dict(store='nagamachiminami',kind_code=21,day='2026-10-05',machine=base['weeks'][0]['machines'][0]['name'],rack=1,games=1000,bb=4,rb=2,max_hold=100)])
            finally: db.close()
            root=tk.Tk();root.withdraw()
            picked, flushed = [], []
            try:
                window=open_event_history(root,lambda n,d:picked.append((n,d)),db_path=path,path=source,on_changed=lambda:flushed.append(True))
                window.withdraw();root.update_idletasks()
                def children(parent):
                    for w in parent.winfo_children():
                        yield w
                        yield from children(w)
                widgets=list(children(window))
                next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='→').invoke()
                self.assertEqual(picked[0][1],'2026-10-05')
                selector=next(w for w in widgets if isinstance(w,ttk.Combobox) and '😍' in w.cget('values'))
                selector.set('😍');selector.event_generate('<<ComboboxSelected>>');root.update()
                db=Store(path)
                try: self.assertEqual(db.history_edits()['cells'][0]['value'],'😍')
                finally: db.close()
                window.flush_history()
                next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='閉じる').invoke()
                self.assertEqual(flushed,[True])
            finally: root.destroy()

    def test_pc_variety_name_color_tracks_each_week_and_last_heart_removal(self):
        import tkinter as tk
        from tkinter import ttk
        from event_history import open_event_history

        def week(kind, first, last, results):
            return dict(type=kind, **{'from': first, 'to': last}, machines=[
                dict(name='テスト機種', record_name=None, count=1, results=results)])

        base = dict(version=2, store='nagamachiminami', symbols=['😀', '😍'], weeks=[
            week('4台構成', '2026-09-28', '2026-10-04', [''] * 7),
            week('バラエティ', '2026-10-05', '2026-10-11', [''] * 6 + ['😍']),
            week('バラエティ', '2026-10-12', '2026-10-18', [''] * 7)])

        def descendants(parent):
            for widget in parent.winfo_children():
                yield widget
                yield from descendants(widget)

        with tempfile.TemporaryDirectory() as folder, patch('event_history_data.load_base', return_value=base), \
                patch('event_history.load_base', return_value=base):
            root = tk.Tk(); root.withdraw()
            try:
                window = open_event_history(root, lambda *_: None, db_path=Path(folder) / 'test.db')
                def labels():
                    return [w for w in descendants(window) if isinstance(w, ttk.Label)
                            and str(w.cget('text')).startswith('テスト機種')]
                def red():
                    return str(labels()[0].cget('foreground')) == '#b91c1c'
                def select(combo, value):
                    combo.set(value); combo.event_generate('<<ComboboxSelected>>'); root.update_idletasks()

                self.assertFalse(red(), '4台構成は😍が無くても通常色')
                combos = [w for w in descendants(window) if isinstance(w, ttk.Combobox)]
                select(combos[0], 'バラエティ')
                select(combos[1], '2026-10-05〜2026-10-11')
                self.assertFalse(red(), '日曜の😍もその週の達成として数える')
                select(combos[1], '2026-10-12〜2026-10-18')
                self.assertTrue(red(), '別の週の😍は数えない')
                symbols = [w for w in descendants(window) if isinstance(w, ttk.Combobox)
                           and '😍' in w.cget('values')]
                select(symbols[0], '😍'); self.assertFalse(red())
                select(symbols[6], '😍'); self.assertFalse(red())
                select(symbols[0], '😀'); self.assertFalse(red(), 'まだ日曜の😍が残る')
                select(symbols[6], ''); self.assertTrue(red(), '最後の😍を消すと即座に赤字に戻る')
            finally:
                root.destroy()

    def test_week_definition_cannot_orphan_existing_cells(self):
        week = dict(store='nagamachiminami',type='バラエティ',week='2026-10-12',lineup_day='2026-10-12',
                    machines=[dict(name='機種A',record_name='機種A',count=2)],removed=False,updated_at='2026-10-19T00:00:00Z')
        old, incoming = empty_edits(), empty_edits()
        old['weeks'] = [week]
        incoming['weeks'] = [dict(week,lineup_day='2026-10-13',updated_at='2026-10-19T00:00:01Z')]
        merged, changed, conflicts, bad, skipped = merge_edits(old,incoming,self.base)
        self.assertEqual(merged['weeks'][0]['lineup_day'], '2026-10-12')
        self.assertEqual((changed, conflicts, bad, skipped), (0, 0, 0, 1))

    def test_common_fixture_across_languages(self):
        doc=json.loads((Path(__file__).resolve().parents[2]/'database_android/test/fixtures/event_history_cases.json').read_text('utf-8'))
        weeks,bad=materialize(doc['base'],doc)
        summary=dict(rejected=bad,weeks=[dict(type=w['type'], **{'from':w['from']},results=[m['results'] for m in w['machines']],links=[m['record_name'] for m in w['machines']]) for w in weeks])
        self.assertEqual(summary,doc['expected'])

    def test_transcribed_names_match_saved_names_exactly(self):
        names=json.loads((Path(__file__).resolve().parents[2]/'database_android/test/fixtures/event_history_saved_names.json').read_text('utf-8'))
        for w in self.base['weeks']:
            if w['from'] in ('2026-09-28','2026-10-05'):
                self.assertTrue(all(m['name'] in names for m in w['machines']))

    def test_partial_machine_is_reported_before_freezing(self):
        records=[dict(store='nagamachiminami',day=d,machine='欠けた機種' if i<n else '通常',rack=i)
                 for d,n in [('2026-10-11',4),('2026-10-12',1)] for i in range(20)]
        _,_,doubtful=variety_week_lineup(records,'2026-10-12')
        self.assertEqual(doubtful,['欠けた機種'])

    def test_conflicting_week_does_not_stop_record_import(self):
        week=dict(store='nagamachiminami',type='バラエティ',week='2026-10-12',lineup_day='2026-10-12',machines=[dict(name='A',record_name='A',count=2)],removed=False,updated_at='2026-10-19T00:00:00Z')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=Store(root/'a.db')
            try:
                old=empty_edits();old['weeks']=[week];db.merge_history_edits(old)
                incoming=empty_edits();incoming['weeks']=[dict(week,machines=[dict(name='B',count=1)])]
                incoming['cells']=[dict(store='nagamachiminami',type='バラエティ',week=week['week'],machine='B',day=week['week'],value='😀',updated_at=week['updated_at'])]
                record=dict(store='nagamachiminami',kind_code=21,day='2026-10-18',machine='通常',rack=1,games=1000,bb=4,rb=2,max_hold=100)
                backup=root/'incoming.json';backup.write_text(json.dumps(dict(format='database-backup',version=1,records=[record],event_history_edits=incoming)),encoding='utf-8')
                plan=import_backup(db,backup)
                self.assertEqual(plan['history_week_conflicts'],1)
                self.assertEqual(plan['history_rejected'],1)
                self.assertEqual(len(db.rows()),1)
                self.assertEqual(db.history_edits()['weeks'][0]['machines'][0]['name'],'A')
            finally:db.close()

    def test_base_name_change_preserves_raw_backup_delete_undo(self):
        from core import delete_records,undo_last_save,RECENT_BACKUP_NAME,VIEWER_FILE_NAME
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=Store(root/'a.db');sync=root/'sync';sync.mkdir()
            try:
                edits=empty_edits();edits['cells']=[cell(self.base)];db.merge_history_edits(edits)
                raw=db.history_edits_raw()
                db.save([dict(store='nagamachiminami',kind_code=21,day='2026-10-18',machine='通常',rack=1,games=1000,bb=4,rb=2,max_hold=100)])
                changed=copy.deepcopy(self.base);changed['weeks'][0]['machines'][0]['name']='新しい保存名'
                save_settings(root,sync_dir=str(sync))
                with patch('event_history_data.load_base',return_value=changed):
                    self.assertEqual(db.history_edits_status()[1],1)
                    backup=root/'raw.json';export_backup(db,backup)
                    self.assertEqual(json.loads(backup.read_text('utf-8'))['event_history_edits'],raw)
                    auto_backup(db,root,strict=True)
                    self.assertTrue((sync/RECENT_BACKUP_NAME).exists())
                    self.assertEqual(delete_records(db,root,'2026-10-18','nagamachiminami'),1)
                    undo_last_save(db,root)
                    self.assertEqual(db.history_edits_raw(),raw)
                    self.assertEqual(len(db.rows()),1)
                with patch('event_history_data.load_base',side_effect=ValueError('基準不正')):
                    notices=[];auto_backup(db,root,strict=True,notices=notices)
                    self.assertTrue(notices)
                    self.assertTrue((sync/VIEWER_FILE_NAME).exists())
            finally:db.close()

    def test_broken_history_envelope_still_exports_an_importable_backup(self):
        # 外枠の壊れた履歴をそのまま書くと、バックアップ全体が取り込み・復元できなくなる（2026-10-19 Claudeレビュー中1）。
        record=dict(store='nagamachiminami',kind_code=21,day='2026-10-18',machine='通常',rack=1,games=1000,bb=4,rb=2,max_hold=100)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=Store(root/'a.db');other=Store(root/'b.db')
            try:
                db.save([record])
                with db.db: db.db.execute('INSERT OR REPLACE INTO app_state VALUES(?,?)',('event_history_edits','{"cells":"壊れた"}'))
                backup=root/'broken.json';export_backup(db,backup)
                exported=json.loads(backup.read_text('utf-8'))['event_history_edits']
                self.assertEqual(exported['unreadable_raw'],'{"cells":"壊れた"}')
                plan=import_backup(other,backup)
                self.assertEqual(len(other.rows()),1)
                self.assertIn('history_error',plan)
            finally:
                db.close();other.close()

    def test_superseded_orphan_is_dropped(self):
        # 基準から消えた記号の古い編集は、同じセルを正しく直したら消える（2026-10-19 Claudeレビュー中2）。
        removed=copy.deepcopy(self.base);removed['symbols']=[s for s in removed['symbols'] if s!='😇']
        for w in removed['weeks']:
            for m in w['machines']: m['results']=['' if v=='😇' else v for v in m['results']]
        old=empty_edits();old['cells']=[cell(self.base,'😇','2026-10-19T01:00:00+09:00','pc')]
        fresh=empty_edits();fresh['cells']=[cell(removed,'😀','2026-10-19T02:00:00+09:00','pc')]
        merged,_,_,rejected,_=merge_edits(old,fresh,removed)
        self.assertEqual(rejected,1)
        self.assertEqual([c['value'] for c in merged['cells']],['😀'])
        _,_,_,rejected,_=merge_edits(merged,empty_edits(),removed)
        self.assertEqual(rejected,0)
        older=empty_edits();older['cells']=[cell(self.base,'😇','2026-10-19T03:00:00+09:00','pc')]
        kept,*_=merge_edits(older,empty_edits(),removed)
        self.assertEqual([c['value'] for c in kept['cells']],['😇'])

    def test_net_face_bands(self):
        # 利用者指定（2026-10-21）：+3000以上＝😍、1000〜2999＝😀、0〜999＝😌、マイナス＝🥶。境目の値を固定する。
        for total, face in [(5000,'😍'),(3000,'😍'),(2999,'😀'),(1000,'😀'),(999,'😌'),(0,'😌'),(-1,'🥶'),(-8000,'🥶')]:
            self.assertEqual(net_face(total), face, total)
        self.assertTrue({'😍','😀','😌','🥶'} <= set(self.base['symbols']))

    def test_auto_faces_fill_only_blank_cells_with_known_net(self):
        week = dict(type='バラエティ', **{'from':'2026-10-12','to':'2026-10-18'}, machines=[
            dict(name='A', record_name='A', count=2, results=['','😍','','','','','']),
            dict(name='B', record_name='B', count=1, results=['']*7)])
        nets = {('2026-10-12','A'):3500, ('2026-10-13','A'):-500, ('2026-10-14','A'):1200,
                ('2026-10-12','B'):500, ('2026-10-14','B'):-1}
        names = {'2026-10-12':{'A','B'}, '2026-10-13':{'A'}, '2026-10-14':{'A','B'}, '2026-10-15':{'B'}}
        cells, skipped = auto_faces(week, nets, names, self.base['symbols'])
        self.assertEqual(sorted(cells), [('A','2026-10-12','😍'),('A','2026-10-14','😀'),('B','2026-10-12','😌'),('B','2026-10-14','🥶')])
        # 入力済みの10/13のAは変えない。10/15のBは記録はあるが差枚が分からないので空欄のまま数える。記録の無い日は数えない。
        self.assertEqual(skipped, 1)
        cells, _ = auto_faces(week, nets, names, self.base['symbols'], blank_days=('2026-10-12',))
        self.assertNotIn('2026-10-12', {d for _m, d, _f in cells})

    def test_machine_day_net_needs_every_rack(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Store(Path(temp)/'nets.db')
            try:
                row = lambda day, machine, rack, **kw: dict(store='nagamachiminami', kind_code=21, day=day, machine=machine, rack=rack, games=1000, bb=4, rb=2, max_hold=100, **kw)
                db.save([row('2026-10-12','機種A',1,jo_net=1500), row('2026-10-12','機種A',2,jo_net=-200),
                         row('2026-10-12','機種B',1,jo_net=900), row('2026-10-12','機種B',2)])
                nets = machine_day_nets(db, '2026-10-12', '2026-10-18')
            finally:
                db.close()
            self.assertEqual(nets.get(('2026-10-12','機種A')), 1300)
            # 機種Bは1台の差枚が分からない。一部だけの合計は出さない。
            self.assertNotIn(('2026-10-12','機種B'), nets)

    def test_pc_auto_insert_works_on_four_and_half_row_weeks(self):
        # 利用者の追加指示（2026-10-21）：4台構成・半列の週表にも同じ自動挿入を出す。
        import tkinter as tk
        from tkinter import ttk
        from unittest.mock import patch
        from event_history import open_event_history
        week = next(w for w in self.base['weeks'] if w['type'] == '4台構成' and w['from'] == '2026-10-05')
        name = week['machines'][0]['name']
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'history.json'; source.write_text(json.dumps(self.base), encoding='utf-8')
            path = Path(temp)/'fixture.db'; db = Store(path)
            try:
                row = lambda rack, net: dict(store='nagamachiminami', kind_code=21, day='2026-10-11', machine=name, rack=rack, games=1000, bb=4, rb=2, max_hold=100, jo_net=net)
                db.save([row(1, 1800), row(2, 1700), row(3, 100), row(4, -500)])
            finally:
                db.close()
            root = tk.Tk(); root.withdraw()
            try:
                window = open_event_history(root, lambda n, d: None, db_path=path, path=source)
                window.withdraw(); root.update_idletasks()
                def children(parent):
                    for w in parent.winfo_children():
                        yield w
                        yield from children(w)
                widgets = list(children(window))
                button = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == 'この日の差枚で顔文字を入れる')
                day_box = next(w for w in widgets if isinstance(w, ttk.Combobox) and '2026-10-11 日' in str(w.cget('values')))
                self.assertEqual(day_box.get(), '2026-10-11 日')  # 既定は記録のある最後の日。10/5〜10/10は入力済み
                with patch('event_history.messagebox.askyesno', return_value=True), patch('event_history.messagebox.showinfo'):
                    button.invoke()
                # 合計3100＝😍。入力済みの他の日・他の機種には入れない。
                self.assertEqual(self._saved_faces(path), {'2026-10-11': '😍'})
            finally:
                root.destroy()

    @staticmethod
    def _saved_faces(path):
        db = Store(path)
        try:
            return {c['day']: c['value'] for c in db.history_edits()['cells']}
        finally:
            db.close()

    def test_pc_auto_insert_button_saves_faces_and_keeps_manual_cells(self):
        import tkinter as tk
        from tkinter import ttk
        from unittest.mock import patch
        from event_history import open_event_history
        with tempfile.TemporaryDirectory() as temp:
            root_path = Path(temp)
            name = self.base['weeks'][-1]['machines'][0]['name']
            # 実際の基準にバラエティの週は無い。週表の作成と同じく、週の定義を編集として保存する。
            base = dict(self.base)
            source = root_path/'history.json'; source.write_text(json.dumps(base), encoding='utf-8')
            path = root_path/'fixture.db'; db = Store(path)
            try:
                row = lambda day, rack, net: dict(store='nagamachiminami', kind_code=21, day=day, machine=name, rack=rack, games=1000, bb=4, rb=2, max_hold=100, jo_net=net)
                week = dict(store='nagamachiminami', type='バラエティ', week='2026-10-12', lineup_day='2026-10-12', removed=False,
                            machines=[dict(name=name, record_name=name, count=2)], updated_at='2026-10-20T00:00:00+09:00', device='pc')
                db.merge_history_edits(dict(empty_edits(), weeks=[week]))
                db.save([row('2026-10-12',1,2000), row('2026-10-12',2,1500), row('2026-10-13',1,-300), row('2026-10-13',2,100)])
            finally:
                db.close()
            root = tk.Tk(); root.withdraw()
            try:
                window = open_event_history(root, lambda n, d: None, db_path=path, path=source)
                window.withdraw(); root.update_idletasks()
                def children(parent):
                    for w in parent.winfo_children():
                        yield w
                        yield from children(w)
                widgets = list(children(window))
                button = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == 'この日の差枚で顔文字を入れる')
                self.assertEqual(button.master.winfo_manager(), 'pack')  # 4台構成・半列・バラエティのどの週表にも出す
                kind_box = next(w for w in widgets if isinstance(w, ttk.Combobox) and 'バラエティ' in w.cget('values'))
                kind_box.set('バラエティ'); kind_box.event_generate('<<ComboboxSelected>>'); root.update()
                self.assertEqual(button.master.winfo_manager(), 'pack')
                widgets = list(children(window))  # 再描画で表の部品が作り直される
                day_box = next(w for w in widgets if isinstance(w, ttk.Combobox) and '2026-10-12 月' in str(w.cget('values')))
                self.assertEqual(day_box.get(), '2026-10-13 火')  # 既定は記録のある最後の日
                saved = lambda: self._saved_faces(path)
                with patch('event_history.messagebox.askyesno', return_value=True), patch('event_history.messagebox.showinfo'):
                    button.invoke()
                    # 選んだ日だけに入る：10/13は合計-200＝🥶、10/12にはまだ入れない。
                    self.assertEqual(saved(), {'2026-10-13': '🥶'})
                    day_box.set('2026-10-12 月'); button.invoke()
                    self.assertEqual(saved(), {'2026-10-12': '😍', '2026-10-13': '🥶'})  # 10/12は合計3500＝😍
                    # 押し直しても入力済みのセルは変えない。記録の無い日は入れない。
                    day_box.set('2026-10-15 木'); button.invoke()
                    self.assertEqual(saved(), {'2026-10-12': '😍', '2026-10-13': '🥶'})
            finally:
                root.destroy()

    def test_thin_capture_period_is_reported(self):
        # 週と前13日がまるごと取り込み不足だと、週内の8割判定は素通りする（2026-10-19 Claudeレビュー中3。実例 9/14〜21）。
        rows=lambda d,n:[dict(store='nagamachiminami',day=d,machine=f'機種{i//4}',rack=i) for i in range(n)]
        records=rows('2026-09-15',60)+rows('2026-09-22',372)
        self.assertEqual(capture_shortfall(records,'2026-09-15'),(60,372))
        self.assertIsNone(capture_shortfall(records,'2026-09-22'))
        self.assertIsNone(capture_shortfall(rows('2026-08-01',372)+rows('2026-09-15',60),'2026-09-15'))

    def test_viewer_stage_excludes_private_history_asset(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('history_stage_viewer',Path(__file__).resolve().parents[2]/'database_android/tool/stage_viewer.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'build';assets=source/'assets/assets';assets.mkdir(parents=True)
            (source/'index.html').write_text('<html></html>',encoding='utf-8')
            (assets/'event_history.json').write_text('{"private":true}',encoding='utf-8')
            (assets/'database_seed.json').write_text('{"rows":[]}',encoding='utf-8')
            module.BUILD=source;module.SEED=assets/'database_seed.json'
            target=root/'public';module.main(target)
            self.assertTrue((target/'index.html').exists())
            self.assertFalse(list(target.rglob('event_history.json')))
            self.assertTrue((assets/'event_history.json').exists())


if __name__ == '__main__': unittest.main()
