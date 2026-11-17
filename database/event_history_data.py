"""週イベント履歴の基準、編集、バックアップ共通処理。数値記録には触れない。"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import math
import re
import unicodedata

STORE = 'nagamachiminami'
SAIWAI_STORE = 'saiwaichou'
VARIETY_KEY = 'saiwaichou_variety'
KINDS = ('4台構成', '半列', 'バラエティ')
# PCで作れる週表の種類（2026-11-17 利用者「PCで作れるように」。今までは長町南の4台構成・半列は画像から書き写した
# 元データ（2026-10-11の週まで）だけで、PCで足せるのはバラエティだけだった）。4台構成は設置ちょうど4台の機種。
FOUR_RACKS = '4台構成'


def creatable_kinds(location):
    return ('バラエティ',) if location == SAIWAI_STORE else ('バラエティ', FOUR_RACKS)


def week_machines_fit(kind, machines, location):
    """PCで作った週表の機種の台数が、その種類に合うか。"""
    if kind == FOUR_RACKS:
        return all(m['count'] == 4 for m in machines)
    return all(m['count'] <= (2 if location == SAIWAI_STORE else 3) for m in machines)
ASSET = Path(__file__).resolve().parents[1] / 'database_android/assets/event_history.json'
FILE_NAME = 'database-event-history.json'
FORMAT = 'database-event-history'


def saiwaichou_base():
    """幸町はPCで作成する週表だけ。長町南の画像転記と記号を混ぜない。"""
    return dict(version=2, store=SAIWAI_STORE, symbols=['優', '良'], user_blank_days=[], weeks=[])


def store_edits(raw, location):
    if location == STORE:
        return raw
    if location != SAIWAI_STORE:
        raise ValueError('対応していない店舗です。')
    return raw.get(VARIETY_KEY, empty_edits())


def store_kinds(location):
    return ('バラエティ',) if location == SAIWAI_STORE else KINDS


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
    if not isinstance(raw, dict) or raw.get('version') != 2 or raw.get('store') not in (STORE, SAIWAI_STORE):
        raise ValueError('履歴ファイルの形式が違います。')
    symbols = raw.get('symbols')
    location = raw['store']
    if location == SAIWAI_STORE and symbols != ['優', '良']:
        raise ValueError('幸町の評価は優・良だけです。')
    if not isinstance(symbols, list) or not symbols or any(not text(v) or len(v) > 16 for v in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError('記号一覧の形式が違います。')
    if not isinstance(raw.get('weeks'), list):
        raise ValueError('週の一覧がありません。')
    occupied, weeks = set(), []
    for w in raw['weeks']:
        if not isinstance(w, dict) or w.get('type') not in store_kinds(location):
            raise ValueError('イベント種別が読めません。')
        first, last = day(w.get('from')), day(w.get('to'))
        if first.weekday() != 0 or last - first != timedelta(days=6) or first in occupied:
            raise ValueError('週の開始日・期間が重複または不正です。')
        occupied.add(first)
        if not isinstance(w.get('machines'), list):
            raise ValueError('機種一覧がありません。')
        machines = [machine(m, symbols) for m in w['machines']]
        if location == SAIWAI_STORE and any(m['count'] > 2 for m in machines):
            raise ValueError('幸町のバラエティは1〜2台機種です。')
        if len({m['name'] for m in machines}) != len(machines):
            raise ValueError('週の機種名が重複しています。')
        weeks.append(dict(type=w['type'], **{'from': first.isoformat(), 'to': last.isoformat()}, machines=machines))
    blanks = raw.get('user_blank_days', [])
    if not isinstance(blanks, list):
        raise ValueError('空欄の日付が読めません。')
    for d in blanks:
        day(d)
    return dict(version=2, store=location, symbols=list(symbols), user_blank_days=blanks, weeks=weeks)


def load_base(path=ASSET):
    try:
        return validate_base(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, TypeError, ValueError) as error:
        raise ValueError(f'履歴ファイルを読めません：{error}') from error


def empty_edits():
    return dict(format=FORMAT, version=1, cells=[], weeks=[], links=[])


def validate_envelope(raw, *, nested=False):
    """バックアップの外枠だけを検証する。個別の古い編集で台データを止めない。"""
    if not isinstance(raw, dict) or raw.get('format') != FORMAT or raw.get('version') != 1:
        raise ValueError('履歴編集の形式が違います。')
    if any(not isinstance(raw.get(k, []), list) for k in ('cells', 'weeks', 'links', 'recommendations', 'recommendation_results')):
        raise ValueError('履歴編集の一覧が読めません。')
    if any(len(raw.get(k, [])) > 30000 for k in ('cells', 'weeks', 'links', 'recommendations', 'recommendation_results')):
        raise ValueError('履歴編集の保存件数の上限（各30,000件）を超えるため保存できません。')
    if VARIETY_KEY in raw:
        if nested:
            raise ValueError('幸町の履歴を入れ子にできません。')
        validate_envelope(raw[VARIETY_KEY], nested=True)


def clean_edits(raw, base, rejected_items=None):
    validate_envelope(raw)
    location = base['store']
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
            kind = w.get('type')
            if w.get('store') != location or kind not in creatable_kinds(location) or type(w.get('removed', False)) is not bool:
                raise ValueError()
            first, lineup = day(w.get('week')), day(w.get('lineup_day'))
            stamp(w.get('updated_at'))
            # 同じ週に別の種類の表は作れない（1週に1種類）。
            if first.weekday() or not 0 <= (lineup - first).days <= 6 or occupied.get(w['week'], kind) != kind:
                raise ValueError()
            machines = [machine(m, base['symbols'], False) for m in w['machines']]
            if not machines or not week_machines_fit(kind, machines, location) or len({m['name'] for m in machines}) != len(machines):
                raise ValueError()
            entry = dict(store=location, type=kind, week=w['week'], lineup_day=w['lineup_day'],
                         machines=machines, updated_at=w['updated_at'], removed=w.get('removed', False))
            key = (kind, w['week'])
            prior = next((v for v in out['weeks'] if v['week'] == w['week'] and v['type'] == kind), None)
            if prior is not None:
                if stamp(entry['updated_at']) < stamp(prior['updated_at']):
                    continue
                out['weeks'].remove(prior)
            out['weeks'].append(entry)
            occupied[w['week']] = kind
            weeks[key] = dict(machines=machines)
        except (AttributeError, KeyError, TypeError, ValueError):
            reject('weeks', w)
    all_names = {m['name'] for w in weeks.values() for m in w['machines']}
    for group in ('cells', 'links'):
        entries = {}
        for c in raw.get(group, []):
            try:
                if c.get('store') != location or not text(c.get('machine')):
                    raise ValueError()
                stamp(c.get('updated_at'))
                scoped = group == 'cells' or 'week' in c or 'type' in c
                entry = {k: c[k] for k in ('store', 'machine', 'updated_at')}
                if scoped:
                    if c.get('type') not in store_kinds(location):
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
    if 'recommendations' in raw and location == STORE:
        from recommendations import merge
        out['recommendations'] = merge([], raw['recommendations'], strict=False)
    if 'recommendation_results' in raw and location == STORE:
        from recommendations import merge_results
        out['recommendation_results'] = merge_results(raw['recommendation_results'])
    return out, rejected


def edit_key(group, c):
    if group == 'links' and 'week' not in c and 'type' not in c:
        return (c['store'], '', '', c['machine'])
    fields = ('store', 'type', 'week') + (() if group == 'weeks' else ('machine',)) + (('day',) if group == 'cells' else ())
    return tuple(c[k] for k in fields)


def merge_edits(stored, incoming, base, *, count_stored_rejected=True):
    """固定済みの週の食い違いは除外し、ほかの台データの取り込みを妨げない。"""
    validate_envelope(incoming)
    if 'unreadable_raw' in stored or 'unreadable_raw' in incoming:
        raise ValueError('履歴の原文が読めません。原本とバックアップを保持してください。')
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
    rejected = (old_bad if count_stored_rejected else 0) + bad_weeks + new_bad
    if base['store'] == STORE and (VARIETY_KEY in stored or VARIETY_KEY in incoming):
        variety, added, differing, bad, skipped = merge_edits(
            stored.get(VARIETY_KEY, empty_edits()), incoming.get(VARIETY_KEY, empty_edits()),
            saiwaichou_base(), count_stored_rejected=count_stored_rejected)
        out[VARIETY_KEY] = variety
        changed += added
        conflicts += differing
        rejected += bad
        skipped_weeks += skipped
    if base['store'] == STORE and ('recommendations' in stored or 'recommendations' in incoming):
        from recommendations import merge
        old_plans = stored.get('recommendations', [])
        out['recommendations'] = merge(old_plans, incoming.get('recommendations', []))
        changed += sum(p not in old_plans for p in out['recommendations'])
    if base['store'] == STORE and ('recommendation_results' in stored or 'recommendation_results' in incoming):
        from recommendations import merge_results
        old_results = stored.get('recommendation_results', [])
        out['recommendation_results'] = merge_results(old_results,incoming.get('recommendation_results',[]))
        changed += sum(r not in old_results for r in out['recommendation_results'])
    validate_envelope(out)
    return out, changed, conflicts, rejected, skipped_weeks


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


def variety_week_lineup(records, monday, location=STORE, kind='バラエティ'):
    """対象週とその前13暦日で最多台数の8割以上ある、週内の最初の日を選ぶ。
    kind が4台構成なら、その日に設置ちょうど4台の機種（doubtful は、周辺の日に4台あったのにその日は3台以下＝取りこぼしの疑い）。"""
    first = day(monday)
    if first.weekday():
        raise ValueError('週開始日は月曜日を選んでください。')
    indexed = {}
    for r in records:
        d = day(r['day'])
        if r['store'] == location and -13 <= (d - first).days <= 6:
            indexed.setdefault(r['day'], {})[(r['machine'], r['rack'])] = r
    usual = max((len(v) for v in indexed.values()), default=0)
    candidates = sorted(d for d, rows in indexed.items() if monday <= d <= (first + timedelta(days=6)).isoformat() and len(rows) >= usual * .8)
    if not candidates:
        raise ValueError('対象週の記録が足りません。週表を作成しませんでした。')
    counts = {}
    for r in indexed[candidates[0]].values():
        counts[r['machine']] = counts.get(r['machine'], 0) + 1
    max_racks = 2 if location == SAIWAI_STORE else 3
    if kind == FOUR_RACKS:
        machines = [dict(name=n, record_name=n, count=c) for n, c in sorted(counts.items()) if c == 4]
        if not machines:
            raise ValueError('対象日に設置4台の機種がありません。')
    else:
        machines = [dict(name=n, record_name=n, count=c) for n, c in sorted(counts.items()) if c <= max_racks]
        if not machines:
            raise ValueError('対象日にバラエティの機種がありません。')
    peak = {}
    for rows in indexed.values():
        per_day = {}
        for name, _rack in rows:
            per_day[name] = per_day.get(name, 0) + 1
        for name, count in per_day.items():
            peak[name] = max(peak.get(name, 0), count)
    if kind == FOUR_RACKS:
        doubtful = [n for n, c in sorted(counts.items()) if c < 4 and peak.get(n, 0) == 4]
    else:
        doubtful = [m['name'] for m in machines if peak.get(m['name'], 0) > max_racks]
    return candidates[0], machines, doubtful


SHORTFALL_DAYS = 30


def capture_shortfall(records, lineup_day, location=STORE):
    """分類日の保存台数が、前後 SHORTFALL_DAYS 日で最も多い日の8割に届かなければ (分類日の台数, その最多) を返す。

    variety_week_lineup の8割は「週と前13日」の中での比較なので、その期間がまるごと取り込み不足
    （例：2026-09-14〜21 は1日14〜68台、9/22以降は372台）だと素通りする。届いていれば None。"""
    center = day(lineup_day)
    counts = {}
    for r in records:
        if r['store'] == location and abs((day(r['day']) - center).days) <= SHORTFALL_DAYS:
            counts.setdefault(r['day'], set()).add((r['machine'], r['rack']))
    usual = max((len(v) for v in counts.values()), default=0)
    found = len(counts.get(lineup_day, ()))
    return (found, usual) if found < usual * .8 else None


# バラエティの週表に自動で入れる顔文字（利用者指定、2026-10-21）。記号は基準JSONの既存の5つのうち4つを使う。
# 当日差枚（機種の全台の合計）が +3000枚以上＝目がハート、1000〜2999＝笑顔、0〜999＝目を閉じた顔、マイナス＝苦しい顔。
NET_FACES = ((3000, '😍'), (1000, '😀'), (0, '😌'))
NET_FACE_LOSS = '🥶'


def net_face(total):
    """機種のその日の合計差枚に対応する顔文字。"""
    for floor, face in NET_FACES:
        if total >= floor:
            return face
    return NET_FACE_LOSS


def net_grade(total):
    """幸町：2,500枚以上は優、0枚以上2,500枚未満は良。対象外は空欄。"""
    if not isinstance(total, (int, float)) or isinstance(total, bool) or not math.isfinite(total) or total < 0:
        return None
    return '優' if total >= 2500 else '良'


def machine_day_totals(db, first, last, location=STORE):
    """{(日, 機種名): (合計差枚, 台数)}。差枚の分からない台・数値異常の台が1台でもあれば合計は None。
    差枚は画面と同じ rack_net（ジャグラーオンラインの差枚、無ければ推定差枚）。"""
    from core import rack_net, implausible_numbers
    query = ("SELECT day, machine, json_extract(payload,'$.games'), json_extract(payload,'$.bb'), json_extract(payload,'$.rb'),"
             " json_extract(payload,'$.max_hold'), json_extract(payload,'$.graph_measurement'),"
             " json_extract(payload,'$.jo_net') FROM days"
             " WHERE store=? AND day BETWEEN ? AND ? AND json_valid(payload)")
    totals, counts = {}, {}
    for d, name, games, bb, rb, max_hold, measurement, jo_net in db.db.execute(query, (location, first, last)):
        try:
            measurement = json.loads(measurement) if measurement else None
        except ValueError:
            measurement = None
        row = {'jo_net': jo_net, 'graph_measurement': measurement, 'max_hold': max_hold, 'games': games,
               'bb': bb, 'rb': rb, 'store': location, 'day': d}
        net = None if implausible_numbers({'games': games, 'bb': bb, 'rb': rb, 'max_hold': max_hold}) else rack_net(row)[0]
        key = (d, name)
        counts[key] = counts.get(key, 0) + 1
        if net is None or totals.get(key, 0) is None:
            totals[key] = None
        else:
            totals[key] = totals.get(key, 0) + net
    return {k: (totals[k], counts[k]) for k in totals}


def machine_day_nets(db, first, last, location=STORE, expected_counts=None):
    """{(日, 機種名): 合計差枚}。全台の差枚が分かる機種・日だけ（一部の台しか分からない合計は出さない）。
    数値異常の台がある機種・日も出さない。"""
    return {k: total for k, (total, count) in machine_day_totals(db, first, last, location).items()
            if total is not None and (expected_counts is None or count == expected_counts.get(k[1]))}


def item_day_net(item, d, totals, names_by_day):
    """週表の機種のその日の合計差枚。保存名が決まり、全台の差枚が分かり、台数が週表と同じときだけ。"""
    name = saved_name(item, names_by_day.get(d, set()))
    total, count = totals.get((d, name), (None, 0)) if name else (None, 0)
    return total if count == item['count'] else None


def auto_grades(week, totals, names_by_day):
    """幸町：空欄のマスに表示する優・良 {(機種名, 日): 記号}（保存しない。手入力の優・良が優先）。"""
    first = day(week['from'])
    out = {}
    for item in week['machines']:
        for i, current in enumerate(item['results']):
            d = (first + timedelta(days=i)).isoformat()
            grade = net_grade(item_day_net(item, d, totals, names_by_day)) if current == '' else None
            if grade:
                out[(item['name'], d)] = grade
    return out


# 幸町の赤字（利用者指定、2026-10-29）：今日を除いた直前5暦日に、機種の合計差枚が+800枚を超えた日が無い機種。
# 記録の無い日・差枚不明の日は「超えていない」と数える。手入力の優（2,500枚以上の意味）は超えた日と数える。
GAP_NET = 800
GAP_DAYS = 5


def today_jst():
    return datetime.now(timezone(timedelta(hours=9))).date()


def gap_end(last_record_day, today=None):
    """赤字判定の最終日：表示週の最後の記録日。ただし今日（日本時間）は含めない。表示週に記録が無ければ None。"""
    if last_record_day is None:
        return None
    return min(last_record_day, ((today or today_jst()) - timedelta(days=1)).isoformat())


def gap_range(end_day):
    """赤字判定に使う最初と最後の日。"""
    return (day(end_day) - timedelta(days=GAP_DAYS - 1)).isoformat(), end_day


def grade_gap(weeks, item, end_day, totals, names_by_day):
    """end_day までの5暦日に、合計差枚が+800枚を超えた日も手入力の優の日も無ければ True。
    前週にまたがる日も、同じ機種名・明示的な保存名の週表から優を探す。"""
    if end_day is None:
        return False
    end = day(end_day)
    for offset in range(GAP_DAYS):
        d = (end - timedelta(days=offset)).isoformat()
        total = item_day_net(item, d, totals, names_by_day)
        if total is not None and total > GAP_NET:
            return False
        for w in weeks:
            if w['type'] != 'バラエティ' or not w['from'] <= d <= w['to']:
                continue
            saved = next((m for m in w['machines'] if m['name'] == item['name'] or
                          (item.get('record_name') and m.get('record_name') == item['record_name'])), None)
            if saved and saved['results'][(day(d) - day(w['from'])).days] == '優':
                return False
    return True


def auto_faces(week, nets, names_by_day, symbols, blank_days=(), only_day=None, classify=net_face):
    """週表の空欄のセルに入れる顔文字。戻り値は (入れるセル[(機種名, 日, 記号)], 入れなかった空欄の数)。
    only_day があればその日だけ。入力済みのセルは変えない。その日の記録が無いセルは数えず、記録はあるが差枚の分からない機種・日は空欄のまま数える。"""
    first = day(week['from'])
    cells, skipped = [], 0
    for item in week['machines']:
        for i, current in enumerate(item['results']):
            d = (first + timedelta(days=i)).isoformat()
            if current != '' or d in blank_days or (only_day is not None and d != only_day):
                continue
            name = saved_name(item, names_by_day.get(d, set()))
            if not name:
                continue  # その日の記録が無い（未来の日・取り込み前）。数えない
            total = nets.get((d, name))
            face = classify(total) if total is not None else None
            if face is None or face not in symbols:
                skipped += 1
                continue
            cells.append((item['name'], d, face))
    return cells, skipped
