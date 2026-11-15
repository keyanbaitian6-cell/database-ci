"""PCの共有出力の状態欄。更新・再出力の操作はTkのスレッドだけで行う。"""
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from backup_status import status_text
from input_versions import recording_status_lines
from sync_health import synced_status, sync_status_lines


class BackupStatusPanel(ttk.Frame):
    def __init__(self, parent, data_dir, folder, reexport):
        super().__init__(parent)
        self.data_dir, self.folder = data_dir, folder
        self._timer_root = self.winfo_toplevel()
        self._job = None
        self._busy = False
        self.summary = tk.StringVar(master=self)
        ttk.Label(self, textvariable=self.summary, wraplength=680).pack(anchor='w')
        buttons = ttk.Frame(self)
        buttons.pack(anchor='w', pady=(4, 0))
        self.update_button = ttk.Button(buttons, text='共有用ファイルを更新', command=reexport)
        self.update_button.pack(side='left')
        ttk.Button(buttons, text='更新状況の詳細', command=self.show_details).pack(side='left', padx=8)
        self.refresh()

    def set_busy(self, busy):
        self._busy = busy
        self.update_button.configure(state='disabled' if busy else 'normal')
        self.refresh()

    def source_text(self, source):
        name = 'database.sqlite3' if source == 'meruhen' else 'pscube.sqlite3'
        if not (Path(self.data_dir) / name).is_file():
            label = '長町南・幸町' if source == 'meruhen' else 'P’s CUBE'
            return f'{label}：PC内の記録ファイルなし'
        return status_text(self.data_dir, source, self.folder())

    def refresh(self):
        if self._job is not None:
            self._timer_root.after_cancel(self._job)
        lines = [self.source_text(source).split('\n')[0] for source in ('meruhen', 'pscube')]
        if self._busy:
            lines.insert(0, '共有用ファイルの更新待ち・書き出し中…')
        self.summary.set('\n'.join(lines))
        # 別プロセスの取り込みブラウザが出した結果も、DBを開き直さず読む。
        self._job = self._timer_root.after(1000, self.refresh)

    def details_text(self):
        """「共有用ファイルの更新状況」の窓の文（試験で中身を確かめられるよう、窓から分けた。2026-11-15 レビュー）。"""
        # P’s CUBEの最新日の差枚の取得状況（○台中○台…）は出さない（2026-11-15 利用者「P'SCUBEはよほどのことがないと
        # もう取り込まないと思うので…この表記をすべてからなくしてほしい」）。
        return (('共有用ファイルの更新待ち・書き出し中です。以下は前回までの結果です。\n\n' if self._busy else '') +
                'PCから共有フォルダへの書き出しと、同期フォルダに届いたGoogle側の処理情報を分けて表示します。\n'
                'Googleドライブへのアップロード完了や、iPhoneでの読み込み完了は確認していません。\n\n'
                f'同期フォルダ：{self.folder() or "未設定"}\n\n' +
                '\n\n'.join(self.source_text(source) for source in ('meruhen', 'pscube')) +
                '\n\nGoogle側の状況（同期フォルダに届いた情報。最新とは限りません）\n' +
                '\n\n'.join(('長町南・幸町' if source == 'meruhen' else 'P’s CUBE') + '\n' +
                            '\n'.join(sync_status_lines(synced_status(self.folder(), source)))
                            for source in ('meruhen', 'pscube')) +
                '\n\n' + '\n'.join(recording_status_lines(self.data_dir)))

    def show_details(self):
        window = tk.Toplevel(self)
        window.title('共有用ファイルの更新状況')
        window.geometry('720x480')
        text = tk.Text(window, wrap='word', padx=14, pady=14)
        text.pack(fill='both', expand=True)
        def read_details():
            text.configure(state='normal')
            text.delete('1.0', 'end')
            text.insert('end', self.details_text())
            text.configure(state='disabled')
        read_details()
        buttons = ttk.Frame(window)
        buttons.pack(pady=8)
        ttk.Button(buttons, text='状況を読み直す', command=read_details).pack(side='left', padx=8)
        ttk.Button(buttons, text='閉じる', command=window.destroy).pack(side='left', padx=8)

    def destroy(self):
        if self._job is not None:
            self._timer_root.after_cancel(self._job)
            self._job = None
        super().destroy()
