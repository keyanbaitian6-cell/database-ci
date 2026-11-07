"""差枚の取得診断。認証情報を保存せず、再解析用数値は7日・合計3MiBまで。"""
import json
import math
import re
from datetime import datetime, timezone

PROBE_MAX = 64 * 1024
PROBE_BUDGET = 3 * 1024 * 1024
PROBE_DAYS = 7
NUMBERS = ('bb', 'rb', 'at_art', 'games', 'my')
STATUSES = {'ok', 'empty', 'invalid', 'network', 'unavailable', 'unknown'}
REASONS = {'ok', 'missing_series', 'empty', 'short_series', 'invalid_points',
           'invalid_net', 'invalid_response', 'network', 'not_ready'}
OMITTED = {'size', 'unsafe', 'expired', 'budget'}


def _error():
    raise ValueError('差枚の取得診断が不正です。')


def _scalar(value):
    return (value is None or (type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e12)
            or (isinstance(value, str) and len(value) <= 32 and re.fullmatch(r'[-+\d.eE]*', value) is not None))


def _size(value):
    return len(json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode())


def _day(value):
    try:
        return isinstance(value, str) and datetime.strptime(value, '%Y-%m-%d').date().isoformat() == value
    except ValueError:
        return False


def _probe(raw):
    if not isinstance(raw, dict):
        _error()
    graph = raw.get('graph', {})
    datas = graph.get('datas', {}) if isinstance(graph, dict) else {}
    day = raw.get('day')
    if (raw.get('version') != 1 or type(raw.get('rack')) is not int or raw['rack'] < 1
            or not isinstance(day, str) or not re.fullmatch(r'\d{8}', day)
            or not _day(f'{day[:4]}-{day[4:6]}-{day[6:]}')
            or not isinstance(raw.get('numbers'), list) or not 1 <= len(raw['numbers']) <= 7
            or not isinstance(datas.get('g'), list) or len(datas['g']) > 7
            or not isinstance(datas.get('p'), list) or len(datas['p']) > 50000
            or not _scalar(graph.get('anjYUnit', 1))):
        _error()
    numbers = []
    for row in raw['numbers']:
        if (not isinstance(row, dict) or not _day(row.get('day'))
                or any(type(row.get(k)) is not int or row[k] < 0 for k in NUMBERS)):
            _error()
        numbers.append({'day': row['day'], **{k: row[k] for k in NUMBERS}})
    fields, series = set(), []
    for line in datas['g']:
        if (not isinstance(line, dict) or not _scalar(line.get('YMD_biz'))
                or not re.fullmatch(r'\d{8}', str(line.get('YMD_biz')))
                or not re.fullmatch(r'out-\d{1,5}', str(line.get('xField', '')))
                or not re.fullmatch(r'value-\d{1,5}', str(line.get('yField', '')))):
            _error()
        fields.update((line['xField'], line['yField']))
        series.append({k: line[k] for k in ('YMD_biz', 'xField', 'yField')})
    points = []
    for point in datas['p']:
        if not isinstance(point, dict) or any(not _scalar(point[k]) for k in fields if k in point):
            _error()
        points.append({k: point[k] for k in fields if k in point})
    result = {'version': 1, 'rack': raw['rack'], 'day': day, 'numbers': numbers,
              'graph': {'anjYUnit': graph.get('anjYUnit', 1), 'datas': {'g': series, 'p': points}}}
    if _size(result) > PROBE_MAX:
        _error()
    return result


def _instant(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return float('-inf')


def validate_net_capture(value, record=None):
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get('version') != 1 or value.get('status') not in STATUSES
            or value.get('reason') not in REASONS or not isinstance(value.get('checked_at'), str)
            or not re.search(r'(Z|[+-]\d{2}:\d{2})$', value['checked_at'])
            or not math.isfinite(_instant(value['checked_at']))):
        _error()
    result = {k: value[k] for k in ('version', 'status', 'reason', 'checked_at')}
    if value.get('http_status') is not None:
        if type(value['http_status']) is not int or not 0 <= value['http_status'] <= 599:
            _error()
        result['http_status'] = value['http_status']
    if value.get('probe_omitted') is not None:
        if value['probe_omitted'] not in OMITTED:
            _error()
        result['probe_omitted'] = value['probe_omitted']
    if value.get('probe') is not None:
        result['probe'] = _probe(value['probe'])
        if record is not None and (result['probe']['rack'] != record['rack'] or not any(
                n['day'] == record['day'] and all(n[k] == record[k] for k in NUMBERS)
                for n in result['probe']['numbers'])):
            _error()
    if value.get('probe_available') is not None:
        if type(value['probe_available']) is not bool:
            _error()
        result['probe_available'] = value['probe_available']
    return result


def trim_net_probes(records, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    remaining = PROBE_BUDGET
    samples = sorted((r for r in records if (r.get('net_capture') or {}).get('probe')),
                     key=lambda r: _instant(r['net_capture']['checked_at']), reverse=True)
    for row in samples:
        capture = row['net_capture']
        at, size = _instant(capture['checked_at']), _size(capture['probe'])
        reason = 'expired' if at < now - PROBE_DAYS * 86400 or at > now + 300 else 'budget' if size > remaining else None
        if reason:
            row['net_capture'] = {**{k: v for k, v in capture.items() if k not in ('probe', 'probe_available')}, 'probe_omitted': reason}
        else:
            remaining -= size
    return records


def merge_net_capture(chosen, alternate, same):
    a, b = chosen.get('net_capture'), alternate.get('net_capture')
    return b if same and b and (not a or _instant(b['checked_at']) > _instant(a['checked_at']) or
                               (b['checked_at'] == a['checked_at'] and b.get('probe') and not a.get('probe'))) else a


def viewer_net_capture(value):
    capture = validate_net_capture(value)
    if capture is None:
        return None
    probe = capture.pop('probe', None)
    if probe or 'probe_available' in capture:
        capture['probe_available'] = bool(probe) or capture.get('probe_available') is True
    return capture


def net_capture_label(row):
    if type(row.get('net_medals')) is int:
        return '取得済み（0枚）' if row['net_medals'] == 0 else '取得済み'
    if row.get('source_site') in ('anaslo', 'site777'):
        # グラフから推定差枚を付けた台（アナスロ・サイトセブン）は、正確な差枚とは分けて「推定あり」。
        return '出典に差枚なし（推定あり）' if row.get('net_estimate') else '出典に差枚なし'
    return {'missing_series': '日別の系列なし', 'empty': '元数値が空', 'short_series': '元数値の点が不足',
            'invalid_points': '元数値の形式不正', 'invalid_net': '差枚の範囲不正',
            'invalid_response': '応答の形式不正', 'network': '差枚の通信失敗',
            'not_ready': 'サイトの通信準備前'}.get((row.get('net_capture') or {}).get('reason'), '未取得（理由未記録）')
