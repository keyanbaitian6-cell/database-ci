from datetime import date, datetime
from pathlib import Path
import base64
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from core import (CONFIRMED_SETTING_OPTIONS, STORE_NAMES, Store, auto_backup, delete_records, export_backup, history_report, import_backup,
                  latest_backup_file, list_snapshots, load_settings, report, restore_backup, save_settings,
                  summary_report, undo_last_save)

ROOT = Path(__file__).parent
DATA_DIR = ROOT / 'data'
MACHINE_DEFAULT = ''
ALL_DAYS_LABEL = 'すべての日付'
ALL_STORES_LABEL = 'すべての店舗'
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


def apply_style(root):
    """One quiet look for the whole window (Apple-style: white cards on a light
    gray page, a single blue for the primary action, hairline borders)."""
    page, hairline, ink, mute, blue = '#f5f5f7', '#d2d2d7', '#1d1d1f', '#707070', '#0071e3'
    style = ttk.Style(root)
    style.theme_use('clam')
    root.configure(background=page)
    base = ('Yu Gothic UI', 10)
    style.configure('.', background=page, foreground=ink, font=base, bordercolor=hairline,
                    lightcolor=page, darkcolor=page, focuscolor=page)
    style.configure('TFrame', background=page)
    style.configure('TLabel', background=page, foreground=ink)
    style.configure('Title.TLabel', font=('Yu Gothic UI', 24, 'bold'))
    style.configure('H2.TLabel', font=('Yu Gothic UI', 15, 'bold'))
    style.configure('H3.TLabel', font=('Yu Gothic UI', 10, 'bold'))
    style.configure('Sub.TLabel', foreground=mute)
    style.configure('TNotebook', background=page, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure('TNotebook.Tab', background=page, foreground=mute, padding=(16, 9), borderwidth=0,
                    font=('Yu Gothic UI', 10, 'bold'))
    style.map('TNotebook.Tab', background=[('selected', '#ffffff')], foreground=[('selected', ink)])
    style.configure('TLabelframe', background=page, bordercolor=hairline, relief='solid')
    style.configure('TLabelframe.Label', background=page, foreground=ink, font=('Yu Gothic UI', 10, 'bold'))
    for name in ('TCheckbutton', 'TRadiobutton'):
        style.configure(name, background=page)
    style.configure('TButton', background='#e8e8ed', foreground=ink, padding=(14, 7), borderwidth=0, relief='flat')
    style.map('TButton', background=[('active', '#dcdce1'), ('pressed', '#d2d2d7')])
    style.configure('Accent.TButton', background=blue, foreground='#ffffff', font=('Yu Gothic UI', 12, 'bold'),
                    padding=(18, 8))
    style.map('Accent.TButton', background=[('active', '#0077ed'), ('pressed', '#006edb')],
              foreground=[('disabled', '#ffffff')])
    style.configure('Link.TButton', background=page, foreground='#0066cc', padding=(4, 2))
    style.map('Link.TButton', background=[('active', page)], foreground=[('active', '#004499')])
    style.configure('TSeparator', background=hairline)
    style.configure('TCombobox', fieldbackground='#ffffff', background='#ffffff', padding=4)
    style.map('TCombobox', fieldbackground=[('readonly', '#ffffff')], background=[('readonly', '#ffffff')])


def main():
    root = tk.Tk()
    root.title('database')
    root.geometry('920x780')
    root.minsize(780, 620)
    apply_style(root)
    frame = ttk.Frame(root, padding=(28, 20, 28, 14))
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='database', style='Title.TLabel').pack(anchor='w')
    ttk.Label(frame, text='長町南店・幸町店｜1000円46枚スロット', style='Sub.TLabel').pack(anchor='w', pady=(2, 12))
    # 記録欄は先に下端へ確保しておく（後から詰め込むと、タブに押されて見えなくなるため）
    log_frame = ttk.Frame(frame)
    log_frame.pack(side='bottom', fill='x', pady=(10, 0))
    notebook = ttk.Notebook(frame)
    notebook.pack(fill='both', expand=True)
    tab_home = ttk.Frame(notebook, padding=22)
    tab_results = ttk.Frame(notebook, padding=22)
    tab_sync = ttk.Frame(notebook, padding=22)
    notebook.add(tab_home, text='  取り込み  ')
    notebook.add(tab_results, text='  結果を見る  ')
    notebook.add(tab_sync, text='  バックアップ・同期  ')

    ttk.Label(tab_results, text='見たい台を選ぶ', style='H2.TLabel').pack(anchor='w')
    ttk.Label(tab_results, text='保存済みの店舗・日付・機種だけ選べます。', style='Sub.TLabel').pack(anchor='w', pady=(0, 10))
    identity = ttk.Frame(tab_results)
    identity.pack(fill='x')
    ttk.Label(identity, text='店舗').grid(row=0, column=0, sticky='w')
    settings = load_settings(DATA_DIR)
    store_name = tk.StringVar(value=STORE_NAMES.get(settings.get('last_store'), STORE_NAMES['nagamachiminami']))
    store_combo = ttk.Combobox(identity, textvariable=store_name, values=list(STORE_NAMES.values()),
                                state='readonly', width=28)
    store_combo.grid(row=1, column=0, sticky='w', padx=(0, 16))
    ttk.Label(identity, text='日付').grid(row=0, column=1, sticky='w')
    day = tk.StringVar(value=settings.get('last_day', ''))
    day_combo = ttk.Combobox(identity, textvariable=day, state='readonly', width=16)
    day_combo.grid(row=1, column=1, sticky='w', padx=(0, 16))
    ttk.Label(identity, text='機種名').grid(row=0, column=2, sticky='w')
    machine = tk.StringVar(value=settings.get('last_machine', MACHINE_DEFAULT))
    machine_combo = ttk.Combobox(identity, textvariable=machine, state='readonly', width=34)
    machine_combo.grid(row=1, column=2, sticky='ew')
    identity.columnconfigure(2, weight=1)


    def current_location():
        return next((key for key, label in STORE_NAMES.items() if label == store_name.get()), None)

    def refresh_days(*_args):
        location = current_location()
        db = Store(ROOT / 'data' / 'database.sqlite3')
        try:
            days = db.days_for(location) if location else []
        finally:
            db.close()
        day_combo['values'] = days
        if day.get() not in days:
            day.set(days[0] if days else '')

    def refresh_machines(*_args):
        location = current_location()
        target = day.get()
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
        refresh_machines()
        remember_selection()

    store_combo.bind('<<ComboboxSelected>>', on_store_change)
    day_combo.bind('<<ComboboxSelected>>', on_day_change)
    machine_combo.bind('<<ComboboxSelected>>', remember_selection)
    refresh_days()
    refresh_machines()

    ttk.Label(tab_home, text='ブラウザで取り込む', style='H2.TLabel').pack(anchor='w')
    ttk.Label(tab_home, text='ふだんの取り込みは、ここから始めます。', style='Sub.TLabel').pack(anchor='w', pady=(0, 12))
    ttk.Button(tab_home, text='ブラウザを開いて取り込む', style='Accent.TButton',
               command=lambda: open_browser_import()).pack(anchor='w', ipadx=22, ipady=9)
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
        values=[ALL_STORES_LABEL, *STORE_NAMES.values()])
    backup_day = tk.StringVar(value=ALL_DAYS_LABEL)
    backup_day_combo = ttk.Combobox(backup_buttons, textvariable=backup_day, state='readonly', width=16)

    def current_backup_location():
        chosen = backup_store.get()
        return next((key for key, label in STORE_NAMES.items() if label == chosen), None)

    def refresh_backup_days():
        location = current_backup_location()
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
                     highlightthickness=1, highlightbackground='#d2d2d7', background='#ffffff', padx=8, pady=6)
    logbox.pack(fill='x', pady=(4, 0))

    def open_browser_import():
        try:
            subprocess.Popen(
                [sys.executable, str(ROOT / 'browser_import.py'),
                 str(ROOT / 'data' / 'database.sqlite3'), str(ROOT / 'reports')],
                cwd=str(ROOT))
            logbox.insert(
                'end',
                'ブラウザ取り込みを別ウィンドウで開始しました。'
                '保存後は「過去の記録を見る」で確認できます。\n')
            logbox.see('end')
        except OSError as exc:
            messagebox.showerror('起動できません', f'ブラウザ取り込みを開始できません：{exc}', parent=root)

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

    def export_backup_file():
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
        applied = len(plan['new']) + len(plan['graph_only']) + len(plan['link_only'])
        summary = (f'新規{len(plan["new"])}件、グラフ追加{len(plan["graph_only"])}件、リンク補完{len(plan["link_only"])}件を取り込みました。'
                   f'既に同じ内容{len(plan["unchanged"])}件、要確認{len(plan["conflicts"])}件、'
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
                             highlightbackground='#d2d2d7')
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
        try:
            db = Store(ROOT / 'data' / 'database.sqlite3')
            try:
                output = history_report(db, ROOT / 'reports')
            finally:
                db.close()
            os.startfile(output)
        except Exception as exc:
            messagebox.showerror('過去の記録を開けません', str(exc), parent=root)

    def delete_record():
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
            ttk.Button(buttons, text='削除へ進む', command=pick).pack(side='left')
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
    ttk.Button(results_buttons, text='台記録を削除', command=delete_record).pack(side='left', padx=8)
    ttk.Button(results_buttons, text='まとめて削除…', command=delete_group).pack(side='left')
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
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    root.mainloop()


if __name__ == '__main__':
    main()
