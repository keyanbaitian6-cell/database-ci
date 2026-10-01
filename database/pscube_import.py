"""P's CUBE browser capture with its own SQLite records and viewer JSON export.

The usual Meruhen database is deliberately separate: its kind_code, stores,
hold score and backup schema have different meanings. Site authentication is
performed by the person in the embedded browser; this module reads rendered DOM.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SHOP = 'c740601'
HOST = 'www.pscube.jp'
ROOT_URL = f'https://{HOST}/dedamajyoho-P-townDMMpachi/{SHOP}/'
FORMAT = 'pscube-viewer'
PACKAGE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
CAPTURE = PACKAGE_ROOT / 'database_android' / 'assets' / 'pscube_capture.js'


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
    if parse_qs(u.query).get('bai') != [m['rate']]:
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
        if not isinstance(g, dict) or g.get('kind') not in ('overview', 'daily') or not isinstance(g.get('zero_y'), (int, float)):
            raise ValueError('グラフの形式が不正です。')
        points = g.get('points')
        if not isinstance(points, list) or not 2 <= len(points) <= 50000:
            raise ValueError('グラフの座標が不正です。')
        for i, point in enumerate(points):
            if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) for v in point):
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
            if parse_qs(actual.query).get('cd_ps') != ['2'] or len(data['machines']) != 1 or not data['records']:
                raise ValueError('全台一覧を確認できません。')
            old = self._read('machines', _machine_key(data['machines'][0]))
            if not old or not old.get('expected_count'):
                raise ValueError('先に設置機種一覧を取り込んでください。')
            if len(data['records']) != old['expected_count']:
                raise ValueError(f'表示は{len(data["records"])}台、設置台数は{old["expected_count"]}台です。全台を表示してから取り込んでください。')
            if any(_machine_key(r) != _machine_key(old) for r in data['records']):
                raise ValueError('機種と台の情報が一致しません。')
        if is_rack and len(data['records']) != 7:
            raise ValueError('7日分の台別データが揃っていません。')
        day = data['records'][0]['day'] if data['records'] else self._state('last_day')
        if is_rack:
            day = compact_day(actual.fragment)
            current = next((r for r in data['records'] if r['day'] == day), None)
            if not current or self._read('records', _record_key(current)) is None:
                raise ValueError('先にこの台の全台一覧を取り込んでください。')
            if any(r['rack'] != current['rack'] or _machine_key(r) != _machine_key(current) for r in data['records']):
                raise ValueError('台別7日分の内容が一致しません。')
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
                saved = _merge(self._read('records', key), r)
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

    def export_viewer(self, path):
        data = {'format': FORMAT, 'version': 1,
                'machines': [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM machines ORDER BY rowid')],
                'records': [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM records ORDER BY rowid')]}
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        temporary.replace(target)
        return target


def run_session(db_path, export_path):
    import webview

    script = CAPTURE.read_text(encoding='utf-8')

    class Bridge:
        def __init__(self):
            self._window = None

        def submit_page(self, raw):
            current = self._window.get_current_url()
            db = PscubeStore(db_path)
            try:
                result = db.import_page(raw, current)
                db.export_viewer(export_path)
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
      button.onclick = async () => {
        if (isRoot) { location.href = indexUrl; return; }
        button.disabled = true; button.textContent = '読み込み中…';
        try {
          const list = document.querySelector('#ulKI') || document.querySelector('li[id^="li-"]')?.parentElement;
          if (list) {
            let stable = 0, old = -1;
            for (let i = 0; i < 70 && stable < 3; i++) {
              list.lastElementChild?.scrollIntoView({block:'end'});
              await new Promise(resolve => setTimeout(resolve, 350));
              const count = list.children.length;
              stable = count === old ? stable + 1 : 0; old = count;
            }
          }
          const payload = CAPTURE_SCRIPT;
          const result = await window.pywebview.api.submit_page(payload);
          button.textContent = `${result.kind}を保存 · 残り${result.remaining}`;
          if (result.next_url) location.href = result.next_url;
        } catch (error) { button.textContent = String(error.message || error); button.disabled = false; }
      };
      document.body.append(button);
    })();
    '''.replace('CAPTURE_SCRIPT', script).replace('INDEX_URL', json.dumps(ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2'))

    def install_overlay():
        try:
            site_url(window.get_current_url())
            window.evaluate_js(overlay)
        except Exception:
            pass

    window.events.loaded += install_overlay
    webview.start(gui='edgechromium')


if __name__ == '__main__':
    root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    run_session(sys.argv[1] if len(sys.argv) > 1 else root / 'data' / 'pscube.sqlite3',
                sys.argv[2] if len(sys.argv) > 2 else root / 'data' / 'pscube-viewer.json')
