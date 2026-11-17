"""PCの「店の入れ方のふり返り」（2026-11-18 利用者「今日追加した店の入れ方の振り返りなんだけど、PCでも表示させてほしい」）。

閲覧ページの同じ画面（database_android/lib/store_pattern_page.dart）と同じ順：その日のまとめ → 全台系（機種ごと）
→ 末尾 → 並び → 日ごとの履歴。計算は store_pattern.py（閲覧ページと同じ数字）。PCは保存している日が多いので、
履歴は閲覧ページより長く見られる。保存済みのデータを読むだけ（書き込まない・サイトへアクセスしない）。
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tkinter as tk
from tkinter import ttk

import core
import store_pattern as sp

PSCUBE = 'pscube:c740601:20'
STORES = {'nagamachiminami': '長町南', 'saiwaichou': '幸町', PSCUBE: 'P-STATION'}
WEEK = '月火水木金土日'
NOTE = ('プラスで終わった台（勝率と同じ数え方）が、機種・末尾・台番の並びに、ランダムに配ったときより偏っていたかを見ます。'
        '「偶然では出にくい」は、何通りも比べた中の一番であることを割り引いても5%未満、「ときどき出る」は20%未満です。'
        '500G以下の台と、プラスかどうか分からない台は除きます。分かる台が稼働した台の7割に届かない日（アナスロで補った日など）は判定しません。'
        '台番が1つずつ続く台を隣とみなします（島の切れ目・角は台番からは分からないので見ていません）。\n'
        '探索の結果です。翌日候補・採点には使っていません。候補に使うなら、先に確かめ方を決めて前向きに確かめてから。'
        '設定そのものではなく、差枚のプラス・マイナスで見ています。')


def day_label(day):
    from datetime import date
    d = date.fromisoformat(day)
    return f'{d.month}/{d.day}（{WEEK[d.weekday()]}）'


def _read_only(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)


class Source:
    """店ごとの記録とイベント名（読むだけ）。"""

    def __init__(self, data_dir, store):
        self.data_dir, self.store = Path(data_dir), store
        self.by_day, self.events = {}, {}
        if store == PSCUBE:
            self._load_pscube()
        else:
            self._load_meruhen()
        self.days = sorted(self.by_day, reverse=True)

    def _load_meruhen(self):
        db = _read_only(self.data_dir / 'database.sqlite3')
        try:
            for machine, payload in db.execute('SELECT machine, payload FROM days WHERE store=? ORDER BY day, rack',
                                               (self.store,)):
                if core.is_hidden_machine(self.store, machine):
                    continue
                try:
                    row = json.loads(payload)
                except ValueError:
                    continue
                self.by_day.setdefault(row['day'], []).append(row)
            raw = db.execute("SELECT value FROM app_state WHERE state_key='date_events'").fetchone()
        finally:
            db.close()
        events = json.loads(raw[0]) if raw else []
        for e in sorted((e for e in events if isinstance(e, dict) and e.get('store') == self.store),
                        key=lambda e: str(e.get('updated_at', ''))):
            self.events[e.get('day')] = e.get('name')

    def _load_pscube(self):
        _, shop, rate = self.store.split(':')
        db = _read_only(self.data_dir / 'pscube.sqlite3')
        try:
            rows = db.execute('SELECT payload FROM records ORDER BY rowid').fetchall()
            raw = db.execute("SELECT value FROM state WHERE key='date_events'").fetchone()
        finally:
            db.close()
        for (payload,) in rows:
            try:
                row = json.loads(payload)
            except ValueError:
                continue
            if row.get('store') == shop and str(row.get('rate')) == rate:
                self.by_day.setdefault(row['day'], []).append(dict(row, store=self.store))
        events = json.loads(raw[0]) if raw else []
        for e in sorted((e for e in events if isinstance(e, dict) and e.get('store') == shop and str(e.get('rate')) == rate),
                        key=lambda e: str(e.get('updated_at', ''))):
            self.events[e.get('day')] = e.get('name')

    def won(self, row):
        return sp.pscube_won(row) if self.store == PSCUBE else core.rack_won(row)

    def report(self, day):
        return sp.store_pattern_day(self.store, day, self.by_day.get(day, []), self.won)


def show(root, data_dir):
    window = tk.Toplevel(root)
    window.title('店の入れ方のふり返り')
    window.geometry('860x760')
    ink, muted, line, red, amber = '#1d1d1f', '#707070', '#d6d6d6', '#b3261e', '#9a6700'
    base = 'Yu Gothic UI'
    top = ttk.Frame(window, padding=(16, 12, 16, 6))
    top.pack(fill='x')
    ttk.Label(top, text='店舗').grid(row=0, column=0, sticky='w')
    ttk.Label(top, text='日付').grid(row=0, column=1, sticky='w', padx=(12, 0))
    store_box = ttk.Combobox(top, state='readonly', values=list(STORES.values()), width=12, font=(base, 12))
    store_box.grid(row=1, column=0, sticky='w')
    day_box = ttk.Combobox(top, state='readonly', width=28, font=(base, 12))
    day_box.grid(row=1, column=1, sticky='w', padx=(12, 0))
    events_only = tk.BooleanVar(value=False)
    ttk.Checkbutton(top, text='履歴はイベントの日だけ', variable=events_only,
                    command=lambda: render_history()).grid(row=1, column=2, sticky='w', padx=(12, 0))
    body_canvas = tk.Canvas(window, highlightthickness=0, background='#ffffff')
    scroll = ttk.Scrollbar(window, command=body_canvas.yview)
    body_canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    body_canvas.pack(fill='both', expand=True)
    body = tk.Frame(body_canvas, background='#ffffff')
    item = body_canvas.create_window((0, 0), window=body, anchor='nw')
    body.bind('<Configure>', lambda _e: body_canvas.configure(scrollregion=body_canvas.bbox('all')))
    body_canvas.bind('<Configure>', lambda e: body_canvas.itemconfigure(item, width=e.width))
    window.bind('<MouseWheel>', lambda e: body_canvas.yview_scroll(-1 * (e.delta // 120), 'units'))
    state = {'source': None, 'day': None, 'cache': {}, 'history_frame': None, 'job': None, 'done': 0}

    def label(parent, text, size=11, color=ink, bold=False, **pack):
        widget = tk.Label(parent, text=text, font=(base, size, 'bold' if bold else 'normal'), fg=color, bg='#ffffff',
                          justify='left', anchor='w', wraplength=780)
        widget.pack(fill='x', anchor='w', **pack)
        return widget

    def card(title):
        frame = tk.Frame(body, background='#ffffff', highlightbackground=line, highlightthickness=1)
        frame.pack(fill='x', padx=16, pady=6)
        pad = tk.Frame(frame, background='#ffffff')
        pad.pack(fill='x', padx=14, pady=(10, 8))
        label(pad, title, 13, ink, True, pady=(0, 4))
        return pad

    def chance_color(chance):
        return red if chance == sp.RARE else amber if chance == sp.SOMETIMES else muted

    def detail(p):
        return '0.1%未満' if p < .001 else f'約{p * 100:.{1 if p < .1 else 0}f}%'

    def report(day):
        cache = state['cache']
        if day not in cache:
            cache[day] = state['source'].report(day)
        return cache[day]

    def group_rows(pad, groups, rate):
        for g in groups:
            row = tk.Frame(pad, background='#ffffff')
            row.pack(fill='x', pady=3)
            share = g['plus'] / g['total']
            tk.Label(row, text=sp.fold_half_width_kana(g['label']), font=(base, 11, 'bold'), fg=ink, bg='#ffffff',
                     anchor='w', width=30).pack(side='left')
            tk.Label(row, text=f"プラス {g['plus']}/{g['total']}台（{round(share * 100)}%）", font=(base, 11), fg=ink,
                     bg='#ffffff', width=20, anchor='w').pack(side='left')
            if share > rate:
                tk.Label(row, text=g['chance'], font=(base, 10, 'bold'), fg=chance_color(g['chance']),
                         bg='#ffffff').pack(side='left')
                label(pad, f"ランダムに配ってこれ以上になる確率 {detail(g['p'])}・{g['compared']}通り比べた分を割り引くと "
                           f"{detail(g['adjusted'])}", 9, muted, pady=(0, 2))
            else:
                tk.Label(row, text='店全体より多くない', font=(base, 10), fg=muted, bg='#ffffff').pack(side='left')

    def render():
        for child in body.winfo_children():
            child.destroy()
        source, day = state['source'], state['day']
        if source is None or day is None:
            label(body, 'この店の記録がありません。', 12, muted, padx=16, pady=16)
            return
        r = report(day)
        pad = card(f"{STORES[source.store]}　{day_label(day)}")
        if source.events.get(day):
            label(pad, f"イベント：{source.events[day]}")
        label(pad, '判定に使える台がありません' if not r['total'] else
              f"判定に使った台 {r['total']}台・プラス {r['plus']}台（{round(r['plus'] / r['total'] * 100)}%）", 12, ink, True)
        label(pad, f"500G以下の台と、プラスかどうか分からない台（{r['excluded']}台）は除いています。", 9, muted)
        if r['total'] and not r['usable']:
            why = ('台が少ない（10台未満）' if r['total'] < sp.MIN_RACKS else
                   'プラスかどうか分かる台が、稼働した台の7割に届かない（アナスロで補った日など）'
                   if r['total'] < sp.KNOWN_SHARE * r['played'] else '全部プラス、または全部マイナス')
            label(pad, f'{why}ので、偏りは判定しません。', 10, muted, pady=(4, 0))
        if r['usable']:
            rate = r['plus'] / r['total']
            pad = card('全台系（機種ごと）')
            shown = r['machines'][:8]
            if shown:
                group_rows(pad, shown, rate)
                if len(r['machines']) > len(shown):
                    label(pad, f"ほか{len(r['machines']) - len(shown)}機種は偏りが小さいので省略。", 9, muted)
            else:
                label(pad, '3台以上ある機種がありません。', 10, muted)
            pad = card('末尾')
            group_rows(pad, r['suffixes'], rate) if r['suffixes'] else label(pad, '3台以上ある末尾がありません。', 10, muted)
            pad = card('並び（台番が続いてプラス）')
            run = r['run']
            if run:
                label(pad, f"いちばん長い並び：{sp.run_label(run)}（{len(run['racks'])}台）", 11, ink, True)
                label(pad, f"{run['chance']}（プラスの印をランダムに配り直して、これ以上長く続く割合 {detail(run['p'])}）", 10,
                      chance_color(run['chance']))
            else:
                label(pad, 'プラスの台がありません。', 10, muted)
        state['history_frame'] = card('日ごとの履歴（押すとその日へ）')
        render_history()
        label(body, NOTE, 9, muted, padx=16, pady=(8, 16))
        body_canvas.yview_moveto(0)

    def render_history():
        frame = state['history_frame']
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children()[1:]:
            child.destroy()
        source = state['source']
        days = [d for d in source.days if not events_only.get() or source.events.get(d)]
        done = [d for d in days if d in state['cache']]
        if len(done) < len(days):
            label(frame, f"計算中（{len(state['cache'])}/{len(source.days)}日）", 9, muted)
        for d in done:
            r = state['cache'][d]
            title = day_label(d) + (f"　{source.events[d]}" if source.events.get(d) else '')
            text = ('判定しない日' if not r['usable'] else
                    '　'.join(r['highlights']) if r['highlights'] else f"目立つ偏りなし（プラス {round(r['plus'] / r['total'] * 100)}%）")
            row = tk.Frame(frame, background='#eef4fd' if d == state['day'] else '#ffffff', cursor='hand2')
            row.pack(fill='x', pady=1)
            for widget in (tk.Label(row, text=title, font=(base, 10, 'bold'), fg=ink, bg=row['background'], anchor='w',
                                    width=26),
                           tk.Label(row, text=text, font=(base, 10), fg=red if r['highlights'] else muted,
                                    bg=row['background'], anchor='w', justify='left', wraplength=520)):
                widget.pack(side='left', fill='x')
                widget.bind('<Button-1>', lambda _e, d=d: choose_day(d))
            row.bind('<Button-1>', lambda _e, d=d: choose_day(d))

    def step_history():
        """履歴は少しずつ計算する（並びの並べ替えで窓が固まらないように）。"""
        state['job'] = None
        source = state['source']
        if source is None or not window.winfo_exists():
            return
        rest = [d for d in source.days if d not in state['cache']]
        for d in rest[:1]:
            report(d)
        render_history()
        if rest[1:]:
            state['job'] = window.after(10, step_history)

    def choose_day(day):
        state['day'] = day
        day_box.current(state['source'].days.index(day))
        render()

    def choose_store(_event=None):
        store = list(STORES)[store_box.current()]
        if state['job']:
            window.after_cancel(state['job'])
            state['job'] = None
        state['source'] = Source(data_dir, store)
        state['cache'] = {}
        days = state['source'].days
        day_box.configure(values=[day_label(d) + (f"　{state['source'].events[d]}" if state['source'].events.get(d) else '')
                                  for d in days])
        state['day'] = days[0] if days else None
        if days:
            day_box.current(0)
        render()
        state['job'] = window.after(50, step_history)

    store_box.bind('<<ComboboxSelected>>', choose_store)
    day_box.bind('<<ComboboxSelected>>', lambda _e: choose_day(state['source'].days[day_box.current()]))
    window.protocol('WM_DELETE_WINDOW', lambda: (state['job'] and window.after_cancel(state['job']), window.destroy()))
    store_box.current(0)
    choose_store()
    return window
