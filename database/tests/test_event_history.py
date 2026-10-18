import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import Store, export_backup, import_backup, auto_backup, save_settings
from event_history_data import (load_base, validate_base, empty_edits, merge_edits,
    materialize, saved_name, variety_week_lineup, FILE_NAME)


def cell(base, value='😀', at='2026-10-19T00:00:00Z', device='android'):
    w = base['weeks'][0]
    return dict(store=base['store'], type=w['type'], week=w['from'], machine=w['machines'][0]['name'],
                day=w['from'], value=value, updated_at=at, device=device)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.base = load_base()

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
                selector.set('😍');selector.event_generate('<<ComboboxSelected>>')
                db=Store(path)
                try: self.assertEqual(db.history_edits()['cells'][0]['value'],'😍')
                finally: db.close()
                window.flush_history()
                next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='閉じる').invoke()
                self.assertEqual(flushed,[True])
            finally: root.destroy()

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
