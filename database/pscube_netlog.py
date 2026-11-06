"""P’s CUBE 取り込み窓の通信の診断記録（2026-11-06、PCだけ）。

目的：最近、取り込みを始めて8〜17分で403・データ不表示で止まる。「保存件数に出ない通信が増えたのか」を、
増えていない可能性も含めて判定できるよう、取り込み窓（WebView2）が実際に出した要求を、種類・状態ごとに数える。

仕組み（サイトへの通信は増やさない）：
- WebView2 の DevTools Protocol（CDP）の Network の通知を受け取るだけ（`Network.enable`。ブラウザの中の通知で、
  サイトへの要求・再読み込み・確認のアクセスは出さない。キャッシュの無効化 `Network.setCacheDisabled` などは使わない）。
  要求ごとの requestId で、同じ要求の重複した通知・リダイレクトの段・キャッシュからの応答・失敗を分ける。
- ページの移動は WebView2 の NavigationStarting / NavigationCompleted（NavigationId）。移動の理由は、アプリが
  直前に決めたこと（次のページ・一覧の読み込み直し・休憩・再開・「もう一度開く」）と突き合わせる。
- アプリの状態（自動取り込みのON/OFF・休憩中・完了・保存中）、保存の開始と結果、休憩中の画面への切替と確認、
  表示の文（データが出ない＝DOMの判定など）は、取り込み窓の処理から直接書く。

軽くする・安全にする：
- 通知の受け口（WebView2 のUIスレッド）では、受け取った文字列と時刻・状態を待ち行列に積むだけ。解析・集計・書き込みは
  別のスレッド。待ち行列があふれたら捨てて、捨てた数を残す。書き込みに失敗しても取り込みは止めない。
- 残すのはホスト・パスと、ページを見分ける問い合わせの値（`cd_ps`・`cd_dai`・`bai`・`nmk_kisyu`・`YMD_biz`）だけ。
  ほかの問い合わせ（`apikey`・`_i`・`_t` など）は名前だけで、値は残さない。#以降も残さない。Cookie・ヘッダー・
  送った本文（`maxPostDataSize: 0`）・応答の本文は受け取らない／残さない。
- 1回の窓で1ファイル（`data/pscube_netlog/net-<開始時刻>-<識別子>.jsonl`）。1ファイル8MiBまで（超えたら要求ごとの行は
  やめ、集計だけ続ける）。新しい10回分・合計40MiBまで残し、古いものから消す。窓を閉じたら同じ名前の
  `-summary.txt` に集計を書く。

測れないこと（集計にも書く）：
- CDPの通知は WebView2 が出した要求の記録で、回線に出たパケットそのものではない。キャッシュの判定は CDP の
  `fromDiskCache`・`requestServedFromCache`・受信バイト数による。Service Worker・プリフェッチの扱いは通知の範囲まで。
- 呼び出し元（initiator のスタック）は、WebView2 ではいちばん上の1段しか残らない（2026-11-06、実WebView2の
  確認試験 tests/smoke_pscube_netlog.py で確認）。全段を残すにはデバッガー系の機能を有効にする必要があるが、
  サイトから自動操作のしるしとして検知されうるので使わない。アプリの差枚取得はサイトの jQuery.ajax を通るので、
  いちばん上はサイトのスクリプトになり、呼び出し元からはアプリかサイト自身かを分けられない。
  そのため差枚APIは、アプリのスクリプト（evaluate_js で入れたので URL が空）が直接送ったと分かるものだけ
  「アプリ」、ほかは「呼び出し元不明」とする。「サイト自身」とは言い切らない。代わりに、アプリが保存の記録に
  残した「差枚を取りに行った回数」（台別ページ1回の保存につき0か1回）と並べ、要求の数との差を見る。
- 定期通信（jquery.netcube.alive.js）は、スクリプトの読み込みでは数えない。そのスクリプトが呼び出し元（上の1段）に
  なった要求を「定期」と数える。alive.js が jQuery を通して送ると上の1段は jQuery になり「サイト自身のデータ通信」に
  入るので、集計の「データ通信の宛先ごと」の件数から読み取る。送信先・周期はここで決めつけない。
- `Network.enable` の前に始まった要求（窓を開いた直後の最初のページの一部）は取り逃しうる。
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

DIR_NAME = 'pscube_netlog'
MAX_FILE_BYTES = 8 * 1024 * 1024
KEEP_FILES = 10
KEEP_TOTAL_BYTES = 40 * 1024 * 1024
QUEUE_SIZE = 50000
# ページを見分ける問い合わせ。これ以外の値は残さない（apikey・_i・_t などの秘密を含むため）。
KEEP_QUERY = ('cd_ps', 'cd_dai', 'bai', 'nmk_kisyu', 'YMD_biz')
SITE_HOST = 'www.pscube.jp'
NET_API = 'nc-m06-003.php'
PAGE_NAMES = ('nc-v03-001.php', 'nc-v05-011.php', 'nc-v06-001.php')
YOUTUBE_HOSTS = ('youtube.com', 'youtube-nocookie.com', 'youtu.be', 'ytimg.com', 'googlevideo.com')
CDP_EVENTS = ('Network.requestWillBeSent', 'Network.requestServedFromCache', 'Network.responseReceived',
              'Network.loadingFinished', 'Network.loadingFailed', 'Network.webSocketCreated')
DATA_TYPES = ('XHR', 'Fetch', 'EventSource', 'WebSocket', 'Ping', 'Preflight', 'CSPViolationReport', 'Other')
RESOURCE_TYPES = ('Script', 'Stylesheet', 'Image', 'Font', 'Media', 'Manifest', 'TextTrack', 'Prefetch',
                  'SignedExchange')
# 集計の分類（表の列の順）。
CATEGORIES = ('page', 'page_other', 'api_app', 'api_unknown', 'site_periodic', 'site_data',
              'resource', 'third_party_data', 'third_party_resource', 'youtube_local', 'unknown')
CATEGORY_LABELS = {
    'page': 'ページ本体（P’s CUBEの対象ページ）', 'page_other': 'ページ本体（対象外のページ・同意画面など）',
    'api_app': '差枚API（アプリのスクリプトが直接送った）',
    'api_unknown': '差枚API（呼び出し元はスタックから分からない）', 'site_periodic': 'サイトの定期通信（alive.jsが呼び出し元）',
    'site_data': 'サイト自身のデータ通信（そのほか）', 'resource': 'サイトの資源（JS・CSS・画像など）',
    'third_party_data': '他のサイトへのデータ通信', 'third_party_resource': '他のサイトの資源',
    'youtube_local': 'YouTube（アプリが手元で止める。送らない）', 'unknown': '分類できない要求'}
# before：窓を開いてから最初に自動ONになるまで（手動の保存を含む）。ONのあとのOFFと分け、「OFFのあとに残る通信」に
# 窓を開いた直後の読み込みを混ぜない（2026-11-06、実サイトの試しで、開いた直後の読み込みがOFFの欄に入っていた）。
STATES = ('before', 'on', 'off', 'rest', 'done')
STATE_LABELS = {'before': '自動ONの前（窓を開いてから最初のONまで。手動の保存を含む）', 'on': '自動ON',
                'off': '自動OFF（ONのあと）', 'rest': '休憩中', 'done': '完了・停止のあと'}


def safe_url(url):
    """記録してよい形のURL：{'host', 'path', 'q'（ページを見分ける値だけ）, 'drop'（値を残さなかった問い合わせの名前）}。"""
    text = str(url or '')
    if text.startswith(('data:', 'blob:')):
        return {'host': '', 'path': text.split(':', 1)[0] + ':', 'q': {}, 'drop': []}
    try:
        parts = urlsplit(text)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return {'host': '', 'path': '(読めないURL)', 'q': {}, 'drop': []}
    q = {k: v[:80] for k, v in pairs if k in KEEP_QUERY}
    drop = sorted({k[:40] for k, _ in pairs if k not in KEEP_QUERY})
    host = (parts.hostname or '').lower()
    path = parts.path[:200] if parts.scheme in ('http', 'https') else (parts.scheme + ':' + parts.path[:40])
    return {'host': host, 'path': path, 'q': q, 'drop': drop}


def url_key(url):
    """同じページかの比較用（#以降を除く。秘密の値は含めない）。"""
    s = safe_url(url)
    return s['host'] + s['path'] + '?' + '&'.join(f'{k}={v}' for k, v in sorted(s['q'].items()))


def _is_youtube(host):
    return any(host == h or host.endswith('.' + h) for h in YOUTUBE_HOSTS)


def initiator_summary(initiator):
    """呼び出し元：{'type', 'script'（いちばん上のURLのあるスクリプトのパス）, 'app'（アプリのスクリプトか。不明はNone）}。
    WebView2 のスタックは上の1段だけのことがある。URL の空の段（アプリのスクリプト）があればアプリと分かるが、
    無くても「アプリでない」とは言えない（アプリがサイトの関数を呼んだ場合、上の1段はサイトのスクリプト）。"""
    if not isinstance(initiator, dict):
        return {'type': None, 'script': None, 'app': None}
    frames = []
    stack = initiator.get('stack')
    while isinstance(stack, dict):
        frames.extend(f for f in stack.get('callFrames') or [] if isinstance(f, dict))
        stack = stack.get('parent')
    script = next((safe_url(f.get('url')) for f in frames if f.get('url')), None)
    scripts = [safe_url(f.get('url'))['path'] for f in frames if f.get('url')]
    # アプリのスクリプト（evaluate_js で入れた取り込みの処理）は URL が空になる。空の段が無ければ不明（None）。
    app = True if any(not f.get('url') for f in frames) else None
    if script is None and initiator.get('url'):
        script = safe_url(initiator.get('url'))
    return {'type': initiator.get('type'), 'script': (script['host'] + script['path']) if script else None,
            'app': app, 'alive': any('alive' in p for p in scripts) or None}


def classify(host, path, rtype, init):
    if _is_youtube(host):
        return 'youtube_local'
    if host != SITE_HOST and not host.endswith('.pscube.jp') and host != 'pscube.jp':
        if rtype in DATA_TYPES:
            return 'third_party_data'
        return 'third_party_resource' if rtype in RESOURCE_TYPES or rtype == 'Document' else 'unknown'
    name = path.rsplit('/', 1)[-1]
    if name == NET_API:
        return 'api_app' if init.get('app') else 'api_unknown'
    if rtype == 'Document':
        return 'page' if name in PAGE_NAMES or path.endswith('/c740601/') else 'page_other'
    if rtype in DATA_TYPES:
        return 'site_periodic' if init.get('alive') else 'site_data'
    if rtype in RESOURCE_TYPES:
        return 'resource'
    return 'unknown'


def code_version(root=None):
    """使った版：git のコミット（取れれば）と、取り込みのファイルの中身のハッシュ。"""
    root = Path(root or Path(__file__).resolve().parent)
    digest = hashlib.sha256()
    for name in ('pscube_import.py', 'pscube_netlog.py', 'pscube_connection.py', 'assets/pscube_capture.js',
                 'assets/pscube_auto_probe.js'):
        try:
            digest.update((root / name).read_bytes())
        except OSError:
            digest.update(b'-')
    info = {'files_sha256': digest.hexdigest()[:16], 'commit': None, 'dirty': None}
    try:
        run = dict(cwd=str(root), capture_output=True, text=True, timeout=3,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        info['commit'] = subprocess.run(['git', 'rev-parse', '--short=12', 'HEAD'], **run).stdout.strip() or None
        status = subprocess.run(['git', 'status', '--porcelain', '--', '.'], **run).stdout
        info['dirty'] = bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return info


class NetLog:
    """1つの取り込み窓の診断記録。受け口（cdp・nav_*・event）は積むだけで、すぐ返る。"""

    def __init__(self, data_dir, *, clock=time.time, version=None, max_file_bytes=MAX_FILE_BYTES,
                 keep_files=KEEP_FILES, keep_total_bytes=KEEP_TOTAL_BYTES, queue_size=QUEUE_SIZE, start=True):
        self.clock = clock
        self.started = clock()
        stamp = datetime.fromtimestamp(self.started).strftime('%Y%m%d-%H%M%S')
        self.session = stamp + '-' + os.urandom(3).hex()
        self.dir = Path(data_dir) / DIR_NAME
        self.path = self.dir / f'net-{self.session}.jsonl'
        self.summary_path = self.dir / f'net-{self.session}-summary.txt'
        self.max_file_bytes, self.keep_files, self.keep_total_bytes = max_file_bytes, keep_files, keep_total_bytes
        self.queue = queue.Queue(maxsize=queue_size)
        self.state = 'before'       # STATES のどれか（受け口から属性を読むだけ）
        self.ever_on = False
        self.saving = False
        self.dropped = 0
        self.write_failed = None
        self.written = 0
        self.truncated = False
        self._version = version
        self._requests = {}
        self._intents = []
        self._navs = {}
        self.totals = Totals()
        self._file = None
        self._thread = None
        self._stopped = threading.Event()
        if start:
            self._thread = threading.Thread(target=self._run, name='pscube-netlog', daemon=True)
            self._thread.start()

    # ---- 受け口（どのスレッドからでも。重い処理をしない） ----
    def _put(self, item):
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def cdp(self, name, params_json):
        self._put(('cdp', self.clock(), self.state, self.saving, name, params_json))

    def nav_start(self, navigation_id, uri, redirected=None, kind=None):
        self._put(('nav', self.clock(), self.state, self.saving, navigation_id, str(uri), redirected, kind))

    def nav_done(self, navigation_id, success, web_error=None, http_status=None):
        self._put(('nav_done', self.clock(), self.state, self.saving, navigation_id, success, web_error, http_status))

    def event(self, name, /, **fields):
        self._put(('event', self.clock(), self.state, self.saving, name, fields))

    def intent(self, reason, url=None):
        """アプリが次に開く（読み込み直す）ページと理由。次の NavigationStarting と突き合わせる。"""
        self._put(('intent', self.clock(), self.state, self.saving, reason, None if url is None else str(url)))

    def set_state(self, state, saving=None):
        if saving is not None:
            self.saving = bool(saving)
        if state == 'on':
            self.ever_on = True
        elif state == 'off' and not self.ever_on:
            state = 'before'
        if state != self.state:
            self.state = state
            self.event('state', to=state)

    def close(self, timeout=5):
        self.event('session_end', dropped=self.dropped)
        self._put(None)
        if self._thread is not None:
            self._thread.join(timeout)
        else:
            self.drain()

    # ---- 書く側（別スレッド） ----
    def _run(self):
        self._write({'ev': 'session_start', 'session': self.session, 'pid': os.getpid(),
                     'version': self._version if self._version is not None else code_version(),
                     'note': 'CDP Network の通知・WebView2の移動・アプリの状態の記録。秘密の値・本文は残さない'},
                    self.started)
        self._prune()
        while self.drain(block=True):
            pass

    def drain(self, block=False):
        """待ち行列を処理する。終わりの印（None）を受けたら集計を書いて False。"""
        while True:
            try:
                item = self.queue.get(timeout=1) if block else self.queue.get_nowait()
            except queue.Empty:
                self._flush()
                return True
            if item is None:
                self._finish()
                return False
            try:
                self._handle(item)
            except Exception as error:  # noqa: BLE001 - 1件の失敗で記録全体を止めない
                self._write({'ev': 'log_error', 'error': type(error).__name__ + ': ' + str(error)[:200]}, self.clock())

    def _handle(self, item):
        kind, at, state, saving = item[:4]
        if kind == 'cdp':
            name, raw = item[4], item[5]
            params = json.loads(raw) if isinstance(raw, str) else (raw or {})
            self._cdp(name, params if isinstance(params, dict) else {}, at, state, saving)
        elif kind == 'nav':
            nav_id, uri, redirected, nav_kind = item[4:]
            reason = self._match_intent(uri, at)
            safe = safe_url(uri)
            self._navs[nav_id] = {'at': at, 'reason': reason}
            self.totals.nav(reason, safe, state)
            self._write({'ev': 'nav', 'nav': nav_id, 'url': safe, 'redirected': redirected, 'kind': nav_kind,
                         'reason': reason, 'state': state}, at)
        elif kind == 'nav_done':
            nav_id, success, web_error, http_status = item[4:]
            start = self._navs.pop(nav_id, None)
            self.totals.nav_done(success, web_error, http_status)
            self._write({'ev': 'nav_done', 'nav': nav_id, 'ok': success, 'web_error': web_error,
                         'http': http_status, 'ms': round((at - start['at']) * 1000) if start else None,
                         'state': state}, at)
        elif kind == 'intent':
            reason, url = item[4:]
            self._intents.append({'at': at, 'reason': reason, 'key': None if url is None else url_key(url)})
            self._intents = self._intents[-8:]
            self._write({'ev': 'intent', 'reason': reason, 'url': None if url is None else safe_url(url),
                         'state': state}, at)
        elif kind == 'event':
            name, fields = item[4], item[5]
            self.totals.event(name, fields, state, at)
            self._write({'ev': name, 'state': state, 'saving': saving, **fields}, at)

    def _match_intent(self, uri, at):
        key = url_key(uri)
        for i in range(len(self._intents) - 1, -1, -1):
            intent = self._intents[i]
            if at - intent['at'] > 60:
                break
            if intent['key'] is None or intent['key'] == key or intent['reason'] == 'rest':
                if intent['reason'] == 'rest' and not str(uri).startswith(('about:', 'data:')):
                    continue
                del self._intents[i]
                return intent['reason']
        return 'site_or_user'   # アプリが決めていない移動（サイトのJS・利用者の操作・サイトの転送など）

    def _cdp(self, name, p, at, state, saving):
        rid = p.get('requestId')
        if name == 'Network.requestWillBeSent':
            request = p.get('request') or {}
            known = self._requests.get(rid)
            if known is not None and not p.get('redirectResponse'):
                self.totals.duplicate_notices += 1   # 同じ要求の通知が重ねて来た（数えない）
                return
            if known is not None:
                # リダイレクト：前の段を閉じて、同じ requestId の次の段を数える。
                hop = p['redirectResponse']
                known['status'] = hop.get('status')
                known['redirect'] = True
                self._close(rid, at, 'redirect')
            init = initiator_summary(p.get('initiator'))
            safe = safe_url(request.get('url'))
            rtype = p.get('type') or 'Other'
            self._requests[rid] = {
                'id': hashlib.sha1(str(rid).encode()).hexdigest()[:10], 'at': at, 'state': state, 'saving': saving,
                'type': rtype, 'cat': classify(safe['host'], safe['path'], rtype, init), 'url': safe,
                'method': request.get('method'), 'post': bool(request.get('hasPostData')), 'init': init,
                'hop': (known or {}).get('hop', 0) + (1 if known else 0), 'status': None, 'cache': None,
                'bytes': None, 'error': None, 'redirect': False}
        elif name == 'Network.webSocketCreated':
            safe = safe_url(p.get('url'))
            self._requests[rid] = {'id': hashlib.sha1(str(rid).encode()).hexdigest()[:10], 'at': at, 'state': state,
                                   'saving': saving, 'type': 'WebSocket', 'url': safe,
                                   'cat': classify(safe['host'], safe['path'], 'WebSocket', initiator_summary(p.get('initiator'))),
                                   'method': None, 'post': False, 'init': initiator_summary(p.get('initiator')),
                                   'hop': 0, 'status': None, 'cache': None, 'bytes': None, 'error': None, 'redirect': False}
            self._close(rid, at, 'websocket')
        elif rid in self._requests:
            r = self._requests[rid]
            if name == 'Network.requestServedFromCache':
                r['cache'] = 'memory'
            elif name == 'Network.responseReceived':
                response = p.get('response') or {}
                r['status'] = response.get('status')
                if response.get('fromDiskCache'):
                    r['cache'] = 'disk'
                elif response.get('fromServiceWorker'):
                    r['cache'] = 'service_worker'
                elif response.get('fromPrefetchCache'):
                    r['cache'] = 'prefetch'
            elif name == 'Network.loadingFinished':
                r['bytes'] = p.get('encodedDataLength')
                self._close(rid, at, 'finished')
            elif name == 'Network.loadingFailed':
                r['error'] = (p.get('errorText') or '')[:80] or None
                r['canceled'] = bool(p.get('canceled'))
                r['blocked'] = p.get('blockedReason')
                self._close(rid, at, 'failed')
        else:
            self.totals.orphan_notices += 1   # 始まりを見ていない要求の通知（Network.enable の前に始まったなど）

    def _close(self, rid, at, how):
        r = self._requests.pop(rid, None) if how != 'redirect' else dict(self._requests[rid])
        if r is None:
            return
        r['how'] = how
        r['ms'] = round((at - r['at']) * 1000)
        r['end_state'] = self.state
        self.totals.request(r, at)
        self._write({'ev': 'req', **{k: v for k, v in r.items() if k != 'at'}}, r['at'])

    def _finish(self):
        for rid in list(self._requests):
            self._close(rid, self.clock(), 'unfinished')
        self.totals.dropped = self.dropped
        self._write({'ev': 'session_totals', 'dropped': self.dropped, 'written': self.written,
                     'truncated': self.truncated, 'write_failed': self.write_failed}, self.clock())
        self._flush()
        try:
            if self._file is not None:
                self._file.close()
        except OSError:
            pass
        self._file = None
        try:
            text = format_summary(self.totals.result(self.session, self.started, self.clock()))
            self.summary_path.write_text(text, encoding='utf-8')
        except Exception as error:  # noqa: BLE001 - 集計を書けなくても取り込みには関係しない
            self.write_failed = self.write_failed or f'{type(error).__name__}: {error}'

    def _write(self, record, at):
        if self.write_failed is not None:
            return
        if self.truncated and record.get('ev') == 'req':
            return
        try:
            if self._file is None:
                self.dir.mkdir(parents=True, exist_ok=True)
                self._file = open(self.path, 'a', encoding='utf-8')
            line = json.dumps({'t': datetime.fromtimestamp(at).isoformat(timespec='milliseconds'), **record},
                              ensure_ascii=False, separators=(',', ':')) + '\n'
            if self.written + len(line.encode('utf-8')) > self.max_file_bytes and record.get('ev') == 'req':
                self.truncated = True
                line = json.dumps({'t': datetime.fromtimestamp(at).isoformat(timespec='milliseconds'),
                                   'ev': 'truncated', 'note': '容量の上限。ここからは要求ごとの行を書かず、集計だけ続ける'},
                                  ensure_ascii=False) + '\n'
            self._file.write(line)
            self.written += len(line.encode('utf-8'))
        except Exception as error:  # noqa: BLE001 - 記録に失敗しても取り込みは止めない（以後は書かない）
            self.write_failed = f'{type(error).__name__}: {str(error)[:200]}'
            try:
                if self._file is not None:
                    self._file.close()
            except Exception:  # noqa: BLE001
                pass
            self._file = None

    def _flush(self):
        try:
            if self._file is not None:
                self._file.flush()
        except OSError as error:
            self.write_failed = self.write_failed or f'{type(error).__name__}: {error}'

    def _prune(self):
        """新しい keep_files 回分・合計 keep_total_bytes までを残し、古い記録から消す（この窓の分は消さない）。"""
        try:
            sessions = {}
            for path in self.dir.glob('net-*'):
                sid = path.name[4:].split('.', 1)[0].removesuffix('-summary')
                sessions.setdefault(sid, []).append(path)
            ordered = sorted(sessions, reverse=True)
            total = 0
            for n, sid in enumerate(ordered):
                size = sum(p.stat().st_size for p in sessions[sid])
                total += size
                if sid != self.session and (n >= self.keep_files or total > self.keep_total_bytes):
                    for p in sessions[sid]:
                        p.unlink()
        except OSError:
            pass


class Totals:
    """集計（書く側のスレッドだけが触る）。要求は requestId ごと・リダイレクトの段ごとに1回。"""

    def __init__(self):
        self.by = {}            # (分, 状態, 分類) -> {'requests', 'network', 'cache', 'failed', 'denied', 'bytes'}
        self.status = {}        # (分類, HTTP状態) -> 件数（400以上）
        self.failures = {}      # (分類, 失敗の文) -> 件数
        self.navs = {}          # 移動の理由 -> 件数
        self.nav_states = {}    # (理由, 状態) -> 件数
        self.nav_results = {}   # ('ok'|web_error, http) -> 件数
        self.events = {}        # 事象 -> 件数
        # app_api_calls：アプリが差枚APIを取りに行った回数（保存の記録の net_capture.reason が not_ready 以外）。
        self.captures = {'ok': 0, 'error': 0, 'net_warning': 0, 'net_denied': 0, 'skipped': 0, 'app_api_calls': 0,
                         'kinds': {}}
        self.first = {}         # 最初の事象の時刻（初めての403など）
        self.scripts = {}       # (分類, 呼び出し元のスクリプト) -> 件数（サイト自身の通信の出どころ）
        self.after = {}         # (状態, 分類, ホスト＋パス) -> 件数（OFF・休憩中・完了後）
        self.paths = {}         # (状態, 分類, ホスト＋パス) -> 件数（データ通信の宛先。ページ本体・資源は除く）
        self.messages = []      # 表示の文が変わった記録（最後の30件）
        self.duplicate_notices = 0
        self.orphan_notices = 0
        self.dropped = 0
        self.last_at = None

    def request(self, r, at):
        minute = datetime.fromtimestamp(at - r['ms'] / 1000).strftime('%H:%M')
        key = (minute, r['state'], r['cat'])
        b = self.by.setdefault(key, {'requests': 0, 'network': 0, 'cache': 0, 'failed': 0, 'denied': 0,
                                     'redirect': 0, 'bytes': 0})
        b['requests'] += 1
        cached = bool(r.get('cache')) or (r['how'] == 'finished' and r.get('bytes') == 0 and r.get('status') == 200)
        if r['how'] == 'redirect':
            b['redirect'] += 1
        if r['how'] == 'failed':
            b['failed'] += 1
            label = (r.get('error') or '') + ('（取り消し）' if r.get('canceled') else '')
            self.failures[(r['cat'], label)] = self.failures.get((r['cat'], label), 0) + 1
        if cached:
            b['cache'] += 1
        elif r['cat'] != 'youtube_local' and not (r['how'] == 'failed' and r.get('blocked')):
            b['network'] += 1
        b['bytes'] += int(r.get('bytes') or 0)
        status = r.get('status')
        if isinstance(status, int) and status >= 400:
            self.status[(r['cat'], status)] = self.status.get((r['cat'], status), 0) + 1
            if status in (403, 429):
                b['denied'] += 1
                self.first.setdefault(f'HTTP {status}（{r["cat"]}）', at)
        script = (r.get('init') or {}).get('script')
        if r['cat'] in ('site_data', 'site_periodic', 'api_unknown', 'unknown', 'third_party_data'):
            k = (r['cat'], script or '（呼び出し元なし）')
            self.scripts[k] = self.scripts.get(k, 0) + 1
        if r['cat'] in ('api_app', 'api_unknown', 'site_data', 'site_periodic', 'unknown', 'third_party_data'):
            k = (r['state'], r['cat'], r['url']['host'] + r['url']['path'])
            self.paths[k] = self.paths.get(k, 0) + 1
        if r['state'] not in ('on', 'before') and r['cat'] not in ('youtube_local',):
            k = (r['state'], r['cat'], r['url']['host'] + r['url']['path'])
            self.after[k] = self.after.get(k, 0) + 1
        self.last_at = at

    def nav(self, reason, safe, state):
        self.navs[reason] = self.navs.get(reason, 0) + 1
        self.nav_states[(reason, state)] = self.nav_states.get((reason, state), 0) + 1

    def nav_done(self, success, web_error, http_status):
        key = ('ok' if success else str(web_error), http_status)
        self.nav_results[key] = self.nav_results.get(key, 0) + 1

    def event(self, name, fields, state, at=None):
        self.events[name] = self.events.get(name, 0) + 1
        if name == 'capture_end':
            c = self.captures
            c['ok' if fields.get('ok') else 'error'] += 1
            for flag in ('net_warning', 'net_denied', 'skipped'):
                if fields.get(flag):
                    c[flag] += 1
            if fields.get('net_called'):
                c['app_api_calls'] += 1
            if fields.get('kind'):
                c['kinds'][fields['kind']] = c['kinds'].get(fields['kind'], 0) + 1
        if name == 'message':
            self.messages = (self.messages + [(state, fields.get('text', ''))])[-30:]
        if name in ('dom_missing', 'connection_failed', 'park_switch_failed', 'stopped'):
            self.first.setdefault(name, at if at is not None else time.time())

    def result(self, session, started, ended):
        return {'session': session, 'started': started, 'ended': ended, 'by': self.by, 'status': self.status,
                'failures': self.failures, 'navs': self.navs, 'nav_states': self.nav_states,
                'nav_results': self.nav_results, 'events': self.events, 'captures': self.captures,
                'scripts': self.scripts, 'after': self.after, 'paths': self.paths, 'messages': self.messages,
                'duplicate_notices': self.duplicate_notices, 'orphan_notices': self.orphan_notices,
                'dropped': self.dropped, 'first': self.first}


NAV_LABELS = {'window_open': '窓を開いたとき', 'next_page': '保存のあと次のページへ', 'reload_list': '機種一覧の読み込み直し',
              'rest': '休憩中の画面へ', 'resume': '休憩のあとの再開', 'retry_button': '「もう一度開く」',
              'site_or_user': 'アプリが決めていない移動（サイト・利用者・転送）'}


def format_summary(r):
    """人が読む集計。測ったもの（要求の通知の数）と、測れないもの（回線のパケット・本当の発信元）を分けて書く。"""
    lines = [f'P’s CUBE 取り込み窓の通信の診断（窓 {r["session"]}）',
             f'期間：{datetime.fromtimestamp(r["started"]).strftime("%Y-%m-%d %H:%M:%S")} 〜 '
             f'{datetime.fromtimestamp(r["ended"]).strftime("%H:%M:%S")}'
             f'（{round((r["ended"] - r["started"]) / 60, 1)}分）', '',
             '数の意味：', '- 要求＝WebView2が出した要求（CDPの requestId ごと。リダイレクトは段ごとに1回）。同じ要求の重ねての通知は数えない。',
             '- 通信＝要求のうち、キャッシュ（ディスク・メモリ・Service Worker・プリフェッチ）から返っていないもの。'
             '回線に出たパケットの数そのものではない（推定ではなく、WebView2の通知による分類）。',
             '- 保存＝アプリがページを保存した回数（取り込みの論理的な回数）。要求の数とは別。', '']
    totals = {}
    for (minute, state, cat), b in r['by'].items():
        t = totals.setdefault((state, cat), {'requests': 0, 'network': 0, 'cache': 0, 'failed': 0, 'denied': 0,
                                             'redirect': 0})
        for k in t:
            t[k] += b[k]
    lines.append('■ 状態・分類ごとの合計（要求／通信／キャッシュ／失敗／拒否403・429／リダイレクト）')
    for state in STATES:
        rows = [(cat, totals[(state, cat)]) for cat in CATEGORIES if (state, cat) in totals]
        if not rows:
            continue
        lines.append(f'［{STATE_LABELS[state]}］')
        for cat, t in rows:
            lines.append(f'  {CATEGORY_LABELS.get(cat, cat)}：{t["requests"]}／{t["network"]}／{t["cache"]}／{t["failed"]}'
                         f'／{t["denied"]}／{t["redirect"]}')
    c = r['captures']
    lines += ['', '■ 保存', f'  保存できた {c["ok"]}回・できなかった {c["error"]}回・差枚が未取得 {c["net_warning"]}回'
              f'・差枚APIの拒否で停止 {c["net_denied"]}回・飛ばした {c["skipped"]}回',
              '  ' + '、'.join(f'{k} {v}回' for k, v in sorted(c['kinds'].items()))]
    pages = sum(t['requests'] for (s, cat), t in totals.items() if cat == 'page' and s == 'on')
    on_all = sum(t['network'] for (s, cat), t in totals.items() if s == 'on' and cat != 'youtube_local')
    if c['ok']:
        lines.append(f'  自動ONの間の通信 {on_all}件 ÷ 保存 {c["ok"]}回 ＝ 保存1回あたり {round(on_all / c["ok"], 1)}件'
                     f'（ページ本体の要求 {pages}件）')
    api = [t for (s, cat), t in totals.items() if cat in ('api_app', 'api_unknown')]
    api_requests, api_network = sum(t['requests'] for t in api), sum(t['network'] for t in api)
    calls = c.get('app_api_calls', 0)
    lines += ['', '■ 差枚API：要求の数と、アプリが取りに行った回数',
              f'  差枚APIの要求 {api_requests}件（うち通信 {api_network}件）／アプリが取りに行った回数 {calls}回（保存の記録から）'
              f'／差 {api_requests - calls}件',
              '  差は、アプリの取りに行った1回以外の要求（サイト自身の呼び出し・WebView2やjQueryの再試行・'
              '読み取りの途中で失敗して保存の記録が無い回）。どれかは、この記録だけでは分けられない。']
    lines += ['', '■ ページの移動（理由ごと）']
    for reason, n in sorted(r['navs'].items(), key=lambda x: -x[1]):
        states = '・'.join(f'{STATE_LABELS.get(s, s)} {m}' for (rs, s), m in r['nav_states'].items() if rs == reason)
        lines.append(f'  {NAV_LABELS.get(reason, reason)}：{n}回（{states}）')
    lines.append('  移動の結果：' + '、'.join(f'{k[0]}{"・HTTP " + str(k[1]) if k[1] else ""} {v}回'
                                         for k, v in sorted(r['nav_results'].items(), key=lambda x: -x[1])))
    lines += ['', '■ HTTP 400以上（分類ごと）']
    lines += [f'  {CATEGORY_LABELS.get(cat, cat)}：HTTP {status} {n}件' for (cat, status), n in sorted(r['status'].items())] or ['  なし']
    lines += ['', '■ 通信の失敗（応答が無い・取り消し）']
    lines += [f'  {CATEGORY_LABELS.get(cat, cat)}：{label or "（文なし）"} {n}件' for (cat, label), n in sorted(r['failures'].items())] or ['  なし']
    lines += ['', '■ 最初に起きた時刻']
    lines += [f'  {k}：{datetime.fromtimestamp(v).strftime("%H:%M:%S")}' for k, v in sorted(r['first'].items(), key=lambda x: x[1])] or ['  なし']
    lines += ['', '■ アプリの事象（回数）', '  ' + '、'.join(f'{k} {v}' for k, v in sorted(r['events'].items()))]
    lines += ['', '■ サイト自身の通信・分類できない要求の出どころ（呼び出し元のスクリプト）']
    lines += [f'  {CATEGORY_LABELS.get(cat, cat)}：{script} {n}件' for (cat, script), n in
              sorted(r['scripts'].items(), key=lambda x: -x[1])[:30]] or ['  なし']
    lines += ['', '■ データ通信の宛先ごと（差枚API・サイトのデータ・定期・他サイト。ページ本体と資源は除く）']
    lines += [f'  ［{STATE_LABELS.get(s, s)}］{CATEGORY_LABELS.get(cat, cat)}：{where} {n}件' for (s, cat, where), n in
              sorted(r.get('paths', {}).items(), key=lambda x: -x[1])[:40]] or ['  なし']
    lines += ['', '■ 自動OFF・休憩中・完了のあとの要求（宛先ごと）']
    lines += [f'  ［{STATE_LABELS.get(s, s)}］{CATEGORY_LABELS.get(cat, cat)}：{where} {n}件' for (s, cat, where), n in
              sorted(r['after'].items(), key=lambda x: -x[1])[:40]] or ['  なし']
    lines += ['', '■ 分ごと（自動ON・通信の件数：ページ本体／差枚API／サイトのデータ・定期／資源／そのほか）']
    minutes = sorted({m for (m, s, cat) in r['by']})
    for m in minutes:
        def n(*cats, state=None):
            return sum(b['network'] for (mm, s, cat), b in r['by'].items()
                       if mm == m and cat in cats and (state is None or s == state))
        rest = sum(b['network'] for (mm, s, cat), b in r['by'].items() if mm == m and s != 'on')
        lines.append(f'  {m}  {n("page", "page_other", state="on")}／{n("api_app", "api_unknown", state="on")}'
                     f'／{n("site_data", "site_periodic", state="on")}／{n("resource", state="on")}'
                     f'／{n("third_party_data", "third_party_resource", "unknown", state="on")}'
                     + (f'  （ON以外 {rest}件）' if rest else ''))
    lines += ['', '■ 表示の文の変化（最後の30件）'] + [f'  ［{STATE_LABELS.get(s, s)}］{t}' for s, t in r['messages']]
    lines += ['', '■ 記録の確かさ',
              f'  同じ要求の重ねての通知（数えなかった）：{r["duplicate_notices"]}件',
              f'  始まりを見ていない要求の通知（記録の開始前に始まった等）：{r["orphan_notices"]}件',
              f'  待ち行列があふれて捨てた通知：{r["dropped"]}件',
              '  測れないこと：回線に出たパケットの数、Network.enable より前の要求、要求の本当の発信元'
              '（WebView2の呼び出し元は上の1段だけ。差枚APIのアプリ・サイトの別は「取りに行った回数」との差で見る）、'
              'サイト側の判定の条件。']
    return '\n'.join(lines) + '\n'


def install(window, netlog):
    """取り込み窓の WebView2 に診断の受け口をつなぐ（before_show、最初の移動の前）。失敗しても取り込みは続ける。
    返すのは pythonnet の受け口の参照（捨てると呼ばれなくなるので、呼んだ側で持つ）。"""
    control = window.native.webview
    keep = []

    def started(sender, args):
        try:
            netlog.nav_start(int(args.NavigationId), str(args.Uri), bool(getattr(args, 'IsRedirected', False)),
                             str(getattr(args, 'NavigationKind', '')) or None)
        except Exception:  # noqa: BLE001
            netlog.dropped += 1

    def completed(sender, args):
        try:
            netlog.nav_done(int(args.NavigationId), bool(args.IsSuccess), str(args.WebErrorStatus),
                            int(args.HttpStatusCode) if hasattr(args, 'HttpStatusCode') else None)
        except Exception:  # noqa: BLE001
            netlog.dropped += 1

    def attach(core):
        try:
            for name in CDP_EVENTS:
                receiver = core.GetDevToolsProtocolEventReceiver(name)

                def received(sender, args, name=name):
                    netlog.cdp(name, str(args.ParameterObjectAsJson))

                receiver.DevToolsProtocolEventReceived += received
                keep.extend([receiver, received])
            # 送った本文は受け取らない（apikey などを含みうる）。キャッシュの設定は変えない。
            core.CallDevToolsProtocolMethodAsync('Network.enable', json.dumps({'maxPostDataSize': 0}))
            netlog.event('cdp_enabled')
        except Exception as error:  # noqa: BLE001 - 診断が使えなくても取り込みは続ける
            netlog.event('cdp_unavailable', error=f'{type(error).__name__}: {str(error)[:200]}')

    def ready(sender, args):
        if args.IsSuccess:
            attach(sender.CoreWebView2)

    control.NavigationStarting += started
    control.NavigationCompleted += completed
    keep.extend([started, completed, ready])
    core = control.CoreWebView2
    if core is None:
        control.CoreWebView2InitializationCompleted += ready
    else:
        attach(core)
    return keep


def app_net_fetch(raw):
    """アプリが保存に送った記録（raw：dict か JSON の文字列）から、差枚APIを取りに行ったかと、失敗のHTTP状態の一覧。
    取り込みの処理（pscube_capture.js）は台別ページ1回につき差枚APIを1回だけ呼び、各日の記録の net_capture に
    reason を書く。準備ができず送らなかった回だけ reason が not_ready。成功のときは http_status を書かない。"""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        records = data.get('records') if isinstance(data, dict) else None
        caps = [r['net_capture'] for r in records or [] if isinstance(r, dict) and isinstance(r.get('net_capture'), dict)]
        called = any(c.get('reason') != 'not_ready' for c in caps)
        statuses = sorted({c.get('http_status') for c in caps if isinstance(c.get('http_status'), int)})
        return called, statuses
    except Exception:  # noqa: BLE001 - 診断の記録で保存を止めない
        return None, []


def pilot_state(pilot, saving):
    """取り込み窓の見張り（auto_loop）から呼ぶ。AutoPilot の状態を記録の状態の名前にする。"""
    if pilot.completed:
        return 'done'
    if pilot.state()['enabled']:
        return 'rest' if pilot.parked is not None else 'on'
    return 'off'


def latest(data_dir):
    files = sorted((Path(data_dir) / DIR_NAME).glob('net-*.jsonl'))
    return files[-1] if files else None


def summarize_file(path):
    """保存した .jsonl から集計を作り直す（窓が途中で落ちて -summary.txt が無いとき用）。"""
    totals = Totals()
    session = started = ended = None
    ever_on = False
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        # 2026-11-06 夕方より前の記録：最初のONの前も 'off'、差枚APIの一部が 'api_site'。今の分け方に読み替える。
        if rec.get('state') == 'on' or (rec.get('ev') == 'state' and rec.get('to') == 'on'):
            ever_on = True
        if rec.get('state') == 'off' and not ever_on:
            rec['state'] = 'before'
        if rec.get('cat') == 'api_site':
            rec['cat'] = 'api_unknown'
        at = datetime.fromisoformat(rec['t']).timestamp()
        started = at if started is None else started
        ended = at
        ev = rec.get('ev')
        if ev == 'session_start':
            session = rec.get('session')
        elif ev == 'req':
            totals.request(rec, at + rec.get('ms', 0) / 1000)
        elif ev == 'nav':
            totals.nav(rec.get('reason'), rec.get('url'), rec.get('state'))
        elif ev == 'nav_done':
            totals.nav_done(rec.get('ok'), rec.get('web_error'), rec.get('http'))
        elif ev not in ('intent', 'session_totals', 'truncated'):
            fields = {k: v for k, v in rec.items() if k not in ('t', 'ev', 'state', 'saving')}
            totals.event(ev, fields, rec.get('state'), at)
    return format_summary(totals.result(session or Path(path).stem, started or 0, ended or 0))


if __name__ == '__main__':
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else latest(Path(__file__).resolve().parent / 'data')
    if target is None:
        print('診断の記録がありません（data/pscube_netlog/）')
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        print(summarize_file(target))
