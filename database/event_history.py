"""長町南の週イベント履歴。編集はSQLiteへ保存し、共有出力はまとめて更新する。"""
from datetime import date, datetime, timedelta
import json
import sqlite3
import unicodedata
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import recommendations as rec

from event_history_data import (ASSET, KINDS, STORE, load_base, empty_edits, materialize,
    clean_edits, edit_key, saved_name, machine_candidates, variety_week_lineup, capture_shortfall, stamp,
    SHORTFALL_DAYS, machine_day_nets, auto_faces, SAIWAI_STORE, VARIETY_KEY,
    saiwaichou_base, store_edits, store_kinds, net_face, machine_day_totals, auto_grades,
    gap_end, gap_range, grade_gap, GAP_NET)

HISTORY_FILE = ASSET
EVENT_TYPES = KINDS
WEEKDAYS = '月火水木金土日'


def load_event_history(path=HISTORY_FILE):
    return load_base(path)['weeks']


def open_event_history(parent, on_pick, *, db_path, on_changed=None, path=HISTORY_FILE, location=STORE):
    from core import Store
    if location not in (STORE, SAIWAI_STORE):
        raise ValueError('対応していない店舗です。')
    saiwaichou = location == SAIWAI_STORE
    title = '幸町のバラエティ履歴' if saiwaichou else '長町南のイベント履歴'
    result_name = '優・良' if saiwaichou else '顔文字'
    rule_text = '+3000枚以上＝😍　1000〜2999枚＝😀　0〜999枚＝😌　マイナス＝🥶'
    skipped_text = '差枚の分からない空欄'
    window = tk.Toplevel(parent)
    window.history_store = location
    window.title(title)
    window.geometry('1180x720')
    window.minsize(820, 440)
    frame = ttk.Frame(window, padding=12)
    frame.pack(fill='both', expand=True)
    status = tk.StringVar(value='読み込み中…')
    try:
        base = saiwaichou_base() if saiwaichou else load_base(path)
        db = Store(db_path)
        try:
            edits = [store_edits(db.history_edits_raw(), location)]
            records = [dict(store=s, day=d, machine=m, rack=r) for s,d,m,r in db.db.execute(
                'SELECT store,day,machine,rack FROM days WHERE store=?', (location,))]
        finally:
            db.close()
    except (OSError, ValueError, sqlite3.Error) as error:
        ttk.Label(frame, text=f'履歴ファイルを読めません：{error}', wraplength=760).pack(pady=24)
        return window
    index = {}
    for r in records:
        index.setdefault(r['day'], set()).add(r['machine'])
    dirty = [False]
    name_labels = {}
    ttk.Label(frame, text=title, style='H2.TLabel').pack(anchor='w')
    ttk.Label(frame, text=('優・良は自動で表示し、手入力・修正はPCで行います。→ はその機種・その日のデータを開きます。' if saiwaichou else
                          '記号はプルダウンで編集します。→ はその機種・その日のデータを開きます。記号の意味は未設定です。')).pack(anchor='w')
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=8)
    kinds = (*store_kinds(location), rec.TYPE) if not saiwaichou else store_kinds(location)
    kind = tk.StringVar(value=kinds[0])
    kind_combo = ttk.Combobox(controls, textvariable=kind, values=kinds, state='readonly', width=14)
    kind_combo.pack(side='left')
    chosen = tk.StringVar()
    week_combo = ttk.Combobox(controls, textvariable=chosen, state='readonly', width=34)
    week_combo.pack(side='left', padx=8)
    content = ttk.Frame(frame)
    content.pack(fill='both', expand=True)
    # 表の真上（スクロールしない位置）。週表を開いているときだけ出す。
    auto_row = ttk.Frame(frame)
    auto_day = tk.StringVar()
    gap_note = tk.StringVar()
    if saiwaichou:
        # 幸町の優・良は表示のたびに差枚から自動判定する（2026-10-29 利用者指定、4大オススメと同じ）。自動の値は保存しない。
        ttk.Label(auto_row, text='空欄の日は、その日の機種合計差枚から自動表示：2,500枚以上＝優　0〜2,499枚＝良　'
                  'マイナス・差枚不明・台数不足は—。手入力した優・良が優先（「自動」で戻す）').pack(anchor='w')
        ttk.Label(auto_row, textvariable=gap_note, foreground='#b91c1c').pack(anchor='w')
    else:
        # 顔文字の自動挿入（4台構成・半列・バラエティ共通）。
        auto_daily = ttk.Frame(auto_row)
        auto_daily.pack(fill='x')
        ttk.Label(auto_daily, text=f'{result_name}の自動挿入：').pack(side='left')
        auto_combo = ttk.Combobox(auto_daily, textvariable=auto_day, state='readonly', width=10)
        auto_combo.pack(side='left', padx=4)
        ttk.Button(auto_daily, text=f'この日の差枚で{result_name}を入れる', command=lambda: auto_insert()).pack(side='left')
        ttk.Label(auto_daily, text=f'  {rule_text}（空欄だけ）').pack(side='left')
    canvas = tk.Canvas(content, highlightthickness=0)
    vertical = ttk.Scrollbar(content, orient='vertical', command=canvas.yview)
    horizontal = ttk.Scrollbar(content, orient='horizontal', command=canvas.xview)
    canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    canvas.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    content.columnconfigure(0, weight=1)
    content.rowconfigure(0, weight=1)
    table = ttk.Frame(canvas)
    canvas.create_window((0,0), window=table, anchor='nw')
    table.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
    footer = ttk.Frame(frame)
    footer.pack(fill='x', pady=(8,0))
    ttk.Label(footer, textvariable=status).pack(side='left')

    def save_many(group, entries):
        # 別窓からの編集も取り込んだ上で、対象のセルだけを保存する（まとめて1回）。
        db = Store(db_path)
        try:
            current = clean_edits(store_edits(db.history_edits_raw(), location), base)[0]
            incoming = empty_edits()
            for entry in entries:
                entry['device'] = 'pc'
                now = datetime.now().astimezone()
                for old in current.get(group, []):
                    if (old.get('week') == entry.get('week') if group == 'recommendations' else rec.result_key(old) == rec.result_key(entry) if group == 'recommendation_results' else edit_key(group, old) == edit_key(group, entry)):
                        now = max(now, stamp(old['updated_at']) + timedelta(milliseconds=1))
                entry['updated_at'] = now.isoformat()
                incoming.setdefault(group, []).append(entry)
            payload = dict(empty_edits(), **{VARIETY_KEY: incoming}) if saiwaichou else incoming
            _changed, conflicts, rejected, skipped_weeks = db.merge_history_edits(payload)
            edits[0] = store_edits(db.history_edits_raw(), location)
        finally:
            db.close()
        dirty[0] = True
        status.set('PCに保存済み。次の保存か「共有へ反映」で共有用ファイルを更新します' + (f'（不一致{conflicts}件）' if conflicts else ''))
        if rejected:
            messagebox.showwarning('履歴の確認', f'形式が合わない編集{rejected}件を反映しませんでした。', parent=window)

    def save(group, entry):
        save_many(group, [entry])

    totals_cache = {}

    def day_totals(first, last):
        # 窓を開いている間は同じ期間を読み直さない（1週で約0.2〜0.3秒）。
        if (first, last) not in totals_cache:
            db = Store(db_path)
            try:
                totals_cache[(first, last)] = machine_day_totals(db, first, last, location)
            finally:
                db.close()
        return totals_cache[(first, last)]

    def names_for(w):
        return set().union(*(names for d,names in index.items() if w['from'] <= d <= w['to']))

    def link_machine(w, item):
        names = names_for(w)
        dialog = tk.Toplevel(window)
        dialog.title('履歴の機種と保存済みの機種を対応付ける')
        dialog.transient(window)
        ttk.Label(dialog, text=item['name'], padding=12).pack(anchor='w')
        candidates = machine_candidates(item['name'], names)
        loose = lambda n: ''.join(unicodedata.normalize('NFKC', n).replace('/', '').split())
        matches = [n for n in candidates if loose(n) == loose(item['name'])]
        initial = item.get('record_name') if item.get('record_name') in names else saved_name(item, names)
        value = tk.StringVar(value=initial or (matches[0] if len(matches) == 1 else ''))
        ttk.Label(dialog, text='同じ機種であることを確認して選んでください。').pack(padx=12)
        combo = ttk.Combobox(dialog, textvariable=value, values=candidates, state='readonly', width=62)
        combo.pack(padx=12, pady=12)
        def accept():
            if value.get() not in names:
                return
            try:
                save('links', dict(store=location, machine=item['name'], record_name=value.get()))
            except Exception as error:
                messagebox.showerror('保存できません', str(error), parent=dialog)
                return
            dialog.destroy()
            render()
        ttk.Button(dialog, text='この保存名に対応付ける', command=accept).pack(pady=(0,12))

    def changed_symbol(w, item, d, value, previous):
        previous = next((c['value'] for c in clean_edits(edits[0], base)[0]['cells'] if c['type'] == w['type']
                         and c['week'] == w['from'] and c['machine'] == item['name'] and c['day'] == d), previous)
        try:
            save('cells', dict(store=location, type=w['type'], week=w['from'], machine=item['name'], day=d,
                               value='' if value.get() == '自動' else value.get()))
            if saiwaichou:
                render()  # 自動の表示と赤字を手入力に合わせて描き直す。
                return
            # 最新の編集を重ねてから判定し、😍を付け外しした直後にも機種名の色を更新する。
            for week in materialize(base, edits[0])[0]:
                for machine in week['machines']:
                    label = name_labels.get((week['type'], week['from'], machine['name']))
                    if label is not None:
                        label.configure(foreground='#b91c1c' if not saiwaichou and week['type'] == 'バラエティ' and '😍' not in machine['results'] else '')
        except Exception as error:
            value.set(previous or ('自動' if saiwaichou else ''))
            messagebox.showerror('保存できません', str(error), parent=window)

    recommendation_drafts = {}

    def recommendation_table():
        from core import rack_net, implausible_numbers
        plans = rec.plans(edits[0].get('recommendations', []))
        all_plans = {p['week']: p for p in plans}
        all_plans.update(recommendation_drafts)
        labels = {f"{first}〜{rec.days(first)[-1]}": all_plans[first] for first in sorted(all_plans, reverse=True)}
        week_combo.configure(values=list(labels))
        if chosen.get() not in labels: chosen.set(next(iter(labels)))
        p = labels[chosen.get()]
        first, machines = p['week'], p['machines']
        lineup, choices = rec.candidates(records, first)
        result_index=rec.result_index(edits[0].get('recommendation_results',[]))
        names=sorted({r['machine'] for r in records if first<=r['day']<=rec.days(first)[-1] and any(rec.normal(r['machine'])==rec.normal(n) for n in machines)})
        result_records=[]
        if names:
            db=Store(db_path)
            try:
                query="SELECT store,day,machine,rack,json_remove(payload,'$.graph_measurement.preview_image') FROM days WHERE store=? AND day BETWEEN ? AND ? AND machine IN ("+','.join('?' for _ in names)+") AND json_valid(payload)"
                result_records=[dict(json.loads(payload),store=s,day=d,machine=m,rack=r) for s,d,m,r,payload in db.db.execute(query,(STORE,first,rec.days(first)[-1],*names))]
            finally:db.close()
        ttk.Label(table, text=f"選定元：{lineup or '保存データなし'} · 7台以上の機種から異なる4機種を選択", padding=8).grid(row=0, column=0, columnspan=8, sticky='w')
        values = []
        row = 1
        for slot, selected in enumerate(machines):
            available = {n for n, _ in choices}
            resolved = rec.saved_name(selected, available) or selected
            options = [n for n, _ in choices]
            if resolved not in options: options.insert(0, resolved)
            value = tk.StringVar(value=resolved)
            values.append(value)
            combo = ttk.Combobox(table, textvariable=value, values=options, state='readonly', width=50)
            combo.grid(row=row, column=0, columnspan=8, sticky='w', pady=(12, 5))
            combo.recommendation_slot = slot
            row += 1
            ttk.Label(table, text='台番号', padding=6).grid(row=row,column=0)
            for i,d in enumerate(rec.days(first)):
                ttk.Label(table,text=f'{d[5:]} {WEEKDAYS[i]}',padding=6).grid(row=row,column=i+1)
            row += 1
            rack_rows = rec.rows(result_records, first, selected)
            for rack, cells in rack_rows:
                ttk.Label(table,text=f'{rack}番',padding=6).grid(row=row,column=0,sticky='w')
                for i,r in enumerate(cells):
                    net = rack_net(r)[0] if r is not None and not implausible_numbers(r) else None
                    fields=dict(store=STORE,week=first,machine=selected,rack=rack,day=rec.days(first)[i])
                    saved=result_index.get(rec.result_key(fields))
                    choice='自動' if saved is None or saved['value'] is None else saved['value']
                    face=net_face(net) if net is not None else ''
                    cell=ttk.Frame(table,padding=2);cell.grid(row=row,column=i+1,sticky='ew')
                    variable=tk.StringVar(value=choice)
                    face_combo=ttk.Combobox(cell,textvariable=variable,values=['自動','',*rec.FACES],state='readonly',width=6)
                    face_combo.pack()
                    face_combo.recommendation_result=(rack,fields['day'])
                    def save_face(_=None,fields=fields,variable=variable):
                        try:
                            save('recommendation_results',dict(fields,value=None if variable.get()=='自動' else variable.get()))
                            render()
                        except Exception as error:messagebox.showerror('顔文字を保存できません',str(error),parent=window)
                    face_combo.bind('<<ComboboxSelected>>',save_face)
                    if choice=='自動':ttk.Label(cell,text=face or '—').pack()
                    text='—' if net is None else ('約' if r.get('jo_net') is None else '')+(f'{net:+,}' if net else '0')
                    ttk.Button(cell,text=text,width=12,state='normal' if r else 'disabled',command=lambda r=r:on_pick(r['machine'],r['day'])).pack()
                row += 1
            if not rack_rows:
                ttk.Label(table,text='この週の保存データはまだありません。',padding=8).grid(row=row,column=0,columnspan=8,sticky='w')
                row += 1
        def accept():
            try:
                selected = [v.get() for v in values]
                for old, new in zip(machines, selected):
                    if new != old and new not in {n for n, _ in choices}:
                        raise ValueError('7台以上の設置機種から選んでください。')
                entry = rec.plan(dict(store=STORE, week=first, machines=selected, updated_at=datetime.now().astimezone().isoformat(),device='pc'))
                save('recommendations', entry)
                recommendation_drafts.pop(first,None)
                render()
            except Exception as error:
                messagebox.showerror('4機種を保存できません',str(error),parent=window)
        ttk.Button(table,text='4機種を保存',command=accept).grid(row=row,column=0,columnspan=8,sticky='w',pady=10)
        ttk.Label(table,text='台ごとの差枚から自動表示：3,000枚以上😍 · 1,000枚以上😀 · 0枚以上😌 · マイナス🥶 · 不明—',padding=8).grid(row=row+1,column=0,columnspan=8,sticky='w')

    def create_recommendation_week():
        value=simpledialog.askstring('4大オススメの週を追加','週開始日（月曜日、例：2026-11-02）',parent=window)
        if not value:return
        try:
            rec.week(value)
            existing=rec.plans(edits[0].get('recommendations',[]))
            if value not in {p['week'] for p in existing}:
                recommendation_drafts[value]=dict(existing[0],week=value)
            kind.set(rec.TYPE);chosen.set(f"{value}〜{rec.days(value)[-1]}")
            render()
        except Exception as error:messagebox.showerror('週を追加できません',str(error),parent=window)

    def render(*_, reset=False):
        for child in table.winfo_children(): child.destroy()
        name_labels.clear()
        if kind.get() == rec.TYPE:
            auto_row.pack_forget()
            recommendation_table()
            return
        weeks, rejected = materialize(base, edits[0])
        selected = [w for w in weeks if w['type'] == kind.get()]
        labels = {f"{w['from']}〜{w['to']}": w for w in selected}
        week_combo.configure(values=list(labels))
        if reset or chosen.get() not in labels: chosen.set(next(iter(labels), ''))
        w = labels.get(chosen.get())
        if w is not None and not saiwaichou:
            first_day = date.fromisoformat(w['from'])
            options = [f"{(first_day+timedelta(days=i)).isoformat()} {WEEKDAYS[i]}" for i in range(7)]
            auto_combo.configure(values=options)
            if auto_day.get() not in options:
                # 既定は、その週で保存済みの記録がある最後の日（無ければ週の初日）。
                recorded = [o for o in options if o.split()[0] in index]
                auto_day.set(recorded[-1] if recorded else options[0])
            auto_row.pack(fill='x', pady=(0, 6), before=content)
        elif w is not None:
            auto_row.pack(fill='x', pady=(0, 6), before=content)
        else:
            auto_row.pack_forget()
        if w is None:
            ttk.Label(table, text='この種別の週表はまだありません。バラエティは「週表を作成」から追加できます。', padding=18).grid()
            return
        first = date.fromisoformat(w['from'])
        days = [(first+timedelta(days=i)).isoformat() for i in range(7)]
        ttk.Label(table, text='機種名・台数', padding=8).grid(row=0,column=0,sticky='w')
        for i,d in enumerate(days):
            ttk.Label(table, text=f'{d[5:]} {WEEKDAYS[i]}', padding=8).grid(row=0,column=i+1)
        automatic, totals, end = {}, {}, None
        if saiwaichou:
            recorded = sorted(d for d in index if w['from'] <= d <= w['to'])
            end = gap_end(recorded[-1] if recorded else None)
            try:
                totals = day_totals(min(w['from'], gap_range(end)[0]) if end else w['from'], w['to'])
            except (OSError, sqlite3.Error) as error:
                status.set(f'差枚を読めないため自動の優・良と赤字を表示できません：{error}')
            automatic = auto_grades(w, totals, index)
            gap_note.set(f'赤字：{end}までの5日間、機種合計差枚が+{GAP_NET}枚を超えた日なし'
                         '（今日は含めない。記録なし・差枚不明の日も超えていないと数え、手入力の優は超えた日と数える）'
                         if end else 'この週は記録がないため赤字判定はしません。')
        if w.get('lineup_day'):
            status.set(f"分類日：{w['lineup_day']}（作成時の構成で固定）" + ('・次の保存か「共有へ反映」で共有用ファイルを更新' if dirty[0] else ''))
        for row,item in enumerate(w['machines'],1):
            namebox = ttk.Frame(table, padding=(4,4))
            namebox.grid(row=row,column=0,sticky='w')
            red = (grade_gap(weeks, item, end, totals, index) if saiwaichou else
                   w['type'] == 'バラエティ' and '😍' not in item['results'])
            name_label = ttk.Label(namebox, text=f"{item['name']}  {item['count']}台", width=38,
                                   foreground='#b91c1c' if red else '')
            name_label.pack(anchor='w')
            name_labels[(w['type'], w['from'], item['name'])] = name_label
            ttk.Button(namebox, text='保存名の対応を確認', command=lambda w=w,m=item: link_machine(w,m)).pack(anchor='w')
            for i,d in enumerate(days):
                cell=ttk.Frame(table,padding=(4,4)); cell.grid(row=row,column=i+1)
                saved_value=item['results'][i]
                value=tk.StringVar(value=(saved_value or '自動') if saiwaichou else saved_value)
                combo=ttk.Combobox(cell,textvariable=value,values=['自動' if saiwaichou else '',*base['symbols']],state='readonly',width=5 if saiwaichou else 4)
                combo.pack(side='left')
                combo.bind('<<ComboboxSelected>>',lambda _,w=w,m=item,d=d,v=value,p=saved_value: changed_symbol(w,m,d,v,p))
                if saiwaichou and not saved_value:
                    ttk.Label(cell,text=automatic.get((item['name'],d),'—'),width=2).pack(side='left',padx=(2,0))
                name=saved_name(item,index.get(d,set()))
                ttk.Button(cell,text='→' if name else '—',width=3,state='normal' if name else 'disabled',
                    command=lambda n=name,d=d:on_pick(n,d)).pack(side='left')
        if rejected: status.set(f'形式が合わない編集{rejected}件を表示していません。')

    def create_week():
        value=simpledialog.askstring('バラエティの週表を作成','週開始日（月曜日、例：2026-10-12）',parent=window)
        if not value: return
        try:
            all_weeks,_=materialize(base,edits[0])
            if any(w['from']==value for w in all_weeks): raise ValueError('この週のイベント表は既にあります。')
            lineup,machines,doubtful=variety_week_lineup(records,value,location)
            notes=[]
            shortfall=capture_shortfall(records,lineup,location)
            if shortfall:
                notes.append(f'分類日（{lineup}）の保存台数は{shortfall[0]}台で、前後{SHORTFALL_DAYS}日で最も多い日（{shortfall[1]}台）の8割に届きません。'
                             + ('この時期は取り込みが少なく、3台以上の機種が1〜2台に見えている可能性があります。' if saiwaichou else
                                'この時期は取り込みが少なく、4台以上の機種が1〜3台に見えている可能性があります。'))
            if doubtful:
                notes.append(f'次の機種は周辺の日に{3 if saiwaichou else 4}台以上あり、取り込み不足の可能性があります。\n' + '\n'.join(doubtful))
            if notes and not messagebox.askyesno('機種台数の確認',
                    '\n\n'.join(notes) + '\n\nこの構成で週表を作成しますか？', parent=window):
                return
            save('weeks',dict(store=location,type='バラエティ',week=value,lineup_day=lineup,machines=machines,removed=False))
            kind.set('バラエティ'); chosen.set(f"{value}〜{(date.fromisoformat(value)+timedelta(days=6)).isoformat()}")
            render()
        except Exception as error: messagebox.showerror('週表を作成できません',str(error),parent=window)

    def auto_insert():
        # 長町南の顔文字。選んだ日の合計差枚で判定し、入力済みのセルは変えない。
        weeks, _rejected = materialize(base, edits[0])
        w = next((x for x in weeks if x['type'] == kind.get() and f"{x['from']}〜{x['to']}" == chosen.get()), None)
        target = auto_day.get()
        if w is None or not target:
            messagebox.showinfo('自動挿入', 'イベントの週と日付を選んでから押してください。', parent=window)
            return
        target = target_label = target.split()[0]
        try:
            db = Store(db_path)
            try:
                nets = machine_day_nets(db, target, target, location)
            finally:
                db.close()
            cells, skipped = auto_faces(w, nets, index, base['symbols'], base.get('user_blank_days', ()),
                                        only_day=target)
            if not cells:
                messagebox.showinfo('自動挿入', f'{target_label}に入れられる空欄がありません。' + (f'\n{skipped_text}が{skipped}件あります。' if skipped else ''), parent=window)
                return
            if not messagebox.askyesno('自動挿入', f'{target_label}の空欄{len(cells)}件に{result_name}を入れます（入力済みのセルは変えません）。\n'
                    + rule_text + '\n' + (f'{skipped_text}{skipped}件は空欄のままです。\n' if skipped else '') + '入れますか？', parent=window):
                return
            save_many('cells', [dict(store=location, type=w['type'], week=w['from'], machine=m, day=d, value=v) for m, d, v in cells])
            render()
            status.set(f'{target_label}に{result_name}を{len(cells)}件入れました。' + (f'{skipped_text}{skipped}件は空欄のままです。' if skipped else '') + '次の保存か「共有へ反映」で共有用ファイルを更新します。')
        except Exception as error:
            messagebox.showerror('自動挿入できません', str(error), parent=window)

    def publish():
        if dirty[0] and on_changed:
            on_changed()
            dirty[0]=False
            status.set('共有用ファイルの更新を依頼しました。結果はPCの作業記録に表示します。')
    def close():
        publish(); window.destroy()
    ttk.Button(controls,text='バラエティの週表を作成',command=create_week).pack(side='left')
    if not saiwaichou:
        ttk.Button(controls,text='4大オススメの週を追加',command=create_recommendation_week).pack(side='left',padx=4)
    ttk.Button(footer,text='共有へ反映',command=publish).pack(side='right')
    ttk.Button(footer,text='閉じる',command=close).pack(side='right',padx=8)
    kind_combo.bind('<<ComboboxSelected>>',lambda _:render(reset=True))
    week_combo.bind('<<ComboboxSelected>>',render)
    window.protocol('WM_DELETE_WINDOW',close)
    window.flush_history = publish
    status.set('編集はPCに保存します。共有への反映はまとめて行います。')
    render()
    return window
