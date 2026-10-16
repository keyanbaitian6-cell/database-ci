"""Offline HTML-to-backup service shared by the separate desktop converter.

Never opens a writable application database. Native MY/URLs are not fabricated.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

from anaslo_html import convert
from anaslo_index import HALL_NAMES, HALLS, P_STATION, SAIWAICHOU

SHOP = 'c740601'
SHOP_NAME = P_STATION.source_name


def normalized(name):
    text = unicodedata.normalize('NFKC', name).strip()
    text = re.sub(r'^(?:スマスロ\s*|LB\s*|L(?=[\sァ-ヶぁ-ん一-龯])\s*)', '', text)
    return re.sub(r'[^\w]', '', text.casefold())


def read_catalog(path):
    path = Path(path)
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM machines')]


def suggestions(name, catalog, rate='20'):
    names = sorted({m['machine'] for m in catalog if m['store'] == SHOP and m['rate'] == rate})
    key = normalized(name)
    exact = [n for n in names if normalized(n) == key]
    candidates = sorted(names, key=lambda n: (-SequenceMatcher(None, key, normalized(n)).ratio(), n))[:5]
    return {'automatic': exact[0] if len(exact) == 1 else None, 'candidates': candidates}


def analyze(paths, rate='20'):
    """``rate`` is the user-confirmed P-STATION rate. 幸町 goes to the meruhen
    DB (1000円46枚 only), so no rate is attached there."""
    staging = convert(paths)
    names = {d['store']['source_name'] for d in staging['days']}
    halls = [h for h in HALLS if h.source_name in names]
    if len(halls) != len(names):
        raise ValueError(f'現在は{HALL_NAMES}のHTMLだけに対応しています。')
    if len(halls) != 1:
        raise ValueError('1回に変換できるのは1店舗のHTMLだけです。店舗ごとに選び直してください。')
    if halls[0] is P_STATION:
        staging = convert(paths, rate)
    staging['hall'] = halls[0].key
    return staging


def make_backup(staging, mapping, catalog):
    """Mapping entries are explicitly chosen names; None means omit this machine."""
    from pscube_import import _validate_machine, _validate_record, is_excluded_machine
    if staging.get('format') != 'anaslo-hall-staging' or staging.get('version') != 1:
        raise ValueError('解析結果の形式が違います。')
    machines, records, skipped = {}, [], Counter()
    occupied = set()
    for d in staging['days']:
        if d['store']['source_name'] != SHOP_NAME or d['store']['rate'] is None:
            raise ValueError('店舗・貸玉を確認してください。')
        rate = d['store']['rate']
        known = {m['machine']: m for m in catalog if m['store'] == SHOP and m['rate'] == rate}
        for source in d['records']:
            name = source['machine']
            if is_excluded_machine(name):
                skipped['excluded'] += 1
                continue
            if name not in mapping:
                raise ValueError(f'機種名の対応を確認してください：{name}')
            target = mapping[name]
            if target is None:
                skipped['manual'] += 1
                continue
            if not isinstance(target, str) or not target.strip() or is_excluded_machine(target):
                raise ValueError(f'対応する機種名が不正です：{name}')
            target = target.strip()
            key = (SHOP, rate, target)
            if key not in machines:
                # Use real catalog URLs only; source-only machines are never capture targets.
                machines[key] = dict(known[target]) if target in known else {
                    'store': SHOP, 'rate': rate, 'machine': target, 'url': None,
                    'expected_count': None, 'machine_type': None, 'source_site': 'anaslo'}
            identity = (SHOP, rate, source['rack'], d['day'])
            if identity in occupied:
                raise ValueError('同じ日付・台番号が重複しています。')
            occupied.add(identity)
            records.append({'store': SHOP, 'rate': rate, 'machine': target, 'rack': source['rack'],
                            'day': d['day'], 'games': source['games'], 'bb': source['bb'],
                            'rb': source['rb'], 'at_art': source['at_art'], 'my': None,
                            'detail_url': None, 'observed_at': None, 'net_medals': None, 'graph': None,
                            'source_site': 'anaslo', 'source_url': d['source']['url'],
                            'source_sha256': d['source']['sha256'], 'source_machine': name,
                            'source_probabilities': source['probabilities'], 'source_graph': source['graph']})
    if not records:
        raise ValueError('出力対象のデータがありません。')
    for m in machines.values():
        _validate_machine(m)
    for r in records:
        _validate_record(r)
    return {'format': 'pscube-viewer', 'version': 1, 'kind': 'backup',
            'source': 'anaslo-converter', 'import_mode': 'fill_missing',
            'machines': list(machines.values()), 'records': records, 'rack_captures': [],
            'conversion_summary': {'records': len(records), 'skipped': dict(skipped)}}


def save_backup(path, payload):
    """Exclusive creation prevents silently overwriting another backup."""
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(text)


# --- 幸町（メルヘン用DB）-------------------------------------------------------

MERUHEN_STORE = SAIWAICHOU.key


_SERIES_WORDS = r'(?:スマスロ|パチスロ|スロット)'


def _plain(name):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', name).casefold())


def _plain_source(name):
    """Ana-slo name without 'スマスロ' / a leading 'L' before kana."""
    return re.sub(r'^l(?=[^a-z0-9])', '', re.sub('^' + _SERIES_WORDS, '', _plain(name)))


def _same_apart_from_decorations(source_key, candidate):
    """Meruhen spells names like '★L／いざ番長／SB8' or 'SマイジャグラーVKD':
    an L/S/LB/SB prefix, an optional series word and a short trailing code."""
    return bool(source_key) and re.fullmatch(
        r'(?:lb|sb|l|s)?' + _SERIES_WORDS + '?' + re.escape(source_key) + r'[a-z0-9]{0,6}',
        _plain(candidate)) is not None


def read_meruhen_catalog(path, store=MERUHEN_STORE):
    """Read-only: saved (day, machine, rack) of one meruhen store."""
    from core import is_hidden_machine, normalize_machine_name
    path = Path(path)
    if not path.is_file():
        return MeruhenCatalog(store, [])
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute("SELECT day, machine, rack, json_extract(payload, '$.source_site') FROM days WHERE store=?",
                          (store,)).fetchall()
    return MeruhenCatalog(store, [(d, normalize_machine_name(m), int(r), site) for d, m, r, site in rows
                                  if not is_hidden_machine(store, m)])


class MeruhenCatalog:
    def __init__(self, store, rows):
        """``rows``: (day, machine, rack[, source_site]) of saved records."""
        self.store = store
        self.occupied = {(day, rack) for day, _, rack, *_ in rows}
        self.names = sorted({name for _, name, _, *_ in rows})
        self.racks = {}
        self.native = {}  # Names the meruhen site itself gave each rack.
        for _, name, rack, *site in rows:
            self.racks.setdefault(rack, Counter())[name] += 1
            if not site or site[0] != 'anaslo':
                self.native.setdefault(rack, Counter())[name] += 1

    def rack_spelling(self, rack, name):
        """Meruhen marks some racks of a machine with ★ (2026-10-17：海門決戦は1278番台だけ★).
        Use the spelling meruhen itself saved on this rack, or the history splits."""
        same = [(count, n) for n, count in self.native.get(rack, {}).items() if _plain(n) == _plain(name)]
        return max(same)[1] if same else name

    def suggestions(self, name, racks=()):
        """Name candidates; names saved on the same racks come first.

        Automatic only when two independent signals agree on one name: the
        names match apart from meruhen's decorations (★, L/S prefix, a short
        trailing code), and that name was saved on one of the same racks."""
        key = _plain_source(name)
        on_racks = Counter()
        for rack in racks:
            on_racks.update(self.racks.get(rack, {}))
        matched = [n for n in self.names if _same_apart_from_decorations(key, n)]
        # Spellings that differ only by symbols (e.g. a leading ★) are one machine:
        # take the one saved most often on these racks.
        spelled = [n for n in matched if n in on_racks]
        automatic = (max(spelled, key=lambda n: (on_racks[n], n))
                     if spelled and len({_plain(n) for n in matched}) == 1 else None)
        by_rack = [n for n, _ in sorted(on_racks.items(), key=lambda item: (-item[1], item[0]))]
        similar = sorted(self.names, key=lambda n: (-SequenceMatcher(None, key, _plain(n)).ratio(), n))[:5]
        return {'automatic': automatic, 'candidates': list(dict.fromkeys([*matched, *by_rack, *similar]))[:8]}


def make_meruhen_backup(staging, mapping, catalog):
    """Meruhen backup that only fills (day, rack) slots missing in the DB.

    The meruhen import never overwrites differing numbers either; skipping
    occupied slots here also avoids a second row under another machine name.
    Racks never saved in the meruhen DB are left out: the HTML has no rate,
    and that DB holds only 1000円46枚 slots."""
    from core import BACKUP_FORMAT, BACKUP_VERSION, _valid_backup_record, is_excluded_machine, normalize_machine_name
    if staging.get('format') != 'anaslo-hall-staging' or staging.get('version') != 1:
        raise ValueError('解析結果の形式が違います。')
    store = catalog.store
    records, skipped, occupied = [], Counter(), set()
    for d in staging['days']:
        if d['store']['source_name'] != SAIWAICHOU.source_name:
            raise ValueError('店舗を確認してください。')
        for source in d['records']:
            name = source['machine']
            if is_excluded_machine(store, name):
                skipped['excluded'] += 1
                continue
            if name not in mapping:
                raise ValueError(f'機種名の対応を確認してください：{name}')
            target = mapping[name]
            if target is None:
                skipped['manual'] += 1
                continue
            if not isinstance(target, str) or not target.strip() or is_excluded_machine(store, target):
                raise ValueError(f'対応する機種名が不正です：{name}')
            if source['rack'] not in catalog.racks:
                skipped['unknown_rack'] += 1
                continue
            identity = (d['day'], source['rack'])
            if identity in catalog.occupied:
                skipped['existing'] += 1
                continue
            if identity in occupied:
                raise ValueError('同じ日付・台番号が重複しています。')
            occupied.add(identity)
            record = {'store': store, 'kind_code': 21, 'day': d['day'],
                      'machine': catalog.rack_spelling(source['rack'], normalize_machine_name(target)),
                      'rack': source['rack'],
                      'games': source['games'], 'bb': source['bb'], 'rb': source['rb'], 'max_hold': None,
                      'source_site': 'anaslo', 'source_url': d['source']['url'],
                      'source_sha256': d['source']['sha256'], 'source_machine': name,
                      'source_probabilities': source['probabilities'], 'source_graph': source['graph']}
            if not _valid_backup_record(record):
                raise ValueError(f'{source["rack"]}番台の数値を確認してください。')
            records.append(record)
    if not records:
        raise ValueError('出力対象のデータがありません（databaseに保存済みの日付・台、または対象外だけでした）。')
    return {'format': BACKUP_FORMAT, 'version': BACKUP_VERSION, 'source': 'anaslo-converter',
            'exported_at': datetime.now().astimezone().isoformat(timespec='seconds'), 'records': records,
            'conversion_summary': {'records': len(records), 'skipped': dict(skipped)}}


# --- 変換画面が店舗ごとに切り替える部分 --------------------------------------------

class PscubeTarget:
    """P-STATION → P’s CUBE用DB（既存の仕様のまま）。"""
    hall = P_STATION
    alias_file = 'machine_names.json'
    rate_text = '貸玉：20円'
    notice = ('既存の日付・台の記録を優先します。MY・差枚は不明のまま保存します。\n'
              '沖ドキは既存ルールに従い対象外です。実DBへの反映はdatabaseの「バックアップを読み込む」で行います。')

    def __init__(self, data_dir):
        self.catalog = read_catalog(Path(data_dir) / 'pscube.sqlite3')

    def names(self):
        return sorted({m['machine'] for m in self.catalog if m['store'] == SHOP and m['rate'] == '20'})

    def suggestions(self, name, racks=()):
        return suggestions(name, self.catalog)

    def excluded(self, name):
        from pscube_import import is_excluded_machine
        return is_excluded_machine(name)

    def make_backup(self, staging, mapping):
        return make_backup(staging, mapping, self.catalog)

    def file_name(self, period):
        return f'pscube-backup-anaslo-{period}.json'


class MeruhenTarget:
    """幸町 → メルヘン用DB。databaseに記録のある1000円46枚の台・未保存の日付だけを足す。"""
    hall = SAIWAICHOU
    alias_file = 'machine_names_saiwaichou.json'
    rate_text = '1000円46枚（databaseに記録のある台だけ）'
    notice = ('databaseに保存済みの日付・台は出力しません（既存の記録を優先）。最大持玉・グラフは不明のまま保存します。\n'
              'ブラックボード・沖ドキ・聖闘士星矢 海皇覚醒は既存ルールに従い対象外です。'
              '実DBへの反映はdatabaseの「バックアップを読み込む」で行います。')

    def __init__(self, data_dir):
        self.catalog = read_meruhen_catalog(Path(data_dir) / 'database.sqlite3', MERUHEN_STORE)

    def names(self):
        return list(self.catalog.names)

    def suggestions(self, name, racks=()):
        return self.catalog.suggestions(name, racks)

    def excluded(self, name):
        from core import is_excluded_machine
        return is_excluded_machine(MERUHEN_STORE, name)

    def make_backup(self, staging, mapping):
        return make_meruhen_backup(staging, mapping, self.catalog)

    def file_name(self, period):
        return f'database-backup-anaslo-{MERUHEN_STORE}-{period}.json'


TARGETS = {target.hall.key: target for target in (PscubeTarget, MeruhenTarget)}
