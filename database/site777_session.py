"""表→グラフ各ページ→掲載済みの次機種。通信は表示ブラウザのリンク操作だけ。"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from time import monotonic

from anaslo_converter import read_catalog, suggestions
from browser_import import clean_overlay_layout
from pscube_import import (PscubeStore, PscubeRandomCapture, auto_backup, business_day, is_excluded_machine,
                           recent_business_days, site777_final, site777_final_at)
from file_io import atomic_writer, write_notice
from site777_browser import Bridge, LAST_STOP_NAME, WAIT_NOTICE_NAME, notice_path
import site777_import as source

# 移動を指示してから、読み込みの完了（成功・失敗）がこれだけ来なければ止める（2026-11-08）。
# 移動中は次の読み取りをしない（旧画面を読み直さない）ので、来ないままだと止まらずに待ち続けるため。
NAVIGATION_LIMIT = 90
# 窓を最小化したままグラフの読み込みを待っている間、PC本体のログ欄へ再通知する間隔（秒、2026-11-23）。
HIDDEN_REMIND_SECONDS = 600
BACKUP_OK = 'バックアップ済み'
# 自動取り込み中に止まったら、3分後に自動で再開する（2026-11-08 利用者「別店舗など、取り込み対象以外へ移動しようとした
# （navigation_blocked）これ以外は全て3分後には自動復帰でお願いします」「利用者の停止ボタンも対象外」）。
# 取り込みが進まないまま（機種・日が1つも済まないまま）自動の再開が5回続いたら、それ以上は再開しない
# （利用者「連続5回まで」。直らない原因で3分ごとにサイトへアクセスし続けないため）。
RESUME_DELAY = 180
RESUME_LIMIT = 5
# サイトが取り込み中のページを別の店（同じ機種）へ転送したとき（site_redirect）は、移動は止めたまま3分後に自動で再開する
# （2026-11-15 利用者「移動先が別の店判定で自動停止がよくわからん。その状態で取り込むボタンおしたら普通に動き出したし。
# 修正して」。11/15 7:36・7:44・7:45、出玉推移一覧を開くとサイトが 08009027・07014026・47005007 の店へ転送し、
# そのたびに止まった。押し直すと普通に進んだので、転送はその場限り）。画面のリンク・利用者の操作で別の店へ移るとき
# （転送でない移動）は、今までどおり navigation_blocked で止めたまま再開しない。
# 停止の理由コードの呼び名（ホームのログ欄・前回の案内・カードに出す。2026-11-08 Codexの提案「画像待ちの上限」
# 「移動失敗」「認証の確認が必要」などを区別し、PCホームにも残す）。
REASON_LABELS = {
    'graph_retry_limit': '画像待ちの上限', 'graph_retry_storage': '画像待ち',
    'not_moved': '移動失敗（リンクで移動しない）', 'navigation_timeout': '移動失敗（読み込みが終わらない）',
    'navigation_failed': '移動失敗（ページを読み込めない）', 'login_required': 'ログインの確認が必要',
    'navigation_blocked': '対象外のページへの移動', 'site_redirect': 'サイトが別の店へ転送', 'capture_error': '読み取りの失敗',
    'card_error': '取り込みカードの失敗', 'overlay_failed': '取り込みカードを出せない',
    'range_unknown': '次の日の機種一覧が分からない', 'user_stop': '停止ボタン', 'stopped': '停止',
}
# 前回の取り込みの範囲・済んだ日・止まった理由（2026-11-08 Codexの提案：窓を開き直すと日付の範囲を選び直しになり、
# 前回どこまで取り込んだかが分からなかった）。窓を開いたとき、カードに案内を出し、残りの日を選んでおく。
LAST_RUN_NAME = 'site777-last-run.json'
BACKUP_DUE_NAME = 'site777-backup-due.json'
# 機種ごとの途中の記録を残す日数（今の営業日から。サイトが見せる8日分より長く取る。2026-11-08）。
STAGING_KEEP_DAYS = 14
# この回転数に満たない台（0Gを含む）は取り込まない（2026-11-10 利用者「0ゲーム、500g未満の台については取り込まない」）。
# 採点の下限（core.MIN_SCORED_GAMES、P’s CUBE の RACK_PAGE_MIN_GAMES）と同じ500G。500Gちょうどは取り込む。
MIN_SAVED_GAMES = 500
# 読み込み直してもグラフが出ない台を、グラフなしで保存して進めてよい台数（1機種につき。2026-11-13 利用者、
# 初めは1台）。2026-11-19 利用者「仮だと思ったら再読み込みして」：ゴーゴージャグラー3の1ページ目の上の2台
# （1286・1287番）が両方出ず、2台目で止まり続けたため、その機種の台数の半分まで（1台・2台の機種は1台）にした。
# 半分を超えて出ないときは、サイト側の不調とみて今までどおり止める。
MAX_GRAPHLESS = 1


def graphless_limit(racks):
    """1機種でグラフなしにしてよい台数。[racks] はその機種の表の台数。"""
    return max(MAX_GRAPHLESS, int(racks) // 2)
# 同じDB（pscube.sqlite3）へほかの窓・PC本体が書いている間、待つ秒数（既定の5秒から延ばした。2026-11-13）。
DB_WAIT = 30.0
_low_thread_lock = threading.Lock()
_job_thread_lock = threading.Lock()


@contextmanager
def _file_lock(folder, name, thread_lock, timeout=DB_WAIT):
    """2窓の別プロセス・別スレッド間で共有ファイル（low / staging）の読み書きを直列化する鍵。"""
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = monotonic() + timeout
    with thread_lock, path.open('a+b') as lock:
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b'0')
            lock.flush()
        while True:
            lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def _low_file_lock(folder, timeout=DB_WAIT):
    """500G未満の控え（日付-low.json）を読んで足して書く鍵（2窓の別プロセス・別スレッドをまたぐ）。"""
    with _file_lock(folder, 'site777-low.lock', _low_thread_lock, timeout=timeout):
        yield


@contextmanager
def _job_file_lock(folder, timeout=DB_WAIT):
    """2窓間で機種ごとの途中記録と保存資料の読み書きを直列化する鍵。"""
    with _file_lock(folder, 'site777-job.lock', _job_thread_lock, timeout=timeout):
        yield

RESUMABLE = frozenset({'not_moved', 'navigation_timeout', 'navigation_failed', 'capture_error',
                       'graph_retry_limit', 'graph_retry_storage', 'card_error', 'overlay_failed',
                       'range_unknown', 'site_redirect'})


class StaleRun(ValueError):
    """停止・再開の前に始まった古い処理。今の取り込みの状態は変えずに捨てる（2026-11-08）。"""


def clean_reason(message):
    """停止の文をログ・知らせに残す形にする。URL（問い合わせに会員情報が入りうる）は残さない。"""
    if not message:
        return None
    return re.sub(r'(?:https?|javascript):\S+', '（URL）', str(message))[:300]


def reason_code(value, default):
    return value if isinstance(value, str) and re.fullmatch(r'[a-z_]{1,40}', value) else default


class Site777RandomCapture(PscubeRandomCapture):
    """サイトセブンの間隔：3〜5秒のランダム（2026-11-07 利用者「取り込み間隔も10秒程度じゃなくて5～7秒程度にしよう」→
    2026-11-17 利用者「サイトセブン優しいから３～5秒で作りなおしたらいい」）。
    P’s CUBE（PscubeRandomCapture の10〜20秒）は変えない。"""
    LOW, HIGH = 3, 5


DIRECTIONS = ('top', 'bottom')


class Session(Bridge):
    def __init__(self, data_dir, log, *, now=None, store_factory=None, window_id=None):
        super().__init__(log)
        self._folder = Path(data_dir)
        self._window_id = window_id
        self._db_path = self._folder / 'pscube.sqlite3'
        self._now = now or (lambda: datetime.now(source.JST))
        # 2つの窓が同時に保存すると、既定の5秒では待ちきれず「database is locked」で止まった（2026-11-13 1:39）。
        self._store_factory = store_factory or (lambda path: PscubeStore(path, timeout=DB_WAIT))
        self._window = None
        self._state_lock = threading.Lock()
        self._work_lock = threading.Lock()
        self._epoch = 0
        self._pace = Site777RandomCapture()
        # 機種を一覧の上から（top）か下から（bottom）か。メルヘンの「上から取り込む／下から取り込む」と同じ（2026-11-07）。
        self._direction = 'top'
        self._enabled = False
        self._days = recent_business_days(self._now(), count=8)
        # 初めに選ぶ日は、確定した（その日の23:30を過ぎた）いちばん新しい日（2026-11-08、11-10 に翌0:30から23:30へ）。確定前の日を
        # 取り込むと営業中・更新前の数値のことがあるので、確認してから（_today_ok）。確定前に取った台は、23:30以降に取り込み直すと置き換わる。
        self._day = next((d for d in self._days if d < self._unfinished_from()), self._days[-1])
        self._today_ok = False
        # 日付の範囲で取り込む（2026-11-07 利用者「日付範囲指定できるようにしてほしい」）。_day が今の日、
        # _queue がこの後に取り込む日（古い順）、_until は範囲の終わり（単日なら None）。
        self._until = None
        self._queue = []
        self._finished_days = []
        # 自動取り込みが最後まで終わったときの結果の文。窓はこれを見て閉じる（site777_browser.close_when_finished、
        # 2026-11-07 利用者「取り込み終わったなら閉じる仕様にしてね」。メルヘン・P’s CUBEの close_when_finished と同じ）。
        self._completed = None
        self._status = 'P-STATIONの20円スロットを開き、取り込む日付を確認してください。'
        self._models = {}
        self._done = set()
        self._index_pages = set()
        self._job = None
        self._added = 0
        self._kept = 0
        self._unknown = 0
        self._active_url = None
        self._pending_navigation = False
        self._pending_since = 0.0
        self._blocked_navigation = False
        # 止めた移動のURL。同じ移動の文書の読み込み（_document_allowed）で、もう一度止め直さない（止め直すと、
        # 待っている自動の再開が取り消され、理由も「対象外のページへの移動」に上書きされていた。2026-11-15）。
        self._blocked_url = None
        # 今の工程（読み取ったページの種類）。停止の記録に残す。
        self._stage = None
        # 窓を閉じたあとに書き出す分がある（1機種でも保存した、または前の窓で書き出しに失敗した）。_backup_after_close が見る。
        self._backup_due = self._backup_due_path().is_file()
        # 自動の再開（RESUME_DELAY 秒後）。_resume_at は monotonic の時刻、_resume_plan は再開する日・範囲・向き・理由、
        # _resume_count は取り込みが進まないまま続けて再開した回数、_resume_serial は再開のたびに増やす番号
        # （記録用。2026-11-08 からカードはこれで読み込み直しの回数を戻さない。再開1回につき読み込み1回）。
        self._resume_at = None
        self._resume_label = None
        self._resume_plan = None
        self._resume_count = 0
        self._resume_serial = 0
        self._own_saves = 0
        # 窓の最小化でグラフ読み込みを待っている間の状態（PC本体のログ欄へ知らせるため、2026-11-23）。
        self._hidden_since = None
        self._hidden_next_remind = None
        self._hidden_reminded = False
        self._hidden_wait_day = None
        self._hidden_wait_page = None
        # 今の取り込みの範囲の始まり・終わり（前回の案内に残す）と、窓を開いたときの前回の案内の文。
        self._run_start = self._run_until = None
        self._previous = None
        self._load_previous()
        self._prune_staging()

    def _backup_due_path(self):
        return self._folder / BACKUP_DUE_NAME

    def _set_backup_due(self, due):
        self._backup_due = bool(due)
        try:
            if due:
                self._write(self._backup_due_path(), {'due': True})
            else:
                self._backup_due_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _prune_staging(self):
        """もう取り込めない古い日の、機種ごとの途中の記録（site777-staging/日付-機種.json）を消す（2026-11-08。
        サイトが見せるのは8日分なので、続きから取り込むのに使えない。消す仕組みが無く、1日に約50本ずつ増えていた）。
        今の営業日より STAGING_KEEP_DAYS 日以上前の日だけ。元の資料（sources、推定差枚を付け直すのに使う）は残す。
        消せなくても窓は開く。"""
        cutoff = (date.fromisoformat(self._days[0]) - timedelta(days=STAGING_KEEP_DAYS)).isoformat()
        removed = 0
        try:
            for path in (self._folder / 'site777-staging').glob('*.json'):
                match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})-(?:\d+|low)\.json', path.name)
                if match and match[1] < cutoff:
                    path.unlink()
                    removed += 1
        except OSError:
            pass
        if removed:
            self._log.write('staging_pruned', removed=removed, before=cutoff)

    def note(self, payload):
        """ページからの記録を受け取り、最小化中のグラフ待機・再開ならPC本体のログ欄用の知らせも残す。"""
        super().note(payload)
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        kind = data.get('kind')
        if kind == 'graph_hidden':
            self._on_graph_hidden(data)
        elif kind == 'graph_visible':
            self._on_graph_visible(data)

    def _window_label(self):
        md = self._day[5:].replace('-', '/') if isinstance(self._day, str) and len(self._day) >= 10 else ''
        way = '下から' if self._direction == 'bottom' else '上から'
        return f'{md}・{way}' if md else way

    def _clear_hidden_wait(self):
        self._hidden_since = None
        self._hidden_next_remind = None
        self._hidden_reminded = False
        self._hidden_wait_day = None
        self._hidden_wait_page = None

    def _on_graph_hidden(self, data):
        with self._state_lock:
            if self._hidden_since is not None:
                return
            now_mono = monotonic()
            self._hidden_since = now_mono
            self._hidden_next_remind = now_mono + HIDDEN_REMIND_SECONDS
            self._hidden_reminded = False
            self._hidden_wait_day = data.get('day') or self._day
            page = data.get('page')
            self._hidden_wait_page = page if type(page) is int and page >= 1 else None
            label = self._window_label()
            stamp = f'{self._now():%H:%M}'
        message = (f'{stamp} 窓が最小化されているため、グラフの読み込みを待っています（{label}・このままでは進みません）。'
                   'タスクバーから窓を元に戻すと続きます（ほかの窓の後ろに置くのは問題ありません）。')
        write_notice(notice_path(self._folder, WAIT_NOTICE_NAME, self._window_id), message)

    def _on_graph_visible(self, data):
        with self._state_lock:
            if self._hidden_since is None:
                return
            reminded = self._hidden_reminded
            self._clear_hidden_wait()
            label = self._window_label()
            stamp = f'{self._now():%H:%M}'
        path = notice_path(self._folder, WAIT_NOTICE_NAME, self._window_id)
        # 初回通知を親画面が読む前（一瞬の最小化）に戻ったときは、未読の知らせを消して再開通知も出さない。
        if not reminded and path.exists():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return
        write_notice(path, f'{stamp} 窓が戻ったため、グラフの読み込みを続けます（{label}）。')

    def _check_hidden_wait(self):
        with self._state_lock:
            if self._hidden_since is None or self._hidden_next_remind is None:
                return None
            now_mono = monotonic()
            if now_mono < self._hidden_next_remind:
                return None
            minutes = max(1, int((now_mono - self._hidden_since) // 60))
            self._hidden_next_remind = now_mono + HIDDEN_REMIND_SECONDS
            self._hidden_reminded = True
            day, page, label = self._hidden_wait_day, self._hidden_wait_page, self._window_label()
            stamp = f'{self._now():%H:%M}'
        message = (f'{stamp} 窓が最小化されたまま約{minutes}分待っています（{label}）。'
                   'タスクバーから窓を元に戻すと続きます。')
        write_notice(notice_path(self._folder, WAIT_NOTICE_NAME, self._window_id), message)
        self._log.write('graph_hidden_waiting', minutes=minutes, day=day, page=page)
        return message

    def state(self):
        self._watch_navigation()
        with self._state_lock:
            # 移動を指示してから読み込みが終わるまでは ready にしない（2026-11-08 Codexのレビュー：
            # 移動先の応答が遅いと、5〜7秒の間隔だけで旧画面を読み直し、同じリンクを押し直していた）。
            return {'enabled': self._enabled, 'epoch': self._epoch, 'day': self._day,
                    'until': self._until, 'queue': list(self._queue), 'finished_days': list(self._finished_days),
                    'days': self._days, 'status': self._status, 'added': self._added, 'kept': self._kept,
                    'ready': self._pace.due() is not None and not self._pending_navigation,
                    'navigating': self._pending_navigation, 'unknown_graphs': self._unknown,
                    'direction': self._direction, 'resume_at': self._resume_label if self._resume_at else None,
                    'resume_serial': self._resume_serial, 'previous': self._previous,
                    'unfinished_from': self._unfinished_from(), 'today_ok': self._today_ok}

    def _unfinished_from(self, now=None):
        """まだ確定していない最初の日。今の営業日（午前3時で切り替え）の23:30（2026-11-10 利用者「23時45分くらいに最終更新だから」
        「23時半以降に取り込みだしたやつも飛ばしていいです」。11/8 は翌日0:30だった）より前ならその営業日、過ぎていれば翌日。"""
        now = now or self._now()
        day = business_day(now)
        if now >= site777_final_at(day):
            day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        return day

    @staticmethod
    def _unfinished(days, first):
        """まだ確定していない日（営業中・更新前・まだ始まっていない日。午前0時から出る翌日のタブも含む）。"""
        return [d for d in days if d and d >= first]

    @staticmethod
    def _counts_as_saved(r):
        """保存済みに数える台。アナスロで補った台と、確定前（その日の23:30より前に取った）のサイトセブンの台は数えない
        （どちらもサイトセブンで取り直して置き換える。2026-11-07・2026-11-08）。"""
        return r.get('source_site') != 'anaslo' and (r.get('source_site') != 'site777' or site777_final(r))

    def _save_run(self, stopped=None, completed=False, remaining=None, locked=False):
        """前回の案内のため、今の取り込みの範囲・済んだ日・残りの日・止まった理由を残す。書けなくても取り込みは続ける。
        locked は呼ぶ側が _state_lock を持っているとき。"""
        if not locked:
            with self._state_lock:
                return self._save_run(stopped, completed, remaining, locked=True)
        if self._run_start is None:
            return None
        if remaining is None:
            remaining = [] if completed else [self._day, *self._queue]
        data = {'at': self._now().isoformat(timespec='minutes'), 'start': self._run_start, 'until': self._run_until,
                'finished_days': list(self._finished_days), 'remaining': list(remaining),
                'direction': self._direction, 'stopped': stopped, 'completed': bool(completed)}
        try:
            self._write(self._folder / LAST_RUN_NAME, data)
        except (OSError, ValueError, TypeError):
            pass
        return None

    def _load_previous(self):
        """窓を開いたとき：前回の取り込みの案内の文を作り、途中で終わっていれば残りの日を選んでおく（掲載日にある日だけ）。"""
        try:
            data = json.loads((self._folder / LAST_RUN_NAME).read_text(encoding='utf-8'))
            start, until, at = data['start'], data.get('until') or data['start'], datetime.fromisoformat(data['at'])
            finished, remaining = [str(d) for d in data.get('finished_days', [])], [str(d) for d in data.get('remaining', [])]
            for value in (start, until, *remaining):
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError(value)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return
        md = lambda d: d[5:].replace('-', '/')
        span = md(start) if start == until else f'{md(start)}〜{md(until)}'
        head = f'前回（{at:%m/%d %H:%M}）：{span}'
        if data.get('completed'):
            self._previous = f'{head}を最後まで取り込みました。'
            return
        why = f'【{data["stopped"]}】' if isinstance(data.get('stopped'), str) and data['stopped'] else \
            '（止まった理由の記録なし。取り込み中に窓を閉じたなど）'
        text = f'{head}を取り込む途中で止まりました{why}。済み：{"、".join(finished) or "なし"}。'
        if remaining and all(d in self._days for d in remaining):
            ordered = sorted(remaining)
            self._day, self._queue = ordered[0], ordered[1:]
            self._until = ordered[-1] if len(ordered) > 1 else None
            if data.get('direction') in DIRECTIONS:
                self._direction = data['direction']
            rest = md(ordered[0]) if len(ordered) == 1 else f'{md(ordered[0])}〜{md(ordered[-1])}'
            text += f'残りの{rest}を選んであります（開始を押すと続きから。保存済みの台は飛ばします）。'
        elif remaining:
            text += f'残りの{"、".join(md(d) for d in remaining)}には、掲載が終わった日があります。日付を選び直してください。'
        self._previous = text

    def _watch_navigation(self):
        with self._state_lock:
            late = self._pending_navigation and monotonic() - self._pending_since > NAVIGATION_LIMIT
            if late and not self._enabled:
                # 手動の取り込みのあと：止めるものは無いので、待つのをやめるだけ（「この画面を取り込む」を押せるように戻す）。
                self._pending_navigation = late = False
        if late:
            self.pause(f'ページの移動が{NAVIGATION_LIMIT}秒たっても終わらないため停止しました。', 'navigation_timeout')

    def _stopped(self, reason, message=None, **detail):
        """自動取り込みが止まった・終わった理由を残す（2026-11-08。今まではカードの停止は理由をログに書かず、
        読み取りの失敗も例外の型しか残らなかったため、OFFになった原因を後から区別できなかった）。
        理由コード・営業日・工程・実行番号を残す。URL・会員情報・ページの中身は残さない。
        窓を閉じたとき親画面に出せるよう、最後の停止の文を知らせファイルにも残す。"""
        resume = None
        with self._state_lock:
            day, epoch, stage = self._day, self._epoch, self._stage
            if detail.get('was_on') and reason in RESUMABLE:
                if self._resume_count >= RESUME_LIMIT:
                    resume = 'gave_up'
                    self._status = (f'{self._status} 自動での再開を{RESUME_LIMIT}回続けても取り込みが進まないため、'
                                    'これ以上は自動で再開しません。画面を確認してから開始してください。')
                else:
                    resume = 'scheduled'
                    plan_day, plan_until = day, self._until
                    if detail.get('left_days'):
                        plan_day, plan_until = detail['left_days'][0], detail['left_days'][-1]
                    self._resume_plan = {'day': plan_day, 'until': plan_until if plan_until != plan_day else None,
                                         'direction': self._direction, 'reason': reason,
                                         'today_ok': self._today_ok}
                    self._resume_at = monotonic() + RESUME_DELAY
                    self._resume_label = f'{self._now() + timedelta(seconds=RESUME_DELAY):%H:%M}'
                    self._status = (f'{self._status} {self._resume_label}に自動で再開します'
                                    f'（{self._resume_count + 1}/{RESUME_LIMIT}回目。取り消すときは自動取り込みのボタンを押す）。')
            status = self._status
        text = clean_reason(message)
        detail.pop('left_days', None)
        self._log.write('auto_off', reason=reason, day=day, epoch=epoch, stage=stage, message=text,
                        resume=resume, resume_count=self._resume_count if resume else None,
                        **{k: v for k, v in detail.items() if v is not None})
        notice = clean_reason(status) if resume else text
        label = REASON_LABELS.get(reason, reason)
        write_notice(notice_path(self._folder, LAST_STOP_NAME, self._window_id),
                     f'{self._now():%m/%d %H:%M}に停止【{label}】：{notice or "停止しました。"}')
        if reason != 'range_unknown':
            self._save_run(stopped=label)

    def _resume_if_due(self):
        """自動の再開の時刻が来ていたら、止まる前と同じ日・範囲・向きでONに戻す。読み込み直す表示中のページのURLを返す
        （窓の見張り site777_browser.run が、そのページを1回だけ読み込み直す。移動の守りはふだんどおり効く）。
        再開しないときは None。"""
        with self._state_lock:
            if self._resume_at is None or monotonic() < self._resume_at or self._work_lock.locked():
                return None
            plan, count = self._resume_plan, self._resume_count + 1
            self._resume_at = None
            run = (self._run_start, self._run_until, list(self._finished_days))
        try:
            self.configure(True, plan['day'], plan['until'], plan['direction'], plan.get('today_ok', False))
        except ValueError as error:
            self._log.write('auto_resume_failed', reason=plan['reason'], error=clean_reason(error))
            return None
        with self._state_lock:
            self._run_start, self._run_until = run[0], run[1]
            if not self._finished_days:
                self._finished_days = run[2]
        self._save_run()
        url = None
        try:
            url = self._window.get_current_url() if self._window else None
        except Exception:  # noqa: BLE001 - 読めなければ読み込み直さずに続ける
            url = None
        url = url if isinstance(url, str) and url.startswith('https://') else None
        with self._state_lock:
            self._resume_count = count
            self._resume_serial += 1
            if url:
                # 読み込み直しが終わるまで読み取らない（移動中と同じ）。
                self._pending_navigation = True
                self._pending_since = monotonic()
            self._status = (f'止まってから{RESUME_DELAY // 60}分たったので、自動で再開しました'
                            f'（{count}/{RESUME_LIMIT}回目）。' + ('このページを読み込み直します。' if url else ''))
        self._log.write('auto_resume', reason=plan['reason'], day=plan['day'], count=count, reload=bool(url))
        return url

    def configure(self, enabled, day=None, until=None, direction=None, today_ok=False):
        """自動取り込みのON/OFFと取り込む日。until を付けると day〜until の範囲（どちらが先でもよい）を
        古い日から順に取り込む。範囲は掲載日（_days）の中だけ。
        today_ok：今の営業日（営業中になりうる日）を取り込むことを利用者が確かめた（カードの確認、2026-11-08）。
        今の営業日を含めて開始するときは必須。付けずに開始しようとしたら、何も変えずに止める。"""
        if type(enabled) is not bool or type(today_ok) is not bool:
            raise ValueError('自動取り込みの設定が不正です。')
        from datetime import date
        for value in (day, until):
            if value is not None and (not isinstance(value, str) or date.fromisoformat(value).isoformat() != value):
                raise ValueError('取り込み日が不正です。')
        if direction is not None and direction not in DIRECTIONS:
            raise ValueError('取り込む向きが不正です。')
        if until is not None and day is None:
            raise ValueError('範囲の始まりの日を選んでください。')
        with self._state_lock:
            queue = []
            if until is not None and until != day:
                first, last = sorted((day, until))
                span = sorted(d for d in self._days if first <= d <= last)
                if not span:
                    raise ValueError('選んだ範囲に掲載日がありません。')
                day, queue = span[0], span[1:]
                if self._work_lock.locked() and day != self._day:
                    raise ValueError('読み取り処理中は日付を変えられません。停止して処理の完了を待ってください。')
            planned = [self._day, *self._queue] if day is None else [day, *queue]
            unfinished = self._unfinished(planned, self._unfinished_from())
            if enabled and unfinished and not today_ok:
                raise ValueError(f'{unfinished[0][5:].replace("-", "/")}の分はまだ確定していません（その日の23:30より前は営業中・'
                                 '更新前の数値のことがあります）。確認してから開始してください（23:30以降に取り込み直すと置き換わります）。')
            # 止めるだけ（日付を変えない configure(False)）のときは確認済みを残す（止まったあとの自動の再開で引き継ぐ）。
            # 開始・日付の変更では、そのときの確認だけを使う。
            if enabled or day is not None or today_ok:
                self._today_ok = today_ok and bool(unfinished)
            if day != self._day and day is not None:
                if self._work_lock.locked():
                    raise ValueError('読み取り処理中は日付を変えられません。停止して処理の完了を待ってください。')
                self._models.clear()
                self._done.clear()
                self._index_pages.clear()
                self._job = None
                self._added = self._kept = 0
                self._unknown = 0
            if day is not None and day != self._day:
                self._finished_days = []
            if day is not None:
                self._queue = queue
                self._until = queue[-1] if queue else None
            self._day = day or self._day
            if direction is not None:
                self._direction = direction
            self._enabled = enabled
            self._completed = None
            if enabled:
                # 開始したら前回の案内は消し、今回の範囲を残す（自動の再開は _resume_if_due が元の範囲に戻す）。
                self._previous = None
                self._run_start, self._run_until = self._day, self._until or self._day
            # 設定し直したら（開始・停止・日付の変更・自動の再開）、待っている自動の再開は取り消す。
            # 利用者が開始したときは、続けて再開した回数も数え直す（自動の再開は _resume_if_due が回数を戻す）。
            self._resume_at = None
            if enabled:
                self._resume_count = 0
            self._pending_navigation = False
            self._blocked_navigation = False
            self._blocked_url = None
            self._clear_hidden_wait()
            self._pace.configure(enabled, 15)
            self._epoch += 1
            self._status = '自動取り込みを開始します。' if enabled else '停止しました。'
        if enabled:
            self._save_run()
        return self.state()

    def _loaded(self):
        with self._state_lock:
            self._pending_navigation = False
            self._clear_hidden_wait()
        self._pace.loaded()

    def _navigation_starting(self, raw, redirected=False):
        with self._state_lock:
            protected = self._enabled or self._pending_navigation or self._blocked_navigation
        if not protected:
            return True
        try:
            source.source_url(raw)
            return True
        except (TypeError, ValueError):
            with self._state_lock:
                repeat = self._blocked_navigation and raw == self._blocked_url
            if repeat:
                return False
            # ログイン・会員の画面（/f/P… 、ログインが切れたときにサイトが移す先）なら「ログインの確認が必要」と分けて出す
            # （2026-11-08 Codexの提案）。どちらも自動では再開しない（利用者「navigation_blocked これ以外は全て3分後」）。
            try:
                target = source.urlsplit(raw)
                login = target.hostname == 'm.site777.jp' and target.path.startswith('/f/P')
            except (TypeError, ValueError, AttributeError):
                login = False
            if login:
                self.pause('ログインの確認が必要です（ログイン・会員の画面へ移ろうとしたため止めました）。'
                           'ログインしてからP-STATIONの20円スロットを開き、開始してください。自動では再開しません。',
                           'login_required')
                # 利用者がこのあとログイン画面を開けるよう、別店舗のときの「止めたあとも守る」（_blocked_navigation）は付けない。
                self._log.write('navigation_blocked', redirected=bool(redirected), login=True)
                return False
            elif redirected:
                self.pause('サイトが別の店のページへ転送したため、移動を止めました（別の店のデータは取り込みません）。',
                           'site_redirect')
            else:
                self.pause('P-STATIONの20円スロット以外への移動を止めました。'
                           '対象店の画面を確認してから再開してください。自動の再取得は行いません。', 'navigation_blocked')
            with self._state_lock:
                self._blocked_navigation = True
                self._blocked_url = raw
            # 認証用の問い合わせは記録せず、公開の店舗・貸玉・機種コードだけ残す。
            try:
                query = dict(source.parse_qsl(source.urlsplit(raw).query))
                public = {k: v for k, v in query.items() if k in ('pmc', 'urt', 'mdc')
                          and v.isdecimal() and len(v) <= 12}
            except (TypeError, ValueError):
                public = {}
            self._log.write('navigation_blocked', redirected=bool(redirected), **public)
            return False

    def _document_allowed(self, raw):
        # NavigationStartingのキャンセルだけではGETが先行しうるため、データ文書にも保護を置く。
        # iframeの認証ページ・画像・通信ヘッダーには触れない。
        try:
            uri = source.urlsplit(raw)
        except (TypeError, ValueError):
            return False
        if uri.hostname != 'm.site777.jp' or uri.path not in source.PATHS:
            return True
        with self._state_lock:
            blocked = self._blocked_navigation
        if blocked:
            # すでに止めてあるときは、読み込みを通さないだけで止め直さない（2026-11-15 レビュー）。文書の読み込みのURLは
            # 画面の移動（NavigationStarting）のURLと文字が一致する保証がなく、止め直すと待っている自動の再開が取り消され、
            # 理由も「対象外のページへの移動」に上書きされる。止める理由は画面の移動の側だけで決める。
            try:
                source.source_url(raw)
                return True
            except (TypeError, ValueError):
                return False
        return self._navigation_starting(raw)

    def pause(self, message=None, reason=None, retries=None):
        """止める。reason はカード・PCが付ける理由コード（user_stop、not_moved、graph_retry_limit など）。"""
        with self._state_lock:
            was_on = self._enabled
        self.configure(False)
        if message:
            with self._state_lock:
                self._status = str(message)[:500]
        self._stopped(reason_code(reason, 'stopped'), message, was_on=was_on,
                      retries=retries if type(retries) is int and 0 <= retries <= 99 else None)
        return self.state()

    def _navigation_done(self, ok, status=None, error=None):
        """ページの読み込みが終わった（WebView2 の NavigationCompleted）。自動取り込み中に読み込めなかったら、
        理由を出して止める（2026-11-08。今までは読み込めないページ（通信エラー・HTTP 403 など）のまま、
        カードが出ずにONのまま止まるか、読み取りの失敗としか分からなかった）。読み込み直しはしない。
        自分の守り（別店舗への移動など）で取り消した移動・別の移動に置き換わった移動（OperationCanceled）は除く。"""
        if ok or 'OperationCanceled' in str(error or ''):
            return
        with self._state_lock:
            active = self._enabled
        if active:
            detail = f'HTTP {status}' if type(status) is int and status else str(error or '不明')[:60]
            self.pause(f'ページを読み込めませんでした（{detail}）。', 'navigation_failed')

    def skip_graph(self, rack, epoch):
        """自動取り込みで、1分ごとの読み込み直し（3回）でもグラフが出ない台を、グラフなしで保存して先へ進む
        （2026-11-13 利用者「グラフなしで進めるようにお願いね」。11/13 1:15〜1:40、ゴーゴージャグラー3の1286番台
        だけ仮の画像のままで、3分後の再開を繰り返していた）。グラフなしにできるのは1機種につき
        [graphless_limit]台まで（台数の半分、1台・2台の機種は1台。2026-11-19）。それを超えて出ないときは
        サイト側の不調とみて、今までどおり止める（呼ぶ側がそのまま停止する）。
        グラフなしの台は「グラフ不明」として保存する（表の数値は保存する。あとで取り込み直しても保存済みの台は飛ばす）。"""
        with self._state_lock:
            job = self._job
            ok = (self._enabled and epoch == self._epoch and job is not None and type(rack) is int
                  and self._stage == 'graphs')
            if ok:
                skipped = job.setdefault('no_graph', [])
                ok = (rack in {r['rack'] for r in job['rows']} and str(rack) not in job['graphs']
                      and rack not in skipped and len(skipped) < graphless_limit(len(job['rows'])))
            if ok:
                skipped.append(rack)
                model, day = job['table']['model_id'], self._day
                self._status = (f'{job["table"]["machine"]}：{rack}番台のグラフが出ないため、この台はグラフなしで'
                                '保存して続けます。')
        if not ok:
            return {'ok': False, 'state': self.state()}
        self._write_job(model, job)
        self._log.write('graph_skipped', day=day, model=model, rack=rack)
        return {'ok': True, 'state': self.state()}

    def save_overlay_layout(self, raw):
        value = clean_overlay_layout(json.loads(raw))
        if value is not None:
            self._write(self._folder / 'site777-layout.json', value)

    def _layout(self):
        try:
            return clean_overlay_layout(json.loads((self._folder / 'site777-layout.json').read_text(encoding='utf-8'))) or {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write(path, data):
        with atomic_writer(path) as out:
            out.write(json.dumps(data, ensure_ascii=False, allow_nan=False))

    def _save_source(self, payload):
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')
        digest = hashlib.sha256(body).hexdigest()
        path = self._folder / 'site777-staging' / 'sources' / (digest + '.json')
        with _job_file_lock(self._folder):
            try:
                with path.open('rb') as existing:
                    if existing.read(len(body) + 1) == body:
                        return digest
            except FileNotFoundError:
                pass
            # 途中書きで残った同名資料も、一時ファイルへの書き込みが完了してから置き換える。
            with atomic_writer(path, binary=True) as stream:
                stream.write(body)
        return digest

    def _job_path(self, model):
        if not model.isdecimal() or not self._day:
            raise ValueError('機種・日付を確認できません。')
        return self._folder / 'site777-staging' / f'{self._day}-{model}.json'

    def _read_job(self, model):
        try:
            with _job_file_lock(self._folder):
                return json.loads(self._job_path(model).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def _write_job(self, model, data):
        with _job_file_lock(self._folder):
            self._write(self._job_path(model), data)

    def _low_path(self):
        return self._folder / 'site777-staging' / f'{self._day}-low.json'

    def _low_racks(self):
        """その日に確定した数値で MIN_SAVED_GAMES 未満だった台（機種コード→台番号の集合）。保存しないので DB には無いが、
        機種の台がそろったかを数えるときは済みに数える（数えないと、その機種・その日を毎回開き直す）。"""
        try:
            data = json.loads(self._low_path().read_text(encoding='utf-8'))
            return {str(k): {int(r) for r in v} for k, v in data.items()}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _remember_low(self, model, racks, captured_at=None):
        """確定した日の500G未満の台を覚える。確定前の日は覚えない（あとで回って500Gを超えることがあるため）。
        書けなくても取り込みは続ける（次に開いたときにその機種を開き直すだけ）。新たに書き込んだら True。"""
        if self._unfinished([self._day], self._unfinished_from(captured_at)):
            return False
        wanted = sorted(racks)
        try:
            with _low_file_lock(self._folder):
                data = {k: sorted(v) for k, v in self._low_racks().items()}
                if data.get(model, []) == wanted:
                    return False
                data[model] = wanted
                self._write(self._low_path(), data)
                return True
        except OSError:
            return False

    def _check(self, epoch):
        with self._state_lock:
            if epoch != self._epoch:
                raise StaleRun('取り込みの設定が変わったため停止しました。')
        if self._active_url and self._window and not source.same_page(self._window.get_current_url(), self._active_url):
            raise ValueError('読み取り中に表示ページが変わったため保存を止めました。')

    def _occupied(self):
        if not self._db_path.is_file():
            return set()
        # アナスロで補った台と確定前のサイトセブンの台はまだ無いものとして数える（取り直して置き換えるため、2026-11-07・11-08）。
        with closing(sqlite3.connect(self._db_path.resolve().as_uri()+'?mode=ro', uri=True, timeout=DB_WAIT)) as db:
            return {r['rack'] for r in (json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM records WHERE json_extract(payload,'$.store')=? "
                "AND json_extract(payload,'$.rate')='20' AND json_extract(payload,'$.day')=?",
                (source.SHOP, self._day))) if self._counts_as_saved(r)}

    def _saved_racks(self):
        """その日の保存済みの台番号（取り込まない機種＝is_excluded_machine と、アナスロで補った台は数えない）。DB は読むだけ。"""
        if not self._db_path.is_file():
            return set()
        with closing(sqlite3.connect(self._db_path.resolve().as_uri()+'?mode=ro', uri=True, timeout=DB_WAIT)) as db:
            rows = [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM records WHERE json_extract(payload,'$.store')=? "
                "AND json_extract(payload,'$.rate')='20' AND json_extract(payload,'$.day')=?",
                (source.SHOP, self._day))]
        # アナスロで補った台・確定前のサイトセブンの台は数えない（取り直して置き換えるため、2026-11-07・11-08）。
        return {r['rack'] for r in rows if not is_excluded_machine(r.get('machine')) and self._counts_as_saved(r)}

    def _skip_saved_machines(self, keep_status=False):
        """機種一覧の台数（[31] など）だけ、その機種のサイトセブンの台がその日に保存済みなら、機種ページを開かずに済みにする
        （2026-11-07 利用者「機種一覧で取り込んでってやったら未取り込みに飛べばよくない？なんでまたゴーゴージャグラーからいくの？」。
        開き直すと済んだ機種の覚えが消え、先頭の機種から1つずつ開いて確かめていた）。
        メルヘンの「次の未取り込み台へ」（browser_import.py の machine_progress：保存済みの台を機種名ごとに数え、
        一覧の台数と比べ、一覧の順で最初の足りない機種へ）と同じ考え方。機種は、保存のときと同じ読み替え
        （suggestions の automatic）をした機種名と、サイトセブンの台は出典URLの機種コード（mdc）でも合わせる。
        アナスロで補った台は数えない（置き換えるため）。台数の読めない機種は今までどおり開いて確かめる。
        DB は読むだけ。何も返さない（続きは _next が決める）。"""
        skipped = 0
        for model, count in self._covered_models().items():
            if model in self._done:
                continue
            self._done.add(model)
            self._kept += count
            skipped += 1
        if skipped:
            self._log.write('machines_skipped', day=self._day, skipped=skipped)
            left = sum(1 for key in self._models if key not in self._done)
            text = f'保存済みの{skipped}機種は開かずに飛ばしました。残り{left}機種を取り込みます。'
            # 機種を保存した直後（_next から）は、その機種の結果の文を残して後ろに足す。
            self._status = f'{self._status} {text}' if keep_status and self._status else text
        return None

    def _covered_models(self):
        """機種一覧の台数（[31] など）だけ、その機種の台がその日に保存済みの機種（機種コード→台数）。
        台数の読めない機種は入れない（開いて確かめる）。DB は読むだけ。"""
        return {model: count for model, (done, count, _) in self._machine_counts(self._models).items()
                if type(count) is int and count >= 1 and done >= count}

    def machine_status(self, raw):
        """機種一覧の各機種の横に出す、その日の取り込み状況（2026-11-10 利用者「なぜメルヘンと同じ仕様になってないんだ。
        機種のよこに未取り込みとかもでてないし」。メルヘンの machine_status と同じ考え方）。raw は機種一覧の
        [{model_id, name, count}] の JSON。返すのは日付と、機種ごとの {done, total, excluded}（同じ順）。
        done は保存済みの台と、500G未満で取り込まなかった台の数。DB は読むだけ。"""
        try:
            machines = json.loads(raw).get('machines')
            models = {str(m['model_id']): {'name': str(m['name']), 'count': m.get('count')}
                      for m in machines if str(m.get('model_id', '')).isdecimal()}
        except (TypeError, ValueError, AttributeError, KeyError):
            return {'day': self._day, 'status': []}
        try:
            counts = self._machine_counts(models)
        except (OSError, sqlite3.Error, ValueError):
            counts = {}
        status = []
        for m in machines:
            done, total, excluded = counts.get(str(m.get('model_id', '')), (0, m.get('count'), False))
            if type(total) is int and total >= 1:
                done = min(done, total)
            status.append({'done': done, 'total': total if type(total) is int else None, 'excluded': excluded})
        return {'day': self._day, 'status': status}

    def _machine_counts(self, models):
        """機種コード→（その日に済んだ台の数、一覧の台数、取り込まない機種か）。済んだ台は、保存済みの台（機種名、または
        サイトセブンの台は出典URLの機種コードで合わせる）と、確定した日に500G未満で取り込まなかった台。DB は読むだけ。"""
        rows = []
        if self._db_path.is_file():
            with closing(sqlite3.connect(self._db_path.resolve().as_uri()+'?mode=ro', uri=True, timeout=DB_WAIT)) as db:
                rows = [json.loads(r[0]) for r in db.execute(
                    "SELECT payload FROM records WHERE json_extract(payload,'$.store')=? "
                    "AND json_extract(payload,'$.rate')='20' AND json_extract(payload,'$.day')=?",
                    (source.SHOP, self._day))]
        rows = [r for r in rows if self._counts_as_saved(r) and not is_excluded_machine(r.get('machine'))]
        by_name = {}
        for r in rows:
            by_name.setdefault(r.get('machine'), set()).add(r['rack'])
        racks = {}
        for r in rows:
            if r.get('source_site') != 'site777':
                continue
            try:
                model = dict(source.parse_qsl(source.urlsplit(r.get('source_url') or '').query)).get('mdc')
            except (TypeError, ValueError):
                continue
            if model:
                racks.setdefault(model, set()).add(r['rack'])
        # 500G未満で取り込まなかった台も済みに数える（確定した日だけ覚えている、2026-11-10）。
        for model, low in self._low_racks().items():
            racks.setdefault(model, set()).update(low)
        catalog = read_catalog(self._db_path) if by_name else []
        result = {}
        for model, m in models.items():
            name = suggestions(m['name'], catalog)['automatic'] or m['name']
            result[model] = (len(racks.get(model, set()) | by_name.get(name, set())), m.get('count'),
                             is_excluded_machine(name) or is_excluded_machine(m['name']))
        return result

    def _skip_complete_days(self):
        """機種一覧の台数（[31] など）の合計だけ、その日の台が保存済みなら、機種ページを開かずにその日を飛ばす
        （2026-11-07 利用者「この改善は導入してね」。11/4・11/5 は全台保存済みなのに約50機種の表を開いていた）。
        台数の読めない機種が1つでもあれば飛ばさない（今までどおり機種ごとに確かめる）。全部飛ばせたら完了。
        2026-11-08（Codexのレビュー）：その日の保存済みの台数の合計だけでは判断しない。別の機種の台でも数が足りれば
        「全台保存済み」になっていたため、機種ごとに（_skip_saved_machines と同じ照合で）全機種そろったときだけ飛ばす。"""
        while True:
            counts = [m.get('count') for m in self._models.values()]
            known = [c for c in counts if type(c) is int and c >= 1]
            total, saved = sum(known), len(self._saved_racks())
            covered = self._covered_models() if counts and len(known) == len(counts) else {}
            # 飛ばすかどうかの数（機種数・台数の合計・台数の読めない機種・保存済み・そろった機種）を残す。
            # 名前・URL・会員情報は残さない。
            self._log.write('day_check', day=self._day, machines=len(counts), unknown_counts=len(counts) - len(known),
                            total=total, saved=saved, covered=len(covered))
            if not counts or len(known) != len(counts):
                return None
            if len(covered) < len(self._models):
                return None
            with self._state_lock:
                finished = f'{self._day[5:].replace("-", "/")}（全{total}台が保存済み・機種ページを開かずに飛ばした）'
                self._finished_days.append(finished)
                self._kept = saved
                if not self._queue:
                    automatic = self._enabled
                    self._enabled = False
                    self._pace.configure(False, 15)
                    self._until = None
                    self._status = ('範囲の取り込みが完了しました。' + '、'.join(self._finished_days)
                                    if len(self._finished_days) > 1 else
                                    f'{finished}。取り込む台はありませんでした。')
                    if automatic:
                        self._completed = self._status
                    self._log.write('auto_finished', day=self._day, automatic=automatic)
                    self._save_run(completed=True, locked=True)
                    return {'complete': True}
                # 機種一覧は日付で変わらないので、読んだ一覧のまま次の日を確かめる。
                self._day = self._queue.pop(0)
                if not self._queue:
                    self._until = None
                self._done.clear()
                self._job = None
                self._added = self._kept = self._unknown = 0
                self._status = f'{finished}。次は{self._day}を確かめます。'

    def _next(self, index_url=None):
        # 次の機種を開く前に、ほかの窓が保存し終えた機種を飛ばす（2026-11-13 利用者「今全部取り込んでたのに自動取り込み
        # 終わってなかった」。上からと下からの2つの窓が出会ったあと、相手が済ませた機種を1つずつ開いて（機種・表の2ページ）
        # 確かめていた。今までは機種一覧に戻ったときだけ飛ばしていた）。DB は読むだけ。
        if self._models:
            self._skip_saved_machines(keep_status=True)
        remaining = [m for key, m in self._models.items() if key not in self._done]
        if remaining:
            # 「下から」なら一覧の下から（メルヘンの direction='bottom' と同じ）。
            pick = remaining[-1] if self._direction == 'bottom' else remaining[0]
            return {'action': {'type': 'listed', 'url': pick['url']}}
        if not self._models and index_url:
            return {'action': {'type': 'link', 'url': index_url}}
        with self._state_lock:
            finished = f'{self._day[5:].replace("-", "/")}（追加{self._added}台・既存{self._kept}台・グラフ不明{self._unknown}台）'
            self._finished_days.append(finished)
            if self._queue and index_url:
                # 範囲の次の日へ。表示中のページの「設置機種」のリンク（index_url）から機種一覧を読み直す
                # （日によって設置機種が違うことがある。サイトの既存のリンクを押すだけで、URLを作って開かない）。
                self._day = self._queue.pop(0)
                if not self._queue:
                    self._until = None
                self._models.clear()
                self._done.clear()
                self._index_pages.clear()
                self._job = None
                self._added = self._kept = self._unknown = 0
                self._status = f'{finished}が完了。次は{self._day}を取り込みます。'
                return {'action': {'type': 'link', 'url': index_url}}
            automatic = self._enabled
            self._enabled = False
            self._pace.configure(False, 15)
            left = len(self._queue)
            left_days = list(self._queue)
            self._queue = []
            self._until = None
            if left:
                self._status = (f'{finished}まで完了しました。機種一覧のページが分からないため、残りの{left}日は'
                                '取り込んでいません。機種一覧を開いてから、残りの日を選んで再開してください。')
            elif len(self._finished_days) > 1:
                self._status = '範囲の取り込みが完了しました。' + '、'.join(self._finished_days)
            else:
                md = self._day[5:].replace('-', '/')
                self._status = f'指定日（{md}）の取り込みが完了しました。追加{self._added}台、既存を保持{self._kept}台、グラフ不明{self._unknown}台。'
            # 残りの日が分からず止まったとき（left）は、続きを選べるよう窓を閉じない。
            if automatic and not left:
                self._completed = self._status
            status = self._status
        if left:
            self._save_run(stopped=REASON_LABELS['range_unknown'], remaining=left_days)
            self._stopped('range_unknown', status, left=left, was_on=automatic, left_days=left_days)
        else:
            self._log.write('auto_finished', day=self._day, automatic=automatic)
            self._save_run(completed=True)
        return {'complete': True}

    def capture(self, raw, epoch):
        if not isinstance(raw, str) or len(raw) > 12*1024*1024:
            raise ValueError('読み取り資料が大きすぎるか不正です。')
        if not self._work_lock.acquire(blocking=False):
            return {'error': '前の読み取りの処理中です。'}
        try:
            self._active_url = None
            self._check(epoch)
            payload = json.loads(raw)
            actual = self._window.get_current_url() if self._window else payload.get('url')
            if not source.same_page(actual, payload.get('url')):
                raise ValueError('表示中のページと読み取り元が違います。')
            url = source.source_url(payload.get('url'))
            self._active_url = url
            kind = source.PATHS[source.urlsplit(url).path]
            if payload.get('kind') != kind:
                raise ValueError('読み取り資料のページ種類が違います。')
            if kind in ('index', 'graphs'):
                page = payload.get('page')
                selected = dict(source.parse_qsl(source.urlsplit(url).query)).get('pan', '1')
                if type(page) is not int or page < 1 or str(page) != selected:
                    raise ValueError('読み取り資料と表示中のページ番号が違います。')
            self._stage = kind
            saves_before = self._own_saves
            result = self._capture(payload, epoch)
            with self._state_lock:
                current = epoch == self._epoch
                if current and result.get('action'):
                    self._pending_navigation = True
                    self._pending_since = monotonic()
                if current and self._own_saves > saves_before:
                    # この窓自身が新しく保存した＝取り込みが進んだ。自動の再開の回数を数え直す
                    # （別の窓が保存した機種を _skip_saved_machines で飛ばしただけでは戻さない）。
                    self._resume_count = 0
            if not current:
                raise StaleRun('取り込みの設定が変わったため停止しました。')
            self._pace.pause('次のページを待ちます。')
            result['state'] = self.state()
            return result
        except Exception as error:
            with self._state_lock:
                # 停止・再開の前に始まった処理（古い実行番号）の失敗は、今の取り込みを止めない（2026-11-08 Codexの
                # レビュー：停止前の読み取りが遅れて届くと、再開したばかりの取り込みまでOFFにしていた）。
                stale = isinstance(error, StaleRun) or epoch != self._epoch
                was_on = self._enabled
                if not stale:
                    self._enabled = False
                    self._pace.configure(False, 15)
                    self._status = str(error)
            # 元資料・URL・会員情報をログに出さない。
            if stale:
                self._log.write('stale_result_dropped', error_type=type(error).__name__)
                return {'error': str(error), 'stale': True, 'state': self.state()}
            self._log.write('capture_stopped', error_type=type(error).__name__)
            self._stopped('capture_error', str(error), error_type=type(error).__name__, was_on=was_on)
            return {'error': str(error), 'state': self.state()}
        finally:
            self._active_url = None
            self._work_lock.release()

    def _capture(self, payload, epoch):
        kind = payload['kind']
        if kind == 'index':
            machines = payload.get('machines')
            if not isinstance(machines, list) or not machines:
                raise ValueError('機種一覧を読み取れません。0機種を完了とは扱いません。')
            for m in machines:
                url = source.source_url(m.get('url'), 'model')
                model = dict(source.parse_qsl(source.urlsplit(url).query)).get('mdc')
                if not model or model != m.get('model_id') or not isinstance(m.get('name'), str) or not m['name']:
                    raise ValueError('掲載機種の情報が不正です。')
                if not is_excluded_machine(m['name']):
                    self._models[model] = {**m, 'url': url}
            self._index_pages.add(payload['page'])
            for page in payload.get('pages', []):
                if page['number'] not in self._index_pages:
                    return {'action': {'type': 'page', 'number': page['number']}}
            return self._skip_complete_days() or (self._skip_saved_machines() or self._next(payload.get('index_url')))
        if kind == 'model':
            url = source.source_url(payload.get('table_url'), 'table')
            return {'action': {'type': 'link', 'url': url}}
        if kind == 'table':
            table_at = self._now()
            days = {source.day_from_label(d['label'], table_at): d for d in payload.get('days', [])}
            if not days:
                raise ValueError('掲載日付がありません。')
            with self._state_lock:
                self._days = sorted(days, reverse=True)
                self._day = self._day or self._days[0]
            if self._day not in days:
                raise ValueError('指定した日付はこの機種のページにありません。')
            if self._unfinished([self._day], self._unfinished_from(table_at)) and not self._today_ok:
                # 確認していない確定前の日は保存しない（手動の取り込みの守り。自動は開始のときに configure が確かめ、
                # 確定前の最初の日は進むだけなので、自動の途中でここに来ることはない）。
                raise ValueError(f'{self._day[5:].replace("-", "/")}の分はまだ確定していないため、取り込みませんでした'
                                 '（その日の23:30より前）。取り込むときはカードの確認から（23:30以降に取り込み直すと置き換わります）。')
            if source.day_from_label(payload.get('selected_md'), table_at) != self._day:
                return {'action': {'type': 'link', 'url': days[self._day]['url']}}
            rows = source.table_records(payload, self._day, table_at)
            model = payload['model_id']
            occupied = self._occupied()
            # 500G未満（0Gを含む）の台は取り込まない（2026-11-10 利用者）。グラフも読まない。すでに保存してある台は消さない。
            low = [r['rack'] for r in rows if r['games'] < MIN_SAVED_GAMES]
            if self._remember_low(model, low, table_at):
                self._own_saves += 1
            wanted = [r for r in rows if r['rack'] not in occupied and r['games'] >= MIN_SAVED_GAMES]
            skipped = f'（{MIN_SAVED_GAMES}G未満の{len(low)}台は取り込まず）' if low else ''
            if not wanted:
                self._done.add(model)
                self._kept += len(rows) - len(low)
                self._status = f'{payload["machine"]}：{len(rows) - len(low)}台は既存の記録を保持しました{skipped}。'
                return self._next(payload.get('index_url'))
            digest = self._save_source(payload)
            old = self._read_job(model)
            self._job = {'table': payload, 'table_at': table_at.isoformat(timespec='seconds'),
                         'rows': wanted, 'all_racks': [r['rack'] for r in rows],
                         'all_my': {str(r['rack']): r['my'] for r in rows},
                         'graphs': old.get('graphs', {}) if old.get('table_sha') == digest else {},
                         'pages': old.get('pages', []) if old.get('table_sha') == digest else [], 'table_sha': digest,
                         'no_graph': old.get('no_graph', []) if old.get('table_sha') == digest else []}
            self._write_job(model, self._job)
            if {r['rack'] for r in wanted} <= {int(k) for k in self._job['graphs']} | set(self._job['no_graph']):
                return self._finish(self._job, epoch, payload.get('index_url'))
            self._status = f'{payload["machine"]}：表{len(rows)}台、未保存{len(wanted)}台のグラフを読みます。'
            return {'action': {'type': 'link', 'url': source.source_url(payload.get('graph_url'), 'graphs')}}
        if kind != 'graphs':
            raise ValueError('先に同じ機種・日付の全台一覧を取り込んでください。')
        # グラフ一覧から押したとき（2026-11-07 利用者「グラフの時に日付を切り替えてる挙動じゃなかった」）：
        # まだこの機種の全台一覧を読んでいなければ、ページにある「大当り一覧」のリンクで全台一覧へ移る
        # （日付の切り替えは全台一覧で行う）。読んだ後で日付だけ違うなら、ページにある日付のタブを押す。
        if not self._job or payload.get('model_id') != self._job['table']['model_id']:
            if payload.get('table_url'):
                return {'action': {'type': 'link', 'url': source.source_url(payload['table_url'], 'table')}}
            raise ValueError('先に同じ機種・日付の全台一覧を取り込んでください。')
        if source.day_from_label(payload.get('selected_md'), self._now()) != self._day:
            tabs = {source.day_from_label(d['label'], self._now()): d for d in payload.get('days', [])}
            if self._day in tabs:
                return {'action': {'type': 'link', 'url': source.source_url(tabs[self._day]['url'], 'graphs')}}
            raise ValueError('指定した日付はこの機種のグラフ一覧にありません。')
        job = self._job
        model = job['table']['model_id']
        if payload.get('count') != len(job['all_racks']):
            raise ValueError('表とグラフ一覧の表示台数が違います。')
        if source.day_from_label(payload.get('selected_md'), self._now()) != self._day or payload.get('model_id') != model:
            raise ValueError('グラフの機種・日付が全台一覧と一致しません。')
        needed = {r['rack'] for r in job['rows']} - set(job.get('no_graph', []))   # グラフなしにした台は待たない
        remaining = needed - {int(k) for k in job['graphs']}
        # 画像を読む前に表示中の台番を検証する。500G未満・保存済みの台は、同じページでも画像を待たない。
        page_racks = payload.get('graph_racks')
        if page_racks is not None:
            if (not isinstance(page_racks, list) or not 1 <= len(page_racks) <= 20
                    or any(type(r) is not int or r not in job['all_racks'] for r in page_racks)
                    or len(set(page_racks)) != len(page_racks)):
                raise ValueError('グラフ一覧の台番号が不明・重複、または全台一覧と一致しません。')
        if payload.get('deferred_images'):
            # 全画像を保持した後のDB保存失敗では、再開後も同じページへ戻る。
            # 「未完了ページなし」で再停止せず、検証済み資料の保存からやり直す。
            if not remaining:
                return self._finish(job, epoch, payload.get('index_url'))
            if payload['page'] in job['pages']:
                for other in payload.get('pages', []):
                    if other['number'] not in job['pages']:
                        return {'action': {'type': 'page', 'number': other['number']}}
                raise ValueError('未完了のグラフページがありません。全台分を確認してください。')
            return {'prepare_graphs': True, 'wanted_racks': sorted(remaining)}
        expected = {int(k): v for k,v in job.get('all_my', {}).items()} or set(job['all_racks'])
        if page_racks is not None and not (remaining & set(page_racks)) and payload.get('graphs') == []:
            got = {}  # 対象外だけのページ。画像不要でも、ページ確認と次ページへの移動は行う。
        else:
            got = source.graph_records(payload, self._day, model, expected, self._now())
        if payload.get('partial_graphs') is True:
            # 画像待ちの失敗時だけ、現在のページで読めた必要台を退避する。
            # 未取得台を完了扱いせず、ページ完了・本体DBへの保存は後の通常処理へ残す。
            if (page_racks is None or not got or not set(got) <= remaining & set(page_racks)
                    or payload['page'] in job['pages']):
                raise ValueError('途中保存の台が必要な台・表示中のページと一致しません。')
            staged = {**job, 'graphs': {**job['graphs'], **{str(r): g for r, g in got.items()}}}
            self._save_source(payload)
            self._check(epoch)
            self._write_job(model, staged)
            self._job = staged
            self._log.write('graphs_staged', day=self._day, model=model, page=payload['page'], racks=sorted(got))
            return {'partial_saved': True}
        if page_racks is not None and (not set(got) <= set(page_racks)
                                      or not (remaining & set(page_racks)) <= set(got)):
            raise ValueError('表示中の必要な台のグラフがそろっていません。完了とは扱いません。')
        page = payload['page']
        if page in job['pages']:
            raise ValueError('同じグラフページへ戻ったため停止しました。')
        if any(str(rack) in job['graphs'] for rack in got):
            raise ValueError('別のページに同じ台のグラフがあるため停止しました。')
        for rack, graph in got.items():
            job['graphs'][str(rack)] = graph
        job['pages'].append(page)
        self._save_source(payload)
        self._check(epoch)
        self._write_job(model, job)
        needed = {r['rack'] for r in job['rows']} - set(job.get('no_graph', []))
        present = {int(r) for r in job['graphs']}
        if not needed <= present:
            for other in payload.get('pages', []):
                if other['number'] not in job['pages']:
                    return {'action': {'type': 'page', 'number': other['number']}}
            raise ValueError('全台のグラフがそろっていません。完了とは扱いません。')
        return self._finish(job, epoch, payload.get('index_url'))

    def _backup_after_close(self):
        """窓を閉じたあとに1回だけ呼ぶ（site777_browser.run）。1機種でも保存していれば、バックアップ・閲覧用ファイルを
        書き出す。保存中の処理があれば終わるのを待つ。書き出しに失敗してもDBへの保存は済んでいる（印を残し、次に閉じたときにまた書く）。
        戻り値：失敗したときの文（親画面のログ欄に出す）。成功・書き出す分が無いときは None。"""
        with self._work_lock:
            if not self._backup_due and not self._backup_due_path().is_file():
                return None
            try:
                store = self._store_factory(self._db_path)
                try:
                    written = str(auto_backup(store, self._folder / 'pscube-viewer.json'))
                finally:
                    store.close()
            except (OSError, ValueError, sqlite3.Error) as error:
                written = f'バックアップに失敗（取り込みは保存済み）：{type(error).__name__}'
            # 成功は「バックアップ済み」で始まる文（「バックアップ済み（より新しい時点の書き出しが先に済んでいます）」も成功）。
            ok = written.startswith(BACKUP_OK)
            self._set_backup_due(not ok)
        self._log.write('backup_after_close', ok=ok, result=written[:200])
        return None if ok else written

    def _table_time(self, job):
        try:
            value = datetime.fromisoformat(job.get('table_at', ''))
            if value.tzinfo is not None:
                return value
        except (TypeError, ValueError, AttributeError):
            pass
        return self._now()

    def _finish(self, job, epoch, index_url):
        model = job['table']['model_id']
        catalog = read_catalog(self._db_path)
        name = job['table']['machine']
        name = suggestions(name, catalog)['automatic'] or name
        graphs = {int(k): v for k,v in job['graphs'].items()}
        for rack in job.get('no_graph', []):
            graphs.setdefault(rack, source.missing_graph())      # グラフなしで進めた台（skip_graph）
        backup = source.make_backup(job['table'], job['rows'], graphs, self._day, name, catalog, self._table_time(job))
        self._check(epoch)
        store = self._store_factory(self._db_path)
        try:
            self._check(epoch)
            summary = store.import_backup(backup)
        finally:
            store.close()
        # バックアップ・閲覧用ファイル（DB全体。約40MBを同期フォルダーなど数か所へ）は、ここでは書かず、窓を閉じたあとに
        # 1回だけ書く（_backup_after_close。メルヘンの backup_after_session と同じ。2026-11-21 利用者「まとめて」）。
        # 1機種ごとに書いていたので、1日約55機種で約55回の全体書き出しになり、取り込みが重かった。
        self._set_backup_due(True)
        if summary['added'] > 0:
            self._own_saves += 1
        self._done.add(model)
        self._added += summary['added']
        self._kept += summary['kept_local']
        unknown = sum(r['graph'] is None for r in backup['records'])
        self._unknown += unknown
        self._status = f'{name}：追加{summary["added"]}台、既存を保持{summary["kept_local"]}台、グラフ不明{unknown}台。'
        self._job = None
        with self._state_lock:
            self._clear_hidden_wait()
        self._check(epoch)
        return self._next(index_url)
