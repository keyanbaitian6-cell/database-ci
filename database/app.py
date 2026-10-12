from datetime import date, datetime
from pathlib import Path
import base64
import math
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import tkinter.font as tkfont
import pscube_import
from event_calendar import PscubeEvents, open_event_calendar
from variety_rainbow import build_variety_tab

from core import (CONFIRMED_SETTING_OPTIONS, DATE_EVENT_OPTIONS, STORE_NAMES, Store, auto_backup, delete_records, export_backup, history_report, import_backup,
                  latest_backup_file, list_snapshots, load_settings, report, restore_backup, save_settings,
                  summary_report, undo_last_save, pull_shared_events, pull_shared_rainbow)

def runtime_root():
    """Keep user data beside the project when running a packaged Windows app."""
    if getattr(sys, 'frozen', False):
        executable_dir = Path(sys.executable).resolve().parent
        for candidate in (executable_dir.parent, executable_dir.parent.parent, executable_dir):
            if (candidate / 'data').exists() or (candidate / 'app.py').exists():
                return candidate
        return executable_dir
    return Path(__file__).parent


ROOT = runtime_root()
DATA_DIR = ROOT / 'data'
MACHINE_DEFAULT = ''
ALL_DAYS_LABEL = 'すべての日付'
ALL_STORES_LABEL = 'すべての店舗'
# P’s CUBE（専用の記録）を、メルヘンの2店舗と並べて選べるようにする（利用者の指示、2026-10-02）。
PSCUBE_KEY = 'pscube'
PSCUBE_LABEL = 'P’s CUBE（スロット）'
PSCUBE_VIEWER_URL = 'https://keyanbaitian6-cell.github.io/database-viewer/pscube/'
# Kept only for the Chrome-extension filename format they still describe;
# no PC-side UI decodes these anymore (see AI_COLLABORATION.md).
GRAPH_DOWNLOAD_RE = re.compile(
    r'database-graph-rack-(\d+)-(\d{4}-\d{2}-\d{2})(?:~s(nagamachiminami|saiwaichou))?(?:~m([A-Za-z0-9_-]+)~)?-.+\.png')
LIST_DOWNLOAD_RE = re.compile(
    r'database-list-(\d{4}-\d{2}-\d{2})(?:~s(nagamachiminami|saiwaichou))?(?:~m([A-Za-z0-9_-]+)~)?-.+\.png')


def decode_machine_token(token):
    if not token:
        return None
    try:
        padding = '=' * (-len(token) % 4)
        name = base64.urlsafe_b64decode(token + padding).decode('utf-8').strip()
    except (ValueError, UnicodeDecodeError):
        return None
    return name or None


class BackupConflictsDialog(tk.Toplevel):
    """List records whose numbers differ from what is already saved.

    Nothing here is applied automatically -- the import already wrote the
    safe (new/graph-only) records. Each conflict needs an explicit decision
    from the user before this dialog will overwrite anything.
    """

    def __init__(self, parent, conflicts):
        super().__init__(parent)
        self.title('バックアップの不一致を確認')
        self.geometry('860x620')
        self.transient(parent)
        self.grab_set()
        self.selected = []
        ttk.Label(self, text='数値または設定情報が一致しない記録があります。日付ごとにまとめて表示しています。'
                              '取り込んだ内容を使う場合だけチェックしてください。',
                  font=('Yu Gothic UI', 13, 'bold'), wraplength=820).pack(anchor='w', padx=16, pady=(14, 8))

        wrapper = ttk.Frame(self)
        wrapper.pack(fill='both', expand=True, padx=16)
        canvas = tk.Canvas(wrapper, highlightthickness=0)
        bar = ttk.Scrollbar(wrapper, orient='vertical', command=canvas.yview)
        grid = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=grid, anchor='nw')
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        grid.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))

        fields = (('games', '総回転数'), ('bb', 'BB'), ('rb', 'RB'), ('max_hold', '最大持玉'),
                  ('confirmed_setting', '設定情報'))
        groups = {}
        order = []
        for local, incoming in conflicts:
            key = (local['store'], local['day'])
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((local, incoming))
        order.sort(key=lambda key: key[1], reverse=True)

        self.checks = []
        for row_index, key in enumerate(order):
            store_key, day = key
            items = sorted(groups[key], key=lambda pair: (pair[0]['machine'], int(pair[0]['rack'])))
            card = ttk.LabelFrame(
                grid, padding=8,
                text=f'{STORE_NAMES.get(store_key, store_key)}｜{day}｜{len(items)}台が不一致')
            card.grid(row=row_index, column=0, sticky='ew', pady=4)
            grid.columnconfigure(0, weight=1)

            group_vars = []
            all_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                card, text='この日をまとめて上書きする', variable=all_var,
                command=lambda vars_=group_vars, all_var=all_var: [v.set(all_var.get()) for v in vars_],
            ).pack(anchor='w', pady=(0, 4))

            for local, incoming in items:
                diff = ', '.join(f'{label} {local.get(field)}→{incoming.get(field)}'
                                  for field, label in fields
                                  if local.get(field) != incoming.get(field))
                var = tk.BooleanVar(value=False)
                group_vars.append(var)
                ttk.Checkbutton(
                    card, text=f'{local["machine"]}｜{local["rack"]}番台：{diff}', variable=var,
                ).pack(anchor='w')
                self.checks.append((var, incoming))

        buttons = ttk.Frame(self)
        buttons.pack(fill='x', padx=16, pady=12)
        ttk.Button(buttons, text='閉じる（何も上書きしない）', command=self.destroy).pack(side='right')
        ttk.Button(buttons, text='チェックした内容で上書きして保存', command=self.accept).pack(side='right', padx=8)

    def accept(self):
        self.selected = [incoming for var, incoming in self.checks if var.get()]
        self.destroy()


# PC本体の見た目（2026-10-04、利用者が渡した Flip7 Design System を参考に。結果のHTML＝core.FLIP7_CSS と同じ配色）。
# ティール・コーラル・ゴールド・クリーム、ティールの淡い背景。並び・文言・働きは変えない。
F7 = dict(page='#EFF8F7', card='#FFFFFF', ink='#1E3B3A', mute='#5D7472', line='#CFE9E6',
          teal='#2BA8A2', teal_l='#3CC4BD', teal_d='#1E8C86', teal_bg='#E8F6F5', tab='#D6EEEC',
          gold='#FFD23F', gold_l='#FFE47A', gold_d='#E6B800', coral='#EF6C4A', coral_l='#FF8A6A',
          coral_d='#D45233', cream='#FFF8E7', sky='#5DADE2')


def _mix(a, b, t):
    a, b = int(a[1:], 16), int(b[1:], 16)
    return '#' + ''.join(f'{round(((a >> s) & 255) * (1 - t) + ((b >> s) & 255) * t):02x}' for s in (16, 8, 0))


class GradientButton(tk.Canvas):
    """利用者指定のボタンデザイン（CSSの .btn-grad）をTkで再現したもの。

    背景は #16A085 → #F4D03F（51%）→ #16A085 の横グラデーションを幅200%で敷き、
    マウスを乗せると0.5秒かけて右端（background-position: right center）へ流す。
    角丸10・文字は白・余白は上下15／左右45。影（0 0 20px #eee）は淡い背景では
    ほぼ見えないため省いた。キーボードでもフォーカスして Enter／Space で押せる。
    """
    STOPS = ((0.0, '#1E8C86'), (0.51, '#FFD23F'), (1.0, '#1E8C86'))   # 2026-10-04：Flip7のティールとゴールド

    def __init__(self, parent, text, command, font=('Yu Gothic UI', 12, 'bold'), padx=45, pady=15,
                 radius=None, background=F7['page']):
        measure = tkfont.Font(root=parent, font=font)
        width = measure.measure(text) + 2 * padx
        height = measure.metrics('linespace') + 2 * pady
        radius = height // 2 if radius is None else radius   # 丸い両端（ピル形）
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, background=background,
                         cursor='hand2', takefocus=1)
        self.command, self.width, self._offset, self._job = command, width, 0.0, None
        span = 2 * width
        row = []
        for x in range(span):
            at = x / (span - 1)
            for (s0, c0), (s1, c1) in zip(self.STOPS, self.STOPS[1:]):
                if at <= s1:
                    row.append(_mix(c0, c1, (at - s0) / (s1 - s0)))
                    break
        self._image = tk.PhotoImage(master=self, width=span, height=height)
        self._image.put(' '.join(['{' + ' '.join(row) + '}'] * height))
        self._picture = self.create_image(0, 0, image=self._image, anchor='nw')
        # 角丸：四隅の円の外側だけを背景色で塗りつぶす。
        steps = 16
        for cx, cy, sx, sy in ((radius, radius, -1, -1), (width - radius, radius, 1, -1),
                               (radius, height - radius, -1, 1), (width - radius, height - radius, 1, 1)):
            arc = [(cx + sx * radius * math.cos(math.pi / 2 * i / steps),
                    cy + sy * radius * math.sin(math.pi / 2 * i / steps)) for i in range(steps + 1)]
            corner = (cx + sx * radius, cy + sy * radius)
            self.create_polygon(*[v for point in (*arc, corner) for v in point], fill=background, outline=background)
        self.create_text(width / 2, height / 2, text=text, fill='#ffffff', font=font)
        self._focus = self.create_rectangle(3, 3, width - 4, height - 4, outline='', dash=(2, 2))
        self.bind('<Enter>', lambda _e: self._slide(-width))
        self.bind('<Leave>', lambda _e: self._slide(0))
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<FocusIn>', lambda _e: self.itemconfigure(self._focus, outline='#ffffff'))
        self.bind('<FocusOut>', lambda _e: self.itemconfigure(self._focus, outline=''))
        for key in ('<Return>', '<KeyRelease-space>'):
            self.bind(key, lambda _e: self.command())

    def _release(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.command()

    def _slide(self, target, duration=500, frame=16):
        if self._job:
            self.after_cancel(self._job)
        start, count = self._offset, max(1, duration // frame)

        def step(i=1):
            self._offset = start + (target - start) * (i / count)
            self.coords(self._picture, round(self._offset), 0)
            self._job = self.after(frame, step, i + 1) if i < count else None
        step()


class FlipTitle(tk.Canvas):
    """画面の題字：扇形に広げた5枚のカードと、クリーム地・濃い枠の少し傾いたリボン（Flip7のロゴ風）。"""

    def __init__(self, parent, text):
        font = tkfont.Font(root=parent, family='Yu Gothic UI', size=20, weight='bold')
        text_w, text_h = font.measure(text), font.metrics('linespace')
        fan_w, pad = 74, 22
        width, height = fan_w + text_w + 2 * pad + 30, max(64, text_h + 26)
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, background=F7['page'])
        ink = F7['ink']
        # 扇形のカード（-24°〜24°）。最後の1枚に「7」。
        pivot_x, pivot_y, card_w, card_h = 34, height - 8, 22, 34
        colors = (F7['coral'], F7['sky'], F7['teal'], F7['gold'], F7['cream'])
        for angle, color in zip((-24, -12, 0, 12, 24), colors):
            rad = math.radians(angle)
            corners = []
            for dx, dy in ((-card_w / 2, -card_h - 10), (card_w / 2, -card_h - 10), (card_w / 2, -10), (-card_w / 2, -10)):
                corners += [pivot_x + dx * math.cos(rad) - dy * math.sin(rad), pivot_y + dx * math.sin(rad) + dy * math.cos(rad)]
            self.create_polygon(*corners, fill=color, outline=ink, width=2)
        rad = math.radians(24)
        cx, cy = pivot_x - (-10 - card_h / 2) * math.sin(rad), pivot_y + (-10 - card_h / 2) * math.cos(rad)
        self.create_text(cx, cy, text='7', fill=F7['gold_d'], angle=-24, font=('Yu Gothic UI', 13, 'bold'))
        # リボン：影（ティール）→ クリーム地・濃い枠の平行四辺形。全体を少し（2°）傾ける。
        x0, x1, y0, y1, skew = fan_w, width - 6, 8, height - 10, 6
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        tilt = math.radians(-2)

        def rotated(points, shift=0):
            out = []
            for x, y in zip(points[::2], points[1::2]):
                x, y = x - center_x, y - center_y
                out += [center_x + x * math.cos(tilt) - y * math.sin(tilt) + shift,
                        center_y + x * math.sin(tilt) + y * math.cos(tilt) + shift]
            return out
        body = [x0 + skew, y0, x1, y0, x1 - skew, y1, x0, y1]
        self.create_polygon(*rotated(body, 4), fill=F7['teal_d'], outline=F7['teal_d'])
        self.create_polygon(*rotated(body), fill=F7['cream'], outline=ink, width=3)
        self.create_text(center_x, center_y, text=text, fill=F7['teal_d'], angle=2, font=font)


def apply_style(root):
    """One look for the whole window (2026-10-04: Flip7 colours — teal, coral, gold and cream on a
    light teal page; gold for the primary action, coral for deleting; same layout and wording)."""
    page, hairline, ink, mute, blue = F7['page'], F7['line'], F7['ink'], F7['mute'], F7['teal']
    style = ttk.Style(root)
    style.theme_use('clam')
    root.configure(background=page)
    base = ('Yu Gothic UI', 10)
    style.configure('.', background=page, foreground=ink, font=base, bordercolor=hairline,
                    lightcolor=page, darkcolor=page, focuscolor=page)
    style.configure('TFrame', background=page)
    style.configure('TLabel', background=page, foreground=ink)
    style.configure('Title.TLabel', font=('Yu Gothic UI', 24, 'bold'), foreground=F7['teal_d'])
    style.configure('H2.TLabel', font=('Yu Gothic UI', 15, 'bold'), foreground=F7['teal_d'])
    style.configure('H3.TLabel', font=('Yu Gothic UI', 10, 'bold'), foreground=F7['teal_d'])
    style.configure('Sub.TLabel', foreground=mute)
    style.configure('TNotebook', background=page, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure('TNotebook.Tab', background=F7['tab'], foreground=F7['teal_d'], padding=(18, 9), borderwidth=0,
                    font=('Yu Gothic UI', 10, 'bold'))
    style.map('TNotebook.Tab', background=[('selected', F7['teal']), ('active', F7['teal_bg'])],
              foreground=[('selected', '#ffffff')])
    style.configure('TLabelframe', background=page, bordercolor=F7['teal_l'], relief='solid')
    style.configure('TLabelframe.Label', background=page, foreground=F7['teal_d'], font=('Yu Gothic UI', 10, 'bold'))
    for name in ('TCheckbutton', 'TRadiobutton'):
        style.configure(name, background=page, indicatorbackground=F7['cream'], indicatorforeground=F7['teal_d'],
                        upperbordercolor=F7['teal_l'], lowerbordercolor=F7['teal_l'])
        style.map(name, background=[('active', page)], indicatorbackground=[('selected', F7['gold'])])
    style.configure('TButton', background=F7['tab'], foreground=F7['teal_d'], padding=(14, 7), borderwidth=0, relief='flat',
                    font=('Yu Gothic UI', 10, 'bold'))
    style.map('TButton', background=[('pressed', F7['teal_l']), ('active', F7['teal_bg'])],
              foreground=[('disabled', mute)])
    style.configure('Accent.TButton', background=F7['gold'], foreground=ink, font=('Yu Gothic UI', 12, 'bold'),
                    padding=(18, 8))
    style.map('Accent.TButton', background=[('pressed', F7['gold_d']), ('active', F7['gold_l'])],
              foreground=[('disabled', mute)])
    # 消す・戻せない操作はコーラル（結果のHTMLの注意の色と同じ）。
    style.configure('Danger.TButton', background=F7['coral'], foreground='#ffffff', font=('Yu Gothic UI', 10, 'bold'),
                    padding=(14, 7), borderwidth=0, relief='flat')
    style.map('Danger.TButton', background=[('pressed', F7['coral_d']), ('active', F7['coral_l'])])
    style.configure('Link.TButton', background=page, foreground=F7['teal_d'], padding=(4, 2))
    style.map('Link.TButton', background=[('active', page)], foreground=[('active', ink)])
    style.configure('TSeparator', background=F7['teal_l'])
    style.configure('TCombobox', fieldbackground=F7['cream'], background=F7['cream'], padding=4,
                    arrowcolor=F7['teal_d'], bordercolor=F7['teal_l'])
    style.map('TCombobox', fieldbackground=[('readonly', F7['cream'])], background=[('readonly', F7['cream'])],
              # 読み取り専用の欄は、選ばれている文字（フォーカス時の選択）が白地に白で見えなくなることがあった
              # （2026-10-02、起動直後の店舗名）。文字は常に濃い色、選択の背景は白で表示する。
              foreground=[('disabled', mute), ('readonly', ink)],
              selectforeground=[('readonly', ink)], selectbackground=[('readonly', F7['cream'])])
    style.configure('TEntry', fieldbackground=F7['cream'], bordercolor=F7['teal_l'])
    style.configure('Vertical.TScrollbar', background=F7['tab'], troughcolor=page, arrowcolor=F7['teal_d'],
                    bordercolor=page)


def main():
    root = tk.Tk()
    root.title('database')
    root.geometry('920x780')
    root.minsize(780, 620)
    apply_style(root)
    frame = ttk.Frame(root, padding=(28, 20, 28, 14))
    frame.pack(fill='both', expand=True)
    FlipTitle(frame, 'database').pack(anchor='w', pady=(0, 12))
    # 記録欄は先に下端へ確保しておく（後から詰め込むと、タブに押されて見えなくなるため）
    log_frame = ttk.Frame(frame)
    log_frame.pack(side='bottom', fill='x', pady=(10, 0))
    notebook = ttk.Notebook(frame)
    notebook.pack(fill='both', expand=True)
    tab_home = ttk.Frame(notebook, padding=22)
    tab_results = ttk.Frame(notebook, padding=22)
    tab_sync = ttk.Frame(notebook, padding=22)
    # バラエティの🌈（確定が出た台の印、RAINBOW.md「バラエティのタブ」、2026-10-11）。
    tab_variety = ttk.Frame(notebook, padding=22)
    notebook.add(tab_home, text='  取り込み  ')
    notebook.add(tab_results, text='  結果を見る  ')
    notebook.add(tab_variety, text='  バラエティ🌈  ')
    notebook.add(tab_sync, text='  バックアップ・同期  ')

    # 🌈：押したときは記録への保存だけ（速い）。閲覧・共有ページ用のファイルとバックアップの作り直し（5秒ほど）は、
    # まとめて1回（2026-10-12 利用者「一個押すたびに保存処理をしているようで数秒かかってしまう。…まとめてつけてから
    # 保存処理してほしい」）：バラエティ🌈の「閲覧・共有ページに反映」ボタン、バラエティ🌈のタブを離れるとき、
    # カレンダーを閉じるとき、PC版を閉じるとき。「過去の記録」の作り直し（10秒ほど）は🌈のときはしない。
    rainbow_pending = [0]
    pending_text = tk.StringVar(value='反映済み')

    def show_pending():
        pending_text.set(f'閲覧・共有ページに反映（{rainbow_pending[0]}件）' if rainbow_pending[0] else '反映済み')

    def mark_rainbow():
        rainbow_pending[0] += 1
        show_pending()

    def flush_rainbow():
        if not rainbow_pending[0]:
            return
        pending_text.set('反映中…')
        root.update_idletasks()
        db = Store(DATA_DIR / 'database.sqlite3')
        try:
            auto_backup(db, DATA_DIR)
        finally:
            db.close()
        tell(f'🌈の付け外し{rainbow_pending[0]}件を、閲覧ページ・共有ページ用のファイルとバックアップに反映しました。\n')
        rainbow_pending[0] = 0
        show_pending()
    refresh_variety = build_variety_tab(tab_variety, DATA_DIR / 'database.sqlite3', mark_rainbow,
                                        on_flush=flush_rainbow, pending=pending_text)
    # タブを開いたときに読み直す（取り込みで新しい日・入れ替えが入っていれば一覧が変わる）。離れるときは🌈をまとめて反映。
    current_tab = [None]

    def open_variety(_event=None):
        selected = notebook.select()
        if current_tab[0] == str(tab_variety) and selected != str(tab_variety):
            flush_rainbow()
        current_tab[0] = selected
        if selected == str(tab_variety):
            pull_shared_rainbow_now()   # iPhoneで付けた🌈も入れてから読み直す
            refresh_variety()
    notebook.bind('<<NotebookTabChanged>>', open_variety, add='+')

    ttk.Label(tab_results, text='見たい台を選ぶ', style='H2.TLabel').pack(anchor='w')
    ttk.Label(tab_results, text='保存済みの店舗・日付・機種だけ選べます。', style='Sub.TLabel').pack(anchor='w', pady=(0, 10))
    startup_notes = []
    identity = ttk.Frame(tab_results)
    identity.pack(fill='x')
    ttk.Label(identity, text='店舗').grid(row=0, column=0, sticky='w')
    settings = load_settings(DATA_DIR)
    store_name = tk.StringVar(value=PSCUBE_LABEL if settings.get('last_store') == PSCUBE_KEY else
                              STORE_NAMES.get(settings.get('last_store'), STORE_NAMES['nagamachiminami']))
    store_combo = ttk.Combobox(identity, textvariable=store_name, values=[*STORE_NAMES.values(), PSCUBE_LABEL],
                                state='readonly', width=28)
    store_combo.grid(row=1, column=0, sticky='w', padx=(0, 16))
    ttk.Label(identity, text='日付').grid(row=0, column=1, sticky='w')
    day = tk.StringVar(value=settings.get('last_day', ''))
    day_combo = ttk.Combobox(identity, textvariable=day, state='readonly', width=16)
    day_combo.grid(row=1, column=1, sticky='w', padx=(0, 16))
    ttk.Label(identity, text='イベント').grid(row=0, column=2, sticky='w')
    event_name = tk.StringVar(value='イベントなし')
    current_event_name = tk.StringVar(value='')
    event_box = ttk.Frame(identity)
    event_box.grid(row=1, column=2, sticky='w', padx=(0, 16))
    event_combo = ttk.Combobox(event_box, textvariable=event_name,
                               values=['イベントなし', *DATE_EVENT_OPTIONS, '自由記載…'],
                               state='readonly', width=20)
    event_combo.pack(side='left')
    # 先の日にも入れられるカレンダー（メルヘン2店舗、EVENT_CALENDAR.md）。
    ttk.Button(event_box, text='カレンダー', style='Link.TButton',
               command=lambda: open_events_calendar()).pack(side='left', padx=(4, 0))
    ttk.Label(identity, text='機種名').grid(row=0, column=3, sticky='w')
    machine = tk.StringVar(value=settings.get('last_machine', MACHINE_DEFAULT))
    machine_combo = ttk.Combobox(identity, textvariable=machine, state='readonly', width=34)
    machine_combo.grid(row=1, column=3, sticky='ew')
    identity.columnconfigure(3, weight=1)


    def current_location():
        if store_name.get() == PSCUBE_LABEL:
            return PSCUBE_KEY
        return next((key for key, label in STORE_NAMES.items() if label == store_name.get()), None)

    def pscube_store():
        return pscube_import.PscubeStore(DATA_DIR / 'pscube.sqlite3')

    def pscube_only(title):
        """P’s CUBEを選んでいるときは、メルヘン専用の操作を止める（P’s CUBEの記録は変えない）。"""
        if current_location() == PSCUBE_KEY:
            messagebox.showinfo(title, 'P’s CUBEの記録は、この操作の対象外です。', parent=root)
            return True
        return False

    def open_pscube_viewer():
        import webbrowser
        webbrowser.open(PSCUBE_VIEWER_URL)
        logbox.insert('end', 'P’s CUBEの閲覧ページを開きました（採点・翌日候補）。Googleドライブの自動読み込みが未設定なら、'
                             'ページの「Googleドライブの自動読み込みを設定」にApps ScriptのURLを入れてください。\n')
        logbox.see('end')

    def refresh_days(*_args):
        location = current_location()
        if location == PSCUBE_KEY:
            store = pscube_store()
            try:
                days = store.days()
            finally:
                store.close()
            day_combo['values'] = days
            if day.get() not in days:
                day.set(days[0] if days else '')
            refresh_event()
            return
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            days = db.days_for(location) if location else []
        finally:
            db.close()
        day_combo['values'] = days
        if day.get() not in days:
            day.set(days[0] if days else '')
        refresh_event()

    def tell(text):
        # 起動直後はまだ記録欄が無いので、できてから出す。
        try:
            logbox.insert('end', text)
            logbox.see('end')
        except NameError:
            startup_notes.append(text)

    def pull_shared_events_now():
        """閲覧ページで入れたイベント（共有カレンダー、同期フォルダの共有ファイル）を取り込む。"""
        folder = load_settings(DATA_DIR).get('sync_dir')
        if not folder:
            return
        location = current_location()
        try:
            if location == PSCUBE_KEY:
                store = pscube_store()
                try:
                    changed = store.pull_shared_events(folder)
                finally:
                    store.close()
            else:
                db = Store(ROOT / 'data' / 'database.sqlite3')
                try:
                    changed = pull_shared_events(db, folder)
                finally:
                    db.close()
        except Exception as exc:  # 取り込めなくても画面は動かす（次の切り替えでまた試す）
            tell(f'共有カレンダーのイベントを取り込めませんでした：{exc}\n')
            return
        if changed:
            tell(f'共有カレンダーのイベントを{changed}件取り込みました。\n')
        if location != PSCUBE_KEY:
            pull_shared_rainbow_now()

    def pull_shared_rainbow_now():
        """iPhoneの閲覧ページで付け外しした🌈（同期フォルダの共有ファイル、RAINBOW.md）を取り込む。
        変わったら閲覧用ファイル・バックアップ・結果を作り直す（共有ページにも届くように）。"""
        folder = load_settings(DATA_DIR).get('sync_dir')
        if not folder:
            return 0
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            changed = pull_shared_rainbow(db, folder)
            if changed:
                auto_backup(db, DATA_DIR)
                history_report(db, ROOT / 'reports')
        except Exception as exc:  # noqa: BLE001 - 取り込めなくても画面は動かす（次にまた試す）
            tell(f'iPhoneで付けた🌈を取り込めませんでした：{exc}\n')
            return 0
        finally:
            db.close()
        if changed:
            tell(f'iPhoneで付け外しした🌈を{changed}台取り込みました。\n')
        return changed

    def refresh_event(*_args):
        location, selected_day = current_location(), day.get()
        event_combo.configure(state='readonly')
        pull_shared_events_now()
        if location == PSCUBE_KEY:
            # P’s CUBEは自由記入だけ。一度付けた名前は選択肢に増えていく（2026-10-06）。
            store = pscube_store()
            try:
                current = store.date_event_for(selected_day) if selected_day else None
                names = store.date_event_names()
            finally:
                store.close()
            event_combo['values'] = ['イベントなし', *names, '自由記載…']
            event_name.set(current or 'イベントなし')
            current_event_name.set(current or '')
            return
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            events = db.date_events(location=location, day=selected_day)
        finally:
            db.close()
        current = events[0]['name'] if events else 'イベントなし'
        choices = ['イベントなし', *DATE_EVENT_OPTIONS, '自由記載…']
        if current not in choices:
            choices.append(current)
        event_combo['values'] = choices
        event_name.set(current)
        current_event_name.set('' if current == 'イベントなし' else current)

    def on_event_change(_event=None):
        location, selected_day = current_location(), day.get()
        if not location or not selected_day:
            return
        selected = event_name.get()
        if selected == '自由記載…':
            selected = simpledialog.askstring('イベント名', 'イベント名を入力してください（60文字以内）',
                                              initialvalue=current_event_name.get(), parent=root)
            if selected is None:
                refresh_event()
                return
            selected = selected.strip()
            if not selected or len(selected) > 60:
                messagebox.showwarning('イベント名', 'イベント名は1〜60文字で入力してください。', parent=root)
                refresh_event()
                return
        if location == PSCUBE_KEY:
            store = pscube_store()
            try:
                store.set_date_event(selected_day, None if selected == 'イベントなし' else selected)
                # 閲覧ページ（Googleドライブ経由）とバックアップにも反映する。
                pscube_import.auto_backup(store, DATA_DIR / 'pscube-viewer.json')
            except ValueError as error:
                messagebox.showwarning('イベント名', str(error), parent=root)
            finally:
                store.close()
            refresh_event()
            return
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            db.set_date_event(location, selected_day, None if selected == 'イベントなし' else selected)
            auto_backup(db, DATA_DIR)
            history_report(db, ROOT / 'reports')
        finally:
            db.close()
        refresh_event()

    def open_events_calendar():
        def changed(db):
            auto_backup(db, DATA_DIR)
            history_report(db, ROOT / 'reports')
            root.after(0, refresh_event)

        def pscube_changed(store):
            # 閲覧ページ（Googleドライブ経由）とバックアップにも反映する（イベント欄と同じ）。
            pscube_import.auto_backup(store, DATA_DIR / 'pscube-viewer.json')
            root.after(0, refresh_event)

        pull_shared_events_now()
        location = current_location()
        if location == PSCUBE_KEY:
            open_event_calendar(root, DATA_DIR / 'pscube.sqlite3',
                                events=PscubeEvents(DATA_DIR / 'pscube.sqlite3', pscube_changed, PSCUBE_LABEL),
                                on_open_record=open_from_calendar)
            return
        open_event_calendar(root, ROOT / 'data' / 'database.sqlite3',
                            location=location if location in STORE_NAMES else None, on_changed=changed,
                            on_open_record=open_from_calendar, on_rainbow=mark_rainbow, on_closed=flush_rainbow)

    def open_from_calendar(location, target_day, row):
        """カレンダーの日のまとめ（TOP10）の台から：結果を見るでその日・その機種を選び、結果を開く。"""
        store_name.set(PSCUBE_LABEL if location == PSCUBE_KEY else STORE_NAMES[location])
        refresh_days()
        if target_day in day_combo.cget('values'):
            day.set(target_day)
        refresh_event()
        refresh_machines()
        if row['machine'] in machine_combo.cget('values'):
            machine.set(row['machine'])
        remember_selection()
        notebook.select(tab_results)
        tell(f'カレンダーから {target_day}・{row["machine"]}（{row["rack"]}番台）を選びました。\n')
        open_result()

    def refresh_machines(*_args):
        location = current_location()
        target = day.get()
        if location == PSCUBE_KEY:
            store = pscube_store()
            try:
                machines = store.machines_for(target) if target else []
            finally:
                store.close()
            machine_combo['values'] = machines
            if machine.get() not in machines:
                machine.set(machines[0] if machines else '')
            return
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            machines = db.machines_for(location, target) if location and target else []
        finally:
            db.close()
        machine_combo['values'] = machines
        if machine.get() not in machines:
            machine.set(machines[0] if machines else '')

    def remember_selection(_event=None):
        save_settings(DATA_DIR, last_store=current_location(), last_day=day.get(),
                      last_machine=machine.get())

    def on_store_change(_event=None):
        refresh_days()
        refresh_machines()
        remember_selection()

    def on_day_change(_event=None):
        refresh_event()
        refresh_machines()
        remember_selection()

    store_combo.bind('<<ComboboxSelected>>', on_store_change)
    day_combo.bind('<<ComboboxSelected>>', on_day_change)
    event_combo.bind('<<ComboboxSelected>>', on_event_change)
    machine_combo.bind('<<ComboboxSelected>>', remember_selection)
    refresh_days()
    refresh_machines()

    ttk.Label(tab_home, text='ブラウザで取り込む', style='H2.TLabel').pack(anchor='w')
    ttk.Label(tab_home, text='ふだんの取り込みは、ここから始めます。', style='Sub.TLabel').pack(anchor='w', pady=(0, 12))
    GradientButton(tab_home, text='メルヘンワールドを取り込む',
                   command=lambda: open_browser_import()).pack(anchor='w')
    ttk.Button(tab_home, text='P’s CUBE（スロット）を取り込む',
               command=lambda: open_pscube_import()).pack(anchor='w', ipadx=22, ipady=9, pady=(9, 0))
    ttk.Label(tab_home, style='Sub.TLabel', justify='left', text=(
        '① 機種一覧・機種別の表・個別台グラフで「この画面を取り込む」\n'
        '② 表は表、グラフはグラフとして保存され、次の必要な台へ移動\n'
        '③ 機種が終わると、機種一覧へ自動で移動')).pack(anchor='w', pady=(14, 18))
    ttk.Separator(tab_home).pack(fill='x', pady=(0, 14))
    quick = ttk.Frame(tab_home)
    quick.pack(anchor='w')
    ttk.Button(quick, text='この日のまとめ', command=lambda: open_summary()).pack(side='left')
    ttk.Button(quick, text='過去の記録を見る', command=lambda: open_history()).pack(side='left', padx=8)
    ttk.Button(quick, text='直前の保存を取り消す', command=lambda: undo_last()).pack(side='left')
    # 4円パチンコ（PC版だけ、PACHINKO.md）：記録のページと、取り込む末尾（2026-10-12 利用者「取り込む末尾を毎月
    # 変えたいから取り込む末尾選択ボタンが欲しい」。月に合わせる＝10月→0、11月→1）。
    pachi = ttk.Frame(tab_home)
    pachi.pack(anchor='w', pady=(10, 0))
    ttk.Button(pachi, text='パチンコの記録', command=lambda: open_pachinko()).pack(side='left')
    ttk.Label(pachi, text='パチンコで取り込む末尾（スロットには関係なし）', style='Sub.TLabel').pack(side='left', padx=(16, 6))
    tail_choices = {'month': '月に合わせる（10月→0・11月→1）', **{str(d): f'末尾{d}' for d in range(10)}}
    tail_saved = str(load_settings(DATA_DIR).get('pachinko_tail', 'month'))
    tail_var = tk.StringVar(value=tail_choices.get(tail_saved, tail_choices['month']))
    tail_box = ttk.Combobox(pachi, textvariable=tail_var, values=list(tail_choices.values()), state='readonly', width=30)
    tail_box.pack(side='left')

    def choose_tail(_event=None):
        key = next(k for k, v in tail_choices.items() if v == tail_var.get())
        try:
            save_settings(DATA_DIR, pachinko_tail=key)
        except OSError as exc:
            messagebox.showerror('取り込む末尾を保存できません', str(exc), parent=root)
    tail_box.bind('<<ComboboxSelected>>', choose_tail)

    sync_box = ttk.LabelFrame(tab_sync, text='同期フォルダ（Google Driveなど）', padding=14)
    sync_box.pack(fill='x', pady=(0, 14))
    sync_dir = tk.StringVar(value=settings.get('sync_dir') or '未設定')
    ttk.Label(sync_box, style='Sub.TLabel', wraplength=680, text=(
        '一度フォルダを指定すると、保存のたびに最新のバックアップが自動でこのフォルダに書き出されます。'
        'Android版のファイルは、ボタン1つで読み込めます（食い違う記録だけ確認します）。')).pack(anchor='w', pady=(0, 8))
    ttk.Label(sync_box, textvariable=sync_dir).pack(anchor='w')
    sync_buttons = ttk.Frame(sync_box)
    sync_buttons.pack(fill='x', pady=(8, 0))

    backup_box = ttk.LabelFrame(tab_sync, text='範囲を指定して書き出す・読み込む', padding=14)
    backup_box.pack(fill='x', pady=(0, 14))
    ttk.Label(backup_box, style='Sub.TLabel', wraplength=680, text=(
        '店舗・日付を選ぶと、その範囲の全機種だけを書き出します（「すべて」なら全体）。'
        '読み込み時、数値が食い違う記録は自動で上書きせず、確認してから反映します。')).pack(anchor='w', pady=(0, 8))
    backup_buttons = ttk.Frame(backup_box)
    backup_buttons.pack(fill='x')
    backup_store = tk.StringVar(value=ALL_STORES_LABEL)
    backup_store_combo = ttk.Combobox(
        backup_buttons, textvariable=backup_store, state='readonly', width=16,
        values=[ALL_STORES_LABEL, *STORE_NAMES.values(), PSCUBE_LABEL])
    backup_day = tk.StringVar(value=ALL_DAYS_LABEL)
    backup_day_combo = ttk.Combobox(backup_buttons, textvariable=backup_day, state='readonly', width=16)

    def current_backup_location():
        chosen = backup_store.get()
        if chosen == PSCUBE_LABEL:
            return PSCUBE_KEY
        return next((key for key, label in STORE_NAMES.items() if label == chosen), None)

    def refresh_backup_days():
        location = current_backup_location()
        if location == PSCUBE_KEY:
            # P’s CUBEは全期間をまとめて書き出す（復元に使える形）。
            backup_day_combo['values'] = [ALL_DAYS_LABEL]
            backup_day.set(ALL_DAYS_LABEL)
            return
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            days = db.days_for(location)
        finally:
            db.close()
        backup_day_combo['values'] = [ALL_DAYS_LABEL, *days]
        if backup_day.get() not in backup_day_combo['values']:
            backup_day.set(ALL_DAYS_LABEL)

    backup_store_combo.bind('<<ComboboxSelected>>', lambda _e=None: refresh_backup_days())
    backup_day_combo.configure(postcommand=refresh_backup_days)
    refresh_backup_days()

    results_box = ttk.Frame(tab_results)
    results_box.pack(fill='x', pady=(18, 0))
    results_buttons = ttk.Frame(results_box)
    results_buttons.pack(fill='x')

    ttk.Label(log_frame, text='記録', style='H3.TLabel').pack(anchor='w')
    logbox = tk.Text(log_frame, wrap='word', height=6, font=('Yu Gothic UI', 10), relief='flat',
                     highlightthickness=2, highlightbackground=F7['line'], highlightcolor=F7['teal_l'],
                     background=F7['cream'], foreground=F7['ink'], padx=10, pady=8)
    logbox.pack(fill='x', pady=(4, 0))
    for note in startup_notes:
        logbox.insert('end', note)

    def open_browser_import():
        try:
            if getattr(sys, 'frozen', False):
                executable_dir = Path(sys.executable).resolve().parent
                browser_candidates = (
                    executable_dir / 'database-browser.exe',
                    executable_dir.parent / 'database-browser' / 'database-browser.exe',
                )
                browser = next((candidate for candidate in browser_candidates if candidate.exists()), None)
                if browser is None:
                    raise OSError('database-browser.exe が見つかりません。database/bin の配布フォルダ一式をそろえてください。')
                command = [str(browser), str(ROOT / 'data' / 'database.sqlite3'), str(ROOT / 'reports')]
            else:
                command = [sys.executable, str(ROOT / 'browser_import.py'),
                           str(ROOT / 'data' / 'database.sqlite3'), str(ROOT / 'reports')]
            subprocess.Popen(
                command,
                cwd=str(ROOT))
            logbox.insert(
                'end',
                'ブラウザ取り込みを別ウィンドウで開始しました。'
                '保存後は「過去の記録を見る」で確認できます。\n')
            logbox.see('end')
        except OSError as exc:
            messagebox.showerror('起動できません', f'ブラウザ取り込みを開始できません：{exc}', parent=root)

    def open_pscube_import():
        try:
            if getattr(sys, 'frozen', False):
                executable_dir = Path(sys.executable).resolve().parent
                candidates = (
                    executable_dir / 'database-pscube.exe',
                    executable_dir.parent / 'database-pscube' / 'database-pscube.exe',
                )
                browser = next((candidate for candidate in candidates if candidate.exists()), None)
                if browser is None:
                    raise OSError('database-pscube.exe が見つかりません。配布フォルダ一式をそろえてください。')
                command = [str(browser), str(ROOT / 'data' / 'pscube.sqlite3'),
                           str(ROOT / 'data' / 'pscube-viewer.json')]
            else:
                command = [sys.executable, str(ROOT / 'pscube_import.py')]
            subprocess.Popen(command, cwd=str(ROOT))
            logbox.insert('end', 'P’s CUBE の取り込み画面を開きました。\n')
            logbox.see('end')
        except OSError as exc:
            messagebox.showerror('起動できません', f'P’s CUBEを開始できません：{exc}', parent=root)

    def values():
        name, target = machine.get().strip(), day.get().strip()
        location = current_location()
        if not location:
            raise ValueError('店舗を選んでください。')
        if not target:
            raise ValueError('この店舗に保存された日付がありません。')
        if not name:
            raise ValueError('この店舗・日付に保存された機種がありません。')
        date.fromisoformat(target)
        return location, name, target

    def make_report(location, name, target):
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            if not db.rows(target, name, location):
                return None
            output, results = report(db, target, name, ROOT / 'reports', location)
            history_report(db, ROOT / 'reports')
        finally:
            db.close()
        done = sum(row['score']['total'] is not None for row in results)
        logbox.insert('end', f'結果を更新しました：{len(results)}台中、総合点確定{done}台。\n{output}\n')
        logbox.see('end')
        return output

    def export_pscube_file():
        name = pscube_import.backup_file_name()
        folder = load_settings(DATA_DIR).get('sync_dir')
        if folder and Path(folder).is_dir():
            path = str(Path(folder) / name)
        else:
            path = filedialog.asksaveasfilename(
                title='P’s CUBEのバックアップの保存先を選択（Google Driveのフォルダなど）',
                initialfile=name, defaultextension='.json',
                filetypes=[('JSON', '*.json'), ('すべて', '*.*')])
        if not path:
            return
        store = pscube_store()
        try:
            count = len(store.export_payload('backup')['records'])
            pscube_import.write_backup(store, path)
        finally:
            store.close()
        logbox.insert('end', f'P’s CUBEのバックアップを書き出しました（全期間）：{count}件 → {path}\n')
        logbox.see('end')
        messagebox.showinfo('書き出しました', f'P’s CUBEの{count}件（全期間）を書き出しました。\n{path}', parent=root)

    def export_backup_file():
        if current_backup_location() == PSCUBE_KEY:
            export_pscube_file()
            return
        chosen_day = backup_day.get()
        day = chosen_day if chosen_day and chosen_day != ALL_DAYS_LABEL else None
        location = current_backup_location()
        store_suffix = f'-{location}' if location else ''
        day_suffix = f'-{day}' if day else ''
        default_name = f'database-backup{store_suffix}{day_suffix}-{datetime.now():%Y%m%d-%H%M%S}.json'
        folder = load_settings(DATA_DIR).get('sync_dir')
        if folder and Path(folder).is_dir():
            path = str(Path(folder) / default_name)
        else:
            path = filedialog.asksaveasfilename(
                title='バックアップの保存先を選択（Google Driveのフォルダなど）',
                initialfile=default_name, defaultextension='.json',
                filetypes=[('JSON', '*.json'), ('すべて', '*.*')])
        if not path:
            return
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            count = export_backup(db, path, location=location, day=day)
        finally:
            db.close()
        scope_bits = [STORE_NAMES[location] if location else '全店舗', day if day else '全期間']
        target_text = '・'.join(scope_bits)
        logbox.insert('end', f'バックアップを書き出しました（{target_text}）：{count}件 → {path}\n')
        logbox.see('end')
        messagebox.showinfo('書き出しました', f'{target_text}の{count}件のデータを書き出しました。\n{path}', parent=root)

    def import_backup_file(path=None, quiet=False):
        path = path or filedialog.askopenfilename(
            title='取り込むバックアップファイルを選択',
            filetypes=[('JSON', '*.json'), ('すべて', '*.*')])
        if not path:
            return
        if pscube_import.is_pscube_backup(path):
            # P’s CUBEのファイルをメルヘンの読み込みに通すと、全台が「対象外」になって何も入らない。
            import_pscube_file(path, quiet=quiet)
            return
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            plan = import_backup(db, path)
            if plan['conflicts']:
                dialog = BackupConflictsDialog(root, plan['conflicts'])
                root.wait_window(dialog)
                if dialog.selected:
                    db.save(dialog.selected)
            history_report(db, ROOT / 'reports')
            auto_backup(db, DATA_DIR)
        except Exception as exc:
            messagebox.showerror('取り込めません', str(exc), parent=root)
            return
        finally:
            db.close()
        refresh_days()
        refresh_machines()
        applied = (len(plan['new']) + len(plan['graph_only']) + len(plan['link_only']) + len(plan.get('jo_only', []))
                   + plan.get('events_added', 0))
        summary = (f'新規{len(plan["new"])}件、グラフ追加{len(plan["graph_only"])}件、リンク補完{len(plan["link_only"])}件、'
                   f'ジャグラーオンラインの差枚{len(plan.get("jo_only", []))}件を取り込みました。'
                   f'既に同じ内容{len(plan["unchanged"])}件、要確認{len(plan["conflicts"])}件、'
                   f'イベント反映{plan.get("events_added", 0)}件、イベント名不一致{plan.get("event_conflicts", 0)}件（入力時刻の無い同士は既存名を維持）、'
                   f'対象外{len(plan["skipped"])}件。')
        logbox.insert('end', f'バックアップを読み込みました：{summary}\n')
        logbox.see('end')
        if quiet:
            return
        if applied:
            messagebox.showinfo('読み込みました', summary, parent=root)
        else:
            messagebox.showinfo('反映なし', summary, parent=root)

    ttk.Button(backup_buttons, text='バックアップを書き出す', command=export_backup_file).pack(side='left')
    ttk.Label(backup_buttons, text='店舗').pack(side='left', padx=(12, 4))
    backup_store_combo.pack(side='left')
    ttk.Label(backup_buttons, text='日付').pack(side='left', padx=(12, 4))
    backup_day_combo.pack(side='left')
    ttk.Button(backup_buttons, text='バックアップを読み込む', command=import_backup_file).pack(side='left', padx=(16, 0))

    def choose_sync_dir():
        folder = filedialog.askdirectory(title='同期フォルダ（Google Driveの同期フォルダなど）を選択', parent=root)
        if not folder:
            return
        save_settings(DATA_DIR, sync_dir=folder)
        sync_dir.set(folder)
        db = Store(DATA_DIR / 'database.sqlite3')
        try:
            auto_backup(db, DATA_DIR)
        finally:
            db.close()
        logbox.insert('end', f'同期フォルダを設定しました：{folder}\n最新のバックアップを書き出しました。\n')
        logbox.see('end')

    def import_latest_from_sync():
        folder = load_settings(DATA_DIR).get('sync_dir')
        if not folder or not Path(folder).is_dir():
            messagebox.showinfo('同期フォルダ未設定', '先に「同期フォルダを指定」してください。', parent=root)
            return
        latest = latest_backup_file(folder)
        if latest is None:
            messagebox.showinfo('見つかりません', 'このフォルダにバックアップファイルがありません。', parent=root)
            return
        logbox.insert('end', f'最新のバックアップ：{latest.name}\n')
        import_backup_file(str(latest))
        remember_synced(latest)

    def import_pscube_from_sync():
        """P’s CUBEの最新バックアップ（Android・ブラウザの書き出しなど）を専用の記録へ統合する。"""
        folder = load_settings(DATA_DIR).get('sync_dir')
        if not folder or not Path(folder).is_dir():
            messagebox.showinfo('同期フォルダ未設定', '先に「同期フォルダを指定」してください。', parent=root)
            return
        latest = pscube_import.latest_pscube_backup(folder)
        if latest is None:
            messagebox.showinfo('見つかりません', 'このフォルダにP’s CUBEのバックアップ（pscube-backup-…）がありません。', parent=root)
            return
        import_pscube_file(latest)

    def import_pscube_file(latest, quiet=False):
        """P’s CUBEのバックアップ1つを専用の記録へ統合する（メルヘンの記録には混ぜない）。"""
        latest = Path(latest)
        store = pscube_import.PscubeStore(DATA_DIR / 'pscube.sqlite3')
        try:
            summary = store.import_backup(latest)
            pscube_import.auto_backup(store, DATA_DIR / 'pscube-viewer.json')
        except Exception as exc:
            messagebox.showerror('取り込めません', str(exc), parent=root)
            return
        finally:
            store.close()
        text = (f'P’s CUBE：新規{summary["added"]}件、更新{summary["updated"]}件、同じ内容{summary["unchanged"]}件、'
                f'新しい自分の数値を維持{summary["kept_local"]}件（{latest.name}）。')
        logbox.insert('end', text + '\n')
        logbox.see('end')
        if not quiet:
            messagebox.showinfo('読み込みました', text, parent=root)

    def remember_synced(latest):
        save_settings(DATA_DIR, last_synced=dict(name=latest.name, mtime=latest.stat().st_mtime))

    def auto_sync_on_start():
        """Pick up a newer backup from the sync folder without any click.

        Only files newer than the last one already read are imported, and
        anything that conflicts still goes through the confirmation dialog.
        """
        current = load_settings(DATA_DIR)
        folder = current.get('sync_dir')
        if not current.get('auto_sync_on_start', True) or not folder or not Path(folder).is_dir():
            return
        latest = latest_backup_file(folder)
        if latest is None:
            return
        seen = current.get('last_synced') or {}
        if seen.get('name') == latest.name and seen.get('mtime') == latest.stat().st_mtime:
            return
        logbox.insert('end', f'同期フォルダに新しいバックアップがあります：{latest.name}\n')
        import_backup_file(str(latest), quiet=True)
        remember_synced(latest)

    auto_sync = tk.BooleanVar(value=settings.get('auto_sync_on_start', True) is not False)
    ttk.Checkbutton(
        sync_box, variable=auto_sync,
        command=lambda: save_settings(DATA_DIR, auto_sync_on_start=auto_sync.get()),
        text='起動時に新しいバックアップを自動で読み込む',
    ).pack(anchor='w', pady=(10, 0))
    def restore_from_snapshot():
        """Pick one of the dated backups (last 7 days) and go back to its state."""
        snapshots = list_snapshots(DATA_DIR)
        if not snapshots:
            messagebox.showinfo('戻せるバックアップがありません',
                                '日ごとのバックアップは、データを保存すると自動で作られます（直近7日分）。', parent=root)
            return
        dialog = tk.Toplevel(root)
        dialog.title('過去のバックアップから戻す')
        dialog.transient(root)
        dialog.grab_set()
        dialog.geometry('520x420')
        ttk.Label(dialog, text='戻したい日を選んでください', style='H2.TLabel').pack(anchor='w', padx=20, pady=(18, 2))
        ttk.Label(dialog, style='Sub.TLabel', wraplength=470, text=(
            'その日の最後の状態に戻します。数値やグラフが食い違う台は、その日の内容で上書きします。'
            'その後に追加した台は消えません。')).pack(anchor='w', padx=20)
        listbox = tk.Listbox(dialog, height=8, activestyle='none', exportselection=False,
                             font=('Yu Gothic UI', 11), relief='flat', highlightthickness=1,
                             highlightbackground=F7['line'], background=F7['cream'], foreground=F7['ink'],
                             selectbackground=F7['teal'], selectforeground='#ffffff')
        for stamp, path in snapshots:
            listbox.insert('end', f'{stamp:%Y-%m-%d}（{"月火水木金土日"[stamp.weekday()]}）　{path.stat().st_size / 1e6:.1f}MB')
        listbox.selection_set(0)
        listbox.pack(fill='x', padx=20, pady=12)
        chosen = {}

        def do_restore():
            selection = listbox.curselection()
            if not selection:
                return
            stamp, path = snapshots[selection[0]]
            if not messagebox.askyesno(
                    '確認', f'{stamp:%Y-%m-%d} の状態に戻します。\n食い違う台は、その日の内容で上書きされます。よろしいですか？',
                    icon='warning', parent=dialog):
                return
            chosen['path'] = path
            chosen['stamp'] = stamp
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill='x', padx=20, pady=(0, 16))
        ttk.Button(buttons, text='この日に戻す', style='Accent.TButton', command=do_restore).pack(side='left')
        ttk.Button(buttons, text='キャンセル', command=dialog.destroy).pack(side='left', padx=8)
        root.wait_window(dialog)
        if not chosen:
            return
        db = Store(DATA_DIR / 'database.sqlite3')
        try:
            result = restore_backup(db, chosen['path'])
            history_report(db, ROOT / 'reports')
            auto_backup(db, DATA_DIR)
        except Exception as exc:
            messagebox.showerror('戻せません', str(exc), parent=root)
            return
        finally:
            db.close()
        refresh_days()
        refresh_machines()
        text = (f'{chosen["stamp"]:%Y-%m-%d} の状態に戻しました：新規{len(result["new"])}件、'
                f'上書き{len(result["forced"])}件。')
        logbox.insert('end', text + '\n')
        logbox.see('end')
        messagebox.showinfo('戻しました', text, parent=root)

    ttk.Button(sync_buttons, text='同期フォルダを指定', command=choose_sync_dir).pack(side='left')
    ttk.Button(sync_buttons, text='同期フォルダの最新を読み込む', command=import_latest_from_sync).pack(side='left', padx=8)
    ttk.Button(sync_buttons, text='過去のバックアップから戻す', command=lambda: restore_from_snapshot()).pack(side='left')
    ttk.Button(sync_box, text='P’s CUBEの同期フォルダの最新を読み込む', command=lambda: import_pscube_from_sync()).pack(anchor='w', pady=(8, 0))

    def open_summary():
        target = day.get().strip()
        if not target:
            messagebox.showinfo('まとめを開けません', '保存された日付がありません。', parent=root)
            return
        db = Store(DATA_DIR / 'database.sqlite3')
        try:
            output = summary_report(db, ROOT / 'reports', target)
        except ValueError as exc:
            messagebox.showinfo('まとめを開けません', str(exc), parent=root)
            return
        finally:
            db.close()
        os.startfile(output)

    def open_result():
        if current_location() == PSCUBE_KEY:
            open_pscube_viewer()
            return
        try:
            location, name, target = values()
        except ValueError as exc:
            messagebox.showerror('結果を開けません', str(exc), parent=root)
            return
        output = make_report(location, name, target)
        if output is None:
            messagebox.showinfo(
                '記録がありません',
                f'{STORE_NAMES[location]}\n{target}\n{name}\nの保存済み記録がありません。',
                parent=root)
            return
        os.startfile(output)

    def open_history():
        if current_location() == PSCUBE_KEY:
            open_pscube_viewer()
            return
        try:
            db = Store(ROOT / 'data' / 'database.sqlite3')
            try:
                output = history_report(db, ROOT / 'reports')
            finally:
                db.close()
            os.startfile(output)
        except Exception as exc:
            messagebox.showerror('過去の記録を開けません', str(exc), parent=root)

    def open_pachinko():
        from pachinko_report import build_report
        try:
            os.startfile(build_report(ROOT / 'data' / 'database.sqlite3', ROOT / 'reports'))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror('パチンコの記録を開けません', str(exc), parent=root)

    def delete_record():
        if pscube_only('台記録を削除'):
            return
        try:
            refresh_days()
            refresh_machines()
            location, name, target = values()
            db = Store(ROOT / 'data' / 'database.sqlite3')
            try:
                rows = db.rows(target, name, location)
                if not rows:
                    raise ValueError('この店舗・日付・機種には削除できる記録がありません。')
                racks = sorted(int(row['rack']) for row in rows)
                rack = simpledialog.askinteger(
                    '台記録を削除',
                    f'{STORE_NAMES[location]}\n{target}\n{name}\n\n削除する台番号を入力してください。\n保存済み：{", ".join(map(str, racks))}',
                    parent=root,
                    minvalue=1,
                    maxvalue=9999,
                )
                if rack is None:
                    return
                if rack not in racks:
                    raise ValueError(f'{rack}番台はこの条件では保存されていません。')
                confirmed = messagebox.askyesno(
                    '削除の確認',
                    f'{target}\n{STORE_NAMES[location]}\n{name}\n{rack}番台の記録を削除します。\nこの操作は元に戻せません。',
                    icon='warning',
                    parent=root,
                )
                if not confirmed:
                    return
                db.delete(location, target, name, rack)
                remaining = db.rows(target, name, location)
                history_report(db, ROOT / 'reports')
                auto_backup(db, DATA_DIR)
            finally:
                db.close()
            refresh_days()
            refresh_machines()
            if remaining:
                make_report(location, name, target)
            logbox.insert('end', f'{target}｜{name}｜{rack}番台の記録を削除しました。\n')
            logbox.see('end')
        except Exception as exc:
            messagebox.showerror('記録を削除できません', str(exc), parent=root)

    def delete_group():
        """取り込みミスなどを、機種ごと・日付ごとにまとめて削除する。

        選んでいる店舗・日付・機種を元に、消す範囲を3つから選ぶ。確認のあとで
        消し、消した内容は「直前の保存を取り消す」で1回分だけ元に戻せる。
        """
        if pscube_only('まとめて削除'):
            return
        try:
            refresh_days()
            refresh_machines()
            location = current_location()
            target = day.get().strip()
            name = machine.get().strip()
            if not location:
                raise ValueError('店舗を選んでください。')
            if not target:
                raise ValueError('この店舗に保存された日付がありません。')
            db = Store(DATA_DIR / 'database.sqlite3')
            try:
                counts = dict(
                    machine=len(db.rows(target, name, location)) if name else 0,
                    store=len(db.rows(target, None, location)),
                    both=len(db.rows(target)),
                )
            finally:
                db.close()
            store_label = STORE_NAMES[location]
            options = [
                ('machine', f'この機種だけ：{store_label}　{target}　{name}（{counts["machine"]}台）',
                 dict(location=location, machine=name)),
                ('store', f'この店舗のこの日すべて：{store_label}　{target}（{counts["store"]}台）',
                 dict(location=location, machine=None)),
                ('both', f'両店舗のこの日すべて：{target}（{counts["both"]}台）',
                 dict(location=None, machine=None)),
            ]

            dialog = tk.Toplevel(root)
            dialog.title('まとめて削除')
            dialog.transient(root)
            dialog.grab_set()
            dialog.resizable(False, False)
            ttk.Label(dialog, text='まとめて削除', style='H2.TLabel').pack(anchor='w', padx=20, pady=(18, 4))
            ttk.Label(dialog, text='取り込みミスなどを、機種ごと・日付ごとに消します。\n'
                                   '消す範囲を選んでください（次に確認があります）。',
                      style='Sub.TLabel').pack(anchor='w', padx=20, pady=(0, 10))
            # 初期選択は、台数がある範囲の最初（無効な範囲を選んだまま進めないように）。
            choice = tk.StringVar(value=next((key for key, _, _ in options if counts[key]), ''))
            if not choice.get():
                raise ValueError('この日付に削除できる記録がありません。')
            for key, label, _ in options:
                ttk.Radiobutton(dialog, text=label, variable=choice, value=key,
                                state='normal' if counts[key] else 'disabled').pack(anchor='w', padx=24, pady=2)
            buttons = ttk.Frame(dialog)
            buttons.pack(fill='x', padx=20, pady=(14, 18))
            selected = {}

            def pick():
                selected['key'] = choice.get()
                dialog.destroy()
            ttk.Button(buttons, text='削除へ進む', style='Danger.TButton', command=pick).pack(side='left')
            ttk.Button(buttons, text='キャンセル', style='Accent.TButton', command=dialog.destroy).pack(side='left', padx=8)
            root.wait_window(dialog)
            key = selected.get('key')
            if not key or not counts.get(key):
                return
            _, label, scope = next(option for option in options if option[0] == key)
            confirmed = messagebox.askyesno(
                '削除の確認',
                f'{label.split("：", 1)[1]}\nの記録を削除します。\n\n'
                '誤って消した場合は、すぐ後なら「直前の保存を取り消す」で元に戻せます。\n'
                '本当に削除しますか？',
                icon='warning', default='no', parent=root)
            if not confirmed:
                return
            db = Store(DATA_DIR / 'database.sqlite3')
            try:
                deleted = delete_records(db, DATA_DIR, target, scope['location'], scope['machine'])
                history_report(db, ROOT / 'reports')
            finally:
                db.close()
            refresh_days()
            refresh_machines()
            logbox.insert('end', f'{label.split("：", 1)[1].rsplit("（", 1)[0]}｜{deleted}台の記録を削除しました。'
                                 '（「直前の保存を取り消す」で元に戻せます）\n')
            logbox.see('end')
        except Exception as exc:
            messagebox.showerror('削除できません', str(exc), parent=root)

    def edit_confirmed_setting():
        """Record a manually verified setting note for one selected rack.

        The note has no path into core.score; it is deliberately metadata only.
        """
        if pscube_only('設定情報を記録'):
            return
        try:
            refresh_days()
            refresh_machines()
            location, name, target = values()
            db = Store(DATA_DIR / 'database.sqlite3')
            try:
                rows = db.rows(target, name, location)
                if not rows:
                    raise ValueError('この店舗・日付・機種には記録がありません。')
                by_rack = {int(row['rack']): row for row in rows}
                rack = simpledialog.askinteger(
                    '設定情報を記録',
                    f'{STORE_NAMES[location]}\n{target}\n{name}\n\n設定情報を記録する台番号を入力してください。\n'
                    f'保存済み：{", ".join(map(str, sorted(by_rack)))}',
                    parent=root, minvalue=1, maxvalue=9999)
                if rack is None:
                    return
                row = by_rack.get(rack)
                if row is None:
                    raise ValueError(f'{rack}番台はこの条件では保存されていません。')

                dialog = tk.Toplevel(root)
                dialog.title('設定情報を記録')
                dialog.transient(root)
                dialog.grab_set()
                dialog.resizable(False, False)
                choice = tk.StringVar(value=row.get('confirmed_setting', ''))
                ttk.Label(dialog, text=f'{name}　{rack}番台', style='H2.TLabel').pack(
                    anchor='w', padx=20, pady=(18, 4))
                ttk.Label(dialog, text='確定・根拠ありの情報だけを手入力で残します。\n採点には影響しません。',
                          style='Sub.TLabel').pack(anchor='w', padx=20, pady=(0, 10))
                for value, label in [('', '未入力（解除）'), *[(v, v) for v in CONFIRMED_SETTING_OPTIONS]]:
                    ttk.Radiobutton(dialog, text=label, variable=choice, value=value).pack(
                        anchor='w', padx=24, pady=2)
                buttons = ttk.Frame(dialog)
                buttons.pack(fill='x', padx=20, pady=(14, 18))
                selected = {}
                def save_choice():
                    selected['value'] = choice.get() or None
                    dialog.destroy()
                ttk.Button(buttons, text='保存', style='Accent.TButton', command=save_choice).pack(side='left')
                ttk.Button(buttons, text='キャンセル', command=dialog.destroy).pack(side='left', padx=8)
                root.wait_window(dialog)
                if 'value' not in selected:
                    return
                db.set_confirmed_setting(location, target, name, rack, selected['value'])
                history_report(db, ROOT / 'reports')
                auto_backup(db, DATA_DIR)
            finally:
                db.close()
            make_report(location, name, target)
            setting_text = selected['value'] or '未入力に戻しました'
            logbox.insert('end', f'{target}｜{name}｜{rack}番台｜設定情報：{setting_text}\n')
            logbox.see('end')
        except Exception as exc:
            messagebox.showerror('設定情報を保存できません', str(exc), parent=root)

    ttk.Button(results_buttons, text='この日のまとめ（両店舗）', command=open_summary).pack(side='left')
    ttk.Button(results_buttons, text='選んだ機種の結果を開く', command=open_result).pack(side='left', padx=8)
    ttk.Button(results_buttons, text='過去の記録を見る', command=open_history).pack(side='left')
    ttk.Button(results_buttons, text='台記録を削除', style='Danger.TButton', command=delete_record).pack(side='left', padx=8)
    ttk.Button(results_buttons, text='まとめて削除…', style='Danger.TButton', command=delete_group).pack(side='left')
    ttk.Button(results_buttons, text='設定情報を記録', command=edit_confirmed_setting).pack(side='left', padx=8)

    def undo_last():
        if not messagebox.askyesno('直前の保存を取り消す',
                                   '直前の保存（表または1台のグラフ）またはまとめて削除を、その前の状態に戻します。よろしいですか？', parent=root):
            return
        db = Store(DATA_DIR / 'database.sqlite3')
        try:
            label = undo_last_save(db, DATA_DIR)
            history_report(db, ROOT / 'reports')
        except ValueError as exc:
            messagebox.showinfo('取り消せません', str(exc), parent=root)
            return
        finally:
            db.close()
        refresh_days()
        refresh_machines()
        logbox.insert('end', f'取り消しました：{label}\n')
        logbox.see('end')

    ttk.Button(results_buttons, text='直前の保存を取り消す', command=undo_last).pack(side='left')

    root.after(400, auto_sync_on_start)
    def close_app():
        try:
            flush_rainbow()   # 未反映の🌈があれば、閉じる前にまとめて反映
        except Exception as exc:  # noqa: BLE001 - 反映できなくても閉じられるように（記録は保存済み）
            print(f'🌈の反映に失敗しました：{exc}')
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close_app)
    root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-local':
        from runtime_smoke import run
        run(sys.modules[__name__], 'main', sys.argv[2])
    else:
        main()
