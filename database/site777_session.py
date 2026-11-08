"""表→グラフ各ページ→掲載済みの次機種。通信は表示ブラウザのリンク操作だけ。"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
from time import monotonic

from anaslo_converter import read_catalog, suggestions
from browser_import import clean_overlay_layout
from pscube_import import (PscubeStore, PscubeRandomCapture, auto_backup, business_day, is_excluded_machine,
                           recent_business_days)
from file_io import write_notice
from site777_browser import Bridge, LAST_STOP_NAME
import site777_import as source

# 移動を指示してから、読み込みの完了（成功・失敗）がこれだけ来なければ止める（2026-11-08）。
# 移動中は次の読み取りをしない（旧画面を読み直さない）ので、来ないままだと止まらずに待ち続けるため。
NAVIGATION_LIMIT = 90
BACKUP_OK = 'バックアップ済み'
# 自動取り込み中に止まったら、3分後に自動で再開する（2026-11-08 利用者「別店舗など、取り込み対象以外へ移動しようとした
# （navigation_blocked）これ以外は全て3分後には自動復帰でお願いします」「利用者の停止ボタンも対象外」）。
# 取り込みが進まないまま（機種・日が1つも済まないまま）自動の再開が5回続いたら、それ以上は再開しない
# （利用者「連続5回まで」。直らない原因で3分ごとにサイトへアクセスし続けないため）。
RESUME_DELAY = 180
RESUME_LIMIT = 5
# 停止の理由コードの呼び名（ホームのログ欄・前回の案内・カードに出す。2026-11-08 Codexの提案「画像待ちの上限」
# 「移動失敗」「認証の確認が必要」などを区別し、PCホームにも残す）。
REASON_LABELS = {
    'graph_retry_limit': '画像待ちの上限', 'graph_retry_storage': '画像待ち',
    'not_moved': '移動失敗（リンクで移動しない）', 'navigation_timeout': '移動失敗（読み込みが終わらない）',
    'navigation_failed': '移動失敗（ページを読み込めない）', 'login_required': 'ログインの確認が必要',
    'navigation_blocked': '対象外のページへの移動', 'capture_error': '読み取りの失敗',
    'card_error': '取り込みカードの失敗', 'overlay_failed': '取り込みカードを出せない',
    'range_unknown': '次の日の機種一覧が分からない', 'user_stop': '停止ボタン', 'stopped': '停止',
}
# 前回の取り込みの範囲・済んだ日・止まった理由（2026-11-08 Codexの提案：窓を開き直すと日付の範囲を選び直しになり、
# 前回どこまで取り込んだかが分からなかった）。窓を開いたとき、カードに案内を出し、残りの日を選んでおく。
LAST_RUN_NAME = 'site777-last-run.json'
# 機種ごとの途中の記録を残す日数（今の営業日から。サイトが見せる8日分より長く取る。2026-11-08）。
STAGING_KEEP_DAYS = 14
RESUMABLE = frozenset({'not_moved', 'navigation_timeout', 'navigation_failed', 'capture_error',
                       'graph_retry_limit', 'graph_retry_storage', 'card_error', 'overlay_failed',
                       'range_unknown'})


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
    """サイトセブンの間隔：5〜7秒のランダム（2026-11-07 利用者「取り込み間隔も10秒程度じゃなくて5～7秒程度にしよう」）。
    P’s CUBE（PscubeRandomCapture の10〜20秒）は変えない。"""
    LOW, HIGH = 5, 7


DIRECTIONS = ('top', 'bottom')


class Session(Bridge):
    def __init__(self, data_dir, log, *, now=None, store_factory=PscubeStore):
        super().__init__(log)
        self._folder = Path(data_dir)
        self._db_path = self._folder / 'pscube.sqlite3'
        self._now = now or (lambda: datetime.now(source.JST))
        self._store_factory = store_factory
        self._window = None
        self._state_lock = threading.Lock()
        self._work_lock = threading.Lock()
        self._epoch = 0
        self._pace = Site777RandomCapture()
        # 機種を一覧の上から（top）か下から（bottom）か。メルヘンの「上から取り込む／下から取り込む」と同じ（2026-11-07）。
        self._direction = 'top'
        self._enabled = False
        self._days = recent_business_days(self._now(), count=8)
        # 初めに選ぶ日は前の営業日（2026-11-08）。今の営業日（営業中）を取り込むと、その時点の数値のまま残り、
        # 後から取り込み直しても置き換わらないため（サイトセブンは無い台だけ補う）。今日は確認してから（_today_ok）。
        self._day = self._days[1]
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
        # 今の工程（読み取ったページの種類）。停止の記録に残す。
        self._stage = None
        # バックアップ・同期フォルダーへの書き出しがうまくいかなかったときの文（DBには保存済み）。完了の文に添える。
        self._backup_note = None
        # 自動の再開（RESUME_DELAY 秒後）。_resume_at は monotonic の時刻、_resume_plan は再開する日・範囲・向き・理由、
        # _resume_count は取り込みが進まないまま続けて再開した回数、_resume_serial は再開のたびに増やす番号
        # （記録用。2026-11-08 からカードはこれで読み込み直しの回数を戻さない。再開1回につき読み込み1回）。
        self._resume_at = None
        self._resume_label = None
        self._resume_plan = None
        self._resume_count = 0
        self._resume_serial = 0
        # 今の取り込みの範囲の始まり・終わり（前回の案内に残す）と、窓を開いたときの前回の案内の文。
        self._run_start = self._run_until = None
        self._previous = None
        self._load_previous()
        self._prune_staging()

    def _prune_staging(self):
        """もう取り込めない古い日の、機種ごとの途中の記録（site777-staging/日付-機種.json）を消す（2026-11-08。
        サイトが見せるのは8日分なので、続きから取り込むのに使えない。消す仕組みが無く、1日に約50本ずつ増えていた）。
        今の営業日より STAGING_KEEP_DAYS 日以上前の日だけ。元の資料（sources、推定差枚を付け直すのに使う）は残す。
        消せなくても窓は開く。"""
        cutoff = (date.fromisoformat(self._days[0]) - timedelta(days=STAGING_KEEP_DAYS)).isoformat()
        removed = 0
        try:
            for path in (self._folder / 'site777-staging').glob('*.json'):
                match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})-\d+\.json', path.name)
                if match and match[1] < cutoff:
                    path.unlink()
                    removed += 1
        except OSError:
            pass
        if removed:
            self._log.write('staging_pruned', removed=removed, before=cutoff)

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
                    'today': self._today(), 'today_ok': self._today_ok}

    def _today(self):
        """今の営業日（午前3時で切り替え）。この日の分は営業中の数値になりうる。"""
        return business_day(self._now())

    @staticmethod
    def _unfinished(days, today):
        """今の営業日以降の日（営業中・まだ始まっていない日。午前0〜3時に出る翌日のタブも含む）。"""
        return [d for d in days if d and d >= today]

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
        write_notice(self._folder / LAST_STOP_NAME,
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
            # 止まる前のバックアップの失敗も引き継ぐ（2026-11-08。configure(True) が消していたので、再開のあと
            # 書き出さずに完了すると、完了の文に失敗が出なかった）。
            run = (self._run_start, self._run_until, list(self._finished_days), self._backup_note)
        try:
            self.configure(True, plan['day'], plan['until'], plan['direction'], plan.get('today_ok', False))
        except ValueError as error:
            self._log.write('auto_resume_failed', reason=plan['reason'], error=clean_reason(error))
            return None
        with self._state_lock:
            self._run_start, self._run_until = run[0], run[1]
            self._backup_note = run[3]
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

    def _with_backup(self, text):
        if not self._backup_note:
            return text
        return (f'{text} ただし{self._backup_note}。バックアップ・同期フォルダーへの書き出しを確かめてください'
                '（サイトへ戻る必要はありません。本体の「バックアップ・同期」で状態を見られます）。')

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
            today = self._today()
            unfinished = self._unfinished(planned, today)
            if enabled and unfinished and not today_ok:
                raise ValueError(f'{unfinished[0][5:].replace("-", "/")}の分は営業中の数値になりうるため、確認してから'
                                 '開始してください（取り込んだ時点の数値のまま残り、後から取り込み直しても置き換わりません）。')
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
                self._backup_note = None
                self._resume_count = 0
            self._pending_navigation = False
            self._blocked_navigation = False
            self._pace.configure(enabled, 15)
            self._epoch += 1
            self._status = '自動取り込みを開始します。' if enabled else '停止しました。'
        if enabled:
            self._save_run()
        return self.state()

    def _loaded(self):
        with self._state_lock:
            self._pending_navigation = False
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
            else:
                self.pause('P-STATIONの20円スロット以外への移動を止めました。'
                           '対象店の画面を確認してから再開してください。自動の再取得は行いません。', 'navigation_blocked')
            with self._state_lock:
                self._blocked_navigation = True
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
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(path)

    def _save_source(self, payload):
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')
        digest = hashlib.sha256(body).hexdigest()
        folder = self._folder / 'site777-staging' / 'sources'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (digest + '.json')
        try:
            with path.open('xb') as stream:
                stream.write(body)
        except FileExistsError:
            pass
        return digest

    def _job_path(self, model):
        if not model.isdecimal() or not self._day:
            raise ValueError('機種・日付を確認できません。')
        return self._folder / 'site777-staging' / f'{self._day}-{model}.json'

    def _check(self, epoch):
        with self._state_lock:
            if epoch != self._epoch:
                raise StaleRun('取り込みの設定が変わったため停止しました。')
        if self._active_url and self._window and not source.same_page(self._window.get_current_url(), self._active_url):
            raise ValueError('読み取り中に表示ページが変わったため保存を止めました。')

    def _occupied(self):
        if not self._db_path.is_file():
            return set()
        # アナスロで補った台はまだ無いものとして数える（サイトセブンで置き換えるため、2026-11-07）。
        with closing(sqlite3.connect(self._db_path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            return {r['rack'] for r in (json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM records WHERE json_extract(payload,'$.store')=? "
                "AND json_extract(payload,'$.rate')='20' AND json_extract(payload,'$.day')=?",
                (source.SHOP, self._day))) if r.get('source_site') != 'anaslo'}

    def _saved_racks(self):
        """その日の保存済みの台番号（取り込まない機種＝is_excluded_machine と、アナスロで補った台は数えない）。DB は読むだけ。"""
        if not self._db_path.is_file():
            return set()
        with closing(sqlite3.connect(self._db_path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            rows = [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM records WHERE json_extract(payload,'$.store')=? "
                "AND json_extract(payload,'$.rate')='20' AND json_extract(payload,'$.day')=?",
                (source.SHOP, self._day))]
        # アナスロで補った台は数えない（サイトセブンで置き換えるため、2026-11-07）。
        return {r['rack'] for r in rows if not is_excluded_machine(r.get('machine')) and r.get('source_site') != 'anaslo'}

    def _skip_saved_machines(self):
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
            self._status = f'保存済みの{skipped}機種は開かずに飛ばしました。残り{left}機種を取り込みます。'
        return None

    def _covered_models(self):
        """機種一覧の台数（[31] など）だけ、その機種の台がその日に保存済みの機種（機種コード→台数）。
        台数の読めない機種は入れない（開いて確かめる）。DB は読むだけ。"""
        if not self._db_path.is_file():
            return {}
        with closing(sqlite3.connect(self._db_path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            rows = [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM records WHERE json_extract(payload,'$.store')=? "
                "AND json_extract(payload,'$.rate')='20' AND json_extract(payload,'$.day')=?",
                (source.SHOP, self._day))]
        rows = [r for r in rows if r.get('source_site') != 'anaslo' and not is_excluded_machine(r.get('machine'))]
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
        catalog = read_catalog(self._db_path) if by_name else []
        covered = {}
        for model, m in self._models.items():
            count = m.get('count')
            if type(count) is not int or count < 1:
                continue
            name = suggestions(m['name'], catalog)['automatic'] or m['name']
            if len(racks.get(model, set()) | by_name.get(name, set())) >= count:
                covered[model] = count
        return covered

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
                    self._status = self._with_backup('範囲の取り込みが完了しました。' + '、'.join(self._finished_days)
                                                     if len(self._finished_days) > 1 else
                                                     f'{finished}。取り込む台はありませんでした。')
                    if automatic:
                        self._completed = self._status
                    self._log.write('auto_finished', day=self._day, automatic=automatic,
                                    backup_ok=not self._backup_note)
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
                self._status = f'指定日の取り込みが完了しました。追加{self._added}台、既存を保持{self._kept}台、グラフ不明{self._unknown}台。'
            self._status = self._with_backup(self._status)
            # 残りの日が分からず止まったとき（left）は、続きを選べるよう窓を閉じない。
            if automatic and not left:
                self._completed = self._status
            status = self._status
        if left:
            self._save_run(stopped=REASON_LABELS['range_unknown'], remaining=left_days)
            self._stopped('range_unknown', status, left=left, was_on=automatic, left_days=left_days)
        else:
            self._log.write('auto_finished', day=self._day, automatic=automatic, backup_ok=not self._backup_note)
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
            done_before = len(self._done) + len(self._finished_days)
            result = self._capture(payload, epoch)
            with self._state_lock:
                current = epoch == self._epoch
                if current and result.get('action'):
                    self._pending_navigation = True
                    self._pending_since = monotonic()
                if current and len(self._done) + len(self._finished_days) > done_before:
                    # 機種・日が1つ済んだ＝取り込みが進んだ。自動の再開の回数を数え直す。
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
            days = {source.day_from_label(d['label'], self._now()): d for d in payload.get('days', [])}
            if not days:
                raise ValueError('掲載日付がありません。')
            with self._state_lock:
                self._days = sorted(days, reverse=True)
                self._day = self._day or self._days[0]
            if self._day not in days:
                raise ValueError('指定した日付はこの機種のページにありません。')
            if self._unfinished([self._day], self._today()) and not self._today_ok:
                # 確認していない今の営業日以降の日は保存しない（手動の取り込みの守り。自動は開始のときに configure が
                # 確かめ、営業日は進むだけなので、自動の途中でここに来ることはない）。
                raise ValueError(f'{self._day[5:].replace("-", "/")}の分は営業中の数値になりうるため、取り込みませんでした。'
                                        '閉店後のデータか確かめてから、カードの確認で取り込んでください。')
            if source.day_from_label(payload.get('selected_md'), self._now()) != self._day:
                return {'action': {'type': 'link', 'url': days[self._day]['url']}}
            rows = source.table_records(payload, self._day, self._now())
            model = payload['model_id']
            occupied = self._occupied()
            wanted = [r for r in rows if r['rack'] not in occupied]
            if not wanted:
                self._done.add(model)
                self._kept += len(rows)
                self._status = f'{payload["machine"]}：{len(rows)}台は既存の記録を保持しました。'
                return self._next(payload.get('index_url'))
            digest = self._save_source(payload)
            old = {}
            try:
                old = json.loads(self._job_path(model).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
            self._job = {'table': payload, 'rows': wanted, 'all_racks': [r['rack'] for r in rows],
                         'all_my': {str(r['rack']): r['my'] for r in rows},
                         'graphs': old.get('graphs', {}) if old.get('table_sha') == digest else {},
                         'pages': old.get('pages', []) if old.get('table_sha') == digest else [], 'table_sha': digest}
            self._write(self._job_path(model), self._job)
            if {r['rack'] for r in wanted} <= {int(k) for k in self._job['graphs']}:
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
        if payload.get('deferred_images'):
            if payload['page'] in job['pages']:
                for other in payload.get('pages', []):
                    if other['number'] not in job['pages']:
                        return {'action': {'type': 'page', 'number': other['number']}}
                raise ValueError('未完了のグラフページがありません。全台分を確認してください。')
            return {'prepare_graphs': True}
        expected = {int(k): v for k,v in job.get('all_my', {}).items()} or set(job['all_racks'])
        got = source.graph_records(payload, self._day, model, expected, self._now())
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
        self._write(self._job_path(model), job)
        needed = {r['rack'] for r in job['rows']}
        present = {int(r) for r in job['graphs']}
        if not needed <= present:
            for other in payload.get('pages', []):
                if other['number'] not in job['pages']:
                    return {'action': {'type': 'page', 'number': other['number']}}
            raise ValueError('全台のグラフがそろっていません。完了とは扱いません。')
        return self._finish(job, epoch, payload.get('index_url'))

    def _finish(self, job, epoch, index_url):
        model = job['table']['model_id']
        catalog = read_catalog(self._db_path)
        name = job['table']['machine']
        name = suggestions(name, catalog)['automatic'] or name
        backup = source.make_backup(job['table'], job['rows'], {int(k): v for k,v in job['graphs'].items()},
                                    self._day, name, catalog, self._now())
        self._check(epoch)
        store = self._store_factory(self._db_path)
        try:
            self._check(epoch)
            summary = store.import_backup(backup)
            # 書き出しに失敗してもDBへの保存は済んでいる（auto_backup は例外を出さず文で返す）。
            # 今までは戻り値を捨て、いつもの完了の文で窓を閉じていた（2026-11-08 Codexのレビュー）。
            written = auto_backup(store, self._folder / 'pscube-viewer.json')
        finally:
            store.close()
        if written != BACKUP_OK:
            self._backup_note = str(written)
            self._log.write('backup_problem', result=self._backup_note)
        elif self._backup_note:
            # 書き出しは毎回DB全体なので、あとで成功すれば前の失敗の分も追いつく（2026-11-08）。
            self._backup_note = None
            self._log.write('backup_recovered')
        self._done.add(model)
        self._added += summary['added']
        self._kept += summary['kept_local']
        unknown = sum(r['graph'] is None for r in backup['records'])
        self._unknown += unknown
        self._status = self._with_backup(
            f'{name}：追加{summary["added"]}台、既存を保持{summary["kept_local"]}台、グラフ不明{unknown}台。')
        self._job = None
        self._check(epoch)
        return self._next(index_url)
