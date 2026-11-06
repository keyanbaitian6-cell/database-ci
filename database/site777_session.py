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
        self._pace = PscubeRandomCapture()
        self._enabled = False
        self._days = recent_business_days(self._now(), count=8)
        self._day = self._days[0]
        self._status = 'P-STATIONの20円スロットを開き、取り込む日付を確認してください。'
        self._models = {}
        self._done = set()
        self._index_pages = set()
        self._job = None
        self._added = 0
        self._kept = 0
        self._unknown = 0
        self._active_url = None

    def state(self):
        with self._state_lock:
            return {'enabled': self._enabled, 'epoch': self._epoch, 'day': self._day,
                    'days': self._days, 'status': self._status, 'added': self._added, 'kept': self._kept,
                    'ready': self._pace.due() is not None, 'unknown_graphs': self._unknown}

    def configure(self, enabled, day=None):
        if type(enabled) is not bool:
            raise ValueError('自動取り込みの設定が不正です。')
        if day is not None:
            from datetime import date
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                raise ValueError('取り込み日が不正です。')
        with self._state_lock:
            if day != self._day and day is not None:
                if self._work_lock.locked():
                    raise ValueError('読み取り処理中は日付を変えられません。停止して処理の完了を待ってください。')
                self._models.clear()
                self._done.clear()
                self._index_pages.clear()
                self._job = None
                self._added = self._kept = 0
                self._unknown = 0
            self._day = day or self._day
            self._enabled = enabled
            self._pace.configure(enabled, 15)
            self._epoch += 1
            self._status = '自動取り込みを開始します。' if enabled else '停止しました。'
        return self.state()

    def _loaded(self):
        self._pace.loaded()

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
        with closing(sqlite3.connect(self._db_path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            return {json.loads(r[0])['rack'] for r in db.execute(
                "SELECT payload FROM records WHERE json_extract(payload,'$.store')=? "
                "AND json_extract(payload,'$.rate')='20' AND json_extract(payload,'$.day')=?",
                (source.SHOP, self._day))}

    def _next(self, index_url=None):
        remaining = [m for key, m in self._models.items() if key not in self._done]
        if remaining:
            return {'action': {'type': 'listed', 'url': remaining[0]['url']}}
        if not self._models and index_url:
            return {'action': {'type': 'link', 'url': index_url}}
        with self._state_lock:
            self._enabled = False
            self._pace.configure(False, 15)
            self._status = f'指定日の取り込みが完了しました。追加{self._added}台、既存を保持{self._kept}台、グラフ不明{self._unknown}台。'
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
            return self._next()
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
        if kind != 'graphs' or not self._job:
            raise ValueError('先に同じ機種・日付の全台一覧を取り込んでください。')
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
