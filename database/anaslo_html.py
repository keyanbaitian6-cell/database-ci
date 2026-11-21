"""Offline, lossless table conversion. No network access or application DB writes.

Usage: python convert_anaslo.py INPUT.html [INPUT.html ...] --output OUTPUT.json
This is a staging document, NOT an existing pscube-viewer backup.
"""
import argparse
from collections import Counter
from datetime import date
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.title = None
        self.titles = []
        self.script = None
        self.scripts = []
        self.canonical = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        if tag == 'h1':
            self.title = []
        if tag == 'script':
            self.script = []
        if tag == 'table':
            if self.table is not None:
                raise ValueError('Nested tables are unsupported')
            self.table = {'id': attrs.get('id'), 'rows': []}
        elif tag == 'tr' and self.table is not None:
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.title is not None:
            self.title.append(data)
        if self.script is not None:
            self.script.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'h1' and self.title is not None:
            self.titles.append(''.join(self.title).strip())
            self.title = None
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.table['rows'].append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


COLUMNS = ['機種名', '台番号', 'G数', 'BB', 'RB', 'ART', '合成確率', 'BB確率', 'RB確率', 'ART確率']
# 幸町店の表にはART・ART確率の列がない（2026-10-16 保存HTMLで確認）。ARTは不明（None）のまま保持する。
COLUMNS_WITHOUT_ART = ['機種名', '台番号', 'G数', 'BB', 'RB', '合成確率', 'BB確率', 'RB確率']


def integer(text):
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)', text):
        raise ValueError(f'Missing or invalid integer: {text!r}')
    return int(text.replace(',', ''))


def probability(text):
    # Keep the source display, including 1/0.0; it is not a valid probability.
    if text in ('', '-', '—'):
        return {'display': text, 'denominator': None}
    match = re.fullmatch(r'1/(\d+(?:\.\d+)?)', text)
    if not match:
        raise ValueError(f'Invalid probability: {text!r}')
    denominator = float(match[1])
    return {'display': text, 'denominator': denominator or None}


def parse_html(raw, filename):
    doc = Document()
    doc.feed(raw.decode('utf-8-sig', errors='strict'))
    if doc.table is not None:
        raise ValueError('Unclosed table')
    matches = [re.fullmatch(r'(\d{4})/(\d{2})/(\d{2}) (.+) データまとめ', t) for t in doc.titles]
    matches = [m for m in matches if m]
    if len(matches) != 1:
        raise ValueError('Expected one unambiguous data heading')
    year, month, day, store = matches[0].groups()
    day = date(int(year), int(month), int(day)).isoformat()
    # The filename and canonical URL are independent date checks, not date fallbacks.
    for value in (filename, doc.canonical or ''):
        match = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', value)
        if match and '-'.join(match.groups()) != day:
            raise ValueError('Heading/date metadata mismatch')
    tables = [t for t in doc.tables if t['id'] == 'all_data_table']
    if len(tables) != 1 or not tables[0]['rows'] or tables[0]['rows'][0] not in (COLUMNS, COLUMNS_WITHOUT_ART):
        raise ValueError('Unexpected all_data_table structure')
    columns = tables[0]['rows'][0]
    records = []
    racks = set()
    for cells in tables[0]['rows'][1:]:
        if len(cells) != len(columns) or not cells[0]:
            raise ValueError('Incomplete table row')
        row = dict(zip(columns, cells))
        rack = integer(row['台番号'])
        if rack <= 0 or rack in racks:
            raise ValueError(f'Duplicate/invalid rack: {rack}')
        racks.add(rack)
        records.append({'machine': row['機種名'], 'rack': rack, 'games': integer(row['G数']),
                        'bb': integer(row['BB']), 'rb': integer(row['RB']),
                        'at_art': integer(row['ART']) if 'ART' in row else None,
                        'probabilities': {key: probability(row[col]) for col, key in
                                          (('合成確率', 'combined'), ('BB確率', 'bb'), ('RB確率', 'rb'), ('ART確率', 'at_art'))
                                          if col in row},
                        'my': None, 'net_medals': None, 'graph': None})
    if not records:
        raise ValueError('Empty all-data table')
    by_rack = {r['rack']: r for r in records}
    # Machine detail tables repeat the same data. Check every numeric rack row.
    checked = set()
    for table in doc.tables:
        rows = table['rows']
        if table is tables[0] or not rows or '台番号' not in rows[0]:
            continue
        headers = rows[0]
        rack_index = headers.index('台番号')
        for cells in rows[1:]:
            if len(cells) <= rack_index or not re.fullmatch(r'\d+', cells[rack_index]):
                continue  # explicitly non-rack rows, e.g. 平均
            if len(cells) != len(headers):
                raise ValueError('Incomplete machine detail row')
            rack = integer(cells[rack_index])
            if rack not in by_rack or rack in checked:
                raise ValueError(f'Unexpected detail rack: {rack}')
            r = by_rack[rack]
            mapping = dict(zip(headers, cells))
            if '機種名' in mapping and mapping['機種名'] != r['machine']:
                raise ValueError(f'Detail machine mismatch: {rack}')
            for col, key in (('G数', 'games'), ('BB', 'bb'), ('RB', 'rb'), ('ART', 'at_art')):
                if col in mapping and (r[key] is None or integer(mapping[col]) != r[key]):
                    raise ValueError(f'Detail mismatch: {rack} {col}')
            for col, key in (('合成確率', 'combined'), ('BB確率', 'bb'), ('RB確率', 'rb'), ('ART確率', 'at_art')):
                if col in mapping and probability(mapping[col]) != r['probabilities'].get(key):
                    raise ValueError(f'Detail probability mismatch: {rack} {col}')
            checked.add(rack)
    if checked != racks:
        raise ValueError('Machine detail tables do not cover all racks')
    graphs = set()
    for script in doc.scripts:
        if 'var x_value' not in script or 'var y_value' not in script:
            continue
        identity = re.search(r'getElementById\([\"\'](\d+)[\"\']\)', script)
        x = re.search(r'var x_value\s*=\s*(\[[^\]]*\])\s*;', script)
        y = re.search(r'var y_value\s*=\s*(\[[^\]]*\])\s*;', script)
        zero = re.findall(r'context\.tick\.value\s*==\s*([\d.]+)', script)
        if not identity or not x or not y or not zero or len(set(zero)) != 1:
            raise ValueError('Unsupported graph script')
        rack = int(identity[1])
        if rack not in racks or rack in graphs:
            raise ValueError('Duplicate/unknown graph rack')
        xs, ys = json.loads(x[1]), json.loads(y[1])
        if len(xs) != len(ys) or not xs or any(type(v) not in (int, float) or not math.isfinite(v) for v in xs + ys):
            raise ValueError('Invalid graph coordinates')
        if any(b < a for a, b in zip(xs, xs[1:])):
            raise ValueError('Graph X values are out of order')
        zero_y, origin = float(zero[0]), {}
        if zero_y == 0 and xs[0] == 0 and ys[0] != 0:
            # 古い形式（P-STATIONの2026-01〜08前半）：軸は −1000〜1000・赤い線は0の設定のまま、点は新しい形式と同じ
            # 画素の座標（下ほどマイナス）で y=312 から始まる。差枚のグラフは0枚から始まるので、最初の点をゼロ線にする
            # （2026-11-21。新しい形式は9,813行すべて (0,312) 始まりで zero_y 312。直したあとのプラスの割合は新しい形式と
            # ほぼ同じ）。目盛りの倍率は確かめられないので印を残し、推定差枚には使わない（anaslo_net.pixels）。
            zero_y, origin = float(ys[0]), {'zero_from': 'first-point'}
        by_rack[rack]['graph'] = {'kind': 'source_coordinates', 'points': list(map(list, zip(xs, ys))),
                                 'zero_y': zero_y, 'y_increases_downward': True,
                                 'medals_per_y_unit': None, 'games_per_x_unit': None, **origin}
        graphs.add(rack)
    counts = Counter(r['machine'] for r in records)
    return {'day': day, 'store': {'source_name': store, 'rate': None},
            'source': {'site': 'anaslo', 'file': filename, 'url': doc.canonical,
                       'sha256': hashlib.sha256(raw).hexdigest(), 'observed_at': None},
            'machines': [{'name': name, 'record_count': count} for name, count in counts.items()],
            'records': records,
            'validation': {'records': len(records), 'machines': len(counts),
                           'detail_rows_checked': len(checked),
                           'racks_without_detail_table': sorted(racks - checked), 'graphs': len(graphs)}}


# 解析結果の控え（2026-11-06）。1か月分の解析に10〜20秒かかるため、同じHTMLを読み直すときは控えを使う。
# 鍵は HTML の中身・ファイル名・このファイル自体の SHA-256。解析の規則を変えれば自動で使われなくなる。
_PARSER_REVISION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def parse_cached(raw, filename, cache_dir=None):
    if cache_dir is None:
        return parse_html(raw, filename)
    key = hashlib.sha256(raw + b'\0' + filename.encode('utf-8') + b'\0' + _PARSER_REVISION.encode()).hexdigest()
    path = Path(cache_dir) / f'{key}.json'
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
        if (isinstance(cached, dict) and cached.get('revision') == _PARSER_REVISION
                and cached.get('sha256') == hashlib.sha256(raw).hexdigest() and isinstance(cached.get('day'), dict)):
            try:
                path.touch()  # 使った順に残す（prune_cache）
            except OSError:
                pass
            return cached['day']
    except (OSError, ValueError):
        pass
    day = parse_html(raw, filename)  # 解析できないHTMLは控えを作らず、今までどおり例外にする
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.part')
        temp.write_text(json.dumps({'revision': _PARSER_REVISION, 'sha256': day['source']['sha256'], 'day': day},
                                   ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temp.replace(path)
    except (OSError, ValueError):
        pass  # 控えが書けなくても変換は続ける
    return day


def prune_cache(cache_dir, keep=400):
    """控えは1日分で約0.2MB。最近使った keep 件（約80MB）だけ残す。"""
    try:
        files = sorted(Path(cache_dir).glob('*.json*'), key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return 0
    removed = 0
    for f in files[keep:]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def set_rate(staging, rate):
    """解析済みの日に、利用者が確かめた貸玉を付ける（HTMLに貸玉は無い）。"""
    if not re.fullmatch(r'\d+(?:\.\d+)?', rate):
        raise ValueError('Invalid explicit rate')
    for d in staging['days']:
        d['store'].update(rate=rate, rate_basis='user_confirmed; not present in HTML')
    return staging


def convert(paths, rate=None, cache_dir=None):
    days = [parse_cached(Path(p).read_bytes(), Path(p).name, cache_dir) for p in paths]
    if rate is not None:
        set_rate({'days': days}, rate)
    identities = [(d['store']['source_name'], d['day']) for d in days]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate store/day input')
    return {'format': 'anaslo-hall-staging', 'version': 1,
            'import_ready': False, 'days': sorted(days, key=lambda d: d['day']),
            'limitations': ['Not a pscube-viewer backup', 'MY and observation time unknown; rate requires user confirmation',
                            'Graph coordinates retained; medal/game scale unknown',
                            'Source machine names require explicit mapping before Pscube import']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--rate', help='Explicit user-confirmed rate; never inferred from HTML')
    args = parser.parse_args()
    payload = convert(args.html, args.rate)  # Validate all inputs before creating any output.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps([{'day': d['day'], **d['validation']} for d in payload['days']], ensure_ascii=False))


if __name__ == '__main__':
    main()
