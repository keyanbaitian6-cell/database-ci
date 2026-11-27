"""日次学習・採用中の候補の表示内容（PCの窓・結果ページ用。Tkに依らない）。

4画面（PC・Android・iPhone閲覧ページ・共有カレンダー）で同じ意味・順序（2026-11-12）。保存済みの selected の台と
順番をそのまま使い、画面側で再学習・再計算しない。Android・閲覧ページは daily_learning_page.dart の DailyView、
共有カレンダーは share_viewer/daily_learning.mjs の dailyView が同じ規則。"""
from datetime import date, datetime, timedelta
import re

from daily_learning import JST

NAMES = {'nagamachiminami': '長町南', 'saiwaichou': '幸町', 'pscube:c740601:20': 'P-STATION'}
WEEK = '月火水木金土日'
IMPORTANT = re.compile('処理失敗|取り込み待ち|同期先|書けません|読めません')
METHOD_TEXT = {
    True: '日次学習版：店舗ごとの判定で、将来の成績による改善を確認したため採用している方式です。',
    False: '従来方式：これまでの翌日候補と同じ選び方です。日次学習版は、将来の成績で改善を確認するまで採用しません。'}
LOAD_ERROR = '日次学習の記録を読めません。PCの自動処理・保存先を確認してください。従来候補は引き続き参考にできます。'


def default_target(now):
    """最初に開く対象日（日本時間）。23:30以降は、その夜に保存される翌日の分（Android・閲覧ページ・共有カレンダーと同じ）。"""
    now = now.astimezone(JST)
    day = now + timedelta(days=1) if (now.hour, now.minute) >= (23, 30) else now
    return day.date().isoformat()


def stale(updated, now):
    """最初に開く対象日の保存時間帯（その前日の23:30から）に入ってから、PCの処理結果が1回も届いていないか。

    2026-11-12：以前は「最終処理の日付が今日でない」で見ていたので、前の晩の23:30台に保存した正しい候補にも、
    0時を過ぎると「本日の処理結果は届いていません」と出ていた（朝にPCを動かさない日は一日中）。"""
    start = datetime.fromisoformat(f'{default_target(now)}T23:30:00+09:00') - timedelta(days=1)
    try:
        at = datetime.fromisoformat(str(updated))
        return at.tzinfo is None or at < start
    except ValueError:
        return True


def date_label(day):
    d = date.fromisoformat(day)
    return f'{d.month}月{d.day}日（{WEEK[d.weekday()]}）'


def time_label(stamp):
    try:
        d = datetime.fromisoformat(str(stamp)).astimezone(JST)
    except (TypeError, ValueError):
        return str(stamp)
    return f'{d.month}月{d.day}日 {d.hour}:{d.minute:02d}'


def status_parts(status, store):
    """状態の文（「長町南：…／幸町：…／同期先…」）を、この店舗の分と全体の分に分ける。"""
    prefixes = [p for k, v in NAMES.items() for p in (k + '：', v + '：')]
    own = (NAMES.get(store, store) + '：', store + '：')
    mine, general = [], []
    for part in (s.strip() for s in str(status or '').split('／')):
        if not part:
            continue
        hit = next((p for p in own if part.startswith(p)), None)
        if hit:
            mine.append(part[len(hit):])
        elif not any(part.startswith(p) for p in prefixes):
            general.append(part)
    return mine, general


def daily_view(doc, store, target, now):
    """表示する中身（4画面で同じ意味・順序。2026-11-12）。保存済みの selected の台と順番をそのまま使い、計算し直さない。"""
    day = next((d for d in doc['days'] if d['target'] == target), None)
    groups = []
    for g in (day or {}).get('groups', []):
        if g['store'] != store:
            continue
        groups.append(dict(name=g['name'], learned=g['active'] == 'learned', status=g['status'],
                           saved=g.get('saved_at') or day['saved_at'],
                           racks=[(int(i[3]), None if i[2] == g['name'] else i[2]) for i in g['selected']]))
    mine, general = status_parts(doc['status'], store)
    alerts = [s for s in mine + general if IMPORTANT.search(s)]
    now = now.astimezone(JST)
    initial = default_target(now)
    if stale(doc['updated_at'], now):
        alerts.append(f'{date_label(initial)}の分の処理結果は届いていません。古い候補をこの日の予測として使わないでください。')
    if target < initial:
        alerts.append(f'{date_label(target)}は過去の対象日です。記録として表示しています。次の営業日の候補として使わないでください。')
    if not groups:
        alerts.append('この日の保存済み候補はありません。データ不足・取り込み待ち・PC停止などを確認してください。')
    machines = sum(g['name'] != 'バラエティ' for g in groups)
    variety = any(g['name'] == 'バラエティ' for g in groups)
    scope = (f'{machines}機種とバラエティ' if machines and variety else 'バラエティ' if variety else f'{machines}機種')
    dates = sorted({initial, target, *(d['target'] for d in doc['days'])}, reverse=True)
    return dict(groups=groups, count=sum(len(g['racks']) for g in groups), scope=scope, alerts=alerts,
                mine=mine, general=general, updated=doc['updated_at'], dates=dates, initial=initial)


CHECKUP_MARKS = {'saved': '○', 'missed': '×', 'pending': '待ち', 'before': '—'}
CHECKUP_NOTES = (
    '○＝その日に予測を保存できた。×＝保存できなかった（PCが止まっていた・取り込み待ちのまま23:30を過ぎた など）。'
    '待ち＝まだ保存できる時間内。—＝日次学習を始める前。',
    '判定不能＝その晩に使った前日データで、差枚もグラフも無く、プラスかどうか決まらない台（有効な台のうち。大当たり0回でグラフ省略の台を除く）。'
    '学習の正解に使えない台です。取りこぼしが減るほど、学習に使えるデータが増えます。',
    '予測と固定した入力だけで数えます。成績（プラス率）はここでは出しません。')


def checkup_view(doc, store):
    """PCの窓の「点検」（2026-11-14）。daily_learning_runtime.checkup の結果を、古い晩→新しい晩の順に並べる。
    点検が無い・形が違うときは None（窓には「次の実行後に出ます」と出す）。"""
    data = doc.get('checkup')
    cells = (data or {}).get('stores', {}).get(store) if isinstance(data, dict) else None
    if not isinstance(cells, list) or not cells:
        return None
    out, saved, expected, racks, unknown, missed = [], 0, 0, 0, 0, []
    for c in cells:
        state = c.get('state')
        if state not in CHECKUP_MARKS:
            return None
        target = str(c.get('target', ''))
        rate = ''
        if state == 'saved':
            saved += 1
            n, u = int(c.get('racks') or 0), int(c.get('unknown') or 0)
            racks, unknown = racks + n, unknown + u
            rate = f'{round(100 * u / n)}%' if n else '—'
        if state in ('saved', 'missed'):
            expected += 1
        if state == 'missed':
            missed.append(target)
        out.append(dict(day=f'{int(target[5:7])}/{int(target[8:10])}', mark=CHECKUP_MARKS[state], state=state, rate=rate))
    summary = f'保存 {saved}/{expected}晩' if expected else '保存の記録はまだありません'
    if racks:
        summary += f'　判定不能 {round(100 * unknown / racks)}%（有効な台 {racks}台のうち {unknown}台）'
    return dict(cells=out, summary=summary, saved=saved, expected=expected, racks=racks, unknown=unknown,
                missed=missed, nights=len(out))
