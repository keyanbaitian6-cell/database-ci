"""機種一覧（PC、2026-11-01）。

利用者「PCの結果を読むの作りはあまり好きではないので、今バラエティを表示しているような作りで見たい」
「バラエティ以外の他の機種を一覧でだしつつ、機種だけみたいときは（プルダウン）で切り替えられるように」。
バラエティ🌈のタブ（variety_rainbow.py）と同じ作り：店舗・日付・機種・並べ方を選び、表の見出しを押すと並べ替え、
🌈の列を押すと確定が出た台の印を付け外しする。列は台番（翌日候補の★☆）・機種・回転数・BB・RB・推定差枚・
設定候補・合計点（「結果を見る」のHTMLと同じ計算：core.scored_rows・provisional_next_day_candidates）。

バラエティ🌈のタブに出る機種（その日に rainbow_variety_max 台以下の機種）は入れない。

P’s CUBE（P-STATION、2026-11-02 利用者「P-STATIONの分がないのはなぜ？」→「点数なしで足す」）：PC版にはP’s CUBEの
採点が無いので、合計点・設定候補・★☆は「—」。差枚は元グラフの確定差枚、MY（最大持玉の代わり）の列を出す。PC版に
P’s CUBEのバラエティ🌈のタブは無いので、全機種を入れる。🌈の印は付けられない（メルヘンだけ）。
"""
import json
import threading
import tkinter as tk
from collections import Counter
from tkinter import ttk, messagebox

from core import RAINBOW_MARK, STORE_NAMES, Store, implausible_numbers, provisional_next_day_candidates, rack_net, \
    scored_rows, signed_medals
from event_calendar import MINUS_COLOR, PLUS_COLOR, RAINBOW_BG, rainbow_cell
from variety_rainbow import rainbow_variety_max

ALL_MACHINES = 'すべての機種'


def _number(value, descending):
    """数値の並べ方のキー。数値の無い台（異常・推定できない台）は多い順・少ない順のどちらでも最後。"""
    return (value is None, -(value or 0) if descending else value or 0)


SORTS = {
    '台番順': lambda r: r['rack'],
    '機種順': lambda r: (r['machine'], r['rack']),
    '回転数の多い順': lambda r: (*_number(r['games'], True), r['rack']),
    '回転数の少ない順': lambda r: (*_number(r['games'], False), r['rack']),
    '差枚の多い順': lambda r: (*_number(r['net'], True), r['rack']),
    '差枚の少ない順': lambda r: (*_number(r['net'], False), r['rack']),
    '合計点の高い順': lambda r: (*_number(r['total'], True), r['rack']),
    '合計点の低い順': lambda r: (*_number(r['total'], False), r['rack']),
}
# 見出しを押したときの並べ方（2つあるものは押すたびに切り替え）。バラエティ🌈と同じ。数値は最初に多い順。
HEADING_SORTS = {
    'rack': ('台番順',),
    'machine': ('機種順',),
    'games': ('回転数の多い順', '回転数の少ない順'),
    'net': ('差枚の多い順', '差枚の少ない順'),
    'total': ('合計点の高い順', '合計点の低い順'),
}
HEADING_LABELS = {'rack': '台番', 'machine': '機種', 'games': '回転数', 'net': '推定差枚', 'total': '合計点'}
# P’s CUBEの店舗の選択肢の値（PC本体の「結果を見る」と同じ名前を app.py から渡す）。
PSCUBE_KEY = 'pscube'
SORT_ARROWS = {'回転数の多い順': ' ▼', '差枚の多い順': ' ▼', '合計点の高い順': ' ▼'}  # ほかは小さい順なので ▲


def setting_text(row):
    """設定候補の欄。手入力の設定情報があればそちら（Androidの表と同じ）。"""
    if row.get('confirmed_setting'):
        return f"設定情報 {row['confirmed_setting']}"
    estimate = row.get('setting_estimate')
    if not estimate:
        return '—'
    if len(estimate['range80']) == estimate['setting_count']:
        return '絞れず'
    return '・'.join(estimate['range80'])


def machine_list_rows(db_path, location, day):
    """その日・その店の、バラエティ以外の機種の台（台番順）。数値異常の台も入れる（数値は「異常」）。"""
    db = Store(db_path)
    try:
        counts = Counter(r['machine'] for r in db.rows(day, None, location))
        limit = rainbow_variety_max(location)
        rows = []
        for machine in sorted(m for m, n in counts.items() if n > limit):
            marks = {int(c['row']['rack']): '★' if c['focus'] else '☆'
                     for c in provisional_next_day_candidates(db, day, machine, location)['candidates']}
            for r in scored_rows(db, day, machine, location):
                bad = implausible_numbers(r)
                net, needs_check, _site = rack_net(r)
                rack = int(r['rack'])
                rows.append({'rack': rack, 'machine': machine, 'bad': bad,
                             'games': None if bad else r.get('games'), 'bb': r.get('bb'), 'rb': r.get('rb'),
                             'net': None if bad else net, 'needs_check': bool(needs_check),
                             'setting': setting_text(r), 'total': r['score']['total'],
                             'mark': marks.get(rack, ''), 'rainbow': r.get('rainbow') is True})
    finally:
        db.close()
    return sorted(rows, key=SORTS['台番順'])


def pscube_list_rows(db_path, day):
    """P’s CUBEのその日の台（台番順）。沖ドキなど表示しない機種は除く。数値異常（カレンダーと同じ基準）は「異常」。
    貸玉が複数ある日は、機種名の前に貸玉を付けて分ける（カレンダーの PscubeEvents.day_records と同じ）。"""
    import pscube_import
    store = pscube_import.PscubeStore(db_path, recording=False)
    try:
        records = [r for r in (json.loads(row[0]) for row in store.db.execute('SELECT payload FROM records'))
                   if r.get('day') == day and not pscube_import.is_excluded_machine(r['machine'])]
    finally:
        store.close()
    rates = {r['rate'] for r in records}
    rows = []
    for r in records:
        bad = ((r.get('games') or 0) > 20000 or (r.get('bb') or 0) > 500 or (r.get('rb') or 0) > 500
               or (r.get('my') or 0) > 100000)
        rows.append({'rack': int(r['rack']), 'machine': (f"{r['rate']}スロ " if len(rates) > 1 else '') + r['machine'],
                     'bad': bad, 'games': None if bad else r.get('games'), 'bb': r.get('bb'), 'rb': r.get('rb'),
                     'net': None if bad else r.get('net_medals'), 'needs_check': False, 'my': r.get('my'),
                     'setting': '—', 'total': None, 'mark': '', 'rainbow': False, 'pscube': True})
    return sorted(rows, key=SORTS['台番順'])


def _in_thread(work, done, widget):
    """重い読み込み（幸町は500台ほどで数秒）を別の糸で行い、終わったら画面の糸で done(結果) を呼ぶ。"""
    box = {}

    def run():
        try:
            box['rows'] = work()
        except Exception as error:  # 画面には出す（タブは使えるまま）
            box['error'] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    def poll():
        if thread.is_alive():
            widget.after(50, poll)
        else:
            done(box)
    widget.after(50, poll)


def _now(work, done, _widget):
    """試験用：その場で読む。"""
    try:
        done({'rows': work()})
    except Exception as error:
        done({'error': error})


def build_machine_list_tab(parent, db_path, on_marked, default_location=None, on_flush=None, pending=None,
                           defer_load=False, run=_in_thread, pscube=None):
    """「機種一覧」のタブの中身。🌈を押したときは記録への保存だけで on_marked() を呼ぶ（作り直しはバラエティ🌈と同じく
    まとめて on_flush。pending はボタンの文字）。pscube＝(P’s CUBEのDBのパス, 店舗の選択肢の名前)。表示を描き直す関数を返す（タブを開いたとき用）。"""
    ttk.Label(parent, text='機種一覧', style='H2.TLabel').pack(anchor='w')
    ttk.Label(parent, text='選んだ日の、バラエティ以外の機種の台です（バラエティはバラエティ🌈のタブ）。'
                           '機種を選ぶとその機種だけ。★注目・☆長期傾向＝翌日候補（仮）。点数・設定候補の意味は「結果を見る」と同じで、'
                           '出率・差枚・設定を表すものではありません。P’s CUBEは全機種で、PC版では採点しないため点数・設定候補・★☆は出ません。',
              style='Sub.TLabel', wraplength=900).pack(anchor='w', pady=(0, 10))
    bar = ttk.Frame(parent)
    bar.pack(fill='x')
    labels = list(STORE_NAMES.values()) + ([pscube[1]] if pscube else [])
    store_var = tk.StringVar(value=STORE_NAMES.get(default_location) or labels[0])
    day_var = tk.StringVar()
    machine_var = tk.StringVar(value=ALL_MACHINES)
    sort_var = tk.StringVar(value='台番順')
    combos = {}
    for column, (text, var, values, width) in enumerate((('店舗', store_var, labels, 28), ('日付', day_var, [], 16),
                                                         ('機種', machine_var, [ALL_MACHINES], 34),
                                                         ('並べ方', sort_var, list(SORTS), 18))):
        ttk.Label(bar, text=text).grid(row=0, column=column, sticky='w')
        combo = ttk.Combobox(bar, textvariable=var, values=values, state='readonly', width=width)
        combo.grid(row=1, column=column, sticky='w', padx=(0, 16))
        combos[text] = combo
    if on_flush is not None:
        ttk.Label(bar, text='閲覧・共有ページ').grid(row=0, column=4, sticky='w')
        ttk.Button(bar, textvariable=pending, command=on_flush).grid(row=1, column=4, sticky='w')
    summary = tk.StringVar()
    ttk.Label(parent, textvariable=summary).pack(anchor='w', pady=(10, 0))
    ttk.Label(parent, text=f'{RAINBOW_MARK}の列を押すと付け外し。台番・機種・回転数・推定差枚・合計点の見出しを押すと並べ替え'
                           '（数値はもう一度押すと多い順・少ない順を切り替え）。数値の無い台は最後。',
              style='Sub.TLabel').pack(anchor='w', pady=(0, 6))
    frame = ttk.Frame(parent)
    frame.pack(fill='both', expand=True)
    columns = ('mark', 'rack', 'machine', 'games', 'bb', 'rb', 'net', 'my', 'setting', 'total')
    table = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
    for key, label, width, anchor in (('mark', RAINBOW_MARK, 40, 'center'), ('rack', '台番', 70, 'e'),
                                      ('machine', '機種', 280, 'w'), ('games', '回転数', 76, 'e'),
                                      ('bb', 'BB', 44, 'e'), ('rb', 'RB', 44, 'e'), ('net', '推定差枚', 90, 'e'),
                                      ('my', 'MY', 70, 'e'), ('setting', '設定候補（BB/RB）', 130, 'center'), ('total', '合計点', 70, 'e')):
        table.heading(key, text=label)
        if key in HEADING_SORTS:
            table.heading(key, command=lambda key=key: heading_sort(key))
        table.column(key, width=width, anchor=anchor, stretch=key == 'machine')
    table.tag_configure('plus', foreground=PLUS_COLOR)
    table.tag_configure('minus', foreground=MINUS_COLOR)
    table.tag_configure('rainbow', background=RAINBOW_BG)
    scroll = ttk.Scrollbar(frame, orient='vertical', command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    table.pack(side='left', fill='both', expand=True)
    scroll.pack(side='left', fill='y')
    state = {'rows': [], 'shown': [], 'token': 0}
    parent.machine_list_table = table   # 試験用
    parent.machine_list_vars = {'store': store_var, 'day': day_var, 'machine': machine_var, 'sort': sort_var}

    def heading_sort(key):
        options = HEADING_SORTS[key]
        current = sort_var.get()
        sort_var.set(options[(options.index(current) + 1) % len(options)] if current in options else options[0])

    def location():
        if pscube and store_var.get() == pscube[1]:
            return PSCUBE_KEY
        return next((key for key, label in STORE_NAMES.items() if label == store_var.get()), None)

    def values(r):
        if r['bad']:
            numbers = ('異常', '—', '—', '—', '—')
        else:
            dash = lambda value: '—' if value is None else value
            net = '—' if r['net'] is None else signed_medals(r['net']) + ('※' if r['needs_check'] else '')
            my = '—' if r.get('my') is None else f"{r['my']:,}"
            numbers = (f"{r['games']:,}", dash(r['bb']), dash(r['rb']), net, my)
        return ('—' if r.get('pscube') else rainbow_cell(r), f"{r['rack']}{' ' + r['mark'] if r['mark'] else ''}",
                r['machine'], *numbers, r['setting'], '—' if r['total'] is None else f"{r['total']:.1f}")

    def tags(r):
        net = r['net'] or 0
        return ('plus' if net > 0 else 'minus' if net < 0 else 'zero',) + (('rainbow',) if r['rainbow'] else ())

    def show():
        chosen = machine_var.get()
        rows = [r for r in state['rows'] if chosen == ALL_MACHINES or r['machine'] == chosen]
        rows.sort(key=SORTS[sort_var.get()])
        state['shown'] = rows
        is_pscube = location() == PSCUBE_KEY
        # MYはP’s CUBEだけ（メルヘンの一覧はバラエティ🌈と同じ列のまま）。
        table['displaycolumns'] = [c for c in columns if c != 'my' or is_pscube]
        for key, label in HEADING_LABELS.items():
            if key == 'net' and is_pscube:
                label = '差枚'   # 元グラフの確定差枚
            picked = sort_var.get() in HEADING_SORTS[key]
            table.heading(key, text=label + (SORT_ARROWS.get(sort_var.get(), ' ▲') if picked else ''))
        totals = [r['total'] for r in rows if r['total'] is not None]
        machines = len({r['machine'] for r in rows})
        if state.get('error'):
            summary.set(f"読み込めませんでした：{state['error']}")
        elif state.get('loading'):
            summary.set('読み込んでいます…')
        elif rows:
            name = f'{machines}機種' if chosen == ALL_MACHINES else chosen
            average = f'・平均 {sum(totals) / len(totals):.1f}点' if totals else ''
            focus = sum(r['mark'] == '★' for r in rows)
            summary.set(f'{name}・{len(rows)}台{average}' + (f'・★注目{focus}台' if focus else ''))
        elif state['rows']:
            summary.set('この日は選んだ機種の記録がありません。')
        else:
            summary.set('この日はバラエティ以外の機種の記録がありません。')
        table.delete(*table.get_children())
        for i, r in enumerate(rows):
            table.insert('', 'end', iid=str(i), values=values(r), tags=tags(r))

    def load(*_args):
        where, day = location(), day_var.get()
        state['token'] += 1
        token = state['token']
        state.update(rows=[], error=None, loading=bool(where and day))
        show()
        if not state['loading']:
            return

        def done(box):
            if token != state['token']:
                return   # 読み込み中に店舗・日付が変わった
            state.update(rows=box.get('rows', []), error=box.get('error'), loading=False)
            names = sorted({r['machine'] for r in state['rows']})
            combos['機種']['values'] = [ALL_MACHINES, *names]
            if machine_var.get() not in names and machine_var.get() != ALL_MACHINES:
                machine_var.set(ALL_MACHINES)   # 選んでいた機種がこの日に無い（machine_var の変更で show も呼ばれる）
            show()
        if where == PSCUBE_KEY:
            run(lambda: pscube_list_rows(pscube[0], day), done, parent)
        else:
            run(lambda: machine_list_rows(db_path, where, day), done, parent)

    def refresh_days(*_args):
        where = location()
        if where == PSCUBE_KEY:
            import pscube_import
            store = pscube_import.PscubeStore(pscube[0], recording=False)
            try:
                days = store.days()
            finally:
                store.close()
        else:
            db = Store(db_path)
            try:
                days = db.days_for(where) if where else []
            finally:
                db.close()
        combos['日付']['values'] = days
        chosen = day_var.get() if day_var.get() in days else (days[0] if days else '')
        if chosen != day_var.get():
            day_var.set(chosen)   # 日付が変わると load が呼ばれる
        else:
            load()

    def toggle(event):
        # 🌈の列（いちばん左）を押したときだけ付け外しする。ほかの列は行を選ぶだけ。
        if table.identify_region(event.x, event.y) != 'cell' or table.identify_column(event.x) != '#1':
            return None
        iid = table.identify_row(event.y)
        if not iid:
            return None
        row = state['shown'][int(iid)]
        if row.get('pscube'):
            return 'break'   # P’s CUBEには🌈の印を付けない
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
        table.item(iid, values=values(row), tags=tags(row))
        on_marked()
        return 'break'

    table.bind('<Button-1>', toggle)
    store_var.trace_add('write', refresh_days)
    day_var.trace_add('write', load)
    machine_var.trace_add('write', lambda *_a: show())
    sort_var.trace_add('write', lambda *_a: show())
    if not defer_load:
        refresh_days()
    return refresh_days
