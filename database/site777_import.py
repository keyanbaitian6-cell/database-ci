"""サイトセブンの表示済み資料の検証・変換。ここでは通信もDB書き込みもしない。"""
from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from PIL import Image

import site777_net

JST = timezone(timedelta(hours=9))
HALL = '04034001'
SHOP = 'c740601'
PATHS = {'/f/D0300.do': 'index', '/f/D2300.do': 'model', '/f/D3300.do': 'table', '/f/D4300.do': 'graphs'}
QUERY_KEYS = ('pmc', 'clc', 'urt', 'mdc', 'bn', 'soc', 'sw', 'pan', 'dsgk', 'dtdd', 'data', 'dn')
HEADERS = {'台番': 'rack', '累計ゲーム': 'games', 'BB回数': 'bb', 'RB回数': 'rb',
           '最高出玉': 'my', 'ART回数': 'at_art'}


def source_url(raw, kind=None):
    """店舗・貸玉・ページ種類を確認し、保存に不要な問い合わせの値を持ち出さない。"""
    if not isinstance(raw, str):
        raise ValueError('サイトセブンの出典URLがありません。')
    u = urlsplit(raw)
    pairs = parse_qsl(u.query, keep_blank_values=True)
    values = dict(pairs)
    if (u.scheme != 'https' or u.netloc != 'm.site777.jp' or u.path not in PATHS
            or kind is not None and PATHS[u.path] != kind
            or values.get('pmc') != HALL or values.get('urt') != '2000'
            or values.get('clc', '03') != '03'):
        raise ValueError('P-STATIONの20円スロットの出典を確認できません。')
    known = [(k, v) for k, v in pairs if k in QUERY_KEYS]
    if len(dict(known)) != len(known) or any(not re.fullmatch(r'-?\d+', v) for _, v in known):
        raise ValueError('出典URLの項目が不正です。')
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(sorted(known)), ''))


def same_page(first, second):
    try:
        return source_url(first) == source_url(second)
    except (TypeError, ValueError):
        return False


def _integer(value, label, nullable=False):
    if nullable and value in (None, '', '--', '－', '—'):
        return None
    if isinstance(value, str) and re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)', value):
        value = int(value.replace(',', ''))
    if type(value) is not int or not 0 <= value <= 1000000:
        raise ValueError(f'{label}の数値が不明または不正です。0に置き換えず保存を止めました。')
    return value


def day_from_label(label, now=None):
    """月日だけの表示を、日本時間の採取日近傍の実在する一つの日付へ解決する。"""
    now = now or datetime.now(JST)
    today = now.astimezone(JST).date()
    if not isinstance(label, str) or not re.fullmatch(r'\d{1,2}/\d{1,2}', label):
        raise ValueError('画面の日付を確認できません。')
    month, day = map(int, label.split('/'))
    choices = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if 0 <= (today - candidate).days <= 9:
            choices.append(candidate.isoformat())
    if len(choices) != 1:
        raise ValueError('掲載期間の日付を確認できません。')
    return choices[0]


def table_records(payload, target_day, now=None):
    """表示中の全台表を検証する。未知のBB/RB/G数では保存せず、ART/MY欠損は保持。"""
    url = source_url(payload.get('url'), 'table')
    if day_from_label(payload.get('selected_md'), now) != target_day:
        raise ValueError('取り込み日と画面の日付が違います。保存しませんでした。')
    headers = payload.get('headers')
    rows = payload.get('rows')
    if not isinstance(headers, list) or not isinstance(rows, list) or not rows:
        raise ValueError('全台一覧の表がありません。')
    columns = [HEADERS.get(h) for h in headers]
    if any(columns.count(k) != 1 for k in HEADERS.values()):
        raise ValueError('台番・累計ゲーム・BB・RB・最高出玉・ARTの6列を表示してください。')
    if type(payload.get('count')) is not int or payload['count'] != len(rows):
        raise ValueError('表示台数と表の行数が一致しません。全台の表を確認してください。')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError('表の列数が一致しません。')
        record = {key: _integer(row[i], key, key in ('my', 'at_art'))
                  for i, key in enumerate(columns) if key}
        rack = record['rack']
        if rack < 1 or rack in seen:
            raise ValueError('台番号の重複または不正があります。')
        seen.add(rack)
        result.append(record)
    q = dict(parse_qsl(urlsplit(url).query))
    if q.get('mdc') != payload.get('model_id') or not isinstance(payload.get('machine'), str) or not payload['machine'].strip():
        raise ValueError('機種名・機種番号を確認できません。')
    return result


def trace_graph(data_uri):
    """原画像の黄色い線を画素座標で保存する。画像から正確な差枚は捏造しない。"""
    import numpy as np

    if not isinstance(data_uri, str) or not data_uri.startswith('data:image/png;base64,') or len(data_uri) > 1500000:
        raise ValueError('表示済みグラフの画像が不正です。')
    try:
        raw = base64.b64decode(data_uri.split(',', 1)[1], validate=True)
        image = Image.open(BytesIO(raw))
        if image.size != (260, 226) or image.format != 'PNG':
            raise ValueError('未対応のグラフ画像サイズです。')
        pixels = np.asarray(image.convert('RGB')).astype('int16')
    except (OSError, ValueError) as error:
        raise ValueError('グラフ画像を読み取れません。') from error
    source = {'format': 'site777-yellow-pixels-v1', 'image_sha256': hashlib.sha256(raw).hexdigest(),
              'width': 260, 'height': 226}
    neutral = (pixels.min(axis=2) >= 185) & (pixels.max(axis=2) - pixels.min(axis=2) <= 15)
    lengths = neutral[:, 6:246].sum(axis=1)
    zero_rows = np.where(lengths >= 210)[0]
    if not len(zero_rows) or int(zero_rows.max()) - int(zero_rows.min()) > 3:
        return None, {**source, 'error': 'zero_line_unknown'}
    zero = float(np.mean(zero_rows))
    yellow = (pixels[:, :, 0] >= 130) & (pixels[:, :, 1] >= 130) & (pixels[:, :, 2] < 100)
    yellow[:8] = False
    yellow[212:] = False
    yellow[:, :8] = False
    yellow[:, 245:] = False
    points = []
    for x in range(8, 245):
        ys = np.where(yellow[:, x])[0]
        if len(ys):
            points.append([x, float(np.median(ys))])
    if len(points) < 3 or points[0][0] > 14 or any(b[0] - a[0] > 3 for a, b in zip(points, points[1:])):
        return None, {**source, 'error': 'curve_unknown'}
    return {'kind': 'daily', 'zero_y': zero, 'points': points}, source


def graph_records(payload, target_day, model_id, expected_racks, now=None):
    url = source_url(payload.get('url'), 'graphs')
    if (day_from_label(payload.get('selected_md'), now) != target_day
            or dict(parse_qsl(urlsplit(url).query)).get('mdc') != model_id
            or payload.get('model_id') != model_id):
        raise ValueError('グラフの機種・日付が全台一覧と一致しません。')
    graphs = payload.get('graphs')
    if not isinstance(graphs, list) or not graphs or len(graphs) > 20:
        raise ValueError('グラフ一覧の台数を確認できません。')
    result = {}
    for item in graphs:
        rack = item.get('rack')
        if type(rack) is not int or rack not in expected_racks or rack in result:
            raise ValueError('全台一覧にない台、または重複した台のグラフです。')
        label = item.get('my_label')
        if isinstance(expected_racks, dict) and label:
            my = _integer(label.removesuffix('枚').strip(), 'グラフ一覧の最高出玉')
            if expected_racks[rack] is not None and my != expected_racks[rack]:
                raise ValueError('表とグラフ一覧の最高出玉が違います。更新中の可能性があるため保存しません。')
        curve, source = trace_graph(item.get('png'))
        result[rack] = {'graph': curve, 'source_graph': source}
        # 画像の目盛りから読んだ推定差枚（site777_net.py、2026-11-07）。読めない・保留の台には付けない。
        estimate = site777_net.net_estimate(base64.b64decode(item['png'].split(',', 1)[1])) if curve else None
        if estimate is not None:
            result[rack]['net_estimate'] = estimate
    return result


def make_backup(table, rows, graphs, target_day, machine, catalog=(), now=None):
    """出典を保持し、既存P’s CUBEインポートへ渡す補完バックアップを作る。"""
    now = now or datetime.now(JST)
    stamp = now.astimezone(JST).isoformat(timespec='seconds')
    url = source_url(table.get('url'), 'table')
    if not isinstance(machine, str) or not machine.strip():
        raise ValueError('保存する機種名が不明です。')
    native = next((m for m in catalog if m['store'] == SHOP and m['rate'] == '20' and m['machine'] == machine), None)
    model = dict(native) if native else {'store': SHOP, 'rate': '20', 'machine': machine,
        'url': None, 'expected_count': table['count'], 'machine_type': None, 'source_site': 'site777'}
    digest = hashlib.sha256(json.dumps({'url': url, 'day': target_day, 'rows': rows},
                                     ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    records = []
    for row in rows:
        if row['rack'] not in graphs:
            raise ValueError('全台のグラフがそろっていません。')
        records.append({**row, 'store': SHOP, 'rate': '20', 'machine': machine, 'day': target_day,
            'detail_url': None, 'observed_at': None, 'net_medals': None, **graphs[row['rack']],
            'source_site': 'site777', 'source_url': url, 'source_sha256': digest,
            'source_machine': table['machine'], 'source_day_label': table['selected_md'],
            'source_captured_at': stamp})
    return {'format': 'pscube-viewer', 'version': 1, 'kind': 'backup', 'source': 'site777',
            'import_mode': 'fill_missing', 'machines': [model], 'records': records, 'rack_captures': []}


def validate_record(record):
    """バックアップ復元・別端末でも使うサイトセブン固有の出典と欠損の検証。"""
    url = source_url(record.get('source_url'), 'table')
    if any(k not in record for k in ('my', 'at_art', 'detail_url', 'net_medals', 'observed_at', 'graph')):
        raise ValueError('サイトセブンの欠損値が明示されていません。')
    if (record.get('store') != SHOP or record.get('rate') != '20'
            or record.get('detail_url') is not None or record.get('net_medals') is not None
            or ('net_estimate' in record and not site777_net.valid(record['net_estimate']))
            or record.get('net_capture') is not None
            or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('source_sha256', '')))
            or not isinstance(record.get('source_machine'), str) or not record['source_machine'].strip()):
        raise ValueError('サイトセブンの出典・店舗・欠損値が不正です。')
    try:
        captured = datetime.fromisoformat(record.get('source_captured_at', ''))
    except (ValueError, TypeError) as error:
        raise ValueError('サイトセブンの採取日時が不正です。') from error
    if captured.utcoffset() != timedelta(hours=9) or day_from_label(record.get('source_day_label'), captured) != record.get('day'):
        raise ValueError('サイトセブンの採取日と営業日が不正です。')
    for name in ('my', 'at_art'):
        if record[name] is not None and type(record[name]) is not int:
            raise ValueError('サイトセブンの数値の型が不正です。')
        _integer(record.get(name), name, nullable=True)
    source = record.get('source_graph')
    if (not isinstance(source, dict) or source.get('format') != 'site777-yellow-pixels-v1'
            or source.get('width') != 260 or source.get('height') != 226
            or not re.fullmatch(r'[0-9a-f]{64}', str(source.get('image_sha256', '')))):
        raise ValueError('サイトセブンのグラフの出典が不正です。')
    if record.get('observed_at') is not None:
        raise ValueError('サイトセブンの未確認の更新日時が設定されています。')
    graph = record.get('graph')
    unknown = graph is None and source.get('error') in ('zero_line_unknown', 'curve_unknown')
    if not unknown and (not isinstance(graph, dict) or graph.get('kind') != 'daily' or type(graph.get('zero_y')) not in (int, float)
            or not 0 <= graph['zero_y'] <= 226 or not isinstance(graph.get('points'), list)
            or not 2 <= len(graph['points']) <= 260
            or any(not isinstance(p, list) or len(p) != 2
                   or any(type(v) not in (int, float) for v in p)
                   or not 0 <= p[0] <= 260 or not 0 <= p[1] <= 226 for p in graph['points'])):
        raise ValueError('サイトセブンの画像とグラフ座標が一致しません。')
    if not dict(parse_qsl(urlsplit(url).query)).get('mdc'):
        raise ValueError('出典の機種番号がありません。')
