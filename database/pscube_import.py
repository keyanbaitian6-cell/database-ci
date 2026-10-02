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
import unicodedata
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from auto_capture import AutoCapture
from pscube_connection import BrowserConnection, install_webview2_handlers, present_connection_failure, retry_page, stop_navigation

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
PROBE = PACKAGE_ROOT / 'database_android' / 'assets' / 'pscube_auto_probe.js'

SCROLL_SCRIPT = r'''(async () => {
  const findList = () => document.querySelector('#ulKI') || document.querySelector('li[id^="li-"]')?.parentElement;
  const target = typeof expectedCount === 'number' ? expectedCount : null;
  let stable = 0, old = -1;
  // 台数が一時的に止まっても、既知の設置台数に届くまでは待つ（最大24.5秒）。
  for (let i = 0; i < 70; i++) {
    const list = findList();
    if (!list) return;
    list.lastElementChild?.scrollIntoView({block:'end'});
    // 続きの台はページの一番下まで来たときに読み込まれる（最後の台が見えるだけでは来ない）。
    // Android版と同じく一番下まで移動する（2026-10-02、表示6台・設置7台で止まった件）。
    window.scrollTo(0, document.documentElement.scrollHeight);
    await new Promise(resolve => setTimeout(resolve, 350));
    // The site can replace the list when another batch arrives.
    const count = target === null ? (findList()?.children.length ?? -1)
      : document.querySelectorAll('li[id^="li-"]').length;
    stable = count === old ? stable + 1 : 0; old = count;
    if (stable >= 6 && (target === null || count >= target)) return;
  }
})()'''


# 「サイトの記録を消してやり直す」：表示中のP’s CUBEのページに残る保存データを消す（Cookieは
# pywebview の clear_cookies で別に消す）。取り込んだ記録（pscube.sqlite3）には触れない。
RESET_SITE_SCRIPT = r'''(async () => {
  try { localStorage.clear(); } catch (_) {}
  try { sessionStorage.clear(); } catch (_) {}
  try { for (const db of (await indexedDB.databases?.()) || []) if (db.name) indexedDB.deleteDatabase(db.name); } catch (_) {}
  try { for (const key of await caches.keys()) await caches.delete(key); } catch (_) {}
  return true;
})()'''
BLOCKED_MESSAGE = ('サイトがデータを表示しなくなりました（止められた可能性）。自動取り込みを止めました。'
                   '時間を空けてから、Cookieを消さずに「もう一度開く」を試してください。')
RESET_DONE_MESSAGE = ('サイトのCookie・保存データを消しました（取り込んだ記録はそのまま）。最初のページを開き直します。'
                      '人間確認・同意が出たら手で操作してください。')


def reset_site(window, pilot, saving):
    """サイトの記録（Cookie・保存データ）を消して最初のページを開き直す。

    同じスマホのChromeでは開けるのにアプリだけデータが出ない＝回線ではなく、この窓に残る
    Cookie等で止められていると考えられたため（2026-10-02、利用者の報告）。自動取り込みはOFFにする。
    """
    if saving():
        raise ValueError('保存中です。保存が終わってから押してください。')
    pilot.configure(False, pilot.state()['seconds'])
    if not stop_navigation(window):
        pilot._eval('window.stop && window.stop()')
    pilot._eval(RESET_SITE_SCRIPT)
    window.clear_cookies()
    with pilot._lock:
        pilot.missing.clear()
        pilot.done.clear()
        pilot.failures.clear()
        pilot.auto.pause(RESET_DONE_MESSAGE)
    window.load_url(ROOT_URL)
    return RESET_DONE_MESSAGE


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


# 沖ドキ（表記は「沖ドキ」「オキドキ」、半角の「沖ﾄﾞｷ」も）は取り込みの対象外。メルヘンと同じ約束
# （利用者の指定、2026-09-29。P’s CUBEへの反映は2026-10-01）。回る対象にせず、表・グラフも保存しない。
EXCLUDED_MACHINE_WORDS = ('沖ドキ', 'オキドキ')


def is_excluded_machine(name) -> bool:
    text = unicodedata.normalize('NFKC', str(name or ''))
    return any(word in text for word in EXCLUDED_MACHINE_WORDS)


def no_hits(r: dict) -> bool:
    """当たりが1回もない台（BB・RB・AT/ARTがすべて0、0回転を含む）。全台一覧の数値は保存するが、
    台別7日分（グラフ）は取りに行かない（メルヘンv12の「大当たり0回はグラフを取らない」を、AT/ARTも
    含めて引き継ぐ。利用者の指定、2026-10-01）。一覧を取り直して当たりが付けば、また取る対象に戻る。"""
    return r['bb'] + r['rb'] + r['at_art'] == 0


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
    if r.get('observed_at') is not None:
        try:
            datetime.fromisoformat(r['observed_at'])
        except (TypeError, ValueError) as exc:
            raise ValueError('更新時刻が不正です。') from exc


def _merge(old: dict | None, fresh: dict) -> dict:
    if old is None:
        return fresh
    same = all(old[k] == fresh[k] for k in ('bb', 'rb', 'at_art', 'games', 'my'))
    old_time = old.get('observed_at') or ''
    fresh_time = fresh.get('observed_at') or ''
    # 表示文字列の大小は時差つき時刻の新旧と一致しない。Android・Webと同じく瞬間で比べる。
    older = (datetime.fromisoformat(fresh_time).timestamp() < datetime.fromisoformat(old_time).timestamp()
             if old_time and fresh_time else fresh['games'] < old['games'])
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


def is_pscube_backup(path) -> bool:
    """P’s CUBEのバックアップ（format が pscube-viewer）か。先頭だけ読む（メルヘンの全期間は大きいため）。"""
    try:
        with open(path, 'rb') as f:
            head = f.read(512).decode('utf-8', errors='ignore')
    except OSError:
        return False
    return re.search(r'"format"\s*:\s*"pscube-viewer"', head) is not None


def backup_file_name(now: datetime | None = None, source: str = 'pc') -> str:
    """手で書き出すバックアップの名前（例 pscube-backup-pc-20261002-001500.json）。メルヘンと重ならない。"""
    return f'pscube-backup-{source}-{(now or datetime.now()):%Y%m%d-%H%M%S}.json'


def write_backup(store: 'PscubeStore', path) -> Path:
    """全期間のバックアップ（復元に使える形）を [path] に書く。"""
    return _write_json(Path(path), store.export_payload('backup'))


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


def installation_count(db_path, current_url):
    """表示中の全台一覧の設置台数を読み取り専用で取得。別機種・貸玉の台数は使わない。"""
    current = site_url(current_url)
    if not current.path.endswith('nc-v05-011.php') or not Path(db_path).is_file():
        return None
    identity = (current.path, parse_qs(current.query))
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        try:
            machines = db.execute('SELECT payload FROM machines').fetchall()
        except sqlite3.OperationalError as error:
            if 'no such table' in str(error):
                return None
            raise
        counts = set()
        for row in machines:
            machine = json.loads(row[0])
            stored = site_url(machine['url'])
            if (stored.path, parse_qs(stored.query)) == identity:
                count = machine.get('expected_count')
                if type(count) is int and 1 <= count <= 5000:
                    counts.add(count)
        return counts.pop() if len(counts) == 1 else None


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
        if is_index:
            data['machines'] = [m for m in data['machines'] if not is_excluded_machine(m['machine'])]
        elif data['machines'] and is_excluded_machine(data['machines'][0]['machine']):
            raise ValueError(f'{data["machines"][0]["machine"]}は取り込みの対象外です（沖ドキ）。保存しませんでした。')
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
        machines = [m for m in machines if not is_excluded_machine(m['machine'])]
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
                pending += [r['detail_url'] for r in rows if _record_key(r) not in captured and not no_hits(r)]
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

    def days(self) -> list[str]:
        """記録がある営業日（新しい順）。PC本体の「結果を見る」の日付の選択肢。"""
        return sorted({json.loads(row[0])['day'] for row in self.db.execute('SELECT payload FROM records')}, reverse=True)

    def machines_for(self, day: str) -> list[str]:
        """[day] に記録がある機種（沖ドキは除く）。PC本体の「結果を見る」の機種の選択肢。"""
        names = set()
        for row in self.db.execute('SELECT payload FROM records'):
            record = json.loads(row[0])
            if record['day'] == day and not is_excluded_machine(record['machine']):
                names.add(record['machine'])
        return sorted(names)

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


class AutoPilot:
    """P’s CUBEの自動取り込みの判断（仕様：PSCUBE_AUTO_CAPTURE.md）。

    メルヘンの `AutoCapture`（ON/OFF・間隔0.1〜4.5秒・起動時OFF）を時間の管理に使い、
    窓への働きかけは渡された `evaluate`（pywebviewの evaluate_js）だけで行う。サイトの
    ボタン・人間確認・同意には触れない：表示中のページを読む判定（pscube_auto_probe.js）が
    ready のときだけ、手動の「未取得を取り込む」と同じ処理を始める。
    """
    MAX_FAILURES = 3
    # P’s CUBEの間隔（秒）。サイトに止められないよう、メルヘン（0.1〜4.5秒）より長くする。
    MIN_SECONDS, MAX_SECONDS, DEFAULT_SECONDS = 5, 60, 7.1
    # 対象のページなのにデータが出ない（人間確認の画面でもない）状態が、この回数・秒数続いたら
    # 止められたとみなして自動取り込みをOFFにする（放置しても叩き続けない。利用者の選択、2026-10-01）。
    BLOCK_CHECKS, BLOCK_SECONDS = 5, 60
    # ページへの問い合わせの時間制限（秒）。pywebview の evaluate_js は返事が来るまで待ち続け、
    # ページの読み込み中は読み込みが終わるまで待つ（2026-10-02 実測）。サイトの返事が遅い・来ないと
    # 自動取り込みが止まっていたため、返事が無ければあきらめて次の機会にやり直す。
    EVAL_TIMEOUT = 10
    # 取り込み（全台の表示→読み取り→保存）がこの秒数たっても終わらなければ、印を外してやり直す
    # （ページ内の処理が途中で消えた場合に「取り込み中」のまま進まなくなるのを防ぐ）。
    PENDING_TIMEOUT = 90

    def __init__(self, evaluate, probe_script, saving=lambda: False, auto=None, eval_timeout=None):
        self.evaluate = evaluate
        self.probe_script = probe_script
        self.saving = saving
        self.auto = auto or AutoCapture(minimum=self.MIN_SECONDS, maximum=self.MAX_SECONDS,
                                        default=self.DEFAULT_SECONDS)
        self.clock = getattr(self.auto, '_clock', time.monotonic)
        self.missing = []
        self.done = set()
        self.failures = {}
        self.pending = None
        self.pending_since = None
        self.loading_page = False
        self.connection_error = None
        self.eval_timeout = self.EVAL_TIMEOUT if eval_timeout is None else eval_timeout
        self._lock = threading.RLock()

    def _eval(self, script):
        """時間制限つきの問い合わせ。返事が無い・失敗したときは None（呼んだ側は次の機会にやり直す）。"""
        box = {}

        def run():
            try:
                box['value'] = self.evaluate(script)
            except Exception as error:  # noqa: BLE001 - a failed query is treated as no answer
                box['error'] = error

        worker = threading.Thread(target=run, name='pscube-eval', daemon=True)
        worker.start()
        worker.join(self.eval_timeout)
        if worker.is_alive() or 'error' in box:
            return None
        return box.get('value')

    def state(self):
        return self.auto.state()

    def render(self):
        self._eval('window.__pscubeRenderAuto && window.__pscubeRenderAuto(' +
                   json.dumps(self.auto.state(), ensure_ascii=True) + ')')

    def configure(self, enabled, seconds):
        with self._lock:
            if enabled and self.connection_error:
                self.auto.pause(self.connection_error)
                return self.auto.state()
            state = self.auto.configure(enabled, seconds)
            if enabled:
                self.failures.clear()
                self.done.clear()
        self.render()
        return self.auto.state()

    def connection_failed(self, message):
        """Native WebView2 callback: no JS/UI wait here."""
        with self._lock:
            self.connection_error = message
            self.auto.configure(False, self.auto.state()['seconds'])
            self.auto.pause(message)

    def connection_started(self):
        with self._lock:
            self.connection_error = None
            self.loading_page = True

    def loading(self):
        """ページの読み込みが始まった：読み込みが終わるまで問い合わせない（問い合わせると待たされる）。"""
        with self._lock:
            self.loading_page = True

    def loaded(self):
        """新しいページ：間隔ぶん待ってから判定する。途中で消えた取り込み（ページ移動）は待たない。"""
        with self._lock:
            self.loading_page = False
            if self.pending is not None and not self.saving():
                self.pending = None
                self.pending_since = None
            if self.connection_error:
                self.auto.pause(self.connection_error)
            else:
                self.auto.loaded()
        self.render()

    def tick(self):
        with self._lock:
            if self.loading_page or self.connection_error:
                return
            now = self.clock()
            if (self.pending is not None and self.pending_since is not None and not self.saving()
                    and now - self.pending_since >= self.PENDING_TIMEOUT):
                signature, self.pending, self.pending_since = self.pending, None, None
                self.failures[signature] = self.failures.get(signature, 0) + 1
                self.auto.pause(f'ON・取り込みが{self.PENDING_TIMEOUT}秒たっても終わらないため、やり直します'
                                f'（{self.failures[signature]}回目）')
            token = self.auto.due(busy=self.pending is not None or self.saving())
            if token is None:
                return
        # 問い合わせの間は鍵を持たない（保存完了の処理などを待たせない）。
        raw = self._eval(self.probe_script)
        with self._lock:
            if self.loading_page or self.connection_error:
                return
            try:
                probe = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except ValueError:
                probe = {}
            if not isinstance(probe, dict):
                probe = {}
            now = self.clock()
            if probe.get('missing') and not probe.get('challenge'):
                self.missing.append(now)
                if len(self.missing) >= self.BLOCK_CHECKS and now - self.missing[0] >= self.BLOCK_SECONDS:
                    self.missing.clear()
                    self.auto.configure(False, self.auto.state()['seconds'])
                    self.auto.pause(BLOCKED_MESSAGE)
                    self.render()
                    return
            else:
                self.missing.clear()
            if probe.get('busy'):
                self.auto.pause('ON・保存処理中・完了待ち', token)
            elif not probe.get('ready'):
                self.auto.pause('ON・待機：' + str(probe.get('reason') or 'ページの準備待ち'), token)
            elif probe.get('signature') in self.done:
                self.auto.pause('ON・次のページ待ち（同じページは重複保存しません）', token)
            elif self.failures.get(probe.get('signature'), 0) >= self.MAX_FAILURES:
                self.auto.pause('ON・同じページで3回失敗したため待機中（内容を確かめて手動で取り込むか、OFF→ONで再開）', token)
            else:
                signature = probe['signature']

                def start():
                    if self._eval('window.__pscubeStartCapture ? window.__pscubeStartCapture() : false') is True:
                        self.pending = signature
                        self.pending_since = self.clock()
                        return True
                    return False

                if self.auto.run_current(token, start):
                    self.auto.pause('ON・取り込み中（' + str(probe.get('kind') or 'ページ') + '）', token)
        self.render()

    def finished(self, result=None, error=None):
        """保存の結果（手動の取り込みでも呼ばれる）。自動で始めた取り込みだけを数える。"""
        with self._lock:
            signature, self.pending, self.pending_since = self.pending, None, None
            enabled = self.auto.state()['enabled']
            if error is not None:
                if signature is not None:
                    self.failures[signature] = self.failures.get(signature, 0) + 1
                    if enabled:
                        self.auto.pause(f'ON・保存できませんでした（{self.failures[signature]}回目）：{error}')
            elif result is not None:
                if signature is not None:
                    self.done.add(signature)
                    self.failures.pop(signature, None)
                if enabled and not result.get('next_url'):
                    self.auto.configure(False, self.auto.state()['seconds'])
                    self.auto.pause('すべて取り込みました（自動取り込みを停止しました）')
                elif enabled:
                    self.auto.pause(f'ON・{result.get("kind", "")}を保存・残り{result.get("remaining", "?")}件・次のページへ')
        self.render()


def overlay_script(capture_script, index_url):
    """取り込み画面の右下のカード（手動の取り込み・自動取り込みのON/OFF・間隔・状態）。"""
    return r'''
    (() => {
      if (document.getElementById('database-pscube-card')) return;
      const card = document.createElement('div');
      card.id = 'database-pscube-card';
      Object.assign(card.style, {position:'fixed',bottom:'14px',right:'14px',zIndex:'2147483647',width:'250px',
        maxHeight:'calc(100vh - 50px)',overflowY:'auto',background:'white',border:'1px solid #c9d2df',borderRadius:'12px',
        padding:'10px',boxShadow:'0 4px 18px rgba(0,0,0,.18)',fontFamily:'sans-serif',display:'grid',gap:'8px'});
      const button = document.createElement('button');
      button.id = 'database-pscube-capture';
      const indexUrl = INDEX_URL;
      const isRoot = location.pathname.endsWith('/c740601/');
      button.textContent = isRoot ? 'スロット機種一覧へ' : '未取得を取り込む';
      Object.assign(button.style, {background:'#304d6e',color:'white',padding:'12px',border:'0',borderRadius:'8px',fontSize:'15px',cursor:'pointer'});
      const auto = document.createElement('button');
      auto.id = 'database-pscube-auto';
      auto.type = 'button';
      Object.assign(auto.style, {color:'white',padding:'10px',border:'2px solid #b8c5d8',borderRadius:'6px',fontSize:'14px',fontWeight:'bold',cursor:'pointer',background:'#526078'});
      auto.textContent = '自動取り込み：OFF（押すと開始）';
      const label = document.createElement('label');
      label.style.cssText = 'font-size:12px;display:block;color:#33445a';
      const seconds = document.createElement('input');
      seconds.id = 'database-pscube-interval';
      seconds.type = 'range'; seconds.min = '5'; seconds.max = '60'; seconds.step = '0.1'; seconds.value = '7.1';
      seconds.style.width = '100%';
      const value = document.createElement('span');
      value.textContent = '間隔：7.1秒';
      label.append(value, seconds);
      const status = document.createElement('div');
      status.id = 'database-pscube-auto-status';
      status.style.cssText = 'font-size:11px;color:#33445a;white-space:normal;word-break:break-word';
      status.textContent = '人間確認・同意の画面ではONのまま待ちます。確認は手動で操作してください。';
      const reset = document.createElement('button');
      const retry = document.createElement('button');
      retry.id = 'database-pscube-retry';
      retry.type = 'button';
      retry.textContent = 'もう一度開く（Cookie・記録は保持）';
      Object.assign(retry.style, {background:'white',color:'#33445a',padding:'6px',border:'1px solid #b8c5d8',borderRadius:'6px',fontSize:'12px',cursor:'pointer'});
      retry.onclick = async () => {
        if (window.__pscubeBusy) { status.textContent = '保存中です。保存が終わってから押してください。'; return; }
        retry.disabled = true;
        try { await window.pywebview.api.retry_page(); }
        catch (_) { retry.disabled = false; status.textContent = '開き直せませんでした。通信状態を確認してください。'; }
      };
      reset.id = 'database-pscube-reset';
      reset.type = 'button';
      reset.textContent = 'サイトの記録を消してやり直す';
      Object.assign(reset.style, {background:'white',color:'#33445a',padding:'6px',border:'1px solid #b8c5d8',borderRadius:'6px',fontSize:'12px',cursor:'pointer'});
      reset.onclick = async () => {
        if (window.__pscubeBusy) { status.textContent = '保存中です。保存が終わってから押してください。'; return; }
        if (!confirm('この画面に残っているCookie・保存データを消して、P’s CUBEの最初のページを開き直します。\n取り込んだ記録は消えません。自動取り込みはOFFになります。\nDNSエラーやHTTP403が直るとは限りません。人間確認・同意が出たら手で操作してください。')) return;
        reset.disabled = true;
        status.textContent = '消しています…';
        try {
          status.textContent = await window.pywebview.api.reset_site();
        } catch (error) {
          reset.disabled = false;
          status.textContent = '消せませんでした：' + String(error?.message || error);
        }
      };
      card.append(button, auto, label, status, retry, reset);
      const identity = raw => {
        const u = new URL(raw);
        if (!u.pathname.endsWith('nc-v06-001.php')) u.hash = '';
        return u.href;
      };
      let capturedUrl = null, autoEnabled = false, autoChanging = false, revision = -1;
      const idle = text => { button.textContent = text; button.disabled = autoEnabled; window.__pscubeBusy = false; };
      window.__pscubeBusy = false;
      window.pscubeCaptureFailed = error => { idle(String(error)); };
      window.pscubeCaptureComplete = result => {
        if (!capturedUrl || identity(location.href) !== identity(capturedUrl)) return;
        idle(`${result.kind}を保存 · 残り${result.remaining} · ${result.backup || ''}`);
        capturedUrl = null;
        if (result.next_url) location.href = result.next_url;
      };
      const run = async () => {
        window.__pscubeBusy = true;
        button.disabled = true; button.textContent = '読み込み中…';
        try {
          const before = location.href;
          const expectedCount = location.pathname.endsWith('nc-v05-011.php')
            ? await window.pywebview.api.get_installation_count() : null;
          if (identity(location.href) !== identity(before)) throw new Error('読み取り中にページが切り替わりました。');
          await SCROLL_SCRIPT;
          if (identity(location.href) !== identity(before)) throw new Error('読み取り中にページが切り替わりました。');
          capturedUrl = location.href;
          const payload = CAPTURE_SCRIPT;
          const result = await window.pywebview.api.submit_page(payload);
          window.pscubeCaptureComplete(result);
        } catch (error) {
          const message = String(error?.message || error);
          idle(message);
          try { await window.pywebview.api.capture_failed(message); } catch (_) {}
        }
      };
      // 自動取り込み（Python側のタイマー）から呼ぶ。取り込み中・最初のページでは始めない。
      window.__pscubeStartCapture = () => {
        if (isRoot || window.__pscubeBusy) return false;
        run();
        return true;
      };
      button.onclick = () => {
        if (isRoot) { location.href = indexUrl; return; }
        if (!window.__pscubeBusy && !autoEnabled) run();
      };
      window.__pscubeRenderAuto = state => {
        if (state.revision < revision) return;
        revision = state.revision;
        autoEnabled = !!state.enabled;
        auto.textContent = autoEnabled ? '自動取り込み：ON（押すと停止）' : '自動取り込み：OFF（押すと開始）';
        auto.style.background = autoEnabled ? '#087d59' : '#526078';
        auto.setAttribute('aria-pressed', String(autoEnabled));
        auto.disabled = autoChanging;
        seconds.disabled = autoEnabled || autoChanging;
        seconds.value = String(state.seconds);
        value.textContent = '間隔：' + Number(state.seconds).toFixed(1) + '秒';
        status.textContent = state.message;
        if (!window.__pscubeBusy) button.disabled = autoEnabled && !isRoot;
        button.style.opacity = button.disabled ? '.5' : '1';
      };
      seconds.oninput = () => { value.textContent = '間隔：' + Number(seconds.value).toFixed(1) + '秒'; };
      auto.onclick = async () => {
        if (autoChanging) return;
        autoChanging = true; auto.disabled = true;
        try {
          const state = await window.pywebview.api.set_auto_capture(!autoEnabled, Number(seconds.value));
          autoChanging = false;
          window.__pscubeRenderAuto(state);
        } catch (error) {
          autoChanging = false; auto.disabled = false;
          status.textContent = '自動取り込みを切り替えられませんでした：' + String(error?.message || error);
        }
      };
      document.body.append(card);
    })();
    '''.replace('SCROLL_SCRIPT', SCROLL_SCRIPT).replace('CAPTURE_SCRIPT', capture_script).replace('INDEX_URL', json.dumps(index_url))


def run_session(db_path, export_path):
    import webview

    script = CAPTURE.read_text(encoding='utf-8')
    probe = PROBE.read_text(encoding='utf-8')
    connection = BrowserConnection(ROOT_URL)

    class Bridge:
        def __init__(self):
            self._window = None
            self._capture_lock = threading.Lock()
            self.pilot = None

        def get_installation_count(self):
            return installation_count(db_path, self._window.get_current_url())

        def submit_page(self, raw):
            with self._capture_lock:
                try:
                    result = self._submit_page(raw)
                except Exception as error:
                    self._notify('window.pscubeCaptureFailed?.(' + json.dumps(str(error), ensure_ascii=True) + ')')
                    self.pilot.finished(error=str(error))
                    raise
                # The site's scrolling changes location.hash. WebView2 may
                # recreate pywebview's promise callbacks on that navigation,
                # so deliver completion to our own stable DOM handler too.
                self.pilot.finished(result=result)
                self._notify('window.pscubeCaptureComplete?.(' + json.dumps(result, ensure_ascii=True) + ')')
                return result

        def _notify(self, script):
            # 待たずに送る（ページが移っている途中だと evaluate_js が待たされ、保存の完了が遅れるため）。
            threading.Thread(target=lambda: self.pilot._eval(script), name='pscube-notify', daemon=True).start()

        def capture_failed(self, message):
            # 読み取りの途中（保存の前）で失敗したとき。保存中の失敗は submit_page が数える。
            if not self._capture_lock.locked():
                self.pilot.finished(error=str(message)[:300])
            return True

        def set_auto_capture(self, enabled, seconds):
            return self.pilot.configure(enabled, seconds)

        def reset_site(self):
            if not self._capture_lock.acquire(blocking=False):
                raise ValueError('保存中です。保存が終わってから押してください。')
            try:
                return reset_site(self._window, self.pilot, saving=lambda: False)
            finally:
                self._capture_lock.release()

        def _submit_page(self, raw):
            if connection.failure:
                raise ValueError(connection.failure['message'])
            current = self._window.get_current_url()
            db = PscubeStore(db_path)
            try:
                result = db.import_page(raw, current)
                result['backup'] = auto_backup(db, export_path)
                result['source_url'] = current
                return result
            finally:
                db.close()

        def retry_page(self):
            if not self._capture_lock.acquire(blocking=False):
                raise ValueError('保存中です。保存が終わってから押してください。')
            try:
                return retry_page(self._window, self.pilot, connection, saving=lambda: False)
            finally:
                self._capture_lock.release()

    bridge = Bridge()
    window = webview.create_window('P’s CUBE 取り込み', ROOT_URL, width=1050, height=780, js_api=bridge)
    bridge._window = window
    bridge.pilot = AutoPilot(window.evaluate_js, probe, saving=bridge._capture_lock.locked)
    overlay = overlay_script(script, ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2')
    stop = threading.Event()
    native_handlers = []

    def failed():
        with connection.lock:
            if not connection.failure:
                return
            message = connection.failure['message']
            revision = connection.revision
        def show():
            with connection.lock:
                if stop.is_set() or revision != connection.revision or not connection.failure:
                    return
                if connection.showing_error:
                    return
            bridge.pilot.connection_failed(message)
            if not present_connection_failure(window, connection, revision):
                bridge.pilot.render()

        threading.Thread(target=show, name='pscube-connection-error', daemon=True).start()

    def install_native():
        native_handlers.extend(install_webview2_handlers(
            window, connection, failed))

    def install_overlay():
        try:
            site_url(window.get_current_url())
            window.evaluate_js(overlay)
        except Exception:
            pass
        if not connection.failure and not connection.showing_error:
            bridge.pilot.connection_started()
        bridge.pilot.loaded()

    def auto_loop():
        # 窓を最小化してもJavaScriptのタイマーのように遅れないよう、Python側で数える。
        while not stop.wait(0.1):
            try:
                bridge.pilot.tick()
            except Exception:
                pass

    def closed():
        stop.set()

    window.events.before_load += bridge.pilot.loading
    if hasattr(window.events, 'before_show'):
        window.events.before_show += install_native
    window.events.loaded += install_overlay
    window.events.closed += closed
    threading.Thread(target=auto_loop, name='pscube-auto', daemon=True).start()
    # pywebview の初期設定はシークレットモード（起動のたびにCookieを消し、別サイトの
    # Cookieも拒否する）。そのため人間確認（hCaptcha）の確認済みが残らず、何度も確認が
    # 出る。Safariと同じく、data の中の専用の場所にCookieを残す（2026-10-01、Androidで
    # 同じ原因を直して人間確認が出なくなったことを受けて）。
    webview.start(gui='edgechromium', private_mode=False, storage_path=str(webview_storage(db_path)))


def webview_storage(db_path) -> Path:
    """P’s CUBE取り込み画面のCookie・サイトのデータを残す場所（記録と同じ data の中、Gitには入らない）。"""
    folder = Path(db_path).resolve().parent / 'pscube-webview'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


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
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-local':
        from runtime_smoke import run
        run(sys.modules[__name__], 'pscube', sys.argv[2])
    else:
        run_session(sys.argv[1] if len(sys.argv) > 1 else root / 'data' / 'pscube.sqlite3',
                    sys.argv[2] if len(sys.argv) > 2 else root / 'data' / 'pscube-viewer.json')
