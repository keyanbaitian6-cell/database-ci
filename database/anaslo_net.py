"""アナスロ（P-STATION）で補った台の推定差枚（2026-11-06 利用者「全部のデータすり合わせて誤差20枚程度に収まるように頑張って」
「入れる画面を相談」→ Android・iPhone・PCの閲覧と共有カレンダー、確かでない台は※、合計・順位にも入れる。AT機などは確かな台だけ）。

アナスロのグラフ（日別ページの Chart.js）は、ゼロ線 y=312 が全グラフ共通で、座標はサイト側で台ごとの目盛りをかけたあとの
ピクセル。P’s CUBE の本当の差枚と突き合わせると（2026-10-01〜11-05、36日）、目盛りは段 k で決まる：
その日の振れの最大（グラフの点の間に隠れた山を含む）が 1000(k-1)〜1000k 枚なら、500(k+1) 枚を 90 ピクセル。
グラフの点は1日9〜16点なので、本当の山が点の間に隠れ、段を形だけでは決めきれない。そこで段 k の候補ごとに
差枚＝終点(px)×500(k+1)/90 を出し、次の3つを掛け合わせて、いちばんありそうな段を選ぶ。
  1. 見えている山（4px刻み）・山が最後の点か・山の隣への落ち方ごとの、段の出やすさ（P’s CUBE と重なる日の実績）
  2. BB・RB・G数からの推定差枚（機種ごとの最小二乗、ずれ σ＝s√G、t分布 ν=4）との近さ
  3. グラフの上下の動きの合計（枚）の、BB・RB・G数からの予測（対数）との近さ
確からしさ（選んだ段の事後確率）が SURE 以上・段が SURE_MAX_TIER 以下・候補が2つ以上なら確か、それ以外は※（要確認）。
値は「アナスロの集計時点」の推定で、閉店後の差枚とは違うことがある（集計時刻が分からない。利用者「前後50枚は想定の範囲内」）。AT機など（ジャグラー・ハナハナ以外）は
G数の数え方が違い推定が当たりにくいので、確かな台だけ値を付ける。
検証（1日ずつ外して作った式、ノーマル2874台・日）：20枚以内 91.6%、確からしさ0.9以上（68%の台）で 99.3%。
AT機など（5002台・日）：確からしさ0.9以上（31%の台）で 97.5%。詳しくは AI_COLLABORATION.md 2026-11-06（夜）。

数値（段の出やすさ・機種ごとの式）は anaslo_net_model.json。作り直し：
  database/.venv/Scripts/python.exe database/anaslo_net.py --fit   （P’s CUBE の DB を読み取り専用で開き、
  html_converter/data/downloaded_htmls の P-STATION の日別HTMLと突き合わせる。サイトには接続しない）
推定は numpy を使わない（変換アプリの Python でも動く）。
"""
from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / 'anaslo_net_model.json'
METHOD = 'anaslo-graph-v1'
SURE = 0.9
BIN = 4
TAU = 6.0
NU = 4.0
TV_WEIGHT = 1.0
# 段の候補の上限。14 だと大きな振れで候補が1つしか残らず、確からしさ1.0のまま2510枚外れた例があった
# （Codex の独立検証、2026-11-06 `../outputs/anaslo-net-astra-20261106/報告.md` 6章）。上限を広げ、確かと言うのは
# 段が SURE_MAX_TIER 以下・候補が2つ以上のときだけにする。上限を超える振れは今まで通り付けない。
MAX_TIER = 40
SURE_MAX_TIER = 12
ZERO_Y = 312.0
NORMAL_SERIES = ('ジャグラー', 'ハナハナ')


def is_normal(name: str) -> bool:
    text = unicodedata.normalize('NFKC', str(name or ''))
    return any(w in text for w in NORMAL_SERIES)


def ratio(k: int) -> float:
    """段 k の1ピクセルあたりの枚数。"""
    return 500 * (k + 1) / 90


def upper(k: int) -> float:
    return 180 * k / (k + 1)


def lower(k: int) -> float:
    return 180 * (k - 1) / (k + 1)


def pixels(graph: dict | None) -> list[float] | None:
    """アナスロのグラフ（source_graph）をゼロ線からの高さ（上が正）にする。形が違えば None。"""
    if not isinstance(graph, dict) or graph.get('kind') != 'source_coordinates' or graph.get('zero_y') != ZERO_Y:
        return None
    points = graph.get('points')
    if not isinstance(points, list) or not points:
        return None
    ys = []
    for p in points:
        if not (isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)):
            return None
        ys.append(ZERO_Y - float(p[1]))
    return ys


def features(ys: list[float]) -> tuple[int, bool, int]:
    peak_i = max(range(len(ys)), key=lambda j: abs(ys[j]))
    neighbours = [abs(ys[peak_i] - ys[j]) for j in (peak_i - 1, peak_i + 1) if 0 <= j < len(ys)]
    steep = min(neighbours) if neighbours else 0.0
    return int(max(abs(v) for v in ys) // BIN), peak_i == len(ys) - 1, min(int(steep // 15), 3)


def _key(f) -> str:
    return f'{f[0]}|{int(f[1])}|{f[2]}'


def total_variation(ys: list[float]) -> float:
    return sum(abs(b - a) for a, b in zip(ys, ys[1:]))


def _prob(model, k, f) -> float:
    coarse = model['prior_coarse'].get(str(f[0]), {})
    tot_c = sum(coarse.values())
    base = (coarse.get(str(k), 0) + 0.3) / (tot_c + 3)
    full = model['prior'].get(_key(f), {})
    tot = sum(full.values())
    return (full.get(str(k), 0) + 3.0 * base) / (tot + 3.0)


_MODEL = None


def load_model(path: Path = MODEL_PATH) -> dict:
    global _MODEL
    if _MODEL is None or path != MODEL_PATH:
        model = json.loads(Path(path).read_text(encoding='utf-8'))
        if model.get('method') != METHOD:
            raise ValueError('推定差枚の数値ファイルの形式が違います。')
        if path != MODEL_PATH:
            return model
        _MODEL = model
    return _MODEL


def estimate(record: dict, model: dict | None = None) -> dict | None:
    """アナスロで補った台（source_site=anaslo）の推定差枚 {'value', 'sure', 'method'}。付けられなければ None。"""
    if record.get('source_site') != 'anaslo' or record.get('net_medals') is not None:
        return None
    ys = pixels(record.get('source_graph'))
    games, bb, rb = record.get('games'), record.get('bb'), record.get('rb')
    if ys is None or not all(type(v) is int and v >= 0 for v in (games, bb, rb)):
        return None
    model = model or load_model()
    counts = model['counts'].get(record.get('machine'))
    if not counts:
        return None
    a, b, c, s = counts
    est = a * bb + b * rb + c * games
    sigma = max(s * math.sqrt(max(games, 100)), 1.0)
    t0, t1, t2, t3, s_tv = model['tv']
    mu = t0 * bb + t1 * rb + t2 * games + t3
    tv_px = total_variation(ys)
    normal = is_normal(record.get('machine'))
    f = features(ys)
    peak, end = max(abs(v) for v in ys), ys[-1]
    scores = []
    for k in range(1, MAX_TIER + 1):
        if peak > upper(k) + 1:
            continue
        p = _prob(model, k, f)
        if peak < lower(k) - 1:
            p *= math.exp(-(lower(k) - peak) / TAU)
        net = end * ratio(k)
        z = (net - est) / sigma
        score = math.log(p) - (NU + 1) / 2 * math.log(1 + z * z / NU)
        if normal and tv_px > 0 and s_tv > 0:   # 動きの合計の予測はノーマルの実績で作ったので、ノーマルだけ
            score -= TV_WEIGHT * 0.5 * ((math.log(tv_px * ratio(k) + 50) - mu) / s_tv) ** 2
        scores.append((score, net, k))
    if not scores:
        return None
    top = max(score for score, _, _ in scores)
    total = sum(math.exp(score - top) for score, _, _ in scores)
    best = max(scores)
    confidence = math.exp(best[0] - top) / total
    sure = confidence >= SURE and best[2] <= SURE_MAX_TIER and len(scores) >= 2
    if not sure and not normal:
        return None   # AT機などは確かな台だけ（2026-11-06 利用者「確からしい台だけ出す」）
    return {'value': int(round(best[1])), 'sure': sure, 'method': METHOD}


def valid(value) -> bool:
    """記録に付いた推定差枚の形（PC・Android・閲覧ページ・共有カレンダーで同じ検査）。"""
    return (isinstance(value, dict) and set(value) == {'value', 'sure', 'method'} and type(value['value']) is int
            and abs(value['value']) <= 1000000 and type(value['sure']) is bool and value['method'] == METHOD)


# ---- 数値の作り直し（--fit。numpy を使う。サイトには接続しない） ----

def fit(db_path: Path, html_dir: Path) -> dict:
    import collections
    import sqlite3

    import numpy as np
    from anaslo_html import parse_html

    con = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)
    truth = collections.defaultdict(dict)
    per_machine = collections.defaultdict(list)
    for (payload,) in con.execute('SELECT payload FROM records'):
        r = json.loads(payload)
        if r.get('source_site') or r.get('net_medals') is None or not r.get('games'):
            continue
        truth[r['day']][int(r['rack'])] = r
        per_machine[r['machine']].append((r['bb'] or 0, r['rb'] or 0, r['games'], r['net_medals']))
    counts = {}
    for machine, rows in per_machine.items():
        if len(rows) < 50:
            continue
        A = np.array([x[:3] for x in rows], float)
        y = np.array([x[3] for x in rows], float)
        coef = np.linalg.lstsq(A, y, rcond=None)[0]
        res = y - A @ coef
        s = math.sqrt(float(np.mean(res ** 2 / np.maximum(A[:, 2], 100))))
        counts[machine] = [round(float(coef[0]), 4), round(float(coef[1]), 4), round(float(coef[2]), 5), round(s, 4)]
    prior = collections.defaultdict(collections.Counter)
    coarse = collections.defaultdict(collections.Counter)
    tv_rows = []
    days = []
    for path in sorted(Path(html_dir).glob('20*-p-station-*.html')):
        day = path.name[:10]
        if day not in truth:
            continue
        days.append(day)
        for a in parse_html(path.read_bytes(), path.name)['records']:
            q = truth[day].get(a['rack'])
            ys = pixels(a.get('graph'))
            if not q or ys is None or abs(ys[-1]) < 8:
                continue
            if q['bb'] != a['bb'] or q['rb'] != a['rb'] or not 0 <= q['games'] - a['games'] <= 1:
                continue   # アナスロが閉店前の途中の値の台は、段が分からないので使わない
            k = max(1, round(q['net_medals'] / ys[-1] * 90 / 500) - 1)
            f = features(ys)
            prior[_key(f)][str(k)] += 1
            coarse[str(f[0])][str(k)] += 1
            if is_normal(q['machine']) and total_variation(ys) > 0:
                tv_rows.append((a['bb'], a['rb'], a['games'], math.log(total_variation(ys) * ratio(k) + 50)))
    X = np.array([[b, r, g, 1] for b, r, g, _ in tv_rows], float)
    y = np.array([v for *_, v in tv_rows], float)
    tv = np.linalg.lstsq(X, y, rcond=None)[0]
    s_tv = float(np.std(y - X @ tv))
    return {'method': METHOD, 'days': [days[0], days[-1], len(days)] if days else [],
            'counts': counts, 'prior': {k: dict(v) for k, v in sorted(prior.items())},
            'prior_coarse': {k: dict(v) for k, v in sorted(coarse.items(), key=lambda x: int(x[0]))},
            'tv': [round(float(v), 6) for v in tv] + [round(s_tv, 6)]}


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--fit']:
        raise SystemExit('使い方：python anaslo_net.py --fit')
    root = Path(__file__).resolve().parent
    model = fit(root / 'data' / 'pscube.sqlite3', root.parent / 'html_converter' / 'data' / 'downloaded_htmls')
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{MODEL_PATH.name}：{model["days"]}、機種 {len(model["counts"])}、段の表 {len(model["prior"])}')
