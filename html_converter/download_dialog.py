"""Tk orchestration; worker threads never touch Tk widgets."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from anaslo_index import HALLS, P_STATION, canonical_url, date_range, extract_links
from anaslo_download import Client, MAX_BYTES, download
from anaslo_browser import BrowserClient
from html_converter_diagnostics import LOGGER

BROWSER = 'browser'
DIRECT = 'direct'
DOWNLOADS = Path(__file__).parent / 'data' / 'downloaded_htmls'
DATA_DIR = Path(__file__).resolve().parent.parent / 'database' / 'data'
DEFAULT_STATUS = '開始日・終了日を必ず指定してください。範囲内の日別HTMLだけを取得します。'


def default_folder(hall):
    # P-STATION keeps the original folder so its saved HTML is reused.
    return DOWNLOADS if hall is P_STATION else DOWNLOADS / hall.key


class DownloadDialog(tk.Toplevel):
    def __init__(self, parent, on_files, *, pacing=None, suggest=False, data_dir=DATA_DIR):
        super().__init__(parent)
        self.title('一覧からHTMLを取得')
        self.geometry('1000x740')
        self.minsize(780, 600)
        self.transient(parent)
        self.grab_set()
        self.on_files = on_files
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.client = Client(self.cancel, pacing=pacing)
        self.browser_factory = BrowserClient
        self.browser_engine = None
        self.browser_cleanup = None
        self.browser_idle_after = None
        self.method = tk.StringVar(value=BROWSER)
        self.busy = False
        self.links = []
        self.scan_key = None
        self.paths = []
        # 開始日・終了日の初期値（DBの台数が足りない日、2026-11-06）。試験では使わない（suggest=False）。
        self.suggest = suggest
        self.data_dir = data_dir
        self.suggested = None
        self.hall = tk.StringVar(value=P_STATION.key)
        self.url = tk.StringVar(value=P_STATION.index_url)
        self.start_day = tk.StringVar()
        self.end_day = tk.StringVar()
        self.local = tk.BooleanVar(value=False)
        self.saved_index = tk.StringVar()
        self.folder = tk.StringVar(value=str(default_folder(P_STATION)))
        self.status = tk.StringVar(value=DEFAULT_STATUS)
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
        hall_row = ttk.Frame(frame)
        hall_row.pack(fill='x', pady=4)
        ttk.Label(hall_row, text='店舗', width=13).pack(side='left')
        for hall in HALLS:
            button = ttk.Radiobutton(hall_row, text=hall.label, variable=self.hall, value=hall.key,
                                     command=self.choose_hall)
            button.pack(side='left', padx=(0, 12))
            self.inputs.append(button)
        entry_row('一覧URL', self.url)
        row = entry_row('保存した一覧HTML', self.saved_index)
        choose = ttk.Button(row, text='選ぶ', command=self.choose_index)
        choose.pack(side='right', padx=(8, 0))
        self.inputs.append(choose)
        offline = ttk.Checkbutton(frame, text='保存した一覧HTMLを使う（一覧ページへ通信しない）', variable=self.local)
        offline.pack(anchor='w')
        self.inputs.append(offline)
        method_row = ttk.Frame(frame)
        method_row.pack(fill='x', pady=(4, 0))
        ttk.Label(method_row, text='取得方法').pack(side='left', padx=(0, 8))
        for text, value in [('ブラウザで表示して自動保存', BROWSER), ('直接ダウンロード', DIRECT)]:
            button = ttk.Radiobutton(method_row, text=text, variable=self.method, value=value)
            button.pack(side='left', padx=(0, 12))
            self.inputs.append(button)
        range_row = ttk.Frame(frame)
        range_row.pack(fill='x', pady=8)
        ttk.Label(range_row, text='開始日').pack(side='left')
        for label, variable in [('開始日', self.start_day), ('終了日', self.end_day)]:
            if label == '終了日':
                ttk.Label(range_row, text='〜 終了日').pack(side='left', padx=10)
            entry = ttk.Entry(range_row, textvariable=variable, width=14)
            entry.pack(side='left', padx=5)
            self.inputs.append(entry)
            calendar_button = ttk.Button(range_row, text='カレンダー', command=lambda v=variable: self.choose_date(v))
            calendar_button.pack(side='left')
            self.inputs.append(calendar_button)
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
        for variable in (self.hall, self.url, self.start_day, self.end_day, self.local, self.saved_index, self.method):
            variable.trace_add('write', lambda *args: self.invalidate())
        if self.suggest:
            self.apply_suggestion()

    def key(self):
        return (self.url.get().strip(), self.start_day.get().strip(), self.end_day.get().strip(), self.local.get(), self.saved_index.get().strip(), self.method.get())

    def selected_hall(self):
        return next(h for h in HALLS if h.key == self.hall.get())

    def choose_hall(self):
        """Switch the index URL, and the folder only while it is still a default one."""
        hall = self.selected_hall()
        defaults = {str(default_folder(h)) for h in HALLS}
        if self.folder.get().strip() in defaults:
            self.folder.set(str(default_folder(hall)))
        self.url.set(hall.index_url)
        # 入っている日付がこの画面の出した初期値のままなら、店舗に合わせて出し直す（手で入れた日付は変えない）。
        if self.suggest and (self.start_day.get().strip(), self.end_day.get().strip()) in ((self.suggested or (None, None)), ('', '')):
            self.apply_suggestion()

    def apply_suggestion(self):
        from datetime import date
        from anaslo_converter import suggest_period
        hall = self.selected_hall()
        try:
            found = suggest_period(hall.key, self.data_dir, self.folder.get().strip() or default_folder(hall), date.today())
        except Exception:  # noqa: BLE001 - 初期値が出せなくても手で選べる
            LOGGER.exception('period suggestion failed')
            found = None
        start, end = (found['start'], found['end']) if found and found['start'] else ('', '')
        self.start_day.set(start)
        self.end_day.set(end)
        self.suggested = (start, end) if start else None
        if found:
            self.status.set(found['note'] + ('　変えるときはカレンダーから選んでください。' if start else ''))
            LOGGER.info('period suggested: %s %s %s', hall.key, start or '-', end or '-')
        else:
            self.status.set(DEFAULT_STATUS)

    def choose_date(self, variable):
        from calendar_picker import CalendarPicker
        CalendarPicker(self, variable.get(), variable.set)

    def cancel_browser_idle(self):
        if self.browser_idle_after:
            self.after_cancel(self.browser_idle_after)
            self.browser_idle_after = None

    def close_browser(self):
        self.cancel_browser_idle()
        engine, self.browser_engine = self.browser_engine, None
        if engine:
            self.browser_cleanup = threading.Thread(target=engine.close, daemon=True)
            self.browser_cleanup.start()

    def expire_browser(self):
        self.browser_idle_after = None
        if self.busy:
            return
        self.close_browser()
        self.scan_key = None
        self.set_busy(False)
        self.status.set('待機が55秒を超えたため取得ブラウザを閉じました。「指定期間のリンクを確認」から再開してください。')
        LOGGER.info('idle browser closed')

    def with_client(self, action, method, *, keep=False):
        if method == DIRECT:
            return action(self.client)
        if method != BROWSER:
            raise ValueError('取得方法を選択してください。')
        def progress(text):
            LOGGER.info('browser: %s', text)
            self.events.put(('log', text))
        if self.browser_cleanup:
            self.browser_cleanup.join(6)
            if self.browser_cleanup.is_alive():
                raise ValueError('前のブラウザの終了を待っています。終了後に一覧を確認してください。')
            self.browser_cleanup = None
        engine, self.browser_engine = self.browser_engine, None
        if engine is None:
            engine = self.browser_factory(Path(__file__).parent / 'data' / 'anaslo-webview', cancel=self.cancel,
                                      pacing=self.client.pacing,
                                      progress=progress)
        try:
            result = action(engine)
            if keep and not self.cancel.is_set():
                self.browser_engine = engine
            return result
        finally:
            if self.browser_engine is not engine:
                engine.close()

    def invalidate(self):
        if not self.busy:
            self.close_browser()
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
                LOGGER.info('worker start: %s', kind)
                result = work()
                LOGGER.info('worker result ready: %s', kind)
                self.events.put((kind, result))
            except Exception as exc:
                LOGGER.exception('worker failed: %s', kind)
                self.events.put(('error', str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def scan(self):
        if self.busy:
            return
        key = self.key()
        try:
            url = canonical_url(key[0], index=True, hall=self.selected_hall())
            start, end = date_range(key[1], key[2])
            if key[3] and not Path(key[4]).is_file():
                raise ValueError('保存した一覧HTMLを選んでください。')
        except (ValueError, OSError) as exc:
            messagebox.showerror('指定を確認してください', str(exc), parent=self)
            return
        self.links, self.paths = [], []
        self.close_browser()
        self.table.delete(*self.table.get_children())
        self.status.set('指定期間のリンクを確認しています。')
        LOGGER.info('scan requested: start=%s end=%s method=%s local=%s', key[1], key[2], key[5], key[3])
        def work():
            self.client.check()
            if key[3]:
                if Path(key[4]).stat().st_size > MAX_BYTES:
                    raise ValueError('一覧HTMLが16MiBを超えています。')
                raw = Path(key[4]).read_bytes()
            else:
                raw = self.with_client(lambda engine: engine.get(url, index=True), key[5], keep=True)
            LOGGER.info('index received: bytes=%d', len(raw))
            self.client.check()
            links = extract_links(raw, url, start, end)
            LOGGER.info('links extracted: selected=%d', len(links))
            if not links:
                all_links = extract_links(raw, url, '0001-01-01', '9999-12-31')
                if not all_links:
                    raise ValueError('一覧HTMLから対象店舗の日別リンクを確認できませんでした。保存した一覧HTMLでも確認してください。')
                self.events.put(('log', f'一覧の掲載範囲：{all_links[0].day}〜{all_links[-1].day}。指定期間のリンクは0件です。'))
            return key, links
        self.launch(work, 'scan')

    def start(self):
        if self.busy or not self.links or self.scan_key != self.key():
            return
        folder = self.folder.get().strip()
        if not folder:
            messagebox.showerror('保存先を確認してください', 'HTML保存先を指定してください。', parent=self)
            return
        start, end = date_range(self.scan_key[1], self.scan_key[2])
        self.cancel_browser_idle()
        links = tuple(self.links)
        self.paths = []
        self.status.set(f'{start}〜{end}の{len(links)}日分を取得します。')
        self.launch(lambda: self.with_client(lambda engine: download(links, start, end, folder, engine,
                    lambda text: self.events.put(('log', text))), self.scan_key[5]), 'download')

    def stop(self):
        self.cancel.set()
        self.status.set('停止を待っています。通信中の場合はタイムアウトまで待つことがあります。')

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                LOGGER.info('UI event: %s', kind)
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
                    if self.browser_engine and self.links:
                        self.cancel_browser_idle()
                        self.browser_idle_after = self.after(55000, self.expire_browser)
                        self.status.set(self.status.get() + ' 同じブラウザで続行します。55秒以内に取得を開始してください。')
                    LOGGER.info('UI scan complete: rows=%d', len(self.links))
                    self.deiconify()
                    self.lift()
                    if not self.links:
                        self.close_browser()
                        messagebox.showwarning('指定期間のリンクがありません', '指定期間のリンクは0件です。ログの掲載範囲を確認してください。', parent=self)
                elif kind == 'download':
                    self.paths = list(data.paths)
                    if self.scan_key and self.scan_key[5] == BROWSER and not self.scan_key[3]:
                        self.scan_key = None
                    self.status.set(f'新規取得{data.downloaded}件・保存済み{data.skipped}件・失敗{data.failed}件。' + data.stopped)
                    self.set_busy(False)
                    LOGGER.info('download finished: new=%d saved=%d failed=%d stopped=%s',
                                data.downloaded, data.skipped, data.failed, bool(data.stopped))
                    if data.stopped and not self.cancel.is_set():
                        self.show_stop(data.stopped)
                    elif data.failed:
                        self.deiconify()
                        self.lift()
                    elif self.paths and not self.cancel.is_set():
                        # 最後まで取れたら、取得画面を閉じて変換画面へ渡す（2026-11-06 利用者「データ取得終わったら
                        # 閉じるように」。取得ブラウザは取得の処理の終わりで閉じ済み）。失敗・停止のときは残して理由を見せる。
                        self.after_idle(self.use)
                elif kind == 'error':
                    self.scan_key = None
                    self.status.set('処理を停止しました：' + data)
                    self.set_busy(False)
                    self.close_browser()
                    if not self.cancel.is_set():
                        self.show_stop(data)
        except queue.Empty:
            pass
        except Exception as exc:
            LOGGER.exception('UI result processing failed')
            self.status.set('画面への反映に失敗しました：' + str(exc))
            self.set_busy(False)
            self.close_browser()
            self.show_stop('画面への反映に失敗しました：' + str(exc))
        finally:
            if self.winfo_exists():
                self.after_id = self.after(100, self.poll)

    def show_stop(self, reason):
        self.log.configure(state='normal')
        self.log.insert('end', '処理を停止しました：' + reason + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')
        self.deiconify()
        self.lift()
        messagebox.showwarning('HTML取得を停止しました', reason, parent=self)

    def destroy(self):
        self.cancel.set()
        self.cancel_browser_idle()
        if not self.busy:
            self.close_browser()
        if getattr(self, 'after_id', None):
            self.after_cancel(self.after_id)
            self.after_id = None
        super().destroy()

    def use(self):
        if self.busy or not self.paths or not self.winfo_exists():
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
