"""週イベント履歴の基準、編集、バックアップ共通処理。数値記録には触れない。"""
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import re
import unicodedata

STORE = 'nagamachiminami'
KINDS = ('4台構成', '半列', 'バラエティ')
ASSET = Path(__file__).resolve().parents[1] / 'database_android/assets/event_history.json'
FILE_NAME = 'database-event-history.json'
FORMAT = 'database-event-history'


def day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('日付の形式が違います。')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('日付の形式が違います。')
    return parsed


def stamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('編集時刻が読めません。')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('編集時刻に時差がありません。')
    return parsed


def text(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 300 and not any(ord(c) < 32 for c in value)


def machine(raw, symbols, results=True):
    if not isinstance(raw, dict) or not text(raw.get('name')):
        raise ValueError('機種名が読めません。')
    if type(raw.get('count')) is not int or not 1 <= raw['count'] <= 9999:
        raise ValueError('機種の台数が読めません。')
    if raw.get('record_name') is not None and not text(raw['record_name']):
        raise ValueError('対応する保存名が読めません。')
    cleaned = {k: raw[k] for k in ('name', 'count')}
    cleaned['record_name'] = raw.get('record_name')
    if results:
        values = raw.get('results')
        if not isinstance(values, list) or len(values) != 7 or any(not isinstance(v, str) or v not in ['', *symbols] for v in values):
            raise ValueError('結果記号の形式が違います。')
        cleaned['results'] = list(values)
    return cleaned


def validate_base(raw):
    if not isinstance(raw, dict) or raw.get('version') != 2 or raw.get('store') != STORE:
        raise ValueError('履歴ファイルの形式が違います。')
    symbols = raw.get('symbols')
    if not isinstance(symbols, list) or not symbols or any(not text(v) or len(v) > 16 for v in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError('記号一覧の形式が違います。')
    if not isinstance(raw.get('weeks'), list):
        raise ValueError('週の一覧がありません。')
    occupied, weeks = set(), []
    for w in raw['weeks']:
        if not isinstance(w, dict) or w.get('type') not in KINDS:
            raise ValueError('イベント種別が読めません。')
        first, last = day(w.get('from')), day(w.get('to'))
        if first.weekday() != 0 or last - first != timedelta(days=6) or first in occupied:
            raise ValueError('週の開始日・期間が重複または不正です。')
        occupied.add(first)
        if not isinstance(w.get('machines'), list):
            raise ValueError('機種一覧がありません。')
        machines = [machine(m, symbols) for m in w['machines']]
        if len({m['name'] for m in machines}) != len(machines):
            raise ValueError('週の機種名が重複しています。')
        weeks.append(dict(type=w['type'], **{'from': first.isoformat(), 'to': last.isoformat()}, machines=machines))
    blanks = raw.get('user_blank_days', [])
    if not isinstance(blanks, list):
        raise ValueError('空欄の日付が読めません。')
    for d in blanks:
        day(d)
    return dict(version=2, store=STORE, symbols=list(symbols), user_blank_days=blanks, weeks=weeks)


def load_base(path=ASSET):
    try:
        return validate_base(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, TypeError, ValueError) as error:
        raise ValueError(f'履歴ファイルを読めません：{error}') from error


def empty_edits():
    return dict(format=FORMAT, version=1, cells=[], weeks=[], links=[])


def validate_envelope(raw):
    """バックアップの外枠だけを検証する。個別の古い編集で台データを止めない。"""
    if not isinstance(raw, dict) or raw.get('format') != FORMAT or raw.get('version') != 1:
        raise ValueError('履歴編集の形式が違います。')
    if any(not isinstance(raw.get(k, []), list) or len(raw.get(k, [])) > 30000 for k in ('cells', 'weeks', 'links')):
        raise ValueError('履歴編集の一覧が読めません。')


def clean_edits(raw, base, rejected_items=None):
    validate_envelope(raw)
    out, rejected = empty_edits(), 0
    def reject(group, value):
        nonlocal rejected
        rejected += 1
        if rejected_items is not None:
            rejected_items.setdefault(group, []).append(deepcopy(value))
    weeks = {(w['type'], w['from']): w for w in base['weeks']}
    occupied = {w['from']: w['type'] for w in base['weeks']}
    for w in raw.get('weeks', []):
        try:
            if w.get('store') != STORE or w.get('type') != 'バラエティ' or type(w.get('removed', False)) is not bool:
                raise ValueError()
            first, lineup = day(w.get('week')), day(w.get('lineup_day'))
            stamp(w.get('updated_at'))
            if first.weekday() or not 0 <= (lineup - first).days <= 6 or occupied.get(w['week'], 'バラエティ') != 'バラエティ':
                raise ValueError()
            machines = [machine(m, base['symbols'], False) for m in w['machines']]
            if not machines or any(m['count'] > 3 for m in machines) or len({m['name'] for m in machines}) != len(machines):
                raise ValueError()
            entry = dict(store=STORE, type='バラエティ', week=w['week'], lineup_day=w['lineup_day'],
                         machines=machines, updated_at=w['updated_at'], removed=w.get('removed', False))
            key = ('バラエティ', w['week'])
            prior = next((v for v in out['weeks'] if v['week'] == w['week']), None)
            if prior is not None:
                if stamp(entry['updated_at']) < stamp(prior['updated_at']):
                    continue
                out['weeks'].remove(prior)
            out['weeks'].append(entry)
            occupied[w['week']] = 'バラエティ'
            weeks[key] = dict(machines=machines)
        except (AttributeError, KeyError, TypeError, ValueError):
            reject('weeks', w)
    all_names = {m['name'] for w in weeks.values() for m in w['machines']}
    for group in ('cells', 'links'):
        entries = {}
        for c in raw.get(group, []):
            try:
                if c.get('store') != STORE or not text(c.get('machine')):
                    raise ValueError()
                stamp(c.get('updated_at'))
                scoped = group == 'cells' or 'week' in c or 'type' in c
                entry = {k: c[k] for k in ('store', 'machine', 'updated_at')}
                if scoped:
                    if c.get('type') not in KINDS:
                        raise ValueError()
                    first = day(c.get('week'))
                    w = weeks[(c['type'], c['week'])]
                    if not any(m['name'] == c['machine'] for m in w['machines']):
                        raise ValueError()
                    entry.update(type=c['type'], week=c['week'])
                elif c['machine'] not in all_names:
                    raise ValueError()
                if group == 'cells':
                    if not 0 <= (day(c.get('day')) - first).days <= 6 or not isinstance(c.get('value'), str) or c['value'] not in ['', *base['symbols']]:
                        raise ValueError()
                    entry.update(day=c['day'], value=c['value'])
                else:
                    if c.get('record_name') is not None and not text(c['record_name']):
                        raise ValueError()
                    entry['record_name'] = c.get('record_name')
                entry['device'] = c.get('device') if c.get('device') in ('pc', 'android', 'shared') else 'pc'
                key = edit_key(group, entry)
                if key not in entries or stamp(entry['updated_at']) >= stamp(entries[key]['updated_at']):
                    entries[key] = entry
            except (AttributeError, KeyError, TypeError, ValueError):
                reject(group, c)
        out[group] = list(entries.values())
    return out, rejected


def edit_key(group, c):
    if group == 'links' and 'week' not in c and 'type' not in c:
        return (c['store'], '', '', c['machine'])
    fields = ('store', 'type', 'week') + (() if group == 'weeks' else ('machine',)) + (('day',) if group == 'cells' else ())
    return tuple(c[k] for k in fields)


def merge_edits(stored, incoming, base):
    """固定済みの週の食い違いは除外し、ほかの台データの取り込みを妨げない。"""
    validate_envelope(incoming)
    orphans = {}
    current, old_bad = clean_edits(stored, base, orphans)
    fixed = {edit_key('weeks', w): w for w in current['weeks']}
    incoming_weeks, bad_weeks = clean_edits(dict(empty_edits(), weeks=incoming.get('weeks', [])), base)
    accepted = dict(fixed)
    skipped_weeks = 0
    for w in incoming_weeks['weeks']:
        key = edit_key('weeks', w)
        old = fixed.get(key)
        if old is not None and any(old[k] != w[k] for k in ('lineup_day', 'machines', 'removed')):
            skipped_weeks += 1
            continue
        if old is None:
            accepted[key] = w
    # 新旧の構成ではなく、採用した構成に対してセルを検証する。
    context = dict(incoming, weeks=list(accepted.values()))
    fresh, new_bad = clean_edits(context, base)
    out, changed, conflicts = empty_edits(), 0, 0
    for group in ('weeks', 'cells', 'links'):
        entries = {edit_key(group, c): c for c in current[group]}
        source = [w for k,w in accepted.items() if k not in fixed] if group == 'weeks' else fresh[group]
        for c in source:
            key = edit_key(group, c)
            old = entries.get(key)
            take = old is None or stamp(c['updated_at']) >= stamp(old['updated_at'])
            differs = old is not None and any(old.get(k) != c.get(k) for k in ('value', 'record_name'))
            if take and c != old:
                if differs and old.get('device') != c.get('device'):
                    conflicts += 1
                entries[key] = c
                changed += 1
        # 保存済みの基準外の編集は、表示からは除いてもバックアップには残す。
        # ただし同じ場所により新しい正しい編集があれば、古い方は役目を終えたので捨てる（警告が残り続けないように）。
        out[group] = [entries[k] for k in sorted(entries)] + [
            o for o in orphans.get(group, []) if not superseded(group, o, entries)]
    return out, changed, conflicts, old_bad + bad_weeks + new_bad, skipped_weeks


def superseded(group, orphan, entries):
    """基準外の編集 orphan と同じ場所に、同時刻以降の正しい編集があるか。場所を読めない原文は残す。"""
    try:
        valid = entries.get(edit_key(group, orphan))
        return valid is not None and stamp(valid['updated_at']) >= stamp(orphan['updated_at'])
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def materialize(base, edits):
    state, rejected = clean_edits(edits, base)
    weeks = {(w['type'], w['from']): deepcopy(w) for w in base['weeks']}
    for w in state['weeks']:
        key = (w['type'], w['week'])
        if w['removed']:
            weeks.pop(key, None)
        else:
            weeks[key] = dict(type=w['type'], **{'from': w['week'], 'to': (day(w['week']) + timedelta(days=6)).isoformat()},
                              lineup_day=w['lineup_day'], machines=[dict(m, results=[''] * 7) for m in w['machines']])
    # 機種共通の対応を先に、週ごとの上書きを後に適用する。
    for c in sorted(state['links'], key=lambda c: ('week' in c, edit_key('links', c))):
        targets = [weeks.get((c['type'], c['week']))] if 'week' in c else weeks.values()
        for w in targets:
            if w is None:
                continue
            for m in w['machines']:
                if m['name'] == c['machine']:
                    m['record_name'] = c['record_name']
    for c in state['cells']:
        w = weeks.get((c['type'], c['week']))
        if w is None:
            continue
        for m in w['machines']:
            if m['name'] == c['machine']:
                m['results'][(day(c['day']) - day(c['week'])).days] = c['value']
    return sorted(weeks.values(), key=lambda w: w['from'], reverse=True), rejected


def saved_name(item, names):
    if item.get('record_name') is not None:
        return item['record_name'] if item['record_name'] in names else None
    normalize = lambda s: ' '.join(s.replace('+', ' ').split())
    hits = [n for n in names if normalize(n) == normalize(item['name'])]
    return hits[0] if len(hits) == 1 else None


def machine_candidates(name, names):
    loose = lambda s: ''.join(unicodedata.normalize('NFKC', s).replace('/', '').split())
    return sorted(names, key=lambda n: (loose(n) != loose(name), n))


def variety_week_lineup(records, monday):
    """対象週とその前13暦日で最多台数の8割以上ある、週内の最初の日を選ぶ。"""
    first = day(monday)
    if first.weekday():
        raise ValueError('週開始日は月曜日を選んでください。')
    indexed = {}
    for r in records:
        d = day(r['day'])
        if r['store'] == STORE and -13 <= (d - first).days <= 6:
            indexed.setdefault(r['day'], {})[(r['machine'], r['rack'])] = r
    usual = max((len(v) for v in indexed.values()), default=0)
    candidates = sorted(d for d, rows in indexed.items() if monday <= d <= (first + timedelta(days=6)).isoformat() and len(rows) >= usual * .8)
    if not candidates:
        raise ValueError('対象週の記録が足りません。週表を作成しませんでした。')
    counts = {}
    for r in indexed[candidates[0]].values():
        counts[r['machine']] = counts.get(r['machine'], 0) + 1
    machines = [dict(name=n, record_name=n, count=c) for n, c in sorted(counts.items()) if c <= 3]
    if not machines:
        raise ValueError('対象日にバラエティの機種がありません。')
    peak = {}
    for rows in indexed.values():
        per_day = {}
        for name, _rack in rows:
            per_day[name] = per_day.get(name, 0) + 1
        for name, count in per_day.items():
            peak[name] = max(peak.get(name, 0), count)
    doubtful = [m['name'] for m in machines if peak.get(m['name'], 0) > 3]
    return candidates[0], machines, doubtful


SHORTFALL_DAYS = 30


def capture_shortfall(records, lineup_day):
    """分類日の保存台数が、前後 SHORTFALL_DAYS 日で最も多い日の8割に届かなければ (分類日の台数, その最多) を返す。

    variety_week_lineup の8割は「週と前13日」の中での比較なので、その期間がまるごと取り込み不足
    （例：2026-09-14〜21 は1日14〜68台、9/22以降は372台）だと素通りする。届いていれば None。"""
    center = day(lineup_day)
    counts = {}
    for r in records:
        if r['store'] == STORE and abs((day(r['day']) - center).days) <= SHORTFALL_DAYS:
            counts.setdefault(r['day'], set()).add((r['machine'], r['rack']))
    usual = max((len(v) for v in counts.values()), default=0)
    found = len(counts.get(lineup_day, ()))
    return (found, usual) if found < usual * .8 else None
