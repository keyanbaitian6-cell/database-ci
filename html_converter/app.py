"""Separate Windows desktop app. The source application DB is read-only."""
from pathlib import Path
import json
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'database'))
from app import apply_style
from anaslo_converter import (TARGETS, MeruhenTarget, PscubeTarget, analyze, make_normal_analysis,
                              make_other_analysis, save_backup, save_normal_analysis, save_other_analysis)
from anaslo_download import PaceState
import pscube_import
from anaslo_html import prune_cache
from html_converter_diagnostics import LOGGER, setup as setup_diagnostics

KEEP = 'HTMLの機種名を使う'
OMIT = '取り込み対象から外す'
PENDING = '対応する機種を選択'
# 幸町のジャグラー・ハナハナだけの分析用ファイル（databaseに読み込まない、2026-10-17）。
NORMAL_ANALYSIS_DIR = Path(__file__).resolve().parent / 'data' / 'normal_analysis'
OTHER_ANALYSIS_DIR = Path(__file__).resolve().parent / 'data' / 'other_analysis'
# 解析結果の控え（Git対象外。2026-11-06）。
PARSE_CACHE_DIR = Path(__file__).resolve().parent / 'data' / 'parse_cache'
# 補完用JSONの保存先の初期値。PC版の「バックアップを読み込む」も、保存から3時間はここを開く（2026-11-06）。
JSON_DIR = Path(__file__).resolve().parent / 'data' / 'backup_json'
DATA_DIR = ROOT / 'database' / 'data'


def sync_folder():
    """PC版の同期フォルダ（ドライブ）。設定を読むだけで書き換えない。未設定・見つからなければ None。"""
    try:
        from core import load_settings
        folder = load_settings(DATA_DIR).get('sync_dir')
        return Path(folder) if folder and Path(folder).is_dir() else None
    except Exception:  # noqa: BLE001 - 見つからなければ今まで通りの保存先
        return None


def json_folder(target):
    """補完用JSONの保存先の初期値。P-STATION は同期フォルダ：起動中のPC版が数分おきに自動で読み込み、
    DB・閲覧用データ・ドライブへの書き出しまで行う（2026-11-06 利用者「Aにして」）。幸町・同期フォルダ未設定は JSON_DIR。"""
    if isinstance(target, PscubeTarget):
        folder = sync_folder()
        if folder:
            return folder
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    return JSON_DIR


class Converter:
    def __init__(self, root):
        self.root = root
        root.title('database HTMLデータ変換')
        root.geometry('1040x760')
        root.minsize(800, 600)
        apply_style(root)
        self.staging = None
        self.target = None
        self.loading = False
        self.parse_cache = PARSE_CACHE_DIR
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
        analysis_footer = ttk.Frame(frame)
        analysis_footer.pack(fill='x', pady=(0, 8))
        self.normal_button = ttk.Button(analysis_footer, text='ノーマルタイプの分析用に保存', command=self.save_normal, state='disabled')
        self.normal_button.pack(side='left')
        self.other_button = ttk.Button(analysis_footer, text='その他機種の分析用に保存', command=self.save_other, state='disabled')
        self.other_button.pack(side='left', padx=(8, 0))
        footer = ttk.Frame(frame)
        footer.pack(fill='x')
        ttk.Button(footer, text='未対応はHTMLの機種名を使う', command=self.keep_remaining).pack(side='left')
        self.save_button = ttk.Button(footer, text='補完用JSONを保存', style='Accent.TButton', command=lambda: self.save(background=True), state='disabled')
        self.save_button.pack(side='right')
        self.notice = tk.StringVar(value=PscubeTarget.notice)
        ttk.Label(frame, textvariable=self.notice, style='Sub.TLabel', wraplength=960).pack(anchor='w', pady=(12, 0))

    def load(self):
        paths = filedialog.askopenfilenames(parent=self.root, title='保存HTMLを選ぶ', filetypes=[('HTML', '*.html *.htm')])
        if not paths:
            return
        self.load_paths(paths, background=True)

    def open_download(self):
        from download_dialog import DownloadDialog
        DownloadDialog(self.root, lambda paths: self.load_paths(paths, background=True), pacing=self.download_pacing, suggest=True)

    def show_window(self):
        # 取得画面を閉じたあと、変換画面が後ろに隠れたままにならないよう前に出す（2026-11-06）。
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def load_paths(self, paths, *, background=False):
        """background：画面から読むとき。HTMLの解析（1か月分で約8秒）を別のスレッドで行い、その間も画面を
        応答させる（2026-11-06 利用者「取り込んでいた画面を下部のアイコンからえらんでも開かない」。Windowsは5秒以上
        応答しない窓を「応答なし」にし、タスクバーから前に出せなくなる）。画面の部品に触るのはメインスレッドだけ。"""
        paths = list(paths)
        self.show_window()
        if not background:
            try:
                staging = analyze(paths)
                target = TARGETS[staging['hall']](ROOT / 'database' / 'data')
            except Exception as exc:
                messagebox.showerror('読み取れません', str(exc), parent=self.root)
                return
            self.show_loaded(staging, target)
            return
        if self.loading:
            messagebox.showinfo('読み込み中です', '前の処理が終わってから選び直してください。', parent=self.root)
            return

        def work():
            # 同じHTMLの2回目以降は解析結果の控えを使う（2026-11-06、anaslo_html.parse_cached）。
            staging = analyze(paths, cache_dir=self.parse_cache) if self.parse_cache else analyze(paths)
            if self.parse_cache:
                prune_cache(self.parse_cache)
            return staging, TARGETS[staging['hall']](ROOT / 'database' / 'data')

        def done(value):
            self.show_loaded(*value)
            self.show_window()

        self.in_background(f'{len(paths)}件のHTMLを読み込んでいます。しばらくお待ちください。', work, done,
                           'HTMLを読み取れませんでした。', '読み取れません')

    def in_background(self, message, work, done, failed_status, failed_title):
        """work を別のスレッドで行い、終わったら done(結果) をメインスレッドで呼ぶ（画面の部品はメインだけ）。
        読み込み・保存のどちらの途中でも、もう一方は始めない（self.loading）。"""
        self.loading = True
        self.set_buttons()
        self.status.set(message)
        result = {}

        def run():
            try:
                result['value'] = work()
            except Exception as exc:  # noqa: BLE001 - 画面に理由を出す
                LOGGER.exception('background task failed: %s', failed_title)
                result['error'] = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        def check():
            if thread.is_alive():
                self.root.after(100, check)
                return
            self.loading = False
            self.set_buttons()
            if 'error' in result:
                self.status.set(failed_status)
                messagebox.showerror(failed_title, str(result['error']), parent=self.root)
                return
            done(result['value'])

        self.root.after(100, check)

    def set_buttons(self):
        """処理の途中は保存のボタンを押せないようにする。"""
        if self.loading or not self.staging:
            state = 'disabled'
            self.save_button.configure(state=state)
            self.normal_button.configure(state=state)
            self.other_button.configure(state=state)
            return
        unresolved = sum(n not in self.mapping for n in self.names)
        self.save_button.configure(state='disabled' if unresolved else 'normal')
        # 分析用は機種名の対応が済んでいなくても作れる（幸町だけ）。
        meruhen = 'normal' if isinstance(self.target, MeruhenTarget) else 'disabled'
        self.normal_button.configure(state=meruhen)
        self.other_button.configure(state=meruhen)

    def show_loaded(self, staging, target):
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
        self.set_buttons()

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

    def save(self, *, background=False):
        """background：画面のボタンから。保存先を先に選び、変換（1か月分で数秒、推定差枚込み）と書き込みは
        別のスレッドで行う（2026-11-06。画面のスレッドで行うと、期間が長いとき「応答なし」になる）。"""
        if not self.staging or self.loading:
            return
        days = sorted(d['day'].replace('-', '') for d in self.staging['days'])
        period = days[0] if len(days) == 1 else f'{days[0]}-{days[-1]}'
        try:
            folder = {'initialdir': str(json_folder(self.target))}
        except OSError:
            folder = {}
        mapping, staging, target = dict(self.mapping), self.staging, self.target
        if not background:
            try:
                payload = target.make_backup(staging, mapping)
            except Exception as exc:
                messagebox.showerror('保存できません', str(exc), parent=self.root)
                return
        path = filedialog.asksaveasfilename(parent=self.root, title='補完用JSONの保存先',
                                           initialfile=target.file_name(period), defaultextension='.json',
                                           filetypes=[('JSON', '*.json')], **folder)
        if not path:
            return
        if not background:
            try:
                save_backup(path, payload)
            except Exception as exc:
                messagebox.showerror('保存できません', str(exc), parent=self.root)
                return
            self.saved(path, payload, mapping)
            return

        def work():
            payload = target.make_backup(staging, mapping)
            save_backup(path, payload)
            return payload

        self.in_background('補完用JSONを作っています。しばらくお待ちください。', work,
                           lambda payload: self.saved(path, payload, mapping), 'JSONを保存できませんでした。', '保存できません')

    def saved(self, path, payload, mapping):
        # Alias persistence failure must not misreport a successful JSON save.
        warning = ''
        try:
            self.alias_file.parent.mkdir(parents=True, exist_ok=True)
            self.aliases.update(mapping)
            self.alias_file.write_text(json.dumps(self.aliases, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            warning = '\n機種名の対応表は保存できませんでした。次回は再確認してください。'
        # PC版の「バックアップを読み込む」のファイル名の欄に貼り付けられるよう、保存先をクリップボードに入れる。
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(Path(path)))
            copied = '\n保存先はクリップボードに入れました（ファイルを選ぶ画面のファイル名の欄に貼り付けられます）。'
        except tk.TclError:
            copied = ''
        skipped = payload['conversion_summary']['skipped']
        detail = ''.join(f'\n{label}：{skipped[key]}件' for key, label in
                         (('existing', 'databaseに保存済みの日付・台'), ('unknown_rack', 'databaseに記録のない台番号'),
                          ('excluded', '対象外の機種'), ('manual', '取り込み対象から外した機種')) if skipped.get(key))
        self.refresh()
        sync = sync_folder()
        automatic = (isinstance(self.target, PscubeTarget) and sync is not None
                     and Path(path).parent.resolve() == sync.resolve()
                     and pscube_import.ANDROID_SYNC_NAME.fullmatch(Path(path).name) is not None)
        how = ('同期フォルダに保存したので、起動中のPC版が数分以内に自動で読み込み、閲覧用データとドライブへの書き出しまで'
               '行います（PC版が閉じていれば、次に起動したときに読み込みます）。' if automatic else
               'database → バックアップ・同期 → バックアップを読み込む、から選択してください。'
               '保存から3時間は、読み込む画面がこのフォルダーで開きます。')
        messagebox.showinfo('保存しました', f"{len(payload['records'])}件の補完用JSONを保存しました。{detail}\n{path}\n\n"
                            + how + copied + warning, parent=self.root)

    def save_normal(self):
        """ジャグラー・ハナハナだけを分析用に保存する。databaseには読み込まないので、共有・採点・翌日候補に出ない。"""
        if not self.staging or not isinstance(self.target, MeruhenTarget):
            return
        try:
            payload = make_normal_analysis(self.staging, self.mapping)
            path = save_normal_analysis(NORMAL_ANALYSIS_DIR / payload['store'], payload)
        except Exception as exc:
            messagebox.showerror('保存できません', str(exc), parent=self.root)
            return
        summary = payload['summary']
        messagebox.showinfo('分析用に保存しました',
                            f"{summary['days']}日分・ジャグラー/ハナハナ{summary['records']}台を分析用に保存しました。\n{path}\n\n"
                            'このファイルはdatabaseに読み込みません（共有ページ・iPhone版・Android・採点・翌日候補には出ません）。'
                            '「バックアップを読み込む」で選んでも読み込めない形式です。', parent=self.root)


    def save_other(self):
        """ジャグラー・ハナハナ以外を、通常の記録と別の分析用に保存する。"""
        if not self.staging or not isinstance(self.target, MeruhenTarget):
            return
        try:
            payload = make_other_analysis(self.staging, self.mapping)
            path = save_other_analysis(OTHER_ANALYSIS_DIR / payload['store'], payload)
        except Exception as exc:
            messagebox.showerror('保存できません', str(exc), parent=self.root)
            return
        summary = payload['summary']
        messagebox.showinfo('分析用に保存しました',
                            f"{summary['days']}日分・ジャグラー/ハナハナ以外{summary['records']}台を分析用に保存しました。\n{path}\n\n"
                            'このファイルはdatabaseに読み込みません（共有ページ・iPhone版・Android・採点・翌日候補には出ません）。'
                            '「バックアップを読み込む」で選んでも読み込めない形式です。', parent=self.root)


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
