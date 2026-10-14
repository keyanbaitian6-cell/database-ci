"""Tk orchestration; worker threads never touch Tk widgets."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from anaslo_index import INDEX_URL, canonical_url, date_range, extract_links
from anaslo_download import Client, MAX_BYTES, download


class DownloadDialog(tk.Toplevel):
    def __init__(self, parent, on_files):
        super().__init__(parent)
        self.title('一覧からHTMLを取得')
        self.geometry('1000x740')
        self.minsize(780, 600)
        self.transient(parent)
        self.grab_set()
        self.on_files = on_files
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.client = Client(self.cancel)
        self.busy = False
        self.links = []
        self.scan_key = None
        self.paths = []
        self.url = tk.StringVar(value=INDEX_URL)
        self.start_day = tk.StringVar()
        self.end_day = tk.StringVar()
        self.local = tk.BooleanVar(value=False)
        self.saved_index = tk.StringVar()
        self.folder = tk.StringVar(value=str(Path(__file__).parent / 'data' / 'downloaded_htmls'))
        self.status = tk.StringVar(value='開始日・終了日を必ず指定してください。範囲内の日別HTMLだけを取得します。')
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='一覧からHTMLを取得', style='H2.TLabel').pack(anchor='w', pady=(0, 10))
        self.inputs = []
        def entry_row(label, variable):
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=label, width=13).pack(side='left')
            entry = ttk.Entry(row, textvariable=variable)
            entry.pack(side='left', fill='x', expand=True)
            self.inputs.append(entry)
            return row
        entry_row('一覧URL', self.url)
        row = entry_row('保存した一覧HTML', self.saved_index)
        choose = ttk.Button(row, text='選ぶ', command=self.choose_index)
        choose.pack(side='right', padx=(8, 0))
        self.inputs.append(choose)
        offline = ttk.Checkbutton(frame, text='保存した一覧HTMLを使う（一覧ページへ通信しない）', variable=self.local)
        offline.pack(anchor='w')
        self.inputs.append(offline)
        range_row = ttk.Frame(frame)
        range_row.pack(fill='x', pady=8)
        ttk.Label(range_row, text='開始日').pack(side='left')
        for label, variable in [('開始日', self.start_day), ('終了日', self.end_day)]:
            if label == '終了日':
                ttk.Label(range_row, text='〜 終了日').pack(side='left', padx=10)
            entry = ttk.Entry(range_row, textvariable=variable, width=14)
            entry.pack(side='left', padx=5)
            self.inputs.append(entry)
        ttk.Label(range_row, text='YYYY-MM-DD（両端を含む）').pack(side='left', padx=10)
        row = entry_row('HTML保存先', self.folder)
        choose = ttk.Button(row, text='選ぶ', command=self.choose_folder)
        choose.pack(side='right', padx=(8, 0))
        self.inputs.append(choose)
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=8)
        self.scan_button = ttk.Button(row, text='指定期間のリンクを確認', command=self.scan)
        self.scan_button.pack(side='left')
        self.start_button = ttk.Button(row, text='表示中の日付のHTMLを取得', style='Accent.TButton', command=self.start, state='disabled')
        self.start_button.pack(side='left', padx=10)
        self.stop_button = ttk.Button(row, text='停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='right')
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('day', 'url'), show='headings', height=9)
        self.table.heading('day', text='対象日')
        self.table.heading('url', text='日別データURL')
        self.table.column('day', width=110, stretch=False)
        self.table.column('url', width=790)
        self.table.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        scrollbar.pack(side='right', fill='y')
        self.table.configure(yscrollcommand=scrollbar.set)
        ttk.Label(frame, textvariable=self.status, wraplength=940).pack(anchor='w', pady=8)
        self.log = tk.Text(frame, height=5, wrap='word', state='disabled')
        self.log.pack(fill='x')
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=(10, 0))
        self.use_button = ttk.Button(row, text='取得・確認できたHTMLを変換画面へ渡す', command=self.use, state='disabled')
        self.use_button.pack(side='left')
        ttk.Button(row, text='閉じる', command=self.close).pack(side='right')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after_id = self.after(100, self.poll)
        for variable in (self.url, self.start_day, self.end_day, self.local, self.saved_index):
            variable.trace_add('write', lambda *args: self.invalidate())

    def key(self):
        return (self.url.get().strip(), self.start_day.get().strip(), self.end_day.get().strip(), self.local.get(), self.saved_index.get().strip())

    def invalidate(self):
        if not self.busy:
            self.start_button.configure(state='disabled')
            self.use_button.configure(state='disabled')
            self.paths = []
            self.scan_key = None

    def choose_index(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('HTML', '*.html *.htm')])
        if path:
            self.saved_index.set(path)
            self.local.set(True)

    def choose_folder(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.folder.set(path)

    def set_busy(self, busy):
        self.busy = busy
        for widget in self.inputs:
            widget.configure(state='disabled' if busy else 'normal')
        self.scan_button.configure(state='disabled' if busy else 'normal')
        self.start_button.configure(state='disabled' if busy or not self.links or self.scan_key != self.key() else 'normal')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        self.use_button.configure(state='disabled' if busy or not self.paths else 'normal')

    def launch(self, work, kind):
        self.cancel.clear()
        self.set_busy(True)
        self.use_button.configure(state='disabled')
        def run():
            try:
                self.events.put((kind, work()))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def scan(self):
        key = self.key()
        try:
            url = canonical_url(key[0], index=True)
            start, end = date_range(key[1], key[2])
            if key[3] and not Path(key[4]).is_file():
                raise ValueError('保存した一覧HTMLを選んでください。')
        except (ValueError, OSError) as exc:
            messagebox.showerror('指定を確認してください', str(exc), parent=self)
            return
        self.links, self.paths = [], []
        self.table.delete(*self.table.get_children())
        self.status.set('指定期間のリンクを確認しています。')
        def work():
            self.client.check()
            if key[3]:
                if Path(key[4]).stat().st_size > MAX_BYTES:
                    raise ValueError('一覧HTMLが16MiBを超えています。')
                raw = Path(key[4]).read_bytes()
            else:
                raw = self.client.get(url, index=True)
            self.client.check()
            return key, extract_links(raw, url, start, end)
        self.launch(work, 'scan')

    def start(self):
        if self.busy or not self.links or self.scan_key != self.key():
            return
        folder = self.folder.get().strip()
        if not folder:
            messagebox.showerror('保存先を確認してください', 'HTML保存先を指定してください。', parent=self)
            return
        start, end = date_range(self.scan_key[1], self.scan_key[2])
        links = tuple(self.links)
        self.paths = []
        self.status.set(f'{start}〜{end}の{len(links)}日分を取得します。')
        self.launch(lambda: download(links, start, end, folder, self.client, lambda text: self.events.put(('log', text))), 'download')

    def stop(self):
        self.cancel.set()
        self.status.set('停止を待っています。通信中の場合はタイムアウトまで待つことがあります。')

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == 'log':
                    self.log.configure(state='normal')
                    self.log.insert('end', data + '\n')
                    self.log.see('end')
                    self.log.configure(state='disabled')
                elif kind == 'scan':
                    key, self.links = data
                    self.scan_key = key
                    for item in self.links:
                        self.table.insert('', 'end', values=(item.day, item.url))
                    self.status.set(f'{key[1]}〜{key[2]}：対象{len(self.links)}日。表示した日付だけを取得します。')
                    self.set_busy(False)
                elif kind == 'download':
                    self.paths = list(data.paths)
                    self.status.set(f'新規取得{data.downloaded}件・保存済み{data.skipped}件・失敗{data.failed}件。' + data.stopped)
                    self.set_busy(False)
                elif kind == 'error':
                    self.status.set('処理を停止しました：' + data)
                    self.set_busy(False)
        except queue.Empty:
            pass
        self.after_id = self.after(100, self.poll)

    def destroy(self):
        self.cancel.set()
        if getattr(self, 'after_id', None):
            self.after_cancel(self.after_id)
            self.after_id = None
        super().destroy()

    def use(self):
        if self.busy or not self.paths:
            return
        paths = list(self.paths)
        self.grab_release()
        self.destroy()
        self.on_files(paths)

    def close(self):
        if self.busy:
            self.stop()
            return
        self.grab_release()
        self.destroy()
