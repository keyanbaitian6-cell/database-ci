# 幸町の土日は設定が低いのか、打たれ方の違いか（過去データで1回、2026-11-16 固定、Claude）

利用者「両方進める」（2026-11-16、`NEXT_DAY_FABLE_REVIEW_20261116.md` の案B）。**この計画は、実データの結果を見る前に固定した。** 実データで流すのは1回だけ。基準を後から変えない。

- 本番の候補・採点・画面（曜日傾向の注記 `database/normal_day_context.py` を含む）・元データは変えない。結果の使い方（下の「結果の使い方」）は、利用者と決めてから。
- スクリプト：`../outputs/weekend-setting-20261116/analyze.py`（リポジトリ外。全文をこの文書の末尾に写した）。固定時の指紋（sha256）：`719df1f7151a1328183924bbd7ed272f71392802d929f900bf262227f8be4307`。
- 計画の前に見たもの：既存の報告の数字（土日の勝率が平日より5〜6ポイント低い、合算の設定位置が0.10〜0.11低い。`../outputs/normal-trends-20261017/`）と、幸町の店全体の稼働（土日は平日の約1.4〜1.5倍）。今回の物差しでの実データの値は見ていない。

## なぜ今までの数字では分からないか

2,000G以上の台だけを見ると、土日は悪い台も長く打たれて2,000Gに届く。全ゲームの合算でも、良い台ほど長く打たれるので同じ向きに動く。どちらも、設定の配分が同じでも土日が低く出る。

台ごとの（回転数・BB・RB）の尤度は、やめ方が当たりの出方だけで決まるなら、設定によらない係数が掛かるだけで、打ち切り方に左右されない。そこで、**区分ごとに設定1〜6の割合を最尤で推定し、その割合での平均の合算確率**を比べる。

## 入力

|項目|内容|
|---|---|
|対象|幸町のジャグラー・ハナハナのうち、確率表のある機種（`database/setting_estimate.py` の表：マイジャグラーV・VI、ネオアイムジャグラーEX、ハナハナホウオウ天翔、キングハナハナ、ドラゴンハナハナ閃光）。BT機のニューキングハナハナVは除く|
|期間|2025-09-15〜2026-11-12。7/31までは分析用JSON（`html_converter/data/normal_analysis/saiwaichou/`、`daily_learning_archive.load`）、8/1からは原本DB（`database.sqlite3`、読み取り専用のコピー）。同じ台・日は原本DBを優先|
|台|`daily_learning.valid()` を通り、回転数・BB・RBが整数で BB+RB≤回転数 の台×日。回転数の下限は付けない|
|区分|平日／土日祝（祝日・振替休日を含む。一覧は10/23の分析と同じに 2026-11-03 を足したもの）。年末年始（12/29〜1/3）とお盆（8/13〜16）は主の比較から除き、参考に別に出す|

## 物差し

- 機種ごと・区分ごとに、設定1〜6の割合をEMで推定（初めは均等、変化が1e-9未満で止める）。その割合で平均の合算確率（BB＋RBの確率の平均）を出す。
- 機種ごと：ln（土日祝 ÷ 平日）。区分ごとに100台日未満の機種は入れない。
- **スコア＝機種ごとの値を、その機種の台日数（両区分の合計）で重み付けた平均**。比＝exp（スコア）。
- 区間：暦週（月曜始まり）を単位にしたブートストラップ1,999回（乱数の種 20261116）、95%。各回、週の重みでEMをやり直す。
- 参考に出すだけ：機種ごとの比、RBだけの比、設定4以上の割合の推定、2,000G以上の台だけの合算の比（今までの物差し）、3期間（2025-09-15〜2026-01-31・2026-02-01〜06-30・07-01〜11-12）、年末年始・お盆÷平日。

## 先に流した試験（合成データ、実データの前）

`analyze.py synthetic`（結果 `synthetic.json`）。3機種・47台・420日。平日は「500G以上でハマり350Gならやめる」、土日祝は「ハマり900Gまで粘る」をまねた。

|確かめたこと|結果|
|---|---|
|(a) 配分が同じでも、2,000G以上の台の合算は土日が低く出る|0.86〜0.89倍（済）|
|(b) 配分が同じなら、この推定は「打たれ方の違い」と判定する|0.9995倍（95%区間 0.9936〜1.0046）（済）|
|(c) 土日だけ低い設定を増やすと、「設定が低い」と判定する|0.968倍（区間 0.962〜0.973。真の値 0.964〜0.970）（済）|

合成データの区間の幅は±0.5%ほど。実データの台数は同じくらいなので、約1%の差まで見分けられる見込み。

## 判定（1回だけ）

- **設定が低い**：区間の上限が1倍未満で、比が0.99倍以下。
- **打たれ方の違い**：区間が0.99〜1.01倍の内側。
- それ以外：判断保留。

## 結果の使い方（どちらも表示の変更なので、出す画面を利用者と決めてから）

- 設定が低い → 土日祝は幸町のジャグラー・ハナハナの候補を減らす・出さない案を作る。変える前に、2026-11-13〜2027-02-28 で同じ計算をもう1回流し（2027-03-01以降に1回）、向きが同じことを確かめる。
- 打たれ方の違い → 今の曜日傾向の注記の文を直す案を作る（「土日に設定が低い証拠は無い」）。
- 判断保留 → 今の注記のまま。

## 限界

- メーカーの表どおりに当たる前提。サイトのBB・RBの数え方がずれていても、同じ機種の区分どうしを比べるので、ずれの多くは打ち消し合う。
- 客が、当日の出方以外の手がかりで高設定の台を見分けて座っていると偏る（これまでの検証では、前日までの成績は翌日をほぼ読めていない）。0Gの台（打たれなかった台）は入らない。
- 平均の合算確率の差は、設定の配分の違いを1つの数にまとめたもの。どの台に入っているかは分からない。P-STATION・長町南・AT機には当てはめない。

## 付録：analyze.py の全文（固定時）

```python
"""幸町のジャグラー・ハナハナ：土日祝は設定が低いのか、打たれ方の違いか（計画：リポジトリの WEEKEND_SETTING_PLAN_20261116.md）。

2026-11-16 に結果を見る前に固定した。考え方：台ごとの（回転数・BB・RB）の尤度は、打ち手がいつやめたかに左右されない
（やめ方が当たりの出方だけで決まるなら、設定によらない係数が掛かるだけ）。そこで、機種ごと・区分（平日／土日祝）ごとに
設定1〜6の割合を最尤（EM）で推定し、その割合での平均の合算確率を比べる。

使い方（database フォルダで）：
  合成データの試験（先に必ず。通らなければ real は動かない）：
    .venv/Scripts/python.exe ../../outputs/weekend-setting-20261116/analyze.py synthetic
  実データで1回だけ：
    .venv/Scripts/python.exe ../../outputs/weekend-setting-20261116/analyze.py real
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# ---- 固定した条件（計画書と同じ） ----
FIRST, LAST = '2025-09-15', '2026-11-12'
DB_FROM = '2026-08-01'                          # これより前は分析用JSON、以降は原本DB（同じ台・日はDBを優先）
STORE = 'saiwaichou'
EXCLUDE_MODELS = ('new_king_v',)                # BT機
# 10/23の分析（supplements.py）の一覧に 2026-11-03 を足したもの（内閣府の国民の祝日）
HOLIDAYS = set('2025-09-15 2025-09-23 2025-10-13 2025-11-03 2025-11-23 2025-11-24 2026-01-01 2026-01-12 2026-02-11 '
               '2026-02-23 2026-03-20 2026-04-29 2026-05-03 2026-05-04 2026-05-05 2026-05-06 2026-07-20 2026-08-11 '
               '2026-09-21 2026-09-22 2026-09-23 2026-10-12 2026-11-03'.split())
MIN_ROWS = 100                                  # 機種ごと・区分ごとの台日の下限
BOOT = 1999
SEED = 20261116
LOW, HIGH = math.log(0.99), math.log(1.01)
THIRDS = (('2025-09-15', '2026-01-31'), ('2026-02-01', '2026-06-30'), ('2026-07-01', '2026-11-12'))


def special(day):
    """年末年始（12/29〜1/3）とお盆（8/13〜16）。主の比較から除き、参考に別に出す。"""
    md = day[5:]
    return md >= '12-29' or md <= '01-03' or '08-13' <= md <= '08-16'


def group(day):
    if special(day):
        return 'special'
    return 'rest' if date.fromisoformat(day).weekday() >= 5 or day in HOLIDAYS else 'weekday'


def week(day):
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


# ---- 推定 ----
def specs_for(key):
    import setting_estimate
    return setting_estimate.SPECS[key][2]


def loglik(games, bb, rb, specs):
    p_bb = np.array([1 / s[1] for s in specs]); p_rb = np.array([1 / s[2] for s in specs])
    g, b, r = (np.asarray(x, dtype=float)[:, None] for x in (games, bb, rb))
    return b * np.log(p_bb) + r * np.log(p_rb) + (g - b - r) * np.log1p(-p_bb - p_rb)


def prepare(L):
    return np.exp(L - L.max(axis=1, keepdims=True))


def em(E, w=None, start=None, iters=3000, tol=1e-9):
    n, S = E.shape
    w = np.ones(n) if w is None else w
    pi = np.full(S, 1 / S) if start is None else start.copy()
    total = w.sum()
    for _ in range(iters):
        num = E * pi
        resp = num / num.sum(axis=1, keepdims=True)
        new = (w @ resp) / total
        if np.max(np.abs(new - pi)) < tol:
            return new
        pi = new
    return pi


def mean_rate(pi, specs):
    return float(sum(p * (1 / s[1] + 1 / s[2]) for p, s in zip(pi, specs)))


def mean_rb(pi, specs):
    return float(sum(p * (1 / s[2]) for p, s in zip(pi, specs)))


def analyse(rows, boot=BOOT, seed=SEED, groups=('weekday', 'rest')):
    """rows：dict(model, day, games, bb, rb)。機種ごとの推定と、台日数で重みを付けた ln(土日祝÷平日)。"""
    by = defaultdict(list)
    for r in rows:
        by[(r['model'], group(r['day']))].append(r)
    weeks = sorted({week(r['day']) for r in rows})
    windex = {w: i for i, w in enumerate(weeks)}
    machines = {}
    for model in sorted({r['model'] for r in rows}):
        parts = {g: by.get((model, g), []) for g in groups}
        if any(len(v) < MIN_ROWS for v in parts.values()):
            continue
        specs = specs_for(model)
        item = dict(rows={g: len(v) for g, v in parts.items()})
        fit = {}
        for g, v in parts.items():
            E = prepare(loglik([r['games'] for r in v], [r['bb'] for r in v], [r['rb'] for r in v], specs))
            pi = em(E)
            fit[g] = dict(E=E, pi=pi, w=np.array([windex[week(r['day'])] for r in v]))
            item[g] = dict(pi=[round(float(x), 4) for x in pi], mean_rate=mean_rate(pi, specs),
                           high_share=float(sum(pi[3:])), mean_rb=mean_rb(pi, specs))
        item['score'] = math.log(item[groups[1]]['mean_rate'] / item[groups[0]]['mean_rate'])
        item['rb_score'] = math.log(item[groups[1]]['mean_rb'] / item[groups[0]]['mean_rb'])
        item['_fit'], item['_specs'] = fit, specs
        machines[model] = item
    if not machines:
        return dict(machines={}, score=None)
    weight = {m: sum(x['rows'].values()) for m, x in machines.items()}

    def combine(scores):
        return sum(weight[m] * s for m, s in scores.items()) / sum(weight.values())

    est = combine({m: x['score'] for m, x in machines.items()})
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(boot):
        counts = np.bincount(rng.integers(0, len(weeks), len(weeks)), minlength=len(weeks)).astype(float)
        scores = {}
        for m, x in machines.items():
            rates = []
            for g in groups:
                f = x['_fit'][g]
                w = counts[f['w']]
                if w.sum() <= 0:
                    rates = None
                    break
                rates.append(mean_rate(em(f['E'], w, start=f['pi'], iters=500, tol=1e-7), x['_specs']))
            if rates is None:
                break
            scores[m] = math.log(rates[1] / rates[0])
        else:
            boots.append(combine(scores))
    boots.sort()
    lo, hi = boots[int(len(boots) * .025)], boots[int(len(boots) * .975) - 1]
    for x in machines.values():
        x.pop('_fit'); x.pop('_specs')
    return dict(machines=machines, score=est, ratio=math.exp(est), ci=(math.exp(lo), math.exp(hi)),
                boots=len(boots), weeks=len(weeks))


def verdict(res):
    if res.get('score') is None:
        return '判断保留（機種が足りない）'
    lo, hi = math.log(res['ci'][0]), math.log(res['ci'][1])
    if hi < 0 and res['ratio'] <= 0.99:
        return '設定が低い'
    if lo >= LOW and hi <= HIGH:
        return '打たれ方の違い'
    return '判断保留'


def naive(rows, groups=('weekday', 'rest')):
    """参考：2,000G以上の台だけの合算確率（回転数の合計で割る）の比。打たれ方の影響を受ける物差し。"""
    agg = defaultdict(lambda: defaultdict(lambda: [0., 0.]))
    for r in rows:
        g = group(r['day'])
        if g in groups and r['games'] >= 2000:
            a = agg[r['model']][g]; a[0] += r['bb'] + r['rb']; a[1] += r['games']
    out = {}
    for m, a in agg.items():
        if all(a[g][1] > 0 for g in groups):
            out[m] = (a[groups[1]][0] / a[groups[1]][1]) / (a[groups[0]][0] / a[groups[0]][1])
    return out


# ---- 合成データ ----
def simulate(rng, model, pi, days, racks, policy):
    """1日×台ごとに設定を pi で引き、50G刻みで遊技をまねる。policy=(やめるハマり, 最低G, 上限G)。"""
    specs = specs_for(model)
    p_bb = np.array([1 / s[1] for s in specs]); p_rb = np.array([1 / s[2] for s in specs])
    rows = []
    for day in days:
        s = rng.choice(len(specs), size=racks, p=pi)
        pb, pr = p_bb[s], p_rb[s]
        drought_stop, minimum, cap = policy[group(day)]
        games = np.zeros(racks); bb = np.zeros(racks); rb = np.zeros(racks); dry = np.zeros(racks)
        alive = np.ones(racks, bool)
        for _ in range(int(cap // 50)):
            hits = rng.binomial(50, pb + pr) * alive
            b = rng.binomial(hits, pb / (pb + pr))
            bb += b; rb += hits - b; games += 50 * alive
            dry = np.where(hits > 0, rng.integers(0, 50, racks), dry + 50)
            alive &= ~((games >= minimum) & (dry >= drought_stop))
            if not alive.any():
                break
        for g, b, r in zip(games, bb, rb):
            if g > 0:
                rows.append(dict(model=model, day=day, games=int(g), bb=int(b), rb=int(r)))
    return rows


def synthetic(boot=199):
    rng = np.random.default_rng(SEED)
    days = [(date(2025, 9, 15) + timedelta(days=i)).isoformat() for i in range(420)]
    same = np.array([.35, .25, .15, .1, .08, .07])
    lower = np.array([.47, .28, .12, .06, .04, .03])
    policy = {'weekday': (350, 500, 9000), 'rest': (900, 500, 9000), 'special': (900, 500, 9000)}
    checks = {}
    base = []
    for model, racks in (('my_juggler_v', 25), ('houou_tensho', 12), ('king_2023', 10)):
        base += simulate(rng, model, same, days, racks, policy)
    nv = naive(base)
    res = analyse(base, boot=boot)
    checks['a_naive_is_biased'] = dict(naive=nv, ok=all(v < 0.99 for v in nv.values()))
    checks['b_same_mix_is_play_style'] = dict(ratio=res['ratio'], ci=res['ci'], verdict=verdict(res),
                                              ok=verdict(res) == '打たれ方の違い')
    # 土日祝だけ低い設定を増やした場合
    shifted = []
    for model, racks in (('my_juggler_v', 25), ('houou_tensho', 12), ('king_2023', 10)):
        wk = [d for d in days if group(d) == 'weekday']; rs = [d for d in days if group(d) != 'weekday']
        shifted += simulate(rng, model, same, wk, racks, policy) + simulate(rng, model, lower, rs, racks, policy)
    res2 = analyse(shifted, boot=boot)
    truth = {}
    for model in ('my_juggler_v', 'houou_tensho', 'king_2023'):
        sp = specs_for(model)
        truth[model] = mean_rate(lower, sp) / mean_rate(same, sp)
    checks['c_lower_mix_is_found'] = dict(ratio=res2['ratio'], ci=res2['ci'], truth=truth, verdict=verdict(res2),
                                          ok=verdict(res2) == '設定が低い')
    checks['passed'] = all(v['ok'] for k, v in checks.items() if isinstance(v, dict))
    return checks


# ---- 実データ ----
def load_real(data_dir):
    sys.path.insert(0, str(Path(data_dir).resolve().parent))
    import daily_learning_archive
    from daily_learning import valid
    from daily_learning_runtime import read_database
    from setting_estimate import model_for_machine
    found = {}
    for r in daily_learning_archive.load(STORE, FIRST, (date.fromisoformat(DB_FROM) - timedelta(days=1)).isoformat()):
        found[(r['day'], int(r['rack']))] = r
    for r in read_database(Path(data_dir) / 'database.sqlite3', 'days'):
        if r.get('store') == STORE and DB_FROM <= r['day'] <= LAST:
            found[(r['day'], int(r['rack']))] = r            # 同じ台・日は原本DBを優先
    rows, skipped = [], defaultdict(int)
    for (day, rack), r in sorted(found.items()):
        if not FIRST <= day <= LAST:
            continue
        model = model_for_machine(r.get('machine'))
        if model is None or model in EXCLUDE_MODELS:
            continue
        if not valid(r) or any(type(r.get(k)) is not int for k in ('games', 'bb', 'rb')) or r['bb'] + r['rb'] > r['games']:
            skipped['invalid'] += 1
            continue
        rows.append(dict(model=model, day=day, games=r['games'], bb=r['bb'], rb=r['rb']))
    return rows, dict(skipped)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('synthetic', 'real'))
    p.add_argument('--data', default='data')
    a = p.parse_args(argv)
    sys.path.insert(0, str(Path(a.data).resolve().parent))      # database フォルダ（setting_estimate など）
    if a.mode == 'synthetic':
        checks = synthetic()
        (HERE / 'synthetic.json').write_text(json.dumps(checks, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(checks, ensure_ascii=False, indent=1))
        return
    syn = HERE / 'synthetic.json'
    if not syn.exists() or not json.loads(syn.read_text(encoding='utf-8')).get('passed'):
        raise SystemExit('合成データの試験が通っていません（synthetic を先に）。')
    out = HERE / 'result-real.json'
    if out.exists():
        raise SystemExit('result-real.json があります。実データは1回だけ。')
    rows, skipped = load_real(a.data)
    main_res = analyse(rows)
    result = dict(period=(FIRST, LAST), rows=len(rows), skipped=skipped, verdict=verdict(main_res), main=main_res,
                  naive_2000=naive(rows))
    # 参考：3期間、年末年始・お盆
    result['thirds'] = []
    for f, l in THIRDS:
        part = [r for r in rows if f <= r['day'] <= l]
        r3 = analyse(part, boot=499)
        result['thirds'].append(dict(period=(f, l), ratio=r3.get('ratio'), ci=r3.get('ci'),
                                     machines=sorted(r3['machines'])))
    sp = analyse(rows, boot=499, groups=('weekday', 'special'))
    result['special_vs_weekday'] = dict(ratio=sp.get('ratio'), ci=sp.get('ci'))
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    lines = [f"幸町 ジャグラー・ハナハナ（確率表のある機種、BT除く）{FIRST}〜{LAST}：{len(rows):,}台日",
             f"判定：{result['verdict']}　土日祝÷平日の平均の合算確率 {main_res['ratio']:.4f}倍"
             f"（週ブロック95%区間 {main_res['ci'][0]:.4f}〜{main_res['ci'][1]:.4f}、{main_res['weeks']}週）"]
    for m, x in main_res['machines'].items():
        lines.append(f"  {m}：{math.exp(x['score']):.4f}倍　RBだけ {math.exp(x['rb_score']):.4f}倍　"
                     f"設定4以上の推定 平日 {x['weekday']['high_share']:.3f}・土日祝 {x['rest']['high_share']:.3f}　"
                     f"台日 平日 {x['rows']['weekday']:,}・土日祝 {x['rows']['rest']:,}　"
                     f"参考 2,000G以上の合算の比 {result['naive_2000'].get(m, float('nan')):.4f}")
    for t in result['thirds']:
        lines.append(f"  参考 {t['period'][0]}〜{t['period'][1]}：{t['ratio'] if t['ratio'] is None else round(t['ratio'], 4)}倍"
                     f"（{t['ci'] if t['ci'] is None else tuple(round(x, 4) for x in t['ci'])}）")
    s = result['special_vs_weekday']
    lines.append(f"  参考 年末年始・お盆÷平日：{s['ratio'] if s['ratio'] is None else round(s['ratio'], 4)}倍")
    (HERE / 'result-real.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
```
