"""表→グラフ各ページ→掲載済みの次機種。通信は表示ブラウザのリンク操作だけ。"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

from anaslo_converter import read_catalog, suggestions
from browser_import import clean_overlay_layout
from pscube_import import PscubeStore, PscubeRandomCapture, auto_backup, is_excluded_machine, recent_business_days
from site777_browser import Bridge
import site777_import as source


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
        self._day = self._days[0]
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
        self._blocked_navigation = False

    def state(self):
        with self._state_lock:
            return {'enabled': self._enabled, 'epoch': self._epoch, 'day': self._day,
                    'until': self._until, 'queue': list(self._queue), 'finished_days': list(self._finished_days),
                    'days': self._days, 'status': self._status, 'added': self._added, 'kept': self._kept,
                    'ready': self._pace.due() is not None, 'unknown_graphs': self._unknown,
                    'direction': self._direction}

    def configure(self, enabled, day=None, until=None, direction=None):
        """自動取り込みのON/OFFと取り込む日。until を付けると day〜until の範囲（どちらが先でもよい）を
        古い日から順に取り込む。範囲は掲載日（_days）の中だけ。"""
        if type(enabled) is not bool:
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
            self._pending_navigation = False
            self._blocked_navigation = False
            self._pace.configure(enabled, 15)
            self._epoch += 1
            self._status = '自動取り込みを開始します。' if enabled else '停止しました。'
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
            self.pause('P-STATIONの20円スロット以外への移動を止めました。'
                       '対象店の画面を確認してから再開してください。自動の再取得は行いません。')
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

    def pause(self, message=None):
        self.configure(False)
        if message:
            with self._state_lock:
                self._status = str(message)[:500]
        return self.state()

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
                raise ValueError('取り込みの設定が変わったため停止しました。')
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
        if not self._db_path.is_file():
            return None
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
        skipped = 0
        for model, m in self._models.items():
            count = m.get('count')
            if model in self._done or type(count) is not int or count < 1:
                continue
            name = suggestions(m['name'], catalog)['automatic'] or m['name']
            if len(racks.get(model, set()) | by_name.get(name, set())) >= count:
                self._done.add(model)
                self._kept += count
                skipped += 1
        if skipped:
            self._log.write('machines_skipped', day=self._day, skipped=skipped)
            left = sum(1 for key in self._models if key not in self._done)
            self._status = f'保存済みの{skipped}機種は開かずに飛ばしました。残り{left}機種を取り込みます。'
        return None

    def _skip_complete_days(self):
        """機種一覧の台数（[31] など）の合計だけ、その日の台が保存済みなら、機種ページを開かずにその日を飛ばす
        （2026-11-07 利用者「この改善は導入してね」。11/4・11/5 は全台保存済みなのに約50機種の表を開いていた）。
        台数の読めない機種が1つでもあれば飛ばさない（今までどおり機種ごとに確かめる）。全部飛ばせたら完了。"""
        while True:
            counts = [m.get('count') for m in self._models.values()]
            known = [c for c in counts if type(c) is int and c >= 1]
            total, saved = sum(known), len(self._saved_racks())
            # 飛ばすかどうかの数（機種数・台数の合計・台数の読めない機種・保存済み）を残す。名前・URL・会員情報は残さない。
            self._log.write('day_check', day=self._day, machines=len(counts), unknown_counts=len(counts) - len(known),
                            total=total, saved=saved)
            if not counts or len(known) != len(counts):
                return None
            if saved < total:
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
            self._queue = []
            self._until = None
            if left:
                self._status = (f'{finished}まで完了しました。機種一覧のページが分からないため、残りの{left}日は'
                                '取り込んでいません。機種一覧を開いてから、残りの日を選んで再開してください。')
            elif len(self._finished_days) > 1:
                self._status = '範囲の取り込みが完了しました。' + '、'.join(self._finished_days)
            else:
                self._status = f'指定日の取り込みが完了しました。追加{self._added}台、既存を保持{self._kept}台、グラフ不明{self._unknown}台。'
            # 残りの日が分からず止まったとき（left）は、続きを選べるよう窓を閉じない。
            if automatic and not left:
                self._completed = self._status
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
            result = self._capture(payload, epoch)
            if result.get('action'):
                with self._state_lock:
                    self._pending_navigation = True
            self._pace.pause('次のページを待ちます。')
            result['state'] = self.state()
            return result
        except Exception as error:
            with self._state_lock:
                self._enabled = False
                self._pace.configure(False, 15)
                self._status = str(error)
            # 元資料・URL・会員情報をログに出さない。
            self._log.write('capture_stopped', error_type=type(error).__name__)
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
            auto_backup(store, self._folder / 'pscube-viewer.json')
        finally:
            store.close()
        self._done.add(model)
        self._added += summary['added']
        self._kept += summary['kept_local']
        unknown = sum(r['graph'] is None for r in backup['records'])
        self._unknown += unknown
        self._status = f'{name}：追加{summary["added"]}台、既存を保持{summary["kept_local"]}台、グラフ不明{unknown}台。'
        self._job = None
        self._check(epoch)
        return self._next(index_url)
