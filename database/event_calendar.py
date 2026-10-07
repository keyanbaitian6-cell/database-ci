"""イベントカレンダー（PC版・メルヘン2店舗、2026-10-07）。仕様は ../EVENT_CALENDAR.md。

先の日にもイベント名を入れられる。入力した時刻を残し（core.Store.set_date_event_days）、
前日までに入力していないイベントは名前の後ろに「＊」を付ける。Android・閲覧ページと同じ作り。
"""
import calendar
from datetime import date, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

from core import STORE_NAMES, Store, date_event_in_advance

WEEKDAYS = '日月火水木金土'
# 「期間でまとめて入力」で一度に付けられる日数。
RANGE_MAX_DAYS = 62
LATE_MARK = '＊'
LATE_NOTE = '＊＝前日までに入力した記録がありません（当日以降の入力・時刻不明）。予想の材料には使いません。'


def month_weeks(year, month):
    """Weeks from Sunday to Saturday; days outside the month are None."""
    return [[d if d.month == month else None for d in week]
            for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)]


def shift_month(first, months):
    index = first.year * 12 + first.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def range_days(first, last):
    """Every day from ``first`` to ``last`` (either order), as yyyy-mm-dd."""
    first, last = sorted((first, last))
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def cell_text(day, event):
    """The label of one calendar day: the day number and the event name (with ＊)."""
    if event is None:
        return str(day.day)
    mark = '' if date_event_in_advance(event) else LATE_MARK
    name = event['name'] if len(event['name']) <= 8 else event['name'][:7] + '…'
    return f'{day.day}\n{name}{mark}'


def ask_event_name(parent, title, current, names):
    """Free text with the past names as a drop-down. '' removes, None cancels."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)
    result = [None]
    ttk.Label(dialog, text=title, style='H2.TLabel').pack(anchor='w', padx=20, pady=(18, 2))
    ttk.Label(dialog, text='今までの名前から選ぶか、自由に入力します（60文字まで）。',
              style='Sub.TLabel').pack(anchor='w', padx=20)
    value = tk.StringVar(value=current or '')
    box = ttk.Combobox(dialog, textvariable=value, values=names, width=36)
    box.pack(fill='x', padx=20, pady=12)
    box.focus_set()
    buttons = ttk.Frame(dialog)
    buttons.pack(fill='x', padx=20, pady=(0, 18))

    def save():
        text = value.get().strip()
        if not text or len(text) > 60:
            messagebox.showwarning('イベント名', 'イベント名は1〜60文字で入力してください。', parent=dialog)
            return
        result[0] = text
        dialog.destroy()

    def remove():
        result[0] = ''
        dialog.destroy()

    ttk.Button(buttons, text='保存', style='Accent.TButton', command=save).pack(side='right')
    if current:
        ttk.Button(buttons, text='イベントなしにする', command=remove).pack(side='right', padx=(0, 8))
    ttk.Button(buttons, text='キャンセル', command=dialog.destroy).pack(side='right', padx=(0, 8))
    dialog.bind('<Return>', lambda _e: save())
    dialog.bind('<Escape>', lambda _e: dialog.destroy())
    dialog.grab_set()
    parent.wait_window(dialog)
    return result[0]


def open_event_calendar(root, db_path, location=None, on_changed=None, today=None):
    """Open the calendar window. ``on_changed(db)`` runs after each save
    (automatic backup, report) while the database is still open."""
    today = today or date.today()
    window = tk.Toplevel(root)
    window.title('イベントカレンダー')
    window.transient(root)
    window.minsize(760, 560)
    style = ttk.Style(window)
    style.configure('Day.TButton', padding=(4, 4), font=('Yu Gothic UI', 9))
    style.configure('Today.TButton', padding=(4, 4), font=('Yu Gothic UI', 9, 'bold'))
    style.configure('Picked.TButton', padding=(4, 4), font=('Yu Gothic UI', 9, 'bold'), background='#F2C14E')
    labels = list(STORE_NAMES.values())
    store_name = tk.StringVar(value=STORE_NAMES.get(location) or labels[0])
    month = [date(today.year, today.month, 1)]
    picking = tk.BooleanVar(value=False)
    picked = [None]
    status = tk.StringVar(value='')

    body = ttk.Frame(window, padding=20)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text='イベントカレンダー', style='H2.TLabel').pack(anchor='w')
    ttk.Label(body, style='Sub.TLabel', wraplength=700, text=(
        '日を押すとイベント名を入れられます。先の日にも入れられ、入力した時刻を残します。'
        'Android・閲覧ページとはバックアップで受け渡し、新しく入れた方が残ります。')).pack(anchor='w', pady=(0, 10))
    bar = ttk.Frame(body)
    bar.pack(fill='x', pady=(0, 8))
    ttk.Combobox(bar, textvariable=store_name, values=labels, state='readonly', width=28).pack(side='left')
    ttk.Button(bar, text='◀ 前の月', command=lambda: move(-1)).pack(side='left', padx=(16, 4))
    month_label = ttk.Label(bar, style='H3.TLabel', width=12, anchor='center')
    month_label.pack(side='left')
    ttk.Button(bar, text='次の月 ▶', command=lambda: move(1)).pack(side='left', padx=(4, 16))
    ttk.Checkbutton(bar, text='期間でまとめて入力', variable=picking,
                    command=lambda: reset_pick()).pack(side='left')
    grid = ttk.Frame(body)
    grid.pack(fill='both', expand=True)
    ttk.Label(body, textvariable=status, style='Sub.TLabel').pack(anchor='w', pady=(6, 0))
    ttk.Label(body, text=LATE_NOTE, style='Sub.TLabel', wraplength=700).pack(anchor='w')

    def current_location():
        return next(key for key, label in STORE_NAMES.items() if label == store_name.get())

    def events_for(location):
        db = Store(db_path)
        try:
            return ({e['day']: e for e in db.date_events(location=location)},
                    db.date_event_names(location))
        finally:
            db.close()

    def reset_pick():
        picked[0] = None
        status.set('最初の日を押してください。' if picking.get() else '')
        render()

    def move(months):
        month[0] = shift_month(month[0], months)
        render()

    def save(days, name):
        db = Store(db_path)
        try:
            db.set_date_event_days(current_location(), days, name or None)
            if on_changed:
                on_changed(db)
        except ValueError as error:
            messagebox.showwarning('イベント名', str(error), parent=window)
        finally:
            db.close()

    def on_day(day):
        location = current_location()
        events, names = events_for(location)
        if picking.get():
            if picked[0] is None:
                picked[0] = day
                status.set(f'{day.month}/{day.day} から。最後の日を押してください。')
                render()
                return
            days = range_days(picked[0], day)
            if len(days) > RANGE_MAX_DAYS:
                messagebox.showwarning('期間でまとめて入力', f'一度に入れられるのは{RANGE_MAX_DAYS}日までです。', parent=window)
                return
            first, last = days[0], days[-1]
            name = ask_event_name(window, f'{first[5:].replace("-", "/")}〜{last[5:].replace("-", "/")}のイベント（{len(days)}日）',
                                  None, names)
            if name is not None:
                save(days, name)
            picking.set(False)
            reset_pick()
            return
        current = events.get(day.isoformat())
        name = ask_event_name(window, f'{day.month}/{day.day}（{WEEKDAYS[(day.weekday() + 1) % 7]}）のイベント',
                              current['name'] if current else None, names)
        if name is not None:
            save([day.isoformat()], name)
        render()

    def render(*_args):
        for child in grid.winfo_children():
            child.destroy()
        first = month[0]
        month_label.configure(text=f'{first.year}年{first.month}月')
        events, _names = events_for(current_location())
        for column, name in enumerate(WEEKDAYS):
            ttk.Label(grid, text=name, style='H3.TLabel', anchor='center').grid(row=0, column=column, sticky='ew')
            grid.columnconfigure(column, weight=1, uniform='day')
        for row, week in enumerate(month_weeks(first.year, first.month), start=1):
            grid.rowconfigure(row, weight=1, uniform='week')
            for column, day in enumerate(week):
                if day is None:
                    continue
                style_name = ('Picked.TButton' if day == picked[0] else
                              'Today.TButton' if day == today else 'Day.TButton')
                ttk.Button(grid, text=cell_text(day, events.get(day.isoformat())), style=style_name,
                           command=lambda d=day: on_day(d)).grid(row=row, column=column, sticky='nsew', padx=1, pady=1)

    store_name.trace_add('write', render)
    render()
    return window
