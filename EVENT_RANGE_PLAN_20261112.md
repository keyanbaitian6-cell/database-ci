# イベントの日の「狙う機種の範囲」の前向き検証の計画（2026-11-12 固定、Claude）

利用者「計画を固定していいよ」（2026-11-12）。`NEXT_DAY_ACCURACY_REVIEW_20261112.md` の案1。**この計画は、前向きの期間の結果を見る前に固定した。** 規則・物差し・判定の基準を途中で変えない。変えるときは利用者に相談し、変えた日以降を新しい検証として数え直す。

- 本番の候補・採点・画面・元データは変えない。差が確かめられた規則だけ、判定のあとで「明日は◯◯の日：対象は△△」と出すかを利用者と決める（出す画面も、決まりどおりそのとき確かめる）。
- 判定のスクリプト：`../outputs/event-range-forward-20261112/review.py`（試験 `test_review.py` 6件。リポジトリ外なので、全文をこの文書の末尾に写した）。固定時の指紋（sha256）：`review.py` = `afe492b9cbedb595c1752d92ff7df8eade4b7b87f811370a05ee01e198af5dcb`、`test_review.py` = `0c99693b9d2a243ad8740332f7d0fba9f2ebf5f9474c8e484f52d9912f896163`。
- 前の段階：意味の確認（利用者「不明です」「前日までにはわかります」）と過去の分析は `AI_COLLABORATION.md` 2026-11-12 夜の2節、`../outputs/event-past-analysis-20261112/報告.md`。

## 規則（4つ）

|規則|対象の日|対象の機種（前日までに分かる情報だけで決める）|由来|
|---|---|---|---|
|R1|幸町で、イベント名に「華の日」がある日|名前に「ハナハナ」がある全機種（NFKCで全角にそろえて判定。ハナビは入らない）|利用者の説明「ハナハナシリーズが強い」|
|R2|長町南の「4台構成」の日／「半列」の日|4台構成：設置4台の機種／半列：設置7台・8台の機種|利用者の説明（`STORE_EVENTS.md`）|
|R3|どの店でも、イベント名と機種名に共通の文字列がある日|イベント名と機種名に共通する漢字・カタカナだけの文字列で、**漢字2字以上、または4字以上**のもの。いちばん長く一致した機種（同じ長さなら全部）。「スマスロ」「パチスロ」は数えない。英字・数字は数えない|過去の分析（ツキヌケ取材（北斗）、天照大御神(マイジャグ全)）。意味の推測ではなく、名前の文字の一致だけ|
|R4|どの店でも、同じ名前のイベントが前にもあった日|前回（別の回）の、店の上位3機種|利用者「この前こうだったというもの」|

- 設置台数・機種の一覧は、**対象日の前の日**のデータ（無ければ3日前まで）で決める。低稼働の台も数える。P-STATIONの名前の変わり目は日次学習と同じくそろえる。
- 同じ名前が続く日（長町南の週替わりなど）は1回にまとめる。R4の「前回」は別の回だけ（同じ週の前の日は前回に数えない）。
- 上位3機種の順位：その回の当たりの比を、ふだんなら30回分を足して縮めたもの（ふだんなら10回未満の機種は入れない）。
- 1つの日が複数の規則に当たれば、規則ごとに数える。
- **P-STATIONの5・15・25日のゴーゴージャグラー3は入れない**（`../outputs/pstation-forward-20261108/PLAN.md` の v1 で前向き検証中。評価は2027-02-07以降）。

## 使うイベント

- 両方のDBの `date_events`（長町南・幸町は `database.sqlite3`、P-STATIONは `pscube.sqlite3`）。同じ日に複数あれば新しい入力。消したもの（名前なし）は使わない。
- **入力時刻（`updated_at`、日本時間）が対象日より前のものだけ**。当日以降に入力・直したものは使わない（直したときに入力時刻が変わるので、前日に入れたものでも当日に直すと外れる）。
- 利用者はこれまでどおり、イベントを前日までに入れる。長町南は毎日イベントがあるので、ふつうの日との比較はしない（利用者「長町は毎日イベントあるからいいよ」）。比べるのは、同じ日の対象の機種と対象外の機種。

## 物差し

- 台：500G以上で `daily_learning.valid()` を通る台。当たり＝BB＋RB。
- 機種のふだんの当たりの率：その機種の直前28日の（BB＋RB）÷ゲーム数（ゲーム数5,000以上のときだけ）。ふだんならの当たり回数＝その日のゲーム数×ふだんの率。
- **1日のスコア＝ ln（対象の機種の 当たり÷ふだんなら ÷ 対象外の機種の 当たり÷ふだんなら）**。0＝差なし。対象・対象外のどちらかでふだんならの当たりが10回未満なら「判定不能」の日として数えるだけ。
- 回（同じ名前が続く日）ごとにスコアを平均し、回を単位にする。
- 参考に出すだけ（判定には使わない）：プラス率（記録上の差枚の符号）の対象・対象外。

## 判定（1回だけ）

- 前向きの対象日：**2026-11-13〜2027-02-07**。判定は **2027-02-15 以降に1回だけ** `review.py forward`（それより前は実行を拒む）。途中の成績は見ない。
- 規則ごとに、回の平均スコアの平均と、回を単位にした 98.75% のブートストラップ区間（4規則のボンフェローニ。10,000回、乱数の種 20261112）。
- **採用候補**：区間の下限が0を超え、かつ対象の比が 1.05倍以上。**不採用**：それ以外。
- **回数が足りない規則**（R1・R2 は3回未満、R3・R4 は5回未満）は「判定保留」。その規則だけ、対象日を 2027-05-15 まで延ばし、**2027-05-23 以降に1回だけ** `review.py extended`。延長でも足りなければ「判定できず」で終える。
- 採用候補になっても、出すかどうか・どこに出すかは利用者と決める。台の順位の式は変えない。

## 参考：計画の前に見た期間（9/14〜11/11）の再計算

判定には使わない。スクリプトが動くことの確かめ（`review.py past`、入力時刻の条件なし）。

|規則|結果|
|---|---|
|R1|2回・判定保留（回数不足）|
|R2|4回・17日、対象の比 0.993倍（区間 0.941〜1.031）、差を確認できず|
|R3|4回・判定保留（業火の極 −0.20、マイジャグ全 +0.14、北斗 +0.42、ジャグラーライター入荷 +0.22）|
|R4|12回・24日、対象の比 0.881倍（区間 0.715〜1.064）、差を確認できず|

## 限界

- 回数が少ない規則（華の日は月1回）は延長しても判定できないことがある。
- 物差しは当たり回数で、設定・収支ではない。
- 店がやり方を変えれば効かなくなる。対象の機種が分かっても、その中のどの台かは分からない。
- P-STATIONは11/4〜11/6に取り込み元がサイトセブンに替わった。前向きの期間の「ふだん」はサイトセブンの28日になるので、12月以降は数え方がそろう。

## 付録：review.py の全文（固定時）

ファイルが失われたときの写し。指紋は上のとおり。

```python
"""イベントの日の「狙う機種の範囲」の前向き検証（計画：リポジトリの EVENT_RANGE_PLAN_20261112.md）。

2026-11-12 に結果を見る前に固定した。規則・物差し・判定の基準を変えるときは、計画書と同じく利用者に相談し、
変えた日以降を新しい検証として数え直す（この版の判定には混ぜない）。

使い方（database フォルダで）：
  前向きの判定（2027-02-15 以降に1回だけ）：
    .venv/Scripts/python.exe ../../outputs/event-range-forward-20261112/review.py forward
  参考（計画前に見た期間 9/14〜11/11 の再計算。判定には使わない）：
    .venv/Scripts/python.exe ../../outputs/event-range-forward-20261112/review.py past
結果は同じフォルダの result-<mode>.json と result-<mode>.txt。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sqlite3
import statistics
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))

# ---- 固定した条件（計画書と同じ） ----
FORWARD = ('2026-11-13', '2027-02-07')        # 前向きの対象日
FORWARD_REVIEW = '2027-02-15'                 # これより前は forward を実行しない
EXTENDED = ('2026-11-13', '2027-05-15')       # 回数が足りない規則だけ、1回だけ延長
EXTENDED_REVIEW = '2027-05-23'
PAST = ('2026-09-14', '2026-11-11')           # 計画前に見た期間（参考）
MIN_GAMES = 500
BASE_DAYS = 28
BASE_MIN_GAMES = 5000
SHRINK = 30
MIN_EXP = 10
MIN_CLUSTERS = {'R1': 3, 'R2': 3, 'R3': 5, 'R4': 5}
LIFT = 1.05
CONF = 1 - .05 / 4                            # 4規則のボンフェローニ（98.75%）
BOOT = 10000
SEED = 20261112
STORES = ('nagamachiminami', 'saiwaichou', 'pscube:c740601:20')
NAMES = {'nagamachiminami': '長町南', 'saiwaichou': '幸町', 'pscube:c740601:20': 'P-STATION'}
RULES = {
    'R1': '幸町 華の日 → ハナハナの全機種',
    'R2': '長町南 4台構成 → 設置4台の機種／半列 → 設置7・8台の機種',
    'R3': 'イベント名に機種名の一部（漢字2字以上、またはカタカナ・漢字4字以上）がある → その機種',
    'R4': '同じ名前のイベントの前回、店の上位3機種だった機種',
}


def shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def norm(text):
    return unicodedata.normalize('NFKC', str(text)).replace(' ', '').replace('　', '')


def is_hana(machine):
    return 'ハナハナ' in norm(machine)


KANJI = re.compile(r'[一-鿿々]')
ALLOWED = re.compile(r'[一-鿿々ァ-ヺー]')
GENERIC = ('スマスロ', 'パチスロ')


def name_match(event_name, machine):
    """イベント名と機種名に共通する、漢字・カタカナだけの文字列のうち、条件を満たすいちばん長いものの長さ（無ければ0）。"""
    e, m = norm(event_name), norm(machine)
    for g in GENERIC:
        m = m.replace(g, '\0')
    best = 0
    runs = re.findall(r'[一-鿿々ァ-ヺー]+', e)
    for run in runs:
        for i in range(len(run)):
            for j in range(i + 2, len(run) + 1):
                sub = run[i:j]
                if sub in m and (len(sub) >= 4 or (len(sub) >= 2 and all(KANJI.match(c) for c in sub))):
                    best = max(best, len(sub))
    return best


def r3_targets(event_name, machines):
    scores = {m: name_match(event_name, m) for m in machines}
    top = max(scores.values(), default=0)
    return {m for m, s in scores.items() if top and s == top}


def entered_before(updated_at, day):
    if not updated_at:
        return False
    t = datetime.fromisoformat(str(updated_at).replace('Z', '+00:00'))
    if t.tzinfo is None:
        t = t.replace(tzinfo=JST)
    return t.astimezone(JST).date().isoformat() < day


# ---- データ ----
def load(data_dir, last_day):
    sys.path.insert(0, str(Path(data_dir).resolve().parent))
    from daily_learning import outcome, valid
    from daily_learning_names import learning_machine
    from daily_learning_runtime import load_inputs
    rows, _ = load_inputs(data_dir, shift(last_day, 1))
    racks, composition = [], defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r['store'] not in STORES:
            continue
        machine = learning_machine(r['store'], r['machine'])
        composition[(r['store'], r['day'])][machine] += 1          # 設置台数（低稼働の台も数える）
        if valid(r) and r['games'] >= MIN_GAMES:
            racks.append(dict(store=r['store'], day=r['day'], machine=machine, games=float(r['games']),
                              hits=float((r.get('bb') or 0) + (r.get('rb') or 0)), plus=outcome(r)))
    events = {}
    for path, query in ((Path(data_dir) / 'database.sqlite3', "select value from app_state where state_key='date_events'"),
                        (Path(data_dir) / 'pscube.sqlite3', "select value from state where key='date_events'")):
        db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            row = db.execute(query).fetchone()
        finally:
            db.close()
        for e in json.loads(row[0]) if row else []:
            store = e['store'] if e['store'] in NAMES else f"pscube:{e['store']}:{e.get('rate', '20')}"
            key = (store, e['day'])
            if key not in events or str(e.get('updated_at', '')) > str(events[key].get('updated_at', '')):
                events[key] = e
    events = {k: dict(name=norm(v['name']), updated_at=v.get('updated_at'))
              for k, v in events.items() if v.get('name') and k[0] in STORES}
    return racks, {k: dict(v) for k, v in composition.items()}, events


# ---- 物差し ----
def with_expected(racks):
    md = defaultdict(lambda: [0., 0.])
    for r in racks:
        x = md[(r['store'], r['machine'], r['day'])]
        x[0] += r['games']; x[1] += r['hits']
    seqs = defaultdict(list)
    for (s, m, d), v in md.items():
        seqs[(s, m)].append((d, v))
    base = {}
    for (s, m), seq in seqs.items():
        seq.sort()
        for i, (d, _) in enumerate(seq):
            first = shift(d, -BASE_DAYS)
            g = sum(v[0] for dd, v in seq[:i] if dd >= first)
            h = sum(v[1] for dd, v in seq[:i] if dd >= first)
            if g >= BASE_MIN_GAMES and h > 0:
                base[(s, m, d)] = h / g
    index = defaultdict(list)
    for r in racks:
        b = base.get((r['store'], r['machine'], r['day']))
        if b:
            index[(r['store'], r['day'])].append({**r, 'expected': r['games'] * b})
    return index


def machine_sums(index, store, days):
    agg = defaultdict(lambda: dict(hits=0., exp=0., plus=0, known=0))
    for d in days:
        for r in index.get((store, d), []):
            a = agg[r['machine']]
            a['hits'] += r['hits']; a['exp'] += r['expected']
            if r['plus'] is not None:
                a['known'] += 1; a['plus'] += r['plus']
    return agg


def top3(agg):
    pool = sorted((((a['hits'] + SHRINK) / (a['exp'] + SHRINK)), m) for m, a in agg.items() if a['exp'] >= MIN_EXP)
    return {m for _, m in pool[::-1][:3]}


def previous_composition(composition, store, day):
    for k in range(1, 4):
        c = composition.get((store, shift(day, -k)))
        if c:
            return c
    return None


def occurrences(events, store):
    """同じ名前が続く日を1回にまとめる：{(名前, 開始日): [日...]}。"""
    runs, last = {}, {}
    for (s, d), e in sorted(events.items(), key=lambda x: x[0][1]):
        if s != store:
            continue
        n = e['name']
        if n in last and shift(last[n][-1], 1) == d:
            last[n].append(d)
        else:
            last[n] = [d]
            runs[(n, d)] = last[n]
    return runs


def targets_for(rule, store, day, name, composition, index, runs):
    comp = previous_composition(composition, store, day)
    if not comp:
        return None
    if rule == 'R1':
        return {m for m in comp if is_hana(m)} if store == 'saiwaichou' and '華の日' in name else None
    if rule == 'R2':
        if store != 'nagamachiminami':
            return None
        if name == '4台構成':
            return {m for m, n in comp.items() if n == 4}
        if name == '半列':
            return {m for m, n in comp.items() if n in (7, 8)}
        return None
    if rule == 'R3':
        return r3_targets(name, comp) or None
    if rule == 'R4':
        mine = [(start, days) for (n, start), days in runs.items() if n == name and days[-1] < day and day not in days]
        if not mine:
            return None
        _, days = max(mine)
        return top3(machine_sums(index, store, days)) or None
    raise ValueError(rule)


def evaluate(racks, composition, events, period, require_entered=True):
    """規則ごとに、対象日のスコア ln(対象の比 ÷ 対象外の比) と、イベントの回（まとまり）を返す。"""
    index = with_expected(racks)
    first, last = period
    out = {rule: [] for rule in RULES}
    for store in STORES:
        runs = occurrences(events, store)
        start_of = {d: start for (n, start), days in runs.items() for d in days}
        for (s, day), e in sorted(events.items()):
            if s != store or not first <= day <= last:
                continue
            if require_entered and not entered_before(e['updated_at'], day):
                continue
            agg = machine_sums(index, store, [day])
            for rule in RULES:
                t = targets_for(rule, store, day, e['name'], composition, index, runs)
                if not t:
                    continue
                T = [a for m, a in agg.items() if m in t]
                O = [a for m, a in agg.items() if m not in t]
                th, te = sum(a['hits'] for a in T), sum(a['exp'] for a in T)
                oh, oe = sum(a['hits'] for a in O), sum(a['exp'] for a in O)
                rec = dict(store=store, day=day, name=e['name'], cluster=f"{store}|{e['name']}|{start_of[day]}",
                           targets=sorted(t), target_exp=round(te, 1))
                if te < MIN_EXP or oe < MIN_EXP or th <= 0 or oh <= 0:
                    rec['score'] = None                                   # 判定不能（対象の台が少ない・動いていない）
                else:
                    rec['score'] = math.log((th / te) / (oh / oe))
                    rec['ratio_target'], rec['ratio_other'] = th / te, oh / oe
                    tk, ok = sum(a['known'] for a in T), sum(a['known'] for a in O)
                    rec['plus_target'] = sum(a['plus'] for a in T) / tk if tk else None
                    rec['plus_other'] = sum(a['plus'] for a in O) / ok if ok else None
                out[rule].append(rec)
    return out


def judge(records, rule, rng=None):
    rng = rng or random.Random(SEED)
    clusters = defaultdict(list)
    for r in records:
        if r['score'] is not None:
            clusters[r['cluster']].append(r['score'])
    means = [statistics.mean(v) for v in clusters.values()]
    res = dict(rule=rule, rule_text=RULES[rule], days=sum(len(v) for v in clusters.values()), clusters=len(means),
               not_measurable=sum(1 for r in records if r['score'] is None))
    if len(means) < MIN_CLUSTERS[rule]:
        res['verdict'] = '判定保留（回数不足）'
        return res
    boots = sorted(statistics.mean(rng.choices(means, k=len(means))) for _ in range(BOOT))
    lo, hi = boots[int(BOOT * (1 - CONF) / 2)], boots[int(BOOT * (1 + CONF) / 2) - 1]
    est = statistics.mean(means)
    res.update(lift=math.exp(est), ci=(math.exp(lo), math.exp(hi)))
    res['verdict'] = '採用候補（差を確認）' if lo > 0 and math.exp(est) >= LIFT else '不採用（差を確認できず）'
    return res


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('forward', 'extended', 'past'))
    p.add_argument('--data', default='data')
    p.add_argument('--today', default=None, help='試験用。省略時は日本時間の今日')
    a = p.parse_args(argv)
    today = a.today or datetime.now(JST).date().isoformat()
    if a.mode == 'forward' and today < FORWARD_REVIEW:
        raise SystemExit(f'前向きの判定は {FORWARD_REVIEW} 以降に1回だけ（今日 {today}）。途中の成績は見ない。')
    if a.mode == 'extended' and today < EXTENDED_REVIEW:
        raise SystemExit(f'延長の判定は {EXTENDED_REVIEW} 以降に1回だけ（今日 {today}）。')
    period = dict(forward=FORWARD, extended=EXTENDED, past=PAST)[a.mode]
    racks, composition, events = load(a.data, period[1])
    rec = evaluate(racks, composition, events, period, require_entered=a.mode != 'past')
    verdicts = [judge(rec[r], r) for r in RULES]
    if a.mode == 'extended':
        first = json.loads((HERE / 'result-forward.json').read_text(encoding='utf-8'))
        held = {v['rule'] for v in first['verdicts'] if v['verdict'].startswith('判定保留')}
        verdicts = [v for v in verdicts if v['rule'] in held]       # 延長は、初回に回数不足だった規則だけ
    result = dict(mode=a.mode, period=period, run_on=today, verdicts=verdicts, records=rec)
    (HERE / f'result-{a.mode}.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    lines = [f'{a.mode} {period[0]}〜{period[1]}（実行 {today}）']
    for v in verdicts:
        extra = f" 対象の比 {v['lift']:.3f}倍（{CONF:.2%}区間 {v['ci'][0]:.3f}〜{v['ci'][1]:.3f}）" if 'lift' in v else ''
        lines.append(f"{v['rule']} {v['rule_text']}：{v['verdict']}　{v['clusters']}回・{v['days']}日・判定不能{v['not_measurable']}日{extra}")
    (HERE / f'result-{a.mode}.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
```
