"""Read-only, chronological comparison of next-day candidate ranking ideas.

The CSV has no store and older exports have no rack. Join only uniquely
matching fingerprints to the backup; never infer an ambiguous rack from row
order. Newer exports include rack, which is used when available.

Run from database/:
    python backtest_candidate_scores.py --json backup.json --csv export.csv

All candidate features use records on or before the prediction day. The next
day's CSV score is used only as the outcome, never to choose candidates.
The captured-at sensitivity check excludes rows with no capture timestamp.
Timezone-free timestamps are treated as Japan time. Because captured_at can
reflect a later refresh, this is conservative rather than a complete replay.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean, median

from backtest_candidates import Rows, hit_rank
from core import next_day_index, percentile


def _fingerprint(row, csv_row=False, include_rack=False):
    if csv_row:
        fields = (row['日付'], row['機種名'], row['G数'], row['最大持ち球'],
                  row['B'], row['R'])
        return fields[:2] + ((row['台番号'],) if include_rack else ()) + fields[2:]
    fields = (row['day'], row['machine'], str(row.get('games') or 0),
              '' if row.get('max_hold') is None else str(row['max_hold']),
              '' if row.get('bb') is None else str(row['bb']),
              '' if row.get('rb') is None else str(row['rb']))
    return fields[:2] + ((str(row['rack']),) if include_rack else ()) + fields[2:]


def join_scores(backup, csv_path):
    with csv_path.open(encoding='utf-8-sig', newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    expected = {'日付', '機種名', '採点結果', 'G数', '最大持ち球', 'B', 'R'}
    if not csv_rows or not expected <= set(csv_rows[0]):
        raise ValueError('日付・機種名・採点結果・G数・最大持ち球・B・Rが必要です')
    include_rack = '台番号' in csv_rows[0]
    by_csv = defaultdict(list)
    by_backup = defaultdict(list)
    for row in csv_rows:
        by_csv[_fingerprint(row, True, include_rack)].append(row)
    for row in backup:
        by_backup[_fingerprint(row, include_rack=include_rack)].append(row)
    scores = {}
    for fingerprint, source in by_backup.items():
        exported = by_csv.get(fingerprint, [])
        if len(source) != 1 or len(exported) != 1:
            continue
        match = re.search(r'(\d+(?:\.\d+)?)点', exported[0]['採点結果'])
        if match:
            row = source[0]
            scores[(row['store'], row['day'], row['machine'], int(row['rack']))] = float(match[1])
    return scores, len(csv_rows)


def score_rank_history(row, by_rack, score_ranks):
    history = [r for r in by_rack[(row['store'], row['machine'], int(row['rack']))]
               if r['day'] <= row['day'] and r.get('games', 0) >= 500]
    history.sort(key=lambda r: r['day'], reverse=True)
    values = [score_ranks[key] for r in history[:10]
              if (key := (r['store'], r['day'], r['machine'], int(r['rack']))) in score_ranks]
    if len(values) < 3:
        return None
    return 50 + sum(v - 50 for v in values) / (len(values) + 5)


def evaluation_groups(backup, scores, cutoff_hour=None):
    full_data = Rows(backup)
    by_rack = defaultdict(list)
    scored_day = defaultdict(list)
    for row in backup:
        key = (row['store'], row['day'], row['machine'], int(row['rack']))
        by_rack[(row['store'], row['machine'], int(row['rack']))].append(row)
        if key in scores:
            scored_day[(row['store'], row['day'], row['machine'])].append(scores[key])
    score_ranks = {}
    for row in backup:
        key = (row['store'], row['day'], row['machine'], int(row['rack']))
        vals = scored_day[(row['store'], row['day'], row['machine'])]
        if key in scores and len(vals) >= 3:
            score_ranks[key] = 100 * percentile(scores[key], vals)

    groups = []
    by_available_day = {}
    for store, machine, day in sorted({(r['store'], r['machine'], r['day']) for r in backup}):
        tomorrow = full_data.rows((date.fromisoformat(day) + timedelta(days=1)).isoformat(),
                                  machine, store)
        if not tomorrow:
            continue
        if cutoff_hour is None:
            data = full_data
        else:
            if day not in by_available_day:
                cutoff = datetime.combine(date.fromisoformat(day) + timedelta(days=1),
                                          time(cutoff_hour),
                                          tzinfo=timezone(timedelta(hours=9)))
                available = []
                for row in backup:
                    captured = row.get('captured_at')
                    if not captured or row['day'] > day:
                        continue
                    try:
                        stamp = datetime.fromisoformat(captured)
                        if stamp.tzinfo is None:
                            stamp = stamp.replace(tzinfo=timezone(timedelta(hours=9)))
                        if stamp < cutoff:
                            available.append(row)
                    except ValueError:
                        continue
                by_available_day[day] = Rows(available)
            data = by_available_day[day]
        by_next_rack = {int(r['rack']): r for r in tomorrow}
        members = []
        for row in data.rows(day, machine, store):
            tendency = next_day_index(data, row)
            if tendency['index'] is None:
                continue
            rack = int(row['rack'])
            next_row = by_next_rack.get(rack)
            next_key = ((store, next_row['day'], machine, rack)
                        if next_row else None)
            next_score = scores.get(next_key)
            today_key = (store, day, machine, rack)
            hist_score = score_rank_history(row, by_rack, score_ranks)
            members.append(dict(rack=rack, hit=tendency['index'], days=tendency['days'],
                                today_games=row['games'],
                                score_history=hist_score,
                                last_score=score_ranks.get(today_key),
                                next_score=next_score if next_row and next_row['games'] >= 500 else None,
                                next_games=next_row['games'] if next_row else None,
                                next_hit_rank=hit_rank(next_row, tomorrow) if next_row else None))
        if len(members) >= 4:
            groups.append(dict(store=store, machine=machine, day=day,
                               count=math.ceil(len(members) * .25), members=members))
    return groups


def pick(group, method):
    def value(r):
        hit, score = r['hit'], r['score_history']
        if method in ('hit', 'hit_top1', 'hit_top10', 'hit_50', 'hit_55', 'hit_60', 'hit_days7', 'hit_55_days7',
                      'hit_today500', 'hit_today1500'):
            return hit
        if method == 'score_history':
            return score if score is not None else hit
        if method == 'blend':
            return (hit + score) / 2 if score is not None else hit
        if method == 'last_score':
            return r['last_score'] if r['last_score'] is not None else hit
        raise ValueError(method)
    count = group['count']
    if method == 'hit_top1':
        count = 1
    elif method == 'hit_top10':
        count = max(1, math.ceil(len(group['members']) * .1))
    rows = sorted(group['members'], key=lambda r: (-value(r), r['rack']))[:count]
    if method == 'hit_50':
        rows = [r for r in rows if r['hit'] > 50]
    elif method == 'hit_55':
        rows = [r for r in rows if r['hit'] >= 55]
    elif method == 'hit_60':
        rows = [r for r in rows if r['hit'] >= 60]
    elif method == 'hit_days7':
        rows = [r for r in rows if r['days'] >= 7]
    elif method == 'hit_55_days7':
        rows = [r for r in rows if r['hit'] >= 55 and r['days'] >= 7]
    elif method == 'hit_today500':
        rows = [r for r in rows if r['today_games'] >= 500]
    elif method == 'hit_today1500':
        rows = [r for r in rows if r['today_games'] >= 1500]
    return {r['rack'] for r in rows}


def evaluate(groups, method, dates, min_games=500):
    chosen, other, group_gaps = [], [], []
    eligible, missing = 0, 0
    for group in groups:
        if group['day'] not in dates:
            continue
        selection = pick(group, method)
        sc, so = [], []
        for row in group['members']:
            if row['rack'] in selection:
                eligible += 1
                if row['next_score'] is None or row['next_games'] < min_games:
                    missing += 1
                    continue
                sc.append(row['next_score'])
            elif row['next_score'] is not None and row['next_games'] >= min_games:
                so.append(row['next_score'])
        chosen.extend(sc)
        other.extend(so)
        if sc and so:
            group_gaps.append((group['day'], mean(sc) - mean(so)))
    daily = {day: mean([g for d, g in group_gaps if d == day]) for day in dates
             if any(d == day for d, _ in group_gaps)}
    rng = random.Random(2026)
    daily_values = list(daily.values())
    bootstrap = sorted(mean(rng.choice(daily_values) for _ in daily_values)
                       for _ in range(10000)) if daily_values else []
    return dict(method=method, chosen=len(chosen), other=len(other),
                selected=eligible, missing=missing,
                mean=round(mean(chosen), 2) if chosen else None,
                median=round(median(chosen), 2) if chosen else None,
                p60=round(sum(v >= 60 for v in chosen) / len(chosen), 3) if chosen else None,
                p80=round(sum(v >= 80 for v in chosen) / len(chosen), 3) if chosen else None,
                control_p60=round(sum(v >= 60 for v in other) / len(other), 3) if other else None,
                control=round(mean(other), 2) if other else None,
                raw_gap=round(mean(chosen) - mean(other), 2) if chosen and other else None,
                group_gap=round(mean(g for _, g in group_gaps), 2) if group_gaps else None,
                daily_gap=round(mean(daily.values()), 2) if daily else None,
                day_bootstrap_95=(round(bootstrap[250], 2), round(bootstrap[9749], 2))
                if bootstrap else None,
                positive_days=sum(g > 0 for g in daily.values()),
                days=len(daily))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', required=True, type=Path)
    parser.add_argument('--csv', required=True, type=Path)
    args = parser.parse_args()
    backup = json.loads(args.json.read_text(encoding='utf-8'))['records']
    scores, csv_count = join_scores(backup, args.csv)
    groups = evaluation_groups(backup, scores)
    days = sorted({g['day'] for g in groups})
    if not days:
        print('翌日の採点と照合できる候補グループがありません。')
        return
    split = days[-4] if len(days) >= 8 else days[-1]
    print(f'CSV {csv_count}行 / バックアップ {len(backup)}行 / 一意に照合した採点 {len(scores)}件')
    print(f'候補を出せる翌日付きグループ {len(groups)}件 / 予測日 {len(days)}日 / 保留開始 {split}')
    for hour in (0, 9):
        available_groups = evaluation_groups(backup, scores, cutoff_hour=hour)
        available_days = sorted({g['day'] for g in available_groups})
        print(f'取得日時が翌日{hour:02d}:00前の記録だけ：{len(available_groups)}グループ '
              f'/ {len(available_days)}日')
        print(evaluate(available_groups, 'hit', available_days))
    print('以下は取得日時を無視した探索比較で、当時の予測精度を示しません。')
    for label, selected_days in [('all', days), ('develop', [d for d in days if d < split]),
                                 ('holdout', [d for d in days if d >= split])]:
        print(label)
        for method in ('hit', 'hit_top1', 'hit_top10', 'hit_50', 'hit_55', 'hit_60', 'hit_days7', 'hit_55_days7',
                       'hit_today500', 'hit_today1500',
                       'score_history', 'blend', 'last_score'):
            print(evaluate(groups, method, selected_days))
        print('holdout min 1500G' if label == 'holdout' else '')
        if label == 'holdout':
            for method in ('hit', 'hit_top1', 'hit_top10', 'hit_50', 'hit_55', 'hit_60', 'hit_days7', 'hit_55_days7',
                           'hit_today500', 'hit_today1500',
                           'score_history', 'blend', 'last_score'):
                print(evaluate(groups, method, selected_days, min_games=1500))


if __name__ == '__main__':
    main()
