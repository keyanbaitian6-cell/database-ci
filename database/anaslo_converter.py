"""Offline HTML-to-backup service shared by the separate desktop converter.

Never opens a writable application database. Native MY/URLs are not fabricated.
"""
from collections import Counter
from contextlib import closing
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

from anaslo_html import convert

SHOP = 'c740601'
SHOP_NAME = 'P-STATION&IIスロット館'


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
    staging = convert(paths, rate)
    if any(d['store']['source_name'] != SHOP_NAME for d in staging['days']):
        raise ValueError('現在はP-STATION&IIスロット館のHTMLだけに対応しています。')
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
