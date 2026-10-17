"""幸町のジャグラー・ハナハナの翌日候補の並べ方（2026-10-17、NEXT_DAY_MODEL_PLAN_20261017.md）。

利用者「少なくとも14ヶ月分のデータを読み取ったのだから本日分から予想精度はあがることを期待していた」
「一度本当に見直してもらいたい」。14か月分（2025-09〜2026-10）から作ったリッジ回帰の式で、
翌日の当たりの軽さ（同じ機種で回転数が近い台の中の順位）を予想し、その点の高い順に並べる。
2026-01〜10 を月ごとに前へ進めて確かめ、今の並べ方（過去の当たりの軽さの指数）より、選んだ台の
翌日の順位が平均 +0.96（p=0.0005、前半・後半とも上回る）だった（outputs/normal-trends-20261017/claude-v10）。

候補に入れる台の集まり（今の指数が出せる台、4台以上の機種）と台数（上位4分の1）は変えない。
変えるのは並べる順だけ。表示する指数・★注目は今のまま。Android `normal_next_day_model.dart` と同じ。
"""
import math
import re
import unicodedata
from datetime import date

from core import implausible_numbers, percentile
from setting_estimate import SPECS, model_for_machine

METHOD_VERSION = '2026-10-17-saiwaichou-normal-model-1'
STORE = 'saiwaichou'
SERIES = ('ジャグラー', 'ハナハナ')
SHRINK_GAMES = 2000
# 生の重み（標準化を戻した値）。2026-10-16 までの全データ 41,690 件で作った（coefficients.json）。
WEIGHTS = {
    'v0': 0.027311058,
    's': 0.040769933,
    'r': -0.061517979,
    's_last3': 0.011048230,
    's_28': -0.006871832,
    's_long': 0.553817886,
    'r_28': 0.019004669,
    'high_d': -0.440139493,
    'high_12': -0.224611027,
    'since_4_9': -0.256742786,
    'since_10_23': -0.377331771,
    'log_games': -0.153899838,
    'long_play': 0.832684670,
}


NOTE = '幸町のジャグラー・ハナハナは、14か月分（2025年9月〜2026年10月）から作った予想の式（台の長い期間の当たりの軽さ、当日の当たりとREG、回転数、直近に明らかに高かったかなど）の点の高い順に選んでいます。表示の数字は過去の当たりの軽さで、並び順とは違うことがあります。過去に当てはめた確認では、選んだ台の翌日の当たりの軽さ（同じ機種の中の順位）は、今までの選び方より平均で約1高い程度でした。翌日の設定や勝ち負けを示すものではありません。'


def applies(location, machine):
    return location == STORE and any(word in str(machine or '') for word in SERIES)


def _spec(machine):
    key = model_for_machine(machine)
    if key:
        return key
    name = re.sub(r'[\s\-−‐‑–—~〜～_・]+', '', unicodedata.normalize('NFKC', str(machine)).upper())
    # アイムジャグラーEX はネオアイムジャグラーEX と同じ公表確率（北電子の公式表）。
    return 'neo_im_juggler' if name in ('アイムジャグラーEXTP', 'SアイムジャグラーEXTP') else None


def clearly_high(row):
    """3,000回転以上で、BIG・REGから見た設定4以上の確率（等事前）が90%以上。"""
    key = _spec(row.get('machine'))
    g, b, r = row.get('games') or 0, row.get('bb'), row.get('rb')
    if key is None or g < 3000 or g > 20000 or b is None or r is None or b < 0 or r < 0 or b + r > g:
        return False
    ll = [b * math.log(1 / x) + r * math.log(1 / y) + (g - b - r) * math.log1p(-1 / x - 1 / y)
          for _, x, y in SPECS[key][2]]
    peak = max(ll)
    weights = [math.exp(v - peak) for v in ll]
    return sum(weights[3:]) / sum(weights) >= .9


def _rank(row, day_rows, value):
    """同じ日・同じ機種で回転数が半分〜2倍（500回転以上）の台の中の順位（0〜100）。3台未満は None。"""
    if row['games'] < 500 or row.get('bb') is None or row.get('rb') is None:
        return None
    peers = [r for r in day_rows if r['games'] >= 500 and r.get('bb') is not None and r.get('rb') is not None
             and row['games'] / 2 <= r['games'] <= row['games'] * 2]
    if len(peers) < 3:
        return None
    return 100 * percentile(value(row) / row['games'], [value(r) / r['games'] for r in peers])


def _hit(row, day_rows):
    return _rank(row, day_rows, lambda r: r['bb'] + r['rb'])


def _reg(row, day_rows):
    if implausible_numbers(row):
        return None
    clean = [r for r in day_rows if not implausible_numbers(r)]
    return _rank(row, clean, lambda r: r['rb'])


_DAY_CACHE = {}


def _day_values(rows):
    """1日・1機種の台ごとの (s, r, 明らかに高い)。その日の台の数字だけで決まるので、数字が同じなら覚えた値を使う。"""
    key = (rows[0]['machine'], rows[0]['day'], tuple(sorted(
        (int(r['rack']), r['games'], r.get('bb'), r.get('rb'), r.get('max_hold')) for r in rows)))
    hit = _DAY_CACHE.get(key)
    if hit is None:
        hit = {}
        for r in rows:
            shrink = r['games'] / (r['games'] + SHRINK_GAMES)
            h, g = _hit(r, rows), _reg(r, rows)
            hit[int(r['rack'])] = (None if h is None else (h - 50) * shrink,
                                   None if g is None else (g - 50) * shrink, clearly_high(r))
        if len(_DAY_CACHE) > 20000:
            _DAY_CACHE.clear()
        _DAY_CACHE[key] = hit
    return hit


def history_values(machine_rows, day):
    """同じ店・同じ機種の day までの記録について、台ごとの (日, 当たりの軽さの寄与 s, REGの寄与 r, 明らかに高い) を
    新しい日から並べる。"""
    by_day = {}
    for r in machine_rows:
        if r['day'] <= day:
            by_day.setdefault(r['day'], []).append(r)
    per_rack = {}
    for d, rows in by_day.items():
        for rack, (s, reg, high) in _day_values(rows).items():
            per_rack.setdefault(rack, []).append((d, s, reg, high))
    for values in per_rack.values():
        values.sort(key=lambda v: v[0], reverse=True)
    return per_rack


def features(per_rack, row, v0_raw):
    """``per_rack`` は [history_values] の結果（row の日まで）。検証のスクリプト（claude-v10/model.py）と同じ材料。"""
    t = date.fromisoformat(row['day']).toordinal()
    s_all, recent3, s28, r28 = [], [], [], []
    high_12, last_high, seen_7 = False, None, False
    today_s = today_r = None
    for d, s, reg, high in per_rack.get(int(row['rack']), []):  # 新しい日から
        ago = t - date.fromisoformat(d).toordinal()
        if ago == 0:
            today_s, today_r = s, reg
        if s is not None:
            s_all.append(s)
            if ago < 7 and len(recent3) < 3:
                recent3.append(s)
            if ago < 28:
                s28.append(s)
        if reg is not None and ago < 28:
            r28.append(reg)
        if high and 1 <= ago <= 2:
            high_12 = True
        if high and last_high is None:
            last_high = ago
        if 1 <= ago <= 7:
            seen_7 = True
    mean = lambda v: sum(v) / len(v) if v else 0.0
    return dict(
        v0=v0_raw - 50, s=today_s or 0.0, r=today_r or 0.0,
        s_last3=mean(recent3), s_28=mean(s28), s_long=sum(s_all) / (len(s_all) + 10), r_28=mean(r28),
        high_d=float(clearly_high(row)), high_12=float(high_12),
        since_4_9=float(last_high is not None and 4 <= last_high <= 9),
        since_10_23=float(last_high is not None and 10 <= last_high <= 23),
        new_rack=float(not seen_7),
        log_games=math.log(max(row['games'], 1) / 4000), long_play=float(row['games'] >= 7000),
    )


def score(feature_values):
    return sum(WEIGHTS[k] * feature_values[k] for k in WEIGHTS)
