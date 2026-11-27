"""Read-only check: did the 翌日候補（仮） racks actually do better the next day?

For every store, machine and day D that also has data for D+1, the candidates
are chosen exactly as the app does (``provisional_next_day_candidates``), using
only records dated up to D. This does not prove those records had already been
saved by D; late imports can make this a hindsight comparison. The same racks
are then looked up on D+1 and compared
with the racks that could be judged but were not chosen.

Run from database/:
    .runtime/Scripts/python.exe backtest_candidates.py            # PC data
    .runtime/Scripts/python.exe backtest_candidates.py --csv x.csv  # legacy detailed CSV
    .runtime/Scripts/python.exe backtest_candidates.py --json x.json  # backup

Never changes any record. Prints a short summary (no rack-level data) and,
with --details, writes per-rack rows to reports/ (private, not in Git).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from core import (implausible_numbers, is_hidden_machine, next_day_index,
                  percentile, provisional_next_day_candidates)

JST = timezone(timedelta(hours=9))

STORE_CODES = {
    'メルヘンワールド長町南店': 'nagamachiminami',
    'スーパーメルヘンワールド幸町': 'saiwaichou',
}
MIN_GAMES = 500  # same floor as next_day_index


class Rows:
    """The two lookups the candidate functions need, over an in-memory list."""

    def __init__(self, rows):
        self.by_machine = defaultdict(list)
        self.by_day = defaultdict(list)
        for r in sorted(rows, key=lambda r: (r['day'], r['store'], int(r['rack']))):
            self.by_machine[(r['machine'], r['store'])].append(r)
            self.by_day[(r['day'], r['machine'], r['store'])].append(r)

    def _machine_rows(self, machine, store):
        return self.by_machine[(machine, store)]

    def rows(self, day=None, machine=None, store=None):
        if machine is None:
            # 1店舗・1日の全機種（バラエティの判定に使う）。
            return [r for key, rows in self.by_day.items()
                    if key[0] == day and key[2] == store for r in rows]
        return self.by_day[(day, machine, store)]


def _int(value):
    text = str(value or '').strip()
    return int(text) if text.lstrip('-').isdigit() else None


def load_sqlite(root: Path):
    path = root / 'data/database.sqlite3'
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        payloads = [json.loads(r[0]) for r in db.execute('SELECT payload FROM days')]
    return [_slim(p) for p in payloads]


def load_json(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, dict):
        data = data.get('records') or data.get('rows') or []
    return [_slim(p) for p in data]


def load_csv(path: Path):
    rows = []
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        required = {'店舗', '日付', '機種名', '台番号', '総回転数', 'BIG', 'REG'}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                'このCSVはバックテストに必要な列がありません。'
                '現在の共有用CSVでは店舗・台番号を省いているため、'
                'databaseのバックアップJSON（--json）かPCデータベースを使ってください。'
            )
        for raw in reader:
            store = STORE_CODES.get(raw['店舗'], raw['店舗'])
            total = str(raw.get('合計点') or '').strip()
            rows.append(dict(store=store, day=raw['日付'], machine=raw['機種名'],
                             rack=_int(raw['台番号']), games=_int(raw['総回転数']),
                             bb=_int(raw['BIG']), rb=_int(raw['REG']),
                             total=float(total) if total else None))
    return [r for r in rows if r['rack'] is not None and r['games'] is not None]


def _slim(p):
    return dict(
        store=p['store'], day=p['day'], machine=p['machine'], rack=int(p['rack']),
        games=p.get('games') or 0, bb=p.get('bb'), rb=p.get('rb'),
        max_hold=p.get('max_hold'),
        graph_measurement=p.get('graph_measurement'),
        jo_net=p.get('jo_net'),
        net_medals=p.get('net_medals'),
        captured_at=p.get('captured_at'),
        total=p.get('total'),
    )


def _read_jst(text):
    """ISO 8601 時刻を UTC にそろえる。時差が無い時刻は日本時間とみなす。"""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(timezone.utc)


def _prediction_cutoff(day, hour):
    d = date.fromisoformat(day) + timedelta(days=1)
    return datetime(d.year, d.month, d.day, hour, tzinfo=JST).astimezone(timezone.utc)


def plus_outcome(row):
    """記録上のプラス判定（1=プラス, 0=非プラス, None=判定不能）。
    取得差枚があればその符号、無ければグラフ終点（±1px以内は判定不能）、大当たり0回グラフ省略は0。"""
    if not row or (row.get('games') or 0) <= 0 or implausible_numbers(row):
        return None
    for key in ('jo_net', 'net_medals'):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return int(value > 0)
    graph = row.get('graph_measurement')
    if isinstance(graph, dict):
        try:
            end = float(graph['baseline_y']) - float(graph['end_y'])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(end) or abs(end) <= 1:
            return None
        return int(end > 1)
    bb, rb = row.get('bb'), row.get('rb')
    if bb is not None and rb is not None and bb >= 0 and rb >= 0 and bb + rb == 0:
        return 0
    return None


def hit_rank(row, day_rows):
    """Next-day 'lightness' 0-100 among same-day racks with similar games
    (half to double), the same yardstick next_day_index uses. None if the
    rack barely played, has implausible numbers, or has fewer than three comparable racks."""
    if (row['games'] < MIN_GAMES or row['bb'] is None or row['rb'] is None
            or row['bb'] < 0 or row['rb'] < 0 or implausible_numbers(row)):
        return None
    peers = [r for r in day_rows if r['games'] >= MIN_GAMES and r['bb'] is not None
             and r['rb'] is not None and r['bb'] >= 0 and r['rb'] >= 0
             and not implausible_numbers(r)
             and row['games'] / 2 <= r['games'] <= row['games'] * 2]
    if len(peers) < 3:
        return None
    rates = [(r['bb'] + r['rb']) / r['games'] for r in peers]
    return 100 * percentile((row['bb'] + row['rb']) / row['games'], rates)


def spearman(xs, ys):
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                result[order[k]] = (i + j) / 2
            i = j + 1
        return result
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def collect(rows, cutoff_hour=None):
    """One entry per judged rack that also has a next-day outcome.

    ``cutoff_hour`` を指定すると、予測日 D の翌日の ``cutoff_hour`` 時（日本時間）より前に
    ``captured_at`` がある記録だけで D の候補を計算する（後知恵リーク防止）。"""
    visible = [r for r in rows if not is_hidden_machine(r['store'], r['machine'])]
    full_data = Rows(visible)
    out = []
    groups = sorted({(r['store'], r['machine'], r['day']) for r in visible})
    by_day_data = {}

    def data_for(day):
        if cutoff_hour is None:
            return full_data
        cached = by_day_data.get(day)
        if cached is None:
            cutoff = _prediction_cutoff(day, cutoff_hour)
            available = [
                r for r in visible
                if r['day'] <= day and (t := _read_jst(r.get('captured_at'))) is not None and t < cutoff
            ]
            cached = by_day_data[day] = Rows(available)
        return cached

    for store, machine, day in groups:
        nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        tomorrow = full_data.rows(nxt, machine, store)
        if not tomorrow:
            continue
        data = data_for(day)
        today = data.rows(day, machine, store)
        if not today:
            continue
        chosen = {int(c['row']['rack'])
                  for c in provisional_next_day_candidates(data, day, machine, store)['candidates']}
        by_rack = {int(r['rack']): r for r in tomorrow}
        for row in today:
            tendency = next_day_index(data, row)
            if tendency['index'] is None:
                continue
            after = by_rack.get(int(row['rack']))
            rank = hit_rank(after, tomorrow) if after else None
            valid_after = (
                after is not None
                and (after.get('games') or 0) > 0
                and after.get('bb') is not None
                and after.get('rb') is not None
                and after['bb'] >= 0
                and after['rb'] >= 0
                and not implausible_numbers(after)
            )
            out.append(dict(store=store, machine=machine, day=day, rack=int(row['rack']),
                            index=tendency['index'], days=tendency['days'],
                            confidence=tendency['confidence'], candidate=int(row['rack']) in chosen,
                            today_rank=hit_rank(row, today), next_rank=rank,
                            next_total=after.get('total') if after else None,
                            next_games=after['games'] if after else None,
                            next_hits=(after['bb'] + after['rb']) if valid_after else None,
                            next_plus=plus_outcome(after) if after else None))
    return out


def day_gaps(entries, key):
    """日等重み差：{day: mean_over_groups(mean(cand) - mean(pool))}。
    同じ店・機種・日の適格母集団（候補含む）と比べるため、母集団構成比の違いによる歪みを防ぐ。"""
    groups = defaultdict(list)
    for e in entries:
        if e.get(key) is not None:
            groups[(e['store'], e['machine'], e['day'])].append(e)
    by_day = defaultdict(list)
    for (_store, _machine, day), items in groups.items():
        cand = [e[key] for e in items if e['candidate']]
        if not cand:
            continue
        pool = [e[key] for e in items]
        by_day[day].append(mean(cand) - mean(pool))
    return {day: mean(vals) for day, vals in sorted(by_day.items())}


def _calendar_blocks(day_diffs, block_days=7, anchor=None):
    if not day_diffs:
        return []
    days = sorted(day_diffs)
    base = date.fromisoformat(anchor or days[0])
    grouped = defaultdict(list)
    for day in days:
        idx = (date.fromisoformat(day) - base).days // block_days
        grouped[idx].append(day_diffs[day])
    return [grouped[idx] for idx in sorted(grouped)]


def block_flip_p(day_diffs, block_days=7, trials=10000, seed=1, anchor=None):
    """暦日ブロック単位の符号反転検定（片側 p 値）。
    日ごとの差の系列に週単位の自己相関があっても第一種の過誤が膨らみにくい。
    戻り値は (日等重み平均, 片側p値, ブロック数)。"""
    blocks = _calendar_blocks(day_diffs, block_days=block_days, anchor=anchor)
    if not blocks:
        return None, None, 0
    sums = [sum(vals) for vals in blocks]
    total_days = sum(len(vals) for vals in blocks)
    observed = sum(sums) / total_days
    k = len(sums)
    if k <= 14:
        hits = 0
        total = 1 << k
        for mask in range(total):
            signed = sum(s if (mask >> i) & 1 else -s for i, s in enumerate(sums))
            if signed / total_days >= observed - 1e-12:
                hits += 1
        return observed, hits / total, k
    rng = random.Random(seed)
    hits = 0
    for _ in range(trials):
        signed = sum(s if rng.getrandbits(1) else -s for s in sums)
        if signed / total_days >= observed - 1e-12:
            hits += 1
    return observed, (hits + 1) / (trials + 1), k


def block_bootstrap_ci(day_diffs, block_days=7, rounds=5000, seed=1, anchor=None):
    """暦日ブロック単位の復元抽出95%区間（ブロック内の日列を丸ごと抽出）。"""
    blocks = _calendar_blocks(day_diffs, block_days=block_days, anchor=anchor)
    if len(blocks) < 2:
        return None
    block_stats = [(sum(vals), len(vals)) for vals in blocks]
    rng = random.Random(seed)
    means = []
    k = len(block_stats)
    for _ in range(rounds):
        s, n = 0.0, 0
        for _ in range(k):
            bs, bn = block_stats[rng.randrange(k)]
            s += bs
            n += bn
        means.append(s / n)
    means.sort()
    return means[int(rounds * 0.025)], means[int(rounds * 0.975) - 1]


def oe_ratio(entries):
    """全ゲームの当たり回数の比（O/E、稼働バイアス対策）。
    500G未満の台も含め、同日・同機種・同適格母集団の合算当たり率に対する候補の実測当たり数比を出す。"""
    groups = defaultdict(list)
    for e in entries:
        if e.get('next_games') and e['next_games'] > 0 and e.get('next_hits') is not None:
            groups[(e['store'], e['machine'], e['day'])].append(e)
    obs_total = 0.0
    exp_total = 0.0
    cand_games = 0
    pool_games = 0
    by_day = defaultdict(lambda: [0.0, 0.0])
    for (_store, _machine, day), items in groups.items():
        cands = [e for e in items if e['candidate']]
        if not cands:
            continue
        g_pool = sum(e['next_games'] for e in items)
        h_pool = sum(e['next_hits'] for e in items)
        if g_pool <= 0:
            continue
        rate = h_pool / g_pool
        g_cand = sum(e['next_games'] for e in cands)
        h_cand = sum(e['next_hits'] for e in cands)
        exp = g_cand * rate
        obs_total += h_cand
        exp_total += exp
        cand_games += g_cand
        pool_games += g_pool
        by_day[day][0] += h_cand
        by_day[day][1] += exp
    day_excess = {day: (o / e - 1.0) for day, (o, e) in sorted(by_day.items()) if e > 0}
    return dict(
        observed=obs_total,
        expected=exp_total,
        ratio=(obs_total / exp_total) if exp_total > 0 else None,
        cand_games=cand_games,
        pool_games=pool_games,
        day_excess=day_excess,
    )


def plus_summary(entries):
    """記録上のプラス率（候補 vs 適格母集団）と欠測感度分析（Manski最悪/最良境界＋共通置換）。"""
    groups = defaultdict(list)
    for e in entries:
        groups[(e['store'], e['machine'], e['day'])].append(e)
    cand_total = cand_judged = cand_plus = 0
    pool_total = pool_judged = pool_plus = 0
    obs_by_day = defaultdict(list)
    worst_by_day = defaultdict(list)
    best_by_day = defaultdict(list)
    both0_by_day = defaultdict(list)
    both1_by_day = defaultdict(list)
    for (_store, _machine, day), items in groups.items():
        cands = [e for e in items if e['candidate']]
        if not cands:
            continue
        cand_total += len(cands)
        pool_total += len(items)
        cj = [e['next_plus'] for e in cands if e.get('next_plus') is not None]
        pj = [e['next_plus'] for e in items if e.get('next_plus') is not None]
        cand_judged += len(cj)
        cand_plus += sum(cj)
        pool_judged += len(pj)
        pool_plus += sum(pj)
        if cj and pj:
            obs_by_day[day].append(mean(cj) - mean(pj))
        # Manski worst case (lower bound): 候補欠測=0, 候補外欠測=1
        wc = [e['next_plus'] if e.get('next_plus') is not None else 0 for e in cands]
        wp = [e['next_plus'] if e.get('next_plus') is not None else (0 if e['candidate'] else 1) for e in items]
        worst_by_day[day].append(mean(wc) - mean(wp))
        # Manski best case (upper bound): 候補欠測=1, 候補外欠測=0
        bc = [e['next_plus'] if e.get('next_plus') is not None else 1 for e in cands]
        bp = [e['next_plus'] if e.get('next_plus') is not None else (1 if e['candidate'] else 0) for e in items]
        best_by_day[day].append(mean(bc) - mean(bp))
        # 共通置換（両群とも欠測=0 / 両群とも欠測=1）
        z0c = [e['next_plus'] if e.get('next_plus') is not None else 0 for e in cands]
        z0p = [e['next_plus'] if e.get('next_plus') is not None else 0 for e in items]
        both0_by_day[day].append(mean(z0c) - mean(z0p))
        z1c = [e['next_plus'] if e.get('next_plus') is not None else 1 for e in cands]
        z1p = [e['next_plus'] if e.get('next_plus') is not None else 1 for e in items]
        both1_by_day[day].append(mean(z1c) - mean(z1p))

    def avg_day(d):
        return {day: mean(vals) for day, vals in sorted(d.items())}

    obs_days = avg_day(obs_by_day)
    return dict(
        cand_total=cand_total,
        cand_judged=cand_judged,
        cand_plus=cand_plus,
        cand_rate=(cand_plus / cand_judged) if cand_judged else None,
        cand_missing_rate=((cand_total - cand_judged) / cand_total) if cand_total else None,
        pool_total=pool_total,
        pool_judged=pool_judged,
        pool_plus=pool_plus,
        pool_rate=(pool_plus / pool_judged) if pool_judged else None,
        pool_missing_rate=((pool_total - pool_judged) / pool_total) if pool_total else None,
        day_diffs=obs_days,
        mean_diff=mean(obs_days.values()) if obs_days else None,
        manski_worst=mean(avg_day(worst_by_day).values()) if worst_by_day else None,
        manski_best=mean(avg_day(best_by_day).values()) if best_by_day else None,
        both_zero=mean(avg_day(both0_by_day).values()) if both0_by_day else None,
        both_one=mean(avg_day(both1_by_day).values()) if both1_by_day else None,
    )


def permutation_p(entries, key, trials, seed=1):
    """One-sided p: how often shuffling the candidate marks within each
    (store, machine, day) gives a candidate-minus-other gap at least as big."""
    usable = [e for e in entries if e[key] is not None]
    groups = defaultdict(list)
    for e in usable:
        groups[(e['store'], e['machine'], e['day'])].append(e)
    groups = [g for g in groups.values() if any(e['candidate'] for e in g)
              and not all(e['candidate'] for e in g)]
    if not groups:
        return None, None

    def gap(marks):
        chosen = [e[key] for g, m in zip(groups, marks) for e, c in zip(g, m) if c]
        other = [e[key] for g, m in zip(groups, marks) for e, c in zip(g, m) if not c]
        return mean(chosen) - mean(other)
    actual = [[e['candidate'] for e in g] for g in groups]
    observed = gap(actual)
    rng = random.Random(seed)
    hits = 0
    for _ in range(trials):
        marks = []
        for m in actual:
            shuffled = m[:]
            rng.shuffle(shuffled)
            marks.append(shuffled)
        if gap(marks) >= observed - 1e-12:
            hits += 1
    return observed, (hits + 1) / (trials + 1)


def summarize(entries, trials, out=print):
    judged = [e for e in entries if e['next_rank'] is not None]
    cand = [e for e in judged if e['candidate']]
    other = [e for e in judged if not e['candidate']]
    days = sorted({e['day'] for e in entries})
    out(f'対象：{len(days)}日分（{days[0] if days else "-"}〜{days[-1] if days else "-"}）の「翌日のデータもある日」')
    out(f'判定できた台 {len(entries)}件のうち、翌日に{MIN_GAMES}G以上回って比べられた台 {len(judged)}件'
        f'（候補 {len(cand)}件・候補外 {len(other)}件）')
    if not cand or not other:
        out('候補の台か候補外の台が足りず、比べられません。データがたまってから再実行してください。')
        return
    out('')
    out('■ 翌日の当たりの軽さ（同じ機種・回転数が近い台の中の順位。0〜100、偶然なら平均50）')
    out(f'  候補の台   平均 {mean(e["next_rank"] for e in cand):5.1f}')
    out(f'  候補外の台 平均 {mean(e["next_rank"] for e in other):5.1f}')
    gap, p = permutation_p(entries, 'next_rank', trials)
    if gap is not None:
        out(f'  差 {gap:+.1f}（参考：日・機種内置換 p={p:.3f}、{trials}回。自己相関に楽観的なため下のブロック検定を優先）')
    rank_days = day_gaps(entries, 'next_rank')
    if rank_days:
        m7, p7, b7 = block_flip_p(rank_days, block_days=7, trials=trials)
        ci7 = block_bootstrap_ci(rank_days, block_days=7, rounds=min(trials, 5000))
        _, p14, b14 = block_flip_p(rank_days, block_days=14, trials=trials)
        ci14 = block_bootstrap_ci(rank_days, block_days=14, rounds=min(trials, 5000))
        ci7_txt = f'、7日ブロック95%区間 [{ci7[0]:+.1f}, {ci7[1]:+.1f}]' if ci7 else ''
        ci14_txt = f'／14日ブロック p={p14:.3f}（{b14}塊）' + (f' [{ci14[0]:+.1f}, {ci14[1]:+.1f}]' if ci14 else '')
        out(f'  日等重み差（候補−適格母集団）{m7:+.1f}（7日ブロック符号反転 p={p7:.3f}、{b7}塊{ci7_txt}{ci14_txt}）')
    top_c = sum(e['next_rank'] >= 75 for e in cand) / len(cand)
    top_o = sum(e['next_rank'] >= 75 for e in other) / len(other)
    out(f'  翌日に上位4分の1へ入った割合：候補 {top_c:.0%}／候補外 {top_o:.0%}（偶然なら約25%）')
    oe = oe_ratio(entries)
    if oe['ratio'] is not None:
        oe_ci = block_bootstrap_ci(oe['day_excess'], block_days=7, rounds=min(trials, 5000))
        oe_ci_txt = f'（日等重み7日ブロック95%区間 [{(1 + oe_ci[0]):.3f}, {(1 + oe_ci[1]):.3f}]）' if oe_ci else ''
        out('')
        out('■ 全ゲームの当たり回数の比（O/E。500G未満含む全稼働台で計算し、稼働の偏りを抑える）')
        out(f'  候補の実測当たり {oe["observed"]:.0f}回 ÷ 同機種適格母集団の期待 {oe["expected"]:.1f}回 = {oe["ratio"]:.4f}{oe_ci_txt}')
    ps = plus_summary(entries)
    if ps['cand_judged'] and ps['pool_judged']:
        _, p_plus, b_plus = block_flip_p(ps['day_diffs'], block_days=7, trials=trials)
        out('')
        out('■ 記録上のプラス率（候補 vs 同じ適格母集団）と欠測感度分析')
        out(f'  候補 {ps["cand_plus"]}/{ps["cand_judged"]}件（{ps["cand_rate"]:.1%}、欠測{ps["cand_missing_rate"]:.1%}）'
            f'／母集団 {ps["pool_plus"]}/{ps["pool_judged"]}件（{ps["pool_rate"]:.1%}、欠測{ps["pool_missing_rate"]:.1%}）')
        out(f'  日等重み差 {ps["mean_diff"]:+.1%}（7日ブロック符号反転 p={p_plus:.3f}、{b_plus}塊）')
        out(f'  欠測の最悪〜最良境界（Manski）：[{ps["manski_worst"]:+.1%}, {ps["manski_best"]:+.1%}]'
            f'（共通置換：全欠測0={ps["both_zero"]:+.1%}、全欠測1={ps["both_one"]:+.1%}）')
    rho = spearman([e['index'] for e in judged], [e['next_rank'] for e in judged])
    both = [e for e in judged if e['today_rank'] is not None]
    rho_today = spearman([e['today_rank'] for e in both], [e['next_rank'] for e in both])
    out('')
    out('■ 指数と翌日の順位の関係（順位相関。0なら無関係、1なら完全に一致）')
    out(f'  翌日候補の指数（過去10日分）→ 翌日：{rho:+.3f}' if rho is not None else '  指数：計算できず')
    out(f'  比較用：今日の当たりの軽さだけ → 翌日：{rho_today:+.3f}' if rho_today is not None else '')
    scored = [e for e in judged if e['next_total'] is not None]
    if scored:
        sc = [e['next_total'] for e in scored if e['candidate']]
        so = [e['next_total'] for e in scored if not e['candidate']]
        if sc and so:
            gap_t, p_t = permutation_p(entries, 'next_total', trials)
            out('')
            out('■ 翌日の合計点（アプリの100点採点）')
            out(f'  候補 平均 {mean(sc):.1f}点（{len(sc)}件）／候補外 平均 {mean(so):.1f}点（{len(so)}件）'
                + (f'　差 {gap_t:+.1f}（p={p_t:.3f}）' if gap_t is not None else ''))
    out('')
    out('■ 内訳（翌日の当たりの軽さ、候補−候補外）')
    for label, pick in [('長町南', lambda e: e['store'] == 'nagamachiminami'),
                        ('幸町', lambda e: e['store'] == 'saiwaichou'),
                        ('データ量 少（3〜6日）', lambda e: e['confidence'] == '少'),
                        ('データ量 中（7日以上）', lambda e: e['confidence'] == '中')]:
        part = [e for e in judged if pick(e)]
        pc = [e['next_rank'] for e in part if e['candidate']]
        po = [e['next_rank'] for e in part if not e['candidate']]
        if pc and po:
            out(f'  {label}：候補 {mean(pc):.1f}（{len(pc)}件）／候補外 {mean(po):.1f}（{len(po)}件）／差 {mean(pc) - mean(po):+.1f}')
        else:
            out(f'  {label}：比べられる件数なし')
    missing = sum(1 for e in entries if e['candidate'] and e['next_rank'] is None)
    out('')
    out(f'翌日に{MIN_GAMES}G未満・データなしで比べられなかった候補：{missing}件（空き台・未取得の可能性）')
    out('注意：p値は「偶然でもこの差が出る割合」の目安。件数が少ないうちは結論を出さないこと。')
    out('注意：記録日だけで過去データを制限しています。後日取得した古い記録が混ざる場合、当時の予測精度ではありません。')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--csv', type=Path, help='旧形式の詳細CSV（現在の9列共有CSV単体は非対応）')
    parser.add_argument('--json', type=Path, help='バックアップ JSON')
    parser.add_argument('--trials', type=int, default=5000)
    parser.add_argument('--cutoff-hour', type=int, default=None,
                        help='予測日翌日の締切時刻（日本時間、例: 8）。指定時は締切前の captured_at のみ使う')
    parser.add_argument('--details', action='store_true', help='台ごとの結果を reports/ に書く')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    if args.csv:
        try:
            rows = load_csv(args.csv)
        except ValueError as error:
            parser.error(str(error))
    elif args.json:
        rows = load_json(args.json)
    else:
        rows = load_sqlite(root)
    entries = collect(rows, cutoff_hour=args.cutoff_hour)
    summarize(entries, args.trials)
    if args.details:
        output = root / 'reports/backtest-candidates.csv'
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=list(entries[0]) if entries else ['empty'])
            writer.writeheader()
            writer.writerows(entries)
        print(f'台ごとの結果：{output}')


if __name__ == '__main__':
    sys.exit(main())
