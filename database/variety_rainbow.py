"""バラエティの🌈（PC、2026-10-11）。仕様は ../RAINBOW.md「バラエティのタブ」。

利用者「特にバラエティはローテーションで入れる傾向があるので、バラエティの機種一覧をpcで表示させて、
この🌈マークをつけられるようにもしてほしい。そのタブかページを作って」。
店舗・日付を選ぶと、その日のバラエティ（1〜3台の機種、core.VARIETY_MAX_RACKS）の台を並べ、🌈の列を
押すと確定が出た台の印を付け外しする。ローテーションを追えるよう、最終🌈と直近30日の🌈回数を出す。
"""
from datetime import date, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

from core import RAINBOW_MARK, STORE_NAMES, VARIETY_MAX_RACKS, Store, signed_medals
from event_calendar import (MINUS_COLOR, PLUS_COLOR, RAINBOW_BG, MeruhenEvents, last_rainbow_text,
                            rainbow_cell)

# 🌈回数を数える日数（その日を含めて30日）。
RAINBOW_COUNT_DAYS = 30
SORTS = {
    '台番順': lambda r: r['rack'],
    f'最終{RAINBOW_MARK}の古い順': lambda r: (r['rainbow'], r.get('prev_rainbow') or '', r['rack']),
    '機種順': lambda r: (r['machine'], r['rack']),
}
# 付け外しのあと、バックアップ・閲覧用ファイルを作り直すまで待つ時間（続けて押すたびに作り直さない）。
SAVE_DELAY_MS = 4000


def variety_lineup(rows):
    """その日の台のうち、バラエティ（その日に1〜VARIETY_MAX_RACKS台の機種）の台。"""
    counts = {}
    for r in rows:
        counts[r['machine']] = counts.get(r['machine'], 0) + 1
    return [r for r in rows if counts[r['machine']] <= VARIETY_MAX_RACKS]


def variety_rows(db_path, location, day, latest=None):
    """バラエティの台の一覧。並べる台と機種名は、その店の最新の取り込み日 [latest] のバラエティから取る
    （2026-10-11 利用者「機種一覧名はとりあえず最新の機種一覧からとって表示させておけばいい。入れ替えとかで
    変わったらその都度書き換えて」＝入れ替えは新しい日を取り込めば自動で変わる）。
    数値・🌈・最終🌈は選んだ日 [day] の、同じ台番号の記録（無ければ数値は None、🌈は付けられない）。
    その日は別の機種だった台は `day_machine` にその日の機種名。直近30日（day を含む）の🌈回数 `rainbow_count`。
    表示しない機種・数値異常の台は入れない。"""
    events = MeruhenEvents(db_path)
    db = Store(db_path)
    try:
        if latest is None:
            days = db.days_for(location)
            latest = days[0] if days else day
        since = (date.fromisoformat(day) - timedelta(days=RAINBOW_COUNT_DAYS - 1)).isoformat()
        found = db.rainbow_counts(location, since, day)
        previous = db.last_rainbow_days(location, day)
    finally:
        db.close()
    lineup = variety_lineup(events.day_records(location, latest))
    on_day = {int(r['rack']): r for r in (events.day_records(location, day) if day != latest else lineup)}
    rows = []
    for current in lineup:
        rack = int(current['rack'])
        record = on_day.get(rack)
        row = dict(record) if record else {'rack': rack, 'games': None, 'bb': None, 'rb': None, 'net': None,
                                           'needs_check': False, 'rainbow': False, 'day': day,
                                           'prev_rainbow': previous.get(rack)}
        row['machine'] = current['machine']
        row['day_machine'] = record['machine'] if record and record['machine'] != current['machine'] else None
        row['recorded'] = record is not None
        row['rainbow_count'] = found.get(rack, 0)
        rows.append(row)
    return sorted(rows, key=SORTS['台番順'])


def build_variety_tab(parent, db_path, on_changed, default_location=None):
    """「バラエティ🌈」のタブの中身。on_changed(db) は付け外しのあと（少し待ってまとめて）呼ぶ
    （バックアップ・閲覧用ファイル・結果の作り直し）。表示を描き直す関数を返す（タブを開いたとき用）。"""
    ttk.Label(parent, text=f'バラエティの{RAINBOW_MARK}', style='H2.TLabel').pack(anchor='w')
    ttk.Label(parent, text=f'最新の取り込み日に1〜{VARIETY_MAX_RACKS}台の機種の台（入れ替えは、新しい日を取り込むと自動で変わります）。'
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
    summary = tk.StringVar()
    ttk.Label(parent, textvariable=summary).pack(anchor='w', pady=(10, 4))
    frame = ttk.Frame(parent)
    frame.pack(fill='both', expand=True)
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
    state = {'rows': [], 'pending': None}

    def location():
        return next((key for key, label in STORE_NAMES.items() if label == store_var.get()), None)

    def values(r):
        net = '—' if r['net'] is None else signed_medals(r['net']) + ('※' if r['needs_check'] else '')
        machine = r['machine'] + (f"（この日：{r['day_machine']}）" if r.get('day_machine') else '')
        dash = lambda value: '—' if value is None else value
        return (rainbow_cell(r) if r['recorded'] else '—', r['rack'], machine,
                '—' if r['games'] is None else f"{r['games']:,}", dash(r['bb']), dash(r['rb']), net,
                last_rainbow_text(r), r['rainbow_count'])

    def tags(r):
        net = r['net'] or 0
        return ('plus' if net > 0 else 'minus' if net < 0 else 'zero',) + (('rainbow',) if r['rainbow'] else ())

    def show():
        table.delete(*table.get_children())
        rows = sorted(state['rows'], key=SORTS[sort_var.get()])
        state['shown'] = rows
        for i, r in enumerate(rows):
            table.insert('', 'end', iid=str(i), values=values(r), tags=tags(r))
        machines = len({r['machine'] for r in rows})
        marked = sum(r['rainbow'] for r in rows)
        summary.set(f'バラエティ {len(rows)}台（{machines}機種）・この日の{RAINBOW_MARK} {marked}台' if rows
                    else 'この日はバラエティの台の記録がありません。')

    def load(*_args):
        where = location()
        if where is None or not day_var.get():
            state['rows'] = []
        else:
            days = day_combo['values']
            state['rows'] = variety_rows(db_path, where, day_var.get(), days[0] if days else None)
        show()

    def refresh_days(*_args):
        where = location()
        db = Store(db_path)
        try:
            days = db.days_for(where) if where else []
        finally:
            db.close()
        day_combo['values'] = days
        chosen = day_var.get() if day_var.get() in days else (days[0] if days else '')
        if chosen != day_var.get():
            day_var.set(chosen)   # 日付が変わると load が呼ばれる
        else:
            load()

    def save_later():
        if state['pending'] is not None:
            parent.after_cancel(state['pending'])

        def run():
            state['pending'] = None
            db = Store(db_path)
            try:
                on_changed(db)
            finally:
                db.close()
        state['pending'] = parent.after(SAVE_DELAY_MS, run)

    def toggle(event):
        # 🌈の列（いちばん左）を押したときだけ付け外しする。ほかの列は行を選ぶだけ。
        if table.identify_region(event.x, event.y) != 'cell' or table.identify_column(event.x) != '#1':
            return None
        iid = table.identify_row(event.y)
        if not iid:
            return None
        row = state['shown'][int(iid)]
        if not row['recorded']:
            messagebox.showinfo(RAINBOW_MARK, f"{row['rack']}番台は{day_var.get()}の記録がないため、{RAINBOW_MARK}を付けられません。",
                                parent=parent)
            return 'break'
        on = not row['rainbow']
        db = Store(db_path)
        try:
            db.set_rainbow(location(), day_var.get(), row['rack'], on)
        except ValueError as error:
            messagebox.showwarning(RAINBOW_MARK, str(error), parent=parent)
            return 'break'
        finally:
            db.close()
        row['rainbow'] = on
        row['rainbow_count'] += 1 if on else -1
        table.item(iid, values=values(row), tags=tags(row))
        marked = sum(r['rainbow'] for r in state['rows'])
        machines = len({r['machine'] for r in state['rows']})
        summary.set(f'バラエティ {len(state["rows"])}台（{machines}機種）・この日の{RAINBOW_MARK} {marked}台')
        save_later()
        return 'break'

    table.bind('<Button-1>', toggle)
    store_var.trace_add('write', refresh_days)
    day_var.trace_add('write', load)
    sort_var.trace_add('write', lambda *_a: show())
    refresh_days()
    return refresh_days
