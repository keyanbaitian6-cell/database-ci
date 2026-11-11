"""PC既存画面から日次学習の保存済み候補を表示する。"""
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
from tkinter import ttk
import tkinter as tk

from daily_learning import JST
from daily_learning_runtime import run, FILE_NAME
from daily_learning_view import (LOAD_ERROR, METHOD_TEXT, NAMES, daily_view, date_label, default_target,  # noqa: F401
                                 status_parts, time_label)


class DailyLearningWorker:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.thread = None
        self.results = queue.Queue()

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return False
        def work():
            try:
                result = run(self.data_dir)
                self.results.put(result['status'])
            except Exception as error:
                import error_log
                error_log.note(self.data_dir, 'daily-learning', f'{type(error).__name__}: {error}')
                self.results.put('日次学習で処理失敗。従来候補を利用できます。日次学習画面を確認してください。')
        self.thread = threading.Thread(target=work, name='daily-learning', daemon=True)
        self.thread.start()
        return True


def show(root, data_dir, *, clock=None):
    """PCの「日次学習・採用中の候補」。4画面と同じ順：切り替え → 重要な注意 → 候補数 → 機種ごとの候補 → 開閉式の説明。"""
    clock = clock or (lambda: datetime.now(JST))
    window = tk.Toplevel(root)
    window.title('日次学習・採用中の候補')
    window.geometry('820x720')
    ink, muted, line = '#1d1d1f', '#707070', '#d6d6d6'
    base = 'Yu Gothic UI'
    top = ttk.Frame(window, padding=(16, 12, 16, 6))
    top.pack(fill='x')
    ttk.Label(top, text='店舗').grid(row=0, column=0, sticky='w')
    ttk.Label(top, text='対象日').grid(row=0, column=1, sticky='w', padx=(12, 0))
    store_box = ttk.Combobox(top, state='readonly', values=list(NAMES.values()), width=14,
                             font=(base, 12))
    store_box.grid(row=1, column=0, sticky='w')
    day_box = ttk.Combobox(top, state='readonly', width=22, font=(base, 12))
    day_box.grid(row=1, column=1, sticky='w', padx=(12, 0))
    reload_button = ttk.Button(top, text='保存済み結果を再表示')
    reload_button.grid(row=1, column=2, sticky='e', padx=(12, 0))
    top.columnconfigure(2, weight=1)
    canvas = tk.Canvas(window, highlightthickness=0, background='#ffffff')
    scroll = ttk.Scrollbar(window, command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    canvas.pack(fill='both', expand=True)
    body = tk.Frame(canvas, background='#ffffff')
    item = canvas.create_window((0, 0), window=body, anchor='nw')
    body.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: (canvas.itemconfigure(item, width=e.width), relayout()))
    window.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-1 * (e.delta // 120), 'units'))
    state = {'doc': None, 'store': 'nagamachiminami', 'target': None, 'dates': [], 'wraps': []}

    def label(parent, text, size=11, color=ink, bold=False, bg='#ffffff', wrap=True, **pack):
        widget = tk.Label(parent, text=text, font=(base, size, 'bold' if bold else 'normal'), fg=color, bg=bg,
                          justify='left', anchor='w')
        if wrap:
            state['wraps'].append(widget)
        widget.pack(fill='x', anchor='w', **pack)
        return widget

    def more(parent, title, lines, bg='#ffffff', padx=0):
        """開閉式の説明。最初は閉じている。"""
        holder = tk.Frame(parent, background=bg)
        holder.pack(fill='x', anchor='w', pady=(6, 2), padx=padx)
        inner = tk.Frame(holder, background=bg)
        button = tk.Button(holder, text='▶ ' + title, relief='flat', bd=0, fg='#0066cc', bg=bg,
                           activebackground=bg, activeforeground='#0066cc', font=(base, 10), cursor='hand2', anchor='w')
        def toggle():
            if inner.winfo_ismapped():
                inner.pack_forget()
                button.configure(text='▶ ' + title)
            else:
                inner.pack(fill='x', anchor='w', padx=(18, 0))
                button.configure(text='▼ ' + title)
            relayout()
        button.configure(command=toggle)
        button.pack(anchor='w')
        for text in lines:
            label(inner, text, 10, muted, bg=bg, pady=(0, 2))

    def relayout():
        width = max(canvas.winfo_width() - 72, 200)
        for widget in state['wraps']:
            if widget.winfo_exists():
                widget.configure(wraplength=width)

    def render():
        for child in body.winfo_children():
            child.destroy()
        state['wraps'] = []
        try:
            doc = state['doc']
            if doc is None:
                raise ValueError('未読込')
            view = daily_view(doc, state['store'], state['target'], clock())
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            box = tk.Frame(body, background='#fff8e8', highlightbackground='#b37413', highlightthickness=1)
            box.pack(fill='x', padx=16, pady=12)
            label(box, LOAD_ERROR, bg='#fff8e8', padx=12, pady=10)
            relayout()
            return
        state['dates'] = view['dates']
        day_box.configure(values=[date_label(d) + ('・過去日' if d < view['initial'] else '') for d in view['dates']])
        day_box.current(view['dates'].index(state['target']))
        store_box.current(list(NAMES).index(state['store']))
        if view['alerts']:
            box = tk.Frame(body, background='#fff8e8', highlightbackground='#b37413', highlightthickness=1)
            box.pack(fill='x', padx=16, pady=(8, 4))
            for text in view['alerts']:
                label(box, text, bg='#fff8e8', padx=12, pady=(6, 6))
        summary = tk.Frame(body, background='#ffffff')
        summary.pack(fill='x', padx=16, pady=(10, 0))
        tk.Label(summary, text=f"{view['count']}台" if view['count'] else '候補なし', font=(base, 22, 'bold'),
                 fg=ink, bg='#ffffff').pack(side='left')
        context = f"{NAMES[state['store']]}・{date_label(state['target'])}"
        if view['count']:
            context += f"・{view['scope']}の保存済み候補"
        tk.Label(summary, text=context, font=(base, 11), fg=ink, bg='#ffffff').pack(side='left', padx=(10, 0), pady=(8, 0))
        label(body, f"最終処理 {time_label(view['updated'])}（日本時間）", 10, muted, padx=16, pady=(0, 8))
        for group in view['groups']:
            card = tk.Frame(body, background='#ffffff', highlightbackground=line, highlightthickness=1)
            card.pack(fill='x', padx=16, pady=6)
            pad = tk.Frame(card, background='#ffffff')
            pad.pack(fill='x', padx=14, pady=(10, 6))
            label(pad, group['name'], 13, ink, True)
            head = tk.Frame(pad, background='#ffffff')
            head.pack(fill='x', pady=(4, 6))
            learned = group['learned']
            tk.Label(head, text='採用中 ' + ('日次学習版' if learned else '従来方式'),
                     font=(base, 10, 'bold' if learned else 'normal'), fg='#0066cc' if learned else ink,
                     bg='#e8f1fd' if learned else '#e6e6e8', padx=10, pady=2).pack(side='left')
            tk.Label(head, text=f"{len(group['racks'])}台", font=(base, 10), fg=muted, bg='#ffffff').pack(side='right')
            racks = tk.Frame(pad, background='#ffffff')
            racks.pack(fill='x', anchor='w')
            columns = 6
            for index, (rack, machine) in enumerate(group['racks']):
                chip = tk.Frame(racks, background='#f2f2f4', padx=10, pady=4)
                chip.grid(row=index // columns, column=index % columns, sticky='nw', padx=(0, 8), pady=(0, 8))
                number = tk.Frame(chip, background='#f2f2f4')
                number.pack(anchor='w')
                tk.Label(number, text=str(rack), font=(base, 20, 'bold'), fg=ink, bg='#f2f2f4').pack(side='left')
                tk.Label(number, text='番', font=(base, 10), fg=muted, bg='#f2f2f4').pack(side='left', anchor='s', pady=(0, 4))
                if machine:
                    tk.Label(chip, text=machine, font=(base, 9), fg=muted, bg='#f2f2f4', wraplength=110,
                             justify='left').pack(anchor='w')
            more(pad, '採用方式の説明・保存時刻',
                 [group['status'], METHOD_TEXT[learned], f"保存 {time_label(group['saved'])}（日本時間）"])
        name = NAMES[state['store']]
        more(body, '処理状況・日次学習について',
             [f'{name}：{s}' for s in view['mine']] + view['general'] +
             ([] if view['mine'] or view['general'] else ['処理状況の記録はありません。']) +
             ['PCで前日23:30〜当日8:00の間に保存した候補を表示します。画面を開いても予測を作り直しません。',
              '採用は店舗ごとに、保存した予測の将来の成績で判定します。判定までは従来方式を採用します。'], padx=16)
        wrapper = tk.Frame(body, background='#ffffff')
        wrapper.pack(fill='x', padx=16, pady=(4, 16))
        label(wrapper, '毎日学習しても、毎日の改善を保証しません。設定確率・勝率・期待収支を示すものではありません。', 10, muted)
        relayout()
        canvas.yview_moveto(0)

    def load():
        try:
            state['doc'] = json.loads((Path(data_dir) / FILE_NAME).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state['doc'] = None
        state['target'] = state['target'] or default_target(clock())
        render()

    def on_store(_event=None):
        state['store'] = list(NAMES)[store_box.current()]
        render()

    def on_day(_event=None):
        state['target'] = state['dates'][day_box.current()]
        render()

    store_box.bind('<<ComboboxSelected>>', on_store)
    day_box.bind('<<ComboboxSelected>>', on_day)
    reload_button.configure(command=load)
    load()
    return window
