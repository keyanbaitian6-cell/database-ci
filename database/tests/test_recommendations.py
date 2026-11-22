import json
from pathlib import Path
import tempfile
import unittest

import recommendations as rec
from core import Store, pull_shared_history, SHARED_HISTORY_NAME
from event_history_data import empty_edits, load_base, clean_edits


class RecommendationTests(unittest.TestCase):
    def tearDown(self):
        import gc
        gc.collect()  # Tcl_AsyncDelete 対策：破棄した Tk を別スレッドの GC へ持ち越さない

    def plan(self, **changes):
        return dict(rec.DEFAULT, machines=['機種A', '機種B', '機種C', '機種D'], **changes)

    def test_default_is_poster_week_and_four_distinct_machines(self):
        p = rec.plans()[0]
        self.assertEqual(rec.days(p['week']), ['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30', '2026-10-31', '2026-11-01'])
        self.assertEqual(len(set(p['machines'])), 4)

    def test_rejects_non_monday_duplicates_other_store_and_invalid_clock(self):
        for raw in [dict(self.plan(),week='2026-10-27'),dict(self.plan(),machines=['A','A','B','C']),dict(self.plan(),machines=['A','B','C']),dict(self.plan(),store='saiwaichou'),dict(self.plan(),updated_at='2026-02-30T00:00:00Z'),dict(self.plan(),updated_at='2026-10-25T24:00:00Z')]:
            with self.assertRaises(ValueError):rec.plan(raw)

    def test_merge_keeps_microseconds_other_weeks_and_invalid_original(self):
        old=self.plan(updated_at='2026-10-25T09:00:00.123456+09:00')
        new=dict(old,machines=['別A','別B','別C','別D'],updated_at='2026-10-25T00:00:00.123457Z')
        other=self.plan(week='2026-11-02')
        raw={'壊れた原文':True}
        merged=rec.merge([old,other,raw],[new])
        self.assertEqual(next(p for p in merged if p.get('week')==old['week']),new)
        self.assertIn(other,merged);self.assertIn(raw,merged)
        self.assertEqual(rec.merge(merged,[old]),merged)

    def test_candidates_use_latest_single_snapshot_seven_distinct_racks_and_scope(self):
        records=[dict(store='nagamachiminami',day='2026-10-25',machine=name,rack=i) for name,count in [('7台',7),('6台',6)] for i in range(count)]
        records += [dict(records[-1])]*10
        records += [dict(store='saiwaichou',day='2026-10-25',machine='他店',rack=i) for i in range(10)]
        records += [dict(store='nagamachiminami',day='2026-11-02',machine='未来',rack=i) for i in range(20)]
        self.assertEqual(rec.candidates(records,'2026-10-26'),('2026-10-25',[('7台',7)]))
        records.append(dict(store='nagamachiminami',day='2026-10-26',machine='一部',rack=100))
        self.assertEqual(rec.candidates(records,'2026-10-26'),('2026-10-26',[]))

    def test_rows_are_per_rack_and_day_not_blocked_by_missing_days(self):
        rows=[dict(store='nagamachiminami',day=d,machine='機種 A' if i==0 else '機種+A',rack=10,jo_net=net) for i,(d,net) in enumerate([('2026-10-26',0),('2026-10-28',3000)])]
        rows += [dict(rows[0],store='saiwaichou',rack=999),dict(rows[0],machine='別機種',rack=888)]
        result=rec.rows(rows,'2026-10-26','機種 A')
        self.assertEqual([r for r,_ in result],[10]);self.assertEqual(result[0][1][0]['jo_net'],0)
        self.assertIsNone(result[0][1][1]);self.assertEqual(result[0][1][2]['jo_net'],3000)
        rows.append(dict(rows[0],jo_net=9000))
        self.assertIsNone(rec.rows(rows,'2026-10-26','機種 A')[0][1][0])

    def test_shared_selection_survives_store_backup_clean_and_other_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Store(Path(temp)/'data.sqlite3')
            try:
                entry=self.plan()
                payload=dict(empty_edits(),recommendations=[entry])
                Path(temp,SHARED_HISTORY_NAME).write_text(json.dumps(payload),encoding='utf-8')
                self.assertEqual(pull_shared_history(db,temp)[0],1)
                self.assertEqual(db.history_edits()['recommendations'],[entry])
                db.merge_history_edits(empty_edits())
                self.assertEqual(db.history_edits_raw()['recommendations'],[entry])
                raw=db.history_edits_raw()
                self.assertEqual(clean_edits(raw,load_base())[0]['recommendations'],[entry])
            finally:db.close()

    def test_pc_table_uses_four_selectors_and_saves_without_changing_old_weeks(self):
        import tkinter as tk
        from tkinter import ttk
        from event_history import open_event_history
        root=tk.Tk();root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'db.sqlite3'
                db=Store(path)
                try:
                    for m,name in enumerate([*rec.DEFAULT['machines'],'候補7台','候補6台']):
                        for i in range(6 if name=='候補6台' else 7):
                            row=dict(store='nagamachiminami',day='2026-10-26',machine=name,rack=m*100+i+1,games=1000,bb=4,rb=2,jo_net=0)
                            db.db.execute('INSERT INTO days VALUES(?,?,?,?,?)',(row['store'],row['day'],name,row['rack'],json.dumps(row)))
                    db.db.commit()
                finally:db.close()
                window=open_event_history(root,lambda *_:None,db_path=path)
                def widgets(w):
                    for child in w.winfo_children():
                        yield child;yield from widgets(child)
                combo=next(w for w in widgets(window) if isinstance(w,ttk.Combobox) and rec.TYPE in w.cget('values'))
                combo.set(rec.TYPE);combo.event_generate('<<ComboboxSelected>>');root.update()
                slots=[w for w in widgets(window) if hasattr(w,'recommendation_slot')]
                self.assertEqual(len(slots),4)
                self.assertEqual([w.get() for w in slots],rec.DEFAULT['machines'])
                self.assertIn('候補7台',slots[0].cget('values'));self.assertNotIn('候補6台',slots[0].cget('values'))
                slots[0].set('候補7台')
                save=next(w for w in widgets(window) if isinstance(w,ttk.Button) and w.cget('text')=='4機種を保存')
                save.invoke();root.update()
                face=next(w for w in widgets(window) if getattr(w,'recommendation_result',None)==(401,'2026-10-26'))
                face.set('😇');face.event_generate('<<ComboboxSelected>>');root.update()
                db=Store(path)
                try:
                    self.assertEqual(db.history_edits()['recommendations'][0]['machines'],['候補7台',*rec.DEFAULT['machines'][1:]])
                    self.assertEqual(db.history_edits()['recommendation_results'][0]['value'],'😇')
                    self.assertTrue(all(json.loads(r[0])['jo_net']==0 for r in db.db.execute('SELECT payload FROM days')))
                finally:db.close()
                combo.set('4台構成');combo.event_generate('<<ComboboxSelected>>');root.update()
                self.assertFalse(any(hasattr(w,'recommendation_slot') for w in widgets(window)))
                window.destroy()
        finally:root.destroy()


    def test_face_override_blank_auto_restore_and_backup_keep_numeric_records_untouched(self):
        entry=dict(store='nagamachiminami',week='2026-10-26',machine=rec.DEFAULT['machines'][0],rack=100,day='2026-10-26',value='😇',updated_at='2026-10-25T00:00:00.123456Z',device='shared')
        fields={k:entry[k] for k in ('store','week','machine','rack','day')}
        blank=dict(entry,value='',updated_at='2026-10-25T00:00:00.123457Z')
        auto=dict(entry,value=None,updated_at='2026-10-25T00:00:00.123458Z')
        self.assertEqual(rec.result_value([entry],fields,'😌'),'😇')
        self.assertEqual(rec.result_value(rec.merge_results([entry],[blank]),fields,'😌'),'')
        self.assertEqual(rec.result_value(rec.merge_results([blank],[auto]),fields,'😌'),'😌')
        for change in [dict(value='未知'),dict(day='2026-11-02'),dict(rack=1.5),dict(updated_at='2026-02-30T00:00:00Z'),dict(updated_at='2026-10-25T24:00:00Z'),dict(updated_at='2026-10-25T12:60:00Z')]:
            with self.assertRaises(ValueError):rec.result(dict(entry,**change))
        for key in fields:
            broken=dict(entry);del broken[key]
            with self.assertRaises(ValueError):rec.result(broken)
        with tempfile.TemporaryDirectory() as temp:
            db=Store(Path(temp)/'data.sqlite3')
            try:
                before=list(db.db.execute('SELECT * FROM days'))
                payload=dict(empty_edits(),recommendation_results=[entry])
                Path(temp,SHARED_HISTORY_NAME).write_text(json.dumps(payload),encoding='utf-8')
                self.assertEqual(pull_shared_history(db,temp)[0],1)
                db.merge_history_edits(empty_edits())
                self.assertEqual(db.history_edits()['recommendation_results'],[entry])
                self.assertEqual(list(db.db.execute('SELECT * FROM days')),before)
            finally:db.close()
