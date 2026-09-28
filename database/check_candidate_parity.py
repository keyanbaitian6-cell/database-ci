"""Check that the PC app picks the same next-day candidates as Android/viewer.

Reads a backup JSON and the candidates written by the Android validation tool
(``dart run tool/backtest_next_day.dart --json <backup> --dump-candidates <x>``)
and recomputes them with ``core.provisional_next_day_candidates`` on the same
records (machine names normalized the same way). Read-only; prints counts only.

Run from database/:
    python check_candidate_parity.py --json <backup.json> --dart <candidates.json>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest_candidates import Rows
from core import normalize_machine_name, provisional_next_day_candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', required=True, type=Path)
    parser.add_argument('--dart', required=True, type=Path)
    args = parser.parse_args()
    merged = {}
    for row in json.loads(args.json.read_text(encoding='utf-8'))['records']:
        if not isinstance(row, dict) or 'unreadable_record' in row:
            continue
        row = dict(row, machine=normalize_machine_name(row['machine']), rack=int(row['rack']))
        key = (row['store'], row['day'], row['machine'], row['rack'])
        old = merged.get(key)
        if old is None or (row.get('games') or 0) >= (old.get('games') or 0):
            merged[key] = row
    data = Rows(merged.values())
    pc = {}
    for store, day, machine in sorted({(r['store'], r['day'], r['machine']) for r in merged.values()}):
        for c in provisional_next_day_candidates(data, day, machine, store)['candidates']:
            pc[(store, day, machine, int(c['row']['rack']))] = (c['index'], c['days'])
    dart = {(c['store'], c['day'], c['machine'], int(c['rack'])): (c['index'], c['days'])
            for c in json.loads(args.dart.read_text(encoding='utf-8'))}
    same = sum(1 for k, v in pc.items() if dart.get(k) == v)
    only_pc = sorted(set(pc) - set(dart))
    only_dart = sorted(set(dart) - set(pc))
    differ = sorted(k for k in set(pc) & set(dart) if pc[k] != dart[k])
    print(f'PC {len(pc)} / Android {len(dart)} candidates; same {same}; '
          f'PC only {len(only_pc)}; Android only {len(only_dart)}; index/days differ {len(differ)}')
    for key in (only_pc + only_dart + differ)[:10]:
        print(' ', key[:2], key[3], pc.get(key), dart.get(key))
    return 0 if same == len(pc) == len(dart) else 1


if __name__ == '__main__':
    raise SystemExit(main())
