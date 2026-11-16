# 入れ替え直後の機種の前向き検証の計画（2026-11-16 固定、Claude）

利用者「両方進める」（2026-11-16、`NEXT_DAY_FABLE_REVIEW_20261116.md` の案A）、主の判定の単位は「3店まとめ」（同日、利用者の選択）。**この計画は、前向きの期間の結果を見る前に固定した。** 規則・物差し・判定の基準を途中で変えない。変えるときは利用者に相談し、変えた日以降を新しい検証として数え直す。

- 本番の候補・採点・画面・元データは変えない。差が確かめられたときだけ、「導入2〜7日目の機種」を出すか（出す画面も）を利用者と決める。台の順位の式は変えない。
- 判定のスクリプト：`../outputs/new-machine-forward-20261116/review.py`（試験 `test_review.py` 8件。リポジトリ外なので、全文をこの文書の末尾に写した）。固定時の指紋（sha256）：`review.py` = `a1436c2fd603d155e6cab46b34e12368e42b86d2a5779c6be19bd62720d13e39`、`test_review.py` = `979792002c31dbedbaccc0f0c7a9b9d7de45bcd3faf1c962cdd2411aefabe9de`。
- 計画の前に見たもの：新しく入った機種の名前・台数・導入日と、稼働（ゲーム数）の合計だけ（`../outputs/fable-next-day-20261116/out-count.txt`、`names-past.txt`）。当たり・プラス率は見ていない。

## 規則（1つ）

|規則|対象の日|対象の機種|
|---|---|---|
|N1|導入2〜7日目（導入日の翌日から6日間）|その店に新しく入った機種の全台|

- **新しく入った機種**：その店で、その日より前の28日間に同じ名前の行が1つも無い機種。名前は日次学習と同じそろえ方（`daily_learning_names.learning_machine`。P-STATIONの名前の変わり目をそろえる）。
  - その日の取り込み台数が、直前14日の中央値の8割未満なら導入日に数えない（取り込みの欠け）。
  - 店のデータが導入日の28日前からあること。
  - ★・☆を外した名前が前の28日にあれば、新しい機種に数えない（同じ機種を別に置いた台）。
  - 名前だけ替わった機種は、成績を見る前に、利用者が `names` の一覧（当たりは出さない）を見て `renamed.json` に書いて外す。
- **回**：店×導入日。同じ店で、最初の導入日から3日以内の導入は同じ回にまとめる。各機種の窓は、その機種自身の導入日から数える。
- **比べる相手**：同じ店で、回の導入日の28日前より前からある機種（ほかの回の新しい機種は除く）のうち、窓A・窓Bの両方に有効な台があるもの。

## 物差し

- 台：`daily_learning.valid()` を通る台（回転数1以上）。当たり＝BB＋RB。
- 窓A＝導入日の翌日から6日間（2〜7日目）。窓B＝導入日の14日後から14日間（15〜28日目）。
- 機種ごと：ln（窓Aの当たり÷ゲーム数 ÷ 窓Bの当たり÷ゲーム数）。どちらかの窓で当たりが30回未満なら、その機種は判定不能。
- **回のスコア＝新しい機種の重み付き平均 − 比べる相手の重み付き平均**（重みは窓A・Bの当たりの合計）。0＝ほかの機種と同じ動き。新しい機種が1つも測れない、または比べる相手が3機種未満なら、その回は判定不能として数えるだけ。
- 条件に使う副：プラス率の形（窓Aの新しい機種−窓Aの比べる相手）−（窓Bの新しい機種−窓Bの比べる相手）。台日で合算し、どれかが20台日未満なら出さない。
- 参考に出すだけ：窓Aの1台あたりのゲーム数の比（新しい機種÷比べる相手）、4台以上の機種だけのスコア、1〜3台の機種だけのスコア、店舗ごとの比。

## 判定（1回だけ）

- 前向きの対象：導入日 **2026-11-16〜2027-02-22**。判定は **2027-03-29以降に1回だけ** `review.py forward`（それより前は実行を拒む。2回目も止まる）。途中の成績は見ない。
- **主の判定は3店まとめ**：回のスコアの平均と、回を単位にした両側95%のt区間。比＝exp（平均）。
  - **強い（対象に入れる候補）**：区間の下限が0を超え、比が1.05倍以上、プラス率の形の平均が0以上。
  - **弱い（参考）**：区間の上限が0未満、比が0.95倍以下、プラス率の形の平均が0以下。当たり回数の比は、よく回される時期ほど低く出る偏りがあるので、「避ける」注記には使わず、利用者に報告するだけ。
  - それ以外：差を確認できず。
  - 測れた回が6回未満なら「判定保留」。導入日を **2027-04-19** まで延ばし、**2027-05-24以降に1回だけ** `review.py extended`。延長でも足りなければ「判定できず」で終える。
- 店舗ごと（参考、判定には使わない）：測れた回が3回以上の店だけ、両側98.33%（3店舗のボンフェローニ）のt区間。
- 判定の前に、利用者に `review.py names --period forward` の一覧を見てもらい、名前だけ替わった機種を `renamed.json` に書く。

## 参考：計画の前の期間（判定には使わない）

- 導入日 2026-08-03〜11-03。`review.py past` は **2026-12-01以降に1回だけ**（11/2・11/3の回の窓Bが11/30に終わるため）。回ごとのばらつきの大きさを確かめるためだけに使い、前向きの規則・基準・期間は変えない。
- 一覧（`names-past.txt`、45機種）：店のデータが28日前から無いので、幸町・P-STATIONの8/3・8/17と長町南の10/20より前は入らない。P-STATIONの9/7の回は窓Aがアナスロ由来の行（無効扱い）なので判定不能になる見込み。P-STATIONの9/25「沖ドキ!GOLD-30」（1台、取り込み元が替わった日）は、名前の違いかを利用者に確かめる。

## 見分けられる差と限界

- 見分けられる差（概算）：回ごとのばらつきを6%と仮定すると、3店まとめ（約20回）で約4%、店舗ごと（約7回）で約1割。
- AT機の当たり回数は、打たれ方・天井で動く。新台は抽選で座れないことがある。店が運用を変えれば効かなくなる。物差しは設定・収支ではない。
- 2週おきの月曜の入れ替えが続かなければ、回数が足りなくなる。
- 窓Bは導入15〜28日目なので、その間に次の入れ替えがあっても、比べる相手からは新しい機種を外してある。

## 付録：review.py の全文（固定時）

ファイルが失われたときの写し。指紋は上のとおり。

```python
"""入れ替え直後の機種（導入2〜7日目）は当たりやすいかの前向き検証（計画：リポジトリの NEW_MACHINE_PLAN_20261116.md）。

2026-11-16 に結果を見る前に固定した。規則・物差し・判定の基準を変えるときは、計画書と同じく利用者に相談し、
変えた日以降を新しい検証として数え直す（この版の判定には混ぜない）。

使い方（database フォルダで）：
  新しく入った機種の一覧（当たりは読まない。いつでもよい）：
    .venv/Scripts/python.exe ../../outputs/new-machine-forward-20261116/review.py names
  過去の確認（参考。2026-12-01 以降に1回だけ）：
    .venv/Scripts/python.exe ../../outputs/new-machine-forward-20261116/review.py past
  前向きの判定（2027-03-29 以降に1回だけ）：
    .venv/Scripts/python.exe ../../outputs/new-machine-forward-20261116/review.py forward
  延長（前向きで判定保留のときだけ。2027-05-24 以降に1回だけ）：
    .venv/Scripts/python.exe ../../outputs/new-machine-forward-20261116/review.py extended
結果は同じフォルダの result-<mode>.json と result-<mode>.txt。2回目は止まる。
名前だけ替わった機種は、成績を見る前に renamed.json（[{"store":…, "intro":…, "machine":…}]）に書いて外す。
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))

# ---- 固定した条件（計画書と同じ） ----
PERIODS = {
    'past': (('2026-08-03', '2026-11-03'), '2026-12-01'),       # 参考（計画の前に件数だけ見た期間）
    'forward': (('2026-11-16', '2027-02-22'), '2027-03-29'),    # 判定
    'extended': (('2026-11-16', '2027-04-19'), '2027-05-24'),   # 前向きで判定保留のときだけ
}
NEW_DAYS = 28            # これより前の28日に同じ名前の行が無ければ「新しく入った機種」
GAP_RATIO = 0.8          # 取り込みが欠けた日（直前14日の台数の中央値の8割未満）は導入日に数えない
MERGE_DAYS = 3           # 同じ店で、最初の導入日から3日以内の導入は同じ回
WINDOW_A = (1, 6)        # 導入日の翌日から6日間（導入2〜7日目）
WINDOW_B = (14, 27)      # 導入日の14日後から14日間（導入15〜28日目）
MIN_HITS = 30            # 機種ごと・窓ごとの当たりの下限
MIN_COMPARE = 3          # 比べる相手の機種の下限
MIN_PLUS = 20            # プラス率の形を出す下限（台日）
MIN_EPISODES = 6         # 3店まとめの判定に要る回
MIN_STORE_EPISODES = 3   # 店舗ごと（参考）に要る回
LIFT_UP, LIFT_DOWN = 1.05, 0.95
STORES = ('nagamachiminami', 'saiwaichou', 'pscube:c740601:20')
NAMES = {'nagamachiminami': '長町南', 'saiwaichou': '幸町', 'pscube:c740601:20': 'P-STATION'}


def shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


# ---- t分布（scipy を使わない） ----
def _t_cdf(x, df):
    if x == 0:
        return .5
    # 正則化不完全ベータ関数を数値積分で（df が小さくても足りる精度）
    t = df / (df + x * x)
    a, b = df / 2, .5
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    n = 4000
    # u^(a-1) (1-u)^(b-1) を 0..t で積分。u = t*v^2 と置いて端の発散を消す（b=.5 側は u→1 で t<1 なので有限）
    total = 0.
    for i in range(n + 1):
        v = i / n
        u = t * v * v
        f = 2 * t * v * math.exp((a - 1) * math.log(u) + (b - 1) * math.log1p(-u)) if 0 < u < 1 else 0.
        total += f * (1 if i in (0, n) else 4 if i % 2 else 2)
    ib = total / (3 * n) / math.exp(ln_beta)
    return 1 - ib / 2 if x > 0 else ib / 2


def t_quantile(p, df):
    lo, hi = 0., 50.
    for _ in range(60):
        mid = (lo + hi) / 2
        if _t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def t_interval(values, conf):
    n = len(values)
    m = statistics.mean(values)
    if n < 2:
        return m, None, None
    se = statistics.stdev(values) / math.sqrt(n)
    q = t_quantile(1 - (1 - conf) / 2, n - 1)
    return m, m - q * se, m + q * se


# ---- データ ----
def load(data_dir, last_day):
    sys.path.insert(0, str(Path(data_dir).resolve().parent))
    from daily_learning import outcome, valid
    from daily_learning_names import learning_machine
    from daily_learning_runtime import load_inputs
    rows, _ = load_inputs(data_dir, shift(last_day, 1))
    out = []
    for r in rows:
        if r['store'] not in STORES:
            continue
        ok = bool(valid(r))
        out.append(dict(store=r['store'], day=r['day'], machine=learning_machine(r['store'], r['machine']),
                        rack=str(r.get('rack')), valid=ok,
                        games=float(r['games']) if ok else 0.,
                        hits=float((r.get('bb') or 0) + (r.get('rb') or 0)) if ok else 0.,
                        plus=outcome(r) if ok else None))
    return out


def index(rows):
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r['store']][r['day']].append(r)
    return by


def base_name(machine):
    return str(machine).replace('★', '').replace('☆', '').strip()


def introductions(by, first, last, renamed=()):
    """{store: [(導入日, 機種, その日の台数)]}。renamed は外す (store, intro, machine)。"""
    skip = {(x['store'], x['intro'], x['machine']) for x in renamed}
    out = {}
    for store, days in by.items():
        ds = sorted(days)
        if not ds:
            continue
        start = ds[0]
        names = {d: {r['machine'] for r in days[d]} for d in ds}
        counts = {d: len(days[d]) for d in ds}
        found = []
        for i, d in enumerate(ds):
            if not first <= d <= last or shift(start, NEW_DAYS) > d:     # 店のデータが導入日の28日前からあること
                continue
            recent = [counts[x] for x in ds[max(0, i - 14):i]]
            if recent and counts[d] < GAP_RATIO * statistics.median(recent):
                continue
            before = set().union(*(names[x] for x in ds[:i] if x >= shift(d, -NEW_DAYS)))
            plain = {base_name(x) for x in before}
            for m in sorted(names[d] - before):
                # ★付きは同じ機種を別に置いた台（10/25の報告「★付きは別機種」）。★を外した名前が前の28日にあれば新しくない
                if (store, d, m) not in skip and base_name(m) not in plain:
                    found.append((d, m, sum(1 for r in days[d] if r['machine'] == m)))
        out[store] = found
    return out


def episodes(intros):
    """同じ店で、最初の導入日から MERGE_DAYS 日以内の導入を1回にまとめる。"""
    out = []
    for store, found in intros.items():
        current = None
        for d, m, n in sorted(found):
            if current is None or d > shift(current['intro'], MERGE_DAYS):
                current = dict(store=store, intro=d, machines=[])
                out.append(current)
            current['machines'].append(dict(machine=m, intro=d, racks=n))
    return out


def window_sums(days, machine, intro, window):
    hits = games = plus = known = 0.
    racks = 0
    for k in range(window[0], window[1] + 1):
        for r in days.get(shift(intro, k), []):
            if r['machine'] != machine or not r['valid']:
                continue
            hits += r['hits']; games += r['games']; racks += 1
            if r['plus'] is not None:
                known += 1; plus += r['plus']
    return dict(hits=hits, games=games, racks=racks, plus=plus, known=known)


def first_seen(days):
    seen = {}
    for d in sorted(days):
        for r in days[d]:
            seen.setdefault(r['machine'], d)
    return seen


def machine_score(a, b):
    if a['hits'] < MIN_HITS or b['hits'] < MIN_HITS or a['games'] <= 0 or b['games'] <= 0:
        return None
    return math.log((a['hits'] / a['games']) / (b['hits'] / b['games']))


def evaluate(rows, period, renamed=()):
    by = index(rows)
    intros = introductions(by, period[0], period[1], renamed)
    new_names = {(s, m) for s, found in intros.items() for _, m, _ in found}
    out = []
    for ep in episodes(intros):
        days = by[ep['store']]
        seen = first_seen(days)
        new, comp = [], []
        for x in ep['machines']:
            a, b = (window_sums(days, x['machine'], x['intro'], w) for w in (WINDOW_A, WINDOW_B))
            day1 = window_sums(days, x['machine'], x['intro'], (0, 0))
            new.append(dict(x, A=a, B=b, day1=day1, score=machine_score(a, b)))
        intro = ep['intro']
        for m, d0 in seen.items():
            if (ep['store'], m) in new_names or d0 > shift(intro, -NEW_DAYS):
                continue
            a, b = (window_sums(days, m, intro, w) for w in (WINDOW_A, WINDOW_B))
            if a['racks'] and b['racks']:
                comp.append(dict(machine=m, A=a, B=b, score=machine_score(a, b)))
        rec = dict(store=ep['store'], intro=intro, new=[dict(machine=x['machine'], intro=x['intro'], racks=x['racks'])
                                                      for x in new])
        good_new = [x for x in new if x['score'] is not None]
        good_comp = [x for x in comp if x['score'] is not None]
        rec['measurable_new'], rec['measurable_compare'] = len(good_new), len(good_comp)
        if not good_new or len(good_comp) < MIN_COMPARE:
            rec['score'] = None
            out.append(rec)
            continue

        def wmean(xs):
            w = [x['A']['hits'] + x['B']['hits'] for x in xs]
            return sum(wi * x['score'] for wi, x in zip(w, xs)) / sum(w)

        rec['score'] = wmean(good_new) - wmean(good_comp)

        def pool(xs, key):
            p = sum(x[key]['plus'] for x in xs); k = sum(x[key]['known'] for x in xs)
            return (p / k if k >= MIN_PLUS else None), k

        (pa_n, _), (pa_c, _), (pb_n, _), (pb_c, _) = pool(new, 'A'), pool(comp, 'A'), pool(new, 'B'), pool(comp, 'B')
        rec['plus_shape'] = (None if None in (pa_n, pa_c, pb_n, pb_c) else (pa_n - pa_c) - (pb_n - pb_c))
        # 参考：1台あたりのゲーム数の比（新しい機種÷比べる相手、窓A）、導入1日目、4台以上とバラエティの別
        ga_n = sum(x['A']['games'] for x in new) / max(1, sum(x['A']['racks'] for x in new))
        ga_c = sum(x['A']['games'] for x in comp) / max(1, sum(x['A']['racks'] for x in comp))
        rec['games_per_rack_ratio_A'] = ga_n / ga_c if ga_c else None
        big = [x for x in good_new if x['racks'] >= 4]
        small = [x for x in good_new if x['racks'] < 4]
        rec['score_4plus'] = wmean(big) - wmean(good_comp) if big else None
        rec['score_variety'] = wmean(small) - wmean(good_comp) if small else None
        out.append(rec)
    return out


def judge(records):
    scored = [r for r in records if r['score'] is not None]
    res = dict(episodes=len(records), measurable=len(scored),
               not_measurable=len(records) - len(scored))
    if len(scored) < MIN_EPISODES:
        res['verdict'] = '判定保留（回数不足）'
    else:
        m, lo, hi = t_interval([r['score'] for r in scored], .95)
        shapes = [r['plus_shape'] for r in scored if r.get('plus_shape') is not None]
        shape = statistics.mean(shapes) if shapes else None
        res.update(lift=math.exp(m), ci=(math.exp(lo), math.exp(hi)), plus_shape=shape, plus_shape_episodes=len(shapes))
        if lo > 0 and math.exp(m) >= LIFT_UP and shape is not None and shape >= 0:
            res['verdict'] = '強い（対象に入れる候補）'
        elif hi < 0 and math.exp(m) <= LIFT_DOWN and shape is not None and shape <= 0:
            res['verdict'] = '弱い（参考。注記には使わない）'
        else:
            res['verdict'] = '差を確認できず'
    stores = {}
    for s in STORES:
        xs = [r['score'] for r in scored if r['store'] == s]
        item = dict(measurable=len(xs))
        if len(xs) >= MIN_STORE_EPISODES:
            m, lo, hi = t_interval(xs, 1 - .05 / 3)
            item.update(lift=math.exp(m), ci=(math.exp(lo), math.exp(hi)))
        stores[s] = item
    res['stores_reference'] = stores
    return res


def names_listing(by, period, renamed):
    """当たりを読まずに、新しく入った機種と、その日に消えた機種を並べる（名前だけの付け替えを見分けるため）。"""
    lines = []
    intros = introductions(by, period[0], period[1], renamed)
    for store, found in intros.items():
        days = by[store]
        for d, m, n in found:
            prev = max((x for x in days if x < d), default=None)
            gone = sorted({r['machine'] for r in days.get(prev, [])} - {r['machine'] for r in days[d]}) if prev else []
            lines.append(f"{NAMES[store]}\t{d}\t{m}\t{n}台\t前日にあって消えた機種：{'、'.join(gone) or 'なし'}")
    return lines


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('names', 'past', 'forward', 'extended'))
    p.add_argument('--data', default='data')
    p.add_argument('--today', default=None, help='試験用。省略時は日本時間の今日')
    p.add_argument('--period', default='forward', help='names のときだけ：past / forward / extended')
    a = p.parse_args(argv)
    today = a.today or datetime.now(JST).date().isoformat()
    renamed_path = HERE / 'renamed.json'
    renamed = json.loads(renamed_path.read_text(encoding='utf-8')) if renamed_path.exists() else []
    if a.mode == 'names':
        period = PERIODS[a.period][0]
        last = min(today, shift(period[1], WINDOW_B[1]))
        rows = load(a.data, shift(last, -1))
        print('\n'.join(names_listing(index(rows), period, renamed)))
        return
    period, opens = PERIODS[a.mode]
    if today < opens:
        raise SystemExit(f'{a.mode} は {opens} 以降に1回だけ（今日 {today}）。途中の成績は見ない。')
    out_json = HERE / f'result-{a.mode}.json'
    if out_json.exists():
        raise SystemExit(f'{out_json.name} があります。判定は1回だけ。')
    if a.mode == 'extended':
        first = json.loads((HERE / 'result-forward.json').read_text(encoding='utf-8'))
        if not first['verdict']['verdict'].startswith('判定保留'):
            raise SystemExit('延長は、前向きの判定が「判定保留」のときだけ。')
    rows = load(a.data, shift(period[1], WINDOW_B[1]))
    rec = evaluate(rows, period, renamed)
    verdict = judge(rec)
    result = dict(mode=a.mode, period=period, run_on=today, renamed=renamed, verdict=verdict, records=rec)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    v = verdict
    lines = [f'{a.mode} 導入日 {period[0]}〜{period[1]}（実行 {today}）',
             f"3店まとめ：{v['verdict']}　{v['measurable']}回（判定不能 {v['not_measurable']}回）"
             + (f"　比 {v['lift']:.3f}倍（95%区間 {v['ci'][0]:.3f}〜{v['ci'][1]:.3f}）"
                f"　プラス率の形 {v['plus_shape'] if v['plus_shape'] is None else round(v['plus_shape'], 4)}"
                if 'lift' in v else '')]
    for s, item in v['stores_reference'].items():
        extra = (f"　比 {item['lift']:.3f}倍（98.33%区間 {item['ci'][0]:.3f}〜{item['ci'][1]:.3f}）"
                 if 'lift' in item else '　回数不足')
        lines.append(f"  参考 {NAMES[s]}：{item['measurable']}回{extra}")
    (HERE / f'result-{a.mode}.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
```
