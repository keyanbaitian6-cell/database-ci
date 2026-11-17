"""店の入れ方のふり返り（全台系・末尾・並び）。PCの窓（store_pattern_ui.py）が使う。

閲覧ページの `database_android/lib/store_pattern.dart` と同じ計算・同じ数字にする（2026-11-18 利用者
「PCでも表示させてほしい」。変えるときは両方）。両方の結果が同じかは、共通の試験データ
`database_android/test/fixtures/store_pattern_cases.json`（このファイルで作った正解）で確かめる。

その日の、プラスで終わった台（勝率と同じ数え方）が、機種（全台系）・末尾・台番の並びに、ランダムに配ったときと
比べてどれだけ偏っていたかを出す。角台は島の配置のデータが無いので出さない。探索の結果であり、翌日候補・採点には
使わない。保存済みのデータだけを読む（サイトへはアクセスしない）。研究の成績は計算しない。

偶然の程度：機種・末尾は超幾何分布の上側確率×比べた組の数（ボンフェローニ）。並びは、プラスの印を台に配り直す
並べ替えを RUN_TRIALS 回行い、いちばん長い並びがこれ以上になる割合。乱数は Park–Miller（48271 を掛けて
2147483647 で割った余り）で、Dart（スマホのブラウザを含む）とPythonで同じ値になる（かけ算が 2^53 を超えない）。
"""
from __future__ import annotations

import math

MIN_SCORED_GAMES = 500       # 採点の下限と同じ（500G以下は除く）
MIN_GROUP = 3                # 比べる組（機種・末尾）に要る台数
MIN_RACKS = 10               # その日を判定するのに要る台数
KNOWN_SHARE = .7             # プラスかどうか分かる台が、稼働した台（500G超）のこの割合に届かない日は判定しない
RUN_TRIALS = 1000
RARE, SOMETIMES, COMMON = '偶然では出にくい', '偶然でもときどき出る', '偶然でもよく出る'

PSCUBE_SUFFIXES = (0, 1, 2, 3, 5, 6, 7, 8)
MERUHEN_SUFFIXES = tuple(range(10))

_VOICED = {'ｳﾞ': 'ヴ', 'ｶﾞ': 'ガ', 'ｷﾞ': 'ギ', 'ｸﾞ': 'グ', 'ｹﾞ': 'ゲ', 'ｺﾞ': 'ゴ', 'ｻﾞ': 'ザ', 'ｼﾞ': 'ジ', 'ｽﾞ': 'ズ',
           'ｾﾞ': 'ゼ', 'ｿﾞ': 'ゾ', 'ﾀﾞ': 'ダ', 'ﾁﾞ': 'ヂ', 'ﾂﾞ': 'ヅ', 'ﾃﾞ': 'デ', 'ﾄﾞ': 'ド', 'ﾊﾞ': 'バ', 'ﾋﾞ': 'ビ',
           'ﾌﾞ': 'ブ', 'ﾍﾞ': 'ベ', 'ﾎﾞ': 'ボ', 'ﾊﾟ': 'パ', 'ﾋﾟ': 'ピ', 'ﾌﾟ': 'プ', 'ﾍﾟ': 'ペ', 'ﾎﾟ': 'ポ'}
_HALF = 'ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝｧｨｩｪｫｬｭｮｯｰ'
_FULL = 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンァィゥェォャュョッー'


def fold_half_width_kana(text):
    """半角カナを全角カナに（Dart `foldHalfWidthKana` と同じ）。"""
    for half, full in _VOICED.items():
        text = text.replace(half, full)
    return text.translate(str.maketrans(_HALF, _FULL))


def chance_of(adjusted):
    return RARE if adjusted < .05 else SOMETIMES if adjusted < .2 else COMMON


def suffixes_for(store):
    return PSCUBE_SUFFIXES if str(store).startswith('pscube:') else MERUHEN_SUFFIXES


def seed(text):
    """店・日からの種（Dart と同じ。UTF-16 の単位で数える）。"""
    value = 0
    data = text.encode('utf-16-le')
    for i in range(0, len(data), 2):
        value = (value * 31 + int.from_bytes(data[i:i + 2], 'little')) % 2147483647
    return value or 1


class ParkMiller:
    def __init__(self, state):
        self.state = state % 2147483647 or 1

    def next_int(self, n):
        self.state = self.state * 48271 % 2147483647
        return self.state % n


def _log_factorials(n):
    values = [0.0] * (n + 1)
    for i in range(2, n + 1):
        values[i] = values[i - 1] + math.log(i)
    return values


def upper_tail(table, population, successes, draws, observed):
    """全体 population 台のうちプラス successes 台から draws 台を選んで、プラスが observed 台以上になる確率。"""
    choose = lambda n, k: table[n] - table[k] - table[n - k]
    high = min(draws, successes)
    low = max(observed, draws - (population - successes))
    if low > high:
        return 0.0
    total = choose(population, draws)
    return min(1.0, sum(math.exp(choose(successes, x) + choose(population - successes, draws - x) - total)
                        for x in range(low, high + 1)))


def _longest_run(racks, plus):
    best, current = [], []
    for rack, won in zip(racks, plus):
        if not won:
            current = []
            continue
        if current and rack != current[-1] + 1:
            current = []
        current = current + [rack]
        if len(current) > len(best):
            best = current
    return best


def _longest_run_length(racks, plus):
    best = current = 0
    for i, won in enumerate(plus):
        if not won:
            current = 0
            continue
        current = current + 1 if current and racks[i] == racks[i - 1] + 1 else 1
        best = max(best, current)
    return best


def store_pattern_day(store, day, rows, won, trials=RUN_TRIALS):
    """rows：その店・その日の台（dict、rack・machine・games）。won(row)：プラスなら True、マイナス False、分からなければ None。"""
    by_rack = {}
    for r in rows:
        if r.get('store', store) == store and r.get('day', day) == day:
            by_rack[r['rack']] = r          # 同じ台が2回あれば後の記録
    played = [r for r in by_rack.values() if (r.get('games') or 0) > MIN_SCORED_GAMES]
    usable = sorted(((r, won(r)) for r in played), key=lambda x: x[0]['rack'])
    usable = [(r, w) for r, w in usable if w is not None]
    total = len(usable)
    plus = sum(1 for _, w in usable if w)
    table = _log_factorials(total)

    def groups(grouped):
        kept = [(label, items) for label, items in grouped if len(items) >= MIN_GROUP]
        out = []
        for label, items in kept:
            hits = sum(1 for _, w in items if w)
            p = upper_tail(table, total, plus, len(items), hits)
            out.append(dict(label=label, plus=hits, total=len(items), p=p, compared=len(kept),
                            adjusted=min(1.0, p * len(kept))))
        return out

    by_machine = {}
    for r, w in usable:
        by_machine.setdefault(fold_half_width_kana(r['machine']), []).append((r, w))
    machines = groups(list(by_machine.items()))
    machines.sort(key=lambda g: (g['adjusted'], -(g['plus'] / g['total'])))
    suffixes = groups([(f'末尾{s}', [(r, w) for r, w in usable if r['rack'] % 10 == s])
                       for s in suffixes_for(store)])
    racks = [r['rack'] for r, _ in usable]
    labels = [w for _, w in usable]
    run = None
    if plus:
        best = _longest_run(racks, labels)
        count = 0
        if plus < total:
            rng = ParkMiller(seed(f'{store}|{day}'))
            shuffled = list(labels)
            for _ in range(trials):
                for i in range(len(shuffled) - 1, 0, -1):
                    j = rng.next_int(i + 1)
                    shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
                if _longest_run_length(racks, shuffled) >= len(best):
                    count += 1
        run = dict(racks=best, p=(count + 1) / (trials + 1) if plus < total else 1.0)
    for group in machines + suffixes:
        group['chance'] = chance_of(group['adjusted'])
    if run:
        run['chance'] = chance_of(run['p'])
    result = dict(store=store, day=day, plus=plus, total=total, played=len(played),
                  excluded=len(by_rack) - total, machines=machines, suffixes=suffixes, run=run)
    result['usable'] = usable_day(result)
    result['highlights'] = highlights(result)
    return result


def usable_day(r):
    """判定できる日か：台が少ない・全部プラス・全部マイナス・プラスか分かる台が少ない（アナスロ補完の日など）日は判定しない。"""
    return (r['total'] >= MIN_RACKS and 0 < r['plus'] < r['total']
            and r['total'] >= KNOWN_SHARE * r['played'])


def highlights(r):
    if not r['usable']:
        return []
    rate = r['plus'] / r['total']
    out = [f"全台系：{g['label']}（{g['plus']}/{g['total']}）" for g in r['machines']
           if g['chance'] == RARE and g['plus'] / g['total'] > rate]
    out += [f"{g['label']}（{g['plus']}/{g['total']}）" for g in r['suffixes']
            if g['chance'] == RARE and g['plus'] / g['total'] > rate]
    run = r['run']
    if run and run['chance'] == RARE:
        out.append(f"並び：{run_label(run)}（{len(run['racks'])}台）")
    return out


def run_label(run):
    racks = run['racks']
    return f'{racks[0]}番' if len(racks) == 1 else f'{racks[0]}〜{racks[-1]}番'


def pscube_won(row):
    """P’s CUBE（P-STATION）の台：元グラフの確定差枚、無ければ確かめた推定差枚の符号（Dart `SlotRecord.won` と同じ）。"""
    if not row.get('games'):
        return None
    net = row.get('net_medals')
    if not isinstance(net, int) or isinstance(net, bool):
        net = None
        estimate = row.get('net_estimate')
        if isinstance(estimate, dict):
            import anaslo_net
            import site777_net
            site = row.get('source_site')
            ok = (site == 'anaslo' and anaslo_net.valid(estimate)) or (site == 'site777' and site777_net.valid(estimate))
            if ok and isinstance(estimate.get('value'), int):
                net = estimate['value']
    return None if net is None else net > 0
