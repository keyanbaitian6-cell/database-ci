"""イベントカレンダー（PC版、メルヘン2店舗 2026-10-07・P’s CUBE 2026-10-08）。仕様は ../EVENT_CALENDAR.md。

先の日にもイベント名を入れられる。入力した時刻を残し（core.Store.set_date_event_days）、
前日までに入力していないイベントは名前の後ろに「＊」を付ける。Android・閲覧ページと同じ作り。
各日にはその店の総差枚も出す（2026-10-08 利用者指定。メルヘンは推定差枚）。
"""
import calendar
from datetime import date, timedelta
import json
import math
import tkinter as tk
from tkinter import ttk, messagebox

from core import STORE_NAMES, Store, date_event_in_advance, implausible_numbers, rack_net, signed_medals

WEEKDAYS = '日月火水木金土'
# 「期間でまとめて入力」で一度に付けられる日数。
RANGE_MAX_DAYS = 62
LATE_MARK = '＊'
LATE_NOTE = '＊＝前日までに入力した記録がありません（当日以降の入力・時刻不明）。予想の材料には使いません。'
PLUS_COLOR, MINUS_COLOR, ZERO_COLOR = '#0066CC', '#C62828', '#707070'
DAY_BG, HOVER_BG, PICKED_BG = '#FFFFFF', '#EEF4FB', '#F2C14E'
DAY_BORDER, TODAY_BORDER = '#D2D2D7', '#0071E3'
# 「強かった機種」に入れる最小の台数（1台だけの機種は、たまたまに左右されるため入れない）。
STRONG_MACHINE_MIN_RACKS = 2


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


def net_text(net):
    """その日の総差枚の文字。差枚が1台も無い日は ''（0にしない）。メルヘンはほぼ毎日、要確認（※）の
    推定差枚の台を含むので、マスには※を付けない（下の説明に書く）。
    P’s CUBEで貸玉が複数ある日は、貸玉ごとに1行。"""
    if not net:
        return ''
    if 'by_rate' in net:
        return '\n'.join(f'{rate}スロ {text}' for rate, part in net['by_rate'].items() if (text := net_text(part)))
    if net['total'] is None:
        return ''
    return signed_medals(net['total'])


def net_color(net):
    total = (net or {}).get('total')
    return ZERO_COLOR if not total else PLUS_COLOR if total > 0 else MINUS_COLOR


def _add_net(totals, day, net, needs_check=False):
    entry = totals.setdefault(day, {'total': None, 'captured': 0, 'needs_check': 0})
    if net is None:
        return
    entry['total'] = (entry['total'] or 0) + net
    entry['captured'] += 1
    entry['needs_check'] += bool(needs_check)


def meruhen_day_nets(db, location, first, last):
    """メルヘンの日ごとの総差枚（推定差枚。Android・閲覧ページの dailyNet と同じ：数値異常の台は数えず、
    推定できない台は足さない）。グラフ画像は読まない（必要な値だけSQLiteで取り出す）。"""
    totals = {}
    query = ("SELECT day, json_extract(payload,'$.games'), json_extract(payload,'$.bb'), json_extract(payload,'$.rb'),"
             " json_extract(payload,'$.max_hold'), json_extract(payload,'$.graph_measurement'),"
             " json_extract(payload,'$.jo_net') FROM days"
             " WHERE store=? AND day BETWEEN ? AND ? AND json_valid(payload)")
    for day, games, bb, rb, max_hold, measurement, jo_net in db.db.execute(query, (location, first, last)):
        if implausible_numbers({'games': games, 'bb': bb, 'rb': rb, 'max_hold': max_hold}):
            continue
        try:
            measurement = json.loads(measurement) if measurement else None
        except ValueError:
            measurement = None
        # ジャグラーオンラインの差枚があれば優先（お試し、JUGGLER_ONLINE.md）。
        net, needs_check, _site = rack_net({'jo_net': jo_net, 'graph_measurement': measurement,
                                            'max_hold': max_hold, 'games': games})
        _add_net(totals, day, net, needs_check)
    return totals


def pscube_day_nets(records, first, last):
    """P’s CUBEの日ごとの総差枚（元グラフの確定差枚）。貸玉ごとに数え、貸玉が1つならその合計、
    複数あれば {'by_rate': {貸玉: 合計}}（別の貸玉は混ぜない）。数値異常の台は数えない。"""
    by_rate = {}
    for r in records:
        if not first <= r['day'] <= last:
            continue
        if ((r.get('games') or 0) > 20000 or (r.get('bb') or 0) > 500 or (r.get('rb') or 0) > 500
                or (r.get('my') or 0) > 100000):
            continue
        _add_net(by_rate.setdefault(r['rate'], {}), r['day'], r.get('net_medals'))
    if len(by_rate) <= 1:
        return next(iter(by_rate.values()), {})
    days = {day for totals in by_rate.values() for day in totals}
    return {day: {'by_rate': {rate: totals[day] for rate, totals in sorted(by_rate.items()) if day in totals}}
            for day in days}


def event_label(event):
    """イベント名（前日までに入力していなければ＊）。無い日は ''。"""
    if event is None:
        return ''
    return event['name'] + ('' if date_event_in_advance(event) else LATE_MARK)


def day_summary(rows):
    """日付を押したときのまとめ（2026-10-09 利用者指定。Android・閲覧ページの calendarDaySummary と同じ）。
    TOP10＝差枚の多い順（同じ差枚は回転数の多い方、次に台番号の小さい方。差枚の無い台は入れない）。
    強かった機種5選＝1台あたりの平均回転数の多い順（STRONG_MACHINE_MIN_RACKS台以上の機種。同じなら台数の多い方）。"""
    top = sorted((r for r in rows if r['net'] is not None), key=lambda r: (-r['net'], -r['games'], r['rack']))[:10]
    by_machine = {}
    for r in rows:
        by_machine.setdefault(r['machine'], []).append(r)
    machines = [{'machine': name, 'racks': len(items),
                 'average': math.floor(sum(r['games'] for r in items) / len(items) + 0.5)}
                for name, items in by_machine.items() if len(items) >= STRONG_MACHINE_MIN_RACKS]
    machines.sort(key=lambda m: (-m['average'], -m['racks'], m['machine']))
    return top, machines[:5]


def open_day_summary(parent, title, store_label, rows, net_label, event_text, on_edit, on_open=None):
    """その日・その店のTOP10と強かった機種5選の窓。on_edit(この窓) はイベント名を入れ直し、新しい表示を返す
    （やめたら None）。
    on_open(row) があれば、TOP10の行をダブルクリック（Enter）で結果を開く。"""
    top, machines = day_summary(rows)
    window = tk.Toplevel(parent)
    window.title(f'{title} {store_label}')
    window.transient(parent)
    body = ttk.Frame(window, padding=20)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text=title, style='H2.TLabel').pack(anchor='w')
    ttk.Label(body, text=store_label, style='Sub.TLabel').pack(anchor='w')
    line = ttk.Frame(body)
    line.pack(fill='x', pady=(8, 4))
    event_var = tk.StringVar(value=f'イベント：{event_text or "なし"}')
    ttk.Label(line, textvariable=event_var).pack(side='left')

    def edit():
        text = on_edit(window)
        if text is not None:
            event_var.set(f'イベント：{text or "なし"}')
    ttk.Button(line, text='イベントを編集', command=edit).pack(side='left', padx=(12, 0))
    nets = [r['net'] for r in rows if r['net'] is not None]
    if nets:
        total = tk.Frame(body)
        total.pack(anchor='w')
        ttk.Label(total, text=f'総{net_label} ').pack(side='left')
        tk.Label(total, text=signed_medals(sum(nets)), font=('Yu Gothic UI', 10, 'bold'),
                 fg=net_color({'total': sum(nets)})).pack(side='left')
        ttk.Label(total, text=f'（{net_label}がわかった台 {len(nets)}/{len(rows)}台）').pack(side='left')

    ttk.Label(body, text=f'TOP10（{net_label}の多い順）', style='H3.TLabel').pack(anchor='w', pady=(12, 2))
    columns = ('rank', 'rack', 'machine', 'games', 'bb', 'rb', 'net')
    table = ttk.Treeview(body, columns=columns, show='headings', height=max(1, len(top)), selectmode='browse')
    for key, label, width, anchor in (('rank', '順位', 44, 'e'), ('rack', '台番', 56, 'e'), ('machine', '機種', 260, 'w'),
                                      ('games', '回転数', 76, 'e'), ('bb', 'BB', 44, 'e'), ('rb', 'RB', 44, 'e'),
                                      ('net', net_label, 90, 'e')):
        table.heading(key, text=label)
        table.column(key, width=width, anchor=anchor, stretch=key == 'machine')
    table.tag_configure('plus', foreground=PLUS_COLOR)
    table.tag_configure('minus', foreground=MINUS_COLOR)
    for i, r in enumerate(top):
        table.insert('', 'end', iid=str(i), tags=('plus' if r['net'] > 0 else 'minus' if r['net'] < 0 else (),),
                     values=(i + 1, r['rack'], r['machine'], f"{r['games']:,}", r['bb'], r['rb'],
                             signed_medals(r['net']) + ('※' if r['needs_check'] else '')))
    if top:
        table.pack(fill='x')
    else:
        ttk.Label(body, text='この日は差枚がわかる台がありません。', style='Sub.TLabel').pack(anchor='w')
    if on_open and top:
        def open_selected(_event=None):
            selected = table.selection()
            if selected:
                on_open(top[int(selected[0])])
        table.bind('<Double-1>', open_selected)
        table.bind('<Return>', open_selected)
        ttk.Label(body, text='行をダブルクリックすると、結果を見るでその日・その機種を選んで結果を開きます。',
                  style='Sub.TLabel').pack(anchor='w')
    if net_label == '推定差枚':
        ttk.Label(body, text='推定差枚はグラフと最大持玉からの計算で、確定値ではありません（※は要確認）。',
                  style='Sub.TLabel').pack(anchor='w')

    ttk.Label(body, text='強かった機種5選（1台あたりの平均回転数）', style='H3.TLabel').pack(anchor='w', pady=(14, 2))
    strong = ttk.Treeview(body, columns=('rank', 'machine', 'average', 'racks'), show='headings',
                          height=max(1, len(machines)), selectmode='none')
    for key, label, width, anchor in (('rank', '順位', 44, 'e'), ('machine', '機種', 330, 'w'),
                                      ('average', '平均回転数', 100, 'e'), ('racks', '台数', 60, 'e')):
        strong.heading(key, text=label)
        strong.column(key, width=width, anchor=anchor, stretch=key == 'machine')
    for i, m in enumerate(machines):
        strong.insert('', 'end', values=(i + 1, m['machine'], f"{m['average']:,}", m['racks']))
    if machines:
        strong.pack(fill='x')
    else:
        ttk.Label(body, text=f'{STRONG_MACHINE_MIN_RACKS}台以上ある機種がありません。', style='Sub.TLabel').pack(anchor='w')
    ttk.Label(body, text=f'{STRONG_MACHINE_MIN_RACKS}台以上ある機種から。数値異常の台は数えていません。',
              style='Sub.TLabel').pack(anchor='w')
    ttk.Button(body, text='閉じる', command=window.destroy).pack(anchor='e', pady=(14, 0))
    window.bind('<Escape>', lambda _e: window.destroy())
    return window


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


class MeruhenEvents:
    """メルヘン2店舗のイベント（database.sqlite3）。"""
    title = 'イベントカレンダー'

    def __init__(self, db_path, on_changed=None):
        self.db_path, self.on_changed = db_path, on_changed
        self.stores = dict(STORE_NAMES)

    def load(self, location):
        db = Store(self.db_path)
        try:
            return {e['day']: e for e in db.date_events(location=location)}, db.date_event_names(location)
        finally:
            db.close()

    net_note = '差枚＝その日の総差枚（推定。グラフと最大持玉から計算できた台の合計で、確定値ではありません。要確認の台も含みます）。'

    def nets(self, location, first, last):
        db = Store(self.db_path)
        try:
            return meruhen_day_nets(db, location, first, last)
        finally:
            db.close()

    net_label = '推定差枚'

    def day_records(self, location, day):
        """その日・その店の台（数値異常の台は除く）。差枚は推定差枚（決められない台は None）。"""
        db = Store(self.db_path)
        try:
            rows = db.db.execute(
                "SELECT rack, machine, json_extract(payload,'$.games'), json_extract(payload,'$.bb'),"
                " json_extract(payload,'$.rb'), json_extract(payload,'$.max_hold'),"
                " json_extract(payload,'$.graph_measurement'), json_extract(payload,'$.jo_net') FROM days"
                " WHERE store=? AND day=? AND json_valid(payload)", (location, day)).fetchall()
        finally:
            db.close()
        result = []
        for rack, machine, games, bb, rb, max_hold, measurement, jo_net in rows:
            if implausible_numbers({'games': games, 'bb': bb, 'rb': rb, 'max_hold': max_hold}):
                continue
            try:
                measurement = json.loads(measurement) if measurement else None
            except ValueError:
                measurement = None
            net, needs_check, _site = rack_net({'jo_net': jo_net, 'graph_measurement': measurement,
                                                'max_hold': max_hold, 'games': games})
            result.append({'rack': rack, 'machine': machine, 'games': games or 0, 'bb': bb, 'rb': rb,
                           'net': net, 'needs_check': bool(needs_check)})
        return result

    def save(self, location, days, name):
        db = Store(self.db_path)
        try:
            db.set_date_event_days(location, days, name or None)
            if self.on_changed:
                self.on_changed(db)
        finally:
            db.close()


class PscubeEvents:
    """P’s CUBEのイベント（pscube.sqlite3）。店舗の全貸玉に同じ名前を付ける（PscubeStore.set_date_event_days）。"""
    title = 'イベントカレンダー（P’s CUBE）'

    def __init__(self, db_path, on_changed=None, label='P’s CUBE'):
        self.db_path, self.on_changed = db_path, on_changed
        self.stores = {'pscube': label}

    def load(self, _location):
        import pscube_import
        store = pscube_import.PscubeStore(self.db_path)
        try:
            return store.date_event_entries(), store.date_event_names()
        finally:
            store.close()

    net_note = '差枚＝その日の総差枚（元グラフの差枚がわかった台の合計）。'

    def nets(self, _location, first, last):
        import pscube_import
        store = pscube_import.PscubeStore(self.db_path)
        try:
            records = [json.loads(row[0]) for row in store.db.execute('SELECT payload FROM records')]
        finally:
            store.close()
        return pscube_day_nets(records, first, last)

    net_label = '差枚'

    def day_records(self, _location, day):
        """その日の台（数値異常の台は除く）。貸玉が複数ある日は、機種名の前に貸玉を付けて分ける。"""
        import pscube_import
        store = pscube_import.PscubeStore(self.db_path)
        try:
            records = [r for r in (json.loads(row[0]) for row in store.db.execute('SELECT payload FROM records'))
                       if r.get('day') == day]
        finally:
            store.close()
        rates = {r['rate'] for r in records}
        return [{'rack': r['rack'], 'machine': (f"{r['rate']}スロ " if len(rates) > 1 else '') + r['machine'],
                 'games': r.get('games') or 0, 'bb': r.get('bb'), 'rb': r.get('rb'),
                 'net': r.get('net_medals'), 'needs_check': False}
                for r in records
                if not ((r.get('games') or 0) > 20000 or (r.get('bb') or 0) > 500 or (r.get('rb') or 0) > 500
                        or (r.get('my') or 0) > 100000)]

    def save(self, _location, days, name):
        import pscube_import
        store = pscube_import.PscubeStore(self.db_path)
        try:
            store.set_date_event_days(days, name or None)
            if self.on_changed:
                self.on_changed(store)
        finally:
            store.close()


def open_event_calendar(root, db_path, location=None, on_changed=None, today=None, events=None, on_open_record=None):
    """Open the calendar window. ``events`` is MeruhenEvents (default) or PscubeEvents.
    ``on_changed(db)`` runs after each save (automatic backup, report) while the database is still open.
    日付を押すと、記録のある日はその日のまとめ（TOP10・強かった機種5選）、無い日はイベント名の入力。
    ``on_open_record(location, day, row)`` があれば、まとめのTOP10の行から結果を開ける。"""
    today = today or date.today()
    events = events or MeruhenEvents(db_path, on_changed)
    window = tk.Toplevel(root)
    window.title(events.title)
    window.transient(root)
    window.minsize(760, 560)
    labels = list(events.stores.values())
    store_name = tk.StringVar(value=events.stores.get(location) or labels[0])
    month = [date(today.year, today.month, 1)]
    picking = tk.BooleanVar(value=False)
    picked = [None]
    status = tk.StringVar(value='')
    net_cache = {}

    body = ttk.Frame(window, padding=20)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text=events.title, style='H2.TLabel').pack(anchor='w')
    ttk.Label(body, style='Sub.TLabel', wraplength=700, text=(
        '日を押すとイベント名を入れられます。先の日にも入れられ、入力した時刻を残します。'
        '閲覧ページで入れたイベントは共有カレンダーから、Androidとはバックアップで受け渡し、'
        '新しく入れた方が残ります。')).pack(anchor='w', pady=(0, 10))
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
    ttk.Label(body, text=events.net_note, style='Sub.TLabel', wraplength=700).pack(anchor='w')
    ttk.Label(body, text=LATE_NOTE, style='Sub.TLabel', wraplength=700).pack(anchor='w')

    def current_location():
        return next(key for key, label in events.stores.items() if label == store_name.get())

    def events_for(location):
        return events.load(location)

    def reset_pick():
        picked[0] = None
        status.set('最初の日を押してください。' if picking.get() else '')
        render()

    def move(months):
        month[0] = shift_month(month[0], months)
        render()

    def save(days, name):
        try:
            events.save(current_location(), days, name or None)
        except ValueError as error:
            messagebox.showwarning('イベント名', str(error), parent=window)

    def on_day(day):
        entries, names = events_for(current_location())
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
        location = current_location()
        title = f'{day.month}/{day.day}（{WEEKDAYS[(day.weekday() + 1) % 7]}）'
        try:
            rows = events.day_records(location, day.isoformat())
        except Exception as error:  # 台が読めなくてもイベントは入れられる
            status.set(f'その日の台を読めませんでした：{error}')
            rows = []
        if not rows:
            edit_one(window, location, day, title)
            render()
            return
        open_day_summary(
            window, title, events.stores[location], rows, events.net_label,
            event_label(entries.get(day.isoformat())),
            lambda parent: edit_one(parent, location, day, title),
            None if on_open_record is None else lambda row: on_open_record(location, day.isoformat(), row))

    def edit_one(parent, location, day, title):
        """1日のイベント名を入れる・変える・消す。カレンダーを描き直し、新しい表示（＊つき）を返す。"""
        entries, names = events.load(location)
        current = entries.get(day.isoformat())
        name = ask_event_name(parent, f'{title}のイベント', current['name'] if current else None, names)
        if name is None:
            return None
        save([day.isoformat()], name)
        render()
        entries, _names = events.load(location)
        return event_label(entries.get(day.isoformat()))

    def render(*_args):
        for child in grid.winfo_children():
            child.destroy()
        first = month[0]
        month_label.configure(text=f'{first.year}年{first.month}月')
        entries, _names = events_for(current_location())
        nets = month_nets()
        for column, name in enumerate(WEEKDAYS):
            ttk.Label(grid, text=name, style='H3.TLabel', anchor='center').grid(row=0, column=column, sticky='ew')
            grid.columnconfigure(column, weight=1, uniform='day')
        for row, week in enumerate(month_weeks(first.year, first.month), start=1):
            grid.rowconfigure(row, weight=1, uniform='week')
            for column, day in enumerate(week):
                if day is not None:
                    day_cell(day, entries.get(day.isoformat()), nets.get(day.isoformat())).grid(
                        row=row, column=column, sticky='nsew', padx=1, pady=1)

    def month_nets():
        """表示中の店・月の総差枚。月・店ごとに1回だけ数える（イベントを入れても差枚は変わらない）。"""
        first = month[0]
        key = (current_location(), first)
        if key not in net_cache:
            last = shift_month(first, 1) - timedelta(days=1)
            try:
                net_cache[key] = events.nets(key[0], first.isoformat(), last.isoformat())
            except Exception as error:  # 差枚が読めなくてもイベントの入力は続けられる
                status.set(f'差枚を読めませんでした：{error}')
                net_cache[key] = {}
        return net_cache[key]

    def day_cell(day, event, net):
        """1日のマス：日付・イベント名（＊）・総差枚（プラスは青、マイナスは赤）。押すとイベントを入れる。"""
        is_picked, is_today = day == picked[0], day == today
        background = PICKED_BG if is_picked else DAY_BG
        frame = tk.Frame(grid, bg=background, cursor='hand2', highlightthickness=2 if is_today else 1,
                         highlightbackground=TODAY_BORDER if is_today else DAY_BORDER)
        number, _, name = cell_text(day, event).partition('\n')
        bold = ('Yu Gothic UI', 9, 'bold')
        parts = [tk.Label(frame, text=number, bg=background, anchor='w',
                          font=bold if is_today or is_picked else ('Yu Gothic UI', 9))]
        if name:
            parts.append(tk.Label(frame, text=name, bg=background, anchor='w', font=('Yu Gothic UI', 9)))
        if text := net_text(net):
            parts.append(tk.Label(frame, text=text, bg=background, anchor='w', justify='left', font=bold,
                                  fg=net_color(net)))
        for part in parts:
            part.pack(fill='x', padx=4, pady=(2, 0))

        def paint(color):
            for widget in (frame, *parts):
                widget.configure(bg=color)
        for widget in (frame, *parts):
            widget.bind('<Button-1>', lambda _e, d=day: on_day(d))
            if not is_picked:
                widget.bind('<Enter>', lambda _e: paint(HOVER_BG))
                widget.bind('<Leave>', lambda _e: paint(DAY_BG))
        return frame

    store_name.trace_add('write', render)
    render()
    return window
