"""Sequential, cancellable download service. No DB/Cookie writes or retries."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import random
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from anaslo_html import parse_html
from anaslo_index import canonical_url, date_range, link_day

MAX_BYTES = 16 * 1024 * 1024


class Stopped(Exception):
    pass


class AccessStopped(Stopped):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Validate BEFORE sending each redirect request.


class Client:
    def __init__(self, cancel=None, opener=None, clock=time.monotonic, jitter=None):
        self.cancel = cancel if cancel is not None else threading.Event()
        self.opener = opener or build_opener(NoRedirect())
        self.clock = clock
        self.jitter = jitter or (lambda: random.uniform(5.0, 8.0))
        self.next_request = 0.0

    def check(self):
        if self.cancel.is_set():
            raise Stopped('利用者が停止しました。')

    def _pace(self):
        self.check()
        delay = max(0.0, self.next_request - self.clock())
        if self.cancel.wait(delay):
            self.check()
        self.next_request = self.clock() + max(5.0, min(8.0, self.jitter()))

    def get(self, url, *, index=False):
        original = canonical_url(url, index=index)
        current = original
        for hop in range(4):
            self._pace()
            request = Request(current, headers={
                'User-Agent': 'database-html-converter/1.0 (Windows; manual date range)',
                'Accept': 'text/html,application/xhtml+xml', 'Accept-Encoding': 'identity'})
            try:
                with self.opener.open(request, timeout=15) as response:
                    # Default redirects are disabled; still reject an unexpected final URL.
                    if canonical_url(response.geturl(), index=index) != original:
                        raise AccessStopped('予期しない移動先のため停止しました。')
                    if response.status != 200:
                        raise ValueError(f'HTTP {response.status}')
                    if response.headers.get_content_type() not in ('text/html', 'application/xhtml+xml'):
                        raise ValueError('HTMLではない応答です。')
                    parts, size = [], 0
                    while True:
                        self.check()
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError('HTMLが16MiBを超えたため停止しました。')
                        parts.append(chunk)
                    raw = b''.join(parts)
                    length = response.headers.get('Content-Length')
                    if length is not None and (not length.isdigit() or int(length) != size):
                        raise ValueError('受信HTMLの長さが一致しません。')
                    lower = raw.lower()
                    if any(marker in lower for marker in (b'cf-chl-', b'captcha', b'just a moment...', b'verify you are human')):
                        raise AccessStopped('認証・アクセス確認ページのため停止しました。')
                    return raw
            except HTTPError as exc:
                try:
                    if exc.code in (401, 403, 429):
                        retry = exc.headers.get('Retry-After', '')
                        raise AccessStopped(f'HTTP {exc.code}：取得を停止しました。' + (f' Retry-After: {retry}' if retry else '')) from exc
                    if exc.code in (301, 302, 303, 307, 308) and hop < 3:
                        if not exc.headers.get('Location'):
                            raise AccessStopped('転送先が不明なため停止しました。')
                        try:
                            destination = canonical_url(urljoin(current, exc.headers.get('Location', '')), index=index)
                        except (ValueError, UnicodeError) as error:
                            raise AccessStopped('対象外への転送のため停止しました。') from error
                        if destination != original:
                            raise AccessStopped('別の日付・ページへの転送のため停止しました。')
                        current = destination
                        continue
                    if exc.code in (301, 302, 303, 307, 308):
                        raise AccessStopped('転送回数の上限に達しました。')
                    raise
                finally:
                    exc.close()
        raise AccessStopped('転送回数の上限に達しました。')


def check_html(raw, filename, day):
    data = parse_html(raw, filename)
    if data['day'] != day or data['store']['source_name'] != 'P-STATION&IIスロット館':
        raise ValueError('指定した日付・店舗とHTMLの内容が一致しません。')
    if link_day(data['source']['url']) != day:
        raise ValueError('日別HTMLの出典URLを確認できません。')
    return data


def cache_name(item):
    return f'{item.day}-p-station-{hashlib.sha256(item.url.encode()).hexdigest()[:12]}.html'


@contextmanager
def folder_lock(folder):
    # OS locks are released on process exit; a retained lock file cannot block resume.
    with (folder / '.download.lock').open('a+b') as lock:
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('この保存先では別の取得処理が動作中です。') from exc
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def write_atomic(path, raw, *, replace=False):
    # A same-directory temporary file is never mistaken for completed HTML.
    fd, name = tempfile.mkstemp(prefix='.download-', suffix='.part', dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(tmp, path)
        elif os.name == 'nt':
            os.rename(tmp, path)  # Windows refuses an existing destination.
        else:
            os.link(tmp, path)  # Exclusive destination creation on POSIX.
    finally:
        tmp.unlink(missing_ok=True)


@dataclass
class Result:
    paths: list = field(default_factory=list)
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    stopped: str = ''


def download(links, start, end, folder, client, progress=lambda message: None):
    start, end = date_range(start, end)
    links = list(links)
    if not links:
        raise ValueError('指定期間に取得対象がありません。')
    if len({item.day for item in links}) != len(links):
        raise ValueError('取得対象の日付が重複しています。')
    # Independently enforce the interval at the network boundary, even if a UI is wrong.
    for item in links:
        if not start <= item.day <= end or link_day(item.url) != item.day:
            raise ValueError('指定期間外または日付が不一致のURLが含まれています。')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = Result()
    with folder_lock(folder):
        manifest_path = folder / 'download-manifest.json'
        manifest = {'format': 'anaslo-downloads', 'version': 1, 'entries': {}}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if (not isinstance(manifest, dict) or manifest.get('format') != 'anaslo-downloads' or
                    manifest.get('version') != 1 or not isinstance(manifest.get('entries'), dict) or
                    any(not isinstance(entry, dict) for entry in manifest['entries'].values())):
                raise ValueError('取得記録の形式が違います。保存先を確認してください。')
        existing = {}
        for path in list(folder.glob('*.html')) + list(folder.glob('*.htm')):
            # Include manually saved date-named HTML, not just our cache filename.
            day = path.name[:10].replace('_', '-')
            existing.setdefault(day, []).append(path)
        consecutive = 0
        for position, item in enumerate(sorted(links, key=lambda x: x.day), 1):
            entry = {**manifest['entries'].get(item.url, {}), 'day': item.day, 'url': item.url}
            try:
                client.check()
                path = folder / cache_name(item)
                candidates = sorted(existing.get(item.day, []))
                if path.exists() and path not in candidates:
                    candidates.insert(0, path)
                valid = None
                errors = []
                for candidate in candidates:
                    try:
                        if candidate.stat().st_size > MAX_BYTES:
                            raise ValueError('既存HTMLが大きすぎます。')
                        candidate_raw = candidate.read_bytes()
                        check_html(candidate_raw, candidate.name, item.day)
                        prior = manifest['entries'].get(item.url, {})
                        digest = hashlib.sha256(candidate_raw).hexdigest()
                        if prior.get('file') == candidate.name and prior.get('sha256') and prior['sha256'] != digest:
                            raise ValueError('取得記録と既存HTMLのハッシュが一致しません。')
                        valid = candidate
                        break
                    except (OSError, ValueError, UnicodeError) as exc:
                        errors.append(str(exc))
                if valid is not None:
                    path = valid
                    status = 'existing'
                elif candidates:
                    raise ValueError('既存HTMLが不正です。上書きせず保留します：' + '; '.join(errors))
                else:
                    raw = client.get(item.url)
                    client.check()
                    check_html(raw, path.name, item.day)
                    write_atomic(path, raw)
                    digest = hashlib.sha256(raw).hexdigest()
                    status = 'downloaded'
                result.paths.append(path)
                if status == 'existing':
                    result.skipped += 1
                else:
                    result.downloaded += 1
                entry.update(status=status, file=path.name, sha256=digest)
                entry.pop('error', None)
                consecutive = 0
                progress(f'[{position}/{len(links)}] {item.day}：' + ('保存済みを使用' if status == 'existing' else '取得しました'))
            except Stopped as exc:
                result.stopped = str(exc)
                entry.update(status='stopped', error=str(exc))
            except (HTTPError, URLError, HTTPException, TimeoutError, OSError, ValueError, UnicodeError) as exc:
                result.failed += 1
                entry.update(status='failed', error=str(exc))
                progress(f'[{position}/{len(links)}] {item.day}：失敗 {exc}')
                # 404 is a per-page absence. Connection/server errors accumulate.
                if not isinstance(exc, HTTPError) or exc.code != 404:
                    consecutive += 1
                else:
                    consecutive = 0
                if consecutive >= 3:
                    result.stopped = '連続3件のエラーで停止しました。'
            manifest['entries'][item.url] = entry
            write_atomic(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'), replace=True)
            if result.stopped:
                progress(result.stopped)
                break
    return result
