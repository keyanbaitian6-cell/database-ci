"""Read-only check: did the 翌日候補（仮） racks actually do better the next day?

For every store, machine and day D that also has data for D+1, the candidates
are chosen exactly as the app does (``provisional_next_day_candidates``), using
only records up to D. The same racks are then looked up on D+1 and compared
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
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

from core import next_day_index, percentile, provisional_next_day_candidates

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
                '現在の共有用CSVでは店舗・日付・台番号を省いているため、'
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
    return dict(store=p['store'], day=p['day'], machine=p['machine'], rack=int(p['rack']),
                games=p.get('games') or 0, bb=p.get('bb'), rb=p.get('rb'), total=None)


def hit_rank(row, day_rows):
    """Next-day 'lightness' 0-100 among same-day racks with similar games
    (half to double), the same yardstick next_day_index uses. None if the
    rack barely played or has fewer than three comparable racks."""
    if row['games'] < MIN_GAMES or row['bb'] is None or row['rb'] is None:
        return None
    peers = [r for r in day_rows if r['games'] >= MIN_GAMES and r['bb'] is not None
             and r['rb'] is not None and row['games'] / 2 <= r['games'] <= row['games'] * 2]
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


def collect(rows):
    """One entry per judged rack that also has a next-day outcome."""
    data = Rows(rows)
    out = []
    groups = sorted({(r['store'], r['machine'], r['day']) for r in rows})
    for store, machine, day in groups:
        nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        tomorrow = data.rows(nxt, machine, store)
        if not tomorrow:
            continue
        today = data.rows(day, machine, store)
        chosen = {int(c['row']['rack'])
                  for c in provisional_next_day_candidates(data, day, machine, store)['candidates']}
        by_rack = {int(r['rack']): r for r in tomorrow}
        for row in today:
            tendency = next_day_index(data, row)
            if tendency['index'] is None:
                continue
            after = by_rack.get(int(row['rack']))
            rank = hit_rank(after, tomorrow) if after else None
            out.append(dict(store=store, machine=machine, day=day, rack=int(row['rack']),
                            index=tendency['index'], days=tendency['days'],
                            confidence=tendency['confidence'], candidate=int(row['rack']) in chosen,
                            today_rank=hit_rank(row, today), next_rank=rank,
                            next_total=after.get('total') if after else None,
                            next_games=after['games'] if after else None))
    return out


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
        out(f'  差 {gap:+.1f}（偶然でもこれ以上の差が出る割合 p={p:.3f}、同じ日・同じ機種の中で印を{trials}回入れ替えて計算）')
    top_c = sum(e['next_rank'] >= 75 for e in cand) / len(cand)
    top_o = sum(e['next_rank'] >= 75 for e in other) / len(other)
    out(f'  翌日に上位4分の1へ入った割合：候補 {top_c:.0%}／候補外 {top_o:.0%}（偶然なら約25%）')
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--csv', type=Path, help='旧形式の詳細CSV（現在の7列共有CSVは非対応）')
    parser.add_argument('--json', type=Path, help='バックアップ JSON')
    parser.add_argument('--trials', type=int, default=5000)
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
    entries = collect(rows)
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
