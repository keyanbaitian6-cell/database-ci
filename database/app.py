from datetime import date, datetime
from pathlib import Path
import base64
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import tkinter.font as tkfont
import error_log
import input_versions
import power
import pscube_import
from event_calendar import PscubeEvents, open_event_calendar
from event_history import open_event_history as show_event_history
from machine_list import build_machine_list_tab
from variety_rainbow import build_variety_tab
from output_worker import OutputWorker, refresh_outputs
from backup_status_ui import BackupStatusPanel

from core import (CONFIRMED_SETTING_OPTIONS, DATE_EVENT_OPTIONS, STORE_NAMES, Store, auto_backup, delete_records, export_backup, history_report, snapshot_store, import_backup, normalize_machine_name,
                  latest_backup_file, list_snapshots, load_settings, new_backup_files, report, resolve_sync_dir, restore_backup, save_settings, write_sync_mark,
                  summary_report, undo_last_save, pull_shared_events, pull_shared_rainbow, pull_shared_history)

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
# 同期フォルダの知らせ（画面上の帯）を出し直す間隔。
SYNC_BANNER_INTERVAL_MS = 30000
PSCUBE_VIEWER_URL = 'https://keyanbaitian6-cell.github.io/database-viewer/pscube/'
# 起動中に同期フォルダのAndroidのP’s CUBEを確かめる間隔（poll_pscube_from_sync）。最初は起動の15秒後。
PSCUBE_SYNC_FIRST_MS = 15_000
PSCUBE_SYNC_POLL_MS = 120_000
# Kept only for the Chrome-extension filename format they still describe;
# no PC-side UI decodes these anymore (see AI_COLLABORATION.md).
GRAPH_DOWNLOAD_RE = re.compile(
    r'database-graph-rack-(\d+)-(\d{4}-\d{2}-\d{2})(?:~s(nagamachiminami|saiwaichou))?(?:~m([A-Za-z0-9_-]+)~)?-.+\.png')
LIST_DOWNLOAD_RE = re.compile(
    r'database-list-(\d{4}-\d{2}-\d{2})(?:~s(nagamachiminami|saiwaichou))?(?:~m([A-Za-z0-9_-]+)~)?-.+\.png')


# HTML変換アプリ（html_converter）の補完用JSONの保存先。保存から3時間は「バックアップを読み込む」がここを開く
# （2026-11-06。それ以外のときは今までどおり Windows が覚えている場所）。
CONVERTER_JSON_DIR = Path(__file__).resolve().parent.parent / 'html_converter' / 'data' / 'backup_json'
CONVERTER_RECENT_SECONDS = 3 * 3600


def recent_converter_folder(folder=None, now=None):
    folder = Path(folder or CONVERTER_JSON_DIR)
    now = datetime.now().timestamp() if now is None else now
    try:
        recent = any(now - f.stat().st_mtime <= CONVERTER_RECENT_SECONDS for f in folder.glob('*.json'))
    except OSError:
        return {}
    return {'initialdir': str(folder)} if recent else {}


def anaslo_converter_command():
    """アナスロのHTML変換アプリ（html_converter/）を別の窓で開くコマンドと作業フォルダ（2026-11-06 利用者
    「databaseにアナスロ取り込みのやつって組み込める？」→ 案1「PC版にボタン」）。画面・操作は変換アプリのまま。
    P-STATION は保存先の初期値が同期フォルダで、起動中のPC版が数分おきに自動で読み込む（pscube_import.ANDROID_SYNC_NAME）。"""
    if getattr(sys, 'frozen', False):
        raise OSError('配布版（EXE）からは開けません。html_converter/start.cmd から開いてください。')
    app_path = Path(__file__).resolve().parent.parent / 'html_converter' / 'app.py'
    if not app_path.is_file():
        raise OSError('html_converter/app.py が見つかりません。')
    return [sys.executable, str(app_path)], app_path.parent


def site777_browser_command():
    """サイトセブン（スマホ会員）をAndroidとして開くブラウザ（site777_browser.py）を別の窓で開くコマンド
    （2026-11-07 利用者「PC版でandroidユーザーとしてブラウザを開いてログインをしたい」）。"""
    if getattr(sys, 'frozen', False):
        raise OSError('配布版（EXE）からは開けません。database/start.cmd から開いてください。')
    here = Path(__file__).resolve().parent
    return [sys.executable, str(here / 'site777_browser.py'), str(here / 'data')], here


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
    # Collect old Tk interpreters on their owner thread before starting workers
    # (also relevant when an embedded caller opens and closes this UI repeatedly).
    import gc
    gc.collect()
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
    # 同期フォルダの知らせ（2026-11-03 利用者「ドライブレター変わってるのに気づかず取り込み終えてしまった」）。
    # 書き出せていない間は赤、別のドライブ文字へ切り替えたときは黄色。中身は下の refresh_sync_banner。
    sync_banner = tk.Frame(frame, padx=12, pady=8)
    sync_banner_text = tk.StringVar()
    tk.Label(sync_banner, textvariable=sync_banner_text, justify='left', anchor='w', wraplength=640,
             font=('Yu Gothic UI', 10, 'bold')).pack(side='left', fill='x', expand=True)
    sync_banner_button = ttk.Button(sync_banner)
    sync_banner_button.pack(side='right')
    notebook = ttk.Notebook(frame)
    notebook.pack(fill='both', expand=True)
    tab_home = ttk.Frame(notebook, padding=22)
    tab_results = ttk.Frame(notebook, padding=22)
    # 同期タブは縦にスクロールできるようにする。共有用ファイルの状況パネルが増え、窓の高さが足りないと
    # 下の「バックアップを読み込む」が窓の外に隠れて押せなかった（2026-10-25 利用者報告）。
    sync_page = ttk.Frame(notebook)
    sync_canvas = tk.Canvas(sync_page, highlightthickness=0, borderwidth=0,
                            background=ttk.Style().lookup('TFrame', 'background') or None)
    sync_bar = ttk.Scrollbar(sync_page, orient='vertical', command=sync_canvas.yview)
    tab_sync = ttk.Frame(sync_canvas, padding=22)
    sync_window = sync_canvas.create_window((0, 0), window=tab_sync, anchor='nw')
    sync_canvas.configure(yscrollcommand=sync_bar.set)
    sync_canvas.pack(side='left', fill='both', expand=True)
    sync_bar.pack(side='right', fill='y')
    tab_sync.bind('<Configure>', lambda _e: sync_canvas.configure(scrollregion=sync_canvas.bbox('all')))
    sync_canvas.bind('<Configure>', lambda e: sync_canvas.itemconfigure(sync_window, width=e.width))

    def scroll_sync(event):
        if sync_canvas.yview() != (0.0, 1.0):
            sync_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
    # ホイールはこのタブの上にあるときだけ受け取る（記録欄など他の部分のスクロールを奪わない）。
    sync_page.bind('<Enter>', lambda _e: sync_canvas.bind_all('<MouseWheel>', scroll_sync))
    sync_page.bind('<Leave>', lambda _e: sync_canvas.unbind_all('<MouseWheel>'))
    # バラエティの🌈（確定が出た台の印、RAINBOW.md「バラエティのタブ」、2026-10-11）。
    tab_variety = ttk.Frame(notebook, padding=22)
    # 機種一覧（machine_list.py、2026-11-01 利用者「今バラエティを表示しているような作りで見たい」）。
    # 「結果を見る」（ブラウザで開くHTML）は「ブラウザでHTML開くことはないから端っこにおいておいて」で右端へ。
    tab_machines = ttk.Frame(notebook, padding=22)
    notebook.add(tab_home, text='  取り込み  ')
    notebook.add(tab_machines, text='  機種一覧  ')
    notebook.add(tab_variety, text='  バラエティ🌈  ')
    notebook.add(sync_page, text='  バックアップ・同期  ')
    notebook.add(tab_results, text='  結果を見る  ')

    # 🌈：押したときは記録への保存だけ（速い）。閲覧・共有ページ用のファイルとバックアップの作り直し（5秒ほど）は、
    # まとめて1回（2026-10-12 利用者「一個押すたびに保存処理をしているようで数秒かかってしまう。…まとめてつけてから
    # 保存処理してほしい」）：バラエティ🌈の「閲覧・共有ページに反映」ボタン、バラエティ🌈のタブを離れるとき、
    # カレンダーを閉じるとき、PC版を閉じるとき。「過去の記録」の作り直し（10秒ほど）は🌈のときはしない。
    # 閉じる途中は「過去の記録」（PC内のページ、開くときに作り直す）を作らず、バックアップだけ待つ（2026-10-17）。
    output_worker = OutputWorker(lambda **options: refresh_outputs(
        DATA_DIR / 'database.sqlite3', DATA_DIR, ROOT / 'reports', cancelled=lambda: output_worker.closing, **options))
    output_poll = [None]
    closing = [False]

    def poll_outputs():
        output_poll[0] = None
        for result in output_worker.poll():
            if result.error:
                tell(f'記録はPCに保存済みですが、レポート・バックアップの更新に失敗しました：{result.error}\n')
            else:
                timings = '、'.join(f'{name} {seconds:.2f}秒' for name, seconds in result.value['timings'].items())
                tell(f'出力更新が完了しました（{timings}）。\n')
                for notice in result.value.get('notices', []):
                    tell(notice + '\n')
            for callback in result.callbacks:
                try:
                    callback(result)
                except Exception as error:
                    tell(f'出力後の画面更新に失敗しました：{error}\n')
        if closing[0] and output_worker.finished:
            root.destroy()
        elif output_worker.thread is not None and output_worker.thread.is_alive():
            output_poll[0] = root.after(50, poll_outputs)

    def schedule_outputs(*, history=False, backup=False, pscube=False, done=None):
        output_worker.request(history=history, backup=backup, pscube=pscube, done=done)
        if output_poll[0] is None:
            output_poll[0] = root.after(50, poll_outputs)

    rainbow_pending = [0]
    pending_text = tk.StringVar(value='反映済み')

    def show_pending():
        pending_text.set(f'閲覧・共有ページに反映（{rainbow_pending[0]}件）' if rainbow_pending[0] else '反映済み')

    def mark_rainbow():
        rainbow_pending[0] += 1
        show_pending()

    rainbow_inflight = [False]

    def flush_rainbow():
        if not rainbow_pending[0] or rainbow_inflight[0]:
            return
        count = rainbow_pending[0]
        rainbow_inflight[0] = True
        pending_text.set('反映中…')
        def complete(result):
            rainbow_inflight[0] = False
            if result.error:
                pending_text.set('反映に失敗（印はPCに保存済み）')
                return
            if result.value.get('notices'):
                pending_text.set('PC内に保存済み（同期フォルダ未設定）')
                return
            rainbow_pending[0] = max(0, rainbow_pending[0] - count)
            tell(f'🌈の付け外し{count}件を、閲覧・共有ページ用のファイルとバックアップに反映しました。\n')
            if result.value['pending_marks']:
                tell('未取り込み日の印はPCとバックアップに保存しています。Webへの反映は数値の取り込み後です。\n')
            show_pending()
        schedule_outputs(backup=True, done=complete)
    refresh_variety = None
    refresh_machine_list = None
    # タブを開いたときに読み直す（取り込みで新しい日・入れ替えが入っていれば一覧が変わる）。離れるときは🌈をまとめて反映。
    current_tab = [None]

    def open_variety(_event=None):
        nonlocal refresh_variety, refresh_machine_list
        selected = notebook.select()
        rainbow_tabs = (str(tab_variety), str(tab_machines))
        if current_tab[0] in rainbow_tabs and selected != current_tab[0]:
            flush_rainbow()
        current_tab[0] = selected
        if selected == str(tab_variety):
            pull_shared_rainbow_now()   # iPhoneで付けた🌈も入れてから読み直す
            if refresh_variety is None:
                refresh_variety = build_variety_tab(tab_variety, DATA_DIR / 'database.sqlite3', mark_rainbow,
                                                    on_flush=flush_rainbow, pending=pending_text, defer_load=True)
            refresh_variety()
        if selected == str(tab_machines):
            pull_shared_rainbow_now()
            if refresh_machine_list is None:
                refresh_machine_list = build_machine_list_tab(
                    tab_machines, DATA_DIR / 'database.sqlite3', mark_rainbow, on_flush=flush_rainbow,
                    pending=pending_text, defer_load=True, pscube=(DATA_DIR / 'pscube.sqlite3', PSCUBE_LABEL))
            refresh_machine_list()
    notebook.bind('<<NotebookTabChanged>>', open_variety, add='+')

    ttk.Label(tab_results, text='見たい台を選ぶ', style='H2.TLabel').pack(anchor='w')
    ttk.Label(tab_results, text='保存済みの店舗・日付・機種だけ選べます。', style='Sub.TLabel').pack(anchor='w', pady=(0, 10))
    ttk.Button(tab_results, text='長町南のイベント履歴', style='Link.TButton',
               command=lambda: open_event_history_page()).pack(anchor='w', pady=(0, 8))
    ttk.Button(tab_results, text='幸町のバラエティ履歴', style='Link.TButton',
               command=lambda: open_event_history_page('saiwaichou')).pack(anchor='w', pady=(0, 8))
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

    def open_local_pscube(target, selected_machine=None):
        from pscube_report import build_report
        try:
            output = build_report(DATA_DIR / 'pscube.sqlite3', ROOT / 'reports', target, selected_machine)
            os.startfile(output)
        except (ValueError, OSError) as exc:
            messagebox.showinfo('P’s CUBEの保存データを開けません', str(exc), parent=root)

    def external_pscube_selected():
        from pscube_report import has_external_day
        return has_external_day(DATA_DIR / 'pscube.sqlite3', day.get().strip())

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
        folder = resolve_sync_dir(DATA_DIR)
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
        folder = resolve_sync_dir(DATA_DIR)
        if not folder:
            return 0
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            changed = pull_shared_rainbow(db, folder)
            if changed:
                schedule_outputs(backup=True)
                schedule_outputs(history=True)
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
                schedule_outputs(pscube=True)
            except ValueError as error:
                messagebox.showwarning('イベント名', str(error), parent=root)
            finally:
                store.close()
            refresh_event()
            return
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            db.set_date_event(location, selected_day, None if selected == 'イベントなし' else selected)
            schedule_outputs(backup=True)
            schedule_outputs(history=True)
        finally:
            db.close()
        refresh_event()

    def open_events_calendar():
        def changed(db):
            schedule_outputs(backup=True)
            schedule_outputs(history=True)
            root.after(0, refresh_event)

        def pscube_changed(store):
            # 閲覧ページ（Googleドライブ経由）とバックアップにも反映する（イベント欄と同じ）。
            schedule_outputs(pscube=True)
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
    ttk.Label(tab_home, text='ふだんの取り込みは、ここから始めます。', style='Sub.TLabel').pack(anchor='w', pady=(0, 10))
    # 取り込みのボタンは2列×2段（2026-11-07 利用者「縦に取り込みが四つならんで見切れちゃう項目あった」）。
    # 上の段はふだんの取り込み（メルヘン・P’s CUBE）、下の段は補う取り込み（サイトセブン・アナスロ）。
    imports = ttk.Frame(tab_home)
    imports.pack(anchor='w', fill='x')
    GradientButton(imports, text='メルヘンワールドを取り込む',
                   command=lambda: open_browser_import()).grid(row=0, column=0, sticky='w')
    ttk.Button(imports, text='P’s CUBE（スロット）を取り込む',
               command=lambda: open_pscube_import()).grid(row=0, column=1, sticky='ew', ipadx=22, ipady=9, padx=(14, 0))
    ttk.Button(imports, text='サイトセブンを開く（スマホ会員）',
               command=lambda: open_site777_browser()).grid(row=1, column=0, sticky='ew', ipadx=22, ipady=9, pady=(9, 0))
    ttk.Button(imports, text='アナスロから補う（P-STATION・幸町）',
               command=lambda: open_anaslo_converter()).grid(row=1, column=1, sticky='ew', ipadx=22, ipady=9,
                                                             padx=(14, 0), pady=(9, 0))
    # よく使うボタン（まとめ・記録・取り消し・パチンコ）を取り込みのすぐ下に。窓が小さいときに見切れても困らない
    # 説明の文は一番下（2026-11-07、最小の窓の大きさでまとめ・パチンコの段が隠れていた）。
    ttk.Separator(tab_home).pack(fill='x', pady=(12, 10))
    quick = ttk.Frame(tab_home)
    quick.pack(anchor='w')
    ttk.Button(quick, text='この日のまとめ', command=lambda: open_summary()).pack(side='left')
    ttk.Button(quick, text='過去の記録を見る', command=lambda: open_history()).pack(side='left', padx=8)
    ttk.Button(quick, text='直前の保存を取り消す', command=lambda: undo_last()).pack(side='left')
    # パチンコの記録のボタンも同じ段に（2026-11-07、ホームの高さを詰めるため）。下の段は取り込む末尾だけ。
    ttk.Button(quick, text='パチンコの記録', command=lambda: open_pachinko()).pack(side='left', padx=(8, 0))
    # 4円パチンコ（PC版だけ、PACHINKO.md）：記録のページと、取り込む末尾（2026-10-12 利用者「取り込む末尾を毎月
    # 変えたいから取り込む末尾選択ボタンが欲しい」。月に合わせる＝10月→0、11月→1）。
    pachi = ttk.Frame(tab_home)
    pachi.pack(anchor='w', pady=(8, 0))
    ttk.Label(pachi, text='パチンコで取り込む末尾（スロットには関係なし）', style='Sub.TLabel').pack(side='left', padx=(0, 6))
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
    ttk.Label(tab_home, style='Sub.TLabel', justify='left', text=(
        'メルヘンワールドの取り込み\n'
        '① 機種一覧・機種別の表・個別台グラフで「この画面を取り込む」\n'
        '② 表は表、グラフはグラフとして保存され、次の必要な台へ移動\n'
        '③ 機種が終わると、機種一覧へ自動で移動')).pack(anchor='w', pady=(16, 0))

    sync_box = ttk.LabelFrame(tab_sync, text='同期フォルダ（Google Driveなど）', padding=14)
    sync_box.pack(fill='x', pady=(0, 14))
    sync_dir = tk.StringVar(value=settings.get('sync_dir') or '未設定')
    ttk.Label(sync_box, style='Sub.TLabel', wraplength=680, text=(
        '保存済みの記録から、共有用ファイルとバックアップをこのフォルダへ書き出します。'
        'メルヘンの取り込み画面で保存した分は、その画面を閉じたあとに自動で書き出します。'
        'Googleドライブへのアップロードは、Drive側の同期状況も確認してください。')).pack(anchor='w', pady=(0, 8))
    ttk.Label(sync_box, textvariable=sync_dir).pack(anchor='w')

    def reexport_shared():
        if closing[0]:
            return
        folder = resolve_sync_dir(DATA_DIR)
        if not folder or not Path(folder).is_dir():
            shared_status.refresh()
            messagebox.showinfo('書き出し先を確認してください',
                                '「同期フォルダを指定」で保存先を選んでください。'
                                'ドライブが見つからないときは、接続の復旧後にもう一度更新できます。', parent=root)
            return
        meruhen = (DATA_DIR / 'database.sqlite3').is_file()
        pscube = (DATA_DIR / 'pscube.sqlite3').is_file()
        if not meruhen and not pscube:
            messagebox.showinfo('保存済みの記録がありません', 'PC内に書き出せる記録ファイルがありません。', parent=root)
            return
        shared_status.set_busy(True)
        tell('共有用ファイルの更新を受け付けました。書き出し完了までお待ちください。\n')
        def completed(result):
            shared_status.set_busy(False)
        try:
            schedule_outputs(backup=meruhen, pscube=pscube, done=completed)
        except Exception:
            shared_status.set_busy(False)
            raise

    shared_status = BackupStatusPanel(sync_box, DATA_DIR,
                                     lambda: resolve_sync_dir(DATA_DIR), reexport_shared)
    shared_status.pack(fill='x', pady=(6, 0))

    banner_state = {'warned': set(), 'retried': set()}

    def refresh_sync_banner():
        """同期フォルダの知らせを出し直す（30秒おき）。書き出せていない間は赤い帯と、1回だけ知らせの窓。
        ドライブが戻った・別のドライブ文字で見つかったら（core.resolve_sync_dir）、止まっていた書き出しを1回やり直す。"""
        if closing[0]:
            return
        try:
            from backup_status import read_status
            failed = [s for s in (read_status(DATA_DIR, name) for name in ('meruhen', 'pscube'))
                      if s.get('state') == 'unavailable' and s.get('folder')]
            folder = resolve_sync_dir(DATA_DIR) if failed else None
            moved = load_settings(DATA_DIR).get('sync_moved')
            if moved:
                sync_dir.set(moved.get('new') or sync_dir.get())
            if failed and folder and Path(folder).is_dir():
                key = tuple(s.get('at') for s in failed)
                if key not in banner_state['retried']:
                    banner_state['retried'].add(key)
                    tell(f'同期フォルダ（{folder}）が見つかったので、止まっていた共有用ファイルの書き出しをやり直します。\n')
                    reexport_shared()
            if failed:
                when = max(str(s.get('at', ''))[:16].replace('T', ' ') for s in failed)
                sync_banner.configure(background='#FDE2E1')
                sync_banner_text.set(f'Googleドライブの同期フォルダ（{failed[0]["folder"]}）が見つからず、{when} の書き出しが'
                                     'ドライブへ届いていません。取り込んだ記録はPCに残っています。ドライブの接続を確かめて'
                                     '「共有用ファイルを更新」を押してください（ドライブが戻れば自動でもやり直します）。')
                sync_banner_button.configure(text='共有用ファイルを更新', command=reexport_shared)
                key = tuple(s.get('at') for s in failed)
                if key not in banner_state['warned']:
                    banner_state['warned'].add(key)
                    root.after(100, lambda: messagebox.showwarning(
                        '同期フォルダが見つかりません', sync_banner_text.get(), parent=root))
            elif moved:
                sync_banner.configure(background='#FFF4DC')
                sync_banner_text.set(f'同期フォルダが {moved.get("old")} に無かったので、目印の一致する {moved.get("new")} に'
                                     '切り替えて書き出しています（Googleドライブのドライブ文字が変わったため）。')

                def dismiss():
                    save_settings(DATA_DIR, sync_moved=None)
                    refresh_sync_banner()
                sync_banner_button.configure(text='わかった', command=dismiss)
            if failed or moved:
                for child in sync_banner.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(background=sync_banner.cget('background'))
                if not sync_banner.winfo_ismapped():
                    sync_banner.pack(fill='x', pady=(0, 10), before=notebook)
            else:
                sync_banner.pack_forget()
        except Exception as error:   # 知らせの不具合で本体を止めない
            error_log.record(DATA_DIR, 'sync_banner', error)

    def sync_banner_loop():
        refresh_sync_banner()
        if not closing[0]:
            root.after(SYNC_BANNER_INTERVAL_MS, sync_banner_loop)
    root.after(3000, sync_banner_loop)
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

    def watch_capture_window(process, label, take_message, after_auto=None, take_stop=None):
        """自動取り込みが全部終わると取り込み窓は自分で閉じる（2026-10-30、サイトへの接続を止めるため）。
        窓のプロセスが終わったら、その結果をログ欄に出す。自動で閉じたとき（結果の文がある）は after_auto も呼ぶ。"""
        def check():
            if process.poll() is None:
                root.after(2000, check)
                return
            try:
                message = take_message()
            except Exception:  # noqa: BLE001 - the notice is only a convenience
                message = None
            stop = None
            if not message and take_stop is not None:
                # 途中で止まって閉じたとき、最後に止まった時刻と理由を出す（2026-11-08、サイトセブン）。
                try:
                    stop = take_stop()
                except Exception:  # noqa: BLE001 - the notice is only a convenience
                    stop = None
            logbox.insert('end', f'{label}：{message}。取り込み画面を閉じ、サイトへの接続を止めました。\n' if message
                          else f'{label}の取り込み画面を閉じました。最後の停止：{stop}\n' if stop
                          else f'{label}の取り込み画面を閉じました。\n')
            logbox.see('end')
            if message and after_auto is not None:
                after_auto(message)

        root.after(2000, check)

    def sleep_after_pscube(message, since):
        """P’s CUBEの自動取り込みが終わって窓が自分で閉じたら、結果を確かめて記録し、5分後にPCをスリープする
        （2026-11-06 利用者「取り込み後問題なかったか確認し、5分後にスリーブ」、power.py）。5分の間は取り消せる。"""
        try:
            problems = pscube_import.capture_problems(DATA_DIR, message, since)
        except Exception as error:  # noqa: BLE001 - 確認に失敗してもスリープの案内は出す
            problems = [f'確認できませんでした：{error}']
        result = '問題なし' if not problems else '気になる点 ' + ' / '.join(problems)
        error_log.note(DATA_DIR, 'pscube.after_check', result)
        logbox.insert('end', f'P’s CUBE 取り込み後の確認：{result}\n')
        logbox.see('end')
        dialog = tk.Toplevel(root)
        dialog.title('5分後にスリープします')
        dialog.attributes('-topmost', True)
        text = tk.StringVar()
        ttk.Label(dialog, text=f'P’s CUBE の自動取り込みが終わりました。\n確認：{result}', wraplength=420,
                  justify='left').pack(padx=16, pady=(14, 6), anchor='w')
        ttk.Label(dialog, textvariable=text).pack(padx=16, pady=6, anchor='w')
        left = [power.SLEEP_DELAY_SECONDS]
        cancelled = [False]

        def cancel():
            cancelled[0] = True
            logbox.insert('end', 'スリープを取り消しました。\n')
            logbox.see('end')
            dialog.destroy()

        ttk.Button(dialog, text='スリープを取り消す', command=cancel).pack(padx=16, pady=(6, 14))
        dialog.protocol('WM_DELETE_WINDOW', cancel)

        def count():
            if cancelled[0]:
                return
            if left[0] <= 0:
                dialog.destroy()
                logbox.insert('end', 'PCをスリープにします。\n')
                logbox.see('end')
                error_log.note(DATA_DIR, 'pscube.after_sleep', 'スリープ' + ('しました' if power.sleep_now() else 'できませんでした'))
                return
            text.set(f'あと {left[0] // 60}分{left[0] % 60:02d}秒でPCをスリープにします。')
            left[0] -= 1
            root.after(1000, count)

        count()

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
            process = subprocess.Popen(
                command,
                cwd=str(ROOT))
            logbox.insert(
                'end',
                'ブラウザ取り込みを別ウィンドウで開始しました。'
                '保存後は「過去の記録を見る」で確認できます。\n')
            logbox.see('end')
        except OSError as exc:
            messagebox.showerror('起動できません', f'ブラウザ取り込みを開始できません：{exc}', parent=root)
            return

        def meruhen_message():
            import browser_import
            return browser_import.take_finished_message(DATA_DIR)

        watch_capture_window(process, 'メルヘン', meruhen_message)

    anaslo_process = [None]

    def open_anaslo_converter():
        running = anaslo_process[0]
        if running is not None and running.poll() is None:
            messagebox.showinfo('開いています', 'アナスロの取り込みの画面は開いています。タスクバーから選んでください。', parent=root)
            return
        try:
            command, folder = anaslo_converter_command()
            anaslo_process[0] = subprocess.Popen(command, cwd=str(folder))
        except OSError as exc:
            messagebox.showerror('起動できません', f'アナスロの取り込みを開けません：{exc}', parent=root)
            return
        logbox.insert('end', 'アナスロの取り込み画面を開きました。P-STATIONは同期フォルダに保存すると、'
                      'この画面が数分以内に自動で読み込みます（幸町は保存後に「バックアップを読み込む」）。\n')
        logbox.see('end')

    site777_process = [None]

    def open_site777_browser():
        running = site777_process[0]
        if running is not None and running.poll() is None:
            messagebox.showinfo('開いています', 'サイトセブンの窓は開いています。タスクバーから選んでください。', parent=root)
            return
        try:
            command, folder = site777_browser_command()
            site777_process[0] = subprocess.Popen(command, cwd=str(folder))
        except OSError as exc:
            messagebox.showerror('起動できません', f'サイトセブンを開けません：{exc}', parent=root)
            return
        # 自動取り込みが最後まで終わると窓は自分で閉じる（2026-11-07）。閉じたら結果をログ欄に出す（P’s CUBEと同じ）。
        import site777_browser
        watch_capture_window(site777_process[0], 'サイトセブン', lambda: site777_browser.take_finished_message(DATA_DIR),
                             take_stop=lambda: site777_browser.take_stop_message(DATA_DIR))
        logbox.insert('end', 'サイトセブンをスマホとして、クレジットカード会員のログイン画面から開きました。'
                      'ログインしたら、P-STATIONの20スロを表示し、取り込みカードの日付（から・まで）を確認して開始してください。\n')
        logbox.see('end')

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
            since = datetime.now().astimezone().isoformat(timespec='seconds')
            process = subprocess.Popen(command, cwd=str(ROOT))
            logbox.insert('end', 'P’s CUBE の取り込み画面を開きました。\n')
            logbox.see('end')
        except OSError as exc:
            messagebox.showerror('起動できません', f'P’s CUBEを開始できません：{exc}', parent=root)
            return
        watch_capture_window(process, 'P’s CUBE', lambda: pscube_import.take_finished_message(DATA_DIR),
                             after_auto=lambda message: sleep_after_pscube(message, since))

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
            schedule_outputs(history=True)
        finally:
            db.close()
        done = sum(row['score']['total'] is not None for row in results)
        logbox.insert('end', f'結果を更新しました：{len(results)}台中、総合点確定{done}台。\n{output}\n')
        logbox.see('end')
        return output

    def export_pscube_file():
        name = pscube_import.backup_file_name()
        folder = resolve_sync_dir(DATA_DIR)
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
        folder = resolve_sync_dir(DATA_DIR)
        if folder and Path(folder).is_dir():
            path = str(Path(folder) / default_name)
        else:
            path = filedialog.asksaveasfilename(
                title='バックアップの保存先を選択（Google Driveのフォルダなど）',
                initialfile=default_name, defaultextension='.json',
                filetypes=[('JSON', '*.json'), ('すべて', '*.*')])
        if not path:
            return
        # 同じ時点の写しから書く。書き出し中に取り込み窓などが台を消しても、台も削除印も無いファイルにしない（2026-11-01）。
        with snapshot_store(ROOT / 'data' / 'database.sqlite3') as db:
            count = export_backup(db, path, location=location, day=day)
        scope_bits = [STORE_NAMES[location] if location else '全店舗', day if day else '全期間']
        target_text = '・'.join(scope_bits)
        logbox.insert('end', f'バックアップを書き出しました（{target_text}）：{count}件 → {path}\n')
        logbox.see('end')
        messagebox.showinfo('書き出しました', f'{target_text}の{count}件のデータを書き出しました。\n{path}', parent=root)

    def import_backup_file(path=None, quiet=False):
        """取り込めたら True。失敗・取り消しは False（自動取り込みは成功したファイルだけを覚える）。"""
        path = path or filedialog.askopenfilename(
            title='取り込むバックアップファイルを選択',
            filetypes=[('JSON', '*.json'), ('すべて', '*.*')], **recent_converter_folder())
        if not path:
            return False
        if pscube_import.is_pscube_backup(path):
            # P’s CUBEのファイルをメルヘンの読み込みに通すと、全台が「対象外」になって何も入らない。
            return import_pscube_file(path, quiet=quiet)
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            plan = import_backup(db, path)
            if plan['conflicts']:
                dialog = BackupConflictsDialog(root, plan['conflicts'])
                root.wait_window(dialog)
                if dialog.selected:
                    db.save(dialog.selected)
            schedule_outputs(history=True)
            schedule_outputs(backup=True)
        except Exception as exc:
            messagebox.showerror('取り込めません', str(exc), parent=root)
            return False
        finally:
            db.close()
        refresh_days()
        refresh_machines()
        applied = (len(plan['new']) + len(plan['graph_only']) + len(plan['link_only']) + len(plan.get('jo_only', []))
                   + len(plan['setting_only']) + plan.get('events_added', 0) + plan.get('rainbow_added', 0) + plan.get('history_added', 0))
        summary = (f'新規{len(plan["new"])}件、グラフ追加{len(plan["graph_only"])}件、リンク補完{len(plan["link_only"])}件、'
                   f'ジャグラーオンラインの差枚{len(plan.get("jo_only", []))}件を取り込みました。'
                   f'🌈・設定情報{len(plan["setting_only"])}件、未取り込み日の🌈{plan.get("rainbow_added", 0)}件。'
                   f'既に同じ内容{len(plan["unchanged"])}件、要確認{len(plan["conflicts"])}件、'
                   f'イベント反映{plan.get("events_added", 0)}件、イベント名不一致{plan.get("event_conflicts", 0)}件（入力時刻の無い同士は既存名を維持）、'
                   f'履歴反映{plan.get("history_added", 0)}件、不一致{plan.get("history_conflicts", 0)}件、'
                   f'週構成の不一致{plan.get("history_week_conflicts", 0)}件（取り込まず、既存を維持）、'
                   f'履歴の除外{plan.get("history_rejected", 0)}件。'
                   f'{plan.get("history_error", "")}'
                   f'対象外{len(plan["skipped"])}件。')
        logbox.insert('end', f'バックアップを読み込みました：{summary}\n')
        logbox.see('end')
        if quiet:
            return True
        if applied:
            messagebox.showinfo('読み込みました', summary, parent=root)
        else:
            messagebox.showinfo('反映なし', summary, parent=root)
        return True

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
        save_settings(DATA_DIR, sync_dir=folder, sync_moved=None)
        write_sync_mark(DATA_DIR, folder)
        sync_dir.set(folder)
        logbox.insert('end', f'同期フォルダを設定しました：{folder}\n')
        logbox.see('end')
        reexport_shared()

    def import_latest_from_sync():
        folder = resolve_sync_dir(DATA_DIR)
        if not folder or not Path(folder).is_dir():
            messagebox.showinfo('同期フォルダ未設定', '先に「同期フォルダを指定」してください。', parent=root)
            return
        latest = latest_backup_file(folder)
        if latest is None:
            messagebox.showinfo('見つかりません', 'このフォルダにバックアップファイルがありません。', parent=root)
            return
        logbox.insert('end', f'最新のバックアップ：{latest.name}\n')
        version = synced_version(latest)
        if import_backup_file(str(latest)) and version:
            save_settings(DATA_DIR, last_synced=version)

    def import_pscube_from_sync():
        """P’s CUBEの最新バックアップ（Android・ブラウザの書き出しなど）を専用の記録へ統合する。"""
        folder = resolve_sync_dir(DATA_DIR)
        if not folder or not Path(folder).is_dir():
            messagebox.showinfo('同期フォルダ未設定', '先に「同期フォルダを指定」してください。', parent=root)
            return
        latest = pscube_import.latest_pscube_backup(folder)
        if latest is None:
            messagebox.showinfo('見つかりません', 'このフォルダにP’s CUBEのバックアップ（pscube-backup-…）がありません。', parent=root)
            return
        import_pscube_file(latest)

    def import_pscube_file(latest, quiet=False, background=False):
        """P’s CUBEのバックアップ1つを専用の記録へ統合する（メルヘンの記録には混ぜない）。
        background：起動中の自動読み込み。ファイル内容の不正を区別して例外を返し、呼び出し側が記録・再試行する。"""
        latest = Path(latest)
        store = pscube_import.PscubeStore(DATA_DIR / 'pscube.sqlite3')
        try:
            source = latest
            if background:
                # 同じ内容を一度だけ読み、DBの読取・保存前の検証だけをファイル固有の失敗にする。
                try:
                    source = json.loads(latest.read_text(encoding='utf-8-sig'))
                    store.import_backup(source, _validate_only=True)
                except (ValueError, TypeError, KeyError) as exc:
                    raise pscube_import.InvalidAndroidSyncFile(str(exc)) from exc
            summary = store.import_backup(source)
            schedule_outputs(pscube=True)
        except Exception as exc:
            if background:
                raise
            messagebox.showerror('取り込めません', str(exc), parent=root)
            return False
        finally:
            store.close()
        text = (f'P’s CUBE：新規{summary["added"]}件、更新{summary["updated"]}件、同じ内容{summary["unchanged"]}件、'
                f'新しい自分の数値を維持{summary["kept_local"]}件（{latest.name}）。')
        logbox.insert('end', text + '\n')
        logbox.see('end')
        if current_location() == PSCUBE_KEY:
            refresh_days()
            refresh_machines()
        if not quiet:
            messagebox.showinfo('読み込みました', text, parent=root)
        return True

    def synced_version(latest):
        """取り込む前のファイルの名前・更新時刻。取り込み中にDriveが書き換えても、次回は新しい版として読む。"""
        try:
            return dict(name=latest.name, mtime=latest.stat().st_mtime)
        except OSError:
            return None

    def auto_sync_on_start():
        """Pick up a newer backup from the sync folder without any click.

        Only files newer than the last one already read are imported, and
        anything that conflicts still goes through the confirmation dialog.
        """
        current = load_settings(DATA_DIR)
        folder = resolve_sync_dir(DATA_DIR)
        if not current.get('auto_sync_on_start', True) or not folder or not Path(folder).is_dir():
            return
        seen = current.get('last_synced') or {}
        # 前回より新しいものを古い順にすべて読む（店舗ごとに分けた書き出しを取りこぼさない、2026-10-25）。
        for path in new_backup_files(folder, seen=seen):
            version = synced_version(path)
            if version is None or version == dict(name=seen.get('name'), mtime=seen.get('mtime')):
                continue
            logbox.insert('end', f'同期フォルダに新しいバックアップがあります：{path.name}\n')
            # 失敗したファイルは覚えず、後のファイルにも進まない（次の起動でそこからやり直す。
            # Driveの一時的な失敗・DBの使用中など）。
            if not import_backup_file(str(path), quiet=True):
                return
            save_settings(DATA_DIR, last_synced=version)

    pscube_sync_errors = {}

    def poll_pscube_from_sync():
        """起動中、同期フォルダに届いたAndroidのP’s CUBE（当日分・全期間）を数分おきに自動で読み込む（2026-10-26）。

        スマホで取り込んでDriveに上がった記録を、ボタンを押さずにPCへ入れる（翌日候補の比較の記録
        input_versions.py は、PCに入った時刻で残る）。読めたファイルは名前と更新時刻を覚え、同じ版は読み直さない。
        失敗したファイルは覚えず、次の確認でやり直す（同じ失敗は記録欄に1回だけ書く）。
        """
        try:
            current = load_settings(DATA_DIR)
            folder = resolve_sync_dir(DATA_DIR)
            if closing[0] or not folder or not Path(folder).is_dir():
                return
            files = pscube_import.android_sync_files(folder)
            seen = current.get('pscube_android_synced')
            due, initial = pscube_import.android_sync_due(files, seen, datetime.now().timestamp())
            if initial is not None:
                save_settings(DATA_DIR, pscube_android_synced=initial)
                seen = initial
            for name, mtime, path in due:
                try:
                    import_pscube_file(path, quiet=True, background=True)
                except Exception as exc:  # noqa: BLE001 - 次の確認でやり直す
                    invalid = isinstance(exc, pscube_import.InvalidAndroidSyncFile)
                    action = 'このファイルを保留して後のファイルを読みます。次の確認で再試行します' if invalid else '次の確認でやり直します'
                    message = f'P’s CUBEの自動読み込みに失敗しました（{name}、{action}）：{exc}'
                    if pscube_sync_errors.get(name) != message:
                        pscube_sync_errors[name] = message
                        logbox.insert('end', message + '\n')
                        logbox.see('end')
                    if invalid:
                        continue  # 原本と未読状態を保ち、正常な別の日の記録まで止めない。
                    break  # DB使用中・同期フォルダの障害などは後続も試さず待つ。
                pscube_sync_errors.pop(name, None)
                seen = {**seen, name: mtime}
                present = {n for n, _m, _p in files}
                save_settings(DATA_DIR, pscube_android_synced={n: m for n, m in seen.items() if n in present})
        except Exception as exc:  # noqa: BLE001 - 確認そのものの失敗でPC版を止めない
            message = f'P’s CUBEの同期フォルダを確認できませんでした：{exc}'
            if pscube_sync_errors.get('') != message:
                pscube_sync_errors[''] = message
                logbox.insert('end', message + '\n')
                logbox.see('end')
        finally:
            if not closing[0]:
                root.after(PSCUBE_SYNC_POLL_MS, poll_pscube_from_sync)

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
            schedule_outputs(history=True)
            schedule_outputs(backup=True)
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
        if current_location() == PSCUBE_KEY:
            open_local_pscube(target)
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
            if external_pscube_selected():
                open_local_pscube(day.get().strip(), machine.get().strip() or None)
                return
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

    def open_event_history_page(location='nagamachiminami'):
        for child in root.winfo_children():
            if hasattr(child, 'flush_history') and getattr(child, 'history_store', 'nagamachiminami') == location:
                child.lift()
                child.focus_set()
                return
        db = Store(DATA_DIR / 'database.sqlite3')
        try:
            changed, _conflicts, rejected, _skipped = pull_shared_history(db, resolve_sync_dir(DATA_DIR))
            if changed:
                schedule_outputs(backup=True)
                tell(f'共有のイベント履歴を{changed}件取り込みました。\n')
            if rejected:
                tell(f'共有のイベント履歴は形式が合わない編集{rejected}件を反映していません。\n')
        except (OSError, ValueError, sqlite3.Error) as error:
            tell(f'共有のイベント履歴を取り込めませんでした（元の記録は保持）：{error}\n')
        finally:
            db.close()
        def open_machine(machine_name, target_day):
            store_name.set(STORE_NAMES[location])
            refresh_days()
            if target_day not in day_combo.cget('values'):
                messagebox.showinfo('記録がありません', f'{target_day}の{STORE_NAMES[location]}の保存済みデータがありません。', parent=root)
                return
            day.set(target_day)
            refresh_machines()
            saved_machine = next((name for name in machine_combo.cget('values')
                                  if normalize_machine_name(name) == normalize_machine_name(machine_name)), None)
            if saved_machine is None:
                messagebox.showinfo('記録がありません',
                                    f'{target_day}\n{machine_name}\nの保存済みデータがありません。', parent=root)
                return
            machine.set(saved_machine)
            remember_selection()
            notebook.select(tab_results)
            open_result()
        show_event_history(root, open_machine, db_path=DATA_DIR / 'database.sqlite3',
                           on_changed=lambda: schedule_outputs(backup=True), location=location)

    def open_history():
        if current_location() == PSCUBE_KEY:
            if external_pscube_selected():
                open_local_pscube(day.get().strip())
                return
            open_pscube_viewer()
            return
        def open_completed(result):
            # 開く前に閉じた場合は作っていない（閉じる途中は作らない）。
            if not result.error and result.value.get('history'):
                os.startfile(result.value['history'])
        schedule_outputs(history=True, done=open_completed)

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
                schedule_outputs(history=True)
                schedule_outputs(backup=True)
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
                deleted = delete_records(db, DATA_DIR, target, scope['location'], scope['machine'], defer_outputs=True)
                schedule_outputs(backup=True)
                schedule_outputs(history=True)
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
                schedule_outputs(history=True)
                schedule_outputs(backup=True)
            finally:
                db.close()
            make_report(location, name, target)
            setting_text = selected['value'] or '未入力に戻しました'
            logbox.insert('end', f'{target}｜{name}｜{rack}番台｜設定情報：{setting_text}\n')
            logbox.see('end')
        except Exception as exc:
            messagebox.showerror('設定情報を保存できません', str(exc), parent=root)

    ttk.Button(results_buttons, text='この日のまとめ', command=open_summary).pack(side='left')
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
            label = undo_last_save(db, DATA_DIR, defer_outputs=True)
            schedule_outputs(backup=True)
            schedule_outputs(history=True)
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
    root.after(PSCUBE_SYNC_FIRST_MS, poll_pscube_from_sync)
    # 翌日候補の比較用の検証記録は、操作ごとに接続を閉じても起動中は送り続ける（input_versions.hold）。
    recording_paths = (DATA_DIR / 'database.sqlite3', DATA_DIR / 'pscube.sqlite3')
    for path in recording_paths:
        input_versions.hold(path)
    def close_app():
        if closing[0]:
            return
        for child in root.winfo_children():
            if hasattr(child, 'flush_history'):
                child.flush_history()
        if rainbow_pending[0]:
            flush_rainbow()
            # Marks added while an earlier output was running need one final snapshot.
            schedule_outputs(backup=True)
        closing[0] = True
        # Prevent another edit after the final output snapshot was requested.
        # Timers keep running so completion/error notifications still reach Tk.
        # A bind tag beginning with '.' is interpreted as a window pathname.
        tag = 'DatabaseClosingInput'
        root.bind_class(tag, '<ButtonPress>', lambda event: 'break')
        root.bind_class(tag, '<KeyPress>', lambda event: 'break')
        def block_inputs(widget):
            for child in widget.winfo_children():
                child.bindtags((tag, *child.bindtags()))
                block_inputs(child)
        block_inputs(root)
        output_worker.finish()
        if output_poll[0] is None:
            poll_outputs()
    root.protocol('WM_DELETE_WINDOW', close_app)
    try:
        root.mainloop()
    finally:
        output_worker.finish()
        if output_worker.thread is not None:
            output_worker.thread.join()
        # 送り切れない分は本体に残り、次の起動で続きから送る。
        for path in recording_paths:
            input_versions.release(path)
        # The event loop has ended; release pending Tk callbacks on this thread.
        list(output_worker.poll())
        try:
            for timer in root.tk.call('after', 'info'):
                root.after_cancel(timer)
        except tk.TclError:
            pass


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-local':
        from runtime_smoke import run
        run(sys.modules[__name__], 'main', sys.argv[2])
    else:
        main()
