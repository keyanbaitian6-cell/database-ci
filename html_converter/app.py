"""Separate Windows desktop app. The source application DB is read-only."""
from pathlib import Path
import json
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'database'))
from app import apply_style
from anaslo_converter import TARGETS, PscubeTarget, analyze, save_backup
from anaslo_download import PaceState
from html_converter_diagnostics import LOGGER, setup as setup_diagnostics

KEEP = 'HTMLの機種名を使う'
OMIT = '取り込み対象から外す'
PENDING = '対応する機種を選択'


class Converter:
    def __init__(self, root):
        self.root = root
        root.title('database HTMLデータ変換')
        root.geometry('1040x760')
        root.minsize(800, 600)
        apply_style(root)
        self.staging = None
        self.target = None
        self.racks = {}
        self.mapping = {}
        self.download_pacing = PaceState()
        self.names = []
        self.aliases = {}
        self.alias_file = None
        frame = ttk.Frame(root, padding=22)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='HTMLデータ変換', style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame, text='P-STATION・幸町の保存HTML → databaseで読み込める補完用JSON', style='Sub.TLabel').pack(anchor='w', pady=(0, 16))
        controls = ttk.Frame(frame)
        controls.pack(fill='x')
        ttk.Button(controls, text='HTMLを選ぶ（複数日可）', command=self.load).pack(side='left')
        ttk.Button(controls, text='一覧から取得', command=self.open_download).pack(side='left', padx=(8, 0))
        self.hall_text = tk.StringVar(value='店舗はHTMLの見出しで判定します。')
        ttk.Label(controls, textvariable=self.hall_text).pack(side='left', padx=20)
        self.status = tk.StringVar(value='HTMLを選ぶと、日付・台数と機種名の対応を表示します。')
        ttk.Label(frame, textvariable=self.status, wraplength=960).pack(anchor='w', pady=12)
        table = ttk.Frame(frame)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('source', 'target', 'status'), show='headings', selectmode='browse')
        for col, label, width in [('source', 'HTMLの機種名', 350), ('target', 'databaseの機種名', 350), ('status', '確認', 160)]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=80)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        editor = ttk.LabelFrame(frame, text='選択した機種の対応', padding=12)
        editor.pack(fill='x', pady=12)
        self.selected_label = tk.StringVar(value='一覧から機種を選んでください。')
        ttk.Label(editor, textvariable=self.selected_label, wraplength=940).pack(anchor='w')
        self.choice = tk.StringVar()
        row = ttk.Frame(editor)
        row.pack(fill='x', pady=(8, 0))
        self.combo = ttk.Combobox(row, textvariable=self.choice, state='readonly', width=65)
        self.combo.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='この対応を確定', command=self.assign).pack(side='left', padx=(8, 0))
        footer = ttk.Frame(frame)
        footer.pack(fill='x')
        ttk.Button(footer, text='未対応はHTMLの機種名を使う', command=self.keep_remaining).pack(side='left')
        self.save_button = ttk.Button(footer, text='補完用JSONを保存', style='Accent.TButton', command=self.save, state='disabled')
        self.save_button.pack(side='right')
        self.notice = tk.StringVar(value=PscubeTarget.notice)
        ttk.Label(frame, textvariable=self.notice, style='Sub.TLabel', wraplength=960).pack(anchor='w', pady=(12, 0))

    def load(self):
        paths = filedialog.askopenfilenames(parent=self.root, title='保存HTMLを選ぶ', filetypes=[('HTML', '*.html *.htm')])
        if not paths:
            return
        self.load_paths(paths)

    def open_download(self):
        from download_dialog import DownloadDialog
        DownloadDialog(self.root, self.load_paths, pacing=self.download_pacing)

    def load_paths(self, paths):
        try:
            staging = analyze(paths)
            target = TARGETS[staging['hall']](ROOT / 'database' / 'data')
        except Exception as exc:
            messagebox.showerror('読み取れません', str(exc), parent=self.root)
            return
        self.staging, self.target = staging, target
        self.hall_text.set(f'店舗：{target.hall.label}　{target.rate_text}')
        self.notice.set(target.notice)
        # Aliases are per hall: the two databases spell machine names differently.
        self.alias_file = Path(__file__).parent / 'data' / target.alias_file
        try:
            aliases = json.loads(self.alias_file.read_text(encoding='utf-8'))
            self.aliases = aliases if isinstance(aliases, dict) else {}
        except (OSError, ValueError):
            self.aliases = {}
        self.mapping = {}
        self.racks = {}
        for d in staging['days']:
            for r in d['records']:
                self.racks.setdefault(r['machine'], set()).add(r['rack'])
        self.names = sorted(self.racks)
        self.tree.delete(*self.tree.get_children())
        for i, name in enumerate(self.names):
            proposed = target.suggestions(name, self.racks[name])['automatic']
            if target.excluded(name):
                self.mapping[name] = None
            elif name in self.aliases and (self.aliases[name] is None or isinstance(self.aliases[name], str)):
                self.mapping[name] = self.aliases[name]
            elif proposed:
                self.mapping[name] = proposed
            self.tree.insert('', 'end', iid=str(i), values=(name, '', ''))
        self.refresh()
        if self.names:
            self.tree.selection_set('0')

    def refresh(self):
        for i, name in enumerate(self.names):
            target = self.mapping.get(name)
            status = '未確認' if name not in self.mapping else '対象外' if target is None else '対応済み'
            self.tree.item(str(i), values=(name, target or '—', status))
        unresolved = sum(n not in self.mapping for n in self.names)
        text = ' / '.join(f"{d['day']}：{len(d['records'])}台" for d in self.staging['days'])
        self.status.set(f'{text}　機種名の未確認：{unresolved}件')
        self.save_button.configure(state='disabled' if unresolved else 'normal')

    def select(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        name = self.names[int(selected[0])]
        self.selected_label.set(name)
        candidates = self.target.suggestions(name, self.racks[name])['candidates']
        all_names = self.target.names()
        self.combo['values'] = [PENDING, KEEP, OMIT, *candidates, *[n for n in all_names if n not in candidates]]
        self.choice.set(PENDING if name not in self.mapping else OMIT if self.mapping[name] is None else KEEP if self.mapping[name] == name else self.mapping[name])

    def assign(self):
        selected = self.tree.selection()
        if not selected or self.choice.get() in ('', PENDING):
            return
        name = self.names[int(selected[0])]
        choice = self.choice.get()
        self.mapping[name] = name if choice == KEEP else None if choice == OMIT else choice
        self.refresh()
        pending = [str(i) for i, n in enumerate(self.names) if n not in self.mapping]
        if pending:
            self.tree.selection_set(pending[0])
            self.tree.see(pending[0])

    def keep_remaining(self):
        if not self.staging:
            return
        for name in self.names:
            if name not in self.mapping:
                self.mapping[name] = name
        self.refresh()
        self.select()

    def save(self):
        if not self.staging:
            return
        try:
            payload = self.target.make_backup(self.staging, self.mapping)
        except Exception as exc:
            messagebox.showerror('保存できません', str(exc), parent=self.root)
            return
        days = sorted(d['day'].replace('-', '') for d in self.staging['days'])
        period = days[0] if len(days) == 1 else f'{days[0]}-{days[-1]}'
        path = filedialog.asksaveasfilename(parent=self.root, title='補完用JSONの保存先',
                                           initialfile=self.target.file_name(period), defaultextension='.json', filetypes=[('JSON', '*.json')])
        if not path:
            return
        try:
            save_backup(path, payload)
        except Exception as exc:
            messagebox.showerror('保存できません', str(exc), parent=self.root)
            return
        # Alias persistence failure must not misreport a successful JSON save.
        warning = ''
        try:
            self.alias_file.parent.mkdir(parents=True, exist_ok=True)
            self.aliases.update(self.mapping)
            self.alias_file.write_text(json.dumps(self.aliases, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            warning = '\n機種名の対応表は保存できませんでした。次回は再確認してください。'
        skipped = payload['conversion_summary']['skipped']
        detail = ''.join(f'\n{label}：{skipped[key]}件' for key, label in
                         (('existing', 'databaseに保存済みの日付・台'), ('unknown_rack', 'databaseに記録のない台番号'),
                          ('excluded', '対象外の機種'), ('manual', '取り込み対象から外した機種')) if skipped.get(key))
        messagebox.showinfo('保存しました', f"{len(payload['records'])}件の補完用JSONを保存しました。{detail}\n{path}\n\ndatabase → バックアップ・同期 → バックアップを読み込む、から選択してください。" + warning, parent=self.root)


def main():
    root = tk.Tk()
    if '--smoke' not in sys.argv:
        try:
            setup_diagnostics()
        except OSError as exc:
            messagebox.showwarning('診断ログを保存できません', str(exc), parent=root)
        def callback_error(kind, value, traceback):
            LOGGER.error('Tk callback failed', exc_info=(kind, value, traceback))
            messagebox.showerror('画面処理でエラーが発生しました', str(value), parent=root)
        root.report_callback_exception = callback_error
    if '--smoke' in sys.argv:
        root.withdraw()
    Converter(root)
    if '--smoke' in sys.argv:
        root.update_idletasks()
        root.destroy()
        print('GUI_OK')
        return
    root.mainloop()


if __name__ == '__main__':
    main()
