"""バラエティの🌈（PC、2026-10-11）。仕様は ../RAINBOW.md「バラエティのタブ」。

利用者「特にバラエティはローテーションで入れる傾向があるので、バラエティの機種一覧をpcで表示させて、
この🌈マークをつけられるようにもしてほしい。そのタブかページを作って」。
店舗・日付を選ぶと、その日のバラエティ（1〜3台の機種、core.VARIETY_MAX_RACKS）の台を並べ、🌈の列を
押すと確定が出た台の印を付け外しする。ローテーションを追えるよう、最終🌈と直近30日の🌈回数を出す。
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from core import RAINBOW_MARK, STORE_NAMES, VARIETY_MAX_RACKS, Store, load_settings, save_settings, signed_medals
from event_calendar import (MINUS_COLOR, PLUS_COLOR, RAINBOW_BG, MeruhenEvents, last_rainbow_text,
                            rainbow_cell)

# 🌈の一覧で「バラエティ」とする台数（2026-10-12 利用者「幸町のバラエティは1台機種限定にして欲しい」）。幸町は1台だけの機種、
# ほかの店は1〜3台（core.VARIETY_MAX_RACKS）。回っていない台・翌日候補の「バラエティ」は1〜3台のまま。共有ページ
# share_viewer/data.mjs の RAINBOW_VARIETY_MAX_RACKS と同じ。
RAINBOW_VARIETY_MAX_RACKS = {'saiwaichou': 1}


def rainbow_variety_max(location):
    return RAINBOW_VARIETY_MAX_RACKS.get(location, VARIETY_MAX_RACKS)


# 🌈回数を数える日数（その日を含めて30日）。
RAINBOW_COUNT_DAYS = 30
SORTS = {
    '台番順': lambda r: r['rack'],
    f'最終{RAINBOW_MARK}の古い順': lambda r: (r['rainbow'], r.get('prev_rainbow') or '', r['rack']),
    '機種順': lambda r: (r['machine'], r['rack']),
}


def variety_lineup(rows, max_racks=VARIETY_MAX_RACKS):
    """その日の台のうち、バラエティ（その日に1〜max_racks台の機種）の台。"""
    counts = {}
    for r in rows:
        counts[r['machine']] = counts.get(r['machine'], 0) + 1
    return [r for r in rows if counts[r['machine']] <= max_racks]


# 並べる台を取る日：新しい日から見て、その店のふだんの台数（直近14日でいちばん多い日）の8割以上の記録がある日
# （2026-10-12 自己点検：長町南の10/10はサイトが落ちていて37台しか取れておらず、最新の日の並びだと5台になった）。
LINEUP_LOOKBACK_DAYS = 14
LINEUP_MIN_SHARE = 0.8


def lineup_day(db_path, location, through=None):
    """バラエティ🌈の並べる台を取る日（記録がそろっている最新の日）。記録が無ければ None。共有ページの lineupDay と同じ。"""
    db = Store(db_path)
    try:
        days = [d for d in db.days_for(location) if through is None or d <= through][:LINEUP_LOOKBACK_DAYS]
        counts = {day: len(MeruhenEvents(db_path).day_records(location, day)) for day in days}
    finally:
        db.close()
    if not counts:
        return None
    usual = max(counts.values())
    return next(day for day in days if counts[day] >= usual * LINEUP_MIN_SHARE)


def variety_rows(db_path, location, day, latest=None):
    """バラエティの台の一覧。並べる台と機種名は、その店の記録がそろっている最新の日 [latest]（lineup_day）のバラエティから取る
    （2026-10-11 利用者「機種一覧名はとりあえず最新の機種一覧からとって表示させておけばいい。入れ替えとかで
    変わったらその都度書き換えて」＝入れ替えは新しい日を取り込めば自動で変わる）。
    数値・🌈・最終🌈は選んだ日 [day] の、同じ台番号の記録。無ければ数値は None。
    本日は未取り込みでも印を別保存できる。過去の未取得日は編集しない。
    その日は別の機種だった台は `day_machine` にその日の機種名。直近30日（day を含む）の🌈回数 `rainbow_count`。
    表示しない機種・数値異常の台は入れない。"""
    events = MeruhenEvents(db_path)
    if latest is None:
        latest = lineup_day(db_path, location, through=day if day == today_jst() else None) or day
    db = Store(db_path)
    try:
        since = (date.fromisoformat(day) - timedelta(days=RAINBOW_COUNT_DAYS - 1)).isoformat()
        found = db.rainbow_counts(location, since, day)
        previous = db.last_rainbow_days(location, day)
        pending = {m['rack']: m for m in db.pending_rainbow_marks(location, day)}
    finally:
        db.close()
    lineup = variety_lineup(events.day_records(location, latest), rainbow_variety_max(location))
    on_day = {int(r['rack']): r for r in (events.day_records(location, day) if day != latest else lineup)}
    rows = []
    for current in lineup:
        rack = int(current['rack'])
        record = on_day.get(rack)
        row = dict(record) if record else {'rack': rack, 'games': None, 'bb': None, 'rb': None, 'net': None,
                                           'needs_check': False, 'rainbow': pending.get(rack, {}).get('on', False), 'day': day,
                                           'prev_rainbow': previous.get(rack)}
        row['machine'] = current['machine']
        row['day_machine'] = record['machine'] if record and record['machine'] != current['machine'] else None
        row['recorded'] = record is not None
        row['editable'] = record is not None or day == today_jst()
        row['lineup_day'] = latest
        row['rainbow_count'] = found.get(rack, 0)
        rows.append(row)
    return sorted(rows, key=SORTS['台番順'])


# 表（ローテーション表）の日数：選んだ日を右端に、カレンダーの日で7日（共有ページの ROTATION_DAYS と同じ）。
ROTATION_DAYS = 7
# 表のマスの色（共有ページと同じ）。
CELL_ON, CELL_OFF, CELL_NONE, CELL_DAY = '#FAC775', '#EEF0F3', '#FFFFFF', '#0071E3'
# 見せ方（2026-10-12 利用者「PCにも同じ表は用意しておいて」）：grid＝表、list＝一覧（今までの表）。settings.json に覚える。
VARIETY_MODES = {'grid': '表', 'list': '一覧'}
WEEKDAYS = '月火水木金土日'


def today_jst():
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def window_days(day, n=ROTATION_DAYS):
    """[day] を右端にした [n] 日（カレンダーの日、古い順）。共有ページの windowDays と同じ。"""
    end = date.fromisoformat(day)
    return [(end - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def days_since(last, day):
    """最後の🌈から何日（[day] に付いていれば0、一度も無ければ None）。共有ページの daysSinceRainbow と同じ。"""
    if not last:
        return None
    return (date.fromisoformat(day) - date.fromisoformat(last)).days


def gap_text(days):
    """空きの表示（共有ページと同じ）。"""
    return 'なし' if days is None else '当日' if days == 0 else f'{days}日'


def rotation_cells(db_path, location, days):
    """表のマス：{日: {台番号: その日の台（day_records の行）}}。台番号で見る（入れ替えがあっても同じ台番号の列）。"""
    events = MeruhenEvents(db_path)
    cells = {day: {int(r['rack']): r for r in events.day_records(location, day)} for day in days}
    db = Store(db_path)
    try:
        for mark in db.pending_rainbow_marks(location):
            if mark['day'] in cells and mark['rack'] not in cells[mark['day']]:
                cells[mark['day']][mark['rack']] = dict(rainbow=mark['on'], recorded=False,
                                                       editable=mark['day'] == today_jst())
    finally:
        db.close()
    return cells


def build_variety_tab(parent, db_path, on_marked, default_location=None, on_flush=None, pending=None,
                      defer_load=False):
    """「バラエティ🌈」のタブの中身。押したときは記録への保存だけ（速い）で、on_marked() を呼ぶ。閲覧・共有ページ用の
    ファイルとバックアップの作り直しはまとめて1回（on_flush：「閲覧・共有ページに反映」のボタン。PC版はタブを離れるとき・
    閉じるときにも呼ぶ。2026-10-12 利用者「一個押すたびに保存処理をしているようで数秒かかってしまう。…まとめてつけてから
    保存処理してほしい」）。pending はボタンの文字（未反映の台数）。表示を描き直す関数を返す（タブを開いたとき用）。"""
    ttk.Label(parent, text=f'バラエティの{RAINBOW_MARK}', style='H2.TLabel').pack(anchor='w')
    ttk.Label(parent, text=f'記録のそろった最新の日（ふだんの8割以上の台を取り込んだ日）の、幸町は1台だけの機種・長町南は1〜{VARIETY_MAX_RACKS}台の機種の台（入れ替えは、新しい日を取り込むと自動で変わります）。'
                           f'数値と{RAINBOW_MARK}は選んだ日のもの。{RAINBOW_MARK}の列を押すと、確定が出た台の印を付け外しします'
                           f'（もう一度押すと外れます）。最終{RAINBOW_MARK}＝その台番号に最後に付いた日、'
                           f'{RAINBOW_COUNT_DAYS}日＝その日までの{RAINBOW_COUNT_DAYS}日の{RAINBOW_MARK}の回数。',
              style='Sub.TLabel', wraplength=900).pack(anchor='w', pady=(0, 10))
    bar = ttk.Frame(parent)
    bar.pack(fill='x')
    labels = list(STORE_NAMES.values())
    store_var = tk.StringVar(value=STORE_NAMES.get(default_location) or labels[0])
    day_var = tk.StringVar()
    sort_var = tk.StringVar(value='台番順')
    for column, (text, var, values, width) in enumerate((('店舗', store_var, labels, 28), ('日付', day_var, [], 16),
                                                         ('並べ方', sort_var, list(SORTS), 18))):
        ttk.Label(bar, text=text).grid(row=0, column=column, sticky='w')
        combo = ttk.Combobox(bar, textvariable=var, values=values, state='readonly', width=width)
        combo.grid(row=1, column=column, sticky='w', padx=(0, 16))
        if var is day_var:
            day_combo = combo
    data_dir = Path(db_path).parent
    saved_mode = load_settings(data_dir).get('variety_mode')
    mode_var = tk.StringVar(value=saved_mode if saved_mode in VARIETY_MODES else 'grid')
    ttk.Label(bar, text='見せ方').grid(row=0, column=3, sticky='w')
    modes = ttk.Frame(bar)
    modes.grid(row=1, column=3, sticky='w')
    for key, label in VARIETY_MODES.items():
        ttk.Radiobutton(modes, text=label, value=key, variable=mode_var).pack(side='left', padx=(0, 10))
    if on_flush is not None:
        ttk.Label(bar, text='閲覧・共有ページ').grid(row=0, column=4, sticky='w', padx=(16, 0))
        ttk.Button(bar, textvariable=pending, command=on_flush).grid(row=1, column=4, sticky='w', padx=(16, 0))
    summary = tk.StringVar()
    ttk.Label(parent, textvariable=summary).pack(anchor='w', pady=(10, 0))
    hint = tk.StringVar()
    ttk.Label(parent, textvariable=hint, style='Sub.TLabel').pack(anchor='w', pady=(0, 6))
    # 表（ローテーション表）：台を縦、選んだ日までの7日を横。マスを押すとその日の🌈を付け外し。右端＝最後の🌈から何日。
    grid_frame = ttk.Frame(parent)
    canvas = tk.Canvas(grid_frame, highlightthickness=0, background=CELL_NONE)
    grid_scroll = ttk.Scrollbar(grid_frame, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=grid_scroll.set)
    inner = tk.Frame(canvas, background=CELL_NONE)
    canvas.create_window((0, 0), window=inner, anchor='nw')
    inner.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.pack(side='left', fill='both', expand=True)
    grid_scroll.pack(side='left', fill='y')

    def wheel(event):
        canvas.yview_scroll(-int(event.delta / 120), 'units')
    canvas.bind('<Enter>', lambda _e: canvas.bind_all('<MouseWheel>', wheel))
    canvas.bind('<Leave>', lambda _e: canvas.unbind_all('<MouseWheel>'))
    # 一覧（今までの表）。
    frame = ttk.Frame(parent)
    columns = ('mark', 'rack', 'machine', 'games', 'bb', 'rb', 'net', 'last', 'count')
    table = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
    for key, label, width, anchor in (('mark', RAINBOW_MARK, 40, 'center'), ('rack', '台番', 60, 'e'),
                                      ('machine', '機種', 300, 'w'), ('games', '回転数', 76, 'e'),
                                      ('bb', 'BB', 44, 'e'), ('rb', 'RB', 44, 'e'), ('net', '推定差枚', 90, 'e'),
                                      ('last', f'最終{RAINBOW_MARK}', 120, 'e'),
                                      ('count', f'{RAINBOW_COUNT_DAYS}日{RAINBOW_MARK}', 70, 'e')):
        table.heading(key, text=label)
        table.column(key, width=width, anchor=anchor, stretch=key == 'machine')
    table.tag_configure('plus', foreground=PLUS_COLOR)
    table.tag_configure('minus', foreground=MINUS_COLOR)
    table.tag_configure('rainbow', background=RAINBOW_BG)
    scroll = ttk.Scrollbar(frame, orient='vertical', command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    table.pack(side='left', fill='both', expand=True)
    scroll.pack(side='left', fill='y')
    state = {'rows': [], 'cells': {}, 'today_mode': False}
    parent.variety_cells = state['cells']   # 試験で押すマス（{(台番号, 日): Label}）
    parent.variety_mode = mode_var
    parent.variety_day = day_var

    def location():
        return next((key for key, label in STORE_NAMES.items() if label == store_var.get()), None)

    def values(r):
        net = '—' if r['net'] is None else signed_medals(r['net']) + ('※' if r['needs_check'] else '')
        machine = r['machine'] + (f"（この日：{r['day_machine']}）" if r.get('day_machine') else '')
        dash = lambda value: '—' if value is None else value
        return (rainbow_cell(r) if r['editable'] or r['rainbow'] else '—', r['rack'], machine,
                '—' if r['games'] is None else f"{r['games']:,}", dash(r['bb']), dash(r['rb']), net,
                last_rainbow_text(r), r['rainbow_count'])

    def tags(r):
        net = r['net'] or 0
        return ('plus' if net > 0 else 'minus' if net < 0 else 'zero',) + (('rainbow',) if r['rainbow'] else ())

    def set_summary():
        rows = state['rows']
        machines = len({r['machine'] for r in rows})
        marked = sum(r['rainbow'] for r in rows)
        reference = f"・台一覧の参照日 {rows[0]['lineup_day']}・当日未取得 {sum(not r['recorded'] for r in rows)}台" if rows and day_var.get() == today_jst() else ''
        summary.set((f'バラエティ {len(rows)}台（{machines}機種）・この日の{RAINBOW_MARK} {marked}台' + reference) if rows
                    else 'この日はバラエティの台の記録がありません。')

    def show():
        rows = sorted(state['rows'], key=SORTS[sort_var.get()])
        state['shown'] = rows
        set_summary()
        if mode_var.get() == 'grid':
            frame.pack_forget()
            grid_frame.pack(fill='both', expand=True)
            hint.set(f'マスを押すと、その日の{RAINBOW_MARK}を付け外しします。本日の「＋」は数値の取り込み前でも保存できます。'
                     f'過去の記録の無い日「·」は押せません。'
                     f'青い枠＝選んだ日。空き＝最後の{RAINBOW_MARK}から何日。並べ方も使えます。')
            show_grid(rows)
            return
        grid_frame.pack_forget()
        frame.pack(fill='both', expand=True)
        hint.set(f'{RAINBOW_MARK}の列を押すと付け外し。本日の数値「—」は未取得です。印だけ保存し、あとから取り込んでも残します。')
        table.delete(*table.get_children())
        for i, r in enumerate(rows):
            table.insert('', 'end', iid=str(i), values=values(r), tags=tags(r))

    def paint(cell, record, selected):
        on = bool(record and record['rainbow'])
        editable = bool(record and record.get('editable', True))
        cell.configure(text=RAINBOW_MARK if on else ('＋' if record and record.get('recorded') is False and editable
                                                    else '·' if not record or not editable else ''),
                       background=CELL_ON if on else CELL_OFF if record else CELL_NONE,
                       cursor='hand2' if editable else '',
                       highlightbackground=CELL_DAY if selected else CELL_NONE)

    def show_grid(rows):
        for child in inner.winfo_children():
            child.destroy()
        state['cells'].clear()
        where, day = location(), day_var.get()
        if not rows or where is None or not day:
            return
        days = window_days(day)
        state['window'] = days
        state['by_day'] = rotation_cells(db_path, where, days)
        if today_jst() in days:
            pending_today = {r['rack']: r for r in (rows if day == today_jst() else
                             variety_rows(db_path, where, today_jst(), latest=rows[0]['lineup_day']))}
            for rack, r in pending_today.items():
                if not r['recorded']:
                    state['by_day'][today_jst()][rack] = r
        font, small = ('Yu Gothic UI', 10), ('Yu Gothic UI', 9)
        heads = [('台番', 'w'), ('機種', 'w')] + [
            (f'{int(d[5:7])}/{int(d[8:10])}\n{WEEKDAYS[date.fromisoformat(d).weekday()]}', 'center') for d in days] + [('空き', 'center')]
        for column, (text, anchor) in enumerate(heads):
            tk.Label(inner, text=text, background=CELL_NONE, foreground='#6E6E73', font=small, anchor=anchor,
                     justify='center').grid(row=0, column=column, sticky='ew', padx=2, pady=(0, 4))
        state['gaps'] = {}
        for i, r in enumerate(rows, start=1):
            rack = int(r['rack'])
            tk.Label(inner, text=str(rack), background=CELL_NONE, font=(font[0], 10, 'bold'), anchor='w').grid(
                row=i, column=0, sticky='w', padx=(2, 6))
            name = r['machine'] + (f"（この日：{r['day_machine']}）" if r.get('day_machine') else '')
            tk.Label(inner, text=name if len(name) <= 22 else name[:21] + '…', background=CELL_NONE, font=small,
                     foreground='#1D1D1F', anchor='w', width=24).grid(row=i, column=1, sticky='w', padx=(0, 6))
            for k, d in enumerate(days):
                record = state['by_day'][d].get(rack)
                cell = tk.Label(inner, width=4, height=1, font=font, highlightthickness=2, borderwidth=0)
                paint(cell, record, d == day)
                cell.grid(row=i, column=2 + k, padx=2, pady=2, ipady=4, sticky='nsew')
                cell.bind('<Button-1>', lambda _e, rack=rack, d=d: toggle_cell(rack, d))
                state['cells'][(rack, d)] = cell
            gap = tk.Label(inner, text=gap_text(row_gap(r)), background=CELL_NONE, font=(font[0], 10, 'bold'), width=5)
            gap.grid(row=i, column=2 + len(days), padx=(6, 2))
            state['gaps'][rack] = gap

    def row_gap(r):
        if r['rainbow']:
            return 0
        return days_since(r.get('prev_rainbow'), day_var.get())

    def toggle_cell(rack, d):
        """表のマス：記録のある台と、本日の未取得の台の🌈を付け外しする。"""
        if check_today_rollover():
            return
        record = state['by_day'].get(d, {}).get(rack)
        if record is None:
            return
        if record.get('recorded') is False and d != today_jst():
            return
        on = not record['rainbow']
        db = Store(db_path)
        try:
            db.set_rainbow(location(), d, rack, on, allow_missing=d == today_jst())
            previous = db.last_rainbow_days(location(), day_var.get()).get(rack)
        except ValueError as error:
            messagebox.showwarning(RAINBOW_MARK, str(error), parent=parent)
            return
        finally:
            db.close()
        record['rainbow'] = on
        paint(state['cells'][(rack, d)], record, d == day_var.get())
        for r in state['rows']:
            if int(r['rack']) == rack:
                if d == day_var.get():
                    r['rainbow'] = on
                if d <= day_var.get() and d >= (date.fromisoformat(day_var.get()) - timedelta(days=RAINBOW_COUNT_DAYS - 1)).isoformat():
                    r['rainbow_count'] += 1 if on else -1
                r['prev_rainbow'] = previous
                state['gaps'][rack].configure(text=gap_text(row_gap(r)))
        set_summary()
        on_marked()

    def load(*_args):
        where = location()
        if where is None or not day_var.get():
            state['rows'] = []
        else:
            state['rows'] = variety_rows(db_path, where, day_var.get())
        show()

    def refresh_days(*_args):
        where = location()
        db = Store(db_path)
        try:
            days = db.days_for(where) if where else []
        finally:
            db.close()
        choices = sorted(set(days + [today_jst()]), reverse=True)
        day_combo['values'] = choices
        chosen = day_var.get() if day_var.get() in choices else (days[0] if days else today_jst())
        if chosen != day_var.get():
            day_var.set(chosen)   # 日付が変わると load が呼ばれる
        else:
            load()

    def go_today():
        state['today_mode'] = True
        state['today_day'] = today_jst()
        if day_var.get() != today_jst():
            day_var.set(today_jst())
        else:
            load()

    def check_today_rollover():
        if state['today_mode'] and state['today_day'] != today_jst():
            go_today()
            messagebox.showinfo(RAINBOW_MARK, '日付が変わりました。本日の台一覧を確認して、もう一度押してください。', parent=parent)
            return True
        return False

    def day_changed(*_args):
        state['today_mode'] = day_var.get() == today_jst()
        if state['today_mode']:
            state['today_day'] = day_var.get()
        load()

    today_button = ttk.Button(bar, text='本日（取り込み前も🌈）', command=go_today)
    today_button.grid(row=2, column=1, sticky='w', pady=(4, 0))
    parent.variety_today_button = today_button

    def toggle(event):
        # 🌈の列（いちばん左）を押したときだけ付け外しする。ほかの列は行を選ぶだけ。
        if table.identify_region(event.x, event.y) != 'cell' or table.identify_column(event.x) != '#1':
            return None
        iid = table.identify_row(event.y)
        if not iid:
            return None
        row = state['shown'][int(iid)]
        if check_today_rollover():
            return 'break'
        if not row['recorded'] and day_var.get() != today_jst():
            messagebox.showinfo(RAINBOW_MARK, f"{row['rack']}番台は{day_var.get()}の記録がないため、{RAINBOW_MARK}を付けられません。",
                                parent=parent)
            return 'break'
        on = not row['rainbow']
        db = Store(db_path)
        try:
            db.set_rainbow(location(), day_var.get(), row['rack'], on, allow_missing=day_var.get() == today_jst())
        except ValueError as error:
            messagebox.showwarning(RAINBOW_MARK, str(error), parent=parent)
            return 'break'
        finally:
            db.close()
        row['rainbow'] = on
        row['rainbow_count'] += 1 if on else -1
        table.item(iid, values=values(row), tags=tags(row))
        set_summary()
        on_marked()
        return 'break'

    table.bind('<Button-1>', toggle)
    store_var.trace_add('write', refresh_days)
    day_var.trace_add('write', day_changed)
    sort_var.trace_add('write', lambda *_a: show())

    def change_mode(*_args):
        try:
            save_settings(data_dir, variety_mode=mode_var.get())
        except OSError:
            pass   # 覚えられなくても切り替えは使える
        show()
    mode_var.trace_add('write', change_mode)
    # PC本体は最初に「取り込み」を開く。表のDB読込・数百個のセル作成はタブを開いたときに行う。
    if not defer_load:
        refresh_days()
    return refresh_days
