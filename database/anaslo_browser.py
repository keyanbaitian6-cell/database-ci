"""Visible WebView2 capture in a dedicated process/profile; no Chrome Cookie access."""
import multiprocessing
from pathlib import Path
import time
from urllib.error import HTTPError

from anaslo_download import AccessStopped, Client, MAX_BYTES, Stopped, folder_lock, reject_access_check
from anaslo_index import canonical_url


class BrowserSession:
    def __init__(self, profile):
        from anaslo_browser_host import run_host
        self.closed = False
        self.confirmed = False
        self.process = None
        self.connection = None
        self.lock = None
        profile = Path(profile)
        profile.mkdir(parents=True, exist_ok=True)
        self.lock = folder_lock(profile)
        self.lock.__enter__()
        try:
            context = multiprocessing.get_context('spawn')
            parent, child = context.Pipe()
            self.connection = parent
            self.process = context.Process(target=run_host, args=(child, str(profile)), daemon=True)
            self.process.start()
            child.close()
        except Exception:
            self.close()
            raise

    def request(self, url, index, cancel, progress):
        try:
            self.connection.send({'kind': 'get', 'url': url, 'index': index})
        except (EOFError, OSError) as exc:
            raise Stopped('取得ブラウザが閉じられました。') from exc
        deadline = time.monotonic() + (300 if not self.confirmed else 45)
        while time.monotonic() < deadline:
            if cancel.is_set():
                raise Stopped('利用者が停止しました。')
            if self.connection.poll(0.1):
                try:
                    message = self.connection.recv()
                except (EOFError, OSError) as exc:
                    raise Stopped('取得ブラウザが閉じられました。') from exc
                if message.get('kind') == 'progress':
                    progress(message['text'])
                elif message.get('kind') == 'snapshot':
                    self.confirmed = True
                    return message
                elif message.get('kind') == 'http_error':
                    raise HTTPError(url, int(message['status']), message['text'], None, None)
                elif message.get('kind') == 'error':
                    raise AccessStopped(message['text'])
            if not self.process.is_alive():
                raise Stopped('取得ブラウザが閉じられました。')
        raise Stopped('ブラウザの表示・確認待ち時間を超えたため停止しました。')

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.connection:
                try:
                    self.connection.send({'kind': 'close'})
                except (OSError, EOFError):
                    pass
            if self.process and self.process.pid:
                self.process.join(3)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(2)
        finally:
            if self.connection:
                self.connection.close()
            if self.lock:
                self.lock.__exit__(None, None, None)
                self.lock = None


class BrowserClient(Client):
    def __init__(self, profile, cancel=None, progress=lambda text: None, session_factory=BrowserSession, **kwargs):
        super().__init__(cancel=cancel, **kwargs)
        self.profile = Path(profile)
        self.progress = progress
        self.session_factory = session_factory
        self.session = None

    def get(self, url, *, index=False):
        target = canonical_url(url, index=index)
        self._pace()
        try:
            if self.session is None:
                self.session = self.session_factory(self.profile)
            try:
                snapshot = self.session.request(target, index, self.cancel, self.progress)
            finally:
                self._rest()  # 表示し終えた時刻から次まで5〜8秒（Client._rest）
            if not isinstance(snapshot, dict):
                raise AccessStopped('ブラウザからの読み取り結果が不正です。')
            if snapshot.get('status') != 200:
                raise AccessStopped(f'HTTP {snapshot.get("status", "不明")}：取得を停止しました。')
            if canonical_url(snapshot.get('url', ''), index=index) != target:
                raise AccessStopped('表示中のURLと取得対象が一致しないため停止しました。')
            text = snapshot.get('html')
            if not isinstance(text, str) or not text:
                raise AccessStopped('表示済みHTMLを取得できませんでした。')
            raw = text.encode('utf-8')
            if len(raw) > MAX_BYTES:
                raise AccessStopped('HTMLが16MiBを超えたため停止しました。')
            reject_access_check(raw, target, index=index)
            return raw
        except HTTPError as exc:
            # Keep the visible session for the next selected date; the common
            # downloader handles 404 and consecutive server errors.
            exc.close()
            raise
        except Stopped:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise AccessStopped('ブラウザ取得を停止しました：' + str(exc)) from exc

    def close(self):
        if self.session:
            self.session.close()
            self.session = None
