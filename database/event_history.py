"""長町南の週イベント履歴。編集はSQLiteへ保存し、共有出力はまとめて更新する。"""
from datetime import date, datetime, timedelta
import json
import sqlite3
import unicodedata
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from event_history_data import (ASSET, KINDS, STORE, load_base, empty_edits, materialize,
    clean_edits, edit_key, saved_name, machine_candidates, variety_week_lineup, capture_shortfall, stamp,
    SHORTFALL_DAYS, machine_day_nets, auto_faces)

HISTORY_FILE = ASSET
EVENT_TYPES = KINDS
WEEKDAYS = '月火水木金土日'


def load_event_history(path=HISTORY_FILE):
    return load_base(path)['weeks']


def open_event_history(parent, on_pick, *, db_path, on_changed=None, path=HISTORY_FILE):
    from core import Store
    window = tk.Toplevel(parent)
    window.title('長町南のイベント履歴')
    window.geometry('1180x720')
    window.minsize(820, 440)
    frame = ttk.Frame(window, padding=12)
    frame.pack(fill='both', expand=True)
    status = tk.StringVar(value='読み込み中…')
    try:
        base = load_base(path)
        db = Store(db_path)
        try:
            edits = [db.history_edits_raw()]
            records = [dict(store=s, day=d, machine=m, rack=r) for s,d,m,r in db.db.execute(
                'SELECT store,day,machine,rack FROM days WHERE store=?', (STORE,))]
        finally:
            db.close()
    except (OSError, ValueError, sqlite3.Error) as error:
        ttk.Label(frame, text=f'履歴ファイルを読めません：{error}', wraplength=760).pack(pady=24)
        return window
    index = {}
    for r in records:
        index.setdefault(r['day'], set()).add(r['machine'])
    dirty = [False]
    ttk.Label(frame, text='長町南のイベント履歴', style='H2.TLabel').pack(anchor='w')
    ttk.Label(frame, text='記号はプルダウンで編集します。→ はその機種・その日のデータを開きます。記号の意味は未設定です。').pack(anchor='w')
    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=8)
    kind = tk.StringVar(value=KINDS[0])
    kind_combo = ttk.Combobox(controls, textvariable=kind, values=KINDS, state='readonly', width=14)
    kind_combo.pack(side='left')
    chosen = tk.StringVar()
    week_combo = ttk.Combobox(controls, textvariable=chosen, state='readonly', width=34)
    week_combo.pack(side='left', padx=8)
    content = ttk.Frame(frame)
    content.pack(fill='both', expand=True)
    # 顔文字の自動挿入：表の真上（スクロールしない位置）。バラエティの週を開いているときだけ出す。
    auto_row = ttk.Frame(frame)
    auto_day = tk.StringVar()
    ttk.Label(auto_row, text='顔文字の自動挿入：').pack(side='left')
    auto_combo = ttk.Combobox(auto_row, textvariable=auto_day, state='readonly', width=10)
    auto_combo.pack(side='left', padx=4)
    ttk.Button(auto_row, text='この日の差枚で顔文字を入れる', command=lambda: auto_insert()).pack(side='left')
    ttk.Label(auto_row, text='  +3000枚以上😍　1000〜2999😀　0〜999😌　マイナス🥶（空欄だけ）').pack(side='left')
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
            current = db.history_edits()
            incoming = empty_edits()
            for entry in entries:
                entry['device'] = 'pc'
                now = datetime.now().astimezone()
                for old in current[group]:
                    if edit_key(group, old) == edit_key(group, entry):
                        now = max(now, stamp(old['updated_at']) + timedelta(milliseconds=1))
                entry['updated_at'] = now.isoformat()
                incoming[group].append(entry)
            _changed, conflicts, rejected, skipped_weeks = db.merge_history_edits(incoming)
            edits[0] = db.history_edits_raw()
        finally:
            db.close()
        dirty[0] = True
        status.set('PCに保存済み。次の保存か「共有へ反映」で共有用ファイルを更新します' + (f'（不一致{conflicts}件）' if conflicts else ''))
        if rejected:
            messagebox.showwarning('履歴の確認', f'形式が合わない編集{rejected}件を反映しませんでした。', parent=window)

    def save(group, entry):
        save_many(group, [entry])

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
                save('links', dict(store=STORE, machine=item['name'], record_name=value.get()))
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
            save('cells', dict(store=STORE, type=w['type'], week=w['from'], machine=item['name'], day=d, value=value.get()))
        except Exception as error:
            value.set(previous)
            messagebox.showerror('保存できません', str(error), parent=window)

    def render(*_, reset=False):
        for child in table.winfo_children(): child.destroy()
        weeks, rejected = materialize(base, edits[0])
        selected = [w for w in weeks if w['type'] == kind.get()]
        labels = {f"{w['from']}〜{w['to']}": w for w in selected}
        week_combo.configure(values=list(labels))
        if reset or chosen.get() not in labels: chosen.set(next(iter(labels), ''))
        w = labels.get(chosen.get())
        if w is not None and w['type'] == 'バラエティ':
            first_day = date.fromisoformat(w['from'])
            options = [f"{(first_day+timedelta(days=i)).isoformat()} {WEEKDAYS[i]}" for i in range(7)]
            auto_combo.configure(values=options)
            if auto_day.get() not in options:
                # 既定は、その週で保存済みの記録がある最後の日（無ければ週の初日）。
                recorded = [o for o in options if o.split()[0] in index]
                auto_day.set(recorded[-1] if recorded else options[0])
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
        if w.get('lineup_day'):
            status.set(f"分類日：{w['lineup_day']}（作成時の構成で固定）" + ('・次の保存か「共有へ反映」で共有用ファイルを更新' if dirty[0] else ''))
        for row,item in enumerate(w['machines'],1):
            namebox = ttk.Frame(table, padding=(4,4))
            namebox.grid(row=row,column=0,sticky='w')
            ttk.Label(namebox, text=f"{item['name']}  {item['count']}台", width=38).pack(anchor='w')
            ttk.Button(namebox, text='保存名の対応を確認', command=lambda w=w,m=item: link_machine(w,m)).pack(anchor='w')
            for i,d in enumerate(days):
                cell=ttk.Frame(table,padding=(4,4)); cell.grid(row=row,column=i+1)
                value=tk.StringVar(value=item['results'][i])
                combo=ttk.Combobox(cell,textvariable=value,values=['',*base['symbols']],state='readonly',width=4)
                combo.pack(side='left')
                combo.bind('<<ComboboxSelected>>',lambda _,w=w,m=item,d=d,v=value,p=item['results'][i]: changed_symbol(w,m,d,v,p))
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
            lineup,machines,doubtful=variety_week_lineup(records,value)
            notes=[]
            shortfall=capture_shortfall(records,lineup)
            if shortfall:
                notes.append(f'分類日（{lineup}）の保存台数は{shortfall[0]}台で、前後{SHORTFALL_DAYS}日で最も多い日（{shortfall[1]}台）の8割に届きません。'
                             'この時期は取り込みが少なく、4台以上の機種が1〜3台に見えている可能性があります。')
            if doubtful:
                notes.append('次の機種は周辺の日に4台以上あり、取り込み不足の可能性があります。\n' + '\n'.join(doubtful))
            if notes and not messagebox.askyesno('機種台数の確認',
                    '\n\n'.join(notes) + '\n\nこの構成で週表を作成しますか？', parent=window):
                return
            save('weeks',dict(store=STORE,type='バラエティ',week=value,lineup_day=lineup,machines=machines,removed=False))
            kind.set('バラエティ'); chosen.set(f"{value}〜{(date.fromisoformat(value)+timedelta(days=6)).isoformat()}")
            render()
        except Exception as error: messagebox.showerror('週表を作成できません',str(error),parent=window)

    def auto_insert():
        # 選んだ日のバラエティの空欄に、その日の機種の合計差枚で顔文字を入れる（入力済みのセルは変えない）。
        weeks, _rejected = materialize(base, edits[0])
        w = next((x for x in weeks if x['type'] == kind.get() and f"{x['from']}〜{x['to']}" == chosen.get()), None)
        target = auto_day.get()
        if w is None or w['type'] != 'バラエティ' or not target:
            messagebox.showinfo('自動挿入', '「バラエティ」の週と日付を選んでから押してください。', parent=window)
            return
        target = target.split()[0]
        try:
            db = Store(db_path)
            try:
                nets = machine_day_nets(db, target, target)
            finally:
                db.close()
            cells, skipped = auto_faces(w, nets, index, base['symbols'], base.get('user_blank_days', ()), only_day=target)
            if not cells:
                messagebox.showinfo('自動挿入', f'{target}に入れられる空欄がありません。' + (f'\n差枚の分からない空欄が{skipped}件あります。' if skipped else ''), parent=window)
                return
            if not messagebox.askyesno('自動挿入', f'{target}の空欄{len(cells)}件に顔文字を入れます（入力済みのセルは変えません）。\n'
                    '+3000枚以上＝😍　1000〜2999枚＝😀　0〜999枚＝😌　マイナス＝🥶\n'
                    + (f'差枚の分からない空欄{skipped}件は空欄のままです。\n' if skipped else '') + '入れますか？', parent=window):
                return
            save_many('cells', [dict(store=STORE, type=w['type'], week=w['from'], machine=m, day=d, value=v) for m, d, v in cells])
            render()
            status.set(f'{target}に顔文字を{len(cells)}件入れました。' + (f'差枚の分からない空欄{skipped}件は空欄のままです。' if skipped else '') + '次の保存か「共有へ反映」で共有用ファイルを更新します。')
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
    ttk.Button(footer,text='共有へ反映',command=publish).pack(side='right')
    ttk.Button(footer,text='閉じる',command=close).pack(side='right',padx=8)
    kind_combo.bind('<<ComboboxSelected>>',lambda _:render(reset=True))
    week_combo.bind('<<ComboboxSelected>>',render)
    window.protocol('WM_DELETE_WINDOW',close)
    window.flush_history = publish
    status.set('編集はPCに保存します。共有への反映はまとめて行います。')
    render()
    return window
