"""P's CUBE browser capture with its own SQLite records and viewer JSON export.

The usual Meruhen database is deliberately separate: its kind_code, stores,
hold score and backup schema have different meanings. Site authentication is
performed by the person in the embedded browser; this module reads rendered DOM.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# バックアップ・Drive同期（仕様：PSCUBE_SYNC.md）。メルヘンの database-backup-* とは名前を分ける。
AUTO_BACKUP_NAME = 'pscube-backup-auto.json'
VIEWER_DRIVE_NAME = 'pscube-viewer-drive.json'
SNAPSHOT_PATTERN = 'pscube-backup-????-??-??.json'
SNAPSHOT_KEEP_DAYS = 7
VIEWER_DAYS = 31
VIEWER_GRAPH_POINTS = 16
MAX_BACKUP_RECORDS = 200000
SHOP = 'c740601'
HOST = 'www.pscube.jp'
ROOT_URL = f'https://{HOST}/dedamajyoho-P-townDMMpachi/{SHOP}/'
FORMAT = 'pscube-viewer'
PACKAGE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
CAPTURE = PACKAGE_ROOT / 'database_android' / 'assets' / 'pscube_capture.js'

SCROLL_SCRIPT = r'''(async () => {
  const findList = () => document.querySelector('#ulKI') || document.querySelector('li[id^="li-"]')?.parentElement;
  let stable = 0, old = -1;
  for (let i = 0; i < 70 && stable < 6; i++) {
    const list = findList();
    if (!list) return;
    list.lastElementChild?.scrollIntoView({block:'end'});
    await new Promise(resolve => setTimeout(resolve, 350));
    // The site can replace the list when another batch arrives.
    const count = findList()?.children.length ?? -1;
    stable = count === old ? stable + 1 : 0; old = count;
  }
})()'''


def site_url(raw: str, suffix: str | None = None):
    if not isinstance(raw, str):
        raise ValueError('ページのURLがありません。')
    p = urlparse(raw)
    if p.scheme != 'https' or p.netloc != HOST or p.username or p.password:
        raise ValueError('対象外のサイトです。')
    if not p.path.startswith(f'/dedamajyoho-P-townDMMpachi/{SHOP}/'):
        raise ValueError('対象外の店舗です。')
    if suffix and not p.path.endswith(suffix):
        raise ValueError('ページの種類が一致しません。')
    return p


def compact_day(raw: str) -> str:
    if not re.fullmatch(r'\d{8}', raw or ''):
        raise ValueError('営業日がありません。')
    return datetime.strptime(raw, '%Y%m%d').date().isoformat()


def _key(*parts) -> str:
    return json.dumps(parts, ensure_ascii=False, separators=(',', ':'))


def _machine_key(m: dict) -> str:
    return _key(m['store'], m['rate'], m['machine'])


def _record_key(r: dict) -> str:
    return _key(r['store'], r['rate'], r['machine'], r['rack'], r['day'])


def _number(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'{name}の数値が不正です。')


def _validate_machine(m):
    if not isinstance(m, dict) or m.get('store') != SHOP or not re.fullmatch(r'\d+(?:\.\d+)?', str(m.get('rate', ''))):
        raise ValueError('店舗・貸玉を確認できません。')
    if not isinstance(m.get('machine'), str) or not m['machine'].strip():
        raise ValueError('機種名を確認できません。')
    u = site_url(m.get('url'), 'nc-v05-011.php')
    if parse_qs(u.query).get('bai') != [m['rate']] or parse_qs(u.query).get('cd_ps') not in (None, ['2']):
        raise ValueError('機種リンクの貸玉が一致しません。')
    count = m.get('expected_count')
    if count is not None and (type(count) is not int or not 1 <= count <= 5000):
        raise ValueError('設置台数が不正です。')
    if m.get('machine_type') not in (None, 'normal', 'other'):
        raise ValueError('機種タイプが不正です。')


def _validate_record(r):
    if not isinstance(r, dict):
        raise ValueError('台の形式が不正です。')
    if r.get('store') != SHOP or not isinstance(r.get('rate'), str) or not re.fullmatch(r'\d+(?:\.\d+)?', r['rate']):
        raise ValueError('店舗・貸玉を確認できません。')
    if not isinstance(r.get('machine'), str) or not r['machine'].strip() or len(r['machine']) > 200:
        raise ValueError('機種名を確認できません。')
    _number(r.get('rack'), '台番号')
    if r['rack'] < 1:
        raise ValueError('台番号が不正です。')
    try:
        if datetime.strptime(r.get('day', ''), '%Y-%m-%d').date().isoformat() != r['day']:
            raise ValueError
    except (TypeError, ValueError) as e:
        raise ValueError('営業日が不正です。') from e
    u = site_url(r.get('detail_url'), 'nc-v06-001.php')
    if parse_qs(u.query).get('cd_dai') != [str(r['rack'])] or u.fragment != r['day'].replace('-', ''):
        raise ValueError('台番号または日付とリンクが一致しません。')
    for name in ('bb', 'rb', 'at_art', 'games', 'my'):
        _number(r.get(name), name)
    g = r.get('graph')
    if g is not None:
        if not isinstance(g, dict) or g.get('kind') not in ('overview', 'daily') or type(g.get('zero_y')) not in (int, float) or not math.isfinite(g['zero_y']):
            raise ValueError('グラフの形式が不正です。')
        points = g.get('points')
        if not isinstance(points, list) or not 2 <= len(points) <= 50000:
            raise ValueError('グラフの座標が不正です。')
        for i, point in enumerate(points):
            if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e7 for v in point):
                raise ValueError('グラフの座標が不正です。')
            if i and point[0] < points[i - 1][0]:
                raise ValueError('グラフの順序が不正です。')


def _merge(old: dict | None, fresh: dict) -> dict:
    if old is None:
        return fresh
    same = all(old[k] == fresh[k] for k in ('bb', 'rb', 'at_art', 'games', 'my'))
    old_time = old.get('observed_at') or ''
    fresh_time = fresh.get('observed_at') or ''
    older = fresh_time < old_time if old_time and fresh_time else fresh['games'] < old['games']
    if older and not same:
        return old
    chosen = old if older else fresh
    other = fresh if older else old
    if same:
        graph = chosen.get('graph')
        if not graph or graph['kind'] != 'daily':
            second = other.get('graph')
            graph = second if second and second['kind'] == 'daily' else graph or second
        return {**chosen, 'graph': graph}
    return chosen


def thin_graph(graph: dict | None, limit: int = VIEWER_GRAPH_POINTS) -> dict | None:
    """閲覧用に点を減らす。最初・最後・最高点・最低点（採点に使う終点・維持の元）は必ず残す。"""
    if not graph or len(graph['points']) <= limit:
        return graph
    points = graph['points']
    required = {0, len(points) - 1, min(range(len(points)), key=lambda i: points[i][1]),
                max(range(len(points)), key=lambda i: points[i][1])}
    others = [i for i in range(len(points)) if i not in required]
    slots = limit - len(required)
    spread = {others[round(k * (len(others) - 1) / (slots - 1))] for k in range(slots)}
    chosen = sorted(required | spread)
    return {**graph, 'points': [points[i] for i in chosen]}


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _load_settings(data_dir) -> dict:
    try:
        loaded = json.loads((Path(data_dir) / 'settings.json').read_text(encoding='utf-8'))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def sync_folder(data_dir) -> Path | None:
    """メルヘンと同じ同期フォルダ（settings.json の sync_dir）。未設定・存在しなければ None。"""
    folder = _load_settings(data_dir).get('sync_dir')
    return Path(folder) if folder and Path(folder).is_dir() else None


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)
    return path


def auto_backup(store: 'PscubeStore', export_path, today: date | None = None) -> str:
    """保存のあとに呼ぶ。書き出しに失敗しても取り込みは止めない（例外を出さない）。

    ローカルの `pscube-viewer.json`、日付ごとの控え（7日分）、同期フォルダの
    `pscube-backup-auto.json` と `pscube-viewer-drive.json` を作る。戻り値は画面に出す状態。
    """
    try:
        data_dir = Path(export_path).parent
        folder = sync_folder(data_dir)
        today = today or date.today()
        full = store.export_payload('backup')
        local = _write_json(Path(export_path), full)
        snapshots = (folder or data_dir) / 'backups'
        snapshot = snapshots / f'pscube-backup-{today.isoformat()}.json'
        snapshots.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, snapshot)
        for old in snapshots.glob(SNAPSHOT_PATTERN):
            try:
                stamp = date.fromisoformat(old.stem[len('pscube-backup-'):])
            except ValueError:
                continue
            if (today - stamp).days > SNAPSHOT_KEEP_DAYS:
                old.unlink(missing_ok=True)
        if folder is None:
            return '同期フォルダ未設定（本体の「バックアップ・同期」で指定）'
        shutil.copyfile(local, folder / AUTO_BACKUP_NAME)
        light = _write_json(data_dir / VIEWER_DRIVE_NAME, store.export_payload('viewer'))
        shutil.copyfile(light, folder / VIEWER_DRIVE_NAME)
        return 'バックアップ済み'
    except (OSError, ValueError, sqlite3.Error):
        return 'バックアップに失敗（取り込みは保存済み）'


def latest_pscube_backup(folder) -> Path | None:
    """同期フォルダの最新のP’s CUBEバックアップ。自分の自動コピーと閲覧用の軽いファイルは除く。"""
    candidates = [p for p in Path(folder).glob('pscube-*.json') if p.name not in (AUTO_BACKUP_NAME, VIEWER_DRIVE_NAME)]
    for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get('format') == FORMAT and payload.get('kind') != 'viewer':
            return path
    return None


class PscubeStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute('CREATE TABLE IF NOT EXISTS machines (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS rack_captures (key TEXT PRIMARY KEY)')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.commit()

    def close(self):
        self.db.close()

    def _read(self, table, key):
        row = self.db.execute(f'SELECT payload FROM {table} WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _state(self, key):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def import_page(self, raw, current_url):
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict) or data.get('error'):
            raise ValueError(data.get('error', 'ページを読めませんでした。') if isinstance(data, dict) else 'ページの形式が不正です。')
        if data.get('format') != FORMAT or data.get('version') != 1 or not isinstance(data.get('machines'), list) or not isinstance(data.get('records'), list):
            raise ValueError('P’s CUBEの取り込み形式ではありません。')
        actual = site_url(current_url)
        reported = site_url(data.get('source_url'))
        if (actual.scheme, actual.netloc, actual.path, actual.query, actual.fragment) != (reported.scheme, reported.netloc, reported.path, reported.query, reported.fragment):
            raise ValueError('表示中のページと読み取り結果が違います。')
        if len(data['machines']) > 10000 or len(data['records']) > 5000:
            raise ValueError('ページの件数が多すぎます。')
        for m in data['machines']:
            _validate_machine(m)
        for r in data['records']:
            _validate_record(r)
        if len({_machine_key(m) for m in data['machines']}) != len(data['machines']) or len({_record_key(r) for r in data['records']}) != len(data['records']):
            raise ValueError('同じ機種・台が重複しています。')
        is_index = actual.path.endswith('nc-v03-001.php')
        is_table = actual.path.endswith('nc-v05-011.php')
        is_rack = actual.path.endswith('nc-v06-001.php')
        if not (is_index or is_table or is_rack):
            raise ValueError('機種一覧・台一覧・台別ページを開いてください。')
        if is_index and (data['records'] or not data['machines'] or parse_qs(actual.query).get('cd_ps') != ['2']):
            raise ValueError('スロット機種一覧を確認できません。')
        if is_table:
            if parse_qs(actual.query).get('cd_ps') not in (None, ['2']) or len(data['machines']) != 1 or not data['records']:
                raise ValueError('全台一覧を確認できません。')
            old = self._read('machines', _machine_key(data['machines'][0]))
            if not old or not old.get('expected_count'):
                raise ValueError('先に設置機種一覧を取り込んでください。')
            if len(data['records']) != old['expected_count']:
                raise ValueError(f'表示は{len(data["records"])}台、設置台数は{old["expected_count"]}台です。全台を表示してから取り込んでください。')
            if any(_machine_key(r) != _machine_key(old) for r in data['records']):
                raise ValueError('機種と台の情報が一致しません。')
        if is_rack and (len(data['machines']) != 1 or len(data['records']) != 7):
            raise ValueError('7日分の台別データが揃っていません。')
        day = data['records'][0]['day'] if data['records'] else self._state('last_day')
        if is_rack:
            day = compact_day(actual.fragment)
            current = next((r for r in data['records'] if r['day'] == day), None)
            if not current or self._read('records', _record_key(current)) is None:
                raise ValueError('先にこの台の全台一覧を取り込んでください。')
            if any(r['rack'] != current['rack'] or _machine_key(r) != _machine_key(current) for r in data['records']):
                raise ValueError('台別7日分の内容が一致しません。')
            if parse_qs(actual.query).get('cd_dai') != [str(current['rack'])] or _machine_key(data['machines'][0]) != _machine_key(current):
                raise ValueError('表示中の台番号・機種と一致しません。')
            expected = {(datetime.fromisoformat(day).date() - timedelta(days=i)).isoformat() for i in range(7)}
            if {r['day'] for r in data['records']} != expected:
                raise ValueError('連続した7日分の履歴ではありません。')
        if is_table and any(r['day'] != day for r in data['records']):
            raise ValueError('一覧内の日付が一致しません。')
        with self.db:
            for m in data['machines']:
                key = _machine_key(m)
                previous = self._read('machines', key)
                saved = {**m, 'expected_count': m.get('expected_count') or (previous or {}).get('expected_count'),
                         'machine_type': m.get('machine_type') or (previous or {}).get('machine_type')}
                self.db.execute('INSERT OR REPLACE INTO machines VALUES (?,?)', (key, json.dumps(saved, ensure_ascii=False)))
            for r in data['records']:
                key = _record_key(r)
                previous = self._read('records', key)
                saved = _merge(previous, r)
                if previous and any(previous[k] != saved[k] for k in ('bb', 'rb', 'at_art', 'games', 'my')):
                    self.db.execute('DELETE FROM rack_captures WHERE key=?', (key,))
                self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', (key, json.dumps(saved, ensure_ascii=False)))
            if day:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('last_day', day))
            if is_index:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                ('active_machine_keys', json.dumps([_machine_key(m) for m in data['machines']], ensure_ascii=False)))
            if is_rack:
                self.db.execute('INSERT OR IGNORE INTO rack_captures VALUES (?)', (_record_key(current),))
        if is_index:
            next_url, remaining = data['machines'][0]['url'], len(data['machines'])
        else:
            next_url, remaining = self.next_target(day)
        return {'saved': len(data['records']), 'day': day, 'next_url': next_url, 'remaining': remaining,
                'kind': '機種一覧' if is_index else '全台一覧' if is_table else '台別7日分'}

    def next_target(self, day=None):
        day = day or self._state('last_day')
        machines = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM machines ORDER BY rowid')]
        active = self._state('active_machine_keys')
        if active:
            by_key = {_machine_key(m): m for m in machines}
            machines = [by_key[key] for key in json.loads(active) if key in by_key]
        if not machines:
            return ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2', 0
        if not day:
            return machines[0]['url'], len(machines)
        pending = []
        all_rows = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM records')]
        captured = {row[0] for row in self.db.execute('SELECT key FROM rack_captures')}
        for machine in machines:
            rows = sorted((r for r in all_rows if _machine_key(r) == _machine_key(machine) and r['day'] == day), key=lambda r: r['rack'])
            if len(rows) != machine.get('expected_count'):
                pending.append(machine['url'])
            else:
                pending += [r['detail_url'] for r in rows if _record_key(r) not in captured]
        return (pending[0] if pending else None), len(pending)

    def export_payload(self, kind='backup', today: date | None = None) -> dict:
        """kind='backup'：全期間・グラフ全点・取り込み済みの印つき。'viewer'：閲覧ページ用の軽い版
        （直近31日・グラフ16点まで。復元には使えない）。"""
        machines = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM machines ORDER BY rowid')]
        records = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM records ORDER BY rowid')]
        data = {'format': FORMAT, 'version': 1, 'kind': kind, 'source': 'pc', 'exported_at': _now_text(),
                'machines': machines, 'records': records}
        if kind == 'viewer':
            latest = max((r['day'] for r in records), default=None)
            if latest:
                first = (date.fromisoformat(latest) - timedelta(days=VIEWER_DAYS - 1)).isoformat()
                data['records'] = [{**r, 'graph': thin_graph(r.get('graph'))} for r in records if r['day'] >= first]
        else:
            data['rack_captures'] = [row[0] for row in self.db.execute('SELECT key FROM rack_captures ORDER BY rowid')]
        return data

    def export_viewer(self, path):
        return _write_json(Path(path), self.export_payload('backup'))

    def import_backup(self, source) -> dict:
        """他の端末のバックアップ（PC・Android・ブラウザ）を統合する。消す操作はない。

        台ごとの統合は取り込みと同じ `_merge`（古い数値で新しい数値を上書きしない）。軽い閲覧用
        ファイル（kind='viewer'）は止める。形式が不正なら1件も保存しない。
        """
        data = json.loads(Path(source).read_text(encoding='utf-8-sig')) if isinstance(source, (str, Path)) else source
        if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != 1 \
                or not isinstance(data.get('machines'), list) or not isinstance(data.get('records'), list):
            raise ValueError('P’s CUBEのバックアップではありません。')
        if data.get('kind') == 'viewer':
            raise ValueError('閲覧用の軽いファイルはバックアップではないため、読み込めません。')
        if len(data['machines']) > 10000 or len(data['records']) > MAX_BACKUP_RECORDS:
            raise ValueError('バックアップの件数が多すぎます。')
        for m in data['machines']:
            _validate_machine(m)
        for r in data['records']:
            _validate_record(r)
        machine_keys = {_machine_key(m) for m in data['machines']}
        record_keys = [_record_key(r) for r in data['records']]
        if len(machine_keys) != len(data['machines']) or len(set(record_keys)) != len(record_keys):
            raise ValueError('同じ機種・台が重複しています。')
        if any(_machine_key(r) not in machine_keys for r in data['records']):
            raise ValueError('台に対応する機種情報がありません。')
        if 'rack_captures' in data:
            captures = data['rack_captures']
            if not isinstance(captures, list) or any(not isinstance(k, str) for k in captures) or not set(captures) <= set(record_keys):
                raise ValueError('取り込み済みの印が不正です。')
        else:
            # 印の無い古い書き出し：台別7日分のグラフがある日は取り込み済みとみなす。
            captures = [_record_key(r) for r in data['records'] if (r.get('graph') or {}).get('kind') == 'daily']
        wanted = set(captures)
        summary = {'added': 0, 'updated': 0, 'unchanged': 0, 'kept_local': 0, 'machines': len(data['machines'])}
        with self.db:
            for m in data['machines']:
                key = _machine_key(m)
                previous = self._read('machines', key) or {}
                saved = {**m, 'expected_count': m.get('expected_count') or previous.get('expected_count'),
                         'machine_type': previous.get('machine_type') or m.get('machine_type')}
                self.db.execute('INSERT OR REPLACE INTO machines VALUES (?,?)', (key, json.dumps(saved, ensure_ascii=False)))
            for r in data['records']:
                key = _record_key(r)
                previous = self._read('records', key)
                saved = _merge(previous, r)
                numbers = ('bb', 'rb', 'at_art', 'games', 'my')
                if previous is None:
                    summary['added'] += 1
                elif any(previous[k] != saved[k] for k in numbers):
                    summary['updated'] += 1
                    self.db.execute('DELETE FROM rack_captures WHERE key=?', (key,))
                elif saved != previous:
                    summary['updated'] += 1
                else:
                    summary['unchanged'] += 1
                if previous is not None and any(previous[k] != r[k] for k in numbers) and saved is previous:
                    summary['kept_local'] += 1
                self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', (key, json.dumps(saved, ensure_ascii=False)))
                if key in wanted and all(saved[k] == r[k] for k in numbers):
                    self.db.execute('INSERT OR IGNORE INTO rack_captures VALUES (?)', (key,))
            if data['records'] and not self._state('last_day'):
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('last_day', max(r['day'] for r in data['records'])))
        return summary


def run_session(db_path, export_path):
    import webview

    script = CAPTURE.read_text(encoding='utf-8')

    class Bridge:
        def __init__(self):
            self._window = None
            self._capture_lock = threading.Lock()

        def submit_page(self, raw):
            with self._capture_lock:
                try:
                    result = self._submit_page(raw)
                    # The site's scrolling changes location.hash. WebView2 may
                    # recreate pywebview's promise callbacks on that navigation,
                    # so deliver completion to our own stable DOM handler too.
                    self._window.evaluate_js('window.pscubeCaptureComplete?.(' + json.dumps(result, ensure_ascii=True) + ')')
                    return result
                except Exception as error:
                    self._window.evaluate_js('window.pscubeCaptureFailed?.(' + json.dumps(str(error), ensure_ascii=True) + ')')
                    raise

        def _submit_page(self, raw):
            current = self._window.get_current_url()
            db = PscubeStore(db_path)
            try:
                result = db.import_page(raw, current)
                result['backup'] = auto_backup(db, export_path)
                result['source_url'] = current
                return result
            finally:
                db.close()

    bridge = Bridge()
    window = webview.create_window('P’s CUBE 取り込み', ROOT_URL, width=1050, height=780, js_api=bridge)
    bridge._window = window
    overlay = r'''
    (() => {
      if (document.getElementById('database-pscube-capture')) return;
      const button = document.createElement('button');
      button.id = 'database-pscube-capture';
      const indexUrl = INDEX_URL;
      const isRoot = location.pathname.endsWith('/c740601/');
      button.textContent = isRoot ? 'スロット機種一覧へ' : '未取得を取り込む';
      Object.assign(button.style, {position:'fixed',bottom:'18px',right:'18px',zIndex:'2147483647',
        background:'#304d6e',color:'white',padding:'14px 18px',border:'0',borderRadius:'10px',fontSize:'16px'});
      const identity = raw => {
        const u = new URL(raw);
        if (!u.pathname.endsWith('nc-v06-001.php')) u.hash = '';
        return u.href;
      };
      let capturedUrl = null;
      window.pscubeCaptureFailed = error => {
        button.textContent = String(error); button.disabled = false;
      };
      window.pscubeCaptureComplete = result => {
        if (!capturedUrl || identity(location.href) !== identity(capturedUrl)) return;
        button.textContent = `${result.kind}を保存 · 残り${result.remaining} · ${result.backup || ''}`;
        button.disabled = false;
        capturedUrl = null;
        if (result.next_url) location.href = result.next_url;
      };
      button.onclick = async () => {
        if (isRoot) { location.href = indexUrl; return; }
        button.disabled = true; button.textContent = '読み込み中…';
        try {
          await SCROLL_SCRIPT;
          capturedUrl = location.href;
          const payload = CAPTURE_SCRIPT;
          const result = await window.pywebview.api.submit_page(payload);
          window.pscubeCaptureComplete(result);
        } catch (error) { button.textContent = String(error.message || error); button.disabled = false; }
      };
      document.body.append(button);
    })();
    '''.replace('SCROLL_SCRIPT', SCROLL_SCRIPT).replace('CAPTURE_SCRIPT', script).replace('INDEX_URL', json.dumps(ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2'))

    def install_overlay():
        try:
            site_url(window.get_current_url())
            window.evaluate_js(overlay)
        except Exception:
            pass

    window.events.loaded += install_overlay
    webview.start(gui='edgechromium')


def runtime_root():
    if getattr(sys, 'frozen', False):
        executable_dir = Path(sys.executable).resolve().parent
        for candidate in (executable_dir.parent, executable_dir.parent.parent, executable_dir):
            if (candidate / 'data').exists() or (candidate / 'app.py').exists():
                return candidate
        return executable_dir
    return Path(__file__).resolve().parent


if __name__ == '__main__':
    root = runtime_root()
    run_session(sys.argv[1] if len(sys.argv) > 1 else root / 'data' / 'pscube.sqlite3',
                sys.argv[2] if len(sys.argv) > 2 else root / 'data' / 'pscube-viewer.json')
